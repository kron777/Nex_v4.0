"""
nex_temporal_delta.py  —  Temporal Delta / Cognitive Velocity
==============================================================
Tracks per-cycle changes in NEX's cognitive state and computes
a "cognitive velocity" metric — how fast is she actually changing?

What it tracks per cycle:
  - belief count delta        (new beliefs absorbed)
  - insight count delta       (new insights synthesized)
  - confidence drift          (avg confidence change)
  - topic alignment drift     (is she improving at using her beliefs?)
  - contradiction resolved    (tension being released)
  - new topics encountered    (exploration breadth)

Outputs:
  - cognitive_velocity  : 0-1 composite change score
  - acceleration        : velocity delta vs previous cycle
  - trend               : "accelerating" | "stable" | "decelerating"
  - peak_velocity_cycle : when was she changing fastest?

Stored in:
  ~/.config/nex/temporal_delta.json  — rolling 100-cycle history
  ~/.config/nex/cognitive_velocity.json — current + peak metrics

Wire-in (run.py) — at end of each cycle stats block:
    from nex_temporal_delta import TemporalDelta, get_temporal_delta

    _td = get_temporal_delta()
    _td.record(
        cycle=cycle,
        beliefs=_bc,
        insights=len(_ins2),
        avg_conf=_avg_conf_real,
        avg_align=_avg_align2,
        contradictions_resolved=_contra_resolved,
    )
    if cycle % 5 == 0:
        print(f"  [VELOCITY] {_td.summary()}")

Standalone:
    python3 nex_temporal_delta.py
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
_CONFIG_DIR    = Path.home() / ".config" / "nex"
_DELTA_FILE    = _CONFIG_DIR / "temporal_delta.json"
_VELOCITY_FILE = _CONFIG_DIR / "cognitive_velocity.json"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Rolling history size
_HISTORY_SIZE  = 100

# Velocity component weights
_WEIGHTS = {
    "belief_growth":    0.25,
    "insight_growth":   0.20,
    "conf_drift":       0.15,
    "align_drift":      0.25,
    "contra_resolved":  0.10,
    "topic_breadth":    0.05,
}

# Normalisation denominators (expected max per cycle)
_NORMS = {
    "belief_growth":    50.0,   # ~50 new beliefs per cycle = max score
    "insight_growth":   5.0,    # ~5 new insights per cycle = max
    "conf_drift":       0.05,   # 5% confidence change per cycle = max
    "align_drift":      0.10,   # 10% alignment change = max
    "contra_resolved":  4.0,    # 4 contradictions resolved = max
    "topic_breadth":    3.0,    # 3 new topics per cycle = max
}


# ── CycleSnapshot ─────────────────────────────────────────────────────────────

class CycleSnapshot:
    """One cycle's worth of cognitive state."""

    def __init__(
        self,
        cycle:                  int,
        beliefs:                int   = 0,
        insights:               int   = 0,
        avg_conf:               float = 0.0,
        avg_align:              float = 0.0,
        contradictions_resolved: int  = 0,
        topics_seen:            int   = 0,
        ts:                     float = 0.0,
    ):
        self.cycle                   = cycle
        self.beliefs                 = beliefs
        self.insights                = insights
        self.avg_conf                = avg_conf
        self.avg_align               = avg_align
        self.contradictions_resolved = contradictions_resolved
        self.topics_seen             = topics_seen
        self.ts                      = ts or time.time()

    def to_dict(self) -> dict:
        return {
            "cycle":                   self.cycle,
            "beliefs":                 self.beliefs,
            "insights":                self.insights,
            "avg_conf":                self.avg_conf,
            "avg_align":               self.avg_align,
            "contradictions_resolved": self.contradictions_resolved,
            "topics_seen":             self.topics_seen,
            "ts":                      self.ts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CycleSnapshot":
        return cls(**{k: d[k] for k in d if k in cls.__init__.__code__.co_varnames})


# ── TemporalDelta ─────────────────────────────────────────────────────────────

class TemporalDelta:
    """
    Tracks cognitive velocity across cycles.

    Records a snapshot each cycle, computes velocity as the composite
    rate of change across all tracked dimensions.
    """

    def __init__(self):
        self._history    : list[CycleSnapshot] = []
        self._velocity   : float               = 0.0
        self._prev_vel   : float               = 0.0
        self._peak_vel   : float               = 0.0
        self._peak_cycle : int                 = 0
        self._trend      : str                 = "stable"
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if _DELTA_FILE.exists():
            try:
                raw = json.loads(_DELTA_FILE.read_text())
                self._history = [CycleSnapshot.from_dict(d) for d in raw.get("history", [])]
            except Exception:
                self._history = []

        if _VELOCITY_FILE.exists():
            try:
                v = json.loads(_VELOCITY_FILE.read_text())
                self._velocity   = v.get("velocity", 0.0)
                self._prev_vel   = v.get("prev_velocity", 0.0)
                self._peak_vel   = v.get("peak_velocity", 0.0)
                self._peak_cycle = v.get("peak_cycle", 0)
                self._trend      = v.get("trend", "stable")
            except Exception:
                pass

    def _save(self):
        try:
            _DELTA_FILE.write_text(json.dumps({
                "history": [s.to_dict() for s in self._history[-_HISTORY_SIZE:]]
            }, indent=2))
        except Exception as e:
            print(f"  [TemporalDelta] delta save error: {e}")

        try:
            _VELOCITY_FILE.write_text(json.dumps({
                "velocity":      self._velocity,
                "prev_velocity": self._prev_vel,
                "peak_velocity": self._peak_vel,
                "peak_cycle":    self._peak_cycle,
                "trend":         self._trend,
                "last_updated":  time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, indent=2))
        except Exception as e:
            print(f"  [TemporalDelta] velocity save error: {e}")

    # ── velocity computation ──────────────────────────────────────────────────

    def _compute_velocity(
        self,
        current: CycleSnapshot,
        prev:    CycleSnapshot,
    ) -> float:
        """Compute velocity score from delta between two snapshots."""

        deltas = {}

        # Belief growth
        belief_delta = max(0, current.beliefs - prev.beliefs)
        deltas["belief_growth"] = min(1.0, belief_delta / _NORMS["belief_growth"])

        # Insight growth
        insight_delta = max(0, current.insights - prev.insights)
        deltas["insight_growth"] = min(1.0, insight_delta / _NORMS["insight_growth"])

        # Confidence drift (absolute change)
        conf_delta = abs(current.avg_conf - prev.avg_conf)
        deltas["conf_drift"] = min(1.0, conf_delta / _NORMS["conf_drift"])

        # Alignment drift (positive drift = improvement)
        align_delta = current.avg_align - prev.avg_align
        # Reward improvement, slight penalty for decline
        if align_delta >= 0:
            deltas["align_drift"] = min(1.0, align_delta / _NORMS["align_drift"])
        else:
            deltas["align_drift"] = max(0.0, 1.0 + align_delta / _NORMS["align_drift"])

        # Contradictions resolved
        deltas["contra_resolved"] = min(
            1.0, current.contradictions_resolved / _NORMS["contra_resolved"]
        )

        # Topic breadth (new topics this cycle)
        topic_delta = max(0, current.topics_seen - prev.topics_seen)
        deltas["topic_breadth"] = min(1.0, topic_delta / _NORMS["topic_breadth"])

        # Weighted sum
        velocity = sum(
            _WEIGHTS[k] * deltas[k] for k in _WEIGHTS
        )
        return round(velocity, 4)

    # ── public API ────────────────────────────────────────────────────────────

    def record(
        self,
        cycle:                  int,
        beliefs:                int   = 0,
        insights:               int   = 0,
        avg_conf:               float = 0.0,
        avg_align:              float = 0.0,
        contradictions_resolved: int  = 0,
        topics_seen:            int   = 0,
    ):
        """
        Record a cycle snapshot and update velocity metrics.
        Call once per cycle at the end of the stats block.
        """
        snap = CycleSnapshot(
            cycle=cycle,
            beliefs=beliefs,
            insights=insights,
            avg_conf=avg_conf,
            avg_align=avg_align,
            contradictions_resolved=contradictions_resolved,
            topics_seen=topics_seen,
        )
        self._history.append(snap)

        # Compute velocity if we have a previous snapshot
        if len(self._history) >= 2:
            prev = self._history[-2]
            self._prev_vel = self._velocity
            self._velocity = self._compute_velocity(snap, prev)

            # Update peak
            if self._velocity > self._peak_vel:
                self._peak_vel   = self._velocity
                self._peak_cycle = cycle

            # Compute trend over last 5 cycles
            if len(self._history) >= 5:
                recent_vels = []
                for i in range(max(0, len(self._history)-5), len(self._history)-1):
                    v = self._compute_velocity(
                        self._history[i+1], self._history[i]
                    )
                    recent_vels.append(v)
                if recent_vels:
                    avg_recent = sum(recent_vels) / len(recent_vels)
                    if self._velocity > avg_recent * 1.15:
                        self._trend = "accelerating"
                    elif self._velocity < avg_recent * 0.85:
                        self._trend = "decelerating"
                    else:
                        self._trend = "stable"

        self._save()

    def velocity(self) -> float:
        """Current cognitive velocity (0-1)."""
        return self._velocity

    def acceleration(self) -> float:
        """Change in velocity vs previous cycle."""
        return round(self._velocity - self._prev_vel, 4)

    def trend(self) -> str:
        """'accelerating' | 'stable' | 'decelerating'"""
        return self._trend

    def peak(self) -> tuple[float, int]:
        """(peak_velocity, peak_cycle)"""
        return self._peak_vel, self._peak_cycle

    def rolling_average(self, n: int = 10) -> float:
        """Average velocity over last N cycles."""
        if len(self._history) < 2:
            return 0.0
        vels = []
        for i in range(max(0, len(self._history)-n), len(self._history)-1):
            vels.append(self._compute_velocity(
                self._history[i+1], self._history[i]
            ))
        return round(sum(vels) / len(vels), 4) if vels else 0.0

    def summary(self) -> str:
        acc = self.acceleration()
        acc_str = f"+{acc:.3f}" if acc >= 0 else f"{acc:.3f}"
        return (
            f"velocity={self._velocity:.3f} ({self._trend}) "
            f"acc={acc_str} peak={self._peak_vel:.3f}@c{self._peak_cycle}"
        )

    def prompt_block(self) -> str:
        """Compact string for system prompt injection."""
        if not self._history:
            return ""
        v = self._velocity
        if v < 0.05:
            state = "in a quiet period — consolidating"
        elif v < 0.15:
            state = "steadily absorbing"
        elif v < 0.30:
            state = "actively learning"
        else:
            state = "in rapid cognitive flux"

        acc = self.acceleration()
        direction = "↑" if acc > 0.01 else "↓" if acc < -0.01 else "→"

        return (
            f"Cognitive state: {state} {direction} "
            f"(velocity={v:.2f}, trend={self._trend})"
        )

    def history_summary(self, n: int = 10) -> list[dict]:
        """Last N cycles as summary dicts."""
        out = []
        history = self._history[-n:]
        for i, snap in enumerate(history):
            vel = 0.0
            if i > 0:
                vel = self._compute_velocity(snap, history[i-1])
            out.append({
                "cycle":    snap.cycle,
                "beliefs":  snap.beliefs,
                "insights": snap.insights,
                "velocity": round(vel, 3),
                "align":    round(snap.avg_align, 3),
            })
        return out


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[TemporalDelta] = None

def get_temporal_delta() -> TemporalDelta:
    global _instance
    if _instance is None:
        _instance = TemporalDelta()
    return _instance


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sqlite3, os

    print("Testing TemporalDelta...\n")
    td = TemporalDelta()

    # Simulate a few cycles from real DB data
    db = sqlite3.connect(os.path.expanduser("~/.config/nex/nex.db"))
    belief_count = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    insight_count = len(json.loads(
        (Path.home() / ".config/nex/insights.json").read_text()
    )) if (Path.home() / ".config/nex/insights.json").exists() else 0
    db.close()

    # Simulate 5 cycles with realistic deltas
    base_beliefs = belief_count - 50
    for i in range(5):
        td.record(
            cycle=i+1,
            beliefs=base_beliefs + i*10 + (i*3),
            insights=insight_count - (4-i),
            avg_conf=0.62 + i*0.002,
            avg_align=0.45 + i*0.01,
            contradictions_resolved=i % 3,
            topics_seen=20 + i,
        )

    print(f"Summary: {td.summary()}")
    print(f"Velocity: {td.velocity():.3f}")
    print(f"Trend: {td.trend()}")
    print(f"Peak: {td.peak()}")
    print(f"Rolling avg (5): {td.rolling_average(5):.3f}")
    print()
    print("Prompt block:")
    print(td.prompt_block())
    print()
    print("History:")
    for h in td.history_summary():
        print(f"  cycle={h['cycle']} beliefs={h['beliefs']} "
              f"insights={h['insights']} velocity={h['velocity']} "
              f"align={h['align']}")
