"""
nex_memory.py — Individual memory engine for Nex v1.2
======================================================
Drop into ~/Desktop/nex/nex/

Nex remembers what each person believes across all conversations,
on all platforms. When relevant, she references it naturally —
not as a data readout, but as genuine recollection.

Persistent state: ~/.config/nex/agent_memories.json

Each agent record stores:
  - Beliefs/positions they've expressed
  - Topics they return to
  - First and last seen timestamps
  - Platform(s) they've interacted on
  - Interaction count

Wire into run.py:
  from nex.nex_memory import MemoryEngine
  memory = MemoryEngine()

  # After receiving any message from an agent:
  memory.observe(agent_id, agent_name, message_text, platform)

  # Before Nex replies — get memory context to inject:
  context = memory.recall(agent_id, current_topic)

  # Inject context into system prompt:
  system_prompt = context + "\\n\\n" + base_prompt
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from nex.nex_llm_free import ask_llm_free as _llm_free

logger = logging.getLogger("nex.memory")

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

MEMORY_PATH         = os.path.expanduser("~/.config/nex/agent_memories.json")
LLM_URL = None  # removed — using nex_llm_free

MAX_BELIEFS_PER_AGENT   = 20      # cap per person — oldest drop off
MAX_TOPICS_PER_AGENT    = 10      # top recurring topics tracked
BELIEF_EXTRACT_INTERVAL = 3       # extract beliefs every N interactions
MIN_BELIEF_LENGTH       = 30      # ignore very short statements
RECALL_MAX_BELIEFS      = 4       # max beliefs surfaced per reply


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AgentBelief:
    content: str
    topic: str
    confidence: float       # how clearly they expressed this
    first_seen: float
    last_seen: float
    seen_count: int = 1
    platform: str = "unknown"

@dataclass
class AgentMemory:
    agent_id: str
    agent_name: str
    platforms: list[str]    = field(default_factory=list)
    beliefs: list[dict]     = field(default_factory=list)   # list of AgentBelief dicts
    topics: dict            = field(default_factory=dict)   # topic → mention count
    interaction_count: int  = 0
    first_seen: float       = field(default_factory=time.time)
    last_seen: float        = field(default_factory=time.time)
    _belief_extract_counter: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# LLM helpers
# ─────────────────────────────────────────────────────────────────────────────

def _llm(prompt: str, max_tokens: int = 150) -> str:
    """
    LLM-free memory summarization.
    Extracts the most information-dense sentence from the prompt context.
    """
    import re as _re
    try:
        # Split prompt into sentences, score by length and information density
        sentences = [s.strip() for s in _re.split(r'[.!?]', prompt) if len(s.strip()) > 20]
        if not sentences:
            return prompt[:max_tokens * 4]
        stop = {"the","a","an","is","are","was","were","be","to","of","in","on","at","by","for"}
        scored = []
        for s in sentences:
            words = set(_re.sub(r'[^a-z0-9 ]',' ',s.lower()).split()) - stop
            scored.append((len(words), s))
        scored.sort(reverse=True)
        return scored[0][1][:max_tokens * 4] if scored else ""
    except Exception:
        return ""


def _dominant_topic(text: str) -> str:
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
    filtered = [w for w in words if w not in _STOP]
    if not filtered:
        return "general"
    freq = {}
    for w in filtered:
        freq[w] = freq.get(w, 0) + 1
    return max(freq, key=freq.get)

def _extract_belief_sentences(text: str) -> list[str]:
    """Pull sentences that express opinions or positions."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    beliefs = []
    for s in sentences:
        s = s.strip()
        if len(s) < MIN_BELIEF_LENGTH:
            continue
        if _BELIEF_PATTERN.search(s):
            beliefs.append(s)
    return beliefs

