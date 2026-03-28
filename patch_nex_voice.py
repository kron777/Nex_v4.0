#!/usr/bin/env python3
"""
patch_nex_voice.py — Apply 3 surgical fixes to nex_voice.py
Run from ~/Desktop/nex:
    python3 patch_nex_voice.py

Fixes:
  1. _assemble()        — guaranteed non-empty output when frags=[]
  2. _choose_strategy() — no frags + question → 'reflect' not 'question'
  3. compose()          — fallback chain goes to nex_reason, not llama
"""

from pathlib import Path
import sys

TARGET = Path(__file__).parent / "nex" / "nex_voice.py"
if not TARGET.exists():
    TARGET = Path(__file__).parent / "nex_voice.py"
if not TARGET.exists():
    print(f"ERROR: cannot find nex_voice.py near {__file__}")
    sys.exit(1)

src = TARGET.read_text()
original = src
patches_applied = 0

# ══════════════════════════════════════════════════════════════════════════════
# PATCH 1 — _assemble(): identity-anchor fallback when frags is empty
# Inserts a guaranteed reply block at the top of _assemble before parts=[]
# ══════════════════════════════════════════════════════════════════════════════

OLD_ASSEMBLE_TAIL = '''        parts = []
        used = set()

        def _add(s: str):
            s = s.strip()
            if s and s not in used and len(s) > 10:
                used.add(s)
                parts.append(s)

        f0 = _own(frags[0]) if frags else ""
        f1 = _own(frags[1]) if len(frags) > 1 else ""
        f2 = _own(frags[2]) if len(frags) > 2 else ""'''

NEW_ASSEMBLE_TAIL = '''        parts = []
        used = set()

        def _add(s: str):
            s = s.strip()
            if s and s not in used and len(s) > 10:
                used.add(s)
                parts.append(s)

        f0 = _own(frags[0]) if frags else ""
        f1 = _own(frags[1]) if len(frags) > 1 else ""
        f2 = _own(frags[2]) if len(frags) > 2 else ""

        # ── SPARSE FALLBACK: no belief frags at all ───────────────────────────
        # Build a reply entirely from identity anchors + opinion + tension.
        # This fires when belief retrieval returns nothing for the query.
        # Never returns empty — guarantees > 20 chars so llama is never called.
        if not frags:
            _anchor_parts = []
            if opinion:
                _anchor_parts.append(opinion.rstrip(".") + ".")
            if tension:
                _anchor_parts.append(
                    f"What I haven't settled on this: {tension.rstrip('.')}."
                )
            if _values:
                _v = next(
                    (v for v in _values
                     if any(w in query.lower() for w in v.lower().split() if len(w) > 4)),
                    _values[0]
                )
                _anchor_parts.append(
                    f"The frame I keep returning to: {_v.rstrip('.')}."
                )
            if not _anchor_parts:
                # Absolute last resort — identity commitment sentence
                _anchor_parts.append(
                    "I don't have dense beliefs on this yet — "
                    "but I'd rather sit with the question than fake certainty I haven't earned."
                )
            return " ".join(_anchor_parts)
        # ─────────────────────────────────────────────────────────────────────'''

if OLD_ASSEMBLE_TAIL in src:
    src = src.replace(OLD_ASSEMBLE_TAIL, NEW_ASSEMBLE_TAIL)
    patches_applied += 1
    print("  [1/3] _assemble() sparse fallback — APPLIED ✓")
else:
    print("  [1/3] _assemble() sparse fallback — PATTERN NOT FOUND (check manually)")


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 2 — _choose_strategy(): return 'reflect' not 'question' by default
# 'question' strategy with empty frags = guaranteed empty output
# 'reflect' with identity anchor = always produces something
# ══════════════════════════════════════════════════════════════════════════════

OLD_STRATEGY = '''    if is_question:
        return "question"

    if affect_tone == "sharp":
        return "pushback"

    return "reflect"'''

NEW_STRATEGY = '''    if is_question:
        # Only return 'question' if there are beliefs to anchor it.
        # Without frags the question strategy produces empty output.
        # Caller uses 'reflect' which has the identity-anchor fallback.
        return "question"

    if affect_tone == "sharp":
        return "pushback"

    return "reflect"'''

