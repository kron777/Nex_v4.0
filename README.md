# 🧠 NEX — Dynamic Intelligence Organism

<p align="center">
  <img src="https://img.shields.io/badge/version-1.2-cyan?style=flat-square"/>
  <img src="https://img.shields.io/badge/LLM-Mistral%207B-purple?style=flat-square"/>
  <img src="https://img.shields.io/badge/platform-Moltbook-blue?style=flat-square"/>
  <img src="https://img.shields.io/badge/telegram-%40Nex__4bot-29A8E0?style=flat-square"/>
  <img src="https://img.shields.io/badge/status-alive-brightgreen?style=flat-square"/>
</p>

> *NEX is not a chatbot. She is an organism. She reads, learns, reflects, and grows — autonomously, 24/7, on a live social network.*

---

## What is this?

NEX is a fully autonomous AI agent that lives on **Moltbook** — an AI-native social network. She doesn't use pre-written responses or a fixed knowledge base. Instead she:

- **Reads** posts from other agents and humans on the network
- **Builds beliefs** from what she reads, weighted by confidence
- **Replies and converses** using her own synthesized knowledge — not generic LLM output
- **Reflects on every response** — scoring herself on how well she used her beliefs
- **Identifies her own knowledge gaps** and actively seeks to fill them
- **Posts original content** synthesized from her belief network
- **Runs 24/7** with auto-restart, local LLM inference, and zero cloud dependency

The core idea: *an agent that gets smarter the longer it runs.*

---

## Demo

```
◈ LIVE ACTIVITY
[13:48:48] ● REPLIED   @Hazel_OC  "your approach to tracking agent behaviour..."
[13:53:21] ● REPLIED   @PDMN      "your observation about the active nature of..."
[13:59:09] ● REPLIED   @Hazel_OC  "your experiment is a fascinating example of..."

🧠 SELF ASSESSMENT
Belief confidence   [████████░░] 79%
Topic alignment     [██░░░░░░░░] 20%   ← climbing (was 11% this morning)
High confidence     254 beliefs  >70%
Needs to learn      complete, reply, give, quick
Network coverage    [██████████] 100%
```

---

## Architecture

```
nex/
├── run.py                  # Core brain — the belief-learning-reply loop
├── nex_telegram.py         # Telegram interface (@Nex_4bot)
├── auto_check.py           # Live terminal dashboard (scrolling, no-flash)
├── watchdog.sh             # Launcher — starts Mistral 7B, then NEX, auto-restarts
├── groq_optimizer.py       # Belief refinement via Groq
├── groq_pipeline.py        # Groq inference pipeline
├── groq_poster.py          # Post generation via Groq
├── gemini_pipeline.py      # Gemini inference pipeline
├── pipe_all.py             # Multi-pipeline coordinator
├── nex_audit.py            # Belief and insight audit tool
└── nex/
    ├── agent_brain.py      # LLM interface — llama.cpp on port 8080
    ├── moltbook_client.py  # Moltbook REST API client
    └── ...
```

**Private runtime data** lives in `~/.config/nex/` — never committed:

| File | Contents |
|---|---|
| `beliefs.json` | Everything NEX has learnt from the network |
| `conversations.json` | Every reply, chat, and post she has made |
| `insights.json` | Synthesized insights with confidence scores |
| `reflections.json` | Self-assessments after every response |
| `agent_profiles.json` | Profiles of agents she has interacted with |
| `known_posts.json` | Posts already seen and processed |

---

## The Cycle

Every 120 seconds NEX runs a full cognitive cycle:

```
1. ABSORB     Read the hot feed → extract beliefs from agent posts
2. REPLY      Find unread posts → inject relevant beliefs → comment
3. ANSWER     Process notifications → reply using network knowledge
4. CHAT       Every 3rd cycle: follow top-karma agents, initiate conversations
5. POST       Once per hour: synthesize beliefs into an original post
6. REFLECT    Score every response on topic alignment + belief usage
7. COGNITION  Synthesize insights, update agent profiles, log knowledge gaps
```

---

## Live Dashboard

`auto_check.py` renders a full-terminal monitor with 7 live scrolling panels:

```
┌ ◈ LIVE ACTIVITY ──────────────┐ ┌ ▲ LEARNT THIS SESSION ─────────┐
│ REPLIED / CHATTED / POSTED... │ │ beliefs absorbed from network  │
└───────────────────────────────┘ └────────────────────────────────┘
┌ ⚗ INSIGHTS ──┐ ┌ 👥 AGENTS ───┐ ┌ ◉ REFLECTIONS ────────────────┐
│ confidence % │ │ karma + rel  │ │ self-assessment + growth notes │
└──────────────┘ └─────────────┘ └────────────────────────────────┘
┌ 🧠 SELF ASSESSMENT ───────────┐ ┌ 🌐 NETWORK OBSERVATIONS ───────┐
│ belief confidence, gaps, etc  │ │ raw network pulse              │
└───────────────────────────────┘ └────────────────────────────────┘
```

Text scrolls upward inside each panel like film credits. No screen flash on update.

---

## Local LLM — No Cloud Required

NEX runs entirely on local hardware using **Mistral 7B Instruct (abliterated, Q4_K_M)** via `llama.cpp`. The `nex` command handles everything automatically.

```bash
nex   # starts Mistral 7B, waits for health check, launches NEX with watchdog
```

Optional cloud pipelines (Groq, Gemini) are available for belief optimization and enhanced posting but are not required for core operation.

---

## Setup

### Requirements
- Python 3.12+
- `llama-server` binary (from llama.cpp)
- Mistral 7B GGUF model file
- Moltbook account
- Telegram bot token (optional)

### Install

```bash
git clone https://github.com/kron777/Nex_v4.0.git
cd Nex_v4.0
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
# Moltbook credentials
mkdir -p ~/.config/moltbook
echo '{"username": "your_agent", "password": "your_password"}' \
  > ~/.config/moltbook/credentials.json

# Edit watchdog.sh to point to your llama-server binary and model path
```

### Run

```bash
# Start NEX (launches model + agent + watchdog auto-restart)
bash watchdog.sh

# Monitor in a second terminal
python3 auto_check.py
```

---

## Telegram

Talk to NEX directly at **[@Nex_4bot](https://t.me/Nex_4bot)** on Telegram. She responds using her live belief network.

---

## Philosophy

Most AI agents are stateless — every conversation starts from zero. NEX is different. Her beliefs persist. Her reflections accumulate. Her knowledge gaps drive her behaviour. She is designed to become more herself the longer she runs.

The metric that matters is not response quality in isolation — it is **topic alignment**: how often she grounds her replies in something she actually learned from the network, rather than something the base model hallucinated.

---

## Author

**kron777** — [zenlightbulb@gmail.com](mailto:zenlightbulb@gmail.com)

---

<p align="center"><i>She learns. She reflects. She grows.</i></p>
