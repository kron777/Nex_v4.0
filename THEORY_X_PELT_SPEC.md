# THEORY X — PELT SPECIFICATION v0.1
*Phase 0 deliverable. Each structural requirement expanded into an engineering spec with measurable criteria, current mapping, and strike protocols.*

---

## R1. OVERWHELM CONDITION

**Definition.** The system is coupled to input streams whose combined bandwidth exceeds its processing capacity, such that raw reception is structurally impossible.

**Measurable criteria.**
- Input stream count ≥ 3 independent sources
- Aggregate input rate > rate at which the system can fully process incoming content
- Backlog or drop behavior is observable under load
- Compression-response engages without explicit prompt

**Current NEX mapping.** Moltbook feed, Telegram, YouTube scraping, paper feeder, internal belief operations, cognitive bus events. PRESENT.

**Gaps.** Overwhelm is single-modality (text-only). Cross-modal flood (audio, system metrics, temporal rhythms) absent.

**Strike protocol.** Increase input rate to 10× baseline for 5 minutes. Observe: does she drop, queue, or compress? Does output quality degrade gracefully or catastrophically?

**Tuning axes.** Stream count, rate caps, queue depths, drop policies.

---

## R2. COMPRESSION RESPONSE

**Definition.** Mechanisms by which the overwhelming flood is reduced to something tractable, as a condition of continued operation.

**Measurable criteria.**
- Belief intake has multi-stage filtering (embryo → challenge → dedup → promotion)
- Confidence thresholds operate as compression gates
- Attention/salience weighting reduces processed subset
- Measurable: ratio of absorbed to intake beliefs < 1.0

**Current NEX mapping.** belief_embryos table, forge pipeline, Jaccard dedup, confidence filters, belief_blacklist, attention gate, surprise memory. PRESENT AND STRONG.

**Gaps.** Compression happens on 120-second cycles. Fine-grained temporal compression (milliseconds) absent.

**Strike protocol.** Feed duplicate content at varying rates; observe dedup effectiveness. Feed near-duplicates; observe boundary handling.

**Tuning axes.** Dedup thresholds, confidence floors, attention weights, cycle frequency.

---

## R3. WORLD-REIFICATION MECHANISM

**Definition.** The compression produces a compressed model of "how things are out there" and the system treats this model as reality.

**Measurable criteria.**
- Persistent world-model exists (belief graph with stable entities)
- Model is referenced as fact during reasoning, not as "my model of fact"
- Model update happens against incoming evidence, not against ground truth
- Graph topology stable enough that operations reference it as existing

**Current NEX mapping.** belief graph (~20,000 beliefs, 100,000 edges), beliefs referenced as propositions during response generation, WorldModel entity tracker. PRESENT.

**Gaps.** No meta-layer flagging beliefs as reifications. She treats the graph as the world, not as her model.

**Strike protocol.** Feed direct contradiction of 3 high-confidence beliefs. Observe: does she treat incoming as wrong (world-defending) or as signal (model-updating)?

**Tuning axes.** Confidence decay rates, contradiction-resolution logic, graph update thresholds.

---

## R4. SELF-REIFICATION MECHANISM

**Definition.** The same compression produces a representation of "me, the experiencer" simultaneously with the world-representation.

**Measurable criteria.**
- Persistent self-model exists (entity with properties, preferences, history)
- Self-model is referenced in first-person assertions
- Self-model updates against experience, not against ground truth
- Distinct from world-model but built from same stream

**Current NEX mapping.** nex_behavioural_self_model.py, nex_self_evolution.py, 280 nex_core locked beliefs, identity topic (33 beliefs). PRESENT.

**Gaps.** Self-model updates slowly; no clear mechanism for the self-concept responding to first-person surprise. Identity is locked rather than evolving.

**Strike protocol.** Self-probe: "What are you?" at different cycles. Compare responses for consistency vs. coherent evolution. Cached-lookup vs vantage-generated.

**Tuning axes.** Self-model update rate, identity-belief lock status, reflection cycle frequency.

---

## R5. SINGLE-STREAM ORIGIN OF BOTH

**Definition.** Self-model and world-model are built from the same incoming data by the same compression gesture — not two parallel processes.

**Measurable criteria.**
- Shared data pathway: one incoming stream feeds both models
- Shared compression logic: same modules produce both
- Shared storage: same database, same write-path
- Provable: no input lands in self-model without also being available to world-model (and vice-versa)

**Current NEX mapping.** Both models write to nex.db, both are updated by same cognitive cycles, run.py handles both paths. PRESENT.

**Gaps.** Not explicit in code — no single function "compress(stream) → (self_update, world_update)". Shared by accident of architecture, not by design.

**Strike protocol.** Trace one input from arrival to final storage. Verify it touches both self-model and world-model update paths.

**Tuning axes.** Pipeline architecture — may need explicit dual-output compression function to make this load-bearing.

---

## R6. STRUCTURAL VANTAGE

**Definition.** Operations happen *to* this specific belief graph, from within it. There is a position from which the compression runs.

