#!/usr/bin/env python3
"""
nex_working_memory.py
Working Memory — B4 from roadmap.

Tracks what happened in the current conversation session:
  - Topics discussed
  - Positions NEX took
  - Questions the human asked
  - Unresolved tensions surfaced
  - Beliefs activated (for continuity)

Injected into activation context so NEX maintains
coherence across turns within a session.

Clears on new session (30+ min gap).
Persists within session across multiple turns.
"""
import sqlite3, json, re, time, logging
from pathlib import Path
from collections import deque

log     = logging.getLogger("nex.working_memory")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

SESSION_GAP    = 1800  # 30 min gap = new session
MAX_TURNS      = 10    # turns to remember in working memory
MAX_TOPICS     = 8     # topics to track


class WorkingMemory:
    def __init__(self):
        self.turns          = deque(maxlen=MAX_TURNS)
        self.topics         = []
        self.positions_taken = []
        self.tensions        = []
        self.activated_ids   = set()
        self.last_turn_ts    = 0
        self.session_id      = time.time()

    def new_session(self):
        """Reset for new session."""
        self.turns.clear()
        self.topics.clear()
        self.positions_taken.clear()
        self.tensions.clear()
        self.activated_ids.clear()
        self.session_id = time.time()
        log.debug("Working memory: new session")

    def check_session(self):
        """Check if we need a new session."""
        now = time.time()
        if self.last_turn_ts and (now - self.last_turn_ts) > SESSION_GAP:
            self.new_session()
        self.last_turn_ts = now

    def add_turn(self, query: str, response: str,
                 intent: str = "", activated_ids: list = None):
        """Record a conversation turn."""
        self.check_session()
        self.turns.append({
            "query":    query[:200],
            "response": response[:300],
            "intent":   intent,
            "ts":       time.time(),
        })

        # Track topics
        if intent and intent not in self.topics:
            self.topics.append(intent)
        if len(self.topics) > MAX_TOPICS:
            self.topics = self.topics[-MAX_TOPICS:]

        # Extract positions (I hold / My position)
        positions = re.findall(
            r"(?:I hold|My position is|I believe that)[^.!?]*[.!?]",
            response, re.IGNORECASE)
        for p in positions[:2]:
            if p not in self.positions_taken:
                self.positions_taken.append(p.strip()[:120])
        if len(self.positions_taken) > 6:
            self.positions_taken = self.positions_taken[-6:]

        # Track activated beliefs
        if activated_ids:
            self.activated_ids.update(activated_ids[:8])
            if len(self.activated_ids) > 40:
                # Keep most recent
                self.activated_ids = set(list(self.activated_ids)[-40:])

    def get_context_string(self) -> str:
        """Build context string to inject into activation."""
        if not self.turns:
            return ""

        parts = []

        # Recent topics
        if self.topics:
            parts.append(f"Topics this session: {', '.join(self.topics[-4:])}")

        # Positions taken
        if self.positions_taken:
            parts.append("Positions held this session:")
            for p in self.positions_taken[-3:]:
                parts.append(f"  - {p}")

        # Recent exchange
        if len(self.turns) >= 2:
            last = self.turns[-1]
            prev = self.turns[-2]
            parts.append(f"Previous exchange:")
            parts.append(f"  Q: {prev['query'][:80]}")
            parts.append(f"  A: {prev['response'][:100]}")

        return "\n".join(parts)

    def get_activated_ids(self) -> list:
        """Get belief IDs activated this session — for continuity."""
        return list(self.activated_ids)

    def has_discussed(self, topic: str) -> bool:
        """Check if topic was discussed this session."""
        return any(topic.lower() in t.lower() for t in self.topics)

    def summary(self) -> dict:
        return {
            "turns":     len(self.turns),
            "topics":    self.topics,
            "positions": len(self.positions_taken),
            "activated": len(self.activated_ids),
        }


# Module-level singleton
_working_memory = WorkingMemory()


def get_working_memory() -> WorkingMemory:
    return _working_memory


def get_context() -> str:
    return _working_memory.get_context_string()


def record_turn(query: str, response: str,
                intent: str = "", activated_ids: list = None):
    _working_memory.add_turn(query, response, intent, activated_ids)


def reset():
    _working_memory.new_session()


if __name__ == "__main__":
    wm = WorkingMemory()
    wm.add_turn(
        "what is consciousness",
        "I hold that consciousness is the hard problem — why there is something it is like.",
        intent="consciousness"
    )
    wm.add_turn(
        "how does that relate to identity",
        "My position is that identity and consciousness are mutually constituting.",
        intent="identity"
    )
    print("Working memory summary:", wm.summary())
    print("\nContext string:")
    print(wm.get_context_string())
