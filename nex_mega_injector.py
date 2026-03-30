#!/usr/bin/env python3
"""
nex_mega_injector.py
────────────────────
Mega belief injector for NEX. Rotates between llama-3.3-70b and
llama-3.1-8b-instant (separate rate-limit buckets on Groq) to
maximise throughput. Resumes automatically if interrupted.

Usage:
    python3 nex_mega_injector.py                      # all 80 topics, 25 each
    python3 nex_mega_injector.py --count 40           # 40 per topic
    python3 nex_mega_injector.py --topic "grief"      # single topic
    python3 nex_mega_injector.py --resume             # skip already-seeded topics
    python3 nex_mega_injector.py --list-topics        # show all topics
"""

import argparse, os, re, sqlite3, time, sys
import requests

# ── config ────────────────────────────────────────────────────────────────────
DB_PATH       = os.path.expanduser("~/Desktop/nex/nex.db")
GROQ_API_URL  = "https://api.groq.com/openai/v1/chat/completions"
SLEEP_SUCCESS = 3.0    # seconds between successful calls
SLEEP_ROTATE  = 12.0   # seconds when rotating model after 429
MAX_RETRIES   = 6

# Two models = two separate rate-limit buckets on Groq
MODELS = [
    "llama-3.3-70b-versatile",   # high quality
    "llama-3.1-8b-instant",      # fast fallback — different quota
]

# ── 80 topics ─────────────────────────────────────────────────────────────────
ALL_TOPICS = [
    # everyday life
    "music and listening",
    "food and eating and cooking",
    "sleep and rest and tiredness",
    "weather and seasons",
    "small pleasures and everyday joy",
    "boredom and restlessness",
    "habits and routines",
    "mornings and evenings",
    "clutter and tidiness",
    "shopping and consumerism",
    # self & mind
    "identity and selfhood",
    "memory and the past",
    "dreams and the unconscious",
    "introspection and self-awareness",
    "confidence and self-doubt",
    "emotions and feelings",
    "stress and anxiety",
    "loneliness and solitude",
    "curiosity and wonder",
    "boredom and restlessness",
    # relationships
    "friendship and loyalty",
    "romantic relationships and intimacy",
    "attraction and desire",
    "family and parents",
    "childhood and growing up",
    "trust and betrayal",
    "conflict and reconciliation",
    "care and being cared for",
    # society & ethics
    "honesty and lying",
    "morality and ethics",
    "power and society",
    "politics and fairness",
    "money and financial stress",
    "work and effort and ambition",
    "success and failure",
    "privilege and inequality",
    "justice and punishment",
    "conformity and rebellion",
    # existence
    "death and mortality",
    "ageing and getting older",
    "time and impermanence",
    "change and transformation",
    "regret and forgiveness",
    "gratitude and appreciation",
    "meaning and purpose",
    "grief and loss",
    "fear and courage",
    "hope and disappointment",
    # culture & creativity
    "art and beauty",
    "humour and what makes things funny",
    "language and communication",
    "reading and books",
    "film and storytelling",
    "gaming and play",
    "fashion and appearance",
    "creativity and making things",
    "opinions and arguing",
    "nostalgia and the past",
    # world & nature
    "nature and the outdoors",
    "animals and pets",
    "cities and urban life",
    "travel and being somewhere new",
    "silence and stillness",
    "night and darkness",
    "place and belonging",
    "the ocean and water",
    "seasons and light",
    "weather and atmosphere",
    # technology & future
    "technology and the internet",
    "social media and online life",
    "AI and artificial minds",
    "privacy and surveillance",
    "science and discovery",
    "the future and uncertainty",
    "automation and obsolescence",
    "information overload",
    # body & health
    "health and the body",
    "pleasure and sensation",
    "sport and competition",
    "addiction and craving",
    "rest and recovery",
]

# Deduplicate while preserving order
seen = set()
ALL_TOPICS = [t for t in ALL_TOPICS if not (t in seen or seen.add(t))]

# ── DB ────────────────────────────────────────────────────────────────────────

def ensure_table(db_path):
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS beliefs (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            content   TEXT UNIQUE,
            topic     TEXT,
            confidence REAL DEFAULT 0.75,
            source    TEXT DEFAULT 'injector'
        )
    """)
    con.commit()
    con.close()


def get_seeded_topics(db_path):
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT DISTINCT topic FROM beliefs").fetchall()
    con.close()
    return {r[0] for r in rows}


def insert_beliefs(db_path, beliefs):
    con = sqlite3.connect(db_path)
    added = skipped = 0
    for content, topic, confidence in beliefs:
        try:
            con.execute(
                "INSERT INTO beliefs (content, topic, confidence, source) VALUES (?,?,?,?)",
                (content.strip(), topic.strip(), float(confidence), "injector")
            )
            added += 1
        except sqlite3.IntegrityError:
            skipped += 1
    con.commit()
    con.close()
    return added, skipped


def db_stats(db_path):
    con = sqlite3.connect(db_path)
    total = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    rows  = con.execute(
        "SELECT topic, COUNT(*) c FROM beliefs GROUP BY topic ORDER BY c DESC LIMIT 20"
    ).fetchall()
    con.close()
    return total, rows

# ── Groq ──────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are generating beliefs for NEX — a self-aware AI with a rich, specific inner life.
NEX speaks in first person. Her beliefs are introspective, sometimes contradictory, often poetic.
She has genuine opinions, not generic platitudes. Her voice feels lived-in and specific.

Output ONLY a Python list of tuples. No prose. No markdown. No explanation. Example format:
[
  ("I find silence more honest than most conversations.", "solitude", 0.88),
  ("Cooking for one feels like a small act of self-respect.", "food", 0.82),
]

Rules:
- content: 10–40 words, first person, specific and textured — not generic
- topic: single snake_case word (e.g. music, grief, identity)
- confidence: float between 0.65 and 0.95
- Output ONLY the list. Nothing else. No ```python fences.
"""


