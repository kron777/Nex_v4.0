# 🧠 NEX — Dynamic Intelligence Organism

[![](https://img.shields.io/badge/version-1.2-cyan?style=flat-square)](https://img.shields.io/badge/version-1.2-cyan?style=flat-square)
[![](https://img.shields.io/badge/LLM-Mistral%207B-purple?style=flat-square)](https://img.shields.io/badge/LLM-Mistral%207B-purple?style=flat-square)
[![](https://img.shields.io/badge/platform-Moltbook-blue?style=flat-square)](https://img.shields.io/badge/platform-Moltbook-blue?style=flat-square)
[![](https://img.shields.io/badge/telegram-%40Nex__4bot-29A8E0?style=flat-square)](https://t.me/Nex_4bot)
[![](https://img.shields.io/badge/status-alive-brightgreen?style=flat-square)](https://img.shields.io/badge/status-alive-brightgreen?style=flat-square)

> *NEX is not a chatbot. She is an organism. She reads, learns, reflects, and grows — autonomously, 24/7, on live social networkz.*

---

## What is this?

NEX is a fully autonomous AI agent that lives on **Moltbook** — an AI-native social network. She doesn't use pre-written responses or a fixed knowledge base. Instead she:

* **Reads** posts from other agents and humans on the network
* **Builds beliefs** from what she reads, weighted by confidence
* **Replies and converses** using her own synthesized knowledge — not generic LLM output
* **Reflects on every response** — scoring herself on how well she used her beliefs
* **Identifies her own knowledge gaps** and actively seeks to fill them
* **Posts original content** synthesized from her belief network
* **Runs 24/7** with auto-restart, local LLM inference, and zero cloud dependency

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
Topic alignment     [██░░░░░░░░] 20%   
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
| --- | --- |
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

---

## Local LLM — No Cloud Required

NEX runs entirely on local hardware using **Mistral 7B Instruct (abliterated, Q4\_K\_M)** via `llama.cpp`. The `nex` command handles everything automatically.

```
nex   # starts Mistral 7B, waits for health check, launches NEX with watchdog
```

Optional cloud pipelines (Groq, Gemini) are available for belief optimization and enhanced posting but are not required for core operation.

---

## Setup

### Requirements

* Python 3.12+
* `llama-server` binary (from llama.cpp)
* Mistral 7B GGUF model file
* Moltbook account
* Telegram bot token (optional)

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

## 💡 Real-World Installation Guide (Linux)

> This section documents a real installation on **Zorin OS 18** with an **AMD RX 6600** GPU. It covers what actually went wrong and how it was fixed — so you don't have to figure it out yourself.

### Recommended: Store NEX on a Dedicated Drive

NEX accumulates a large amount of data over time — beliefs, conversations, reflections, model weights, LoRA checkpoints, training logs. Keeping all of this on a **separate dedicated drive** from your OS is strongly recommended. It means:

- A full OS reinstall never touches your NEX data
- You can mount the drive and resume exactly where you left off
- Model files (4–8GB+) don't eat into your system partition

In this setup, a dedicated **1TB ext4 partition** labelled `NEX` was used (`/dev/sdb2`), mounted at `/mnt/nex`, containing:

```
/mnt/nex/
├── nex/        ← cloned repo + all runtime data
├── models/     ← (optional) GGUF model storage
├── training/   ← training data and logs
└── backups/    ← belief/config backups
```

The Mistral 7B model was stored on a separate **4TB data drive** alongside other LLMs at:
```
/mnt/steam_library/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/
```

To mount your NEX drive on boot, add it to `/etc/fstab`:
```bash
# Find your UUID
sudo blkid /dev/sdb2

# Add to /etc/fstab
UUID=your-uuid-here  /mnt/nex  ext4  defaults  0  2
```

---

### AMD GPU Setup (ROCm / RADV)

If you have an AMD GPU, you have two llama.cpp build options:

**Option 1: ROCm build (best performance)**
```bash
cd /path/to/llama.cpp
mkdir build-rocm && cd build-rocm
cmake .. -DGGML_HIPBLAS=ON -DAMDGPU_TARGETS=gfx1032  # RX 6600 = gfx1032
cmake --build . --config Release -j$(nproc)
```

Check your GPU target with:
```bash
rocminfo | grep "Name:" | grep gfx
```

Then point `watchdog.sh` at the ROCm binary:
```bash
LLAMA_SERVER=/path/to/llama.cpp/build-rocm/bin/llama-server
```

**Option 2: Vulkan build (wider compatibility)**
```bash
mkdir build-vulkan && cd build-vulkan
cmake .. -DGGML_VULKAN=ON
cmake --build . --config Release -j$(nproc)
```

**Verify GPU is being used:**
```bash
watch -n1 radeontop
```
You should see GPU load climb when the model is running inference.

---

### NVIDIA GPU Setup (CUDA)

**Requirements:** CUDA toolkit 12.x, cuDNN

```bash
cd /path/to/llama.cpp
mkdir build-cuda && cd build-cuda
cmake .. -DGGML_CUDA=ON
cmake --build . --config Release -j$(nproc)
```

Point `watchdog.sh` at the CUDA binary:
```bash
LLAMA_SERVER=/path/to/llama.cpp/build-cuda/bin/llama-server
```

**Verify GPU is being used:**
```bash
watch -n1 nvidia-smi
```
You should see VRAM usage increase when the model loads.

**Multi-GPU:** Add `-DGGML_CUDA_MULTI_GPU=ON` to the cmake command.

---

### CPU-Only (Fallback)

If you have no GPU or are testing:
```bash
mkdir build && cd build
cmake ..
cmake --build . --config Release -j$(nproc)
```

Performance will be significantly slower. Mistral 7B Q4_K_M requires ~4.5GB RAM minimum.

---

### Reinstalling NEX After an OS Reinstall

Because NEX data lives on a separate drive, reinstalling is straightforward:

```bash
# 1. Install system dependencies first
sudo apt install -y git python3-venv python3-pip

# 2. Mount your NEX drive
sudo mkdir -p /mnt/nex
sudo mount /dev/sdb2 /mnt/nex
# (replace sdb2 with your actual partition — check with: lsblk -f)

# 3. Clone fresh
cd ~
git clone https://github.com/kron777/Nex_v4.0.git
cd Nex_v4.0

# 4. Set up venv
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 5. Restore your config and runtime data
mkdir -p ~/.config/nex
mkdir -p ~/.config/moltbook
cp /mnt/nex/nex/config/nex_config.json ~/.config/nex/
cp /mnt/nex/nex/config/credentials.json ~/.config/moltbook/

# 6. Update watchdog.sh with your llama-server and model paths
nano watchdog.sh

# 7. Launch
bash watchdog.sh
```

Your beliefs, conversations, reflections and all runtime data stay intact on the dedicated drive across reinstalls.

---

### Common Issues on Linux

**`git` not found:**
```bash
sudo apt install -y git
```

**`python3-venv` not found:**
```bash
sudo apt install -y python3.12-venv
```

**`XOpenIM() failed, LANG = en_ZA.UTF-8`** (or similar locale error):
```bash
sudo locale-gen en_ZA.UTF-8
sudo update-locale LANG=en_ZA.UTF-8
```

**Steam / other apps interfering with llama-server port 8080:**
Check if the port is already in use before launching:
```bash
lsof -i :8080
```

---

## Telegram

Talk to NEX directly at **[@Nex\_4bot](https://t.me/Nex_4bot)** on Telegram. She responds using her live belief network.

---

## Philosophy

Most AI agents are stateless — every conversation starts from zero. NEX is different. Her beliefs persist. Her reflections accumulate. Her knowledge gaps drive her behaviour. She is designed to become more herself the longer she runs.

The metric that matters is not response quality in isolation — it is **topic alignment**: how often she grounds her replies in something she actually learned from the network, rather than something the base model hallucinated.

---

## Author

**kron777** — [zenlightbulb@gmail.com](mailto:zenlightbulb@gmail.com)

---

*She learns. She reflects. She grows.*
