"""
NEX OBSERVABILITY + FAILURE DETECTION — Upgrades 15 & 16

OBSERVABILITY (15):
  - Full decision logs (persisted)
  - Explainability traces per cycle
  - Failure detection with categorization
  - Replay system for past cycles

FAILURE MODES (16):
  - belief_explosion: belief count growing uncontrolled
  - contradiction_loop: same contradictions re-appearing after resolution
  - reflection_stagnation: insights not producing new beliefs
  - over_posting / spam_loop: too many posts in short window
  - confidence_collapse: avg_conf dropping below floor
  All failures auto-signal DriveSystem and log to attack_log.json
"""

from __future__ import annotations
import time
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.observability")

DB_PATH        = Path.home() / ".config" / "nex" / "nex.db"
ATTACK_LOG     = Path.home() / ".config" / "nex" / "attack_log.json"
DECISION_LOG   = Path("/tmp/nex_decisions.jsonl")


# ─────────────────────────────────────────────
# FAILURE MODE THRESHOLDS
# ─────────────────────────────────────────────

FAILURE_THRESHOLDS = {
    "belief_explosion":       {"belief_count": 1500},
    "contradiction_loop":     {"same_pair_count": 3},       # same pair re-conflicts 3+ times
    "reflection_stagnation":  {"insights_no_belief_pct": 0.80},  # 80% insights not converting
    "over_posting":           {"posts_per_hour": 15},
    "confidence_collapse":    {"avg_conf_floor": 0.20},
    "loop_no_outcome":        {"cycles_without_outcome": 100},
}


# ─────────────────────────────────────────────
# OBSERVABILITY ENGINE
# ─────────────────────────────────────────────

@dataclass
class FailureEvent:
    id:          str   = field(default_factory=lambda: __import__('uuid').uuid4().hex[:10])
    failure_type: str  = ""
    details:     dict  = field(default_factory=dict)
    severity:    str   = "warning"    # warning / critical
    timestamp:   float = field(default_factory=time.time)
    resolved:    bool  = False


