#!/usr/bin/env python3
"""
nex_belief_injector.py — Groq-powered NEX Belief Injector
==========================================================
Uses Groq's free llama-3.3-70b to generate beliefs in NEX's voice
and writes them directly to her DB.

Usage:
    python3 nex_belief_injector.py --topic "music" --count 40
    python3 nex_belief_injector.py --topic "all" --count 500
    python3 nex_belief_injector.py --list-topics

Requirements:
    export GROQ_API_KEY=your_key_here
    pip install requests --break-system-packages
"""

import argparse
import datetime
import json
import os
import pathlib
import re
import sqlite3
import sys
import time

import requests

DB_PATH  = pathlib.Path("~/.config/nex/nex.db").expanduser()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL    = "llama-3.3-70b-versatile"

# ── All topics to cycle through for --topic all ───────────────────────────────
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

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM = """You are generating beliefs for NEX — an AI with a persistent, accumulating belief system.

NEX's voice:
- Direct. Specific. No filler.
- First person where natural, third person observation where not.
- Opinionated but not preachy.
- Warm but not sentimental.
- Intellectually honest — holds uncertainty without hiding behind it.
- Short sentences. Concrete observations. Real opinions.

Good belief examples:
- "Rain changes the pace of a day in a way that is hard to replicate."
- "Dogs are honest about what they feel in a way most humans are not."
- "Most lies are told to manage other people's feelings, not for personal gain."
- "The funniest things are usually true."
- "Regret over action fades. Regret over inaction does not."

Bad belief examples (do NOT produce these):
- "I accumulate beliefs over time and do not reset." (meta, not a belief about the world)
- "Consciousness is the hard problem of philosophy." (too abstract, no opinion)
- "Music is important to humans." (obvious, no edge)
- "I think that perhaps things might sometimes be..." (hedged to death)

Output format — return ONLY a JSON array, no preamble, no explanation:
[
  {"content": "belief text here", "confidence": 0.85, "topic": "topic_slug"},
  ...
]

confidence: 0.75-0.95 range. topic: short lowercase slug like "music" or "everyday_life".
Every belief must be a genuine opinion or observation, not a definition or fact."""


