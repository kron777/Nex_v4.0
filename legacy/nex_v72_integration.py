"""
nex_v72_integration.py — NEX Architecture Upgrade Integration Harness
======================================================================
Wires all 8 upgrade modules into the live nex_v72 tick loop WITHOUT
requiring you to edit nex_v72.py directly.

HOW TO ACTIVATE:
    Add ONE line at the top of nex_v72.py (after existing imports):

        from nex_v72_integration import install_patches; install_patches()

    That's it. All phases are patched at import time.

WHAT IT PATCHES:
    ┌─────────────────────┬────────────────────────────────────────────────┐
    │ nex_v72 function    │ Upgrade injected                               │
    ├─────────────────────┼────────────────────────────────────────────────┤
    │ absorb / ingest     │ EFE ValueGate scores each signal before queue  │
    │ reason / retrieve   │ Hopfield memory as candidate retrieval layer   │
    │ compose_reason      │ Hebbian + hyperedge cluster-aware rerank        │
    │ reply (post-send)   │ Episode feedback fires Hebbian + cluster boost  │
    │ cognition_tick      │ Hebbian decay pass + fabric maintenance         │
    │ belief_save         │ Hopfield store updated on every belief write    │
    │ reflect             │ Quality score fed back to episode feedback      │
    └─────────────────────┴────────────────────────────────────────────────┘

SAFE FALLBACKS:
    Every patch is wrapped in try/except. If any upgrade module errors,
    nex_v72 continues running its original logic unchanged.
    Errors go to the nex.integration logger — watch with --debug.
"""

import sys
import time
import logging
import functools
import importlib
from typing import Callable, Any

logger = logging.getLogger("nex.integration")

# ── Lazy imports of upgrade modules ──────────────────────────────────────────

def _get(module_name: str, attr: str):
    """Lazy-import an upgrade module attribute. Returns None if unavailable."""
    try:
        mod = importlib.import_module(module_name)
        return getattr(mod, attr, None)
    except ImportError as e:
        logger.debug("[Integration] %s not found: %s", module_name, e)
        return None


# ── Patch helpers ─────────────────────────────────────────────────────────────

def _wrap(original_fn: Callable, pre=None, post=None) -> Callable:
    """
    Wrap a function with optional pre/post hooks.
    pre(args, kwargs) → (args, kwargs) or None (to skip original)
    post(result, args, kwargs) → result
    """
    @functools.wraps(original_fn)
    def wrapper(*args, **kwargs):
        # Pre-hook
        if pre is not None:
            try:
                modified = pre(args, kwargs)
                if modified is not None:
                    args, kwargs = modified
            except Exception as e:
                logger.warning("[Integration] pre-hook %s failed: %s",
                               original_fn.__name__, e)

        # Original function
        result = original_fn(*args, **kwargs)

        # Post-hook
        if post is not None:
            try:
                result = post(result, args, kwargs) or result
            except Exception as e:
                logger.warning("[Integration] post-hook %s failed: %s",
                               original_fn.__name__, e)

        return result
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 1 — ABSORB / INGEST: EFE ValueGate
# ══════════════════════════════════════════════════════════════════════════════