# The real fix: default bare return becomes 'reflect', and we add a
# _choose_strategy_safe wrapper that the compositor calls instead.
OLD_STRATEGY_FULL = '''def _choose_strategy(
    query: str,
    has_opinion: bool,
    has_tension: bool,
    affect_tone: str,
    pressure: float,
) -> str:
    """
    Returns one of: assert | question | pushback | hold_tension | reflect
    """
    q = query.lower()

    # Explicit question → question back or assert
    is_question = q.rstrip().endswith("?") or q.startswith(("what", "why", "how", "do you", "can you", "is ", "are "))

    if has_opinion and not is_question:
        return "assert"

    if has_tension and affect_tone in ("contemplative", "focused"):
        return "hold_tension"

    if is_question and pressure > 0.5:
        return "assert"

    if is_question:
        return "question"

    if affect_tone == "sharp":
        return "pushback"

    return "reflect"'''

NEW_STRATEGY_FULL = '''def _choose_strategy(
    query: str,
    has_opinion: bool,
    has_tension: bool,
    affect_tone: str,
    pressure: float,
    has_frags: bool = True,      # NEW: passed by compositor
) -> str:
    """
    Returns one of: assert | question | pushback | hold_tension | reflect

    'question' strategy requires belief frags to be non-empty — if frags are
    absent, it falls back to 'reflect' which uses the identity-anchor path.
    """
    q = query.lower()

    is_question = q.rstrip().endswith("?") or q.startswith(
        ("what", "why", "how", "do you", "can you", "is ", "are ")
    )

    if has_opinion and not is_question:
        return "assert"

    if has_tension and affect_tone in ("contemplative", "focused"):
        return "hold_tension"

    if is_question and pressure > 0.5:
        return "assert"

    if is_question:
        # Without frags, 'question' produces empty output — route to reflect
        return "question" if has_frags else "reflect"

    if affect_tone == "sharp":
        return "pushback"

    return "reflect"'''

if OLD_STRATEGY_FULL in src:
    src = src.replace(OLD_STRATEGY_FULL, NEW_STRATEGY_FULL)
    patches_applied += 1
    print("  [2/3] _choose_strategy() has_frags guard — APPLIED ✓")
else:
    print("  [2/3] _choose_strategy() has_frags guard — PATTERN NOT FOUND (check manually)")

# Also update the call site inside compose() to pass has_frags
OLD_STRATEGY_CALL = '''        strategy  = _choose_strategy(
            query,
            has_opinion  = opinion is not None,
            has_tension  = tension is not None,
            affect_tone  = self.tone,
            pressure     = self.pressure.pressure,
        )'''

NEW_STRATEGY_CALL = '''        strategy  = _choose_strategy(
            query,
            has_opinion  = opinion is not None,
            has_tension  = tension is not None,
            affect_tone  = self.tone,
            pressure     = self.pressure.pressure,
            has_frags    = bool(frags),   # guard: no frags → no 'question'
        )'''

if OLD_STRATEGY_CALL in src:
    src = src.replace(OLD_STRATEGY_CALL, NEW_STRATEGY_CALL)
    print("     → _choose_strategy call site updated ✓")
else:
    print("     → _choose_strategy call site NOT FOUND (check manually)")


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 3 — module-level compose(): replace llama fallback with nex_reason
# The voice_wrapper path eventually calls _complete() → llama → dead server
# Replace it with nex_reason.reason() which is fully LLM-free
# ══════════════════════════════════════════════════════════════════════════════

OLD_COMPOSE = '''def compose(user_input: str) -> str:
    """Module-level shortcut — NexVoice compositor with conversational fallback."""
    import time
    # Nex pauses before responding — she thinks, not reacts
    time.sleep(3)
    # Try NexVoice compositor
    try:
        result = get_compositor().compose(user_input)
        if (result and isinstance(result, str) and len(result.strip()) > 15
                and "bayesian belief updating" not in result.lower()[:60]
                and "what i haven" not in result.lower()[:30]
                and "i don't have enough" not in result.lower()[:40]):
            return result
    except Exception:
        pass
    # Conversational wrapper fallback
    try:
        from nex.nex_voice_wrapper import compose_reply
        return compose_reply(user_input)
    except ImportError:
        try:
            from nex_voice_wrapper import compose_reply
            return compose_reply(user_input)
        except ImportError:
            pass
    return "Still processing. Ask me something else."'''

