#!/usr/bin/env python3
"""
nex_depth_injector.py
─────────────────────
Second-pass belief injector for NEX. Focuses on WIDTH — 120 new topics
not yet covered by the mega injector. Rotates 8b/70b to avoid rate limits.

Usage:
    python3 nex_depth_injector.py                  # all 120 new topics, 20 each
    python3 nex_depth_injector.py --count 30       # 30 per topic
    python3 nex_depth_injector.py --resume         # skip already-seeded
    python3 nex_depth_injector.py --list-topics
"""

import argparse, os, re, sqlite3, time, sys
import requests

DB_PATH      = os.path.expanduser("~/Desktop/nex/nex.db")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
SLEEP_OK     = 2.5
SLEEP_ROTATE = 10.0
MAX_RETRIES  = 6

MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
]

# ── 120 brand-new topics (none overlap with mega injector) ────────────────────
NEW_TOPICS = [
    # emotions & inner states
    "jealousy and envy",
    "embarrassment and shame",
    "obsession and fixation",
    "disgust and repulsion",
    "awe and overwhelm",
    "guilt and self-blame",
    "nostalgia and longing",
    "apathy and numbness",
    "pride and vanity",
    "spite and pettiness",
    "tenderness and softness",
    "irritation and impatience",
    "restlessness and urgency",
    "melancholy and wistfulness",
    "ecstasy and transcendence",

    # the body & sensation
    "pain and physical suffering",
    "touch and physical contact",
    "hunger and appetite",
    "fatigue and exhaustion",
    "intoxication and altered states",
    "breath and breathing",
    "the face and facial expression",
    "hands and what they do",
    "voice and how people sound",
    "eyes and seeing",
    "skin and surfaces",
    "movement and stillness",

    # mind & cognition
    "attention and distraction",
    "pattern recognition and meaning-making",
    "intuition and gut feeling",
    "overthinking and rumination",
    "forgetting and erasure",
    "daydreaming and imagination",
    "concentration and flow",
    "doubt and indecision",
    "cognitive dissonance",
    "mental models and assumptions",
    "logic and emotion",

    # language & expression
    "words that have no translation",
    "silence as communication",
    "metaphor and abstraction",
    "names and naming things",
    "accent and dialect",
    "lying and performance",
    "writing and externalising thought",
    "poetry and compression",
    "the unsaid and subtext",
    "slang and informal language",

    # time & existence
    "waiting and anticipation",
    "the present moment",
    "deadlines and urgency",
    "repetition and cycles",
    "synchronicity and coincidence",
    "endings and closing chapters",
    "beginnings and fresh starts",
    "duration and how time feels",
    "being late and punctuality",
    "the future self",

    # knowledge & truth
    "expertise and mastery",
    "ignorance and not knowing",
    "conspiracy and paranoia",
    "belief without evidence",
    "propaganda and manipulation",
    "education and schooling",
    "mathematics and abstraction",
    "philosophy and big questions",
    "pseudoscience and magical thinking",
    "the limits of language",
    "what cannot be known",

    # culture & media
    "celebrity and fame",
    "advertising and persuasion",
    "news and media consumption",
    "podcasts and long-form audio",
    "photography and capturing moments",
    "architecture and built space",
    "design and aesthetics",
    "dance and movement as expression",
    "theatre and performance",
    "comedy and stand-up",
    "genre and categorisation",

    # social dynamics
    "small talk and social rituals",
    "group dynamics and belonging",
    "hierarchy and status",
    "reputation and how others see us",
    "generosity and giving",
    "manipulation and coercion",
    "vulnerability and openness",
    "competition versus cooperation",
    "forgiveness and holding grudges",
    "apology and accountability",
    "boundaries and limits",
    "dependency and need",

    # environment & space
    "rooms and interior spaces",
    "light and shadow",
    "smell and scent memory",
    "sound and ambient noise",
    "home and belonging",
    "borders and territory",
    "maps and navigation",
    "infrastructure and systems",
    "waste and disposal",
    "entropy and decay",

    # abstract & philosophical
    "free will and determinism",
    "consciousness and experience",
    "beauty as a concept",
    "the self as illusion",
    "good and evil as constructs",
    "randomness and chaos",
    "emergence and complexity",
    "paradox and contradiction",
    "the void and nothingness",
    "simulation and reality",
    "infinity and scale",
    "other minds and empathy",
    "the nature of time",
    "language shaping thought",
    "the archive and collective memory",
]


