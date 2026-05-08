# NEX Tasks

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

## Deferred / fresh-mind
- FOUNTAIN parrot-Zen
- v6 Cognitive Homeostat (7 modules)

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
