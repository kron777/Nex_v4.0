"""nex_inner_life.py — stub created by sentience upgrade"""
import nex_mood_hmm as _mood_mod
import nex_affect_valence as _valence_mod
# ── NEX v4 groq shim ─────────────────────────────────────────
try:
    from nex.nex_groq_shim import _groq, _call_groq, call_groq
except ImportError:
    try:
        from nex_groq_shim import _groq, _call_groq, call_groq
    except ImportError:
        pass
# ─────────────────────────────────────────────────────────────

def get_current_inner_state() -> str:
    mood = _mood_mod.current()
    label = _valence_mod.current_label()
    report = _mood_mod.self_report()
    return f"[INNER LIFE] {mood} / {label} — {report}"