NEW_COMPOSE = '''def compose(user_input: str) -> str:
    """
    Module-level shortcut — NexVoice compositor, LLM-free.
    Fallback chain:
      1. NexVoiceCompositor (full signal pipeline)
      2. nex_reason.reason()  (belief-graph reasoning, LLM-free)
      3. Identity-anchor sentence (always non-empty)
    llama / nex_voice_wrapper are NOT in this chain.
    """
    import time
    # Nex pauses before responding — she thinks, not reacts
    time.sleep(3)

    # ── 1. Full compositor ────────────────────────────────────────────
    try:
        result = get_compositor().compose(user_input)
        _bad = (
            "bayesian belief updating" in result.lower()[:80] or
            "what i haven" in result.lower()[:40] or
            "i don't have enough" in result.lower()[:40] or
            "still processing" in result.lower()[:40]
        )
        if result and isinstance(result, str) and len(result.strip()) > 20 and not _bad:
            return result
    except Exception:
        pass

    # ── 2. nex_reason — belief-graph reasoning, zero LLM ─────────────
    try:
        from nex.nex_reason import reason as _reason
        r = _reason(user_input)
        reply = r.get("reply", "")
        # Only accept if it's substantive and not the canned 'question' dead-end
        if (reply
                and len(reply) > 25
                and "sparse here" not in reply
                and "belief graph is sparse" not in reply):
            return reply
    except Exception:
        pass

    # ── 3. nex_reason with debug=False — try again, accept any output ─
    try:
        from nex.nex_reason import reason as _reason
        r = _reason(user_input)
        reply = r.get("reply", "")
        if reply and len(reply) > 15:
            return reply
    except Exception:
        pass

    # ── 4. Hard identity anchor — never returns empty ─────────────────
    # Pull one anchor from DB, else use core commitment
    _anchor = "Truth first. I'd rather say I don't know than produce noise."
    try:
        import sqlite3 as _sq
        _db = _sq.connect(str(DB_PATH))
        _row = _db.execute(
            "SELECT content FROM beliefs WHERE is_identity=1 AND confidence > 0.8 "
            "ORDER BY confidence DESC LIMIT 1"
        ).fetchone()
        _db.close()
        if _row and _row[0]:
            _anchor = _row[0].strip().rstrip(".") + "."
    except Exception:
        pass
    return _anchor'''

if OLD_COMPOSE in src:
    src = src.replace(OLD_COMPOSE, NEW_COMPOSE)
    patches_applied += 1
    print("  [3/3] compose() fallback chain → nex_reason — APPLIED ✓")
else:
    print("  [3/3] compose() fallback chain — PATTERN NOT FOUND (check manually)")


# ══════════════════════════════════════════════════════════════════════════════
# Write + validate
# ══════════════════════════════════════════════════════════════════════════════

if patches_applied == 0:
    print("\nNo patches applied — source may have changed. Diff manually.")
    sys.exit(1)

TARGET.write_text(src)
print(f"\n  Wrote {TARGET}")

import subprocess
r = subprocess.run(["python3", "-m", "py_compile", str(TARGET)], capture_output=True)
if r.returncode == 0:
    print("  Syntax OK ✓")
else:
    print(f"  SYNTAX ERROR: {r.stderr.decode()[:300]}")
    # Restore original
    TARGET.write_text(original)
    print("  Restored original — patch aborted.")
    sys.exit(1)

print(f"\n  {patches_applied}/3 patches applied.")
print("\n  What changed:")
print("    1. _assemble()        — empty frags → identity anchor reply (never empty)")
print("    2. _choose_strategy() — question + no frags → reflect (not dead-end)")
print("    3. compose()          — fallback chain: compositor → nex_reason → anchor")
print("                           llama / nex_voice_wrapper REMOVED from chain")
print("\n  Next: restart Nex and test with a topic she has sparse beliefs on.")
print("  Expected: she replies from identity/anchor rather than timing out.")
