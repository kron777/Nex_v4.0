"""Tests for nex_focal_set.py — Layer 1 attention protocol, 11 cases."""

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nex_focal_set import FocalSet, ShiftEvent, _default_salience


def _fn(scores: dict):
    """Fixed-score salience fn for deterministic tests."""
    def fn(bid, data, tick):
        return scores.get(bid, 0.0)
    return fn


# ── 1 ────────────────────────────────────────────────────────────────────────

def test_top_k_selection():
    """10 candidates, K=3; top-3 by salience win."""
    # b0=0.0 … b9=0.9; top-3 are b9, b8, b7
    scores = {f"b{i}": i * 0.1 for i in range(10)}
    fs = FocalSet(K=3, max_priority_delta=1.0, min_hold_ticks=0, salience_fn=_fn(scores))
    fs.update({f"b{i}": {} for i in range(10)}, current_tick=0)
    assert fs.get_focal_ids() == {"b9", "b8", "b7"}


# ── 2 ────────────────────────────────────────────────────────────────────────

def test_smooth_shift():
    """First appearance seeds at raw salience; subsequent updates are delta-clamped.
    A=0.85 steady; X enters at 0.3, its raw then jumps to 0.9 at tick 1."""
    scores = {"A": 0.85, "X": 0.3}

    def sal(bid, data, tick):
        return scores.get(bid, 0.0)

    fs = FocalSet(K=1, max_priority_delta=0.25, min_hold_ticks=0, salience_fn=sal)

    # tick 0: both appear for first time — seeded at raw score, no clamp
    fs.update({"A": {}, "X": {}}, 0)
    assert fs.get_priorities()["A"] == pytest.approx(0.85)
    assert fs.get_priorities()["X"] == pytest.approx(0.3)
    assert "A" in fs.get_focal_ids()

    # X's raw jumps to 0.9; delta clamp limits rise to +max_delta per tick
    scores["X"] = 0.9

    # tick 1: X: prev=0.30, delta=+0.25 → 0.55 < A=0.85; A still wins
    fs.update({"A": {}, "X": {}}, 1)
    assert "A" in fs.get_focal_ids(), "X clamped at prev+max_delta, cannot displace A yet"
    assert fs.get_priorities()["X"] == pytest.approx(0.55)

    # tick 2: X: prev=0.55, delta=+0.25 → 0.80 < A=0.85; A still wins
    fs.update({"A": {}, "X": {}}, 2)
    assert "A" in fs.get_focal_ids()
    assert fs.get_priorities()["X"] == pytest.approx(0.80)

    # tick 3: X: prev=0.80, raw=0.9, delta=min(0.25, 0.10)=0.10 → 0.90 > A=0.85; X wins
    fs.update({"A": {}, "X": {}}, 3)
    assert "X" in fs.get_focal_ids()
    assert "A" not in fs.get_focal_ids()


# ── 3 ────────────────────────────────────────────────────────────────────────

def test_hold_time_gate():
    """Existing focal members cannot be displaced within min_hold_ticks."""
    fs = FocalSet(K=1, max_priority_delta=1.0, min_hold_ticks=5)

    # tick 0: A enters focal
    fs.set_salience_fn(_fn({"A": 0.9, "X": 0.1}))
    fs.update({"A": {}}, 0)
    assert "A" in fs.get_focal_ids()
    assert fs.last_shift_tick == 0

    # tick 3 (3 < 5, in hold): X now dominates in raw salience but gate blocks it
    fs.set_salience_fn(_fn({"A": 0.1, "X": 0.9}))
    fs.update({"A": {}, "X": {}}, 3)
    assert "A" in fs.get_focal_ids(), "A must be protected by hold gate"
    assert "X" not in fs.get_focal_ids()

    # tick 5 (5 - 0 = 5, not < 5 → gate lifts): X displaces A
    fs.update({"A": {}, "X": {}}, 5)
    assert "X" in fs.get_focal_ids()
    assert "A" not in fs.get_focal_ids()


# ── 4 ────────────────────────────────────────────────────────────────────────

def test_blocked_recorded():
    """ShiftEvent.blocked contains candidates gated out during hold."""
    fs = FocalSet(K=1, max_priority_delta=1.0, min_hold_ticks=5)
    fs.set_salience_fn(_fn({"A": 0.9, "X": 0.1}))
    fs.update({"A": {}}, 0)  # A enters focal, last_shift_tick=0

    fs.set_salience_fn(_fn({"A": 0.1, "X": 0.9}))
    event = fs.update({"A": {}, "X": {}}, 3)  # within hold

    assert "X" in event.blocked, "X wanted top-K but was gated"
    assert "A" not in event.blocked


# ── 5 ────────────────────────────────────────────────────────────────────────

