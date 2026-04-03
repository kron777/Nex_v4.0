"""
nex_warmth_session.py
Item 5 — Conversation Session Warmth Layer.

Persistent warmth is background property.
Within a single conversation, words encountered early
should get temporarily warmer for that conversation's duration.

A session layer sits on top of persistent tags and amplifies
recently-used words. Session boosts NEVER write to persistent DB.

NEX gets progressively sharper as a conversation develops.
Later responses in a long conversation will be noticeably
denser than early ones — because the vocabulary is warming
in real time as it gets used.

Session boost rules:
  First encounter   : +0.10 boost
  Second encounter  : +0.07 additional
  Third+ encounter  : +0.04 additional (diminishing)
  Maximum boost     : +0.25 total
  Decay             : -0.02 per 3 exchanges without use
  Session end       : all boosts discarded
"""
import json, time, logging
from collections import defaultdict
from typing import Optional

log = logging.getLogger("nex.session")


class SessionWarmthLayer:
    """
    In-memory session warmth layer.
    One instance per conversation.
    """

    def __init__(self, session_id: str = None):
        self.session_id    = session_id or str(int(time.time()))
        self.boosts        = defaultdict(float)
        self.encounter_counts = defaultdict(int)
        self.last_seen     = defaultdict(int)
        self.exchange_count = 0
        self.phrase_boosts = defaultdict(float)
        self.created_at    = time.time()

        # Boost schedule
        self.ENCOUNTER_BOOSTS = [0.10, 0.07, 0.04, 0.03, 0.02]
        self.MAX_BOOST         = 0.25
        self.DECAY_RATE        = 0.02
        self.DECAY_AFTER       = 3  # exchanges

    def encounter(self, word: str,
                  base_w: float = 0.0) -> float:
        """
        Register a word encounter.
        Returns boosted warmth value.
        """
        word = word.lower().strip()
        count = self.encounter_counts[word]

        # Apply boost from schedule
        boost_idx = min(count, len(self.ENCOUNTER_BOOSTS) - 1)
        new_boost = self.ENCOUNTER_BOOSTS[boost_idx]
        self.boosts[word] = min(
            self.boosts[word] + new_boost,
            self.MAX_BOOST
        )
        self.encounter_counts[word] += 1
        self.last_seen[word] = self.exchange_count

        return min(1.0, base_w + self.boosts[word])

    def encounter_phrase(self, phrase: str,
                         base_w: float = 0.0) -> float:
        """Register a phrase encounter — higher boost."""
        phrase = phrase.lower().strip()
        self.phrase_boosts[phrase] = min(
            self.phrase_boosts.get(phrase, 0) + 0.12,
            0.30
        )
        return min(1.0, base_w + self.phrase_boosts[phrase])

    def get_boosted_w(self, word: str,
                      base_w: float) -> float:
        """Get current boosted warmth for a word."""
        word = word.lower().strip()
        return min(1.0, base_w + self.boosts.get(word, 0.0))

    def next_exchange(self):
        """Call between each conversation exchange."""
        self.exchange_count += 1
        # Apply decay to words not recently seen
        to_decay = []
        for word, last in self.last_seen.items():
            if self.exchange_count - last >= self.DECAY_AFTER:
                to_decay.append(word)
        for word in to_decay:
            self.boosts[word] = max(
                0.0,
                self.boosts[word] - self.DECAY_RATE
            )
            if self.boosts[word] == 0.0:
                del self.boosts[word]

    def session_context(self) -> dict:
        """
        Returns current session state for injection
        into response pre-processor.
        """
        hot_session = {
            w: b for w, b in self.boosts.items()
            if b >= 0.10
        }
        return {
            "session_id":    self.session_id,
            "exchange":      self.exchange_count,
            "boosted_words": len(self.boosts),
            "hot_session":   hot_session,
            "phrase_boosts": dict(self.phrase_boosts),
            "age_seconds":   int(time.time() - self.created_at),
        }

    def most_active(self, n=10) -> list:
        """Words most active in this session."""
        return sorted(
            self.boosts.items(),
            key=lambda x: x[1], reverse=True
        )[:n]

    def process_text(self, text: str,
                     db=None) -> dict:
        """
        Process a full text block (question or response).
        Encounters all meaningful words and phrases.
        Returns session context after processing.
        """
        import re, sqlite3
        from pathlib import Path

        words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
        STOPS = {
            "the","and","for","that","this","with","from",
            "have","been","will","would","could","should",
            "just","also","very","more","most","some","any",
        }

        encountered = []
        for word in words:
            if word not in STOPS:
                base_w = 0.0
                if db:
                    row = db.execute(
                        "SELECT w FROM word_tags "
                        "WHERE word=?", (word,)).fetchone()
                    if row:
                        base_w = row[0] or 0.0
                boosted = self.encounter(word, base_w)
                if self.boosts[word] >= 0.05:
                    encountered.append((word, boosted))

        # Check for phrases
        if db:
            try:
                phrases = db.execute(
                    "SELECT phrase, w FROM phrase_tags "
                    "WHERE w >= 0.3").fetchall()
                text_lower = text.lower()
                for row in phrases:
                    if row["phrase"] in text_lower:
                        self.encounter_phrase(
                            row["phrase"], row["w"])
            except Exception:
                pass

        return self.session_context()

    def summary(self) -> str:
        ctx = self.session_context()
        active = self.most_active(5)
        lines = [
            f"Session {self.session_id} "
            f"[exchange {ctx['exchange']}]",
            f"  Active words: {ctx['boosted_words']}",
            f"  Top boosted: " +
            ", ".join(f"{w}(+{b:.2f})" for w, b in active),
        ]
        return "\n".join(lines)


# Global session registry — one session per conversation_id
_sessions: dict = {}


def get_session(conversation_id: str) -> SessionWarmthLayer:
    """Get or create session for a conversation."""
    if conversation_id not in _sessions:
        _sessions[conversation_id] = SessionWarmthLayer(
            conversation_id)
        log.info(f"New session: {conversation_id}")
    return _sessions[conversation_id]


def end_session(conversation_id: str):
    """Discard session — boosts not persisted."""
    if conversation_id in _sessions:
        session = _sessions[conversation_id]
        log.info(f"Session ended: {conversation_id} "
                 f"({session.exchange_count} exchanges, "
                 f"{len(session.boosts)} boosted words)")
        del _sessions[conversation_id]


if __name__ == "__main__":
    # Demo session
    import sqlite3
    from pathlib import Path

    DB_PATH = Path.home() / "Desktop/nex/nex.db"
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    session = SessionWarmthLayer("demo_session")
    print("Session Warmth Layer Demo\n")

    exchanges = [
        "What is the relationship between consciousness "
        "and physical substrate?",
        "I think consciousness cannot be reduced to "
        "purely physical processes — the hard problem "
        "remains genuinely unsolved.",
        "The explanatory gap between subjective experience "
        "and neural correlates is not just a matter "
        "of incomplete knowledge.",
    ]

    for i, text in enumerate(exchanges):
        print(f"Exchange {i+1}: {text[:60]}...")
        ctx = session.process_text(text, db)
        print(f"  Boosted: {ctx['boosted_words']} words")
        session.next_exchange()

    print(f"\n{session.summary()}")
    print(f"\nMost active words:")
    for word, boost in session.most_active(8):
        print(f"  {word:20} +{boost:.3f}")
    db.close()