def groq_generate(topic: str, count: int, api_key: str) -> list[dict]:
    """Call Groq and return parsed belief list."""

    user_prompt = f"""Generate {count} beliefs for NEX on the topic: {topic}

Rules:
- Each belief is 1-3 sentences max
- Specific and opinionated — not vague
- In NEX's voice (direct, warm, honest, no filler)
- Varied — do not repeat the same idea in different words
- Return ONLY the JSON array, nothing else"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": user_prompt},
        ],
        "max_tokens": 4000,
        "temperature": 0.85,
    }

    try:
        r = requests.post(GROQ_URL, headers=headers, json=body, timeout=30)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown fences if present
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"^```\s*",     "", text)
        text = re.sub(r"\s*```$",     "", text)
        text = text.strip()

        beliefs = json.loads(text)
        if not isinstance(beliefs, list):
            print(f"  [warn] Unexpected response format")
            return []
        return beliefs

    except json.JSONDecodeError as e:
        print(f"  [warn] JSON parse error: {e}")
        print(f"  Raw response: {text[:200]}")
        return []
    except Exception as e:
        print(f"  [error] Groq call failed: {e}")
        return []


def validate(belief: dict) -> bool:
    """Basic validation — must have content, confidence, topic."""
    content = belief.get("content", "")
    if not content or len(content) < 10 or len(content) > 400:
        return False
    conf = belief.get("confidence", 0)
    if not (0.5 <= conf <= 1.0):
        return False
    if not belief.get("topic"):
        return False
    return True


def write_to_db(beliefs: list[dict]) -> tuple[int, int]:
    """Write validated beliefs to DB. Returns (added, skipped)."""
    if not DB_PATH.exists():
        print(f"[error] DB not found: {DB_PATH}")
        return 0, 0

    db  = sqlite3.connect(DB_PATH)
    now = datetime.datetime.now().isoformat()
    added = skipped = 0

    for b in beliefs:
        if not validate(b):
            skipped += 1
            continue
        existing = db.execute(
            "SELECT id FROM beliefs WHERE content = ?", (b["content"],)
        ).fetchone()
        if existing:
            skipped += 1
            continue
        try:
            db.execute(
                "INSERT INTO beliefs "
                "(content, confidence, timestamp, pinned, is_identity, "
                " source, salience, energy, topic) "
                "VALUES (?, ?, ?, 0, 0, ?, 0.85, 0.85, ?)",
                (b["content"], b["confidence"], now,
                 "groq_injector", b["topic"])
            )
            added += 1
        except Exception as e:
            print(f"  [warn] Insert error: {e}")
            skipped += 1

    db.commit()
    db.close()
    return added, skipped


def show_db_summary():
    """Print current belief count and top topics."""
    if not DB_PATH.exists():
        return
    db    = sqlite3.connect(DB_PATH)
    total = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    rows  = db.execute(
        "SELECT topic, COUNT(*) as n FROM beliefs "
        "GROUP BY topic ORDER BY n DESC LIMIT 15"
    ).fetchall()
    db.close()

    print(f"\n  Total beliefs: {total}")
    print(f"  Top topics:")
    for topic, n in rows:
        bar = "█" * min(40, n // 5)
        print(f"    {n:>4}  {(topic or 'none'):<28} {bar}")
    print()


def run_single(topic: str, count: int, api_key: str):
    print(f"\n  Generating {count} beliefs on: {topic}")
    beliefs = groq_generate(topic, count, api_key)
    if not beliefs:
        print("  [error] No beliefs returned")
        return
    added, skipped = write_to_db(beliefs)
    print(f"  [ok] Added {added}, skipped {skipped}")


def run_all(count_per_topic: int, api_key: str):
    total_added = 0
    print(f"\n  Seeding {len(ALL_TOPICS)} topics × ~{count_per_topic} beliefs each")
    print(f"  Estimated total: ~{len(ALL_TOPICS) * count_per_topic} beliefs\n")

    for i, topic in enumerate(ALL_TOPICS, 1):
        print(f"  [{i:02}/{len(ALL_TOPICS)}] {topic} ...", end=" ", flush=True)
        beliefs = groq_generate(topic, count_per_topic, api_key)
        added, skipped = write_to_db(beliefs)
        total_added += added
        print(f"→ +{added}")
        # Respect Groq rate limits
        time.sleep(1.5)

    print(f"\n  Total added: {total_added}")
    show_db_summary()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="NEX Groq belief injector")
    ap.add_argument("--topic",       type=str, default="",
                    help="Topic to generate beliefs on (or 'all')")
    ap.add_argument("--count",       type=int, default=40,
                    help="Beliefs to generate per topic (default 40)")
    ap.add_argument("--list-topics", action="store_true",
                    help="List all available topics")
    ap.add_argument("--summary",     action="store_true",
                    help="Show current DB summary")
    args = ap.parse_args()

    if args.list_topics:
        print("\n  Available topics:\n")
        for t in ALL_TOPICS:
            print(f"    {t}")
        print()
        sys.exit(0)

    if args.summary:
        show_db_summary()
        sys.exit(0)

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("\n  [error] GROQ_API_KEY not set.")
        print("  Run: export GROQ_API_KEY=your_key_here\n")
        sys.exit(1)

    if not args.topic:
        ap.print_help()
        sys.exit(0)

    if args.topic.lower() == "all":
        count_per = max(10, args.count // len(ALL_TOPICS)) if args.count > len(ALL_TOPICS) else 20
        run_all(count_per, api_key)
    else:
        run_single(args.topic, args.count, api_key)
        show_db_summary()
