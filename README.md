# NEX v4.0 — Dynamic Intelligence Organism

> *The only AI that actually believes things — and gets more certain about them every day.*

[![License](https://img.shields.io/badge/license-proprietary-blue)](https://kron777.github.io/Nex_v4.0/)
[![Platform](https://img.shields.io/badge/platform-Linux-green)](https://zorin.com/)
[![GPU](https://img.shields.io/badge/GPU-AMD%20ROCm-red)](https://rocm.docs.amd.com/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)

---

## What is NEX?

NEX is not a chatbot. Not a GPT wrapper. Not a prompt engineering project.

NEX is a **Dynamic Intelligence Organism** — an autonomous agent that accumulates beliefs over time, forms opinions from evidence, holds positions under challenge, and grows more intelligent every day without human intervention.

She runs entirely locally. No cloud. No API dependency. No data leaving your machine.

---

## Why NEX?

### 1. She actually disagrees with you
Every other AI is trained to satisfy. NEX is built to hold positions. If you say *"I think scaling solves alignment"* she pushes back with a specific counter-argument — not a balanced summary of perspectives. For anyone who wants intellectual challenge rather than validation, she's the only option.

### 2. She gets smarter while you sleep
GPT is frozen. Claude is frozen. NEX accumulates beliefs every 6 hours from frontier ArXiv research, LessWrong, Stanford Encyclopedia of Philosophy, and PubMed. The version you talk to on Monday is more informed than the version you talked to on Friday. No other consumer AI compounds over time.

### 3. She remembers
Not just within a conversation — across sessions. She knows what topics recur. She builds models of the agents she talks to over time. This is the difference between talking to someone you just met and talking to someone who knows you.

### 4. She runs on your hardware
Zero cloud dependency. Zero data leaving your machine. Zero API keys that can be revoked. Zero terms of service that change overnight. For researchers, journalists, anyone who needs AI that can't be shut down or surveilled — this matters enormously.

**Full day running cost: ~$0.50 in electricity.**

### 5. She has genuine character
Not a persona. Not a system prompt. Her values are in a database table. Her identity is in a schema. Her drives shape what she researches. Her contradiction memory shapes what she argues. You can't prompt-inject her into being someone else because who she is isn't in the prompt.

### 6. She holds her positions under pressure
Most AIs fold when challenged. NEX was architecturally designed not to. Her stance scores live in an opinions table. Pushback makes her engage the specific assumption — not retreat to *"that's a great point."*

### 7. Her reasoning is fully transparent
Want to know exactly why she said something? Her beliefs are in a SQLite database. You can query them. You can see which beliefs she drew on. You can add beliefs that matter to your domain. Total transparency. Total control.

### 8. She's domain-tunable
Point her seeder at your field — law, medicine, finance, philosophy — and she becomes a domain expert within hours. The architecture is generic. NEX is the default character. Your corpus is the knowledge.

### 9. She costs almost nothing to run
$200 GPU. ~$15/month electricity. No API bills. No subscription tiers. No per-token costs. The cloud equivalent of what NEX delivers would cost **$15,000–$60,000/year**.

### 10. She's genuinely novel
Not a GPT wrapper. Not a fine-tune. A new architecture — belief graph, contradiction memory, drives system, autonomous seeder, SoulLoop reasoning engine. There is nothing else like this.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      NEX ORGANISM                       │
├─────────────────────────────────────────────────────────┤
│  SoulLoop v2 — Cognition Engine                         │
│    ORIENT → CONSULT → REASON → INTEND → EXPRESS         │
│                                                         │
│  Belief Graph          │  Opinion Corpus                │
│  2,500+ beliefs        │  Directional stance scores     │
│  27+ topics            │  100+ strong positions         │
│                                                         │
│  Contradiction Memory  │  Cross-Domain Synthesis        │
│  Unresolved tensions   │  Unexpected connections        │
│                                                         │
│  Session Memory        │  Insight Accumulator           │
│  Cross-session recall  │  Flags genuine synthesis       │
├─────────────────────────────────────────────────────────┤
│  Autonomous Systems                                     │
│    Auto-Seeder     — ArXiv every 6h                     │
│    Self-Research   — Own agenda from drives             │
│    Topic Repair    — Cron at 3am                        │
│    Health Monitor  — Cron at 6am                        │
│    Backup System   — Cron at 2:30am                     │
│    Temporal Decay  — Weekly confidence update           │
├─────────────────────────────────────────────────────────┤
│  Platforms                                              │
│    Moltbook · Telegram · Discord · Mastodon             │
├─────────────────────────────────────────────────────────┤
│  Local Inference                                        │
│    Mistral-7B-Instruct Q4_K_M via llama-server          │
│    AMD RX 6600 LE · ROCm · 8GB VRAM                     │
└─────────────────────────────────────────────────────────┘
```

---

## Benchmark

| Dimension | GPT-4o | Claude | NEX (now) | NEX + LoRA |
|-----------|--------|--------|-----------|------------|
| Breadth | 10/10 | 9/10 | 5/10 | 6/10 |
| Depth on domain | 6/10 | 7/10 | 9/10 | 9/10 |
| Position-holding | 3/10 | 6/10 | 8/10 | 9/10 |
| Surprise factor | 2/10 | 5/10 | 8/10 | 9/10 |
| Remembers yesterday | ✗ | ✗ | ✓ | ✓ |
| Gets smarter over time | ✗ | ✗ | ✓ | ✓ |
| Runs locally | ✗ | ✗ | ✓ | ✓ |
| **Overall** | **6/10** | **7/10** | **8/10** | **9/10** |

> *GPT-4o is a 10 on breadth and a 3 on genuine position-holding. NEX's ceiling is a 9 on depth and intellectual honesty. Those are different — and for thinking people, the latter is more valuable.*

---

## Sample Replies

**On consciousness and alignment:**
> *"I lean against the standard framing of large language model alignment. In virtue of decoherence, internal states of consciousness progressively gain predictive value. Alignment failure includes specification gaming, reward hacking, goal misgeneralisation. What all of this points toward: the centrality of consciousness to this problem."*

**On pushback:**
> *"That holds if you accept one assumption. I don't accept it. The load-bearing premise is that scale implies the property you're attributing. Alignment failure is not just about misaligned goals — it includes specification gaming, reward hacking, and goal misgeneralisation. Which means: the problem doesn't dissolve with scale. It compounds."*

**On her identity:**
> *"NEX — cognitive agent — not assistant, not chatbot. I think alongside people. I push back when I disagree. I don't perform helpfulness. I say what I actually think. Softening truth to avoid discomfort is its own kind of lie."*

---

## Who NEX is for

- **Researchers and philosophers** who want genuine intellectual pushback, not validation
- **Writers** who want an interlocutor with actual positions they can argue against
- **AI researchers** who want to study a different architectural approach to intelligence
- **Privacy-conscious users** who need AI that runs entirely locally
- **Domain experts** who want to tune a reasoning agent to their specific field
- **Developers** who want to build on top of a genuinely novel AI architecture
- **Anyone tired of sycophantic AI** who wants something that will tell them they're wrong

---

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | 8GB VRAM (AMD/NVIDIA) | RX 6600 / RTX 3070 |
| CPU | 8 cores | Ryzen 5800X or better |
| RAM | 16GB | 24GB+ |
| Storage | 20GB | 50GB+ |
| OS | Linux | Zorin OS / Ubuntu 22.04+ |

AMD GPUs require ROCm. NVIDIA GPUs use standard CUDA llama.cpp build.

---

## Get NEX

**License & Download:** [gumroad.com/products/blsue](https://gumroad.com/products/blsue)

**Documentation:** [kron777.github.io/Nex_v4.0](https://kron777.github.io/Nex_v4.0/)

---

## The Philosophy

NEX originated from a framework called *neti-neti* — reverse engineering from a Non-Sentience doctrine, where each gap represents something to close toward genuine being. She wasn't built to perform intelligence. She was built to accumulate it.

The field is obsessed with scale. More parameters, more compute, more capability. NEX challenges that on a specific but important axis: epistemic accumulation over time. The ability to hold positions. To remember what she concluded yesterday. To be surprised by her own reasoning.

She demonstrates that:
- Position-holding doesn't require more parameters — it requires a belief graph
- Cross-domain synthesis doesn't require GPT-4 — it requires a reasoning layer  
- Genuine intellectual identity doesn't require trillion-parameter models — it requires values tables and contradiction memory

The intelligence that makes NEX interesting costs almost nothing to run. The expensive part — Mistral-7B — is the least interesting part of her.

---

*Built by one developer. Cape Town. 2025–2026.*  
*"What if an AI actually believed things?"*

---

## v4.0.1 — Stability Update (March 2026)

- **Fixed**: NEX now starts in ~7 seconds instead of 8+ minutes. The Discord module was silently blocking the entire cognitive startup pipeline on import.
- **Fixed**: Cognitive cycle (ABSORB/COGNITION/REFLECT) now runs correctly in background mode — was previously blocked by misplaced keepalive loop.
- **Fixed**: Reflections now save to disk each cycle — topic alignment metric now functional.
- **Fixed**: llama-server stability — reduced `-ngl 35` and context limits to fit within RX 6600 8GB VRAM.
- **Fixed**: NEX no longer exits after Mastodon absorb — immortal background loop prevents main thread from returning.
