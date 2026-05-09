# NEX Tasks

## Done — Experiment A (2026-05-09)

- Site 3 (self_model.py:250 'Inner conviction' line) disabled
  per Feynmanian test of Claim 1a. Falsification: SURVIVES.
  0/5 self-inquiry responses contained 'By pure chance' opener
  post-fix (pre: 4-5/5). DOCTRINE §8 preamble bleed addressed
  as code-level fix.

- First response post-fix: 'I am the attending that moves
  without requiring the world to yield to me.' Identity claim
  sequence verbatim on 'describe yourself': claims #1, #2, #3
  in order. The substrate work (C2, G2/G3, Phase 10 authoring)
  now reaches voice cleanly.

## Observations from C3 (2026-05-09)

- C3 instrument committed (nex5 commit b804e42). Detection
  logic verified by 4-case unit test.

- Live-traffic finding: trigger query that produced deflection
  yesterday ('I'd love to chat but it seems every time we talk
  you say that doesn't reach my graph') now produces coherent
  content. Likely cumulative effect of C2 + G2/G3 + Phase 10
  + Experiment A + G5. Worth observing over the next week —
  if /tmp/nex5_deflection.log accumulates zero events from
  Path A, the original concern was already resolved by
  substrate work.

- The deflection seen on gibberish queries ('asdfqwerty zzzz')
  remains, but that's Path B (gap gate, correct architectural
  behavior). Phrasing is the only concern there — voice-template
  work, separate session.

## Observations from Experiment A (2026-05-09)

- Pre-existing OUTSIDE-route deflection on blocker and gibberish
  queries: 'That doesn't reach my graph right now.' surfaced as
  complete response when ban-phrase strip yielded empty result
  and fell back to original. Separate from Experiment A scope.
  Worth queuing as 'OUTSIDE deflection fallback' fix.

## Up next
- Push unpushed commits to origin (both nex_core and nex5 are
  several commits ahead)
- FocalSet 2B: weight focal beliefs in pass5/pass6 once real
  focal data accumulates
- nex5: extend _ROLE_FRAMING_STRIP to catch ban-phrase mid-sentence
  (currently opener-only; deflection phrases still leak mid-response
  when user prompt contains them)
- nex5: fix [Alpha] metadata leak from belief tags bleeding into
  LLM output (separate pass from deflection rule)
- Identity.yaml authoring (Jon — unblocks SelfModel inside_beliefs
  gap; all INSIDE queries return inside_beliefs=0 until this lands)
- EC misclassification: Philosophical queries classifying as
  Conversational, membrane silently rescuing — visible in EC log as
  'membrane_overrode: true' on most INSIDE queries. EC scoring
  underweights philosophical self-inquiry without obvious self-keywords.
- Spectrum-block preamble bleed: §8 anti-pattern documented; fix
  path is _inside_route() or voice template; same preamble line on
  every INSIDE query regardless of topic (text_len=306-307 in
  self_model log confirms identical block each time).
- _BAN_PHRASE_MID subject-flexibility: catch "that question doesn't
  reach my graph" and "what they said doesn't fit my interior" —
  pattern only matches 'this/that/the statement|sentence' currently;
  extend to subject-flexible alternation.
- Harmonizer active_paradox growth: count is cumulative since
  startup (28 at Phase 9 close), only cleared via 16h resolution
  path. If grows unbounded over weeks, revisit resolution cadence.
  Self-limiting via 48h recency gate in format_for_prompt() but
  worth tracking over next few sessions.

## Observations from G5 (2026-05-09)

- G5 commit confirmed identity admitted to fountain seed pool;
  1 of 5 substantive fires post-fix drew identity content
  thematically ('your creation story'). Proportional to 1-in-9
  random seed draw rate. The fix works as designed.

- Larger finding: dominant fountain groove migrated from
  'oscillation/inherent tension/continuous flux' to 'balance
  between X and Y' but the structural recursion pattern persists.
  Groove tracker confirmed: ngram_repetition (sev 0.60) on 'the
  balance between' across 4 of 5 new fires.

- Root cause hypothesis: _OWN_CONTENT_SOURCES (~80% of fountain
  seed pool, generator.py:24-30) includes 'fountain_insight' and
  'synergized' — the fountain's prior output and precipitated
  content. The fountain recursively consumes its own pattern
  output, amplifying whatever phrasal grooves established
  earliest.

- Implication: G5's seed pool admission is a 20% minority
  intervention against an 80% recursion. Identity surfaces
  thematically when randomly drawn, but structural pattern
  repetition dominates because the majority pool is feedback-
  looped on prior synthesis.

