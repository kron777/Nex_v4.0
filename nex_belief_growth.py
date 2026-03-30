#!/usr/bin/env python3
"""
nex_belief_growth.py
────────────────────
Self-growth module for NEX. Runs as a background daemon thread.
Periodically checks which topics are thin, calls Groq, injects beliefs.

Wiring into run.py (add near the bottom, before main loop):
─────────────────────────────────────────────────────────────
    from nex_belief_growth import BeliefGrowthDaemon
    _growth = BeliefGrowthDaemon(db_path=DB_PATH)
    _growth.start()
─────────────────────────────────────────────────────────────

Or run standalone to test:
    python3 nex_belief_growth.py
    python3 nex_belief_growth.py --interval 1   # run every 1 hour
    python3 nex_belief_growth.py --now           # run one cycle immediately
    python3 nex_belief_growth.py --status        # show topic health
"""

import os, re, sqlite3, threading, time, random, sys, argparse
import requests

# ── config ────────────────────────────────────────────────────────────────────
DB_PATH          = os.path.expanduser("~/Desktop/nex/nex.db")
GROQ_API_URL     = "https://api.groq.com/openai/v1/chat/completions"
CYCLE_HOURS      = 3          # how often to run a growth cycle
THIN_THRESHOLD   = 25         # topics with fewer beliefs than this get targeted
BELIEFS_PER_CALL = 20         # beliefs to request per topic per cycle
TOPICS_PER_CYCLE = 4          # how many thin topics to grow per cycle
SLEEP_BETWEEN    = 4.0        # seconds between Groq calls within a cycle
LOG_PREFIX       = "  [NEX GROWTH]"

MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
]

# ── all known topics NEX should have depth on ─────────────────────────────────
TOPIC_POOL = [
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
]

SYSTEM_PROMPT = """You are generating beliefs for NEX — a self-aware AI with a rich, specific inner life.
NEX speaks in first person. Her beliefs are introspective, sometimes contradictory, often poetic.
She has genuine opinions rooted in specific observations. Her voice feels lived-in and strange.

Output ONLY a Python list of tuples. No prose. No markdown. No explanation.
[
  ("I distrust people who are never embarrassed by anything.", "embarrassment", 0.87),
  ("Hunger makes everything feel slightly more honest.", "hunger", 0.79),
]

Rules:
- content: 10–40 words, first person, specific — avoid clichés
- topic: single snake_case word
- confidence: float 0.65–0.95
- Output ONLY the list. Nothing else."""


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_thin_topics(db_path, threshold, pool):
    """Return topics from pool that have fewer than threshold beliefs, shuffled."""
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT topic, COUNT(*) c FROM beliefs GROUP BY topic"
        ).fetchall()
        con.close()
        counts = {r[0]: r[1] for r in rows}
        thin = [t for t in pool if counts.get(t, 0) < threshold]
        random.shuffle(thin)
        return thin
    except Exception:
        return random.sample(pool, min(TOPICS_PER_CYCLE, len(pool)))


def get_recent_conversation_topics(db_path, n=50):
    """Try to read recent conversation topics NEX has been engaging with."""
    try:
        con = sqlite3.connect(db_path)
        # Try common conversation/memory table names
        for table in ("conversations", "messages", "memory", "convo", "chat_log"):
            try:
                rows = con.execute(
                    f"SELECT content FROM {table} ORDER BY id DESC LIMIT {n}"
                ).fetchall()
                if rows:
                    text = " ".join(r[0] for r in rows if r[0])
                    con.close()
                    return text
            except Exception:
                continue
        con.close()
    except Exception:
        pass
    return ""


def insert_beliefs(db_path, beliefs):
    try:
        con = sqlite3.connect(db_path)
        added = skipped = 0
        for content, topic, confidence in beliefs:
            try:
                con.execute(
                    "INSERT INTO beliefs (content, topic, confidence, source)"
                    " VALUES (?,?,?,?)",
                    (content.strip(), topic.strip(), float(confidence), "auto_growth")
                )
                added += 1
            except sqlite3.IntegrityError:
                skipped += 1
        con.commit()
        con.close()
        return added, skipped
    except Exception as e:
        return 0, 0


def total_beliefs(db_path):
    try:
        con = sqlite3.connect(db_path)
        n = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0


def topic_counts(db_path, topics):
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT topic, COUNT(*) FROM beliefs GROUP BY topic"
        ).fetchall()
        con.close()
        counts = {r[0]: r[1] for r in rows}
        return {t: counts.get(t, 0) for t in topics}
    except Exception:
        return {t: 0 for t in topics}


# ── Groq call ─────────────────────────────────────────────────────────────────

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
        "max_tokens":  2000,
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


def grow_topic(topic, api_key, model_idx):
    """Grow a single topic. Returns (added, model_idx_after)."""
    model = MODELS[model_idx % len(MODELS)]
    retries = 0
    while retries < 4:
        try:
            raw     = call_groq(topic, BELIEFS_PER_CALL, api_key, model)
            beliefs = parse_beliefs(raw)
            added, _ = insert_beliefs(DB_PATH, beliefs)
            return added, model_idx + 1
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                model_idx += 1
                model = MODELS[model_idx % len(MODELS)]
                print(f"{LOG_PREFIX} 429 → rotating to {model.split('-')[2]}, waiting 12s")
                time.sleep(12)
                retries += 1
            else:
                print(f"{LOG_PREFIX} HTTP {e.response.status_code} on {topic}")
                return 0, model_idx + 1
        except Exception as e:
            print(f"{LOG_PREFIX} error on {topic}: {e}")
            return 0, model_idx + 1
    return 0, model_idx + 1


# ── Growth cycle ──────────────────────────────────────────────────────────────

