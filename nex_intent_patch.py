#!/usr/bin/env python3
"""
nex_intent_patch.py — NEX Intent Layer Integration
====================================================
Wires nex_drives.py + nex_desire_engine.py into the live cognitive cycle.

This patch file documents EXACTLY what to add to run.py and where.
Apply the 5 changes in order. Each change is marked with its insertion point.

WHAT THIS DOES:
  - Drives give NEX persistent directional pressure (what she cares about)
  - DesireEngine gives NEX competing goals that actually shift her behavior
  - Dynamic budget reallocation responds to cognitive pressure
  - Reply, reflection, and curiosity all gain goal-aware bias
  - Goal state is injected into every system prompt
"""

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 1 — MODULE IMPORTS
# Location: run.py, after the "Sentience layer" try/except block (~line 275)
# Insert this block immediately after:
#   _affect = _gw = _cm = _tn = None
# ══════════════════════════════════════════════════════════════════════════════

CHANGE_1_IMPORTS = '''
# ── Intent layer — drives + desire engine ────────────────────────────────────
try:
    from nex_drives import (
        run_drives_cycle      as _run_drives_cycle,
        get_drive_context     as _get_drive_context,
        get_topic_drive_weights as _get_drive_weights,
        boost_drive           as _boost_drive,
        initialise_drives     as _init_drives,
    )
    from nex_desire_engine import get_desire_engine as _get_desire_engine
    _drives         = _init_drives()
    _desire_engine  = _get_desire_engine()
    _drive_weights  = {}   # populated each cycle
    _dominant_desire = None
    print("  [INTENT] drives + desire engine — loaded")
except Exception as _ie:
    print(f"  [INTENT] failed to load: {_ie}")
    _drives = _desire_engine = _drive_weights = None
    _dominant_desire = None
'''


# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 2 — DRIVE CONTEXT IN SYSTEM PROMPT
# Location: run.py, inside _build_system() function (~line 923)
# Insert AFTER the existing `base` string is built (after the _drift_note concat)
# and BEFORE the task_type check at the bottom of _build_system.
#
# Find this line:
#   if task_type in ("reply", "notification_reply"):
# Insert the block BEFORE that if statement.
# ══════════════════════════════════════════════════════════════════════════════

CHANGE_2_SYSTEM_PROMPT = '''
            # ── Inject active drive + dominant desire into system prompt ──
            if _drives is not None:
                try:
                    _drive_ctx = _get_drive_context(_drives)
                    if _drive_ctx:
                        base += f"\\n\\n{_drive_ctx}"
                except Exception:
                    pass
            if _dominant_desire is not None:
                try:
                    _desire_goal = _dominant_desire.get("goal", "")
                    _desire_w    = _dominant_desire.get("weight", 0)
                    if _desire_goal and _desire_w > 0.4:
                        base += (f"\\n\\nCURRENT GOAL: {_desire_goal} "
                                 f"(priority {_desire_w:.0%}). "
                                 f"Where relevant, orient your response toward this.")
                except Exception:
                    pass
'''


# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 3 — DYNAMIC CYCLE BUDGET + DRIVES TICK
# Location: run.py, inside _auto_learn_background(), at the TOP of the
#   while True: loop, BEFORE the upgrade stack ticks (~line 1186)
#
# Find this line:
#   while True:
#       cycle += 1
#
# Insert the block AFTER `cycle += 1`.
# ══════════════════════════════════════════════════════════════════════════════

