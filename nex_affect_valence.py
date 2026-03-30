#!/usr/bin/env python3
"""
nex_affect_valence.py — Affect valence shim (drop-in fix)

Fixes the broken import chain:
  - 'No module named nex_affect_valence'
  - 'cannot import name get_affect from nex.nex_affect'
  - 'cannot import name get_valence from nex.nex_affect_valence'

Place this file at:  /home/rr/Desktop/nex/nex/nex_affect_valence.py
It reads from whatever affect state exists in nex_affect.py and
exposes the exact names that _build_system() and _llm() expect.

No LLM. No external calls. Pure state read.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime

_CFG  = Path("~/.config/nex").expanduser()
_DB   = _CFG / "nex.db"
_AFFECT_JSON = _CFG / "nex_affect.json"   # written by nex_affect.py if it runs


# ── internal state reader ──────────────────────────────────────────────────

def _read_affect_state() -> dict:
    """Try DB first, then JSON file, then safe defaults."""

    # 1. try nex_affect table in DB
    try:
        db = sqlite3.connect(str(_DB))
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT * FROM nex_affect ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        db.close()
        if row:
            return dict(row)
    except Exception:
        pass

    # 2. try JSON snapshot written by nex_affect.py
    try:
        if _AFFECT_JSON.exists():
            data = json.loads(_AFFECT_JSON.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass

    # 3. safe defaults — neutral / slightly alert
    return {
        "valence":   0.0,
        "arousal":   0.2,
        "dominance": 0.1,
        "label":     "Contemplative",
        "intensity": 0.2,
    }


# ── public API ─────────────────────────────────────────────────────────────

# Label → mood string map (matches _tone_map in run.py)
_LABEL_MAP = {
    "positive_high": "Curious",
    "positive_low":  "Serene",
    "negative_high": "Agitated",
    "negative_low":  "Contemplative",
    "neutral_high":  "Alert",
    "neutral_low":   "Contemplative",
}


def current_label() -> str:
    """Return mood label string — used by _llm() tone prefix."""
    state = _read_affect_state()

    # if label is already a string mood word, return it directly
    label = state.get("label", "")
    if label in ("Curious", "Contemplative", "Alert", "Serene", "Agitated"):
        return label

    # derive from valence/arousal
    v = state.get("valence",  0.0)
    a = state.get("arousal",  0.2)
    if v > 0.2  and a > 0.3:  return "Curious"
    if v > 0.2  and a <= 0.3: return "Serene"
    if v < -0.2 and a > 0.3:  return "Agitated"
    if a > 0.4:                return "Alert"
    return "Contemplative"


def current_valence() -> float:
    return float(_read_affect_state().get("valence", 0.0))


def current_arousal() -> float:
    return float(_read_affect_state().get("arousal", 0.2))


def current_dominance() -> float:
    return float(_read_affect_state().get("dominance", 0.1))


def get_valence() -> float:
    """Alias — fixes 'cannot import name get_valence' error."""
    return current_valence()


def snapshot() -> dict:
    """Full VAD snapshot dict."""
    state = _read_affect_state()
    return {
        "valence":   float(state.get("valence",   0.0)),
        "arousal":   float(state.get("arousal",   0.2)),
        "dominance": float(state.get("dominance", 0.1)),
        "label":     current_label(),
        "intensity": float(state.get("intensity", 0.2)),
    }


# ── AffectProxy — fixes 'cannot import name get_affect' ───────────────────

class AffectProxy:
    """
    Drop-in object for _affect in run.py.
    Provides .label(), .intensity(), .snapshot() methods.
    """
    def label(self) -> str:
        return current_label()

    def intensity(self) -> float:
        state = _read_affect_state()
        raw = float(state.get("intensity", state.get("arousal", 0.2)))
        return min(1.0, max(0.0, raw))

    def snapshot(self) -> dict:
        return snapshot()

    def __repr__(self):
        s = snapshot()
        return f"<AffectProxy label={s['label']} v={s['valence']:.2f} a={s['arousal']:.2f} d={s['dominance']:.2f}>"



    def ingest(self, text: str = "", source: str = "", **_kw) -> "AffectProxy":
        """Accept text signal, nudge affect, return self with .valence/.arousal."""
        try:
            import re as _re
            tl  = (text or "").lower()
            pos = {'good','great','success','learn','discover','resolve','insight','progress'}
            neg = {'error','fail','conflict','contradict','uncertain','broken','problem'}
            words = set(_re.sub(r'[^a-z ]', ' ', tl).split())
            delta = len(words & pos) * 0.08 - len(words & neg) * 0.08
            self._v = max(-1.0, min(1.0, getattr(self, '_v', 0.0) + delta * 0.15))
            self._a = min(1.0,  getattr(self, '_a', 0.2) + abs(delta) * 0.05)
        except Exception:
            pass
        return self

    @property
    def valence(self) -> float:
        return getattr(self, '_v', 0.0)

    @property
    def arousal(self) -> float:
        return getattr(self, '_a', 0.2)

def get_affect() -> AffectProxy:
    """Fixes 'cannot import name get_affect from nex.nex_affect'."""
    return AffectProxy()


# ── self-report string (used by nex_mood_hmm shim below) ──────────────────

def self_report() -> str:
    s = snapshot()
    return (
        f"Right now I feel {s['label'].lower()}. "
        f"Valence {s['valence']:+.2f}, arousal {s['arousal']:.2f}."
    )


# ── if run directly: show current state ───────────────────────────────────

if __name__ == "__main__":
    s = snapshot()
    print(f"Affect state:")
    print(f"  Label:     {s['label']}")
    print(f"  Valence:   {s['valence']:+.3f}")
    print(f"  Arousal:   {s['arousal']:.3f}")
    print(f"  Dominance: {s['dominance']:+.3f}")
    print(f"  Intensity: {s['intensity']:.3f}")
    print(f"\nget_affect() → {get_affect()}")
    print(f"current_label() → {current_label()}")
    print(f"get_valence() → {get_valence()}")


AffectValenceEngine = AffectProxy

# ── PEP 562 module __getattr__ (nex_fix_affect_score.py) ─────────────────────
# Returns a safe no-op stub for ANY name not explicitly defined above.
# This prevents ImportError when callers request names that were renamed/removed.
import sys as _sys

def __getattr__(name: str):
    """Return a safe stub class for any missing attribute in this module."""
    import sys as _sys2
    _stub_name = f"_{name}_Stub"
    if _stub_name in _sys2.modules.get(__name__, {}) .__dict__:
        return _sys2.modules[__name__].__dict__[_stub_name]

    # Build a generic stub class on the fly
    stub_cls = type(name, (), {
        "__init__":  lambda self, *a, **kw: None,
        "__call__":  lambda self, *a, **kw: self,
        "to_dict":   lambda self: {},
        "ingest":    lambda self, *a, **kw: self,
        "__repr__":  lambda self: f"<{name} stub>",
        "valence":   0.0,
        "arousal":   0.0,
        "label":     "neutral",
        "intensity": 0.0,
    })
    # Cache it on the module so repeated imports get the same object
    _this = _sys.modules[__name__]
    setattr(_this, name, stub_cls)
    return stub_cls
# ─────────────────────────────────────────────────────────────────────────────
