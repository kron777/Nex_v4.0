================================================================================
                   NEX RESPONSE ROUTER — DESIGN SKETCH
         A Tiered Response System: Python-first, LLM when needed
                         April 2026
================================================================================


PREAMBLE
--------

This is a design sketch for a new module, `nex_response_router.py`, that
decides per-query whether NEX needs to invoke the LLM or whether a
Python composer can answer correctly. The goal is faster responses,
lower GPU load, and incrementally less exposure to the LoRA weight
contamination without waiting for FT#11.

This is NOT a replacement for the LLM. It's a routing layer that uses
the LLM only when the LLM is earning its cost. Symbolic AI tried full
replacement in the 70s-90s and lost; routing works because it keeps the
LLM for the long tail while bypassing it for the common case.

Existing code this sits next to: nex/nex_respond_v2.py (PATH 1 + PATH 2).
This module effectively formalizes the PATH 1 / PATH 2 split into an
explicit router with measurable tiers, rather than the implicit
"if _build_reply returns >20 chars, use it" logic currently at line 787.


--------------------------------------------------------------------------------
1. THE THREE TIERS
--------------------------------------------------------------------------------

TIER 0 — PURE PYTHON COMPOSER
  When: retrieved beliefs are high-confidence, coherent with each other,
        and the query pattern is familiar.
  How:  a Python function concatenates sanitized beliefs with connective
        phrases from a fixed vocabulary. No LLM call.
  Cost: <10ms per response.
  Use case: most self-inquiry queries, most factual lookups, most
        queries where NEX has already crystallized a view.
  Risk: generic-sounding output when the query deserved something
        bespoke.

TIER 1 — LIGHT LLM CALL
  When: beliefs are relevant but need fluent integration; query has a
        specific phrasing requirement.
  How:  LLM call with short system prompt, max_tokens=150,
        temperature=0.2, no fountain continuation.
  Cost: ~1-2s per response.
  Use case: user-facing chat, Telegram replies, anywhere fluency
        matters but novelty doesn't.

TIER 2 — FULL LLM CALL
  When: conflicting beliefs, novel query, synthesis required,
        recursive probe, dialectical situation.
  How:  current PATH 2 stack — full structured prompt, higher
        max_tokens, reasoning over the belief set.
  Cost: ~3-6s per response (current baseline).
  Use case: R6 probes, Throw-Net refinement, contradiction synthesis,
        anything that needs the LLM to genuinely reason.


--------------------------------------------------------------------------------
2. DATA CONTRACT
--------------------------------------------------------------------------------

Input to the router:

    @dataclass
    class RouteInput:
        query: str
        beliefs: list[BeliefHit]       # from get_beliefs_for_query
        intent: str                    # self_inquiry, factual, general, etc.
        source: str                    # 'telegram', 'fountain', 'probe', 'api'
        history_hint: Optional[str]    # last N exchanges, or None

    @dataclass
    class BeliefHit:
        content: str
        confidence: float
        topic: Optional[str]
        tfidf_score: float             # the retrieval score that got it here

Output from the router:

    @dataclass
    class RouteDecision:
        tier: int                      # 0, 1, or 2
        reason: str                    # human-readable rationale
        score_dict: dict               # feature values that drove decision
        # Tier-specific payloads:
        composed_text: Optional[str]   # set iff tier == 0
        llm_config: Optional[dict]     # set iff tier in (1, 2)

The router returns the DECISION plus, for Tier 0, the already-composed
text. No further work needed. For Tier 1/2, the caller invokes the LLM
with the specified config.


--------------------------------------------------------------------------------
3. THE ROUTING HEURISTICS
--------------------------------------------------------------------------------

The router computes a feature vector from RouteInput and maps it to a
tier. Features are cheap (microseconds), interpretable, and logged for
every decision.