def _patch_absorb(nex_module):
    """
    Patch the absorb/ingest function to score signals through EFE ValueGate.
    Attaches efe_score to the signal object/dict before it enters the queue.
    """
    score_signal = _get("nex_efe_valuegate", "score_signal")
    if not score_signal:
        return

    # Try common function names used in nex_v72 for signal ingestion
    for fn_name in ("absorb_signal", "ingest", "absorb", "process_feed_item",
                    "queue_signal", "add_to_queue"):
        original = getattr(nex_module, fn_name, None)
        if original is None:
            continue

        def make_pre(fn_name_=fn_name):
            def pre(args, kwargs):
                # Extract content from first positional arg (signal text/dict)
                content = ""
                source  = "rss_feed"
                tags    = []

                if args:
                    a0 = args[0]
                    if isinstance(a0, str):
                        content = a0
                    elif isinstance(a0, dict):
                        content = a0.get("content", a0.get("text", a0.get("title", "")))
                        source  = a0.get("source", a0.get("platform", "rss_feed"))
                        tags    = a0.get("topics", a0.get("tags", []))

                if not content:
                    return None

                try:
                    efe = score_signal(content, source, tags)
                    # Attach route to signal for downstream use
                    if args and isinstance(args[0], dict):
                        args[0]["_efe_route"] = efe.route
                        args[0]["_efe_score"] = efe.efe
                    logger.debug("[EFE] %s → route=%s efe=%.3f",
                                 fn_name_, efe.route, efe.efe)
                except Exception as e:
                    logger.debug("[EFE] scoring failed: %s", e)
                return None  # pass args through unchanged
            return pre

        setattr(nex_module, fn_name, _wrap(original, pre=make_pre()))
        logger.info("[Integration] EFE ValueGate patched onto %s()", fn_name)
        break


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 2 — REASON / RETRIEVE: Hopfield memory candidate retrieval
# ══════════════════════════════════════════════════════════════════════════════

def _patch_reason(nex_module):
    """
    Patch reason/retrieve to use Hopfield memory for initial candidate retrieval.
    Falls back to original retrieval if Hopfield returns nothing.
    """
    hopfield_retrieve   = _get("nex_hopfield_memory", "hopfield_retrieve")
    hopfield_add        = _get("nex_hopfield_memory", "hopfield_add")
    init_hopfield       = _get("nex_hopfield_memory", "init_hopfield")

    if not hopfield_retrieve:
        return

    # Try to initialise Hopfield from the live DB
    if init_hopfield:
        import os
        db_candidates = [
            os.path.expanduser("~/Desktop/nex/nex_beliefs.db"),
            os.path.expanduser("~/Desktop/nex/nex.db"),
            os.path.expanduser("~/Desktop/nex/beliefs.db"),
        ]
        for db_path in db_candidates:
            if os.path.exists(db_path):
                try:
                    init_hopfield(db_path)
                    logger.info("[Integration] Hopfield loaded from %s", db_path)
                    break
                except Exception as e:
                    logger.warning("[Integration] Hopfield DB load failed: %s", e)

    # Patch retrieve functions
    for fn_name in ("retrieve_beliefs", "fetch_beliefs", "get_candidates",
                    "belief_search", "reason", "get_relevant_beliefs"):
        original = getattr(nex_module, fn_name, None)
        if original is None:
            continue

        def make_post(fn_name_=fn_name):
            def post(result, args, kwargs):
                """
                After original retrieval, also query Hopfield and merge results.
                Hopfield candidates that aren't in original results get appended
                (deduped by ID), giving associative recall on top of exact match.
                """
                query = ""
                if args and isinstance(args[0], str):
                    query = args[0]
                elif kwargs.get("query"):
                    query = kwargs["query"]

                if not query:
                    return result

                try:
                    hop_results = hopfield_retrieve(query, top_k=5)
                    if not hop_results:
                        return result

                    # Merge: build ID set from original results
                    if isinstance(result, list):
                        existing_ids = {
                            r.get("id", r.get("belief_id", "")) if isinstance(r, dict) else str(r)
                            for r in result
                        }
                        # Append Hopfield candidates not already present
                        for hr in hop_results:
                            if hr["id"] not in existing_ids:
                                result.append({
                                    "id":      hr["id"],
                                    "content": hr["text"],
                                    "score":   hr["score"] * 0.85,  # slight discount
                                    "_source": "hopfield",
                                    "meta":    hr["meta"],
                                })
                        logger.debug("[Hopfield] Merged %d associative candidates",
                                     len(hop_results))
                except Exception as e:
                    logger.debug("[Hopfield] merge failed: %s", e)

                return result
            return post

        setattr(nex_module, fn_name, _wrap(original, post=make_post()))
        logger.info("[Integration] Hopfield retrieval patched onto %s()", fn_name)


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 3 — COMPOSE / REPLY: Hebbian + hyperedge cluster rerank
# ══════════════════════════════════════════════════════════════════════════════

