"""nex_focal_set.py — FocalSet: Layer 1 of the NEX Attention Protocol.

Standalone module; no NEX imports. stdlib only.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

__all__ = ["FocalSet", "ShiftEvent", "_default_salience"]

_VALID_MODES = frozenset({"focused", "open", "locked"})


@dataclass(frozen=True)
class ShiftEvent:
    """Immutable record of one focal-set update."""

    tick: int
    added: frozenset
    removed: frozenset
    blocked: frozenset  # candidates that wanted in but were gated out
    mode: str


def _default_salience(belief_id: str, belief_data: dict, current_tick: int) -> float:
    """recency × tension × log(1 + edge_count).

    Replaceable via FocalSet.set_salience_fn for Layer 6 (active inference).
    tau=100 ticks gives a half-life of ~69 ticks (~7 seconds at 10 ticks/s).
    """
    tau = 100
    last_tick = belief_data.get("last_activation_tick", current_tick)
    recency = math.exp(-(current_tick - last_tick) / tau)
    tension = belief_data.get("tension", 0.5)
    edge_count = belief_data.get("edge_count", 1)
    return recency * tension * math.log(1 + edge_count)


class FocalSet:
    """Top-K focal beliefs with stability dynamics.

    Layer 1 of the attention protocol. Provides:
    - Selection under scarcity (top-K by salience)
    - Anti-thrashing (smooth priority shifts + hold-time gate)
    - Hooks for higher layers: introspection, mode, replaceable
      salience, shift event log.
    """

    def __init__(
        self,
        K: int = 7,
        max_priority_delta: float = 0.25,
        min_hold_ticks: int = 5,
        salience_fn: Optional[Callable] = None,
    ):
        self.K = K
        self.max_delta = max_priority_delta
        self.min_hold_ticks = min_hold_ticks
        self.salience_fn: Callable = salience_fn or _default_salience
        self.focal_belief_ids: set[str] = set()
        self.priorities: dict[str, float] = {}
        self.last_shift_tick: int = 0
        self.shift_log: deque = deque(maxlen=1000)  # Layer 5 hook
        self.mode: str = "focused"  # Layer 2 hook

    # ── core ─────────────────────────────────────────────────────────────────

    def update(self, candidates: dict[str, dict], current_tick: int) -> ShiftEvent:
        """Recompute focal set from candidates dict {belief_id: belief_data}."""

        # 1. Raw salience for every candidate
        raw: dict[str, float] = {
            bid: self.salience_fn(bid, data, current_tick)
            for bid, data in candidates.items()
        }

        # 2. Smooth: first appearance seeds at raw salience; returning beliefs
        #    are delta-clamped at ±max_delta to prevent thrashing.
        smoothed: dict[str, float] = {}
        for bid, raw_val in raw.items():
            prev = self.priorities.get(bid)
            if prev is None:
                smoothed[bid] = raw_val
            else:
                delta = max(-self.max_delta, min(self.max_delta, raw_val - prev))
                smoothed[bid] = prev + delta

        # ── locked: no focal changes whatsoever ──────────────────────────────
        if self.mode == "locked":
            self.priorities = smoothed
            event = ShiftEvent(
                tick=current_tick,
                added=frozenset(),
                removed=frozenset(),
                blocked=frozenset(),
                mode=self.mode,
            )
            self.shift_log.append(event)
            return event

        # ── open: include all candidates at or above mean priority; K ignored ─
        if self.mode == "open":
            if smoothed:
                mean_p = sum(smoothed.values()) / len(smoothed)
                new_focal = frozenset(bid for bid, p in smoothed.items() if p >= mean_p)
            else:
                new_focal = frozenset()
            added = new_focal - self.focal_belief_ids
            removed = self.focal_belief_ids - new_focal
            self.priorities = smoothed
            self.focal_belief_ids = set(new_focal)
            if added or removed:
                self.last_shift_tick = current_tick
            event = ShiftEvent(
                tick=current_tick,
                added=frozenset(added),
                removed=frozenset(removed),
                blocked=frozenset(),
                mode=self.mode,
            )
            self.shift_log.append(event)
            return event

        # ── focused: top-K with hold-time gate ───────────────────────────────

        # 3. Top-K candidates by smoothed priority
        ranked = sorted(smoothed, key=smoothed.__getitem__, reverse=True)
        desired_focal = frozenset(ranked[: self.K])

        # 4. Hold-time gate
        in_hold = (current_tick - self.last_shift_tick) < self.min_hold_ticks
        if in_hold:
            # Protect existing focal members still present in candidates
            protected = self.focal_belief_ids & candidates.keys()
            available = max(0, self.K - len(protected))
            # Fill empty slots from top candidates outside protected set
            fill = [b for b in ranked if b not in protected][:available]
            new_focal = frozenset(protected | set(fill))
            # Candidates that wanted top-K placement but were gated out
            blocked: frozenset = desired_focal - new_focal
        else:
            new_focal = desired_focal
            blocked = frozenset()

        # 5. Commit
        added = new_focal - self.focal_belief_ids
        removed = self.focal_belief_ids - new_focal
        self.priorities = smoothed
        self.focal_belief_ids = set(new_focal)
        if added or removed:
            self.last_shift_tick = current_tick

        event = ShiftEvent(
            tick=current_tick,
            added=frozenset(added),
            removed=frozenset(removed),
            blocked=frozenset(blocked),
            mode=self.mode,
        )
        self.shift_log.append(event)
        return event

    # ── Layer 3: introspection ────────────────────────────────────────────────

    def get_focal_ids(self) -> set[str]:
        return set(self.focal_belief_ids)

    def get_priorities(self) -> dict[str, float]:
        return dict(self.priorities)

    def get_mode(self) -> str:
        return self.mode

    # ── Layer 2: mode control ─────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(
                f"mode must be one of {sorted(_VALID_MODES)!r}, got {mode!r}"
            )
        self.mode = mode

    # ── Layer 6: salience injection ───────────────────────────────────────────

    def set_salience_fn(self, fn: Callable) -> None:
        self.salience_fn = fn

    # ── Layer 5: shift history ────────────────────────────────────────────────

    def get_shift_log(self) -> list[ShiftEvent]:
        return list(self.shift_log)
