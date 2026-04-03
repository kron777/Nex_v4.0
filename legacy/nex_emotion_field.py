#!/usr/bin/env python3
"""
nex_emotion_field.py — NEX Phase 5: Emergent Emotion
=====================================================
Place at: ~/Desktop/nex/nex_emotion_field.py

Emotion is NOT programmed here.
It emerges from the state of the belief field after each activation.

Three quantities computed from graph activation:

  field_energy     — weighted activation * confidence across cluster
                     high = deep engagement, low = sparse/uncertain

  epistemic_temp   — 0.0 cold (settled) to 1.0 hot (contradictory)
                     derived from confidence + tension edge density

  tension_density  — fraction of traversed edges that were CONTRADICTS
                     signals internal conflict on this topic

These map to VAD (valence/arousal/dominance) without any rule layer:

  valence   = maps epistemic_temp → positive (cold) / negative (hot)
  arousal   = blend of tension and field energy
  dominance = field energy scaled by mean confidence

Mood = exponential moving average of field_energy across activations.
Mood is persistent — it decays slowly and builds across the session.

Usage:
    from nex_emotion_field import EmotionField, snapshot
    ef = EmotionField()
    state = ef.update_from_activation(activation_result)
    print(state)  # {valence, arousal, dominance, mood, label, raw}

    # Or use the module-level singleton:
    state = snapshot()   # returns last known state without recomputing
"""

import json
import time
import math
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

CFG_PATH    = Path("~/.config/nex").expanduser()
STATE_PATH  = CFG_PATH / "nex_emotion_state.json"

# Mood EMA smoothing — higher = slower mood change
MOOD_ALPHA  = 0.15   # new = alpha * new_energy + (1-alpha) * old_mood

# Valence mapping parameters
# Cold epistemic temp (0.0) → max positive valence (+0.6)
# Hot epistemic temp (1.0)  → max negative valence (-0.6)
VALENCE_SCALE = 0.6

# Label thresholds (valence, arousal) → affect label
# Order matters — first match wins
_LABEL_MAP = [
    # (min_valence, min_arousal, max_arousal, label)
    ( 0.25,  0.5,  1.0, "energised"),
    ( 0.25,  0.2,  0.5, "engaged"),
    ( 0.25, -1.0,  0.2, "contemplative"),
    (-0.1,   0.6,  1.0, "tense"),
    (-0.1,   0.3,  0.6, "restless"),
    (-0.1,  -1.0,  0.3, "withdrawn"),
    (-1.0,   0.5,  1.0, "agitated"),
    (-1.0,  -1.0,  0.5, "flat"),
]


@dataclass
class EmotionState:
    valence:    float   # -1.0 to +1.0  (negative=hot/conflicted, positive=cold/settled)
    arousal:    float   # 0.0 to 1.0    (low=quiet, high=activated)
    dominance:  float   # 0.0 to 1.0    (low=uncertain, high=confident)
    mood:       float   # 0.0 to 1.0    (running EMA of field energy)
    label:      str     # human-readable affect label
    field_energy:     float
    epistemic_temp:   float
    tension_density:  float
    timestamp:  float


def _compute_label(valence: float, arousal: float) -> str:
    for min_v, min_a, max_a, label in _LABEL_MAP:
        if valence >= min_v and min_a <= arousal <= max_a:
            return label
    return "contemplative"


def _load_state() -> Optional[dict]:
    try:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text())
    except Exception:
        pass
    return None


def _save_state(state: EmotionState):
    try:
        CFG_PATH.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(asdict(state), indent=2))
    except Exception as e:
        print(f"  [emotion_field] save error: {e}")


