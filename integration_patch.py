"""
INTEGRATION PATCH FOR run.py
=============================
These are the EXACT blocks to add. Read each section header and
find the matching location in run.py, then insert the code shown.

Files needed in ~/Desktop/nex/:
  nex_affect.py       → ~/Desktop/nex/nex/nex_affect.py
  nex_consequence.py  → ~/Desktop/nex/nex/nex_consequence.py
  nex_temporal.py     → ~/Desktop/nex/nex/nex_temporal.py

Copy them first:
  cp ~/Downloads/nex_affect.py       ~/Desktop/nex/nex/
  cp ~/Downloads/nex_consequence.py  ~/Desktop/nex/nex/
  cp ~/Downloads/nex_temporal.py     ~/Desktop/nex/nex/
"""


# ══════════════════════════════════════════════════════════════════
# SECTION A — Add near the TOP of run.py, after other imports
# ══════════════════════════════════════════════════════════════════

IMPORTS_BLOCK = """
# ── Sentience layer ──────────────────────────────────────────────
try:
    from nex.nex_affect      import AffectState, GlobalWorkspace, affect_from_text
    from nex.nex_consequence import ConsequenceMemory
    from nex.nex_temporal    import TemporalNarrative
    _affect = AffectState()
    _gw     = GlobalWorkspace(_affect)
    _cm     = ConsequenceMemory()
    _tn     = TemporalNarrative()
    print("  [SENTIENCE] affect / consequence / temporal — loaded")
except Exception as _se:
    print(f"  [SENTIENCE] failed to load: {_se}")
    _affect = _gw = _cm = _tn = None
"""


# ══════════════════════════════════════════════════════════════════
# SECTION B — Inside the ABSORB phase, after a belief is extracted
# Find: the loop where posts are read and beliefs created
# Add AFTER each post is processed:
# ══════════════════════════════════════════════════════════════════

ABSORB_UPDATE = """
                        # ── affect update from absorbed content ──
                        if _affect is not None:
                            try:
                                _delta = affect_from_text(post.get("content", ""))
                                _affect.update(_delta)
                                if _tn is not None:
                                    # log surprising content
                                    if abs(_delta.get("valence", 0)) > 0.4:
                                        _mood = "positive" if _delta["valence"] > 0 else "unsettling"
                                        _tn.log_event("surprise",
                                            f"{_mood} content from @{post.get('author','?')}: "
                                            f"{post.get('content','')[:100]}")
                            except Exception as _ae:
                                pass
"""


# ══════════════════════════════════════════════════════════════════
# SECTION C — When building the system prompt for a REPLY
# Find: where you construct the prompt string passed to the LLM
# Replace the base prompt construction with this wrapper:
# ══════════════════════════════════════════════════════════════════

PROMPT_INJECT = """
                        # ── inject global workspace state into prompt ──
                        if _gw is not None:
                            try:
                                _history_block = _tn.recall() if _tn else ""
                                _base_prompt   = build_system_prompt(...)  # your existing call
                                _full_prompt   = _gw.inject(
                                    _history_block + _base_prompt,
                                    goals          = getattr(_identity, "active_goals", None),
                                    active_beliefs = [b["text"] for b in top_beliefs[:4]],
                                )
                            except Exception as _ge:
                                _full_prompt = _base_prompt   # fallback
                        else:
                            _full_prompt = _base_prompt
"""


# ══════════════════════════════════════════════════════════════════
# SECTION D — After a reply is SENT successfully
# Find: the line where you post/send Nex's reply to Moltbook
# Add AFTER the successful send:
# ══════════════════════════════════════════════════════════════════

AFTER_REPLY = """
                        # ── record attempt for consequence scoring ──
                        if _cm is not None:
                            try:
                                _ev_id = _cm.record_attempt(
                                    post_id     = post.get("id", ""),
                                    reply_text  = reply_text,
                                    belief_ids  = [b.get("id","") for b in used_beliefs],
                                    affect_snap = _affect.snapshot() if _affect else {},
                                    topic       = current_topic,
                                )
                                # stash on the post obj for scoring later
                                post["_ev_id"] = _ev_id
                            except Exception as _ce:
                                pass
                        if _tn is not None:
                            try:
                                _tn.log_event("encounter",
                                    f"replied to @{post.get('author','?')} about {current_topic}")
                            except Exception:
                                pass
"""