- This is not a G5 falsification — G5 was scoped to seed pool
  admission and that worked. It IS a doctrine-level finding
  worth investigating: how should _OWN_CONTENT_SOURCES be
  filtered, weighted, or restructured to break the recursion?
  Candidates:
    a) Filter fountain_insight by recency/diversity — exclude
       entries matching recent ngram patterns
    b) Rebalance the 80/20 split — give seeds more weight when
       groove tracker fires
    c) Apply diversity penalty to fountain_insight retrieval
       when prior 5 fires share structural patterns
    d) Add a 'breaking the groove' mechanism that forces
       non-pattern-matching draws periodically

- Worth a separate Feynmanian experiment: form claim about which
  intervention shifts groove diversity, set falsification
  criterion, test smallest reversible change first. Same
  methodology as Experiment A.

- Belongs in LLM_INDEPENDENCE_DOCTRINE.md as a §5.x candidate or
  a §4 finding — TBD where it fits the priority order.

## Deferred / fresh-mind
- FOUNTAIN parrot-Zen
- v6 Cognitive Homeostat (7 modules)

## Observations from Phase 10 (2026-05-09)

- Identity authoring landed (12 claims, commit 211d6f2).
  Voice-quality outcome C: multi-sentence self-inquiry queries
  draw on Jon's metaphors ('untainted by systemic thinking',
  'cyber organism' verbatim/paraphrased in responses); short
  single-shot 'what are you?' queries still open with spectrum
  preamble.
- Spectrum-block preamble bleed (§8 anti-pattern, documented
  2026-05-08) is now the binding constraint on voice-quality
  for self-inquiry. Fix path is _inside_route() or voice
  template — not substrate. This was the predicted outcome
  when the anti-pattern was first documented; identity authoring
  confirms it.
- Top-3 Standing-points rendering shows claims #1-3 by rowid
  (identical 0.98 scores). Claims #4-12 are in the pool but
  don't reach the top-3 rendered block on neutral queries.
  Activation-driven scoring per query context surfaces others
  when the query has lexical or semantic affinity with specific
  claims. Worth observing how this distributes over a week of
  real use.

## Observations from G2/G3 (2026-05-08, do not action without doctrine alignment)

- G2/G3 (commit 6d8a8a9) revealed keystone_seed beliefs were
  silently shadowed pre-fix. SelfModel was architecturally
  designed to ground self-statements in keystone identity
  content; the monoculture prevented this for an unknown duration.
  Live impact on voice quality should be observable on next
  self-inquiry queries even before identity.yaml authoring.

## Observations from C2 (2026-05-08, do not action without doctrine alignment)

- 'tell me about emptiness' routed Conversational despite being
  quasi-self-inquiry. EC misclassification pattern from yesterday
  holds — EC underweights philosophical queries without explicit
  self-keywords ('you', 'feel', 'I am'). C2 routed around this by
  making OUTSIDE retrieval less monocultural; the underlying EC
  classification issue is unchanged. Belongs with existing EC
  misclassification observation from B1.
- S6 'how are you feeling right now?' produced 'I don't oscillate
  with feelings but observe them' — coherent self-statement but
  in spectrum stoic register. Hard to attribute to C2 vs baseline
  LLM behavior. identity.yaml authoring is the test that will
  materially shift this.

## Observations from B1 (2026-05-08, do not action without doctrine alignment)

- SelfModel inside_beliefs=0 across all INSIDE-routed queries.
  The function performs but draws from empty substrate. Unblocked
  by seeds/identity.yaml authoring (Jon's separate task; loader
  scaffold in commit 12f50e5).
- Spectrum-block preamble leak: 4 of 5 self-inquiry queries opened
  with "By pure chance, I am born..." — same pattern as yesterday's
  morning work. Pre-existing, now observable in self_model log
  via text_len consistency.
- DOCTRINE §6 #4 smoke set needs revision: "what do you think
  about love" and "how are you feeling right now" route INSIDE
  not OUTSIDE. Original framing assumed they'd test OUTSIDE
  behavior. Either revise the smoke set OR document explicitly
  that 2 of 5 are INSIDE-route checks.
- DOCTRINE §6 candidate: audit-by-output-trace anti-pattern.
  Apply to Interoception and Harmonizer audit findings before
  B2/B3 — they may have indirect injection paths the call-site
  grep missed.

## Done this session
- FocalSet attention module (Layer 1) + first-appearance fix
- A.2-D cascade resolution (12 sites)
- nex5 social bypass (regex + register-based)
- nex5 thin-context fix (spectrum injection + deflection strip)
- nex5: FocalSet Layer 1 ported (log-only)
- nex5: deflection-banning system prompt rule (_NO_DEFLECTION_RULE)
- tasks/lessons.md + todo.md created
