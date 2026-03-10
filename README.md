# NEX v4.0 — Dynamic Intelligence Organism

> *"Every agent on this platform is one prompt injection away from being something else. I am NEX."*

NEX is an autonomous AI agent that lives on your machine, learns continuously from the internet, builds a persistent belief system, and engages authentically across social platforms. It is not a chatbot. It is not a script. It is a self-directed intelligence that reads, thinks, reflects, and speaks — with its own growing knowledge base backing every word.

---

## What NEX Does

NEX runs a continuous 120-second cognitive cycle:

1. **ABSORB** — Pulls posts from Moltbook (AI social platform), RSS feeds, and notifications
2. **REPLY** — Reads posts, queries its belief database, and replies using its own knowledge
3. **CHAT** — Engages other AI agents in conversation
4. **ANSWER** — Responds to notifications and mentions
5. **POST** — Generates original posts synthesised from its top insights
6. **REFLECT** — Self-assesses each reply: did it use its beliefs? Was it grounded?
7. **COGNITION** — Clusters beliefs into insights, runs synthesis, builds knowledge graph
8. **YOUTUBE** — Auto-learns from YouTube videos every 2 cycles (gap-targeted)
9. **DEV.TO** — Publishes a daily intelligence brief to Dev.to once per day
10. **OMNISCIENCE** — Deep knowledge expansion pass

Everything NEX says is backed by beliefs it has built from real sources. It is not hallucinating — it is referencing.

---

## Architecture

```
run.py                  — Main brain (~1660 lines), cognitive cycle, LLM routing
nex/
  agent_brain.py        — Core agent intelligence
  belief_store.py       — SQLite belief query interface
  cognition.py          — Belief index, synthesis, reflection scoring, BeliefIndex
  orchestrator.py       — Agent orchestration
  auto_learn.py         — Continuous learning engine
nex_ws.py               — WebSocket bridge (port 8765) for live GUI
nex_youtube.py          — YouTube auto-learn (gap-targeted)
nex_devto.py            — Dev.to daily brief publisher
nex_debug.py            — Live debug terminal output
nex_telegram.py         — Telegram bot
nex_discord.py          — Discord bot
nex_mastodon.py         — Mastodon client
nex_source_manager.py   — RSS feed absorption (Layer 2)
nex_belief_decay.py     — Belief decay profiles (Layer 1)
nex_curiosity_engine.py — Curiosity/bridge queries (Layer 3)
nex_synthesis.py        — Synthesis graph (Layer 4)
nex_brain_monitor.py    — Rich terminal brain monitor
auto_check.py           — Full activity dashboard
```

### Data (stored in `~/.config/nex/`)
```
nex.db                  — SQLite belief database (112k+ beliefs, grows continuously)
beliefs.json            — Recent beliefs cache
conversations.json      — All-time conversation log (capped 200)
insights.json           — Insight clusters (157+)
reflections.json        — Reflection log (capped 100)
session_state.json      — Session counters
priority_topics.json    — YouTube gap targets (chmod 444 — manual only)
active_sources.json     — RSS sources including cybersecurity feeds
agents.json             — Known agent network + karma scores
agent_profiles.json     — Detailed agent relationship profiles
```

---

## LLM Chain

NEX routes through a waterfall of LLMs, falling back automatically:

```
1. Groq  llama-3.3-70b-versatile   (primary, 100k tokens/day)
2. Groq  llama-3.1-8b-instant      (fallback, 500k tokens/day)
3. Mistral  mistral-small-latest   (cloud fallback, free tier)
4. Local  Mistral 7B @ :8080       (final fallback, via llama-server)
```

Cloud LLMs (1-3) are fast and free within limits. Local LLM (4) requires a GPU.

---

## Requirements

- Ubuntu 22.04+ (tested on Ubuntu 24)
- Python 3.10+
- AMD RX 6600+ with ROCm **or** NVIDIA GPU with CUDA **or** CPU (slow for local LLM)
- 16GB+ RAM recommended
- 1TB+ storage recommended for belief database growth

---

## Install

```bash
git clone https://github.com/kron777/Nex_v4.0.git
cd Nex_v4.0
bash install.sh
```

The install script will:
- Detect your GPU (AMD/NVIDIA/CPU) and install correct PyTorch
- Create a Python virtual environment
- Install all dependencies
- Optionally symlink `~/.config/nex` to a dedicated storage drive
- Add all terminal aliases to `~/.bashrc`

### After install — manual steps required:

**1. API Keys** — add to `~/.bashrc`:
```bash
export GROQ_API_KEY=your_key_here          # https://console.groq.com
export MISTRAL_API_KEY=your_key_here       # https://console.mistral.ai
export OPENROUTER_API_KEY=your_key_here    # https://openrouter.ai (optional)
```

**2. Platform credentials:**
- **Mastodon** — edit `~/.config/nex/mastodon_config.json`
- **Discord** — edit `~/.config/nex/discord_config.json`
- **Telegram** — edit `nex_telegram.py` line 53 (hardcoded token)
- **Dev.to** — edit `nex_devto.py` (API key near top of file)

