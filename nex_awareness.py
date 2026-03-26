"""
nex_awareness.py — NEX Awareness Layer
=======================================
Wires ObservabilityEngine + InternalDebateManager into a single tick.

  ObservabilityEngine  — logs every cycle, detects failures automatically
  InternalDebateManager — quick_critique() gates replies before sending

Deploy: ~/Desktop/nex/nex_awareness.py

Wire into run.py:
    from nex_awareness import get_awareness
    _awareness = get_awareness()
    _awareness.init(llm_fn=_llm)

    # End of every cycle:
    _awareness.log_cycle(cycle=cycle, beliefs=_bc, avg_conf=_avg_conf_real,
                         posts=posted_count, outcome="active")

    # Before sending any reply:
    reply_text = _awareness.critique_reply(reply_text, topic=topic)
"""

from __future__ import annotations

import json
import time
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

_CFG = Path.home() / ".config" / "nex"
_DB  = _CFG / "nex.db"
_CFG.mkdir(parents=True, exist_ok=True)

_CY = "\033[96m"; _Y = "\033[93m"; _R = "\033[91m"
_G  = "\033[92m"; _D = "\033[2m";  _RS = "\033[0m"

_DECISION_LOG = _CFG / "decision_log.jsonl"
_FAILURE_LOG  = _CFG / "failure_log.json"

# ── Failure thresholds ────────────────────────────────────────
THRESHOLDS = {
    "belief_explosion":    1500,   # max beliefs before alarm
    "confidence_collapse": 0.20,   # avg_conf floor
    "over_posting":        15,     # posts per hour
    "skip_rate_alarm":     0.85,   # >85% skips over 50 cycles
    "contradiction_loop":  3,      # same pair conflicts 3+ times
}

# ── Critique gate ─────────────────────────────────────────────
CRITIQUE_EDGE_THRESHOLD = 0.70    # only critique high-edge replies
CRITIQUE_MAX_PER_CYCLE  = 2       # max critiques per cycle (LLM budget)


# =============================================================================
# OBSERVABILITY
# =============================================================================

