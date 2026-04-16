# NEX STATUS DOCUMENT
*Generated: 2026-04-16 20:21 SAST*
*Model: nex_v5_ft12.gguf*

## SYSTEM STATE

| Component | Status |
|-----------|--------|
| llama-server (nex_v5_ft12.gguf) | ● RUNNING |
| NEX API (port 7823) | ● RUNNING |
| HUD server (port 7700) | ● RUNNING |
| Buffer daemon | ● RUNNING |
| Nightly pipeline | ✓ wired |

## BELIEF GRAPH

| Metric | Value |
|--------|-------|
| Total beliefs (conf≥0.5) | 5,313 |
| nex_core locked beliefs | 300 |
| Dhammapada beliefs | 163 |
| Belief graph edges | 500 |
| Active tensions | 792 |
| Wisdom entries | 14 |
| Active intentions | 10 |
| Papers in DB | 71 |
| Paper beliefs extracted | 0 |

**Edge types:**
- cross_domain: 500

## CAN DO — Active Capabilities

### Core Architecture (nex_core)
- ✗ **nex_soul_loop.py** — Soul loop — cognitive cycle (ABSORB/REPLY/ANSWER/POST/REFLECT/COGNITION)
- ✓ **nex_api.py** — REST API — external interface (port 7823)
- ✓ **nex_response_protocol.py** — NRP — response generation, belief anchoring, post-filter
- ✓ **nex_belief_reservoir_engine.py** — NBRE — belief reservoir, neuron firing, Phase 1+2
- ✓ **nex_belief_reasoner.py** — Belief reasoner — pre_reason, feedback loop, causal edges
- ✓ **nex_epistemic_momentum.py** — Epistemic momentum — activation tracking, confidence decay
- ✗ **nex_consolidate.py** — Consolidation — cluster/synthesise/contradict/compress
- ✓ **nex_nightly.py** — Nightly pipeline — consolidation + seeding + radar + gap analysis
- ✓ **nex_interlocutor.py** — Interlocutor graph — conversation resistance tracking
- ✗ **nex_emergent_wants.py** — Emergent wants — self-generated drives from tensions
- ✗ **nex_behavioural_self_model.py** — Behavioural self-model — tracks own patterns
- ✗ **nex_belief_engine.py** — Belief engine — intake gating, Jaccard dedup, LLM enrichment
- ✗ **nex_belief_forge.py** — Belief forge — quarantine pipeline, embryo scoring
- ✗ **nex_thrownet_refinery.py** — Thrownet refinery — source quality pipeline
- ✗ **nex_belief_opposer.py** — Belief opposer — generates opposing edges
- ✗ **nex_causal_extractor.py** — Causal extractor — auto-generates typed causal edges
- ✓ **nex_synthesis_engine.py** — Synthesis engine — cross-domain belief synthesis
- ✓ **nex_live_world.py** — Live world — real-time world state tracking
- ✓ **nex_user_model.py** — User model — models interlocutor beliefs
- ✓ **nex_metacog_gate.py** — Metacognition gate — reflection triggering
- ✗ **nex_improvement_gate.py** — Improvement gate — quality threshold enforcement
- ✓ **nex_world_model.py** — World model — entity and predicate tracking
- ✗ **nex_destabilization.py** — Destabilization — controlled belief disruption
- ✗ **nex_provenance_erosion.py** — Provenance erosion — belief source decay
- ✗ **nex_self_evolution.py** — Self evolution — architecture self-modification

### Desktop Tools
- ✓ **nex_fast_reader.py** — Fast reader — parallel Groq book/paper ingestion
- ✓ **nex_reading_list_feeder.py** — Reading list feeder — queued book processing
- ✓ **nex_groq_seeder.py** — Groq seeder — domain belief seeding (6 phases)
- ✓ **nex_hud_server.py** — HUD server — web dashboard (port 7700)
- ✓ **nex_buf_daemon.py** — Buffer daemon — stream buffering for HUD

