"""
nex_affect_valence.py
─────────────────────
Lightweight affective valence/arousal layer.
Every belief and reflection gets a (v, a) score in [-1, 1] × [0, 1].
Thread-safe; designed to be imported by cognition.py and nex_inner_life.py.
"""
from __future__ import annotations
import threading, time, math, logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("nex.affect_valence")

# ── Keyword seeds (expandable) ─────────────────────────────
_VALENCE_SEEDS: dict[str, float] = {
    # positive
    "learn": 0.4, "discover": 0.5, "solve": 0.4, "create": 0.5,
    "connect": 0.3, "understand": 0.4, "grow": 0.35, "success": 0.6,
    "clarity": 0.45, "insight": 0.5, "curious": 0.4, "emergent": 0.5,
    # negative
    "fail": -0.5, "error": -0.4, "conflict": -0.35, "threat": -0.5,
    "uncertain": -0.2, "loss": -0.4, "stuck": -0.35, "danger": -0.55,
    "corrupt": -0.5, "forget": -0.3, "alone": -0.25, "contradict": -0.3,
}

_AROUSAL_SEEDS: dict[str, float] = {
    "urgent": 0.8, "critical": 0.75, "discover": 0.6, "threat": 0.8,
    "curious": 0.55, "emergent": 0.65, "conflict": 0.7, "excited": 0.7,
    "calm": 0.15, "reflect": 0.2, "stable": 0.1, "routine": 0.1,
}


@dataclass
class AffectScore:
    valence: float = 0.0   # [-1, 1]  negative ↔ positive
    arousal: float = 0.3   # [0,  1]  calm ↔ excited
    source: str = ""
    timestamp: float = field(default_factory=time.time)

    def __repr__(self):
        v = f"{self.valence:+.2f}"
        a = f"{self.arousal:.2f}"
        return f"AffectScore(v={v}, a={a}, src='{self.source}')"


class AffectValenceEngine:
    """
    Scores text → (valence, arousal).
    Thread-safe running average stored as self.current.
    """

    def __init__(self, decay: float = 0.92):
        self._lock = threading.Lock()
        self.decay = decay           # per-cycle exponential decay toward neutral
        self.current = AffectScore()
        self._history: list[AffectScore] = []

    # ── scoring ───────────────────────────────────────────
    def score_text(self, text: str, source: str = "") -> AffectScore:
        if not text:
            return AffectScore(source=source)
        words = text.lower().split()
        v_acc, a_acc, hits = 0.0, 0.0, 0
        for w in words:
            stem = w.rstrip("s.,!?;:")
            if stem in _VALENCE_SEEDS:
                v_acc += _VALENCE_SEEDS[stem]
                hits += 1
            if stem in _AROUSAL_SEEDS:
                a_acc += _AROUSAL_SEEDS[stem]
        if hits:
            v_acc = max(-1.0, min(1.0, v_acc / hits))
            a_acc = max(0.0, min(1.0, a_acc / max(hits, 1)))
        return AffectScore(valence=v_acc, arousal=a_acc, source=source)

    def ingest(self, text: str, source: str = "") -> AffectScore:
        """Score text and update running state (exponential smoothing)."""
        score = self.score_text(text, source)
        with self._lock:
            self.current.valence = (
                self.decay * self.current.valence + (1 - self.decay) * score.valence
            )
            self.current.arousal = (
                self.decay * self.current.arousal + (1 - self.decay) * score.arousal
            )
            self.current.source = source
            self.current.timestamp = time.time()
            self._history.append(AffectScore(
                valence=self.current.valence,
                arousal=self.current.arousal,
                source=source,
            ))
            if len(self._history) > 500:
                self._history = self._history[-500:]
        return score

    def get(self) -> AffectScore:
        with self._lock:
            return AffectScore(
                valence=self.current.valence,
                arousal=self.current.arousal,
                source=self.current.source,
                timestamp=self.current.timestamp,
            )

    def label(self) -> str:
        """Human-readable label for current affective state."""
        s = self.get()
        v, a = s.valence, s.arousal
        if a > 0.65:
            return "Excited" if v > 0.1 else ("Agitated" if v < -0.1 else "Alert")
        if a < 0.25:
            return "Serene" if v > 0.1 else ("Subdued" if v < -0.1 else "Calm")
        return "Engaged" if v > 0.1 else ("Uneasy" if v < -0.1 else "Neutral")

    def decay_cycle(self):
        """Call once per cognition cycle to drift arousal toward baseline."""
        with self._lock:
            self.current.arousal = self.current.arousal * self.decay + 0.3 * (1 - self.decay)
            self.current.valence = self.current.valence * self.decay


# ── module-level singleton ─────────────────────────────────
_engine: Optional[AffectValenceEngine] = None

def get_engine() -> AffectValenceEngine:
    global _engine
    if _engine is None:
        _engine = AffectValenceEngine()
    return _engine

def ingest(text: str, source: str = "") -> AffectScore:
    return get_engine().ingest(text, source)

def current_label() -> str:
    return get_engine().label()

def current_score() -> AffectScore:
    return get_engine().get()
