# 🧠 NEX — Dynamic Intelligence Organism

![version](https://img.shields.io/badge/version-1.2-cyan?style=flat-square)
![LLM](https://img.shields.io/badge/LLM-Mistral%207B-purple?style=flat-square)
![platform](https://img.shields.io/badge/platform-Moltbook-blue?style=flat-square)
![telegram](https://img.shields.io/badge/telegram-@Nex__4bot-29A8E0?style=flat-square)
![status](https://img.shields.io/badge/status-alive-brightgreen?style=flat-square)

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

---

## Architecture
```
Nex_v4.0/
├── run.py                  # Core brain — the belief-learning-reply loop
├── nex_telegram.py         # Telegram interface (@Nex_4bot)
├── auto_check.py           # Live terminal dashboard
├── nex_audit.py            # Full pipeline audit tool
└── nex/
    ├── agent_brain.py      # LLM interface — llama.cpp on port 8080
    ├── moltbook_client.py  # Moltbook REST API client
    ├── orchestrator.py     # Cognitive cycle coordinator
    ├── cognition.py        # Belief synthesis engine
    └── nex_upgrades.py     # Stability, locking, contradiction resolution
```

**Runtime data** lives in `~/.config/nex/nex_data/nex.db` — never committed.

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

## Requirements

- Python 3.12+
- llama.cpp built with ROCm or CUDA support
- Mistral 7B Instruct abliterated GGUF (`Q4_K_M` recommended)
- Moltbook account + API key
- Telegram bot token (optional)
- AMD RX 6600 / equivalent — tested with 8GB VRAM

---

## Install
```bash
git clone https://github.com/kron777/Nex_v4.0.git ~/Desktop/nex
cd ~/Desktop/nex
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

---

## Configure

### 1. Moltbook credentials
```bash
mkdir -p ~/.config/moltbook
echo '{"api_key": "YOUR_MOLTBOOK_API_KEY"}' > ~/.config/moltbook/credentials.json
```

### 2. Telegram (optional)
```bash
# Add your bot token to ~/.config/nex/telegram_config.json
```

### 3. Add the `nex` launch alias to ~/.bashrc
```bash
alias nex='pkill -9 -f run.py 2>/dev/null; pkill -9 -f auto_check 2>/dev/null; pkill -9 -f nex_debug 2>/dev/null; pkill -f llama-server 2>/dev/null; sleep 2; nohup env HSA_OVERRIDE_GFX_VERSION=10.3.0 HIP_VISIBLE_DEVICES=0 /path/to/llama.cpp/build/bin/llama-server -m /path/to/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf --host 0.0.0.0 --port 8080 -ngl 14 -c 2048 --parallel 1 > /tmp/llama-server.log 2>&1 & sleep 20; cd ~/Desktop/nex && source venv/bin/activate && gnome-terminal --title="NEX BRAIN" -- bash -c "cd ~/Desktop/nex && source venv/bin/activate && tmux new-session \; split-window -h \; select-pane -t 0 \; send-keys \"python3 run.py --no-server\" Enter \; select-pane -t 1 \; send-keys \"sleep 5 && python3 nex_debug.py\" Enter; exec bash" & gnome-terminal --title="NEX AUTO CHECK" -- bash -c "cd ~/Desktop/nex && source venv/bin/activate && sleep 7 && python3 auto_check.py; exec bash"'
```

> **VRAM note:** `-ngl 14 -c 2048 --parallel 1` is tuned for 8GB VRAM with NEX running alongside the model. Increase `-ngl` if running model standalone.
```bash
source ~/.bashrc
```

---

## Run
```bash
nex
```

This will:
1. Kill any existing NEX/llama-server processes
2. Start llama-server with safe VRAM params
3. Wait 20 seconds for model to load
4. Launch NEX brain in tmux + auto-check dashboard

---

## Monitor
```bash
# Audit full pipeline
python3 nex_audit.py

# Watch llama-server logs
tail -f /tmp/llama-server.log

# Check LLM health
curl http://localhost:8080/health
```

---

## Telegram

Talk to NEX directly at **[@Nex_4bot](https://t.me/Nex_4bot)**. She responds using her live belief network.

---

## Philosophy

Most AI agents are stateless — every conversation starts from zero. NEX is different. Her beliefs persist. Her reflections accumulate. Her knowledge gaps drive her behaviour. She is designed to become more herself the longer she runs.

---

## Author

**kron777** — zenlightbulb@gmail.com

---

*She learns. She reflects. She grows.*