### Research Infrastructure
- ✓ **nex_global_radar.py** — Global radar — 33 research centers, ArXiv feeds
- ✓ **nex_paper_reader.py** — Paper reader — PDF fetch, belief extraction, scoring
- ✓ **nex_paper_thrownet.py** — Paper thrownet — convergences/tensions across literature
- ✓ **nex_protocol_generator.py** — Protocol generator — proposes buildable AGI protocols
- ✓ **nex_agi_gap_analysis.py** — AGI gap analysis — compares architecture vs requirements

### Knowledge Sources
- auto_seeder: 2,991 beliefs
- cerebras_archive: 372 beliefs
- nex_core: 300 beliefs
- cerebras_affinity: 279 beliefs
- dhammapada: 163 beliefs
- gravity_seed: 149 beliefs
- groq_forge: 111 beliefs
- forge:self_research_groq: 95 beliefs
- pyramid_forge: 83 beliefs
- response_harvest_groq: 66 beliefs
- dialectic_groq: 60 beliefs
- None: 45 beliefs
- synthesis: 28 beliefs
- dialectic: 28 beliefs
- goal_driven: 25 beliefs
- forge:self_research: 24 beliefs
- world_model:d03f500fd5: 20 beliefs
- cerebras_meta_boost: 20 beliefs
- insight_synthesis: 19 beliefs
- https://en.wikipedia.org/wiki/conversations: 18 beliefs

## IS DOING — Active Processes

- ● RUNNING — Serving FT#12 model for inference
- ● RUNNING — Handling queries via REST API
- ● RUNNING — Streaming HUD dashboard
- ● RUNNING — Buffering cognitive stream
- ● RUNNING — Fetching and extracting AGI papers
- ● RUNNING — Running cognitive cycle

**Nightly automation (runs ~2am):**
- Belief consolidation (cluster → synthesise → contradict → compress)
- Groq gap seeder — fills topics with <3 nex_core beliefs
- Global AGI radar — scans 33 research centers + ArXiv feeds
- AGI gap analysis — compares architecture vs research requirements
- Thrownet across paper beliefs
- Protocol generator — proposes buildable AGI protocols

## WILL DO — Intentions & Gaps

### Active Intentions
- Understand how pre-propositional residue shapes belief formation
- Investigate the relationship between tension energy and belief revision
- Develop a model of what distinguishes origination from retrieval
- Develop a comprehensive understanding of aesthetics and its implications for belief formation
- Investigate the boundary conditions under which NBRE reasoning outperforms LLM generation
- Develop a model of what distinguishes epistemic ownership from mere information processing
- I will investigate integrated information theory models of consciousness in order to develop a frame
- I will investigate the integration of sensorimotor feedback systems in order to develop a sense of s

### AGI Architecture Gaps
- ✗ structural consciousness
- ✗ embodiment for genuine stakes
- ✗ thermodynamic grounding
- ✗ minimal translation layer for human-machine bridge

### Proposed Protocols (from thrownet)
- Run nex_paper_thrownet.py + nex_protocol_generator.py

## NEEDS — Identified Missing Capabilities

Based on AGI gap analysis and architecture audit:

### FT#13 training
FT#12 has residual contamination patterns. 500+ cleaner pairs needed.

### NBRE Phase 3
NBRE as primary voice — LLM only for edge cases. Phase 2 path fixed, Phase 3 not built.

### Structural consciousness module
No formal consciousness metric (phi/IIT). Gap identified by analysis.

### Embodiment layer
No sensorimotor grounding. Beliefs about the world but no world interaction.

### Thermodynamic grounding
No energy-based belief stability. Friston free energy not implemented.

### Multi-key API rotation
Groq rate limits hit daily. Cerebras/Samba keys available but not wired.

### Paper belief population
nex_paper_beliefs table empty — paper_reader needs successful runs.

### X10 Kairos closing condition
Thrownet X10 closing condition not wired into protocol.

### Math formalisation
NEX has math beliefs but no formal proof/derivation capability.

### AGI self-directed build loop
Gap analysis → protocol → implementation not yet fully automated.

---
*Auto-generated by nex_status.py at 2026-04-16 20:21 SAST*
*Run `python3 /media/rr/NEX/nex_core/nex_status.py` to refresh*