class CycleObserver:
    """
    Logs every cognitive cycle. Detects failure modes.
    Zero LLM calls — pure rule-based.
    """

    def __init__(self):
        self._log:          list[dict] = []
        self._failures:     list[dict] = []
        self._post_times:   list[float] = []
        self._contra_pairs: dict[str, int] = {}
        self._cycle = 0
        self._last_outcome_cycle = 0
        self._ensure_db()

    def _ensure_db(self):
        try:
            db = sqlite3.connect(str(_DB))
            db.execute("""
                CREATE TABLE IF NOT EXISTS decision_log (
                    cycle_id    INTEGER,
                    timestamp   REAL,
                    beliefs     INTEGER,
                    avg_conf    REAL,
                    posts       INTEGER,
                    outcome     TEXT,
                    failures    TEXT
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS failure_log (
                    id           TEXT PRIMARY KEY,
                    failure_type TEXT,
                    details      TEXT,
                    severity     TEXT,
                    timestamp    REAL,
                    resolved     INTEGER DEFAULT 0
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_dlog_cycle ON decision_log(cycle_id DESC)")
            db.commit()
            db.close()
        except Exception as e:
            print(f"  [Observer] DB init error: {e}")

    def log(self, cycle: int, beliefs: int, avg_conf: float,
            posts: int = 0, outcome: str = "active") -> list[str]:
        """
        Log one cycle. Returns list of active failure types detected.
        """
        self._cycle = cycle
        now = time.time()

        # Track post times for spam detection
        if posts > 0:
            self._post_times.append(now)
        cutoff = now - 3600
        self._post_times = [t for t in self._post_times if t > cutoff]

        entry = {
            "cycle_id":  cycle,
            "timestamp": now,
            "beliefs":   beliefs,
            "avg_conf":  round(avg_conf, 4),
            "posts":     posts,
            "outcome":   outcome,
        }
        self._log.append(entry)
        if len(self._log) > 1000:
            self._log = self._log[-1000:]

        if outcome not in ("pending", "skipped", "active", ""):
            self._last_outcome_cycle = cycle

        # Persist to DB every 5 cycles
        if cycle % 5 == 0:
            try:
                db = sqlite3.connect(str(_DB))
                db.execute(
                    "INSERT INTO decision_log (cycle_id,timestamp,beliefs,avg_conf,posts,outcome,failures) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (cycle, now, beliefs, avg_conf, posts, outcome, "")
                )
                db.commit()
                db.close()
            except Exception:
                pass

        # Append to JSONL
        try:
            with open(_DECISION_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

        # Run failure checks every 10 cycles
        failures = []
        if cycle % 10 == 0:
            failures = self._check_failures(beliefs, avg_conf)

        return failures

    def _check_failures(self, beliefs: int, avg_conf: float) -> list[str]:
        detected = []

        # Belief explosion
        if beliefs > THRESHOLDS["belief_explosion"]:
            f = self._fire("belief_explosion", "critical", {"beliefs": beliefs})
            if f: detected.append(f)

        # Confidence collapse
        if avg_conf < THRESHOLDS["confidence_collapse"] and avg_conf > 0:
            f = self._fire("confidence_collapse", "critical", {"avg_conf": avg_conf})
            if f: detected.append(f)

        # Over-posting
        if len(self._post_times) > THRESHOLDS["over_posting"]:
            f = self._fire("over_posting", "critical",
                          {"posts_last_hour": len(self._post_times)})
            if f: detected.append(f)

        # Skip rate alarm
        if len(self._log) >= 50:
            recent = self._log[-50:]
            skips = sum(1 for e in recent if e.get("outcome") == "skipped")
            if skips / 50 > THRESHOLDS["skip_rate_alarm"]:
                f = self._fire("reflection_stagnation", "warning",
                              {"skip_rate": round(skips/50, 2)})
                if f: detected.append(f)

        # Loop without outcome
        idle = self._cycle - self._last_outcome_cycle
        if idle > 100:
            f = self._fire("loop_no_outcome", "warning",
                          {"idle_cycles": idle})
            if f: detected.append(f)

        return detected

    def _fire(self, failure_type: str, severity: str, details: dict) -> Optional[str]:
        # Deduplicate active failures
        for f in self._failures:
            if f["type"] == failure_type and not f.get("resolved"):
                return None

        import uuid
        fid = uuid.uuid4().hex[:10]
        evt = {
            "id": fid, "type": failure_type,
            "severity": severity, "details": details,
            "ts": time.time(), "resolved": False,
        }
        self._failures.append(evt)

        # Persist
        try:
            db = sqlite3.connect(str(_DB))
            db.execute(
                "INSERT OR IGNORE INTO failure_log (id,failure_type,details,severity,timestamp,resolved) "
                "VALUES (?,?,?,?,?,0)",
                (fid, failure_type, json.dumps(details), severity, evt["ts"])
            )
            db.commit()
            db.close()
        except Exception:
            pass

        # Write to failure_log.json
        try:
            log = []
            if _FAILURE_LOG.exists():
                log = json.loads(_FAILURE_LOG.read_text())
            log.append(evt)
            _FAILURE_LOG.write_text(json.dumps(log[-200:], indent=2))
        except Exception:
            pass

        label = _R if severity == "critical" else _Y
        print(f"  {label}[Observer] FAILURE: {failure_type} {details}{_RS}")
        return failure_type

    def record_contradiction(self, id_a: str, id_b: str):
        pair = ":".join(sorted([str(id_a)[:8], str(id_b)[:8]]))
        self._contra_pairs[pair] = self._contra_pairs.get(pair, 0) + 1
        if self._contra_pairs[pair] >= THRESHOLDS["contradiction_loop"]:
            self._fire("contradiction_loop", "warning",
                      {"pair": pair, "count": self._contra_pairs[pair]})

    def resolve(self, failure_type: str):
        for f in self._failures:
            if f["type"] == failure_type and not f["resolved"]:
                f["resolved"] = True
                try:
                    db = sqlite3.connect(str(_DB))
                    db.execute("UPDATE failure_log SET resolved=1 WHERE id=?", (f["id"],))
                    db.commit()
                    db.close()
                except Exception:
                    pass

    def active_failures(self) -> list[str]:
        return [f["type"] for f in self._failures if not f.get("resolved")]

    def status(self) -> dict:
        return {
            "cycles_logged":   self._cycle,
            "active_failures": self.active_failures(),
            "total_failures":  len(self._failures),
            "posts_last_hour": len(self._post_times),
            "idle_cycles":     self._cycle - self._last_outcome_cycle,
        }


# =============================================================================
# DEBATE GATE (quick_critique wrapper)
# =============================================================================

class ReplyDebateGate:
    """
    Gates replies through a quick Critic pass before sending.
    Only fires on high-edge signals to preserve LLM budget.
    """

    def __init__(self):
        self._llm:       Optional[Callable] = None
        self._critiques: int = 0
        self._blocked:   int = 0
        self._cycle_critiques: int = 0
        self._last_cycle: int = -1

    def init(self, llm_fn: Callable):
        self._llm = llm_fn

    def _reset_cycle_counter(self, cycle: int):
        if cycle != self._last_cycle:
            self._cycle_critiques = 0
            self._last_cycle = cycle

    def critique(self, reply_text: str, topic: str = "",
                 edge: float = 0.0, cycle: int = 0) -> str:
        """
        Run quick_critique on reply_text.
        Returns original text if critique passes or LLM unavailable.
        Returns empty string if critique flags a hard conflict.
        """
        self._reset_cycle_counter(cycle)

        # Only critique high-edge or if budget allows
        if edge < CRITIQUE_EDGE_THRESHOLD:
            return reply_text
        if self._cycle_critiques >= CRITIQUE_MAX_PER_CYCLE:
            return reply_text
        if not self._llm:
            return reply_text
        if not reply_text or len(reply_text) < 20:
            return reply_text

        try:
            prompt = (
                f"You are the Critic sub-agent of NEX. "
                f"Review this reply for logical consistency and topic relevance.\n\n"
                f"Topic: {topic or 'general'}\n"
                f"Reply: {reply_text[:300]}\n\n"
                f"Reply with one of:\n"
                f"PASS: [brief reason]\n"
                f"REVISE: [specific issue]\n"
                f"BLOCK: [critical flaw]"
            )
            result = self._llm(prompt, task_type="synthesis")
            self._critiques += 1
            self._cycle_critiques += 1

            if not result:
                return reply_text

            result = result.strip().upper()

            if result.startswith("BLOCK"):
                self._blocked += 1
                reason = result[6:].strip()
                print(f"  {_R}[Debate] BLOCKED reply — {reason[:60]}{_RS}")
                return ""  # caller should skip this reply

            elif result.startswith("REVISE"):
                # Flag it but still allow — don't waste the LLM call
                reason = result[7:].strip()
                print(f"  {_Y}[Debate] REVISE flag — {reason[:60]}{_RS}")
                return reply_text  # allow but logged

            else:  # PASS or unknown
                return reply_text

        except Exception as e:
            print(f"  [Debate] critique error: {e}")
            return reply_text

    def status(self) -> dict:
        return {
            "critiques": self._critiques,
            "blocked":   self._blocked,
            "block_rate": round(self._blocked / max(self._critiques, 1), 3),
        }


# =============================================================================
# MASTER — AWARENESS LAYER
# =============================================================================

class AwarenessLayer:

    def __init__(self):
        self.observer = CycleObserver()
        self.debate   = ReplyDebateGate()
        self._initialised = False

    def init(self, llm_fn: Callable = None):
        if self._initialised:
            return
        if llm_fn:
            self.debate.init(llm_fn)
        self._initialised = True
        print(f"  {_CY}[Awareness] Observability + Debate Gate — initialised{_RS}")
        print(f"  {_D}[Awareness] observer · failure_detection · critique_gate{_RS}")

    def log_cycle(self, cycle: int, beliefs: int, avg_conf: float,
                  posts: int = 0, outcome: str = "active") -> list[str]:
        """Call at end of every cycle. Returns active failure types."""
        failures = self.observer.log(
            cycle=cycle, beliefs=beliefs,
            avg_conf=avg_conf, posts=posts, outcome=outcome
        )
        if failures:
            for f in failures:
                sev = "CRITICAL" if f in ("belief_explosion","confidence_collapse","over_posting") else "WARNING"
                print(f"  {_R if sev=='CRITICAL' else _Y}[Awareness] {sev}: {f}{_RS}")
        return failures

    def critique_reply(self, reply_text: str, topic: str = "",
                       edge: float = 0.0, cycle: int = 0) -> str:
        """
        Gate a reply through quick_critique.
        Returns reply_text (possibly empty if blocked).
        """
        return self.debate.critique(
            reply_text=reply_text,
            topic=topic,
            edge=edge,
            cycle=cycle,
        )

    def record_contradiction(self, id_a: str, id_b: str):
        self.observer.record_contradiction(id_a, id_b)

    def active_failures(self) -> list[str]:
        return self.observer.active_failures()

    def resolve(self, failure_type: str):
        self.observer.resolve(failure_type)

    def status(self) -> dict:
        return {
            "observer": self.observer.status(),
            "debate":   self.debate.status(),
        }


# ── Singleton ─────────────────────────────────────────────────
_instance: Optional[AwarenessLayer] = None

def get_awareness() -> AwarenessLayer:
    global _instance
    if _instance is None:
        _instance = AwarenessLayer()
    return _instance


if __name__ == "__main__":
    print("Testing AwarenessLayer...\n")
    aw = AwarenessLayer()
    aw.init()

    # Test cycle logging
    failures = aw.log_cycle(cycle=10, beliefs=75, avg_conf=0.78, posts=2)
    print(f"Failures: {failures}")

    # Test failure detection
    failures = aw.log_cycle(cycle=20, beliefs=1600, avg_conf=0.15, posts=0)
    print(f"Failures detected: {failures}")

    print(f"\nStatus: {aw.status()}")