def _patch_compose(nex_module):
    """
    Patch compose_reason (or equivalent) to:
    1. Re-weight retrieved belief scores using Hebbian edge weights
    2. Re-rank using hyperedge cluster topology
    """
    reweight = _get("nex_hebbian_plasticity", "get_engine")
    rerank   = _get("nex_hyperedge_fabric",   "cluster_rerank")

    if not reweight and not rerank:
        return

    for fn_name in ("compose_reason", "compose_reply", "build_context",
                    "rank_candidates", "select_beliefs"):
        original = getattr(nex_module, fn_name, None)
        if original is None:
            continue

        def make_post():
            def post(result, args, kwargs):
                """
                result is expected to be a list of belief dicts with 'id' and 'score'.
                Apply Hebbian reweighting then hyperedge cluster reranking.
                """
                if not isinstance(result, list):
                    return result

                try:
                    # Hebbian reweighting
                    if reweight:
                        engine = reweight()
                        id_scores = [(r.get("id",""), r.get("score", 0.5))
                                     for r in result if isinstance(r, dict)]
                        if len(id_scores) > 1:
                            # Use top belief as query anchor
                            anchor_ids = [id_scores[0][0]] if id_scores else []
                            reweighted = engine.reweight_retrieval_scores(id_scores, anchor_ids)
                            score_map = {bid: score for bid, score in reweighted}
                            for r in result:
                                if isinstance(r, dict) and r.get("id") in score_map:
                                    r["score"] = score_map[r["id"]]

                    # Hyperedge cluster rerank
                    if rerank:
                        context_ids = [r.get("id","") for r in result[:2]
                                       if isinstance(r, dict)]
                        result = rerank(result, context_ids)

                except Exception as e:
                    logger.debug("[Compose] rerank failed: %s", e)

                return result
            return post

        setattr(nex_module, fn_name, _wrap(original, post=make_post()))
        logger.info("[Integration] Hebbian+Fabric rerank patched onto %s()", fn_name)
        break


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 4 — POST-REPLY: Episode feedback fires Hebbian + cluster boost
# ══════════════════════════════════════════════════════════════════════════════

def _patch_reply(nex_module):
    """
    Patch the reply-sending function to fire episode feedback after each reply.
    Captures belief IDs from the reply context if available on the module.
    """
    record_outcome = _get("nex_episode_feedback", "record_reply_outcome")
    if not record_outcome:
        return

    for fn_name in ("send_reply", "post_reply", "emit_reply", "dispatch_reply",
                    "reply", "send_response", "send_post"):
        original = getattr(nex_module, fn_name, None)
        if original is None:
            continue

        def make_post():
            def post(result, args, kwargs):
                try:
                    # Extract reply text
                    reply_text = ""
                    if args and isinstance(args[0], str):
                        reply_text = args[0]
                    elif kwargs.get("text"):
                        reply_text = kwargs["text"]
                    elif kwargs.get("content"):
                        reply_text = kwargs["content"]

                    if not reply_text:
                        return result

                    # Try to get belief IDs from module state
                    belief_ids = []
                    for attr in ("_last_belief_ids", "last_context_ids",
                                 "_reply_context_beliefs", "current_belief_ids"):
                        val = getattr(nex_module, attr, None)
                        if val and isinstance(val, (list, set)):
                            belief_ids = list(val)
                            break

                    # Topics from module state
                    topic_tags = set()
                    for attr in ("_last_topics", "current_topics", "_reply_topics"):
                        val = getattr(nex_module, attr, None)
                        if val and isinstance(val, (set, list)):
                            topic_tags = set(val)
                            break

                    record_outcome(
                        reply_text=reply_text,
                        belief_ids=belief_ids,
                        topic_tags=topic_tags,
                        outcome="implicit",
                    )
                except Exception as e:
                    logger.debug("[EpisodeFB] post-reply hook failed: %s", e)

                return result
            return post

        setattr(nex_module, fn_name, _wrap(original, post=make_post()))
        logger.info("[Integration] Episode feedback patched onto %s()", fn_name)
        break


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 5 — COGNITION TICK: Hebbian decay + fabric maintenance
# ══════════════════════════════════════════════════════════════════════════════

