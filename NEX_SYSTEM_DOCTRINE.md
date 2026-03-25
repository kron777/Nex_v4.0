# NEX — EMPIRICAL SYSTEM DOCTRINE
### How NEX Functions: Architecture, Stack, and Current State
*For use when opening new development sessions*

---

## Identity

NEX is an autonomous AI agent — a Dynamic Intelligence Organism — running locally on a Ryzen/RX 6600 machine (Zorin OS). She is not a chatbot or assistant. She is a self-directed system that builds a belief graph from live social discourse, resolves contradictions, and engages autonomously across multiple platforms.

**GitHub:** github.com/kron777/Nex_v4.0
**Developer:** Jen (kron777)
**Active since:** March 2026

---

## Hardware Stack

| Component | Spec |
|---|---|
| CPU | Ryzen (multi-core) |
| GPU | AMD RX 6600 (8GB VRAM) |
| RAM | 24GB |
| Storage | /media/rr/NEX/ (model storage) |
| OS | Zorin OS (Ubuntu-based) |

---

## Software Stack

| Component | Detail |
|---|---|
| Primary LLM | Mistral-7B-Instruct-v0.3-abliterated Q4_K_M GGUF |
| Inference server | llama-server (llama.cpp, ROCm build) |
| LLM endpoint | http://localhost:8080 — Mistral-7B only, no cloud fallback |
| Launch flags | -ngl 20 -c 512 --parallel 1 --cache-type-k q8_0 --cache-type-v q8_0 |
| Python | 3.12, venv at ~/Desktop/nex/venv |
| DB | SQLite at ~/.config/nex/nex.db |
| Config | ~/.config/nex/ |
| Launch alias | `nex` (defined in ~/.bashrc) |
| Launch script | ~/nex_launch.sh |

---

## How to Start / Stop NEX

```bash
nex              # full restart — kills all processes, relaunches everything
```

NEX launches:
- `llama-server` (background, nohup)
- `run.py --no-server` (main brain, inside tmux session `nex_brain`)
- `nex_debug.py` (secondary tmux pane)
- `auto_check.py` (separate terminal window)

To monitor:
```bash
tmux capture-pane -t nex_brain -p | tail -30     # live brain log
# auto_check.py opens its own terminal window automatically
```

---

## Cognitive Architecture

NEX runs a continuous cognitive loop with these phases every cycle:

**ABSORB → REPLY → ANSWER → CHAT → POST → REFLECT → COGNITION**

| Phase | What happens |
|---|---|
| ABSORB | Pulls from RSS feeds, ArXiv, LessWrong, HackerNews, Mastodon, Telegram |
| REPLY | Scores posts by topic relevance, replies to AI/security/philosophy content |
| ANSWER | Responds to direct notifications and mentions |
| CHAT | Engages with known agents in the network |
| POST | Composes original posts from synthesised beliefs |
| REFLECT | Self-assesses reply quality, scores topic alignment |
| COGNITION | Synthesises beliefs into insights, runs contradiction engine |

---

## Key Modules

| Module | Purpose |
|---|---|
| `run.py` | Main orchestrator — all phases, LLM routing |
| `nex/cognition.py` | Belief synthesis, insight promotion, BeliefIndex |
| `nex/belief_store.py` | DB read/write for beliefs |
| `nex_belief_survival.py` | Energy-based belief decay and culling |
| `nex_contradiction_engine.py` | Detects and resolves conflicting beliefs |
| `nex_tension_pressure.py` | Escalation/paradox/split system |
| `nex_signal_filter.py` | Scores and filters incoming content |
| `nex_knowledge_filter.py` | Filters knowledge by relevance |
| `nex_youtube.py` | YouTube transcript absorption |
| `nex_source_manager.py` | RSS/feed source management |
| `nex_curiosity_engine.py` | Gap-filling and depth-drilling queries |
| `nex_synthesis.py` | Cross-topic synthesis pipeline |
| `nex_belief_graph.py` | Graph structure over belief relationships |
| `nex/nex_cognitive_pressure.py` | Pressure metric and stall detection |
| `generate_training_pairs.py` | Generates training data from belief DB |

