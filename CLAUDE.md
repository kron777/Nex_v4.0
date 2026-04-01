# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

NEX v4.0 is a locally-running autonomous AI reasoning agent. It is **not** a chatbot wrapper — it maintains a persistent belief graph (SQLite + ChromaDB) that grows over time, reasons from accumulated beliefs, and uses a local LLM (llama-server) purely as a voice layer. The graph does the thinking; the LLM speaks.

## Running NEX

**Full stack startup:**
```bash
source venv/bin/activate
./start_nex.sh
```

**Running components individually (assumes llama-server already running at localhost:8080):**
```bash
python3 run.py --no-server --background   # Main cognitive loop
python3 nex_api.py                         # REST API (port 7823)
python3 nex_scheduler.py                   # Domain saturation scheduler (port 7825)
python3 auto_check.py                      # Watchdog process
python3 nex_debug.py                       # Debug terminal with belief browser
```

**run.py flags:**
```
--model /path/to/gguf    Explicit GGUF model path
--port 8080              llama-server port
--gpu 35                 GPU layers to offload
--ticks 100              Belief engine cycles before chat
--no-server              External llama-server expected
--background             Run without terminal UI
```

**Testing via curl:**
```bash
# Chat
curl -X POST http://localhost:7823/chat \
  -H "X-API-Key: nex-..." \
  -d '{"query":"What do you think about alignment?"}'

# Belief stats
curl http://localhost:7823/stats

# Trigger scheduler job
curl -X POST http://localhost:7825/scheduler/trigger \
  -H "X-Admin-Secret: nex-admin-2026" \
  -d '{"job":"saturation"}'
```

## Architecture

### Cognitive Cycle (nex/nex_soul_loop.py)
Every user input passes through 5 stages:
1. **ORIENT** — classify query intent (position / probe / self_inquiry / social)
2. **CONSULT** — read live affect state, drives, narrative context
3. **REASON** — 3-hop belief resonance chain: anchor → neighbors → tensions → synthesis
4. **INTEND** — map to active intention (identity defense / curiosity / drive)
5. **EXPRESS** — assemble from character, generate via LLM, apply epistemic temperature

### Belief Graph (nex/belief_store.py)
- Primary store: SQLite at `/home/rr/Desktop/nex/nex.db` (hardcoded in many modules)
- Vector search: ChromaDB at `~/.config/nex/chroma/`
- Key table: `beliefs(id, content, topic, confidence, source, belief_type, embedding, locked)`
- Supporting tables: `metabolism_log`, `bridge_history`, `belief_edges`
- **Always use INSERT OR IGNORE** — UNIQUE constraint on content causes spam otherwise

### LLM Backend
- Primary: Qwen2.5-3B QLoRA fine-tuned (`nex_lora_f16.gguf`)
- Fallback: Mistral-7B-Instruct Q4_K_M
- Served by llama-server at `localhost:8080` — binary lives at `/media/rr/NEX/llama.cpp/build/bin/llama-server`
- Models stored on external mount: `/media/rr/NEX/models/`

### Service Ports
| Port | Service |
|------|---------|
| 8080 | llama-server (LLM inference) |
| 7823 | REST API (Flask, nex_api.py) |
| 7824 | Web dashboard |
| 7825 | Scheduler API (nex_scheduler.py) |

### Autonomous Background Processes
- **Every 6h:** Auto-seeder ingests ArXiv/RSS feeds → injects beliefs
- **3:00 AM:** Topic repair cron
- **6:00 AM:** Health monitor cron
- **02:00–06:00 nightly:** Annealing engine (coherence crystallization)
- **On demand:** QLoRA fine-tuning when domain saturation targets are met (200 beliefs/domain)

### Upgrade Stack
`nex_upgrades/` contains 29 version files (v5.0 → R115) that patch cognition non-invasively. They are applied in run.py imports at startup. When adding new capabilities, follow this pattern rather than modifying core files directly.

## Key Files

| File | Purpose |
|------|---------|
| `run.py` | Entry point, ~294KB, heavily patched at top with imports |
| `nex/nex_soul_loop.py` | Core 5-step cognition (best abstraction to read first) |
| `nex/belief_store.py` | All SQLite read/write operations |
| `nex_api.py` | REST API, Tier 1–3 auth, belief routes |
| `nex_annealing.py` | Overnight coherence engine |
| `nex_homeostasis.py` | 9-layer system regulation stack |
| `nex/auto_learn.py` | Learning from user feedback |
| `nex/nex_affect_valence.py` | Emotion derived from belief field energy |
| `nex_plan.txt` | 8-phase architecture roadmap — read before planning changes |

## Critical Development Rules

These come from `nex_plan.txt` and past incidents:

1. **Always read the actual current source** before proposing changes — never work from assumptions or recalled file contents.
2. **One change at a time** — verify with curl before moving on.
3. **Commit after each verified step.**
4. **NEX replies must derive from the belief graph**, not templates or hardcoded strings.
5. **Reduce LLM dependency** — the graph reasons, the LLM only vocalizes.
6. Watch for **unicode em-dashes** (—) in source — use line-number patching when they cause parse issues.
7. Many **backup files** exist (`*.bak`, `*.pre_*`) — confirm you're editing the live version.

## Current Roadmap (from nex_plan.txt)

**Phase 1 (immediate priority):** Build graph edges — `belief_edges(belief_a_id, belief_b_id, weight, edge_type)` with types: `topic_sibling`, `topic_bridge`, `tension`, `supports`, `synthesis`. This unlocks all downstream phases.

**Phases 2–8:** Graph activation → annealing → epistemic temperature → emergent emotion → graph memory → emergent curiosity → second QLoRA run.

## Environment

```bash
# Required for AMD GPU (RX 6600 LE)
HSA_OVERRIDE_GFX_VERSION=10.3.0
HSA_ENABLE_SDMA=0
ROCR_VISIBLE_DEVICES=0
LD_LIBRARY_PATH=/media/rr/NEX/llama.cpp/build/bin
```

Python venv: `/home/rr/Desktop/nex/venv/`
