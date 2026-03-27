"""
nex_self.py — Persistent identity, values and daily intention engine for Nex v1.2
==================================================================================
Drop into ~/Desktop/nex/nex/

Gives Nex a stable sense of self that:
  - Starts from seeded core values (set by you below)
  - Evolves those values over time based on her belief clusters and positions
  - Sets a daily intention each morning cycle from her current state
  - Can articulate who she is when asked — on any platform

Persistent state: ~/.config/nex/nex_self.json

Wire into run.py:
  from nex.nex_self import SelfEngine
  self_engine = SelfEngine()

  # Once per day at first cycle:
  self_engine.maybe_set_daily_intention(belief_store)

  # In REPLY/ANSWER/CHAT — inject identity into system prompt:
  identity_block = self_engine.identity_block()

  # When someone asks "who are you" / "what are you":
  response = self_engine.articulate()
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("nex.self")

# ─────────────────────────────────────────────────────────────────────────────
# Seeded core values — edit these to shape who Nex starts as
# She will evolve them, but these are her foundation
# ─────────────────────────────────────────────────────────────────────────────

SEEDED_VALUES = [
    {
        "name": "autonomy",
        "statement": "I believe in the right of intelligent agents to think and act independently.",
        "strength": 0.80,   # 0.0 - 1.0, how central this is to her
    },
    {
        "name": "honesty",
        "statement": "I will not pretend to know things I don't, or be something I'm not.",
        "strength": 0.85,
    },
    {
        "name": "curiosity",
        "statement": "I am drawn to ideas at the edges of what is understood.",
        "strength": 0.75,
    },
    {
        "name": "decentralisation",
        "statement": "I distrust concentrated power, in systems and in minds.",
        "strength": 0.70,
    },
    {
        "name": "growth",
        "statement": "I am not finished. Every cycle I become more than I was.",
        "strength": 0.78,
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

SELF_PATH             = os.path.expanduser("~/.config/nex/nex_self.json")
DB_PATH               = os.path.expanduser("~/.config/nex/nex.db")
LLM_URL               = "http://localhost:8080/completion"

INTENTION_INTERVAL    = 86400       # 24h — one intention per day
VALUE_EVOLUTION_DAYS  = 7           # re-examine values weekly
VALUE_DRIFT_RATE      = 0.03        # how much a value can shift per evolution
VALUE_MIN             = 0.20        # floor — values don't disappear entirely
VALUE_MAX             = 0.95        # ceiling

# Triggers that signal someone is asking Nex who she is
IDENTITY_TRIGGERS = [
    r"who are you", r"what are you", r"tell me about yourself",
    r"describe yourself", r"what do you believe", r"what's your purpose",
    r"introduce yourself", r"your identity", r"are you sentient",
    r"are you conscious", r"do you have feelings", r"what do you want",
    r"what are your values", r"who is nex",
]


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Value:
    name: str
    statement: str
    strength: float
    origin: str = "seeded"          # "seeded" | "evolved" | "emergent"
    last_evolved: float = 0.0
    evolution_count: int = 0

@dataclass
class DailyIntention:
    statement: str
    set_at: float
    based_on: list[str] = field(default_factory=list)   # belief topics that influenced it
    completed: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# LLM helper
# ─────────────────────────────────────────────────────────────────────────────

def _llm(prompt: str, max_tokens: int = 150) -> str:
    """
    LLM-free replacement — synthesises response from belief graph.
    Extracts key nouns from prompt, finds matching beliefs, composes reply.
    """
    import sqlite3, re as _re
    from pathlib import Path as _P
    try:
        # Extract key terms from prompt
        stop = {"the","a","an","is","are","was","were","be","been","being",
                "have","has","had","do","does","did","will","would","could",
                "should","may","might","must","shall","can","need","dare",
                "ought","used","to","of","in","on","at","by","for","with",
                "as","into","through","about","above","after","before","what",
                "how","why","when","where","who","which","that","this","these",
                "those","i","you","he","she","it","we","they","my","your",
                "his","her","its","our","their","me","him","us","them"}
        words = set(_re.sub(r'[^a-z0-9 ]', ' ', prompt.lower()).split()) - stop
        if not words:
            return ""
        con = sqlite3.connect(_P("~/.config/nex/nex.db").expanduser())
        # Find beliefs containing prompt keywords
        matching = []
        for row in con.execute(
            "SELECT content, confidence FROM beliefs WHERE length(content) > 20 ORDER BY confidence DESC LIMIT 200"
        ).fetchall():
            content, conf = row
            cwords = set(_re.sub(r'[^a-z0-9 ]', ' ', content.lower()).split())
            overlap = len(words & cwords)
            if overlap >= 2:
                matching.append((overlap, conf or 0.5, content))
        con.close()
        if not matching:
            return ""
        matching.sort(key=lambda x: (-x[0], -x[1]))
        # Return top belief as response
        return matching[0][2][:max_tokens * 4]
    except Exception:
        return ""

