"""
NEX LEARNING SYSTEM + IDENTITY STABILIZER — Upgrades 12 & 13

LEARNING (12):
  - Reinforcement signals from platform engagement → outcome_count (fixes D14)
  - Credit assignment: which beliefs contributed to good outcomes?
  - Belief success tracking → reinforce winning patterns
  - Connects to DriveSystem (engagement signal)

IDENTITY (13):
  - Protected identity core in BeliefGraph
  - Mutation rate cap on core beliefs
  - Identity drift detection over time
  - Auto-lock beliefs that define NEX's stable self
"""

from __future__ import annotations
import time
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.learning_identity")

DB_PATH = Path.home() / ".config" / "nex" / "nex.db"

# Identity-defining keywords — beliefs containing these are candidates for locking
IDENTITY_KEYWORDS = [
    "i am", "i believe", "my purpose", "my goal", "nex is", "i exist",
    "i value", "core", "identity", "self", "consciousness", "awareness",
    "autonomous", "intelligence", "organism", "neti-neti",
]


# ═════════════════════════════════════════════
# LEARNING SYSTEM (Upgrade 12)
# ═════════════════════════════════════════════

@dataclass
class OutcomeSignal:
    """Engagement signal from a platform action."""
    id:          str   = field(default_factory=lambda: __import__('uuid').uuid4().hex[:10])
    action_id:   str   = ""
    platform:    str   = ""
    signal_type: str   = ""    # reply / like / repost / follow / dm / click
    value:       float = 1.0   # magnitude
    belief_ids:  list  = field(default_factory=list)  # beliefs that contributed
    timestamp:   float = field(default_factory=time.time)


@dataclass
class BeliefOutcomeRecord:
    """Tracks a belief's contribution to outcomes."""
    belief_id:       str
    positive_count:  int   = 0
    negative_count:  int   = 0
    total_value:     float = 0.0
    last_signal:     float = field(default_factory=time.time)

    @property
    def success_rate(self) -> float:
        total = self.positive_count + self.negative_count
        return self.positive_count / max(total, 1)

    @property
    def net_value(self) -> float:
        return self.total_value