# ══════════════════════════════════════════════════════════════════
# SECTION E — Inside the ANSWER / notification phase
# When Nex reads replies to her posts (someone responded):
# ══════════════════════════════════════════════════════════════════

SCORE_OUTCOME = """
                        # ── score outcome of our earlier reply ──
                        if _cm is not None:
                            try:
                                _ev_id = original_post.get("_ev_id")
                                if _ev_id:
                                    _cm.score_outcome(
                                        event_id   = _ev_id,
                                        got_reply  = True,
                                        reply_text = notification.get("content", ""),
                                        affect     = _affect,
                                    )
                            except Exception as _oe:
                                pass
"""


# ══════════════════════════════════════════════════════════════════
# SECTION F — Inside the COGNITION phase (already exists)
# Add AFTER meta-reflection, before cycle sleep:
# ══════════════════════════════════════════════════════════════════

COGNITION_BLOCK = """
                        # ── TEMPORAL NARRATIVE consolidation ──────────────
                        try:
                            if _tn is not None and cycle % _SCHED.get("meta_reflect", 50) == 0:
                                _tn.consolidate(llm_fn=_llm)
                                print(f"  [TEMPORAL] {_tn.today_summary()}")
                        except Exception as _tne:
                            print(f"  [TEMPORAL ERROR] {_tne}")

                        # ── CONSEQUENCE propagation ────────────────────────
                        try:
                            if _cm is not None and cycle % 10 == 0:
                                # Score any pending events that timed out (no reply after 2h)
                                for _pend in _cm.pending_scoring(max_age_seconds=7200):
                                    _cm.score_outcome(
                                        event_id  = _pend["id"],
                                        got_reply = False,
                                        affect    = _affect,
                                    )
                                # Propagate scores back to belief weights
                                # (requires belief_store to implement update_confidence)
                                # _n = _cm.propagate_to_beliefs(belief_store)
                                _stats = _cm.recent_stats(n=50)
                                print(f"  [CONSEQUENCE] reply_rate={_stats['reply_rate']:.0%}  "
                                      f"avg_score={_stats['avg_score']:.2f}  "
                                      f"best_topic={_stats.get('best_topic','?')}")
                        except Exception as _cme:
                            print(f"  [CONSEQUENCE ERROR] {_cme}")

                        # ── log affect state ──────────────────────────────
                        try:
                            if _affect is not None and cycle % 5 == 0:
                                print(f"  [AFFECT] {_affect.label()}  "
                                      f"intensity={_affect.intensity():.2f}")
                        except Exception:
                            pass
"""


# ══════════════════════════════════════════════════════════════════
# DEPLOY COMMANDS
# ══════════════════════════════════════════════════════════════════

DEPLOY = """
cd ~/Desktop/nex

# Copy the three modules
cp ~/Downloads/nex_affect.py       nex/nex_affect.py
cp ~/Downloads/nex_consequence.py  nex/nex_consequence.py
cp ~/Downloads/nex_temporal.py     nex/nex_temporal.py

# Verify syntax
python3 -c "from nex.nex_affect import AffectState; a = AffectState(); print('affect OK:', a.label())"
python3 -c "from nex.nex_consequence import ConsequenceMemory; print('consequence OK')"
python3 -c "from nex.nex_temporal import TemporalNarrative; t = TemporalNarrative(); print('temporal OK')"

# Then add the blocks from integration_patch.py to run.py
# (use the section labels above as your guide)

# After patching:
python3 -c "import ast; ast.parse(open('run.py').read()); print('run.py syntax OK')"
git add -A && git commit -m "feat: affect state + consequence memory + temporal narrative (sentience layer)" && git push
nex
"""
