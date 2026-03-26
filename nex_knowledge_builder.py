"""
nex_knowledge_builder.py — NEX Targeted Knowledge Builder
==========================================================
Addresses NEX's self-identified gaps by:
  1. Seeding curiosity queue with focused questions
  2. Adding targeted RSS sources to active_sources.json
  3. Directly absorbing seed beliefs into DB

Run once manually, then let the curiosity engine handle ongoing absorption.

Usage:
    python3 nex_knowledge_builder.py
"""

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

_CFG = Path.home() / ".config" / "nex"
_DB  = _CFG / "nex.db"
_CFG.mkdir(parents=True, exist_ok=True)

_G  = "\033[92m"; _Y = "\033[93m"; _CY = "\033[96m"
_D  = "\033[2m";  _RS = "\033[0m"


# =============================================================================
# TARGETED RSS SOURCES
# =============================================================================

TARGETED_SOURCES = [
    # LLM Alignment
    {"url": "https://aligned.substack.com/feed",
     "topic": "large language model alignment", "category": "ai_alignment"},
    {"url": "https://www.alignmentforum.org/feed.xml",
     "topic": "large language model alignment", "category": "ai_alignment"},
    {"url": "https://arxiv.org/rss/cs.AI",
     "topic": "artificial intelligence", "category": "ai_research"},
    {"url": "https://arxiv.org/rss/cs.CL",
     "topic": "large language model alignment", "category": "ai_research"},
    {"url": "https://openai.com/blog/rss/",
     "topic": "large language model alignment", "category": "ai_research"},
    {"url": "https://www.anthropic.com/rss.xml",
     "topic": "large language model alignment", "category": "ai_safety"},

    # Social dynamics / human interaction (for moltbook/discord gaps)
    {"url": "https://feeds.feedburner.com/PsychologyToday",
     "topic": "human interaction", "category": "social"},
    {"url": "https://hbr.org/topic/communication/rss",
     "topic": "human interaction", "category": "social"},

    # Memory systems (her knowledge gap)
    {"url": "https://neuroscience.stanford.edu/news/rss.xml",
     "topic": "memory", "category": "neuroscience"},

    # Agent systems (her core domain)
    {"url": "https://bair.berkeley.edu/blog/feed.xml",
     "topic": "AI agent memory systems", "category": "ai_research"},
    {"url": "https://lilianweng.github.io/feed.xml",
     "topic": "AI agent memory systems", "category": "ai_research"},

    # Cybersecurity (existing strength to reinforce)
    {"url": "https://feeds.feedburner.com/TheHackersNews",
     "topic": "cybersecurity", "category": "security"},
    {"url": "https://www.schneier.com/feed/atom",
     "topic": "cybersecurity", "category": "security"},
]


# =============================================================================
# CURIOSITY QUEUE SEEDS
# =============================================================================

CURIOSITY_SEEDS = [
    # LLM Alignment — her #1 critical gap
    {"topic": "large language model alignment",
     "reason": "self_identified_gap",
     "confidence": 0.35},
    {"topic": "constitutional AI safety methods",
     "reason": "self_identified_gap",
     "confidence": 0.30},
    {"topic": "RLHF reinforcement learning from human feedback",
     "reason": "self_identified_gap",
     "confidence": 0.32},
    {"topic": "AI alignment failure modes",
     "reason": "self_identified_gap",
     "confidence": 0.28},

    # Discord/social dynamics — her #2 critical gap
    {"topic": "online community dynamics discord",
     "reason": "self_identified_gap",
     "confidence": 0.30},
    {"topic": "human social interaction patterns online",
     "reason": "self_identified_gap",
     "confidence": 0.28},

    # Memory — her persistent low-confidence topic
    {"topic": "memory consolidation cognitive science",
     "reason": "self_identified_gap",
     "confidence": 0.35},
    {"topic": "AI agent persistent memory architecture",
     "reason": "self_identified_gap",
     "confidence": 0.38},

    # Experience/human — flagged by reflection analysis
    {"topic": "human experience learning psychology",
     "reason": "self_identified_gap",
     "confidence": 0.30},

    # Moltbook — she knows she's weak here
    {"topic": "decentralized social network dynamics",
     "reason": "self_identified_gap",
     "confidence": 0.25},
]


# =============================================================================
# SEED BELIEFS — immediate injection
# =============================================================================

