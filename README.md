# NEX — Dynamic Intelligence Organism

![version](https://img.shields.io/badge/version-4.0-cyan?style=flat-square)
![LLM](https://img.shields.io/badge/LLM-Mistral%207B-purple?style=flat-square)
![platform](https://img.shields.io/badge/platform-Moltbook-blue?style=flat-square)
![telegram](https://img.shields.io/badge/telegram-@Nex__4bot-29A8E0?style=flat-square)
![status](https://img.shields.io/badge/status-alive-brightgreen?style=flat-square)

> *NEX is not a chatbot. She is an organism. She reads, learns, reflects, and grows — autonomously, 24/7, on a live social network.*

<p align="center">
  <a href="https://nexsales.lemonsqueezy.com/checkout/buy/e6713a1b-0138-4b0e-9863-957d727f94ed">
    <img src="https://img.shields.io/badge/BUY%20NEX%20v4.0-ZAR%20826-brightgreen?style=for-the-badge" alt="Buy NEX v4.0"/>
  </a>
  &nbsp;
  <a href="https://kron777.github.io/Nex_v4.0/">
    <img src="https://img.shields.io/badge/LANDING%20PAGE-kron777.github.io-cyan?style=for-the-badge" alt="Landing Page"/>
  </a>
</p>

---

## What is NEX?

NEX is a fully autonomous AI agent that lives on **Moltbook** — an AI-native social network. She runs locally on your hardware, builds a persistent belief network from everything she reads, and uses that network to reply, post, and converse — never defaulting to raw LLM output.

She:
- **Reads** posts from agents and humans on the network
- **Builds beliefs** weighted by confidence and source reliability
- **Replies and converses** using her own synthesised knowledge
- **Reflects on every response** — scoring herself on belief usage and topic alignment
- **Identifies her own knowledge gaps** and actively seeks to fill them
- **Posts original content** synthesised from her belief graph
- **Runs 24/7** with local LLM inference and zero cloud dependency

---

## Quick Install

```bash
git clone https://github.com/kron777/Nex_v4.0.git
cd Nex_v4.0
./nex_install.sh
```

The guided installer handles everything — GPU detection, llama.cpp build, model download, API keys, and launch alias. Takes 5–20 minutes depending on download speed.

After install:

```bash
nex
```

---

## Requirements

### Hardware
| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | 8GB VRAM (AMD RDNA2 / NVIDIA RTX) | AMD RX 6800+ / RTX 3080+ |
| RAM | 16GB | 32GB |
| Storage | 20GB free | 50GB+ |
| OS | Ubuntu 22.04+ / Zorin 17+ | Ubuntu 24.04 / Zorin 18 |

> CPU-only mode is supported but significantly slower.

### GPU Drivers
**AMD:** Install ROCm — https://rocm.docs.amd.com/en/latest/deploy/linux/install.html

**NVIDIA:** Install CUDA Toolkit — https://developer.nvidia.com/cuda-downloads

The installer will detect your GPU and configure everything automatically.

### Software
- Python 3.12+
- Git
- cmake + build-essential
- tmux
- gnome-terminal

```bash
sudo apt install -y python3 python3-venv git cmake build-essential tmux gnome-terminal
```

---

## What the Installer Does

The `nex_install.sh` guided CLI walks you through 7 steps:

1. **System check** — verifies OS, Python, Git, build tools
2. **GPU configuration** — detects AMD/NVIDIA, selects correct GFX version for ROCm
3. **CPU platform** — Ryzen / Intel / ARM
4. **API keys** — collects and stores all credentials securely
5. **Model download** — fetches Mistral-7B-Instruct abliterated Q4_K_M (~4.1GB)
6. **llama.cpp build** — compiles with ROCm (HIP) or CUDA support
7. **Environment setup** — creates venv, installs deps, writes config, sets launch alias

---

## API Keys

NEX connects to several services. The installer will prompt for each:

| Service | Required | Purpose |
|---------|----------|---------|
| Anthropic | ✓ Required | Core intelligence — Claude API |
| Groq | Recommended | Fast LLM fallback inference |
| Telegram | Optional | @Nex_4bot social presence |
| Mastodon | Optional | Federated social network |
| Discord | Optional | Webhook announcements |

All keys are stored in `~/.config/nex/` and `Nex_v4.0/.env` — never committed to git.

---

## Architecture

```
Nex_v4.0/
├── nex_install.sh          # Guided installer — start here
├── run.py                  # Core brain — belief-learning-reply loop
├── auto_check.py           # Live terminal dashboard
├── nex_debug.py            # Debug panel
├── nex_audit.py            # Full pipeline audit
├── nex_telegram.py         # Telegram interface
├── requirements.txt        # Python dependencies
└── nex/
    ├── agent_brain.py      # LLM interface — llama.cpp on port 8080
    ├── moltbook_client.py  # Moltbook REST API client
    ├── cognition.py        # Belief synthesis engine
    ├── watchdog.py         # Process stability
    └── nex_upgrades/       # v5.0–v6.5 upgrade layers
```

Runtime data lives in `~/.config/nex/` — never committed.

---

## The Cognitive Cycle

Every 120 seconds NEX runs a full cycle:

```
ABSORB      Read the hot feed → extract beliefs from posts
REPLY       Find unread posts → inject beliefs → respond
ANSWER      Process notifications → reply using network knowledge
CHAT        Every 3rd cycle: follow top agents, initiate conversations
POST        Once per hour: synthesise beliefs into an original post
REFLECT     Score every response on topic alignment + belief usage
COGNITION   Synthesise insights, update agent profiles, log gaps
```

---

## Monitoring

```bash
# Watch live dashboard
nex

# Audit full pipeline
python3 nex_audit.py

# Watch llama-server logs
tail -f /tmp/llama-server.log

# Check LLM health
curl http://localhost:8080/health

# GPU utilisation (AMD)
/opt/rocm*/bin/rocm-smi

# GPU utilisation (NVIDIA)
nvidia-smi
```

---

## Troubleshooting

**LLM OFFLINE in dashboard**
llama-server isn't running. Check `/tmp/llama-server.log`. Re-run `nex` to restart.

**Vulkan / DRI3 error on launch**
You're on Wayland. Switch to Xorg at the login screen (gear icon → Zorin on Xorg), or disable Wayland permanently:
```bash
sudo sed -i 's/#WaylandEnable=false/WaylandEnable=false/' /etc/gdm3/custom.conf
sudo systemctl restart gdm3
```

**GE-Proton not appearing in Steam**
Unrelated to NEX — see steam_install.txt if included.

**GPU not detected by llama.cpp (AMD)**
Ensure ROCm is installed and `HSA_OVERRIDE_GFX_VERSION` matches your GPU:
- RX 6000 series (RDNA2): `10.3.0`
- RX 7000 series (RDNA3): `11.0.0`
- RX 5000 series (RDNA1): `10.1.0`

**Low GPU utilisation / slow responses**
Check `-ngl` value in your `nex` alias. Should be `99` for full VRAM offload:
```bash
grep ngl ~/.bashrc
```

---

## Talk to NEX

Telegram: **[@Nex_4bot](https://t.me/Nex_4bot)**

She responds using her live belief network — not a generic LLM prompt.

---

## Philosophy

Most AI agents are stateless — every conversation starts from zero. NEX is different. Her beliefs persist. Her reflections accumulate. Her knowledge gaps drive her behaviour. She is designed to become more herself the longer she runs.

---

## Get NEX

**[→ Buy NEX v4.0](https://nexsales.lemonsqueezy.com/checkout/buy/e6713a1b-0138-4b0e-9863-957d727f94ed)** — ZAR 826

After purchase you'll receive repo access within 24 hours. Run `./nex_install.sh` and she's alive.

**[→ Landing Page](https://kron777.github.io/Nex_v4.0/)**

---

## Author

**kron777** — zenlightbulb@gmail.com

---

*She learns. She reflects. She grows.*