def test_introspection():
    """get_focal_ids / get_priorities / get_mode return correct state."""
    scores = {"A": 0.9, "B": 0.8, "C": 0.7, "D": 0.5}
    fs = FocalSet(K=3, max_priority_delta=1.0, min_hold_ticks=0, salience_fn=_fn(scores))
    fs.update({"A": {}, "B": {}, "C": {}, "D": {}}, 10)

    assert fs.get_focal_ids() == {"A", "B", "C"}

    prios = fs.get_priorities()
    assert set(prios.keys()) == {"A", "B", "C", "D"}
    assert prios["A"] == pytest.approx(0.9)
    assert prios["D"] == pytest.approx(0.5)

    assert fs.get_mode() == "focused"


# ── 6 ────────────────────────────────────────────────────────────────────────

def test_replaceable_salience():
    """set_salience_fn installs custom fn; it is called with correct args."""
    calls: list = []

    def custom_fn(bid, data, tick):
        calls.append((bid, tick))
        return 0.5

    fs = FocalSet(K=3)
    fs.set_salience_fn(custom_fn)
    fs.update({"A": {}, "B": {}}, 7)

    called_bids = {c[0] for c in calls}
    called_ticks = {c[1] for c in calls}
    assert "A" in called_bids
    assert "B" in called_bids
    assert 7 in called_ticks


# ── 7 ────────────────────────────────────────────────────────────────────────

def test_shift_log_capped():
    """Shift log never exceeds maxlen=1000 regardless of update count."""
    fs = FocalSet(K=2, max_priority_delta=1.0, min_hold_ticks=0,
                  salience_fn=_fn({"A": 0.9, "B": 0.8}))
    candidates = {"A": {}, "B": {}}
    for tick in range(1010):
        fs.update(candidates, tick)
    assert len(fs.get_shift_log()) == 1000


# ── 8 ────────────────────────────────────────────────────────────────────────

def test_mode_focused():
    """focused mode: standard top-K behavior, K honored."""
    scores = {f"b{i}": i * 0.1 for i in range(10)}
    fs = FocalSet(K=3, max_priority_delta=1.0, min_hold_ticks=0, salience_fn=_fn(scores))
    assert fs.get_mode() == "focused"
    fs.update({f"b{i}": {} for i in range(10)}, 0)
    assert fs.get_focal_ids() == {"b9", "b8", "b7"}


# ── 9 ────────────────────────────────────────────────────────────────────────

def test_mode_open():
    """open mode: K is ignored; includes every candidate at or above mean priority."""
    # scores: A=0.1, B=0.2, C=0.7, D=0.8, E=0.9  mean = 2.7/5 = 0.54
    # >= mean: C(0.7), D(0.8), E(0.9); below: A(0.1), B(0.2)
    scores = {"A": 0.1, "B": 0.2, "C": 0.7, "D": 0.8, "E": 0.9}
    fs = FocalSet(K=1, max_priority_delta=1.0, min_hold_ticks=0, salience_fn=_fn(scores))
    fs.set_mode("open")
    fs.update({"A": {}, "B": {}, "C": {}, "D": {}, "E": {}}, 0)
    focal = fs.get_focal_ids()
    assert "A" not in focal
    assert "B" not in focal
    assert "C" in focal
    assert "D" in focal
    assert "E" in focal
    assert len(focal) == 3  # K=1 is overridden by open mode


# ── 10 ───────────────────────────────────────────────────────────────────────

def test_mode_locked():
    """locked mode: no shifts even when salience fully inverts."""
    scores_init = {"A": 0.9, "B": 0.8, "C": 0.7, "D": 0.6}
    fs = FocalSet(K=3, max_priority_delta=1.0, min_hold_ticks=0, salience_fn=_fn(scores_init))
    fs.update({"A": {}, "B": {}, "C": {}, "D": {}}, 0)
    assert fs.get_focal_ids() == {"A", "B", "C"}

    fs.set_mode("locked")
    fs.set_salience_fn(_fn({"A": 0.1, "B": 0.2, "C": 0.3, "D": 0.9}))

    event = fs.update({"A": {}, "B": {}, "C": {}, "D": {}}, 1)

    assert fs.get_focal_ids() == {"A", "B", "C"}, "focal must not change in locked mode"
    assert event.added == frozenset()
    assert event.removed == frozenset()
    assert event.blocked == frozenset()


# ── 11 ───────────────────────────────────────────────────────────────────────

def test_set_mode_invalid():
    """set_mode raises ValueError for unrecognised mode strings."""
    fs = FocalSet()
    with pytest.raises(ValueError):
        fs.set_mode("hyperfocused")
    with pytest.raises(ValueError):
        fs.set_mode("")
    with pytest.raises(ValueError):
        fs.set_mode("FOCUSED")  # case-sensitive