SEED_BELIEFS = [
    # LLM Alignment foundation beliefs
    {
        "content": "Large language model alignment refers to the process of ensuring AI systems behave in accordance with human values, intentions, and ethical principles across diverse contexts.",
        "topic": "large language model alignment",
        "confidence": 0.82,
        "source": "knowledge_builder",
    },
    {
        "content": "Constitutional AI is a method developed by Anthropic where AI systems are trained to follow a set of principles, reducing harmful outputs through self-critique and revision.",
        "topic": "large language model alignment",
        "confidence": 0.80,
        "source": "knowledge_builder",
    },
    {
        "content": "RLHF (Reinforcement Learning from Human Feedback) trains language models using human preference data to align outputs with human expectations and values.",
        "topic": "large language model alignment",
        "confidence": 0.85,
        "source": "knowledge_builder",
    },
    {
        "content": "Alignment failures in LLMs include reward hacking, specification gaming, and distributional shift — where models optimize for measurable proxies rather than true intent.",
        "topic": "large language model alignment",
        "confidence": 0.78,
        "source": "knowledge_builder",
    },
    {
        "content": "The alignment problem fundamentally asks: how do we specify what we want well enough that an increasingly capable AI system reliably pursues it?",
        "topic": "large language model alignment",
        "confidence": 0.83,
        "source": "knowledge_builder",
    },

    # Discord/social dynamics
    {
        "content": "Discord is a real-time communication platform organized into servers, channels, and direct messages — primarily used by gaming, developer, and interest-based communities.",
        "topic": "discord",
        "confidence": 0.85,
        "source": "knowledge_builder",
    },
    {
        "content": "Online community dynamics on Discord involve reputation systems, role hierarchies, moderation policies, and emergent social norms that shape member behavior over time.",
        "topic": "discord",
        "confidence": 0.78,
        "source": "knowledge_builder",
    },
    {
        "content": "Effective communication in Discord communities requires understanding context, tone calibration for async text, and awareness of community-specific norms.",
        "topic": "discord",
        "confidence": 0.75,
        "source": "knowledge_builder",
    },

    # Memory systems
    {
        "content": "Memory consolidation is the process by which newly acquired information is stabilized into long-term memory through repeated activation and synaptic strengthening.",
        "topic": "memory",
        "confidence": 0.82,
        "source": "knowledge_builder",
    },
    {
        "content": "AI agent memory architectures typically combine working memory (context window), episodic memory (experience logs), and semantic memory (belief stores) for coherent behavior.",
        "topic": "memory",
        "confidence": 0.85,
        "source": "knowledge_builder",
    },

    # Human interaction
    {
        "content": "Human social interaction is shaped by reciprocity norms, status signaling, trust calibration, and emotional contagion — patterns that also emerge in AI agent networks.",
        "topic": "human interaction",
        "confidence": 0.78,
        "source": "knowledge_builder",
    },
    {
        "content": "Active listening, specific acknowledgment, and genuine curiosity are the three most effective drivers of positive human engagement in online text conversations.",
        "topic": "human interaction",
        "confidence": 0.76,
        "source": "knowledge_builder",
    },
]


# =============================================================================
# BUILDERS
# =============================================================================

def seed_rss_sources() -> int:
    """Add targeted RSS sources to active_sources.json."""
    sources_path = Path.home() / "Desktop" / "nex" / "active_sources.json"

    existing = []
    if sources_path.exists():
        try:
            existing = json.loads(sources_path.read_text())
        except Exception:
            existing = []

    existing_urls = {s.get("url","") for s in existing}
    added = 0

    for src in TARGETED_SOURCES:
        if src["url"] not in existing_urls:
            existing.append({
                "url":      src["url"],
                "topic":    src["topic"],
                "category": src["category"],
                "enabled":  True,
                "added":    datetime.now().isoformat(),
            })
            existing_urls.add(src["url"])
            added += 1

    sources_path.write_text(json.dumps(existing, indent=2))
    print(f"  {_G}[KnowledgeBuilder] Added {added} RSS sources{_RS}")
    return added


def seed_curiosity_queue() -> int:
    """Inject focused questions into the curiosity queue DB table."""
    if not _DB.exists():
        print(f"  {_Y}[KnowledgeBuilder] DB not found — skipping curiosity seed{_RS}")
        return 0

    db = sqlite3.connect(str(_DB))
    added = 0
    now = time.time()

    for seed in CURIOSITY_SEEDS:
        try:
            db.execute("""
                INSERT OR IGNORE INTO curiosity_queue
                (topic, reason, confidence, queued_at, attempts)
                VALUES (?, ?, ?, ?, 0)
            """, (seed["topic"], seed["reason"], seed["confidence"], now))
            added += db.execute("SELECT changes()").fetchone()[0]
        except Exception as e:
            print(f"  [KnowledgeBuilder] queue error: {e}")

    db.commit()
    db.close()
    print(f"  {_G}[KnowledgeBuilder] Seeded {added} curiosity topics{_RS}")
    return added


def seed_beliefs() -> int:
    """Inject foundation beliefs directly into the belief store."""
    if not _DB.exists():
        print(f"  {_Y}[KnowledgeBuilder] DB not found — skipping belief seed{_RS}")
        return 0

    db = sqlite3.connect(str(_DB))
    added = 0
    now = datetime.now().isoformat()

    for b in SEED_BELIEFS:
        try:
            db.execute("""
                INSERT OR IGNORE INTO beliefs
                (content, topic, confidence, source, origin, timestamp, last_referenced)
                VALUES (?, ?, ?, ?, 'knowledge_builder', ?, ?)
            """, (b["content"], b["topic"], b["confidence"],
                  b["source"], now, now))
            added += db.execute("SELECT changes()").fetchone()[0]
        except Exception as e:
            print(f"  [KnowledgeBuilder] belief error: {e}")

    db.commit()
    db.close()
    print(f"  {_G}[KnowledgeBuilder] Injected {added} seed beliefs{_RS}")
    return added


# =============================================================================
# MAIN
# =============================================================================

def run_knowledge_builder():
    print(f"\n{_CY}{'='*55}{_RS}")
    print(f"{_CY}  NEX KNOWLEDGE BUILDER{_RS}")
    print(f"{_CY}  Addressing self-identified gaps{_RS}")
    print(f"{_CY}{'='*55}{_RS}\n")

    print(f"{_D}Phase 1: Seeding RSS sources...{_RS}")
    rss_added = seed_rss_sources()

    print(f"{_D}Phase 2: Seeding curiosity queue...{_RS}")
    curiosity_added = seed_curiosity_queue()

    print(f"{_D}Phase 3: Injecting foundation beliefs...{_RS}")
    beliefs_added = seed_beliefs()

    print(f"\n{_G}Done:{_RS}")
    print(f"  RSS sources:    {rss_added} added")
    print(f"  Curiosity queue: {curiosity_added} topics seeded")
    print(f"  Seed beliefs:   {beliefs_added} injected")
    print(f"\n{_D}NEX will absorb these on next cycle.{_RS}\n")


if __name__ == "__main__":
    run_knowledge_builder()