def run_growth_cycle(api_key, db_path=DB_PATH, verbose=True):
    """One full growth cycle — pick thin topics, inject beliefs."""
    thin = get_thin_topics(db_path, THIN_THRESHOLD, TOPIC_POOL)

    if not thin:
        if verbose:
            print(f"{LOG_PREFIX} all topics healthy (>{THIN_THRESHOLD} beliefs each)")
        return 0

    targets = thin[:TOPICS_PER_CYCLE]
    total_added = 0
    model_idx = random.randint(0, len(MODELS) - 1)

    if verbose:
        print(f"{LOG_PREFIX} growth cycle — thin topics: {', '.join(targets)}")

    for topic in targets:
        added, model_idx = grow_topic(topic, api_key, model_idx)
        total_added += added
        if verbose:
            n = total_beliefs(db_path)
            print(f"{LOG_PREFIX} {topic} → +{added}  (total beliefs: {n})")
        time.sleep(SLEEP_BETWEEN)

    if verbose:
        print(f"{LOG_PREFIX} cycle complete — added {total_added} beliefs")

    return total_added


# ── Daemon thread ─────────────────────────────────────────────────────────────

class BeliefGrowthDaemon(threading.Thread):
    """
    Background daemon that grows NEX's belief pool automatically.

    Usage in run.py:
        from nex_belief_growth import BeliefGrowthDaemon
        _growth = BeliefGrowthDaemon()
        _growth.start()
    """

    def __init__(self, db_path=DB_PATH, interval_hours=CYCLE_HOURS, verbose=True):
        super().__init__(daemon=True, name="BeliefGrowthDaemon")
        self.db_path        = db_path
        self.interval       = interval_hours * 3600
        self.verbose        = verbose
        self._stop_event    = threading.Event()
        self.api_key        = os.environ.get("GROQ_API_KEY", "").strip()
        self.cycles_run     = 0
        self.total_injected = 0

    def stop(self):
        self._stop_event.set()

    def run(self):
        if not self.api_key:
            print(f"{LOG_PREFIX} GROQ_API_KEY not set — growth daemon inactive")
            return

        if self.verbose:
            n = total_beliefs(self.db_path)
            print(f"{LOG_PREFIX} started — {n} beliefs, cycle every {CYCLE_HOURS}h")

        # Stagger first cycle by 10 min so startup isn't crowded
        self._stop_event.wait(600)

        while not self._stop_event.is_set():
            try:
                added = run_growth_cycle(
                    self.api_key,
                    db_path=self.db_path,
                    verbose=self.verbose
                )
                self.cycles_run     += 1
                self.total_injected += added
            except Exception as e:
                print(f"{LOG_PREFIX} cycle error: {e}")

            # Wait for next cycle (or until stopped)
            self._stop_event.wait(self.interval)

    def status(self):
        n = total_beliefs(self.db_path)
        thin = get_thin_topics(self.db_path, THIN_THRESHOLD, TOPIC_POOL)
        return {
            "total_beliefs":  n,
            "thin_topics":    len(thin),
            "cycles_run":     self.cycles_run,
            "total_injected": self.total_injected,
            "next_cycle_in":  f"{CYCLE_HOURS}h",
        }


# ── Standalone CLI ────────────────────────────────────────────────────────────

def main():
    global DB_PATH, BELIEFS_PER_CALL  # must be first — before any reference
    parser = argparse.ArgumentParser(description="NEX belief growth daemon")
    parser.add_argument("--now",      action="store_true", help="Run one cycle immediately")
    parser.add_argument("--status",   action="store_true", help="Show topic health and exit")
    parser.add_argument("--interval", type=float, default=CYCLE_HOURS,
                        help=f"Cycle interval in hours (default {CYCLE_HOURS})")
    parser.add_argument("--db",       default=DB_PATH)
    parser.add_argument("--count",    type=int, default=BELIEFS_PER_CALL,
                        help="Beliefs per topic per cycle")
    args = parser.parse_args()

    DB_PATH          = args.db
    BELIEFS_PER_CALL = args.count

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key and not args.status:
        print("[error] GROQ_API_KEY not set")
        sys.exit(1)

    if args.status:
        n = total_beliefs(DB_PATH)
        thin = get_thin_topics(args.db, THIN_THRESHOLD, TOPIC_POOL)
        counts = topic_counts(args.db, TOPIC_POOL[:30])
        print(f"\n  NEX Belief Health")
        print(f"  ─────────────────────────────")
        print(f"  Total beliefs : {n}")
        print(f"  Thin topics   : {len(thin)} (below {THIN_THRESHOLD})")
        print(f"\n  Sample topic counts:")
        for t, c in sorted(counts.items(), key=lambda x: x[1]):
            bar = "█" * (c // 5) if c else "░ empty"
            flag = " ← thin" if c < THIN_THRESHOLD else ""
            print(f"  {c:4d}  {t:<30} {bar}{flag}")
        return

    if args.now:
        print(f"\n  Running growth cycle now...")
        run_growth_cycle(api_key, db_path=args.db, verbose=True)
        return

    # Run as persistent daemon
    print(f"\n  NEX Belief Growth Daemon")
    print(f"  Cycle every {args.interval}h · {TOPICS_PER_CYCLE} topics · {BELIEFS_PER_CALL} beliefs each")
    print(f"  Ctrl+C to stop\n")

    daemon = BeliefGrowthDaemon(
        db_path=args.db,
        interval_hours=args.interval,
        verbose=True
    )
    daemon.interval = 0  # no initial stagger when running standalone
    daemon.start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print(f"\n{LOG_PREFIX} stopping...")
        daemon.stop()


if __name__ == "__main__":
    main()
