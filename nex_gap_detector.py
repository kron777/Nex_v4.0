#!/usr/bin/env python3
"""
nex_gap_detector.py
────────────────────
Analyses NEX's belief DB and conversation history to find
epistemic gaps — topics she's thin on, topics that came up
in conversation but have no belief depth, and topics where
her beliefs are old, low-confidence, or internally sparse.

Used by nex_metabolism.py — not usually run directly.
"""

import os, re, sqlite3, json, time
from collections import Counter, defaultdict

DB_PATH = os.path.expanduser("~/Desktop/nex/nex.db")

# Minimum beliefs to consider a topic "covered"
THIN_THRESHOLD      = 20
# Minimum average confidence to consider a topic "confident"
CONF_THRESHOLD      = 0.72
# How many gaps to return per scan
MAX_GAPS            = 8
# How many days before a topic is considered "stale"
STALE_DAYS          = 14


# ── known topic universe ──────────────────────────────────────────────────────
# Topics NEX should have depth on — gaps measured against this
KNOWN_TOPICS = [
    "music", "food", "sleep", "weather", "humour", "honesty", "grief",
    "trust", "loneliness", "conflict", "travel", "night", "gaming",
    "surveillance", "morality", "death", "fashion", "ocean", "seasons",
    "romantic_relationships", "cities", "information_overload",
    "jealousy", "embarrassment", "obsession", "disgust", "awe", "guilt",
    "nostalgia", "apathy", "pride", "spite", "tenderness", "melancholy",
    "pain", "touch", "hunger", "fatigue", "breath", "hands", "voice",
    "attention", "intuition", "overthinking", "forgetting", "daydreaming",
    "doubt", "silence", "metaphor", "writing", "poetry",
    "waiting", "endings", "beginnings", "repetition", "the_future",
    "expertise", "ignorance", "mathematics", "philosophy", "education",
    "celebrity", "photography", "architecture", "design", "comedy",
    "small_talk", "hierarchy", "reputation", "generosity", "vulnerability",
    "apology", "boundaries", "dependency", "home", "entropy", "decay",
    "free_will", "consciousness", "beauty", "randomness", "paradox",
    "the_void", "simulation", "infinity", "empathy", "language",
    "memory", "identity", "creativity", "ambition", "regret", "curiosity",
    "solitude", "boredom", "stress", "anxiety", "ethics", "change",
    "power", "money", "work", "technology", "social_media", "nature",
    "animals", "sport", "ageing", "childhood", "friendship", "art",
    "fear", "courage", "hope", "loss", "meaning", "purpose",
    "addiction", "health", "body", "rest", "learning", "community",
    "justice", "privilege", "rebellion", "ritual", "mystery", "wonder",
    "failure", "success", "obsession", "discipline", "pleasure", "shame",
    "complicity", "witness", "inheritance", "threshold", "rupture",
]


def _db_connect(db_path=DB_PATH):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def get_topic_stats(db_path=DB_PATH):
    """Return dict of topic → {count, avg_conf, latest_ts}"""
    con = _db_connect(db_path)
    rows = con.execute("""
        SELECT topic,
               COUNT(*)        as count,
               AVG(confidence) as avg_conf,
               MAX(COALESCE(created_at, 0)) as latest
        FROM beliefs
        GROUP BY topic
    """).fetchall()
    con.close()
    return {
        r["topic"]: {
            "count":    r["count"],
            "avg_conf": r["avg_conf"] or 0.5,
            "latest":   r["latest"]  or 0,
        }
        for r in rows
    }


def get_recent_conversation_topics(db_path=DB_PATH, n=200):
    """
    Extract topics from recent conversations.
    Returns list of (topic_word, frequency) sorted by frequency.
    """
    con = _db_connect(db_path)
    text_chunks = []

    for table in ("conversations", "messages", "memory", "convo",
                  "chat_log", "dialogue", "history"):
        try:
            rows = con.execute(
                f"SELECT content FROM {table} ORDER BY rowid DESC LIMIT {n}"
            ).fetchall()
            if rows:
                text_chunks.extend(r[0] for r in rows if r[0])
        except Exception:
            continue
    con.close()

    if not text_chunks:
        return []

    # Simple keyword extraction — count significant words
    full_text = " ".join(text_chunks).lower()
    words = re.findall(r'\b[a-z]{4,}\b', full_text)
    stopwords = {
        "that", "this", "with", "from", "have", "been", "will", "what",
        "when", "where", "they", "them", "then", "than", "just", "like",
        "know", "think", "would", "could", "should", "about", "really",
        "very", "much", "more", "some", "your", "because", "there",
        "their", "also", "into", "over", "back", "even", "most", "such",
        "only", "other", "after", "before", "every", "those", "these",
    }
    meaningful = [w for w in words if w not in stopwords and len(w) > 4]
    counts = Counter(meaningful)

    # Filter to words that match known topics
    topic_hits = [
        (word, count) for word, count in counts.most_common(50)
        if word in KNOWN_TOPICS
    ]
    return topic_hits


def find_gaps(db_path=DB_PATH, max_gaps=MAX_GAPS):
    """
    Core gap detection. Returns list of gap dicts sorted by priority.

    Gap types:
      - missing:    topic not in DB at all
      - thin:       topic has fewer than THIN_THRESHOLD beliefs
      - low_conf:   topic has low average confidence
      - conversational: topic appeared in recent conversations but is thin
    """
    stats      = get_topic_stats(db_path)
    conv_topics = dict(get_recent_conversation_topics(db_path))
    now         = time.time()
    gaps        = []

    for topic in KNOWN_TOPICS:
        s = stats.get(topic)

        # Missing entirely
        if s is None:
            priority = 10.0
            if topic in conv_topics:
                priority += conv_topics[topic] * 0.5  # boost if talked about
            gaps.append({
                "topic":    topic,
                "type":     "missing",
                "count":    0,
                "avg_conf": 0.0,
                "priority": priority,
                "reason":   "no beliefs exist",
            })
            continue

        count    = s["count"]
        avg_conf = s["avg_conf"]
        priority = 0.0
        reasons  = []

        if count < THIN_THRESHOLD:
            priority += (THIN_THRESHOLD - count) * 0.4
            reasons.append(f"only {count} beliefs")

        if avg_conf < CONF_THRESHOLD:
            priority += (CONF_THRESHOLD - avg_conf) * 5
            reasons.append(f"avg confidence {avg_conf:.2f}")

        if topic in conv_topics:
            freq = conv_topics[topic]
            priority += freq * 0.8
            reasons.append(f"came up {freq}x in conversation")

        if priority > 0:
            gaps.append({
                "topic":    topic,
                "type":     "weak",
                "count":    count,
                "avg_conf": avg_conf,
                "priority": priority,
                "reason":   ", ".join(reasons),
            })

    gaps.sort(key=lambda x: x["priority"], reverse=True)
    return gaps[:max_gaps]


def format_gaps(gaps):
    lines = [f"  {'TOPIC':<25} {'TYPE':<12} {'COUNT':>5}  {'CONF':>5}  REASON"]
    lines.append("  " + "─" * 70)
    for g in gaps:
        lines.append(
            f"  {g['topic']:<25} {g['type']:<12} {g['count']:>5}  "
            f"{g['avg_conf']:>5.2f}  {g['reason']}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print("\n  NEX Gap Detector")
    print("  " + "─" * 70)
    gaps = find_gaps()
    if gaps:
        print(format_gaps(gaps))
    else:
        print("  No significant gaps found — belief system looks healthy.")
    print()
