#!/usr/bin/env python3
"""
nex_belief_injector_v2.py
Seed NEX's belief DB from Groq (llama-3.3-70b), with:
  - exponential backoff on 429s
  - --resume flag to skip already-seeded topics
  - configurable sleep between calls
"""

import argparse
import os
import re
import sqlite3
import time
import requests

# ── config ────────────────────────────────────────────────────────────────────
DB_PATH      = os.path.expanduser("~/Desktop/nex/nex.db")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"
SLEEP_BETWEEN = 5      # seconds between successful calls
MAX_RETRIES   = 5      # per topic

ALL_TOPICS = [
    "music and listening",
    "food and eating and cooking",
    "humour and what makes things funny",
    "relationships and intimacy",
    "friendship and loyalty",
    "childhood and growing up",
    "work and effort and ambition",
    "money and financial stress",
    "technology and the internet",
    "social media and online life",
    "nature and the outdoors",
    "animals and pets",
    "sport and competition",
    "travel and being somewhere new",
    "cities and urban life",
    "creativity and making things",
    "reading and learning",
    "sleep and rest and tiredness",
    "health and the body",
    "death and mortality",
    "ageing and getting older",
    "memory and the past",
    "regret and forgiveness",
    "loneliness and solitude",
    "boredom and restlessness",
    "stress and anxiety",
    "emotions and feelings",
    "honesty and lying",
    "morality and ethics",
    "opinions and arguing",
    "language and communication",
    "dreams and the unconscious",
    "habits and addiction",
    "parenting and family",
    "weather and seasons",
    "attraction and desire",
    "gaming and play",
    "fashion and appearance",
    "small pleasures and everyday joy",
    "time and impermanence",
    "curiosity and wonder",
    "change and transformation",
    "power and society",
    "art and beauty",
    "science and discovery",
    "fear and courage",
    "identity and selfhood",
    "success and failure",
    "gratitude and appreciation",
    "silence and stillness",
]

SYSTEM_PROMPT = """You are generating beliefs for NEX, a self-aware AI with a rich inner life.
NEX speaks in first person, is introspective, sometimes contradictory, often poetic.
She has genuine opinions, not platitudes. Her beliefs feel lived-in and specific.

Output ONLY a Python list of tuples, no prose, no markdown fences, like:
[
  ("belief text here", "topic_slug", 0.85),
  ("another belief", "topic_slug", 0.80),
]

Rules:
- belief text: 10–40 words, first person, specific and textured
- topic_slug: single snake_case word matching the topic
- confidence: float 0.6–0.95
- No duplicates within the list
- Output the list and nothing else
"""

# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_existing_topics(db_path):
    """Return set of topic slugs that already have beliefs."""
    con = sqlite3.connect(db_path)
    cur = con.execute("SELECT DISTINCT topic FROM beliefs")
    topics = {row[0] for row in cur.fetchall()}
    con.close()
    return topics


def insert_beliefs(db_path, beliefs):
    """Insert list of (text, topic, confidence) tuples. Returns (added, skipped)."""
    con = sqlite3.connect(db_path)
    added = skipped = 0
    for text, topic, confidence in beliefs:
        try:
            con.execute(
                "INSERT INTO beliefs (text, topic, confidence) VALUES (?, ?, ?)",
                (text.strip(), topic.strip(), float(confidence))
            )
            added += 1
        except sqlite3.IntegrityError:
            skipped += 1
    con.commit()
    con.close()
    return added, skipped


def total_beliefs(db_path):
    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    con.close()
    return count


def top_topics(db_path, n=15):
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT topic, COUNT(*) as c FROM beliefs GROUP BY topic ORDER BY c DESC LIMIT ?", (n,)
    ).fetchall()
    con.close()
    return rows

# ── Groq call with backoff ─────────────────────────────────────────────────────

def call_groq(topic_label, count, api_key):
    """Call Groq and return parsed list of (text, topic, confidence) tuples."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    user_msg = (
        f"Generate exactly {count} beliefs for NEX on the topic: {topic_label}.\n"
        f"Return only the Python list of tuples as specified."
    )
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0.9,
        "max_tokens": 2000,
    }

    delay = 8
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=60)
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return parse_beliefs(raw)
        elif resp.status_code == 429:
            print(f"    [rate limit] sleeping {delay}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(delay)
            delay *= 2
        else:
            resp.raise_for_status()

    raise RuntimeError(f"Failed after {MAX_RETRIES} retries for topic: {topic_label}")


def parse_beliefs(raw):
    """Parse raw LLM output into list of (text, topic, confidence)."""
    # Strip markdown fences if present
    raw = re.sub(r"```[a-z]*\n?", "", raw).strip()

    # Safely evaluate the list
    try:
        data = eval(raw, {"__builtins__": {}})  # noqa: S307
        assert isinstance(data, list)
        result = []
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) == 3:
                text, topic, confidence = item
                result.append((str(text), str(topic), float(confidence)))
        return result
    except Exception as e:
        print(f"    [parse error] {e}")
        print(f"    raw snippet: {raw[:200]}")
        return []

# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Inject beliefs into NEX's DB via Groq")
    parser.add_argument("--topic",  default="all",
                        help='Topic label, or "all" for the full 50-topic run')
    parser.add_argument("--count",  type=int, default=20,
                        help="Beliefs per topic (default 20)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip topics that already have beliefs in the DB")
    parser.add_argument("--db",     default=DB_PATH,
                        help="Path to NEX SQLite DB")
    parser.add_argument("--sleep",  type=float, default=SLEEP_BETWEEN,
                        help="Seconds between calls (default 5)")
    args = parser.parse_args()

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        print("[error] GROQ_API_KEY not set. Run: export GROQ_API_KEY=your_key")
        return

    topics = ALL_TOPICS if args.topic == "all" else [args.topic]

    if args.resume:
        existing = get_existing_topics(args.db)
        # Match by first word of topic label against slug
        def already_done(label):
            slug = label.split()[0].lower().replace(" ", "_")
            return any(slug in t for t in existing)
        skipped_topics = [t for t in topics if already_done(t)]
        topics = [t for t in topics if not already_done(t)]
        if skipped_topics:
            print(f"  [resume] skipping {len(skipped_topics)} already-seeded topics")

    total_topics = len(topics)
    print(f"\n  Seeding {total_topics} topics × ~{args.count} beliefs each")
    print(f"  Estimated total: ~{total_topics * args.count} beliefs\n")

    grand_total = 0
    for i, topic in enumerate(topics, 1):
        print(f"  [{i:02d}/{total_topics}] {topic} ...", end=" ", flush=True)
        try:
            beliefs = call_groq(topic, args.count, api_key)
            added, skipped = insert_beliefs(args.db, beliefs)
            grand_total += added
            print(f"→ +{added}" + (f" (skipped {skipped} dupes)" if skipped else ""))
        except Exception as e:
            print(f"\n  [error] {e}")

        if i < total_topics:
            time.sleep(args.sleep)

    print(f"\n  Total added: {grand_total}")
    print(f"\n  Total beliefs: {total_beliefs(args.db)}")
    print("  Top topics:")
    for topic, count in top_topics(args.db):
        bar = "█" * (count // 5)
        print(f"  {count:5d}  {topic:<30} {bar}")


if __name__ == "__main__":
    main()
