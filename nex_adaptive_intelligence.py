"""
nex_adaptive_intelligence.py — NEX v4 Stabilization & Adaptive Intelligence
=============================================================================
7 systems. Single tick() call per cycle.

  NEW:
    1. AdaptiveRetryEngine      — multi-strategy failure recovery
    3. ResolutionClosureSystem  — contradiction → stable belief update
    7. EnergyBudgetSystem       — per-operation cost gating

  EXTENDED (wraps/replaces existing partial coverage):
    2. QueuePressureRegulator   — extends nex_cognitive_pressure overload logic
    4. SelectiveCompressionEngine — replaces blind MemoryCompressionV2 logic
    5. FailureMemorySystem      — persistent version of v72 FailureMemoryPenalty
    6. AttentionReinforcementMemory — wires nex_attention decay per-cycle

Deploy: ~/Desktop/nex/nex_adaptive_intelligence.py

Wire into run.py (after existing v3 tick block):
    from nex_adaptive_intelligence import get_adaptive_intelligence
    _ai = get_adaptive_intelligence()
    _ai.init()

    # each cycle:
    _ai.tick(cycle=cycle, llm_fn=_llm, log_fn=nex_log)

    # before any heavy operation:
    if _ai.can_afford("deep_dive"):
        ...
    elif _ai.can_afford("synthesis"):
        ...

    # after a task fails:
    _ai.record_failure(topic="memory", strategy="abstraction", reason="no beliefs found")

    # after contradiction resolves:
    _ai.on_resolution(topic="memory", belief_content="...", parent_ids=[12,34])
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

_CFG = Path.home() / ".config" / "nex"
_DB  = _CFG / "nex.db"
_CFG.mkdir(parents=True, exist_ok=True)

_G  = "\033[92m"; _Y = "\033[93m"; _R = "\033[91m"
_CY = "\033[96m"; _D = "\033[2m";  _RS = "\033[0m"

_FAILURE_LOG_PATH   = _CFG / "failure_log.json"
_ATTN_STATE_PATH    = _CFG / "attention_state.json"
_ENERGY_STATE_PATH  = _CFG / "energy_budget.json"


def _db():
    c = sqlite3.connect(str(_DB), timeout=10)
    c.row_factory = sqlite3.Row
    return c


# =============================================================================
# SYSTEM 1 — ADAPTIVE RETRY ENGINE
# =============================================================================

_RETRY_STRATEGIES = ["abstraction", "decomposition", "context_split", "unresolved"]

class AdaptiveRetryEngine:
    """
    On task failure: cycle through abstraction → decomposition →
    context_split → mark unresolved. Prevents dead-end termination.
    """

    def __init__(self):
        # topic → list of (strategy, result, cycle, reason)
        self._attempts: dict[str, list[dict]] = defaultdict(list)
        self.total_retried  = 0
        self.total_resolved = 0

    def next_strategy(self, topic: str) -> str:
        """Return the next strategy to try for this topic."""
        past = [a["strategy"] for a in self._attempts.get(topic, [])]
        for s in _RETRY_STRATEGIES:
            if s not in past:
                return s
        return "unresolved"

    def record_attempt(self, topic: str, strategy: str,
                       success: bool, reason: str = "", cycle: int = 0):
        self._attempts[topic].append({
            "strategy": strategy,
            "success":  success,
            "reason":   reason,
            "cycle":    cycle,
            "ts":       datetime.now().isoformat(),
        })
        # Keep last 10 per topic
        if len(self._attempts[topic]) > 10:
            self._attempts[topic] = self._attempts[topic][-10:]
        if not success:
            self.total_retried += 1
        else:
            self.total_resolved += 1

    def should_skip(self, topic: str, strategy: str) -> bool:
        """True if this strategy already failed for this topic recently."""
        for a in self._attempts.get(topic, []):
            if a["strategy"] == strategy and not a["success"]:
                return True
        return False

    def get_resolution_prompt(self, topic: str, strategy: str,
                               beliefs: list[str]) -> str:
        """Build a strategy-specific LLM prompt."""
        sample = "\n".join(f"- {b[:120]}" for b in beliefs[:6])
        if strategy == "abstraction":
            return (
                f"Zoom out from '{topic}'. What higher-level principle "
                f"unifies these beliefs?\n{sample}\n\n"
                f"Reply with one abstracted belief sentence."
            )
        elif strategy == "decomposition":
            return (
                f"Break '{topic}' into sub-components. Which sub-topic "
                f"is most tractable?\n{sample}\n\n"
                f"Reply: SUB_TOPIC: one sentence belief about that sub-topic."
            )
        elif strategy == "context_split":
            return (
                f"These beliefs about '{topic}' may all be true in different contexts.\n"
                f"{sample}\n\n"
                f"Identify two contexts where different beliefs apply. "
                f"Reply: CONTEXT_A: ... | CONTEXT_B: ..."
            )
        else:
            return f"Mark '{topic}' as unresolved. Reason: insufficient evidence."

    def run(self, topic: str, beliefs: list[str],
            llm_fn=None, cycle: int = 0, log_fn=None) -> dict:
        """
        Attempt resolution using next available strategy.
        Returns dict with strategy, result, success.
        """
        strategy = self.next_strategy(topic)
        if strategy == "unresolved":
            self.record_attempt(topic, "unresolved", False, "all strategies exhausted", cycle)
            if log_fn:
                log_fn("retry", f"[Retry] '{topic}' → UNRESOLVED (all strategies exhausted)")
            return {"strategy": "unresolved", "success": False, "result": None}

        if not llm_fn:
            return {"strategy": strategy, "success": False, "result": None}

        prompt   = self.get_resolution_prompt(topic, strategy, beliefs)
        try:
            result   = llm_fn(prompt, task_type="synthesis")
            success  = bool(result and len(result.strip()) > 20)
            self.record_attempt(topic, strategy, success, result[:80] if result else "", cycle)
            if log_fn:
                status = "✓" if success else "✗"
                log_fn("retry", f"[Retry] '{topic}' {strategy} {status}")
            print(f"  {_CY}[Retry] '{topic[:40]}' → {strategy} {'✓' if success else '✗'}{_RS}")
            return {"strategy": strategy, "success": success, "result": result}
        except Exception as e:
            self.record_attempt(topic, strategy, False, str(e), cycle)
            return {"strategy": strategy, "success": False, "result": None}

    def status(self) -> dict:
        return {
            "total_retried":  self.total_retried,
            "total_resolved": self.total_resolved,
            "active_topics":  len(self._attempts),
        }


# =============================================================================
# SYSTEM 2 — QUEUE PRESSURE REGULATOR
# Extends nex_cognitive_pressure with intake throttling + attention decay
# =============================================================================

class QueuePressureRegulator:
    """
    Monitors tension queue size. When overloaded:
      - reduces intake rate (returned as signal to caller)
      - raises priority threshold (returned as min_confidence floor)
      - accelerates decay for low-attention topics
    """
    QUEUE_SOFT_LIMIT  = 20
    QUEUE_HARD_LIMIT  = 35
    DECAY_ACCEL_TOPIC = 0.02   # extra confidence decay for ignored topics
    INTERVAL          = 60

    def __init__(self):
        self.last_run        = 0.0
        self.intake_rate     = 1.0      # 1.0 = normal, <1.0 = throttled
        self.priority_floor  = 0.25     # min confidence for intake
        self.overload_events = 0

    def tick(self, log_fn=None) -> dict:
        if time.time() - self.last_run < self.INTERVAL:
            return {"intake_rate": self.intake_rate,
                    "priority_floor": self.priority_floor}
        self.last_run = time.time()

        if not _DB.exists():
            return {}
        try:
            db = _db()
            queue_size = db.execute(
                "SELECT COUNT(*) FROM tensions WHERE resolved_at IS NULL"
            ).fetchone()[0]
            db.close()
        except Exception:
            return {}

        if queue_size <= self.QUEUE_SOFT_LIMIT:
            # Normal — relax limits gradually
            self.intake_rate    = min(1.0, self.intake_rate + 0.05)
            self.priority_floor = max(0.25, self.priority_floor - 0.01)
        elif queue_size <= self.QUEUE_HARD_LIMIT:
            # Soft overload — moderate throttle
            self.intake_rate    = 0.6
            self.priority_floor = 0.40
            self._accelerate_low_attention_decay()
            self.overload_events += 1
            msg = f"[QPR] soft overload queue={queue_size} intake={self.intake_rate}"
            print(f"  {_Y}{msg}{_RS}")
            if log_fn: log_fn("pressure", msg)
        else:
            # Hard overload — aggressive throttle
            self.intake_rate    = 0.3
            self.priority_floor = 0.55
            self._accelerate_low_attention_decay()
            self.overload_events += 1
            msg = f"[QPR] HARD OVERLOAD queue={queue_size} floor={self.priority_floor}"
            print(f"  {_R}{msg}{_RS}")
            if log_fn: log_fn("pressure", msg)

        return {
            "queue_size":     queue_size,
            "intake_rate":    self.intake_rate,
            "priority_floor": self.priority_floor,
        }

    def _accelerate_low_attention_decay(self):
        """Decay confidence of beliefs with no recent reference."""
        try:
            db = _db()
            db.execute("""
                UPDATE beliefs
                SET confidence = MAX(confidence - ?, 0.05)
                WHERE last_referenced IS NULL
                  AND confidence < 0.45
                  AND human_validated = 0
                  AND (origin NOT IN ('identity_core','dream_inversion') OR origin IS NULL)
            """, (self.DECAY_ACCEL_TOPIC,))
            db.commit()
            db.close()
        except Exception:
            pass

    def status(self) -> dict:
        return {
            "intake_rate":     self.intake_rate,
            "priority_floor":  self.priority_floor,
            "overload_events": self.overload_events,
        }


# =============================================================================
# SYSTEM 3 — RESOLUTION CLOSURE SYSTEM
# =============================================================================

class ResolutionClosureSystem:
    """
    After successful contradiction synthesis:
      - inserts new resolved belief with parent_ids
      - reduces tension weight for that topic
      - marks topic as resolved in tensions table
      - boosts confidence of surviving parent beliefs
    """

    def __init__(self):
        self.closures = 0

    def close(self, topic: str, synthesis: str,
              parent_ids: list[int], confidence: float = 0.78,
              log_fn=None) -> bool:
        """
        Call after a successful dialectic/contradiction resolution.
        Returns True if closure was committed.
        """
        if not synthesis or len(synthesis.strip()) < 15:
            return False
        if not _DB.exists():
            return False
        try:
            db = _db()
            now = datetime.now().isoformat()

            # 1. Insert resolved belief
            tags = json.dumps(["resolved", "synthesis", topic])
            parent_json = json.dumps(parent_ids)
            db.execute("""
                INSERT OR IGNORE INTO beliefs
                  (content, confidence, topic, source, timestamp, tags)
                VALUES (?, ?, ?, 'resolution_closure', ?, ?)
            """, (synthesis[:500], confidence, topic, now, tags))

            new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            # 2. Boost parent beliefs slightly (they contributed to synthesis)
            if parent_ids:
                placeholders = ",".join("?" * len(parent_ids))
                db.execute(
                    f"UPDATE beliefs SET confidence = MIN(confidence + 0.04, 0.95) "
                    f"WHERE id IN ({placeholders})",
                    parent_ids
                )

            # 3. Reduce tension weight for topic
            db.execute("""
                UPDATE tensions
                SET weight = MAX(weight - 0.2, 0.0)
                WHERE topic = ? AND resolved_at IS NULL
            """, (topic,))

            # 4. Mark tension resolved if weight hits 0 or only 1 left
            db.execute("""
                UPDATE tensions SET resolved_at = ?
                WHERE topic = ? AND weight <= 0.05 AND resolved_at IS NULL
            """, (now, topic))

            # 5. Link parent beliefs to new synthesis via belief_links
            for pid in parent_ids:
                try:
                    db.execute("""
                        INSERT OR IGNORE INTO belief_links
                          (parent_id, child_id, link_type)
                        VALUES (?, ?, 'resolved_into')
                    """, (pid, new_id))
                except Exception:
                    pass

            db.commit()
            db.close()
            self.closures += 1
            msg = f"[Closure] '{topic}' resolved → belief {new_id} conf={confidence:.2f}"
            print(f"  {_G}{msg}{_RS}")
            if log_fn:
                log_fn("resolution", msg)
            return True

        except Exception as e:
            print(f"  [Closure] error: {e}")
            return False

    def tick(self, cycle: int, llm_fn=None, log_fn=None) -> int:
        """
        Passive pass: find topics with contradiction_engine beliefs that
        haven't been formally closed yet, attempt closure.
        Runs every 20 cycles.
        """
        if cycle % 20 != 0 or not llm_fn:
            return 0
        if not _DB.exists():
            return 0

        closed = 0
        try:
            db = _db()
            # Find topics with unresolved tensions AND existing synthesis beliefs
            rows = db.execute("""
                SELECT b.topic, b.content, b.id, b.confidence
                FROM beliefs b
                JOIN tensions t ON t.topic = b.topic
                WHERE b.source IN ('contradiction_engine','dialectic_resolver')
                  AND t.resolved_at IS NULL
                  AND b.confidence >= 0.65
                ORDER BY b.confidence DESC LIMIT 5
            """).fetchall()
            db.close()

            for row in rows:
                result = self.close(
                    topic=row["topic"],
                    synthesis=row["content"],
                    parent_ids=[row["id"]],
                    confidence=min(row["confidence"] + 0.05, 0.90),
                    log_fn=log_fn,
                )
                if result:
                    closed += 1

        except Exception as e:
            print(f"  [Closure] tick error: {e}")

        return closed

    def status(self) -> dict:
        return {"closures": self.closures}


# =============================================================================
# SYSTEM 4 — SELECTIVE COMPRESSION ENGINE
# =============================================================================

class SelectiveCompressionEngine:
    """
    Only compress a cluster if:
      - size > MIN_SIZE
      - keyword similarity > SIMILARITY_THRESHOLD
      - confidence variance < VARIANCE_THRESHOLD
    Otherwise retain structure. Prevents lossy over-compression.
    """
    MIN_SIZE            = 8
    SIMILARITY_THRESHOLD = 0.45
    VARIANCE_THRESHOLD  = 0.18
    INTERVAL            = 600  # 10 min

    def __init__(self):
        self.last_run    = 0.0
        self.compressed  = 0
        self.retained    = 0

    def _similarity(self, contents: list[str]) -> float:
        """Jaccard similarity across all contents in cluster."""
        if len(contents) < 2:
            return 0.0
        import re
        stop = {"that","this","with","from","have","been","they","their",
                "will","would","could","should","about","into","which","when"}
        sets = []
        for c in contents:
            words = set(re.findall(r'\b[a-z]{4,}\b', c.lower())) - stop
            if words:
                sets.append(words)
        if len(sets) < 2:
            return 0.0
        union = sets[0]
        inter = sets[0]
        for s in sets[1:]:
            union = union | s
            inter = inter & s
        return len(inter) / len(union) if union else 0.0

    def _variance(self, confidences: list[float]) -> float:
        if len(confidences) < 2:
            return 0.0
        mean = sum(confidences) / len(confidences)
        return sum((c - mean) ** 2 for c in confidences) / len(confidences)

    def tick(self, log_fn=None) -> dict:
        if time.time() - self.last_run < self.INTERVAL:
            return {}
        self.last_run = time.time()
        if not _DB.exists():
            return {}

        compressed_this = 0
        retained_this   = 0

        try:
            db = _db()
            rows = db.execute("""
                SELECT topic, COUNT(*) n,
                       GROUP_CONCAT(content, '|||') contents,
                       GROUP_CONCAT(confidence, ',') confs,
                       AVG(confidence) ac
                FROM beliefs
                WHERE human_validated = 0
                  AND (origin NOT IN ('identity_core','dream_inversion') OR origin IS NULL)
                GROUP BY topic
                HAVING n >= ?
                ORDER BY n DESC LIMIT 10
            """, (self.MIN_SIZE,)).fetchall()
            db.close()
        except Exception as e:
            print(f"  [SelectiveCompressor] query error: {e}")
            return {}

        for row in rows:
            topic    = row["topic"]
            contents = (row["contents"] or "").split("|||")
            try:
                confs = [float(c) for c in (row["confs"] or "").split(",") if c]
            except Exception:
                confs = [row["ac"]] * row["n"]

            sim  = self._similarity(contents)
            var  = self._variance(confs)

            if sim >= self.SIMILARITY_THRESHOLD and var <= self.VARIANCE_THRESHOLD:
                # Safe to compress — high similarity, low variance = redundant
                summary = f"[compressed:{row['n']}] " + " | ".join(
                    c[:80] for c in contents[:3]
                )
                try:
                    db = _db()
                    db.execute(
                        "DELETE FROM beliefs WHERE topic=? AND human_validated=0",
                        (topic,)
                    )
                    db.execute("""
                        INSERT OR IGNORE INTO beliefs
                          (topic, content, confidence, source, timestamp)
                        VALUES (?, ?, ?, 'selective_compressor', ?)
                    """, (topic, summary[:500], row["ac"], datetime.now().isoformat()))
                    db.commit()
                    db.close()
                    compressed_this += 1
                    self.compressed += 1
                    msg = (f"[SelectiveCompressor] compressed '{topic}' "
                           f"n={row['n']} sim={sim:.2f} var={var:.3f}")
                    print(f"  {_D}{msg}{_RS}")
                    if log_fn: log_fn("compression", msg)
                except Exception as e:
                    print(f"  [SelectiveCompressor] compress error: {e}")
            else:
                retained_this += 1
                self.retained += 1

        return {"compressed": compressed_this, "retained": retained_this}

    def status(self) -> dict:
        return {"compressed": self.compressed, "retained": self.retained}


# =============================================================================
# SYSTEM 5 — FAILURE MEMORY SYSTEM (persistent)
# =============================================================================

class FailureMemorySystem:
    """
    Persistent failure log: topic + strategy + reason + cycle.
    Prevents reusing failed strategies for the same topic.
    Survives restarts (JSON-backed).
    """

    def __init__(self):
        self._log: dict[str, list[dict]] = {}
        self._load()

    def _load(self):
        if _FAILURE_LOG_PATH.exists():
            try:
                self._log = json.loads(_FAILURE_LOG_PATH.read_text())
            except Exception:
                self._log = {}

    def _save(self):
        try:
            _FAILURE_LOG_PATH.write_text(json.dumps(self._log, indent=2))
        except Exception:
            pass

    def record(self, topic: str, strategy: str,
               reason: str = "", cycle: int = 0):
        if topic not in self._log:
            self._log[topic] = []
        self._log[topic].append({
            "strategy": strategy,
            "reason":   reason[:200],
            "cycle":    cycle,
            "ts":       datetime.now().isoformat(),
        })
        # Keep last 20 per topic
        self._log[topic] = self._log[topic][-20:]
        self._save()

    def failed_strategies(self, topic: str) -> list[str]:
        """Return list of strategies already tried and failed for this topic."""
        return [e["strategy"] for e in self._log.get(topic, [])]

    def should_avoid(self, topic: str, strategy: str) -> bool:
        return strategy in self.failed_strategies(topic)

    def clear_topic(self, topic: str):
        """Call after a topic is successfully resolved."""
        if topic in self._log:
            del self._log[topic]
            self._save()

    def hot_failures(self, n=5) -> list[tuple]:
        """Topics with most failure entries."""
        return sorted(
            [(t, len(v)) for t, v in self._log.items()],
            key=lambda x: -x[1]
        )[:n]

    def tick(self, log_fn=None):
        """Periodic: log hot failure topics."""
        hot = self.hot_failures(3)
        if hot and log_fn:
            log_fn("failure", f"[FailureMemory] hot: {hot}")

    def status(self) -> dict:
        return {
            "tracked_topics":  len(self._log),
            "hot_failures":    self.hot_failures(5),
            "total_entries":   sum(len(v) for v in self._log.values()),
        }


# =============================================================================
# SYSTEM 6 — ATTENTION REINFORCEMENT MEMORY
# =============================================================================

class AttentionReinforcementMemory:
    """
    Persistent attention scores per topic.
    Increases when topic is processed; decays over time.
    High-attention topics surface first in retrieval.
    """
    DECAY_PER_CYCLE   = 0.005
    BOOST_ON_PROCESS  = 0.08
    BOOST_ON_BELIEF   = 0.04
    MAX_SCORE         = 1.0
    INTERVAL          = 1   # every cycle

    def __init__(self):
        self._scores: dict[str, float] = {}
        self._last_focus: dict[str, int] = {}
        self._load()

    def _load(self):
        if _ATTN_STATE_PATH.exists():
            try:
                data = json.loads(_ATTN_STATE_PATH.read_text())
                self._scores     = data.get("scores", {})
                self._last_focus = data.get("last_focus", {})
            except Exception:
                pass

    def _save(self):
        try:
            _ATTN_STATE_PATH.write_text(json.dumps({
                "scores":     self._scores,
                "last_focus": self._last_focus,
            }, indent=2))
        except Exception:
            pass

    def on_topic_processed(self, topic: str, cycle: int):
        self._scores[topic] = min(
            self.MAX_SCORE,
            self._scores.get(topic, 0.0) + self.BOOST_ON_PROCESS
        )
        self._last_focus[topic] = cycle

    def on_belief_added(self, topic: str):
        self._scores[topic] = min(
            self.MAX_SCORE,
            self._scores.get(topic, 0.0) + self.BOOST_ON_BELIEF
        )

    def get_score(self, topic: str) -> float:
        return round(self._scores.get(topic, 0.0), 4)

    def top_topics(self, n=10) -> list[tuple]:
        return sorted(self._scores.items(), key=lambda x: -x[1])[:n]

    def tick(self, cycle: int, log_fn=None):
        """Decay all attention scores per cycle. Save every 10 cycles."""
        for topic in list(self._scores.keys()):
            self._scores[topic] = max(
                0.0,
                self._scores[topic] - self.DECAY_PER_CYCLE
            )
            if self._scores[topic] == 0.0:
                del self._scores[topic]
                if topic in self._last_focus:
                    del self._last_focus[topic]

        if cycle % 10 == 0:
            self._save()

        # Sync high-attention topics to DB last_referenced
        if cycle % 5 == 0 and _DB.exists():
            top = self.top_topics(n=5)
            if top:
                try:
                    db = _db()
                    now = datetime.now().isoformat()
                    for topic, score in top:
                        if score > 0.3:
                            db.execute("""
                                UPDATE beliefs
                                SET last_referenced = ?
                                WHERE topic = ?
                                  AND (last_referenced IS NULL OR
                                       last_referenced < datetime('now', '-1 hour'))
                            """, (now, topic))
                    db.commit()
                    db.close()
                except Exception:
                    pass

    def status(self) -> dict:
        return {
            "tracked_topics": len(self._scores),
            "top_topics":     self.top_topics(5),
        }


# =============================================================================
# SYSTEM 7 — ENERGY BUDGET SYSTEM
# =============================================================================

_OPERATION_COSTS = {
    "deep_dive":   25.0,
    "synthesis":   10.0,
    "reflection":   8.0,
    "reply":        5.0,
    "scan":         2.0,
    "idle":         0.5,
}

_REGEN_PER_CYCLE   = 8.0
_ENERGY_MAX        = 100.0
_ENERGY_FLOOR      = 15.0   # below this: skip all non-critical ops
_ENERGY_LOW        = 35.0   # below this: skip deep_dive

class EnergyBudgetSystem:
    """
    Global energy pool. Each operation has a cost.
    If energy below threshold, low-priority tasks are skipped.
    Regenerates each cycle.
    """

    def __init__(self):
        self._pool = _ENERGY_MAX
        self._load()
        self.spent    = 0.0
        self.skipped  = 0
        self.cycles   = 0

    def _load(self):
        if _ENERGY_STATE_PATH.exists():
            try:
                data = json.loads(_ENERGY_STATE_PATH.read_text())
                self._pool = float(data.get("pool", _ENERGY_MAX))
            except Exception:
                self._pool = _ENERGY_MAX

    def _save(self):
        try:
            _ENERGY_STATE_PATH.write_text(json.dumps({"pool": round(self._pool, 2)}))
        except Exception:
            pass

    def can_afford(self, operation: str) -> bool:
        cost = _OPERATION_COSTS.get(operation, 5.0)
        if self._pool < _ENERGY_FLOOR:
            return operation in ("idle", "scan")
        if self._pool < _ENERGY_LOW:
            return operation not in ("deep_dive",)
        return self._pool >= cost

    def spend(self, operation: str) -> bool:
        cost = _OPERATION_COSTS.get(operation, 5.0)
        if not self.can_afford(operation):
            self.skipped += 1
            return False
        self._pool = max(0.0, self._pool - cost)
        self.spent += cost
        return True

    def tick(self, cycle: int, log_fn=None):
        """Regenerate energy each cycle."""
        self._pool = min(_ENERGY_MAX, self._pool + _REGEN_PER_CYCLE)
        self.cycles += 1
        if cycle % 10 == 0:
            self._save()
        if self._pool < _ENERGY_FLOOR and log_fn:
            log_fn("energy", f"[Energy] LOW pool={self._pool:.1f} — low-priority ops skipped")

    def status(self) -> dict:
        return {
            "pool":    round(self._pool, 1),
            "spent":   round(self.spent, 1),
            "skipped": self.skipped,
            "level":   ("CRITICAL" if self._pool < _ENERGY_FLOOR
                        else "LOW" if self._pool < _ENERGY_LOW
                        else "OK"),
        }


# =============================================================================
# MASTER — ADAPTIVE INTELLIGENCE SINGLETON
# =============================================================================

class AdaptiveIntelligence:

    def __init__(self):
        self.retry       = AdaptiveRetryEngine()
        self.queue       = QueuePressureRegulator()
        self.closure     = ResolutionClosureSystem()
        self.compressor  = SelectiveCompressionEngine()
        self.failure_mem = FailureMemorySystem()
        self.attention   = AttentionReinforcementMemory()
        self.energy      = EnergyBudgetSystem()
        self._initialised = False

    def init(self):
        if self._initialised:
            return
        self._initialised = True
        print(f"  {_CY}[AI] Adaptive Intelligence — initialised{_RS}")
        print(f"  {_D}[AI] retry · queue · closure · compressor · failure_mem · attention · energy{_RS}")

    def tick(self, cycle: int, llm_fn=None, log_fn=None) -> dict:
        results = {}

        # Energy first — gates everything else
        self.energy.tick(cycle=cycle, log_fn=log_fn)
        results["energy"] = self.energy.status()

        # Queue pressure
        results["queue"] = self.queue.tick(log_fn=log_fn)

        # Attention decay
        self.attention.tick(cycle=cycle, log_fn=log_fn)
        results["attention_topics"] = len(self.attention._scores)

        # Failure memory log (every 10 cycles)
        if cycle % 10 == 0:
            self.failure_mem.tick(log_fn=log_fn)

        # Resolution closure (every 20 cycles)
        results["closures"] = self.closure.tick(
            cycle=cycle, llm_fn=llm_fn, log_fn=log_fn)

        # Selective compression (time-gated internally)
        if self.energy.can_afford("synthesis"):
            results["compression"] = self.compressor.tick(log_fn=log_fn)

        return results

    # ── External event hooks ──────────────────────────────────────────────────

    def record_failure(self, topic: str, strategy: str,
                       reason: str = "", cycle: int = 0):
        self.failure_mem.record(topic, strategy, reason, cycle)
        self.retry.record_attempt(topic, strategy, False, reason, cycle)

    def on_resolution(self, topic: str, belief_content: str,
                      parent_ids: list[int], confidence: float = 0.78,
                      log_fn=None):
        """Call after any successful contradiction/dialectic resolution."""
        self.closure.close(topic, belief_content, parent_ids, confidence, log_fn)
        self.failure_mem.clear_topic(topic)
        self.attention.on_topic_processed(topic, cycle=0)

    def on_topic_processed(self, topic: str, cycle: int = 0):
        self.attention.on_topic_processed(topic, cycle)

    def on_belief_added(self, topic: str):
        self.attention.on_belief_added(topic)

    def can_afford(self, operation: str) -> bool:
        return self.energy.can_afford(operation)

    def spend(self, operation: str) -> bool:
        return self.energy.spend(operation)

    def next_retry_strategy(self, topic: str) -> str:
        known_failures = self.failure_mem.failed_strategies(topic)
        for s in _RETRY_STRATEGIES:
            if s not in known_failures:
                return s
        return "unresolved"

    def status(self) -> dict:
        return {
            "retry":       self.retry.status(),
            "queue":       self.queue.status(),
            "closure":     self.closure.status(),
            "compressor":  self.compressor.status(),
            "failure_mem": self.failure_mem.status(),
            "attention":   self.attention.status(),
            "energy":      self.energy.status(),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[AdaptiveIntelligence] = None

def get_adaptive_intelligence() -> AdaptiveIntelligence:
    global _instance
    if _instance is None:
        _instance = AdaptiveIntelligence()
    return _instance


# =============================================================================
# RUN.PY PATCH BLOCK
# =============================================================================
#
# ── LOCATION A: top of _auto_learn_background(), after v3 init block ──
#
#   try:
#       from nex_adaptive_intelligence import get_adaptive_intelligence as _get_ai
#       _ai = _get_ai()
#       _ai.init()
#   except Exception as _ai_init_e:
#       print(f'  [AI] init failed: {_ai_init_e}')
#       _ai = None
#
# ── LOCATION B: after v3.tick() in cognition cycle ──
#
#   try:
#       if '_ai' in dir() and _ai is not None:
#           _ai.tick(cycle=cycle, llm_fn=_llm, log_fn=nex_log)
#   except Exception as _aite:
#       print(f'  [AI] tick error: {_aite}')
#
# ── LOCATION C: replace boost_belief_energy calls with ──
#
#   _v3.on_belief_used(content=_bu_e, belief_id=None)
#   if '_ai' in dir() and _ai:
#       _ai.on_belief_added(topic=_bu_topic)   # if topic available
#
# ── LOCATION D: after contradiction resolution ──
#
#   if '_ai' in dir() and _ai and synthesis_result:
#       _ai.on_resolution(topic=topic, belief_content=synthesis_result,
#                         parent_ids=[], log_fn=nex_log)
#
# ── LOCATION E: gate deep operations ──
#
#   if '_ai' not in dir() or _ai is None or _ai.can_afford("deep_dive"):
#       # ... run deep dive ...
#       if '_ai' in dir() and _ai: _ai.spend("deep_dive")
#
# =============================================================================

if __name__ == "__main__":
    print("Testing AdaptiveIntelligence...\n")
    ai = AdaptiveIntelligence()
    ai.init()
    result = ai.tick(cycle=20)
    print(f"\nTick result: {result}")
    print(f"\nStatus: {ai.status()}")
    print(f"\nEnergy can_afford deep_dive: {ai.can_afford('deep_dive')}")
    print(f"Next retry strategy for 'memory': {ai.next_retry_strategy('memory')}")