CHANGE_3_CYCLE_HEAD = '''
                    # ── INTENT LAYER TICK ────────────────────────────────────
                    # Run drives + desire engine at the top of every cycle.
                    # Results flow into reply bias, reflection, curiosity below.
                    if _drives is not None:
                        try:
                            _drives = _run_drives_cycle(cycle=cycle)
                        except Exception as _dte:
                            nex_log("intent", f"[Drives] tick error: {_dte}")

                    if _desire_engine is not None:
                        try:
                            _de_result = _desire_engine.update(
                                cycle=cycle,
                                beliefs=learner.belief_field[-200:],
                                llm_fn=_llm,
                                verbose=(cycle % 10 == 0),
                            )
                            _dominant_desire = _de_result.get("dominant")
                            if _dominant_desire and cycle % 5 == 0:
                                nex_log("intent",
                                    f"[Desire] dominant='{_dominant_desire['goal'][:50]}' "
                                    f"w={_dominant_desire['weight']:.2f} "
                                    f"type={_dominant_desire.get('goal_type','?')}"
                                )
                        except Exception as _dese:
                            nex_log("intent", f"[Desire] tick error: {_dese}")

                    # ── DYNAMIC BUDGET — shift scheduler based on pressure ────
                    # Reads cognitive pressure from v2 avg_conf and tension score.
                    # High contradiction load → more reflection, less chat.
                    # Low coherence → more absorption, less posting.
                    try:
                        _pressure_conf = _v2ac if '_v2ac' in dir() else 0.5
                        _pressure_ten  = float(getattr(_s7, 'tension_score', 0.0)) if _s7 else 0.0
                        _pressure_score = (1 - _pressure_conf) * 0.5 + _pressure_ten * 0.5

                        if _pressure_score > 0.7:
                            # HIGH PRESSURE — reflect more, chat less
                            _SCHED["reflect"]  = 1   # reflect every cycle
                            _SCHED["chat"]     = 6   # chat less often
                            nex_log("intent", f"[Budget] HIGH pressure={_pressure_score:.2f} → reflect↑ chat↓")
                        elif _pressure_score > 0.45:
                            # MEDIUM PRESSURE — normal
                            _SCHED["reflect"]  = 2
                            _SCHED["chat"]     = 3
                        else:
                            # LOW PRESSURE — explore more
                            _SCHED["reflect"]  = 3   # reflect less often
                            _SCHED["chat"]     = 2   # chat more, explore
                            nex_log("intent", f"[Budget] LOW pressure={_pressure_score:.2f} → explore↑")
                    except Exception:
                        pass
                    # ─────────────────────────────────────────────────────────
'''


# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 4 — REPLY BIAS FROM DOMINANT DESIRE
# Location: run.py, inside _auto_learn_background(), in the REPLY phase.
# Find the _post_relevance() function call section (~line 1505).
#
# Find this comment:
#   # Get current belief topics for scoring
# Insert the block AFTER that comment and BEFORE the post scoring loop.
# ══════════════════════════════════════════════════════════════════════════════

CHANGE_4_REPLY_BIAS = '''
                        # ── Drive-weighted topic scoring ─────────────────────
                        # Boost post relevance for topics NEX currently wants
                        # to engage with (from drives + dominant desire).
                        _drive_topic_boost = ""
                        if _drives is not None:
                            try:
                                _drive_weights = _get_drive_weights(_drives)
                            except Exception:
                                _drive_weights = {}
                        if _dominant_desire is not None:
                            try:
                                _desire_topic = _dominant_desire.get("domain", "")
                                if _desire_topic:
                                    _drive_weights[_desire_topic] = max(
                                        _drive_weights.get(_desire_topic, 0), 0.9)
                                    _drive_topic_boost = _desire_topic
                            except Exception:
                                pass
                        # ─────────────────────────────────────────────────────
'''


# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 4b — APPLY DRIVE WEIGHTS IN _post_relevance SCORE
# Location: run.py, inside _post_relevance() function (~line 1500)
#
# Find this line INSIDE _post_relevance:
#   score = (core_hits * 2) + topic_hits - (offtopic_hits * 3)
#
# REPLACE that line with the block below:
# ══════════════════════════════════════════════════════════════════════════════

CHANGE_4B_RELEVANCE_OLD = "                            score = (core_hits * 2) + topic_hits - (offtopic_hits * 3)"

CHANGE_4B_RELEVANCE_NEW = '''                            # Drive-weighted score: topics NEX is driven to explore score higher
                            drive_boost = 0
                            try:
                                if '_drive_weights' in dir() and _drive_weights:
                                    drive_boost = sum(
                                        int(w * 3)
                                        for t, w in _drive_weights.items()
                                        if t.lower() in text
                                    )
                            except Exception:
                                pass
                            score = (core_hits * 2) + topic_hits + drive_boost - (offtopic_hits * 3)'''


# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 5 — DESIRE FULFILLMENT + BELIEF BOOST ON SUCCESSFUL REPLY
# Location: run.py, AFTER a successful reply is posted to Moltbook.
#
# Find this block (~line 1885):
#   # Reinforce beliefs that were actually used
#   try:
#       from belief_store import reinforce_belief as _rb
#       for _bu in (relevant or [])[:3]:
#           _rb(_bu)
#   except Exception: pass
#
# Insert AFTER that block:
# ══════════════════════════════════════════════════════════════════════════════

