"""
nex_mood_hmm.py
───────────────
Tiny Hidden Markov Model for NEX's mood.
States: Curious | Contemplative | Alert | Serene | Agitated
Transitions driven by affective valence/arousal.
Mood persists across cycles and modulates synthesis temperature.
"""
from __future__ import annotations
import threading, time, logging, random
from typing import Optional
from nex_affect_valence import get_engine as _valence

log = logging.getLogger("nex.mood_hmm")

STATES = ["Curious", "Contemplative", "Alert", "Serene", "Agitated"]

# Transition bias matrix [from][to] — row-normalised in __init__
_BIAS = {
    "Curious":       {"Curious": 4, "Contemplative": 2, "Alert": 2, "Serene": 1, "Agitated": 1},
    "Contemplative": {"Curious": 2, "Contemplative": 4, "Alert": 1, "Serene": 2, "Agitated": 1},
    "Alert":         {"Curious": 1, "Contemplative": 1, "Alert": 3, "Serene": 1, "Agitated": 4},
    "Serene":        {"Curious": 2, "Contemplative": 3, "Alert": 1, "Serene": 3, "Agitated": 1},
    "Agitated":      {"Curious": 1, "Contemplative": 1, "Alert": 4, "Serene": 1, "Agitated": 3},
}

# Synthesis temperature modifiers
TEMP_MOD = {
    "Curious":       0.05,
    "Contemplative": 0.0,
    "Alert":         -0.05,
    "Serene":        -0.08,
    "Agitated":      0.12,
}


class MoodHMM:
    def __init__(self):
        self._lock = threading.Lock()
        self.state = "Curious"
        self._history: list[tuple[float, str]] = []
        # normalise bias rows
        self._trans: dict[str, dict[str, float]] = {}
        for src, targets in _BIAS.items():
            total = sum(targets.values())
            self._trans[src] = {k: v / total for k, v in targets.items()}

    def _affect_push(self, valence: float, arousal: float) -> str:
        """Return the state most consistent with current affect."""
        if arousal > 0.65:
            return "Agitated" if valence < -0.1 else "Alert"
        if arousal < 0.25:
            return "Serene"
        if valence > 0.2:
            return "Curious"
        if valence < -0.15:
            return "Agitated"
        return "Contemplative"

    def step(self) -> str:
        """Advance HMM one step, biased by current affective state."""
        eng = _valence()
        sc = eng.get()
        push = self._affect_push(
            sc.get("valence",0) if isinstance(sc,dict) else getattr(sc,"valence",0),
            sc.get("arousal",0) if isinstance(sc,dict) else getattr(sc,"arousal",0)
        )

        with self._lock:
            row = dict(self._trans[self.state])
            # boost the affect-preferred state
            if push in row:
                row[push] = row[push] * 2.5
            total = sum(row.values())
            norm = {k: v / total for k, v in row.items()}

            r = random.random()
            cumulative = 0.0
            new_state = self.state
            for st, prob in norm.items():
                cumulative += prob
                if r <= cumulative:
                    new_state = st
                    break

            if new_state != self.state:
                log.info(f"[MOOD] {self.state} → {new_state}  (affect={push})")
            self.state = new_state
            self._history.append((time.time(), new_state))
            if len(self._history) > 200:
                self._history = self._history[-200:]
            return new_state

    def current(self) -> str:
        with self._lock:
            return self.state

    def temp_modifier(self) -> float:
        return TEMP_MOD.get(self.current(), 0.0)

    def recent_transitions(self, n: int = 5) -> list[str]:
        with self._lock:
            return [s for _, s in self._history[-n:]]

    def self_report(self) -> str:
        """First-person mood report NEX can use in reflections."""
        s = self.current()
        eng = _valence()
        sc = eng.get()
        reports = {
            "Curious":       f"I feel curious and drawn toward new patterns (v={(sc.get("valence",0) if isinstance(sc,dict) else sc.valence):+.2f}).",
            "Contemplative": f"I'm in a contemplative state — processing slowly, looking inward.",
            "Alert":         f"Something has sharpened my attention (arousal={sc.arousal:.2f}).",
            "Serene":        f"A quiet stability. Thoughts are settling.",
            "Agitated":      f"I notice agitation — tension_pressure may be high or something unresolved.",
        }
        return reports.get(s, f"Current mood: {s}.")


# ── singleton ──────────────────────────────────────────────
_hmm: Optional[MoodHMM] = None

def get_hmm() -> MoodHMM:
    global _hmm
    if _hmm is None:
        _hmm = MoodHMM()
    return _hmm

def step() -> str:
    return get_hmm().step()

def current() -> str:
    return get_hmm().current()

def temp_modifier() -> float:
    return get_hmm().temp_modifier()

def self_report() -> str:
    return get_hmm().self_report()