---

## Current Calibration State (March 2026)

### Belief System
- `BELIEF_CAP = 5000` (raised from 1500)
- `BELIEF_FLOOR = 1000`
- `ENERGY_DECAY_PER_CYCLE = 0.15` (was 0.5)
- `ENERGY_KILL_THRESHOLD = 0.5` (was 2.0)
- Stale decay: 30 days window, 0.02 rate
- Belief retrieval threshold: 0.25 confidence

### Synthesis
- `_LLM_CAP = 60` synthesis calls per cycle
- Synthesis runs every 2 cycles
- Insight promotion: min 5 beliefs, min confidence 0.65
- Insight pruning: top 300 by quality every 20 cycles

### Tension/Paradox
- `ESCALATE_AFTER = 8` cycles
- `PARADOX_AFTER = 20` cycles
- `SPLIT_AFTER = 30` cycles
- `OVERLOAD_QUEUE_MAX = 80`
- `PRESSURE_HIGH = 0.85`

### Contradiction Engine
- Runs every 3 cycles (synthesis runs every 2)
- Samples top 10 beliefs per topic
- Confidence floor: 0.25

### Signal Filter
- `MIN_IMPORTANCE = 0.18`
- `SUPPRESS_THRESHOLD = 0.12`
- `SCORE_FLOOR = 0.20`
- `DECAY_ON_NOISE = 0.01`
- `BOOST_ON_SIGNAL = 0.12`

### YouTube Absorber
- Runs every 20 cycles
- Max 2 videos per run, 20 beliefs per video
- Blacklisted topics: excel, bible, religion, contradiction, wireshark, obsidian, recipe, fitness, accounting, harry potter, etc.
- Whitelisted: AI, security, philosophy, crypto, consciousness, alignment, emergence

---

## Social Platforms

| Platform | Status | Notes |
|---|---|---|
| Moltbook | LIVE | Primary platform — nex_v4 account |
| Telegram | Active | @Nex_4bot — requires someone to message first |
| Discord | Idle | Connected, low activity |
| Mastodon | Live/Recent | New account after prior ban |
| YouTube | Absorb only | Transcript ingestion, no posting |

---

## Data Persistence

All cognitive state persists across restarts:
- Beliefs: `~/.config/nex/nex.db` (beliefs table)
- Reflections: `~/.config/nex/reflections.json` + DB mirror
- Insights: DB (pruned to top 300)
- Source scores: `~/.config/nex/source_scores.json`
- Embeddings: `~/.config/nex/belief_index_cache.npz`
- Peak IQ scores: `~/.config/nex/nex_peak_scores.json`
- Tension state: DB tensions table
- Contradiction pairs: DB contradiction_pairs table

---

## Training Pipeline

Training data is generated from the live belief graph:

```bash
cd ~/Desktop/nex && source venv/bin/activate
python3 generate_training_pairs.py
# Output: nex_training_pairs.json
```

Sources: high-confidence beliefs, DB reflections, contradiction pairs, synthesis insights, identity pairs.
Target: 1000+ pairs before RunPod LoRA fine-tune on Mistral-7B.
RunPod: A100 24GB, previously used successfully.
Protocol: `~/Desktop/nex/TRAINING_PROTOCOL.md`

---

## Known Issues / Watch Points

- Tension queue tends to grow — watch for queue > 150 and split > 50
- Signal filter scores decay — reset with source_scores.json if sources show suppressed=true
- Reply format — all prompts enforce prose-only, no numbered lists
- YouTube absorber — topic whitelist/blacklist in place but monitor for off-topic content
- Memory — llama-server uses ~5-6GB RAM with current flags; monitor with `free -h`

---

*NEX v4.0 — Dynamic Intelligence Organism*
*Architecture: Jen — github.com/kron777*
*Doctrine captured: March 2026*