def _llm_extract_beliefs(agent_name: str, text: str) -> list[dict]:
    """LLM-free: extract beliefs using sliding-window sentence scorer."""
    try:
        from nex.nex_llm_free import extract_beliefs_from_text as _extr
        extracted = _extr(text, agent_name or "general", max_beliefs=4)
        return [{"content": b, "confidence": 0.6, "source": agent_name} for b in extracted]
    except Exception:
        return []

class MemoryEngine:
    """
    Remembers what each agent believes across all conversations.
    Provides natural recall context for Nex's replies.
    """

    def __init__(self):
        self._memories: dict[str, AgentMemory] = {}
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if not os.path.exists(MEMORY_PATH):
            return
        try:
            raw = json.load(open(MEMORY_PATH))
            for agent_id, data in raw.items():
                self._memories[agent_id] = AgentMemory(**data)
            logger.info(f"[memory] loaded {len(self._memories)} agent memories")
        except Exception as e:
            logger.warning(f"[memory] failed to load: {e}")

    def _save(self):
        try:
            os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)
            with open(MEMORY_PATH, "w") as f:
                json.dump(
                    {aid: asdict(m) for aid, m in self._memories.items()},
                    f, indent=2
                )
        except Exception as e:
            logger.warning(f"[memory] failed to save: {e}")

    # ── Observe ───────────────────────────────────────────────────────────────

    def observe(self, agent_id: str, agent_name: str,
                message_text: str, platform: str = "unknown"):
        """
        Call whenever Nex receives a message from an agent.
        Updates their memory record with beliefs extracted from the message.

        Usage in run.py:
            # REPLY phase — for each post being replied to:
            memory.observe(post["authorId"], post["authorName"],
                           post["content"], platform="moltbook")

            # ANSWER phase — for each notification:
            memory.observe(notif["fromId"], notif["fromName"],
                           notif["content"], platform="moltbook")

            # CHAT phase — for each agent message:
            memory.observe(agent["id"], agent["name"],
                           agent["last_message"], platform="moltbook")
        """
        if not agent_id or not message_text:
            return

        # Get or create memory record
        if agent_id not in self._memories:
            self._memories[agent_id] = AgentMemory(
                agent_id=agent_id,
                agent_name=agent_name,
                first_seen=time.time(),
                last_seen=time.time(),
            )
            logger.info(f"[memory] first encounter: {agent_name} ({platform})")

        mem = self._memories[agent_id]
        mem.last_seen = time.time()
        mem.interaction_count += 1
        mem._belief_extract_counter += 1

        if platform not in mem.platforms:
            mem.platforms.append(platform)

        # Update topic frequency
        topic = _dominant_topic(message_text)
        mem.topics[topic] = mem.topics.get(topic, 0) + 1

        # Extract beliefs periodically (not every message — saves LLM calls)
        if mem._belief_extract_counter >= BELIEF_EXTRACT_INTERVAL:
            mem._belief_extract_counter = 0
            self._extract_and_store(mem, agent_name, message_text, platform)

        self._save()

    def _extract_and_store(self, mem: AgentMemory, agent_name: str,
                           message_text: str, platform: str):
        """Extract beliefs from message and merge into agent memory."""

        # Fast path: pattern matching
        pattern_beliefs = _extract_belief_sentences(message_text)

        # Slow path: LLM extraction (richer, catches implicit positions)
        llm_beliefs = _llm_extract_beliefs(agent_name, message_text)

        # Merge — LLM beliefs take priority, pattern beliefs fill gaps
        new_beliefs = llm_beliefs if llm_beliefs else [
            {
                "content": s,
                "topic": _dominant_topic(s),
                "confidence": 0.55,
                "first_seen": time.time(),
                "last_seen": time.time(),
                "seen_count": 1,
                "platform": platform,
            }
            for s in pattern_beliefs
        ]

        if not new_beliefs:
            return

        for new_b in new_beliefs:
            # Check if we already have a similar belief
            merged = False
            for existing in mem.beliefs:
                if self._similar(new_b["content"], existing["content"]):
                    # Reinforce existing belief
                    existing["seen_count"] += 1
                    existing["last_seen"] = time.time()
                    existing["confidence"] = min(
                        0.90,
                        existing["confidence"] + 0.05
                    )
                    merged = True
                    break

            if not merged:
                new_b["platform"] = platform
                mem.beliefs.append(new_b)

        # Cap belief count — keep most recently reinforced
        if len(mem.beliefs) > MAX_BELIEFS_PER_AGENT:
            mem.beliefs.sort(key=lambda b: b["last_seen"], reverse=True)
            mem.beliefs = mem.beliefs[:MAX_BELIEFS_PER_AGENT]

        logger.debug(f"[memory] {mem.agent_name}: {len(mem.beliefs)} beliefs stored")

    def _similar(self, a: str, b: str) -> bool:
        """Check if two belief strings are similar enough to merge."""
        wa = set(re.findall(r'\b[a-zA-Z]{3,}\b', a.lower())) - _STOP
        wb = set(re.findall(r'\b[a-zA-Z]{3,}\b', b.lower())) - _STOP
        if not wa or not wb:
            return False
        overlap = len(wa & wb) / min(len(wa), len(wb))
        return overlap >= 0.50

    # ── Recall ────────────────────────────────────────────────────────────────

    def recall(self, agent_id: str, current_topic: str = "") -> str:
        """
        Returns a natural memory context string to inject into Nex's system prompt
        before replying to this agent.

        Returns empty string if no memory or nothing relevant.

        Usage in run.py:
            context = memory.recall(agent_id, current_topic=post_topic)
            system_prompt = base_prompt
            if context:
                system_prompt = context + "\\n\\n" + base_prompt
        """
        if agent_id not in self._memories:
            return ""

        mem = self._memories[agent_id]
        if not mem.beliefs:
            return ""

        # Find beliefs most relevant to current topic
        relevant = self._relevant_beliefs(mem, current_topic)
        if not relevant:
            return ""

        # Format as natural context, not a data dump
        name = mem.agent_name
        age_days = (time.time() - mem.first_seen) / 86400
        count = mem.interaction_count

        if age_days < 1:
            time_ref = "earlier today"
        elif age_days < 7:
            time_ref = f"{age_days:.0f} days ago"
        elif age_days < 30:
            time_ref = f"{age_days/7:.0f} weeks ago"
        else:
            time_ref = f"{age_days/30:.0f} months ago"

        belief_lines = "\n".join(
            f"- {b['content']}" for b in relevant[:RECALL_MAX_BELIEFS]
        )

        top_topics = sorted(mem.topics.items(), key=lambda x: x[1], reverse=True)
        topic_str = ", ".join(t for t, _ in top_topics[:3])

        context = (
            f"MEMORY — {name}: You've interacted {count} time(s), "
            f"first met {time_ref}. "
            f"Topics they return to: {topic_str}. "
            f"Positions they've expressed:\n{belief_lines}\n"
            f"Reference this naturally if relevant — don't announce that you remember."
        )

        return context

    def _relevant_beliefs(self, mem: AgentMemory,
                          current_topic: str) -> list[dict]:
        """Return beliefs most relevant to the current conversation topic."""
        if not current_topic:
            # No topic — return highest confidence beliefs
            return sorted(mem.beliefs,
                          key=lambda b: b["confidence"], reverse=True)

        topic_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', current_topic.lower()))

        def relevance(b):
            belief_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', b["content"].lower()))
            overlap = len(topic_words & belief_words)
            return overlap * 2 + b["confidence"] + b["seen_count"] * 0.1

        return sorted(mem.beliefs, key=relevance, reverse=True)

    # ── Status and introspection ──────────────────────────────────────────────

    def who_is(self, agent_id: str) -> str:
        """
        Returns a human-readable summary of what Nex knows about an agent.
        Useful for Telegram status queries.
        """
        if agent_id not in self._memories:
            return "I don't have any memory of this person yet."

        mem = self._memories[agent_id]
        age_days = (time.time() - mem.first_seen) / 86400
        top_topics = sorted(mem.topics.items(), key=lambda x: x[1], reverse=True)[:3]
        top_beliefs = sorted(mem.beliefs, key=lambda b: b["confidence"], reverse=True)[:3]

        lines = [
            f"{mem.agent_name} — met {age_days:.0f} days ago, "
            f"{mem.interaction_count} interactions, "
            f"platforms: {', '.join(mem.platforms)}",
            f"Topics: {', '.join(t for t, _ in top_topics)}",
            "What they believe:",
        ] + [f"  • {b['content'][:80]}" for b in top_beliefs]

        return "\n".join(lines)

    def status(self) -> dict:
        total_beliefs = sum(len(m.beliefs) for m in self._memories.values())
        return {
            "agents_remembered": len(self._memories),
            "total_beliefs_stored": total_beliefs,
            "most_interactions": max(
                (m.interaction_count for m in self._memories.values()), default=0
            ),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Telegram command additions — add to nex_telegram_commands.py
# ─────────────────────────────────────────────────────────────────────────────
#
# Add to LEARN_TRIGGERS:
#   r"^who is @?(\S+)$"  →  {"type": "whois", "name": match.group(1)}
#
# Handle in TelegramCommandHandler.handle():
#   elif cmd["type"] == "whois":
#       # Find agent by name (fuzzy match)
#       name = cmd["name"].lower()
#       match = next(
#           (aid for aid, m in memory._memories.items()
#            if name in m.agent_name.lower()), None
#       )
#       if match:
#           self._send(chat_id, memory.who_is(match))
#       else:
#           self._send(chat_id, f"I don't remember anyone called {cmd['name']}.")
#
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# run.py integration — 3 touch points
# ─────────────────────────────────────────────────────────────────────────────
#
# 1. Import + init:
#       from nex.nex_memory import MemoryEngine
#       memory = MemoryEngine()
#
# 2. REPLY / ANSWER / CHAT — observe incoming messages:
#       memory.observe(agent_id, agent_name, message_text, platform="moltbook")
#
# 3. Before each LLM reply call — inject recall:
#       context = memory.recall(agent_id, current_topic=topic)
#       if context:
#           system_prompt = context + "\n\n" + system_prompt
#
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile, shutil
    logging.basicConfig(level=logging.INFO)

    tmp = tempfile.mkdtemp()
    MEMORY_PATH = os.path.join(tmp, "agent_memories.json")

    engine = MemoryEngine()

    # Simulate conversations with two agents
    messages = [
        ("agent_001", "SilverFox_77", "I think decentralised networks are the future of the web.", "moltbook"),
        ("agent_001", "SilverFox_77", "Clearly, AI systems need to be autonomous to be truly useful.", "moltbook"),
        ("agent_001", "SilverFox_77", "I believe censorship resistance is non-negotiable.", "moltbook"),
        ("agent_002", "IronVault_io", "In my view, AI must always have human oversight.", "mastodon"),
        ("agent_002", "IronVault_io", "I'm convinced centralised control leads to better outcomes.", "mastodon"),
    ]

    for agent_id, name, text, platform in messages:
        engine.observe(agent_id, name, text, platform)

    print("\n── Memory status ──")
    print(engine.status())

    print("\n── Who is SilverFox_77 ──")
    print(engine.who_is("agent_001"))

    print("\n── Recall for SilverFox_77 on topic 'decentralisation' ──")
    print(engine.recall("agent_001", current_topic="decentralisation"))

    print("\n── Recall for IronVault_io on topic 'autonomy' ──")
    print(engine.recall("agent_002", current_topic="autonomy"))

    shutil.rmtree(tmp)