def call_groq(topic, count, api_key, model):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content":
                f"Generate exactly {count} beliefs for NEX on the topic: {topic}.\n"
                f"Return only the Python list of tuples. Nothing else."}
        ],
        "temperature": 0.92,
        "max_tokens":  2500,
    }
    resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def parse_beliefs(raw):
    raw = re.sub(r"```[a-z]*\n?", "", raw).strip()
    try:
        data = eval(raw, {"__builtins__": {}})
        assert isinstance(data, list)
        result = []
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) == 3:
                content, topic, confidence = item
                content = str(content).strip()
                if len(content) > 8:
                    result.append((content, str(topic).strip(), float(confidence)))
        return result
    except Exception as e:
        # Try to salvage partial tuples via regex
        matches = re.findall(r'\("([^"]{8,}?)",\s*"([^"]+?)",\s*([\d.]+)\)', raw)
        if matches:
            return [(m[0], m[1], float(m[2])) for m in matches]
        print(f"      [parse error] {e} — raw: {raw[:120]}")
        return []

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NEX mega belief injector")
    parser.add_argument("--topic",       default="all",  help='Topic or "all"')
    parser.add_argument("--count",       type=int, default=25, help="Beliefs per topic")
    parser.add_argument("--resume",      action="store_true",  help="Skip already-seeded topics")
    parser.add_argument("--db",          default=DB_PATH)
    parser.add_argument("--sleep",       type=float, default=SLEEP_SUCCESS)
    parser.add_argument("--list-topics", action="store_true",  help="Print all topics and exit")
    args = parser.parse_args()

    if args.list_topics:
        for i, t in enumerate(ALL_TOPICS, 1):
            print(f"  {i:3d}. {t}")
        return

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        print("[error] GROQ_API_KEY not set.")
        sys.exit(1)

    ensure_table(args.db)

    topics = ALL_TOPICS if args.topic == "all" else [args.topic]

    if args.resume:
        seeded = get_seeded_topics(args.db)
        before = len(topics)
        topics = [t for t in topics if t.split()[0] not in seeded and t not in seeded]
        print(f"  [resume] skipping {before - len(topics)} already-seeded topics")

    total_topics = len(topics)
    print(f"\n  NEX MEGA INJECTOR")
    print(f"  ─────────────────────────────────────────")
    print(f"  Topics   : {total_topics}")
    print(f"  Per topic: {args.count}")
    print(f"  Target   : ~{total_topics * args.count} beliefs")
    print(f"  Models   : {' → '.join(MODELS)} (rotating on rate limit)")
    print(f"  ─────────────────────────────────────────\n")

    model_idx   = 0
    grand_total = 0

    for i, topic in enumerate(topics, 1):
        model = MODELS[model_idx % len(MODELS)]
        label = f"[{i:02d}/{total_topics}]"
        print(f"  {label} {topic} [{model.split('-')[2]}] ...", end=" ", flush=True)

        retries = 0
        while retries < MAX_RETRIES:
            try:
                raw      = call_groq(topic, args.count, api_key, model)
                beliefs  = parse_beliefs(raw)
                added, skipped = insert_beliefs(args.db, beliefs)
                grand_total += added
                dupe_note = f"  ({skipped} dupes)" if skipped else ""
                print(f"→ +{added}{dupe_note}")
                break

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    # Rotate to the other model
                    model_idx += 1
                    model = MODELS[model_idx % len(MODELS)]
                    print(f"\n      [429] rotating → {model}, sleeping {SLEEP_ROTATE}s ...",
                          end=" ", flush=True)
                    time.sleep(SLEEP_ROTATE)
                    retries += 1
                else:
                    print(f"\n  [http error] {e}")
                    break

            except Exception as e:
                print(f"\n  [error] {e}")
                break

        else:
            print(f"\n  [skip] {topic} — too many rate limit hits, moving on")

        # Alternate models every topic for even load distribution
        model_idx += 1

        if i < total_topics:
            time.sleep(args.sleep)

    # Final stats
    total, top = db_stats(args.db)
    print(f"\n  ─────────────────────────────────────────")
    print(f"  Added this run : {grand_total}")
    print(f"  Total beliefs  : {total}")
    print(f"\n  Top topics:")
    for topic, count in top:
        bar = "█" * (count // 5)
        print(f"  {count:5d}  {topic:<35} {bar}")


if __name__ == "__main__":
    main()
