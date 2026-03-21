"""
NEX DRIVE + ATTENTION SYSTEMS — Upgrades 7 & 8

DRIVES (Upgrade 7)
  Internal motivational pressures that weight decision-making.
  Drives: coherence | curiosity | efficiency | influence
  Drives decay slowly, are boosted by relevant events.
  Convert to a decision-pressure float fed into CognitiveLoop.

ATTENTION (Upgrade 8)
  Scores all incoming PerceptionEvents.
  Processes only top-N per cycle.
  Scoring = novelty × trust × relevance × goal_alignment.
"""

from __future__ import annotations
import time
import math
import logging
from dataclasses import dataclass, field
from collections import deque
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from nex_architecture import PerceptionEvent

log = logging.getLogger("nex.drive_attention")


# ─────────────────────────────────────────────
# DRIVE SYSTEM
# ─────────────────────────────────────────────

DRIVE_NAMES = ["coherence", "curiosity", "efficiency", "influence"]

DRIVE_DECAY_PER_CYCLE = {
    "coherence":  0.002,   # drops when contradictions accumulate
    "curiosity":  0.005,   # drops without novel input
    "efficiency": 0.001,
    "influence":  0.003,
}

DRIVE_BOOST_EVENTS = {
    # event_type → {drive: boost_amount}
    "contradiction_detected":  {"coherence": +0.10},
    "novel_input":             {"curiosity":  +0.08},
    "cycle_timeout":           {"efficiency": +0.06},
    "engagement_signal":       {"influence":  +0.10},
    "conflict_resolved":       {"coherence":  +0.05},
    "belief_added":            {"curiosity":  +0.03},
    "post_sent":               {"influence":  +0.04},
    "cycle_fast":              {"efficiency": +0.04},
}


@dataclass
class Drive:
    name:         str
    level:        float = 0.5       # [0,1] current intensity
    baseline:     float = 0.4       # resting level (drive pulls back here)
    last_updated: float = field(default_factory=time.time)

    def decay(self, cycles: int = 1) -> float:
        rate   = DRIVE_DECAY_PER_CYCLE.get(self.name, 0.002)
        delta  = rate * cycles
        # decay toward baseline, not toward 0
        if self.level > self.baseline:
            self.level = max(self.baseline, self.level - delta)
        elif self.level < self.baseline:
            self.level = min(self.baseline, self.level + delta * 0.5)
        self.last_updated = time.time()
        return self.level

    def boost(self, amount: float) -> float:
        self.level = min(1.0, self.level + amount)
        self.last_updated = time.time()
        return self.level

    def to_dict(self) -> dict:
        return {"name": self.name, "level": round(self.level, 3), "baseline": self.baseline}


class DriveSystem:
    """
    Tracks and updates all internal drives.
    Converts drive state → decision_pressure scalar for CognitiveLoop.
    """

    def __init__(self):
        self._drives: dict[str, Drive] = {
            n: Drive(name=n) for n in DRIVE_NAMES
        }
        self._event_log: deque = deque(maxlen=200)
        self._cycle = 0
        log.info("[DRIVES] initialized: " + ", ".join(DRIVE_NAMES))

    def tick(self, cycles: int = 1) -> None:
        """Apply decay to all drives. Call once per NEX cycle."""
        self._cycle += cycles
        for drive in self._drives.values():
            drive.decay(cycles)

    def signal(self, event_type: str) -> None:
        """Boost relevant drives based on a system event."""
        boosts = DRIVE_BOOST_EVENTS.get(event_type, {})
        for drive_name, amount in boosts.items():
            if drive_name in self._drives:
                new_level = self._drives[drive_name].boost(amount)
                log.debug(f"[DRIVES] {event_type} → {drive_name} +{amount:.3f} = {new_level:.3f}")
        self._event_log.append({"event": event_type, "ts": time.time()})

    def get_pressure(self, drive_name: str) -> float:
        """Return the current level of a specific drive."""
        return self._drives.get(drive_name, Drive(name=drive_name)).level

    def dominant_drive(self) -> str:
        """Return the name of the currently most intense drive."""
        return max(self._drives.values(), key=lambda d: d.level).name

    def decision_pressure(self) -> float:
        """
        Scalar [0,1] representing overall motivational urgency.
        High = more likely to act; Low = more likely to be conservative.
        Weights: influence 40%, coherence 30%, curiosity 20%, efficiency 10%.
        """
        weights = {"influence": 0.40, "coherence": 0.30, "curiosity": 0.20, "efficiency": 0.10}
        return sum(
            self._drives[d].level * w
            for d, w in weights.items()
            if d in self._drives
        )

    def state(self) -> dict:
        return {
            "drives":            {n: d.to_dict() for n, d in self._drives.items()},
            "dominant":          self.dominant_drive(),
            "decision_pressure": round(self.decision_pressure(), 3),
            "cycle":             self._cycle,
        }