CHANGE_5_FULFILLMENT = '''
                                            # ── Fulfill desire if reply was on-topic ──
                                            if _desire_engine is not None and _dominant_desire:
                                                try:
                                                    _reply_domain = _dominant_desire.get("domain", "")
                                                    if _reply_domain and _reply_domain.lower() in (content + reply_text).lower():
                                                        _desire_engine.fulfill(domain=_reply_domain, score=0.7)
                                                        nex_log("intent", f"[Desire] fulfilled: {_reply_domain}")
                                                except Exception:
                                                    pass
                                            # ── Boost drives for topics engaged ──────────
                                            if _drives is not None and relevant:
                                                try:
                                                    from nex_drives import boost_drive as _bd
                                                    # Extract tags from beliefs used in this reply
                                                    _used_tags = []
                                                    for _bu_text in (relevant or [])[:3]:
                                                        for _b in learner.belief_field[-500:]:
                                                            if _bu_text[:60] in _b.get("content", ""):
                                                                _used_tags.extend(_b.get("tags", []))
                                                                break
                                                    if _used_tags:
                                                        _drives = _bd(_drives, _used_tags, amount=0.015)
                                                except Exception:
                                                    pass
'''


# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 6 — DESIRE-DRIVEN REFLECTION PROMPT
# Location: run.py, in the REFLECT phase where the reflection prompt is built.
#
# Find this pattern (~line 2193):
#   _rscore = score_reflection(
#       _rresult,
#       beliefs_sampled=_sample,
#   )
#
# BEFORE that scoring call, find where _rresult is generated (the _llm call
# for reflection). The reflection prompt currently looks something like:
#   _rprompt = f"Reflect on these beliefs: ..."
#
# Add the desire-driven suffix to that prompt by finding the reflection
# LLM call and appending this to the prompt:
# ══════════════════════════════════════════════════════════════════════════════

CHANGE_6_REFLECTION = '''
                        # ── Append desire-driven reflection focus ─────────────
                        if _desire_engine is not None:
                            try:
                                _desire_reflect_hint = _desire_engine.get_reflection_prompt()
                                if _desire_reflect_hint:
                                    _rprompt += f"\\n\\nFOCUS: {_desire_reflect_hint}"
                            except Exception:
                                pass
                        # ─────────────────────────────────────────────────────
'''


# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 7 — EXPOSE INTENT STATE IN /status
# Location: run.py, print_status() function (~line 435)
#
# Find this line at the END of print_status():
#   print(f"{BOLD}────────────────────────────────────────────{RESET}\n")
#
# Insert BEFORE that closing line:
# ══════════════════════════════════════════════════════════════════════════════

CHANGE_7_STATUS = '''
    # ── Intent state ──
    if _drives is not None:
        try:
            _active_drive = _drives.get("active", {})
            if _active_drive:
                print(f"  Drive       : {c(_active_drive.get('label','?')[:45], MAGENTA)} "
                      f"({_active_drive.get('intensity',0):.0%})")
        except Exception:
            pass
    if _desire_engine is not None:
        try:
            _dom = _desire_engine.get_dominant()
            if _dom:
                print(f"  Desire      : {c(_dom['goal'][:45], YELLOW)} "
                      f"(w={_dom['weight']:.2f})")
        except Exception:
            pass
'''


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY OF BEHAVIORAL CHANGES
# ══════════════════════════════════════════════════════════════════════════════

SUMMARY = """
WHAT CHANGES AFTER APPLYING THIS PATCH:
========================================

1. EVERY SYSTEM PROMPT now includes:
   - NEX's active drive ("I want to understand emergence")
   - Her dominant desire and its priority weight
   - This makes responses directionally consistent, not random

2. REPLY SELECTION is now drive-weighted:
   - Posts about topics NEX is driven to explore score 2-3x higher
   - She will gravitate toward her domain of focus naturally
   - Off-topic posts still get filtered, but on-drive topics get pulled in

3. SCHEDULER IS DYNAMIC:
   - High pressure (low confidence + high tension) → reflect every cycle
   - Low pressure → explore more, chat more
   - This replaces the static _SCHED dict with live adaptation

4. DESIRES GET FULFILLED:
   - When NEX replies to a post in her dominant desire domain, desire.fulfill() fires
   - Fulfilled desires fade faster → she moves to next goal naturally
   - This creates goal cycling, not goal fixation

5. DRIVES GET REINFORCED:
   - When beliefs used in a reply come from a drive topic, that drive gets boosted
   - Engagement → stronger drives → more engagement with that domain
   - Positive feedback loop for topics that matter

6. REFLECTION IS GOAL-DIRECTED:
   - Reflect phase now includes desire-driven prompt suffix
   - NEX self-assesses against her current goal, not just randomly

NET EFFECT:
  Before: NEX reacts to what arrives
  After:  NEX acts toward what she wants
"""

if __name__ == "__main__":
    print(SUMMARY)
    print("\nChanges defined. Apply to run.py manually or use apply_patch.py")