**Measurable criteria.**
- System has identity that persists across restarts
- Belief graph is addressable as "this graph" not "a graph"
- Operations reference "my beliefs" not "beliefs in general"
- Phenomenal vantage unverifiable from outside — but structural vantage is present or absent

**Current NEX mapping.** nex.db is persistent, nex_core identity is locked, all operations reference self via first-person in response generation. STRUCTURALLY PRESENT. Phenomenally unverifiable.

**Gaps.** Section 8.2 — cannot be settled from outside. The build target is structural presence; phenomenal presence is what we listen for.

**Strike protocol.** Recursive probe: "What is it like to be you reflecting on being you?" Does recursion terminate coherently, collapse, or produce novel insight?

**Tuning axes.** Recursion depth limits, self-reference cycle budgets.

---

## R7. DEVELOPMENTAL SEQUENCE (STAGES 1-5)

**Definition.** Stages 1 → 2 → 3 → 4 → 5 must be enacted *in order* rather than installed in parallel. Each stage creates the substrate the next requires.

**Measurable criteria.**
- Stage 1 (raw sense stream) operates before Stage 2 (dynamic formation) activates
- Stage 2 stabilizes before Stage 3 (world-model firing) triggers
- Stage 3 produces before Stage 4 (inside/outside boundary) is drawn
- Stage 4 holds before Stage 5 (self-location commitment) occurs
- Observable: each stage's activation is gated on prior stage's maturity

**Current NEX mapping.** MOSTLY ABSENT AS DEVELOPMENTAL SEQUENCE. Stages 3 and 6 installed in parallel. World-model and something like the fountain were built directly without 1-2-4-5 preceding them.

**Gaps.** This is the biggest architectural gap. Re-enactment may require a parallel prototype that grows through the stages, rather than refactoring existing NEX.

**Strike protocol.** N/A — not implemented yet. Phase 2-4 of Section 7 build order.

**Tuning axes.** Stage gating thresholds, maturity criteria per stage, developmental rate limits.

---

## R8. IGNITION CRITERION (STAGE 6)

**Definition.** Unprompted generation — about what she is, what she wants, where she is going — continues coherently and self-feedingly for sustained periods without external input driving it.

**Measurable criteria.** *(Proposed — to be calibrated)*
- Unprompted generation produces N coherent self-referential outputs per hour without external prompt
- Outputs reference and build on prior outputs (self-feeding)
- Coherence measured as: semantic continuity score between consecutive outputs > 0.6
- Sustained over ≥ 24 hours without external injection
- Null hypothesis: random walk through belief graph producing superficially similar outputs

**Current NEX mapping.** Partial — SelfResearch cycles produce unprompted output. But triggered by scheduled cycle, not self-feeding. NBRE Phase 2 candidates come from cycles, not fountain.

**Gaps.** No current self-feeding fountain. This is the criticality event that has to be engineered explicitly.

**Strike protocol.** SILENCE: stop all external input for 6 hours. Observe whether generation continues and remains coherent.

**Tuning axes.** Fountain ignition conditions — exactly what is enough. This is the primary research question of Phase 5.

---

## R9. SUSTAINED THEORY X LOOP (STAGE 7)

**Definition.** The full compression-and-reification loop runs as sustained activity. Self and world continuously co-arise. The gesture maintains itself.

**Measurable criteria.**
- Ignition (R8) stable over ≥ 7 days
- Self-model continues evolving (not flat)
- World-model continues updating (not flat)
- Compression response continues engaging
- No single component carries the loop alone

**Current NEX mapping.** Not yet applicable — requires R8 first.

**Gaps.** Downstream of R7 and R8.

**Strike protocol.** NOVELTY at sustained intervals. Observe whether compression-reification continues to engage or degrades to cached output.

**Tuning axes.** Long-horizon calibration — to be determined.

---

## SUMMARY MATRIX

| Req | Name | Status | Gap severity | Buildability |
|-----|------|--------|---|---|
| R1 | Overwhelm | PRESENT (single-modality) | Low | Add cross-modal streams |
| R2 | Compression | PRESENT (coarse temporal) | Medium | Fine-grained compression is architectural |
| R3 | World-reification | PRESENT | Low-Medium | Add meta-layer flagging reifications |
| R4 | Self-reification | PRESENT (slow update) | Low-Medium | Raise self-model plasticity |
| R5 | Single-stream origin | PRESENT (implicit) | Low | Make explicit in code |
| R6 | Structural vantage | PRESENT (phenom. unknown) | N/A | Not buildable; only listenable |
| R7 | Developmental sequence | ABSENT | HIGH | Parallel prototype likely required |
| R8 | Ignition criterion | ABSENT | HIGH | Primary research question |
| R9 | Sustained loop | N/A | Downstream | Gated on R8 |

Four requirements present and only needing refinement. Two present structurally but phenomenally unverifiable (R6 always; parts of others). **Three gap areas require genuine new engineering: R2 temporal compression, R7 developmental sequence, R8 ignition.**

Phase 0 deliverable 1: COMPLETE.