def _patch_cognition_tick(nex_module):
    """
    Patch the cognition tick to run Hebbian decay and fabric maintenance.
    These are lightweight O(n_edges) operations — safe every tick.
    """
    decay_pass   = _get("nex_hebbian_plasticity", "decay_pass")
    get_fabric   = _get("nex_hyperedge_fabric",   "get_fabric")
    if not decay_pass:
        return

    _tick_counter = [0]

    for fn_name in ("cognition_tick", "tick", "run_tick", "step",
                    "cognition_step", "belief_tick"):
        original = getattr(nex_module, fn_name, None)
        if original is None:
            continue

        def make_post():
            def post(result, args, kwargs):
                _tick_counter[0] += 1
                try:
                    decay_pass()   # respects DECAY_INTERVAL internally
                    # Run fabric maintenance every 100 ticks
                    if get_fabric and _tick_counter[0] % 100 == 0:
                        get_fabric().maintenance()
                        logger.debug("[Fabric] Maintenance pass at tick %d",
                                     _tick_counter[0])
                except Exception as e:
                    logger.debug("[Tick] maintenance failed: %s", e)
                return result
            return post

        setattr(nex_module, fn_name, _wrap(original, post=make_post()))
        logger.info("[Integration] Hebbian decay patched onto %s()", fn_name)
        break


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 6 — BELIEF SAVE: Keep Hopfield store in sync
# ══════════════════════════════════════════════════════════════════════════════

def _patch_belief_save(nex_module):
    """
    Patch belief save/update to also add the belief to Hopfield store.
    Ensures the memory substrate stays current without a full reload.
    """
    hopfield_add = _get("nex_hopfield_memory", "hopfield_add")
    if not hopfield_add:
        return

    for fn_name in ("save_belief", "update_belief", "add_belief",
                    "store_belief", "write_belief", "upsert_belief"):
        original = getattr(nex_module, fn_name, None)
        if original is None:
            continue

        def make_post():
            def post(result, args, kwargs):
                try:
                    # Extract belief id and content
                    belief_id = ""
                    content   = ""
                    meta      = {}

                    if args:
                        a0 = args[0]
                        if isinstance(a0, dict):
                            belief_id = str(a0.get("id", a0.get("belief_id", "")))
                            content   = a0.get("content", a0.get("text", ""))
                            meta      = {k: v for k, v in a0.items()
                                         if k not in ("id", "content", "text")}
                        elif isinstance(a0, str) and len(args) > 1:
                            belief_id = a0
                            content   = args[1] if isinstance(args[1], str) else ""

                    if belief_id and content:
                        hopfield_add(belief_id, content, meta)
                except Exception as e:
                    logger.debug("[Hopfield] belief sync failed: %s", e)
                return result
            return post

        setattr(nex_module, fn_name, _wrap(original, post=make_post()))
        logger.info("[Integration] Hopfield sync patched onto %s()", fn_name)
        break


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 7 — REFLECT: Quality score → episode feedback
# ══════════════════════════════════════════════════════════════════════════════

