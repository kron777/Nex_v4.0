#!/usr/bin/env python3
"""
nex_drain.py — Curiosity drain using real NexCrawler + get_db factory.
Usage:
    python3 nex_drain.py [N]        # drain N topics (default 10)
    python3 nex_drain.py --status   # queue status only
"""
import sys, json, sqlite3, logging, inspect, traceback
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(message)s")
NEX_DIR = Path(__file__).parent
sys.path.insert(0, str(NEX_DIR))

CFG = Path("~/.config/nex").expanduser()
DB  = CFG / "nex.db"

# ── Seed topics for belief growth ────────────────────────────────
SEED_TOPICS = [
    ("reinforcement learning",          "machine_learning"),
    ("transformer architecture",        "ai_architecture"),
    ("emergent behaviour complex systems","complexity"),
    ("bayesian inference",              "reasoning"),
    ("meta-learning few-shot",          "machine_learning"),
    ("causal reasoning AI",             "reasoning"),
    ("embodied cognition robotics",     "cognitive_science"),
    ("knowledge representation graphs", "ai_architecture"),
    ("self-supervised learning",        "machine_learning"),
    ("neural scaling laws",             "ai_research"),
    ("model interpretability XAI",      "ai_safety"),
    ("active inference free energy",    "cognitive_science"),
    ("goal misgeneralisation AI",       "ai_safety"),
    ("recursive self-improvement",      "ai_safety"),
    ("AI consciousness hard problem",   "philosophy"),
    ("distributed cognition",           "cognitive_science"),
    ("information theory entropy",      "mathematics"),
    ("collective intelligence swarms",  "complexity"),
    ("formal verification software",    "computer_science"),
    ("quantum computing algorithms",    "computer_science"),
    ("constitutional AI alignment",     "ai_safety"),
    ("RLHF reward hacking",             "ai_safety"),
    ("mechanistic interpretability",    "ai_safety"),
    ("world models prediction",         "ai_architecture"),
    ("memory consolidation sleep",      "neuroscience"),
    ("predictive processing brain",     "neuroscience"),
    ("language grounding symbols",      "cognitive_science"),
    ("multi-agent cooperation game theory","reasoning"),
    ("attention transformer self-attention","ai_architecture"),
    ("contrastive learning representations","machine_learning"),
]


def _belief_count():
    try:
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM beliefs")
        n = cur.fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0


def _enqueue_seeds(engine, topics):
    """Try every known enqueue API until one works."""
    q = getattr(engine, '_queue', None) or getattr(engine, 'queue', None)
    if q is None:
        print("  [seed] Cannot find queue object on engine")
        return 0

    # Discover the enqueue method
    methods = [m for m in dir(q) if not m.startswith('_')]
    enqueue_fn = None
    for name in ['enqueue', 'add', 'push', 'put', 'add_topic', 'queue_topic']:
        if hasattr(q, name):
            enqueue_fn = getattr(q, name)
            break

    if enqueue_fn is None:
        print(f"  [seed] No enqueue method found. Queue methods: {methods}")
        return 0

    # Inspect signature
    sig = inspect.signature(enqueue_fn)
    params = list(sig.parameters.keys())
    print(f"  [seed] Using {type(q).__name__}.{enqueue_fn.__name__}{sig}")

    added = 0
    for topic, reason in topics:
        try:
            if "reason" in params and "confidence" in params:
                enqueue_fn(topic, reason=reason, confidence=0.5)
            elif "reason" in params:
                enqueue_fn(topic, reason=reason)
            elif len(params) >= 2:
                enqueue_fn(topic, reason)
            else:
                enqueue_fn(topic)
            added += 1
        except Exception as exc:
            print(f"  [seed] Failed to enqueue '{topic}': {exc}")
            break

    return added


def main():
    if "--status" in sys.argv:
        from nex.nex_curiosity import CuriosityEngine
        class _M:
            def on_knowledge_gap(self, **kw): return 0
        print(CuriosityEngine(_M()).status())
        print(f"Beliefs in DB: {_belief_count()}")
        return

    n_cycles = 10
    for arg in sys.argv[1:]:
        try:
            n_cycles = int(arg)
        except ValueError:
            pass

    # ── Build crawler with get_db as belief_store ─────────────────
    # NexCrawler does: _db = self.bs() if callable(self.bs) else self.bs
    # get_db() returns a sqlite3 connection with .execute() and .commit()
    # So passing get_db (the function) is exactly right.
    try:
        from nex.nex_crawler import NexCrawler
        from nex.belief_store import get_db
        crawler = NexCrawler(belief_store=get_db)
        print(f"  [crawler] NexCrawler(belief_store=get_db) ✓")
        # Verify it works
        test_db = get_db()
        test_db.execute("SELECT COUNT(*) FROM beliefs")
        print(f"  [crawler] DB connection test ✓")
        test_db.close()
    except Exception:
        print("[FATAL] Cannot build crawler:")
        traceback.print_exc()
        sys.exit(1)

    from nex.nex_curiosity import CuriosityEngine
    engine = CuriosityEngine(crawler)

    # Seed queue if empty
    status = engine.status()
    if status.get("pending", 0) == 0:
        print(f"  Queue empty — seeding {len(SEED_TOPICS)} topics")
        added = _enqueue_seeds(engine, SEED_TOPICS)
        print(f"  Seeded {added} topics into queue")
        status = engine.status()
        print(f"  Queue now: {status}")

    start = _belief_count()
    print(f"\n  Beliefs at start: {start}")
    print(f"  Draining {n_cycles} cycles...\n")

    total = 0
    for i in range(n_cycles):
        status = engine.status()
        pending = status.get("pending", 0)
        if pending == 0:
            print(f"  Queue empty at cycle {i} — re-seeding")
            _enqueue_seeds(engine, SEED_TOPICS[:10])
            status = engine.status()
            if status.get("pending", 0) == 0:
                print("  Queue still empty — stopping")
                break

        count  = engine.drain()
        total += count
        now    = _belief_count()
        print(f"  cycle {i+1}: +{count} beliefs → db={now}")

    final = _belief_count()
    print(f"\n  ── Done ──")
    print(f"  Beliefs: {start} → {final} (+{final - start})")

    # Refresh opinions
    try:
        from nex.nex_opinions import refresh_opinions
        n_op = refresh_opinions()
        print(f"  Opinions: {n_op} formed/updated")
    except Exception as exc:
        print(f"  [warn] opinions: {exc}")

    # Contradiction detection
    try:
        from nex.nex_contradiction_resolver import detect_and_log
        n_t = detect_and_log(limit=500, max_new=15)
        print(f"  Tensions: {n_t} new")
    except Exception as exc:
        print(f"  [warn] tensions: {exc}")

    print(f"\n  Run: python3 weaning_status.py")


if __name__ == "__main__":
    main()