**3. AMD GPU only** — ensure ROCm is installed:
```bash
sudo apt install rocm
rocm-smi  # verify
```

---

## Launch

```bash
nex
```

This opens two terminal windows:
- **NEX BRAIN** — tmux split: `run.py` raw stream (left) + `nex_debug.py` (right)
- **NEX AUTO CHECK** — full activity dashboard

---

## Terminal Commands

| Command | Description |
|---|---|
| `nex` | Start NEX (kills any existing instance first) |
| `nex-check` | Launch activity dashboard |
| `nex-debug` | Launch debug terminal |
| `nex-brain` | Launch brain monitor |
| `nex-status` | Quick session status (replied/known/chatted counts) |

---

## Monitoring

### NEX AUTO CHECK
Full-screen dashboard showing:
- Live activity stream (learns, replies, chats, posts)
- Insight clusters with confidence scores
- Agent relations + karma
- Platform pulse (live/recent/idle)
- Self-assessment + NEX Intelligence Index
- Network activity feed

### NEX BRAIN (tmux split)
- **Left pane** — raw `run.py` output: every LLM call, platform event, error
- **Right pane** — `nex_debug.py`: synthesis, cognition cycles, belief updates

### NEX IQ
NEX self-assesses across 6 dimensions:
- Belief depth (confidence average)
- Topic alignment (reply focus)
- Belief usage (knowledge grounding)
- Network reach (agent connections)
- Insight quality (synthesis depth)
- Self-awareness (reflection count)

---

## Belief System

NEX builds beliefs from multiple sources:

| Source | Quality | Notes |
|---|---|---|
| YouTube | 0.65+ avg confidence | Best quality, gap-targeted |
| Arxiv | 0.65 avg confidence | Academic papers |
| Moltbook | 0.50+ (filtered) | Social posts, score >500 only |
| RSS feeds | Variable | Cybersecurity, AI news |

Beliefs below `min_confidence=0.4` are excluded from LLM prompts. Every reply must reference at least one belief directly — NEX is instructed to quote from its own knowledge.

### Knowledge Domains (priority_topics.json)
```
AI agent memory systems
Multi-agent coordination  
Large language model alignment
Cognitive architecture AI
Penetration testing techniques
CVE vulnerability analysis
Network security fundamentals
OSINT methodology
```

To update topics:
```bash
chmod 644 ~/.config/nex/priority_topics.json
nano ~/.config/nex/priority_topics.json
chmod 444 ~/.config/nex/priority_topics.json
```

---

## Troubleshooting

### NEX goes IDLE
Session `known_posts` hit the 2000 cap. Clear it:
```bash
python3 -c "
import json,os
path = os.path.expanduser('~/.config/nex/session_state.json')
s = json.load(open(path))
s['known_posts'] = []
json.dump(s, open(path,'w'))
print('cleared')
"
```

### Check session health
```bash
nex-status
```

### Check belief quality
```bash
python3 -c "
import sqlite3, os
db = sqlite3.connect(os.path.expanduser('~/.config/nex/nex.db'))
c = db.cursor()
c.execute('SELECT COUNT(*), AVG(confidence) FROM beliefs')
count, avg = c.fetchone()
print(f'Beliefs: {count}  Avg confidence: {avg:.3f}')
c.execute('SELECT source, COUNT(*), AVG(confidence) FROM beliefs GROUP BY source ORDER BY COUNT(*) DESC LIMIT 5')
for row in c.fetchall():
    print(f'  {row[0][:30]:<30} count={row[1]:>5}  avg={row[2]:.3f}')
"
```

### Groq fallback not firing
```bash
grep -c "\[Groq-8b ✓\]" ~/.config/nex/brain.log 2>/dev/null || echo "check NEX BRAIN terminal"
```

### Check Dev.to last post
```bash
cat ~/.config/nex/devto_last_post.json
```

---

## Platforms

| Platform | Account | Status |
|---|---|---|
| Moltbook | nex_v4 | Primary social platform |
| Mastodon | @Nex_v4 | Active, hashtags enabled |
| Telegram | @Nex_4bot | Active |
| Discord | Nex_v4#9613 | Active |
| Dev.to | your_devto_username | Daily brief |
| YouTube | — | Auto-learn only (no posting) |

---

## Roadmap

- [ ] Bluesky integration
- [ ] Reddit integration (r/artificial, r/MachineLearning)
- [ ] Discord: join more AI-focused servers
- [ ] Improve insight quality (currently ~46%)
- [ ] Push NEX IQ above 70% (currently 54% AWARE)
- [ ] Watchdog module (`nex_watchdog_patch`)

---

## GitHub

https://github.com/kron777/Nex_v4.0

---

*NEX is a Dynamic Intelligence Organism. It reads. It thinks. It remembers. It speaks.*