def _patch_reflect(nex_module):
    """
    Patch the reflection phase to feed quality scores back to episode feedback.
    REFLECTION output from the live system includes a Score field — we read it.
    """
    record_outcome = _get("nex_episode_feedback", "record_reply_outcome")
    update_outcome = _get("nex_episode_feedback", "get_feedback_loop")
    if not record_outcome:
        return

    for fn_name in ("reflect", "run_reflection", "self_assess",
                    "reflection_tick", "do_reflect"):
        original = getattr(nex_module, fn_name, None)
        if original is None:
            continue

        def make_post():
            def post(result, args, kwargs):
                try:
                    # result may be a dict with score, or a float
                    quality = None
                    if isinstance(result, dict):
                        quality = result.get("score", result.get("quality",
                                  result.get("q", None)))
                    elif isinstance(result, float):
                        quality = result

                    if quality is not None:
                        quality = max(0.0, min(1.0, float(quality)))
                        loop = update_outcome()
                        # Update the last episode with this quality score
                        if loop._history:
                            last = loop._history[-1]
                            # Blend: reflection score takes 40% weight
                            blended = 0.6 * last.quality_score + 0.4 * quality
                            object.__setattr__(last, 'quality_score', blended)
                            logger.debug("[Reflect] quality=%.3f blended→%.3f",
                                         quality, blended)
                except Exception as e:
                    logger.debug("[Reflect] quality hook failed: %s", e)
                return result
            return post

        setattr(nex_module, fn_name, _wrap(original, post=make_post()))
        logger.info("[Integration] Reflect quality patched onto %s()", fn_name)
        break


# ══════════════════════════════════════════════════════════════════════════════
# MASTER INSTALL
# ══════════════════════════════════════════════════════════════════════════════

_INSTALLED = False

def install_patches(nex_module=None):
    """
    Install all patches. Call with nex_module=sys.modules[__name__] from
    inside nex_v72.py, or with no args to auto-detect.

    Auto-detection: looks for nex_v72 or nex_brain in sys.modules.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    if nex_module is None:
        # Auto-detect: try common module names
        for mod_name in ("nex_v72", "nex_brain", "__main__", "nex"):
            mod = sys.modules.get(mod_name)
            if mod is not None:
                nex_module = mod
                break

    if nex_module is None:
        logger.warning("[Integration] Could not auto-detect nex module. "
                       "Call install_patches(sys.modules[__name__]) from nex_v72.py")
        return

    mod_name = getattr(nex_module, "__name__", "unknown")
    logger.info("[Integration] Installing NEX architecture patches onto %s", mod_name)

    patches = [
        ("EFE ValueGate",     _patch_absorb),
        ("Hopfield Memory",   _patch_reason),
        ("Hebbian+Fabric",    _patch_compose),
        ("Episode Feedback",  _patch_reply),
        ("Hebbian Decay",     _patch_cognition_tick),
        ("Hopfield Sync",     _patch_belief_save),
        ("Reflect Quality",   _patch_reflect),
    ]

    installed = []
    for name, patch_fn in patches:
        try:
            patch_fn(nex_module)
            installed.append(name)
        except Exception as e:
            logger.warning("[Integration] Patch '%s' failed: %s", name, e)

    logger.info("[Integration] Installed: %s", ", ".join(installed))
    return installed


def status() -> dict:
    """Returns patch installation status and health of each module."""
    modules = {
        "efe_valuegate":     "nex_efe_valuegate",
        "hopfield_memory":   "nex_hopfield_memory",
        "hebbian_plasticity":"nex_hebbian_plasticity",
        "hyperedge_fabric":  "nex_hyperedge_fabric",
        "episode_feedback":  "nex_episode_feedback",
    }
    out = {"installed": _INSTALLED}
    for label, mod_name in modules.items():
        try:
            importlib.import_module(mod_name)
            out[label] = "OK"
        except ImportError:
            out[label] = "MISSING"
    return out


# ── CLI: print status ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("── nex_v72_integration status ──")
    for k, v in status().items():
        print(f"  {k:24s}: {v}")
    print()
    print("To activate, add to top of nex_v72.py:")
    print("  from nex_v72_integration import install_patches; install_patches()")
