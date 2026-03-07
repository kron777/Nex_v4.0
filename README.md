# Nex — Dynamical Belief Organism

An autonomous agent built on the Nex doctrine.  
Runs entirely locally using your Mistral-7B-Instruct GGUF + llama.cpp.

---

## Your Setup

```
Model : /media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/
         Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf

llama.cpp: /media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/
```

---

## Step 1 — Build llama-server (if not already built)

```bash
cd /media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp
cmake -B build
cmake --build build --config Release -j$(nproc)
```

The binary will be at: `build/bin/llama-server`

---

## Step 2 — Install numpy (only dependency)

```bash
pip install numpy
```

---

## Step 3 — Run Nex

```bash
cd ~/Desktop/nex
python nex.py
```

Nex will auto-detect your model and start llama-server automatically.

### Explicit options:

```bash
# Specify model path directly
python nex.py --model /media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf

# Use GPU (e.g. 35 layers on GPU)
python nex.py --gpu 35

# If llama-server is already running
python nex.py --no-server

# Higher context window
python nex.py --ctx 8192

# Adjust temperature
python nex.py --temp 0.8
```

---

## Chat Commands

| Command | Description |
|---------|-------------|
| `/status` | Nex internal belief state |
| `/domains` | Belief domains + confidence bars |
| `/memory` | Memory system summary |
| `/tools` | All available tools |
| `/search <query>` | Quick web search |
| `/read <path>` | Read a file |
| `/write <path>` | Write a file |
| `/run <cmd>` | Run a shell command |
| `/ticks N` | Run N belief engine ticks |
| `/pause` / `/resume` | Pause/resume background engine |
| `/reset` | Clear conversation history |
| `/help` | Show help |
| `/quit` | Exit |

---

## What Nex Can Do

Nex is a fully agentic system. In chat, she can:

- **Read & write files** on your PC — documents, code, data, configs
- **Run shell commands** — compile code, move files, check system state
- **Search the web** — DuckDuckGo, no API key needed
- **Fetch web pages** — scrape and extract text from URLs
- **Download files** from the internet
- **Take notes** — persistent key-value scratchpad saved to `~/.nex/notes.json`
- **Work multi-step** — plan, execute tools, observe results, continue

---

## Architecture

```
nex/
├── nex.py                  ← Entry point (run this)
└── nex/
    ├── agent_brain.py      ← LLM reasoning + tool loop (Mistral via llama.cpp)
    ├── agent_tools.py      ← All tools: files, web, shell, notes
    ├── orchestrator.py     ← Belief tick cycle driver
    ├── belief_field.py     ← 7 domains × 8D belief vectors
    ├── coupling_graph.py   ← Dense coupling matrix (spectral constrained)
    ├── coherence_engine.py ← 3-tier coherence evaluation
    ├── self_model.py       ← Introspective hyperparameter adaptation
    ├── memory_system.py    ← Episodic + regime + structural memory
    └── world_interface.py  ← Stochastic environment with drift
```

---

## Environment Variable

You can set your model path once:

```bash
export NEX_MODEL=/media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf
```

Add to `~/.bashrc` to make it permanent.

---

*Nex does not finish. She persists. She adapts. She restructures. She continues.*