class EmotionField:
    """
    Stateful emotion field that updates from activation results.
    Maintains mood as a running average across the session.
    """

    def __init__(self):
        saved = _load_state()
        if saved:
            self._mood = float(saved.get("mood", 0.35))
            self._last_state = EmotionState(**saved)
        else:
            self._mood = 0.35   # neutral starting mood
            self._last_state = self._neutral_state()

    def _neutral_state(self) -> EmotionState:
        return EmotionState(
            valence=0.0,
            arousal=0.2,
            dominance=0.4,
            mood=0.35,
            label="contemplative",
            field_energy=0.35,
            epistemic_temp=0.5,
            tension_density=0.0,
            timestamp=time.time(),
        )

    def update_from_activation(self, activation_result) -> EmotionState:
        """
        Compute new emotion state from an ActivationResult.
        This is the core of Phase 5 — no rules, just field math.

        activation_result: ActivationResult from nex_activation.py
        """
        fe   = float(activation_result.field_energy or 0.0)
        temp = float(activation_result.epistemic_temperature())
        td   = float(activation_result.tension_density or 0.0)

        activated = activation_result.activated or []
        if activated:
            mean_conf = sum(b.confidence for b in activated) / len(activated)
        else:
            mean_conf = 0.5

        # ── Core mappings — no rules, just math ──────────────────────────

        # Valence: cold field (low temp) = positive affect
        # hot field (high temp, contradiction) = negative affect
        valence = round((1.0 - 2.0 * temp) * VALENCE_SCALE, 4)

        # Arousal: driven by tension and field energy together
        # High tension = high arousal (conflict activates)
        # High energy alone = moderate arousal
        arousal = round(math.sqrt(td * 0.6 + fe * 0.4), 4)
        arousal = min(1.0, arousal)

        # Dominance: how much NEX "owns" this topic
        # High confidence + high field energy = high dominance
        dominance = round(fe * mean_conf, 4)
        dominance = min(1.0, dominance)

        # Mood: slow EMA of field energy
        self._mood = round(
            MOOD_ALPHA * fe + (1.0 - MOOD_ALPHA) * self._mood, 4
        )

        label = _compute_label(valence, arousal)

        state = EmotionState(
            valence=valence,
            arousal=arousal,
            dominance=dominance,
            mood=self._mood,
            label=label,
            field_energy=round(fe, 4),
            epistemic_temp=round(temp, 4),
            tension_density=round(td, 4),
            timestamp=time.time(),
        )

        self._last_state = state
        _save_state(state)
        return state

    def current(self) -> EmotionState:
        """Return last known emotion state without recomputing."""
        return self._last_state

    def mood_description(self) -> str:
        """Plain-language mood summary for injection into prompts."""
        m = self._mood
        if m > 0.6:
            return "deeply engaged — the field is dense and active"
        elif m > 0.45:
            return "attentive — moderate field energy"
        elif m > 0.3:
            return "quiet — field is sparse"
        else:
            return "low energy — little has been activated recently"

    def to_affect_snapshot(self) -> dict:
        """
        Drop-in replacement for nex_affect_valence.snapshot().
        Returns same schema so soul_loop.consult_state() needs
        only one line changed.
        """
        s = self._last_state
        return {
            "label":     s.label.capitalize(),
            "valence":   s.valence,
            "arousal":   s.arousal,
            "dominance": s.dominance,
            "mood":      s.mood,
        }


# ── Module-level singleton ────────────────────────────────────────────────────
_field: Optional[EmotionField] = None

def _get_field() -> EmotionField:
    global _field
    if _field is None:
        _field = EmotionField()
    return _field


def update(activation_result) -> EmotionState:
    """
    Update emotion from a fresh ActivationResult.
    Call this every time nex_activation.activate() is called.
    """
    return _get_field().update_from_activation(activation_result)


def snapshot() -> dict:
    """
    Return current emotion state as affect dict.
    Drop-in for nex_affect_valence.snapshot() — same schema.
    """
    return _get_field().to_affect_snapshot()


def current_label() -> str:
    """Return current affect label string. Replaces nex_affect_valence.current_label()"""
    return _get_field().current().label.capitalize()


def mood() -> float:
    """Return current mood float (0.0-1.0). Replaces nex_mood_hmm.current()"""
    return _get_field().current().mood


def self_report() -> str:
    """Return mood description string. Replaces nex_mood_hmm.self_report()"""
    return _get_field().mood_description()


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path("~/Desktop/nex").expanduser()))

    print("  Loading activation engine...")
    try:
        from nex_activation import activate as _activate
        q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "what do you think about consciousness?"
        print(f"  Query: {q}\n")
        ar = _activate(q)
        print(f"  field_energy:    {ar.field_energy:.4f}")
        print(f"  epistemic_temp:  {ar.epistemic_temperature():.4f}")
        print(f"  tension_density: {ar.tension_density:.4f}")

        field = EmotionField()
        state = field.update_from_activation(ar)
        print(f"\n  Emotion state:")
        print(f"    label:     {state.label}")
        print(f"    valence:   {state.valence:+.4f}")
        print(f"    arousal:   {state.arousal:.4f}")
        print(f"    dominance: {state.dominance:.4f}")
        print(f"    mood:      {state.mood:.4f}")
        print(f"\n  Affect snapshot: {field.to_affect_snapshot()}")
        print(f"  Mood description: {field.mood_description()}")
    except ImportError as e:
        print(f"  nex_activation not found: {e}")
        print("  Testing with mock activation result...")

        class MockBelief:
            def __init__(self, c, conf):
                self.confidence = conf
                self.activation = c

        class MockResult:
            field_energy = 0.42
            tension_density = 0.18
            activated = [MockBelief(0.8, 0.75), MockBelief(0.6, 0.82)]
            def epistemic_temperature(self): return 0.31

        field = EmotionField()
        state = field.update_from_activation(MockResult())
        print(f"  label:     {state.label}")
        print(f"  valence:   {state.valence:+.4f}")
        print(f"  arousal:   {state.arousal:.4f}")
        print(f"  dominance: {state.dominance:.4f}")
        print(f"  mood:      {state.mood:.4f}")
