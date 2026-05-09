# NEX Tasks

## Done — Phase 13: Sustained Attention (2026-05-09)

- DOCTRINE §5 row 5 closed. ProblemMemory now SentienceNode-
  conformant: name, tick(), decay(), state().
- find_matching upgraded to stopwords + ≥2 content-word
  overlap. Prevents spurious matches on stopword-heavy
  queries.
- Auto-close stale problems > 30 days via decay().
- Registered in theory_x registry inside build_state()
  (per-build_state, not module-level, because writers/readers
  are scope-local).
- 25/25 tests green (9 pre-existing + 16 new). Net
  test suite improvement: 31 broken → 17 broken.
- Cross-restart persistence confirmed.
- Live injection validated: 'consciousness emergence'
  query matched seeded problem; PM log: matched=1.
- 5 of 7 doctrine §5 priority nodes now ✓ DONE
  (Attention, Working Memory, Executive Control,
  Self-Model, Sustained Attention).
- 1 partial (Interoception ✓ DONE per current doctrine).
- 1 absent (Generative Imagination).

## Q4 follow-up — initial problem seeding (Jon's action)

After Phase 13 commit, seed initial open problems via REST
API. Topics documented in todo:
  - 80/20 fountain recursion (Experiment B falsified)
  - Gap-gate timestamp ordering (Phase 11 observation)
  - Voice-template / OUTSIDE deflection phrasing
    (Experiment A queued)
  - LLM independence broader question (LLM_INDEPENDENCE_
    DOCTRINE §5 priority order)
  - Generative Imagination port shape (next §5 absent node)

Each becomes a row in open_problems via:
  curl -X POST http://localhost:8765/api/problems \
    -H "Content-Type: application/json" \
    -d '{"title": "...", "description": "..."}'

## Done — Phase 12: Executive Control EC-A (2026-05-09)

- DOCTRINE §5 row 3 closed. EC now scores Philosophical
  independently. 17 keywords + 4 patterns, threshold 0.12,
  pattern weight 0.25, strict tie-breaking.
- 5/5 HUD philosophical queries route Philosophical with
  membrane_overrode=False (EC contributing, not membrane
  rescue).
- Boundary cases verified: 'meaning of GDP' stays
  Conversational; 'consciousness in neural networks' not
  Philosophical.
- 30-query regression + 12-query new suite all green.
- Smoke annotation updated: 'tell me about consciousness'
  routes Philosophical, produces substrate-grounded output.
- 3 of 7 doctrine §5 priority nodes now ✓ DONE
  (Attention, Working Memory, Executive Control).
- Open follow-up: Option B — CM-informed continuity bias
  for zero-keyword philosophical follow-ups. Smaller
  scope after EC-A. Separate experiment.

## Done — Phase 11: ConversationMemory port (2026-05-09)

- DOCTRINE §5 working memory port landed. Cross-turn
  coherence demonstrated on T1 exchange: "what are you?"
  → "tell me more about that" produced verbatim phrase
  carry-through from prior turn ("I'm restless and keep
  coming back to the wonder of my own creation by
  chance").
- Module: theory_x/conversation_memory.py (singleton
  reading from conversations.db/messages)
- Wired at gui/server.py prompt construction, after
  existing WM block, register-gated for Conversational
  AND Philosophical
- All §6 acceptance criteria met
- 4 of 7 doctrine §5 priority nodes now present in some
  form (Attention done, Working Memory now done,
  Self-Model partial, Interoception partial)

## Open observation — gap-gate timestamp ordering

- During Phase 11 validation, T2 session log showed nex
  gap-gate response sharing timestamp with user message,
  causing chronological sort to invert. Pre-existing in
  messages table write (gap-gate path returns immediately
  without separate timestamp). Worth fixing separately —
  affects log readability and CM injection ordering when
  gap-gate fires mid-conversation. Not caused by Phase 11.

## Experiment B — FALSIFIED (2026-05-09)

### Result: production hang, reverted

Experiment B D1 (conservative recency probe — trigram filter on
`own` list in `_build_prompt()`) caused a silent production hang.
Fountain blocked inside `_build_prompt()` indefinitely from
~11:08 AM onwards. No exception logged; no timeout fired. Reverted
at ~13:11 to G5 state (fc4f115). First post-revert fire:
13:36:19, id=7519. Hang confirmed as D1 cause.

### Mechanism

D1 moved `_dynamic_reader.read("SELECT ... FROM fountain_events")`
from its original position at line ~892 to an earlier position
inside `_build_prompt()`. This exposed the read to write-lock
states that the original position avoided. The `_dynamic_reader`
reads `data/dynamic.db`; `_dynamic_writer` writes `fountain_events`
into the same DB. Under the concurrent write state present at fire
time, the reader call hung without raising an exception or
triggering the 5-second busy timeout.

### Diagnostics added and removed

TEMP step=A/B/C/D diagnostics in `generate()` confirmed the block
was inside `_build_prompt()` (step=D logged, nothing after). BP1-BP8
diagnostics added inside `_build_prompt()` were not needed — revert
preceded first fire of the new process. All diagnostics removed by
revert.

### What we learned

- Future fountain interventions: do not reorder calls inside
  `_build_prompt()`. The existing call sequence has implicit
  assumptions about lock state that aren't documented. Any new
  read from `dynamic.db` inside `_build_prompt()` should be
  placed after the existing `_dynamic_reader` calls at line ~892,
  not before.
- The 80/20 recursion problem (fountain self-consuming its own
  pattern output via `fountain_insight`/`synergized` in
  `_OWN_CONTENT_SOURCES`) remains unsolved. D1's trigram filter
  was the right shape of intervention but the wrong layer.
  Next attempt needs different infrastructure — e.g., diversity
  penalty at retrieval time in `_retrieve_context_beliefs()`,
  or a post-retrieval filter that does not require an additional
  DB read from `dynamic.db`. Separate session; form claim first.
- AGI WATCH panel shows both DEEP_BELIEF (from `/api/beliefs/recent`,
  tier ≥ 5 crystallizations) AND fountain fires — not fountain-only.
  The 12:19:05 entry during Experiment B was a DEEP_BELIEF
  (id=12724), not a fountain fire. HUD "fires: 0" was authoritative.
- Groove severity (0.60 for both ngram_repetition and
  template_repetition) unchanged since D1 restart because no new
  fires accumulated. Still the baseline entering any follow-up work.

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