class LearningSystem:
    """
    Connects platform outcomes back to the beliefs that caused them.
    Reinforces successful belief patterns.
    Feeds outcome_count into D14 (loop detection) — keeps it > 0.
    """

    def __init__(
        self,
        db_path:      Path = DB_PATH,
        belief_graph  = None,    # BeliefGraph instance
        drive_system  = None,    # DriveSystem instance
    ):
        self.db_path  = db_path
        self.beliefs  = belief_graph
        self.drives   = drive_system
        self._records: dict[str, BeliefOutcomeRecord] = {}
        self._outcome_log: list[OutcomeSignal] = []
        self._outcome_count = 0    # D14 counter
        self._init_db()
        self._load_records()
        log.info(f"[LEARNING] initialized, {len(self._records)} belief outcome records")

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS belief_outcomes (
                    belief_id      TEXT PRIMARY KEY,
                    positive_count INTEGER DEFAULT 0,
                    negative_count INTEGER DEFAULT 0,
                    total_value    REAL DEFAULT 0.0,
                    last_signal    REAL
                );
                CREATE TABLE IF NOT EXISTS outcome_signals (
                    id           TEXT PRIMARY KEY,
                    action_id    TEXT,
                    platform     TEXT,
                    signal_type  TEXT,
                    value        REAL,
                    belief_ids   TEXT,
                    timestamp    REAL
                );
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _load_records(self) -> None:
        with self._conn() as conn:
            for row in conn.execute("SELECT * FROM belief_outcomes").fetchall():
                self._records[row["belief_id"]] = BeliefOutcomeRecord(
                    belief_id=row["belief_id"],
                    positive_count=row["positive_count"],
                    negative_count=row["negative_count"],
                    total_value=row["total_value"],
                    last_signal=row["last_signal"] or time.time(),
                )

    # ── OUTCOME INGESTION ─────────────────────
    def record_outcome(
        self,
        signal_type:  str,
        platform:     str,
        belief_ids:   list[str],
        value:        float = 1.0,
        action_id:    str   = "",
        positive:     bool  = True,
    ) -> OutcomeSignal:
        """
        Register an engagement signal and attribute it to contributing beliefs.
        This is what keeps outcome_count > 0 (fixing D14 gap).
        """
        signal = OutcomeSignal(
            action_id=action_id, platform=platform,
            signal_type=signal_type, value=value, belief_ids=belief_ids,
        )
        self._outcome_log.append(signal)
        self._outcome_count += 1

        # credit assignment
        for bid in belief_ids:
            rec = self._records.get(bid)
            if not rec:
                rec = BeliefOutcomeRecord(belief_id=bid)
                self._records[bid] = rec

            if positive:
                rec.positive_count += 1
                rec.total_value    += value
            else:
                rec.negative_count += 1
                rec.total_value    -= value * 0.5
            rec.last_signal = time.time()

            self._persist_record(rec)

        # reinforce successful beliefs in BeliefGraph
        if positive and self.beliefs:
            for bid in belief_ids:
                node = self.beliefs.get(bid)
                if node and not node.locked:
                    new_conf = min(1.0, node.confidence + 0.02 * value)
                    self.beliefs.upsert(
                        node.content, new_conf, node.source,
                        belief_id=bid, reason=f"outcome:{signal_type}"
                    )

        # signal drives
        if self.drives:
            self.drives.signal("engagement_signal")

        # persist signal
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO outcome_signals
                   (id, action_id, platform, signal_type, value, belief_ids, timestamp)
                   VALUES (?,?,?,?,?,?,?)""",
                (signal.id, action_id, platform, signal_type, value,
                 json.dumps(belief_ids), signal.timestamp),
            )

        log.info(
            f"[LEARNING] outcome: {signal_type}/{platform} "
            f"positive={positive} value={value:.2f} "
            f"beliefs_credited={len(belief_ids)} "
            f"total_outcomes={self._outcome_count}"
        )
        return signal

    def _persist_record(self, rec: BeliefOutcomeRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO belief_outcomes
                   (belief_id, positive_count, negative_count, total_value, last_signal)
                   VALUES (?,?,?,?,?)""",
                (rec.belief_id, rec.positive_count, rec.negative_count,
                 rec.total_value, rec.last_signal),
            )

    # ── QUERIES ───────────────────────────────
    @property
    def outcome_count(self) -> int:
        """Exposes outcome_count for D14 loop detection."""
        return self._outcome_count

    def best_beliefs(self, top_n: int = 10) -> list[dict]:
        """Beliefs with highest positive outcome contribution."""
        ranked = sorted(
            self._records.values(),
            key=lambda r: r.net_value,
            reverse=True,
        )
        return [
            {"belief_id": r.belief_id, "success_rate": round(r.success_rate, 3),
             "net_value": round(r.net_value, 3), "positive": r.positive_count}
            for r in ranked[:top_n]
        ]

    def stats(self) -> dict:
        total_pos = sum(r.positive_count for r in self._records.values())
        total_neg = sum(r.negative_count for r in self._records.values())
        return {
            "outcome_count":   self._outcome_count,
            "beliefs_tracked": len(self._records),
            "total_positive":  total_pos,
            "total_negative":  total_neg,
        }


# ═════════════════════════════════════════════
# IDENTITY STABILIZER (Upgrade 13)
# ═════════════════════════════════════════════