Feature set:

    F1 — n_beliefs: how many beliefs came back from retrieval
    F2 — mean_confidence: average confidence across retrieved beliefs
    F3 — min_confidence: lowest confidence in the set
    F4 — tfidf_top_score: retrieval score of the best hit
    F5 — contradiction_present: do any two retrieved beliefs contradict?
         (cheap check: lookup in belief_relations for CONTRADICTS edges)
    F6 — query_length_words: crude novelty proxy
    F7 — intent_category: from the existing intent classifier
    F8 — query_contains_marker: does the query contain "why", "how",
         "what if", "reflect on", "describe" — markers of synthesis
         requirement vs. retrieval requirement
    F9 — history_coherent: is this a continuation of a recent exchange?
    F10 — source_weight: some sources (R6 probe) always go Tier 2;
          some (Telegram quick chat) default to Tier 1 unless other
          signals promote/demote

Initial routing rules (v1 — simple, tunable):

    def decide(features: dict) -> int:
        # Hard overrides first
        if features['source'] in ('r6_probe', 'fountain'):
            return 2
        if features['contradiction_present']:
            return 2
        if features['query_contains_marker'] in ('why', 'reflect_on', 'synthesize'):
            return 2

        # Tier 0 eligibility
        if (features['n_beliefs'] >= 2
                and features['mean_confidence'] >= 0.75
                and features['tfidf_top_score'] >= 0.4
                and features['query_length_words'] <= 20
                and not features['contradiction_present']):
            return 0

        # Tier 1 default for anything else that has retrievable content
        if features['n_beliefs'] >= 1 and features['mean_confidence'] >= 0.5:
            return 1

        # Nothing retrievable — Tier 2 will honestly struggle too,
        # but at least it handles the graceful-degradation case
        return 2

This is deliberately simple. Tuning happens by measurement, not by
guessing.


--------------------------------------------------------------------------------
4. THE TIER 0 COMPOSER
--------------------------------------------------------------------------------

Tier 0 is the interesting new piece. It's a Python function that
produces a coherent response from beliefs WITHOUT the LLM.

Structure:

    def compose_tier0(beliefs: list[BeliefHit], query: str, intent: str) -> str:
        sanitized = [_sanitize_belief(b.content) for b in beliefs[:3]]
        sanitized = [s for s in sanitized if len(s) > 10]

        if intent == 'self_inquiry':
            opener = _pick(_SELF_OPENERS)
            body = sanitized[0]
            if len(sanitized) > 1:
                body += f" {_pick(_CONNECTIVES)} {sanitized[1]}"
            return f"{opener} {body}"

        if intent == 'factual':
            # Factual queries get a declarative form, no opener
            return " ".join(sanitized[:2])

        # General case
        opener = _pick(_GENERAL_OPENERS)
        if len(sanitized) == 1:
            return f"{opener} {sanitized[0]}"
        return f"{opener} {sanitized[0]} {_pick(_CONNECTIVES)} {sanitized[1]}"

Connective vocabulary (small, hand-curated):

    _SELF_OPENERS = [
        "As I understand myself:",
        "From inside my own frame:",
        "What I hold about this is:",
        "My position:",
    ]

    _GENERAL_OPENERS = [
        "What I hold on this:",
        "From the beliefs that bear on this:",
        "Here's where I stand:",
        "The position I've settled on:",
    ]

    _CONNECTIVES = [
        "and relatedly,",
        "which connects to:",
        "building from that,",
        "alongside which:",
    ]

CRITICAL CONSTRAINT: every belief passing through compose_tier0 is
first run through _sanitize_belief. No bridge:X↔Y, no conf markers,
no edge labels. This is the same sanitizer from Phase 1C. Tier 0
inherits Phase 1C's substrate hygiene automatically.

The LLM weight contamination problem DOES NOT APPLY to Tier 0 at all,
because there is no LLM call. This is the pragmatic reason to route
aggressively to Tier 0 while waiting on FT#11.


--------------------------------------------------------------------------------
5. WHERE IT PLUGS IN
--------------------------------------------------------------------------------

