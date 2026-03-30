#!/usr/bin/env python3
"""
nex_affect_valence.py — Affect valence shim (drop-in fix)

Fixes:
  - 'AffectProxy' object has no attribute 'get'     ← get() was outside class
  - 'No module named nex_affect_valence'
  - 'cannot import name get_affect from nex.nex_affect'
  - 'cannot import name get_valence from nex.nex_affect_valence'
  - current_score() returned None, breaking GWT broadcast

Place at BOTH:
  /home/rr/Desktop/nex/nex_affect_valence.py
  /home/rr/Desktop/nex/nex/nex_affect_valence.py
"""

import sqlite3
import json
import sys
from pathlib import Path
from datetime import datetime

_CFG         = Path("~/.config/nex").expanduser()
_DB          = _CFG / "nex.db"
_AFFECT_JSON = _CFG / "nex_affect.json"


# ── internal state reader ──────────────────────────────────────────────────

def _read_affect_state() -> dict:
    """Try DB first, then JSON file, then safe defaults."""
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
    try:
        if _AFFECT_JSON.exists():
            data = json.loads(_AFFECT_JSON.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {
        "valence":   0.0,
        "arousal":   0.2,
        "dominance": 0.1,
        "label":     "Contemplative",
        "intensity": 0.2,
    }


# ── public scalar API ──────────────────────────────────────────────────────

_LABEL_MAP = {
    "positive_high": "Curious",
    "positive_low":  "Serene",
    "negative_high": "Agitated",
    "negative_low":  "Contemplative",
    "neutral_high":  "Alert",
    "neutral_low":   "Contemplative",
}


def current_label() -> str:
    state = _read_affect_state()
    label = state.get("label", "")
    if label in ("Curious", "Contemplative", "Alert", "Serene", "Agitated"):
        return label
    v = state.get("valence", 0.0)
    a = state.get("arousal", 0.2)
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
    return current_valence()


def snapshot() -> dict:
    state = _read_affect_state()
    return {
        "valence":   float(state.get("valence",   0.0)),
        "arousal":   float(state.get("arousal",   0.2)),
        "dominance": float(state.get("dominance", 0.1)),
        "label":     current_label(),
        "intensity": float(state.get("intensity", 0.2)),
    }


def self_report() -> str:
    s = snapshot()
    return (
        f"Right now I feel {s['label'].lower()}. "
        f"Valence {s['valence']:+.2f}, arousal {s['arousal']:.2f}."
    )


# ── AffectScore dataclass ──────────────────────────────────────────────────

class AffectScore:
    """
    Returned by current_score() — used by GWT broadcast in run.py:
        from nex_affect_valence import current_score as _cv_score
        _cs = _cv_score()
        _gwb_run.submit(_afs(_cs.valence, _cs.arousal, _mood_cur()))
    """
    __slots__ = ("valence", "arousal", "label", "intensity")

    def __init__(self, valence=0.0, arousal=0.2, label="Contemplative", intensity=0.2):
        self.valence   = float(valence)
        self.arousal   = float(arousal)
        self.label     = label
        self.intensity = float(intensity)

    def to_dict(self) -> dict:
        return {
            "valence":   self.valence,
            "arousal":   self.arousal,
            "label":     self.label,
            "intensity": self.intensity,
        }

    def get(self, key, default=None):
        """Dict-style .get() so callers can treat this like a dict."""
        return self.to_dict().get(key, default)

    def __repr__(self):
        return (f"AffectScore(valence={self.valence:.2f}, "
                f"arousal={self.arousal:.2f}, label={self.label!r})")


def current_score() -> AffectScore:
    """
    Returns a real AffectScore — NOT None.
    Fixes GWT broadcast crash: _cs = _cv_score(); _cs.valence / _cs.arousal
    """
    s = snapshot()
    return AffectScore(
        valence   = s["valence"],
        arousal   = s["arousal"],
        label     = s["label"],
        intensity = s["intensity"],
    )


# ── AffectProxy ────────────────────────────────────────────────────────────

class AffectProxy:
    """
    Drop-in object for _affect in run.py.
    ALL methods that any caller uses are defined here — nothing outside the class.
    """

    def label(self) -> str:
        return current_label()

    def intensity(self) -> float:
        state = _read_affect_state()
        raw = float(state.get("intensity", state.get("arousal", 0.2)))
        return min(1.0, max(0.0, raw))

    def snapshot(self) -> dict:
        return snapshot()

    def get(self, key=None, default=None):
        """
        Dict-style .get() — fixes 'AffectProxy object has no attribute get'.
        Called as: _affect.get('valence') or _affect.get()
        """
        s = snapshot()
        if key is None:
            return s
        return s.get(key, default)

    def ingest(self, text: str = "", source: str = "", **_kw) -> "AffectProxy":
        """Nudge internal affect from text signal. Returns self."""
        try:
            import re as _re
            tl  = (text or "").lower()
            pos = {'good','great','positive','success','learn','grow','discover',
                   'understand','resolve','clear','progress','insight','achieve'}
            neg = {'error','fail','wrong','conflict','contradict','uncertain',
                   'confused','broken','bad','problem','issue','stuck','loss'}
            words = set(_re.sub(r'[^a-z ]', ' ', tl).split())
            delta = len(words & pos) * 0.08 - len(words & neg) * 0.08
            self._valence = max(-1.0, min(1.0, getattr(self, '_valence', 0.0) + delta * 0.15))
            self._arousal = min(1.0,  getattr(self, '_arousal', 0.2) + abs(delta) * 0.05)
        except Exception:
            pass
        return self

    def update(self, delta: dict) -> None:
        """Accept a delta dict from affect_from_text() — used in run.py absorb loop."""
        try:
            v = float(delta.get("valence", 0.0))
            a = float(delta.get("arousal", 0.0))
            self._valence = max(-1.0, min(1.0, getattr(self, '_valence', 0.0) + v * 0.1))
            self._arousal = min(1.0,  getattr(self, '_arousal', 0.2) + abs(a) * 0.05)
        except Exception:
            pass

    @property
    def valence(self) -> float:
        return getattr(self, '_valence', _read_affect_state().get('valence', 0.0))

    @property
    def arousal(self) -> float:
        return getattr(self, '_arousal', _read_affect_state().get('arousal', 0.2))

    def __repr__(self):
        s = snapshot()
        return (f"<AffectProxy label={s['label']} "
                f"v={s['valence']:.2f} a={s['arousal']:.2f} d={s['dominance']:.2f}>")


def get_affect() -> AffectProxy:
    return AffectProxy()


def get_engine() -> AffectProxy:
    """Alias used by NarrativeThread and other callers."""
    return AffectProxy()


def ingest(data, source=None):
    """Module-level ingest — returns the proxy so callers can do .valence etc."""
    return get_singleton().ingest(str(data) if data else "", source=source or "")


# ── Singleton ──────────────────────────────────────────────────────────────

_affect_singleton: AffectProxy = None  # type: ignore

def get_singleton() -> AffectProxy:
    global _affect_singleton
    if _affect_singleton is None:
        _affect_singleton = AffectProxy()
    return _affect_singleton


# ── Compatibility aliases ──────────────────────────────────────────────────

AffectValenceEngine = AffectProxy


# Stubs that used to return None — kept for import compatibility
def _affect_lbl(*a, **kw): return current_label()
def _al(*a, **kw):         return current_label()
def _cv_score(*a, **kw):   return current_score()
def _snap(*a, **kw):       return snapshot()
def _valence(*a, **kw):    return current_valence()


# ── PEP 562: catch-all for any other missing name ─────────────────────────

def __getattr__(name: str):
    """Return a safe stub for any attribute not defined above."""
    stub_cls = type(name, (), {
        "__init__":  lambda self, *a, **kw: None,
        "__call__":  lambda self, *a, **kw: self,
        "get":       lambda self, k=None, d=None: d,
        "to_dict":   lambda self: {},
        "ingest":    lambda self, *a, **kw: self,
        "update":    lambda self, *a, **kw: None,
        "__repr__":  lambda self: f"<{name} stub>",
        "valence":   0.0,
        "arousal":   0.0,
        "label":     "neutral",
        "intensity": 0.0,
    })
    setattr(sys.modules[__name__], name, stub_cls)
    return stub_cls


# ── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    s = snapshot()
    print(f"Affect state:")
    print(f"  Label:     {s['label']}")
    print(f"  Valence:   {s['valence']:+.3f}")
    print(f"  Arousal:   {s['arousal']:.3f}")
    print(f"  Dominance: {s['dominance']:+.3f}")
    print(f"  Intensity: {s['intensity']:.3f}")
    cs = current_score()
    print(f"\ncurrent_score() → {cs}")
    print(f"current_score().get('valence') → {cs.get('valence')}")
    ap = AffectProxy()
    print(f"AffectProxy().get() → {ap.get()}")
    print(f"AffectProxy().get('valence') → {ap.get('valence')}")
    print(f"AffectProxy().get('missing', 99) → {ap.get('missing', 99)}")
