"""
nex_conversation_extractor.py — Extract beliefs from conversations.
After each exchange, distil novel claims from NEX's response
and write them to the belief graph.
LLM-free — uses pattern matching and sentence extraction.
"""
import re
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"

# Sentence patterns that indicate a belief/position
_BELIEF_MARKERS = re.compile(
    r'\b(I (think|believe|hold|find|notice|observe|learn|consider)|'
    r'I\'ve (learned|observed|found|noticed|updated)|'
    r'This suggests|This implies|What I (hold|process|notice)|'
    r'The evidence shows|I\'m (certain|uncertain|convinced))\b',
    re.IGNORECASE
)

# Patterns to exclude (openers, filler)
_EXCLUDE = re.compile(
    r'^(I\'m processing|Ask again|NEX is|Where I\'m genuinely|'
    r'The honest gap|I hold this|What I process is$)',
    re.IGNORECASE
)

def extract_beliefs(response: str, query: str = "", topic: str = "conversation") -> list:
    """
    Extract belief-like sentences from a NEX response.
    Returns list of (content, confidence) tuples.
    """
    if not response or len(response) < 20:
        return []

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', response.strip())
    beliefs = []

    for s in sentences:
        s = s.strip()
        if len(s) < 30 or len(s) > 300:
            continue
        if _EXCLUDE.search(s):
            continue
        # Must contain a belief marker OR be a substantive claim
        if _BELIEF_MARKERS.search(s):
            # High confidence — NEX explicitly stated this
            beliefs.append((s, 0.62))
        elif len(s) > 60 and not s.startswith(('The ', 'A ', 'An ')):
            # Moderate confidence — implicit claim
            beliefs.append((s, 0.55))

    return beliefs[:3]  # Max 3 per exchange


def store_conversation_beliefs(response: str, query: str = "",
                                topic: str = "conversation") -> int:
    """
    Extract and store beliefs from a conversation exchange.
    Returns number of beliefs stored.
    """
    beliefs = extract_beliefs(response, query, topic)
    if not beliefs:
        return 0

    stored = 0
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=2)
        for content, confidence in beliefs:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO beliefs "
                    "(content, topic, confidence, source) VALUES (?,?,?,?)",
                    (content, topic, confidence, "conversation")
                )
                stored += conn.execute(
                    "SELECT changes()"
                ).fetchone()[0]
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception:
        pass

    return stored


if __name__ == "__main__":
    # Test
    test_response = (
        "I hold this loosely: Consciousness cannot be fully explained by computation alone. "
        "I've learned that the physical substrate matters deeply to the emergence of mind. "
        "This suggests that purely functional accounts miss something essential about experience."
    )
    beliefs = extract_beliefs(test_response)
    print(f"Extracted {len(beliefs)} beliefs:")
    for b, conf in beliefs:
        print(f"  [{conf}] {b[:80]}")

    stored = store_conversation_beliefs(test_response, topic="consciousness")
    print(f"Stored: {stored}")