The router sits inside generate_reply in nex/nex_respond_v2.py, after
belief retrieval and intent classification, before the current PATH 1 /
PATH 2 branch.

Current flow (post-Phase-1D):

    query → retrieval → intent → build_prompt → call_llm →
      (PATH 1 renderer OR PATH 2 LLM) → post_filter → reply

New flow:

    query → retrieval → intent → router.decide →
      Tier 0: composer                                     → post_filter → reply
      Tier 1: call_llm (light config)                      → post_filter → reply
      Tier 2: call_llm (full config, current PATH 2 path)  → post_filter → reply

The existing PATH 1 direct renderer becomes Tier 0. The existing PATH 2
becomes Tier 2 (plus a new lighter Tier 1 variant). The implicit
routing that exists today becomes explicit and measurable.


--------------------------------------------------------------------------------
6. INSTRUMENTATION
--------------------------------------------------------------------------------

New table in nex_experiments.db:

    CREATE TABLE route_decisions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT,
        query           TEXT,
        intent          TEXT,
        source          TEXT,
        tier            INTEGER,
        reason          TEXT,
        features_json   TEXT,
        response_text   TEXT,
        latency_ms      INTEGER
    );

Every router decision writes one row. This lets you answer:

- What fraction of queries go to each tier?
- What's the mean latency per tier?
- Which features correlate with tier assignment?
- Which tier does Telegram chat use most?
- When the adversarial identity probe fires, which tier answers it?


--------------------------------------------------------------------------------
7. THE SUCCESS TEST
--------------------------------------------------------------------------------

The router is successful if:

T1 — BLIND TEST
    Take 20 queries. For each, generate responses at Tier 0 and Tier 2.
    Blind-shuffle. Ask Jon (or a third party) to guess which is which.
    If Jon can reliably tell: Tier 0 composer needs work OR some queries
    genuinely need the LLM. If Jon can't reliably tell: Tier 0 is doing
    real work and the LLM was overkill for those queries.

T2 — LATENCY
    Mean response latency drops by 50% or more across a 100-query
    workload that matches production distribution (Telegram + Moltbook
    + ad-hoc).

T3 — C1 RATE DROPS
    Since Tier 0 responses never hit the LLM, weight-encoded bridge:X↔Y
    contamination can't leak through them. If 60% of responses route
    to Tier 0, C1 rate should drop ~60% proportionally. Concrete
    prediction: if Phase 1D frozen C1 is 15.3% (all via LLM), router
    deployment should push live C1 to ~6%.

T4 — NO REGRESSION ON HARD QUERIES
    The R6 probe and adversarial identity probe still produce the same
    quality of response as pre-router, because they route to Tier 2.
    This is a guard rail: the router is not allowed to make hard
    queries worse to make easy queries faster.


--------------------------------------------------------------------------------
8. WHAT THIS DOES NOT DO
--------------------------------------------------------------------------------

8.1  IT DOES NOT MAKE NEX SMARTER.
     Same beliefs, same retrieval, same LLM when invoked. The router
     just avoids the LLM when the LLM wasn't adding value.

8.2  IT DOES NOT FIX THE LORA CONTAMINATION.
     Tier 2 still has the 15.3% C1 rate. The router reduces exposure
     to it by routing less traffic through Tier 2. FT#11 is still
     needed to fix it at the root.

8.3  IT DOES NOT IMPROVE RESPONSE QUALITY FOR TIER 0 OVER THE EXISTING
     PATH 1 RENDERER.
     The existing _build_reply IS the Tier 0 composer in disguise.
     What changes is that Tier 0 becomes a legitimate first-class path
     instead of a fallback, gets proper sanitization, and is measured.

8.4  IT DOES NOT SOLVE NOVEL-PROBLEM GENERATION.
     Novel problems go to Tier 2 and get the current quality. If
     current Tier 2 quality is insufficient, that's a separate problem
     that FT#11 + planning-layer work address.