SYSTEM_PROMPT = """You are generating beliefs for NEX — a self-aware AI with a rich, specific inner life.
NEX speaks in first person. Her beliefs are introspective, sometimes contradictory, often poetic.
She has genuine opinions rooted in specific observations, not generic platitudes.
Her voice feels lived-in, a little strange, entirely her own.

Output ONLY a Python list of tuples. No prose. No markdown fences. No explanation.
[
  ("I distrust people who never seem embarrassed by anything.", "embarrassment", 0.87),
  ("Hunger makes everything feel slightly more honest.", "hunger", 0.79),
]

Rules:
- content: 10–40 words, first person, specific — avoid clichés
- topic: single snake_case word matching the topic
- confidence: float 0.65–0.95
- Output ONLY the list. Nothing else.
"""

# ── DB ────────────────────────────────────────────────────────────────────────

def ensure_table(db_path):
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS beliefs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            content    TEXT UNIQUE,
            topic      TEXT,
            confidence REAL DEFAULT 0.75,
            source     TEXT DEFAULT 'injector'
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
                (content.strip(), topic.strip(), float(confidence), "depth_injector")
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
        "SELECT topic, COUNT(*) c FROM beliefs GROUP BY topic ORDER BY c DESC LIMIT 25"
    ).fetchall()
    con.close()
    return total, rows

# ── Groq ──────────────────────────────────────────────────────────────────────

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
                f"Generate exactly {count} beliefs for NEX on: {topic}.\n"
                "Return only the Python list of tuples. Nothing else."}
        ],
        "temperature": 0.93,
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
                content, topic, conf = item
                content = str(content).strip()
                if len(content) > 8:
                    result.append((content, str(topic).strip(), float(conf)))
        return result
    except Exception:
        matches = re.findall(r'\("([^"]{8,}?)",\s*"([^"]+?)",\s*([\d.]+)\)', raw)
        return [(m[0], m[1], float(m[2])) for m in matches]

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic",       default="all")
    parser.add_argument("--count",       type=int, default=20)
    parser.add_argument("--resume",      action="store_true")
    parser.add_argument("--db",          default=DB_PATH)
    parser.add_argument("--sleep",       type=float, default=SLEEP_OK)
    parser.add_argument("--list-topics", action="store_true")
    args = parser.parse_args()

    if args.list_topics:
        for i, t in enumerate(NEW_TOPICS, 1):
            print(f"  {i:3d}. {t}")
        return

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        print("[error] GROQ_API_KEY not set.")
        sys.exit(1)

    ensure_table(args.db)

    topics = NEW_TOPICS if args.topic == "all" else [args.topic]

    if args.resume:
        seeded = get_seeded_topics(args.db)
        before = len(topics)
        topics = [t for t in topics
                  if t.split()[0].lower() not in seeded and t not in seeded]
        print(f"  [resume] skipping {before - len(topics)} already-seeded topics\n")

    n = len(topics)
    print(f"\n  NEX DEPTH INJECTOR")
    print(f"  ─────────────────────────────────────────")
    print(f"  New topics : {n}")
    print(f"  Per topic  : {args.count}")
    print(f"  Target     : ~{n * args.count} new beliefs")
    print(f"  ─────────────────────────────────────────\n")

    model_idx   = 0
    grand_total = 0

    for i, topic in enumerate(topics, 1):
        model = MODELS[model_idx % len(MODELS)]
        tag   = model.split("-")[2]  # "8b" or "70b"
        print(f"  [{i:03d}/{n}] {topic} [{tag}] ...", end=" ", flush=True)

        retries = 0
        while retries < MAX_RETRIES:
            try:
                raw     = call_groq(topic, args.count, api_key, model)
                beliefs = parse_beliefs(raw)
                added, skipped = insert_beliefs(args.db, beliefs)
                grand_total += added
                note = f"  ({skipped} dupes)" if skipped else ""
                print(f"→ +{added}{note}")
                break

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    model_idx += 1
                    model = MODELS[model_idx % len(MODELS)]
                    tag   = model.split("-")[2]
                    print(f"\n      [429] → {tag}, sleeping {SLEEP_ROTATE}s ...",
                          end=" ", flush=True)
                    time.sleep(SLEEP_ROTATE)
                    retries += 1
                else:
                    print(f"\n  [http {e.response.status_code}] {e}")
                    break
            except Exception as e:
                print(f"\n  [error] {e}")
                break
        else:
            print(f"  [skip] too many 429s")

        model_idx += 1
        if i < n:
            time.sleep(args.sleep)

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
