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

# ── run_inner_life_cycle — added by nex_brain_repair.sh ──────────────────────
def run_inner_life_cycle(cycle: int = 0, metrics: dict = None) -> dict:
    """
    Called every cycle by run.py.
    Returns dict with emotion, diary, self_model keys.
    """
    result = {"emotion": None, "diary": "", "self_model": ""}
    try:
        state = get_current_inner_state()
        result["emotion"] = state
    except Exception:
        pass
    try:
        mood = _mood_mod.current()
        result["diary"] = f"cycle={cycle} mood={mood}"
    except Exception:
        pass
    try:
        label = _valence_mod.current_label()
        result["self_model"] = f"valence={label}"
        result["emotion"] = result["emotion"] or label
    except Exception:
        pass
    # Apply metrics to modulate mood if available
    if metrics:
        try:
            conf = metrics.get("belief_confidence", 0.5)
            if conf > 0.7:
                result["diary"] += " — high coherence"
            elif conf < 0.3:
                result["diary"] += " — low coherence, seeking resolution"
        except Exception:
            pass
    return result