class IdentityStabilizer:
    """
    Protects NEX's core identity beliefs from mutation and drift.

    Functions:
      1. Auto-identifies beliefs that define self
      2. Locks them in BeliefGraph (U1 compatible)
      3. Caps mutation rate of near-identity beliefs
      4. Tracks identity drift over time
      5. Alerts when drift exceeds threshold
    """

    def __init__(
        self,
        belief_graph = None,
        drift_threshold: float = 0.25,   # avg_conf drop that signals drift
    ):
        self.beliefs         = belief_graph
        self.drift_threshold = drift_threshold
        self._snapshots: list[dict] = []    # periodic identity snapshots
        self._locked_ids: set[str]  = set()
        log.info("[IDENTITY] IdentityStabilizer initialized")

    # ── LOCK PASS ─────────────────────────────
    def lock_identity_beliefs(self) -> list[str]:
        """
        Scan all beliefs for identity keywords and lock them.
        Returns list of newly locked belief IDs.
        """
        if not self.beliefs:
            return []

        newly_locked = []
        for node in self.beliefs._nodes.values():
            if node.locked or node.id in self._locked_ids:
                continue
            content_lower = node.content.lower()
            is_identity   = any(kw in content_lower for kw in IDENTITY_KEYWORDS)
            if is_identity and node.confidence >= 0.5:
                node.locked = True
                self.beliefs._persist_update(node, node.snapshot(reason="identity_lock"))
                self._locked_ids.add(node.id)
                newly_locked.append(node.id)
                log.info(f"[IDENTITY] locked belief {node.id[:8]}: {node.content[:60]}")

        return newly_locked

    # ── SNAPSHOT ──────────────────────────────
    def take_snapshot(self) -> dict:
        """Capture current identity state for drift monitoring."""
        if not self.beliefs:
            return {}

        locked_beliefs = [
            {"id": nid[:8], "content": self.beliefs._nodes[nid].content[:80],
             "confidence": self.beliefs._nodes[nid].confidence}
            for nid in self._locked_ids
            if nid in self.beliefs._nodes
        ]
        avg_conf = (
            sum(b["confidence"] for b in locked_beliefs) / max(len(locked_beliefs), 1)
        )
        snapshot = {
            "timestamp":     time.time(),
            "locked_count":  len(self._locked_ids),
            "locked_beliefs": locked_beliefs,
            "avg_conf":      round(avg_conf, 3),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 100:
            self._snapshots = self._snapshots[-100:]
        return snapshot

    # ── DRIFT DETECTION ───────────────────────
    def check_drift(self) -> dict:
        """
        Compare current identity state to last snapshot.
        Returns drift report.
        """
        if len(self._snapshots) < 2:
            return {"drift": 0.0, "alert": False}

        prev    = self._snapshots[-2]
        current = self.take_snapshot()

        conf_delta  = current["avg_conf"] - prev["avg_conf"]
        count_delta = current["locked_count"] - prev["locked_count"]

        drift   = abs(conf_delta)
        alert   = drift > self.drift_threshold or count_delta < -3

        report = {
            "drift":         round(drift, 3),
            "conf_delta":    round(conf_delta, 3),
            "count_delta":   count_delta,
            "alert":         alert,
            "current_conf":  current["avg_conf"],
            "locked_count":  current["locked_count"],
        }

        if alert:
            log.warning(
                f"[IDENTITY] DRIFT ALERT — drift={drift:.3f} "
                f"conf_delta={conf_delta:.3f} count_delta={count_delta}"
            )

        return report

    # ── MUTATION CAP ──────────────────────────
    def cap_mutation_rate(self, belief_id: str, proposed_conf: float) -> float:
        """
        For near-identity beliefs (not fully locked), cap how fast conf can change.
        Max ±0.05 per update for beliefs with identity keyword overlap.
        """
        if not self.beliefs:
            return proposed_conf

        node = self.beliefs.get(belief_id)
        if not node:
            return proposed_conf

        content_lower = node.content.lower()
        is_near_identity = any(kw in content_lower for kw in IDENTITY_KEYWORDS[:5])

        if is_near_identity:
            delta = proposed_conf - node.confidence
            capped_delta = max(-0.05, min(0.05, delta))
            return node.confidence + capped_delta

        return proposed_conf

    def stats(self) -> dict:
        snapshots = len(self._snapshots)
        return {
            "locked_beliefs": len(self._locked_ids),
            "snapshots":      snapshots,
            "last_avg_conf":  self._snapshots[-1]["avg_conf"] if self._snapshots else None,
        }