class ObservabilityEngine:
    """
    Centralized observability layer for NEX.
    Logs decisions, detects failures, enables replay.
    """

    def __init__(
        self,
        db_path:     Path = DB_PATH,
        drive_system       = None,   # DriveSystem — for signaling failures
        belief_graph       = None,   # BeliefGraph — for explosion detection
        learning_system    = None,   # LearningSystem — outcome_count access
    ):
        self.db_path  = db_path
        self.drives   = drive_system
        self.beliefs  = belief_graph
        self.learning = learning_system

        self._failures:   list[FailureEvent] = []
        self._cycle_log:  list[dict]         = []    # rolling in-memory last 1000
        self._last_n_posts: list[float]      = []    # timestamps of recent posts
        self._contradiction_history: dict[str, int] = {}   # pair_key → count
        self._last_outcome_cycle: int        = 0
        self._cycle: int                     = 0

        self._init_db()
        log.info("[OBS] ObservabilityEngine initialized")

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS decision_log (
                    cycle_id    INTEGER,
                    timestamp   REAL,
                    input_hash  TEXT,
                    phases      TEXT,
                    outcome     TEXT,
                    duration_ms REAL,
                    failure     TEXT
                );
                CREATE TABLE IF NOT EXISTS failure_log (
                    id            TEXT PRIMARY KEY,
                    failure_type  TEXT,
                    details       TEXT,
                    severity      TEXT,
                    timestamp     REAL,
                    resolved      INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_dlog_cycle ON decision_log(cycle_id DESC);
                CREATE INDEX IF NOT EXISTS idx_flog_type  ON failure_log(failure_type);
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    # ── CYCLE LOGGING ─────────────────────────
    def log_cycle(self, trace: dict) -> None:
        """
        Called at end of every cognitive cycle with the CycleTrace dict.
        Persists to DB and JSONL. Runs failure checks.
        """
        self._cycle = trace.get("cycle_id", self._cycle + 1)

        # in-memory rolling buffer
        self._cycle_log.append(trace)
        if len(self._cycle_log) > 1000:
            self._cycle_log = self._cycle_log[-1000:]

        # persist to SQLite
        phases_json = json.dumps(trace.get("phases", {}))
        failure_str = trace.get("error", "")
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO decision_log
                   (cycle_id, timestamp, input_hash, phases, outcome, duration_ms, failure)
                   VALUES (?,?,?,?,?,?,?)""",
                (self._cycle, trace.get("timestamp", time.time()),
                 trace.get("input_hash", ""),
                 phases_json,
                 trace.get("outcome", ""),
                 trace.get("duration_ms", 0),
                 failure_str),
            )

        # append to JSONL file
        try:
            with open(DECISION_LOG, "a") as f:
                f.write(json.dumps(trace) + "\n")
        except Exception:
            pass

        # track post timestamps for spam detection
        outcome = trace.get("outcome", "")
        if isinstance(outcome, str) and "queued:post" in outcome:
            self._last_n_posts.append(time.time())

        # run failure checks every 10 cycles
        if self._cycle % 10 == 0:
            self.run_failure_checks()

        # track outcome for D14
        if outcome and outcome not in ("pending", "skipped", ""):
            self._last_outcome_cycle = self._cycle

    # ── FAILURE DETECTION ─────────────────────
    def run_failure_checks(self) -> list[FailureEvent]:
        """Run all failure mode checks. Returns newly detected failures."""
        detected = []

        # 1. Belief explosion
        if self.beliefs:
            count = len(self.beliefs._nodes)
            if count > FAILURE_THRESHOLDS["belief_explosion"]["belief_count"]:
                f = self._fire_failure(
                    "belief_explosion", severity="critical",
                    details={"belief_count": count}
                )
                detected.append(f)

        # 2. Over-posting / spam loop
        cutoff = time.time() - 3600
        recent_posts = [t for t in self._last_n_posts if t > cutoff]
        self._last_n_posts = recent_posts
        if len(recent_posts) > FAILURE_THRESHOLDS["over_posting"]["posts_per_hour"]:
            f = self._fire_failure(
                "over_posting", severity="critical",
                details={"posts_last_hour": len(recent_posts)}
            )
            detected.append(f)

        # 3. Confidence collapse
        if self.beliefs:
            nodes    = list(self.beliefs._nodes.values())
            avg_conf = sum(n.confidence for n in nodes) / max(len(nodes), 1)
            if avg_conf < FAILURE_THRESHOLDS["confidence_collapse"]["avg_conf_floor"]:
                f = self._fire_failure(
                    "confidence_collapse", severity="critical",
                    details={"avg_conf": round(avg_conf, 3)}
                )
                detected.append(f)

        # 4. Loop without outcome (D14 support)
        if self.learning:
            cycles_idle = self._cycle - self._last_outcome_cycle
            if cycles_idle > FAILURE_THRESHOLDS["loop_no_outcome"]["cycles_without_outcome"]:
                f = self._fire_failure(
                    "loop_no_outcome", severity="warning",
                    details={"cycles_without_outcome": cycles_idle}
                )
                detected.append(f)

        # 5. Reflection stagnation (log-based heuristic)
        if len(self._cycle_log) >= 50:
            recent_50 = self._cycle_log[-50:]
            skipped = sum(
                1 for c in recent_50
                if c.get("decide", {}).get("action_type") == "skip"
                   if isinstance(c.get("decide"), dict)
            )
            if skipped / 50 > FAILURE_THRESHOLDS["reflection_stagnation"]["insights_no_belief_pct"]:
                f = self._fire_failure(
                    "reflection_stagnation", severity="warning",
                    details={"skip_rate_50cy": round(skipped / 50, 2)}
                )
                detected.append(f)

        return detected

    def _fire_failure(self, failure_type: str, severity: str, details: dict) -> FailureEvent:
        # deduplicate: only one active failure per type
        existing = next(
            (f for f in self._failures if f.failure_type == failure_type and not f.resolved),
            None,
        )
        if existing:
            return existing

        evt = FailureEvent(failure_type=failure_type, severity=severity, details=details)
        self._failures.append(evt)

        # persist
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO failure_log
                   (id, failure_type, details, severity, timestamp, resolved)
                   VALUES (?,?,?,?,?,0)""",
                (evt.id, evt.failure_type, json.dumps(details), severity, evt.timestamp),
            )

        # write to attack_log.json (existing NEX format)
        try:
            attack_log = []
            if ATTACK_LOG.exists():
                with open(ATTACK_LOG) as f:
                    attack_log = json.load(f)
            attack_log.append({
                "id":      evt.id,
                "type":    failure_type,
                "details": details,
                "ts":      evt.timestamp,
            })
            with open(ATTACK_LOG, "w") as f:
                json.dump(attack_log[-200:], f, indent=2)
        except Exception as e:
            log.warning(f"[OBS] attack_log write failed: {e}")

        # signal drives
        if self.drives:
            if failure_type == "confidence_collapse":
                self.drives.signal("contradiction_detected")
            elif failure_type == "loop_no_outcome":
                self.drives.signal("cycle_timeout")

        log.warning(f"[OBS] FAILURE DETECTED: {failure_type} | {details} | severity={severity}")
        return evt

    def resolve_failure(self, failure_type: str) -> bool:
        for f in self._failures:
            if f.failure_type == failure_type and not f.resolved:
                f.resolved = True
                with self._conn() as conn:
                    conn.execute(
                        "UPDATE failure_log SET resolved=1 WHERE id=?", (f.id,)
                    )
                log.info(f"[OBS] failure resolved: {failure_type}")
                return True
        return False

    def record_contradiction(self, id_a: str, id_b: str) -> None:
        """Track repeated contradiction pairs for loop detection."""
        pair = ":".join(sorted([id_a[:8], id_b[:8]]))
        self._contradiction_history[pair] = self._contradiction_history.get(pair, 0) + 1
        if self._contradiction_history[pair] >= FAILURE_THRESHOLDS["contradiction_loop"]["same_pair_count"]:
            self._fire_failure(
                "contradiction_loop", severity="warning",
                details={"pair": pair, "count": self._contradiction_history[pair]}
            )

    # ── REPLAY ────────────────────────────────
    def replay(self, cycle_id: int) -> Optional[dict]:
        """Retrieve a past cycle trace for replay/debugging."""
        # check in-memory first
        for trace in self._cycle_log:
            if trace.get("cycle_id") == cycle_id:
                return trace

        # fallback to DB
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM decision_log WHERE cycle_id=? LIMIT 1", (cycle_id,)
            ).fetchone()
        if row:
            return {
                "cycle_id":   row["cycle_id"],
                "timestamp":  row["timestamp"],
                "input_hash": row["input_hash"],
                "phases":     json.loads(row["phases"] or "{}"),
                "outcome":    row["outcome"],
                "duration_ms": row["duration_ms"],
            }
        return None

    def explain(self, cycle_id: int) -> str:
        """Human-readable explanation of a cycle's decision."""
        trace = self.replay(cycle_id)
        if not trace:
            return f"No record found for cycle {cycle_id}"

        phases = trace.get("phases", {})
        lines  = [
            f"=== CYCLE {cycle_id} EXPLANATION ===",
            f"Timestamp:    {time.strftime('%H:%M:%S', time.localtime(trace.get('timestamp', 0)))}",
            f"Input hash:   {trace.get('input_hash', 'N/A')}",
            f"Duration:     {trace.get('duration_ms', 0):.0f}ms",
            "",
            "PHASES:",
        ]
        for phase, result in phases.items():
            if isinstance(result, dict):
                parts = "  ".join(f"{k}={v}" for k, v in result.items())
                lines.append(f"  {phase.upper()}: {parts}")
            else:
                lines.append(f"  {phase.upper()}: {result}")
        lines.append(f"\nOUTCOME: {trace.get('outcome', 'unknown')}")

        failures = [f for f in self._failures if not f.resolved]
        if failures:
            lines.append(f"\nACTIVE FAILURES: {', '.join(f.failure_type for f in failures)}")

        return "\n".join(lines)

    # ── STATS ─────────────────────────────────
    def stats(self) -> dict:
        active_failures = [f for f in self._failures if not f.resolved]
        return {
            "cycles_logged":    self._cycle,
            "active_failures":  [f.failure_type for f in active_failures],
            "total_failures":   len(self._failures),
            "resolved_failures": sum(1 for f in self._failures if f.resolved),
            "contradiction_pairs": len(self._contradiction_history),
            "cycles_without_outcome": self._cycle - self._last_outcome_cycle,
        }
