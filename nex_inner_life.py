"""
nex_inner_life.py — Phase 5: Emergent Emotion
==============================================
Place at: ~/Desktop/nex/nex_inner_life.py

Previously delegated to nex_mood_hmm and nex_affect_valence (rule-based).
Now reads directly from nex_emotion_field — emotion emerges from the
belief graph, not from programmed state machines.

No rules. No HMM. Inner life precipitates from field energy.
"""

# ── NEX v4 groq shim (preserved) ─────────────────────────────
try:
    from nex.nex_groq_shim import _groq, _call_groq, call_groq
except ImportError:
    try:
        from nex_groq_shim import _groq, _call_groq, call_groq
    except ImportError:
        pass
# ─────────────────────────────────────────────────────────────

import nex_emotion_field as _ef


def get_current_inner_state() -> str:
    mood  = _ef.mood()
    label = _ef.current_label()
    report = _ef.self_report()
    return f"[INNER LIFE] {mood:.3f} / {label} — {report}"


def run_inner_life_cycle(cycle: int = 0, metrics: dict = None) -> dict:
    """
    Drop-in for the old run_inner_life_cycle call in run.py.
    Now reads from nex_emotion_field instead of rule-based state machine.
    """
    mood  = _ef.mood()
    label = _ef.current_label()
    report = _ef.self_report()
    state = _ef._get_field().current()
    return {
        "mood":       mood,
        "label":      label,
        "report":     report,
        "valence":    state.valence,
        "arousal":    state.arousal,
        "dominance":  state.dominance,
        "cycle":      cycle,
    }