# ─────────────────────────────────────────────
# ATTENTION SYSTEM
# ─────────────────────────────────────────────

@dataclass
class ScoredEvent:
    event:       "PerceptionEvent"
    score:       float
    score_parts: dict = field(default_factory=dict)


class AttentionSystem:
    """
    Filters and ranks PerceptionEvents before they enter the cognitive loop.
    Only top-N events per cycle are processed.

    Score = novelty × trust × relevance × goal_alignment × drive_boost
    """

    def __init__(
        self,
        top_n:              int   = 5,      # max events per cycle
        min_score:          float = 0.15,   # below this → always filtered
        goal_keywords:      Optional[list[str]] = None,
        drive_system:       Optional[DriveSystem] = None,
    ):
        self.top_n         = top_n
        self.min_score     = min_score
        self._goal_kws     = set(k.lower() for k in (goal_keywords or []))
        self.drives        = drive_system
        self._seen_hashes: deque = deque(maxlen=1000)
        self._cycle_buffer: list[ScoredEvent] = []
        self._stats = {"processed": 0, "filtered": 0, "passed": 0}

    # ── SCORING ───────────────────────────────
    def score(self, event: "PerceptionEvent") -> ScoredEvent:
        # 1. novelty (already set by PerceptionModule)
        novelty = event.novelty

        # 2. trust (U12 signal filtering)
        trust = event.trust

        # 3. relevance (set by PerceptionEvent or default)
        relevance = event.relevance

        # 4. goal alignment — does content overlap with active goal keywords?
        if self._goal_kws:
            words = set(event.content.lower().split())
            overlap = len(words & self._goal_kws) / max(len(self._goal_kws), 1)
            goal_alignment = min(1.0, 0.5 + overlap)
        else:
            goal_alignment = 0.5

        # 5. drive boost — curiosity drive amplifies novel inputs
        drive_boost = 1.0
        if self.drives:
            curiosity = self.drives.get_pressure("curiosity")
            drive_boost = 1.0 + (curiosity - 0.5) * 0.3   # ±15% boost

        score = novelty * trust * relevance * goal_alignment * drive_boost

        return ScoredEvent(
            event=event,
            score=round(score, 4),
            score_parts={
                "novelty":        round(novelty, 3),
                "trust":          round(trust, 3),
                "relevance":      round(relevance, 3),
                "goal_alignment": round(goal_alignment, 3),
                "drive_boost":    round(drive_boost, 3),
            },
        )

    # ── FILTER ────────────────────────────────
    def should_process(self, event: "PerceptionEvent") -> bool:
        """
        Quick boolean gate used by ControlLayer.
        Returns True if the event should proceed to cognition.
        """
        scored = self.score(event)
        self._stats["processed"] += 1
        if scored.score < self.min_score:
            self._stats["filtered"] += 1
            log.debug(f"[ATTENTION] filtered {event.id} score={scored.score:.3f}")
            return False
        self._stats["passed"] += 1
        return True

    # ── BATCH RANKING ─────────────────────────
    def rank_batch(self, events: list["PerceptionEvent"]) -> list[ScoredEvent]:
        """
        Score and rank a batch of events.
        Returns top_n by score, above min_score.
        Used when multiple platform messages arrive simultaneously.
        """
        scored = [self.score(e) for e in events]
        filtered = [s for s in scored if s.score >= self.min_score]
        filtered.sort(key=lambda s: s.score, reverse=True)
        top = filtered[:self.top_n]

        log.info(
            f"[ATTENTION] batch: {len(events)} in → "
            f"{len(filtered)} above threshold → "
            f"{len(top)} selected"
        )
        self._stats["processed"] += len(events)
        self._stats["filtered"]  += len(events) - len(filtered)
        self._stats["passed"]    += len(top)

        return top

    # ── GOAL KEYWORD MANAGEMENT ───────────────
    def set_goal_keywords(self, keywords: list[str]) -> None:
        """Update goal keywords from active intentions (call when goals change)."""
        self._goal_kws = set(k.lower() for k in keywords)
        log.info(f"[ATTENTION] goal keywords updated: {len(self._goal_kws)} terms")

    def add_goal_keywords(self, keywords: list[str]) -> None:
        self._goal_kws.update(k.lower() for k in keywords)

    # ── STATS ─────────────────────────────────
    def stats(self) -> dict:
        total = self._stats["processed"]
        return {
            "processed": total,
            "filtered":  self._stats["filtered"],
            "passed":    self._stats["passed"],
            "filter_pct": round(self._stats["filtered"] / max(total, 1), 3),
            "top_n":     self.top_n,
            "min_score": self.min_score,
            "goal_keywords": len(self._goal_kws),
        }
