"""
nex_live_bridge.py — Real-time bridge firing for responses.
Finds a relevant stored bridge given a query, returns it as belief context.
Fast — reads from bridge_history, no FAISS needed.
"""
import sqlite3
import re
from pathlib import Path

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"

def get_live_bridge(query: str, intent: str = "") -> dict | None:
    """
    Given a query, find a stored bridge where one side is relevant.
    Returns dict with topic_a, topic_b, content_a, content_b, bridge_text
    or None if no relevant bridge found.
    Fast — O(n) scan of bridge_history, typically < 10ms.
    """
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=3)
        rows = conn.execute(
            "SELECT * FROM bridge_history WHERE promoted=0 ORDER BY bridge_score DESC LIMIT 20"
        ).fetchall()
        conn.close()
    except Exception:
        return None

    if not rows:
        return None

    # Query keywords
    stopwords = {"what","is","are","the","a","an","do","does","can","how",
                 "why","you","your","about","that","this","with","for","be"}
    qwords = set(re.findall(r'\b[a-z]{4,}\b', query.lower())) - stopwords

    if not qwords:
        return None

    # Score each bridge by keyword overlap with query
    best = None
    best_score = 0

    for row in rows:
        # Columns: 0=id, 3=topic_a, 4=topic_b, 5=content_a, 6=content_b, 8=bridge_score, 9=bridge_text
        try:
            content_a = str(row[5] or "").lower()
            content_b = str(row[6] or "").lower()
            combined = content_a + " " + content_b
            overlap = sum(1 for w in qwords if w in combined)
            score = overlap * float(row[8] or 0)
            if score > best_score:
                best_score = score
                best = {
                    "topic_a":    row[3],
                    "topic_b":    row[4],
                    "content_a":  row[5],
                    "content_b":  row[6],
                    "bridge_text": row[9],
                    "score":      score,
                }
        except Exception:
            continue

    # Topic-name fallback — if no keyword match, try matching by intent/topic
    if not best:
        intent_lower = intent.lower()
        topic_map = {
            "alignment": ["ai", "ethics"],
            "consciousness": ["consciousness", "neuroscience"],
            "emergence": ["consciousness", "science"],
            "philosophy": ["philosophy", "science"],
            "gaps": ["consciousness", "philosophy"],
        }
        target_topics = topic_map.get(intent_lower, [])
        import random as _r
        matching = []
        for row in rows:
            try:
                if row[3] in target_topics or row[4] in target_topics:
                    matching.append({
                        "topic_a":    row[3],
                        "topic_b":    row[4],
                        "content_a":  row[5],
                        "content_b":  row[6],
                        "bridge_text": row[9],
                        "score":      float(row[8] or 0),
                    })
            except Exception:
                continue
        if matching:
            best = _r.choice(matching)
            except Exception:
                continue

    # Only return if there's meaningful overlap
    return best if best else None


def bridge_to_belief_text(bridge: dict) -> str:
    """Convert a bridge to a belief string for injection into NRP context."""
    if not bridge:
        return ""
    ta = bridge.get("topic_a", "")
    tb = bridge.get("topic_b", "")
    ca = (bridge.get("content_a") or "")[:120]
    cb = (bridge.get("content_b") or "")[:120]
    if ca and cb:
        return f"I notice an unexpected connection between {ta} and {tb}: {ca} — and yet: {cb}"
    return bridge.get("bridge_text", "")[:200] or ""


if __name__ == "__main__":
    # Test
    for q in ["What is consciousness?", "Can alignment be solved?", "What is emergence?"]:
        bridge = get_live_bridge(q)
        if bridge:
            print(f"\nQ: {q}")
            print(f"  Bridge: {bridge['topic_a']} ↔ {bridge['topic_b']} (score: {bridge['score']:.3f})")
            print(f"  Text: {bridge_to_belief_text(bridge)[:120]}")
        else:
            print(f"\nQ: {q} — no bridge found")