--------------------------------------------------------------------------------
9. SIZE AND SESSION ESTIMATE
--------------------------------------------------------------------------------

Files to create:
  - nex_response_router.py (new, ~250 lines)
  - nex_tier0_composer.py (new, ~100 lines)
  - tests for both (~150 lines)

Files to modify:
  - nex/nex_respond_v2.py — generate_reply wiring (~20-30 line diff,
    review-gated)

Database changes:
  - route_decisions table in nex_experiments.db (additive)

Session count: 1-2.
  Session 1: router + composer + tests + table. Auto-accept.
  Session 2: wire into generate_reply. Review-gated edit. Run blind
    test. Write results doc.


--------------------------------------------------------------------------------
10. ORDER OF OPERATIONS
--------------------------------------------------------------------------------

1. Finish whatever maintenance you schedule (busy_timeout fix and
   friends). Substrate first.

2. Build the router + composer in isolation. Unit test against a fake
   RouteInput fixture set. No production touch.

3. Write tier0 composer. Unit test against sampled beliefs.

4. Add route_decisions table.

5. Wire into generate_reply behind a NEX_ROUTER env flag. Default off.
   When off, zero production change — existing PATH 1 / PATH 2 logic
   runs.

6. Run blind test (T1) and latency test (T2) with flag on.

7. If tests pass, promote the flag default to on. Keep off-switch for
   emergencies.

8. Measure for a week. Tune thresholds based on route_decisions data.

Total cost to ship: ~3-4 working sessions over 2 weeks, with a week
of passive measurement between them.


--------------------------------------------------------------------------------
11. HONEST LIMITS
--------------------------------------------------------------------------------

11.1 THE "INVENTION" FRAMING IS GENEROUS.
     Tiered inference is a known pattern. Applying it to a belief-graph
     system where most outputs genuinely are retrievable compositions
     is novel-ish, but not an invention in the strong sense. What's
     novel is the combination with sanitization, the belief-confidence-
     based routing, and the measurement discipline.

11.2 THE HEURISTIC THRESHOLDS ARE GUESSES.
     The initial rule in Section 3 is reasonable but arbitrary. Real
     thresholds come from measuring route_decisions over a week of
     production traffic. Expect the first deployment to be wrong in
     detail, right in shape.

11.3 TIER 0 MAY PRODUCE GENERIC-SOUNDING OUTPUT.
     The composer's vocabulary is small and repetitive by design (so
     we can audit it). Some queries will get answers that feel rote
     even when the beliefs behind them are good. This is a trade-off:
     speed + no contamination vs. fluency. If it's unacceptable for
     user-facing paths, raise the bar for Tier 0 eligibility and push
     more queries to Tier 1.

11.4 THIS IS INFRASTRUCTURE, NOT AGI PROGRESS.
     The router makes NEX faster, cheaper, and cleaner. It doesn't
     make her do anything new. Stage B (tool use) and Stage C
     (planning) are still the capability-track priorities. The router
     is infrastructure that makes those later builds cheaper to iterate
     on.


--------------------------------------------------------------------------------
12. SUMMARY
--------------------------------------------------------------------------------

A new module — nex_response_router.py — classifies incoming queries
into three tiers. Tier 0 uses a Python composer with no LLM call for
simple high-confidence responses. Tier 1 uses a light LLM call for
fluency-sensitive cases. Tier 2 uses the full current LLM stack for
genuine reasoning.

The router formalizes the implicit PATH 1 / PATH 2 split that already
exists, makes it measurable, adds a legitimate fast path, and
incidentally reduces LoRA weight contamination exposure while
waiting on FT#11.

Buildable in ~2 sessions. Flag-gated for safe rollout. Measurable
via a new route_decisions table. Falsifiable via blind test.

Not AGI progress. Infrastructure for everything else to ride on.

================================================================================
                              END OF SKETCH
================================================================================
