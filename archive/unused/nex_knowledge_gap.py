"""
nex_knowledge_gap.py
Detects thin belief areas and seeds from web search.
Runs nightly — finds topics with < MIN_BELIEFS high-conf beliefs
and auto-seeds from DuckDuckGo results.
"""
import sqlite3, logging, time
from pathlib import Path

log     = logging.getLogger("nex.gap")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
MIN_BELIEFS    = 50   # topics below this get seeded
MAX_SEED       = 10   # max beliefs to seed per topic per run
MIN_CONF_SEED  = 0.55 # confidence for web-sourced beliefs

# Topics NEX should know about
CORE_TOPICS = [
    "consciousness", "philosophy", "ethics", "ai", "science",
    "free_will", "alignment", "neuroscience", "psychology",
    "language", "mathematics", "physics", "biology", "politics",
    "economics", "art", "music", "history", "logic", "epistemology"
]

def find_gaps() -> list:
    """Return topics below MIN_BELIEFS high-conf count."""
    db = sqlite3.connect(str(DB_PATH))
    gaps = []
    for topic in CORE_TOPICS:
        count = db.execute(
            "SELECT COUNT(*) FROM beliefs WHERE topic=? AND confidence >= 0.6",
            (topic,)).fetchone()[0]
        if count < MIN_BELIEFS:
            gaps.append({"topic": topic, "count": count, "need": MIN_BELIEFS - count})
    db.close()
    gaps.sort(key=lambda x: x["count"])
    return gaps

def seed_from_web(topic: str, n: int = 10) -> int:
    """Search web for topic and insert belief candidates."""
    import sys
    sys.path.insert(0, "/home/rr/Desktop/nex")
    from nex_web_search import search_and_extract_beliefs

    candidates = search_and_extract_beliefs(
        f"{topic} philosophy science", topic=topic)

    if not candidates:
        candidates = search_and_extract_beliefs(topic, topic=topic)

    db = sqlite3.connect(str(DB_PATH))
    inserted = 0
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    for content, conf in candidates[:n]:
        if len(content.split()) < 8:
            continue
        try:
            db.execute("""INSERT INTO beliefs
                (content, topic, confidence, source, belief_type, created_at)
                VALUES (?,?,?,?,?,?)""",
                (content[:300], topic, MIN_CONF_SEED, "web_gap_fill", "fact", now))
            inserted += 1
        except sqlite3.IntegrityError:
            pass

    db.commit()
    db.close()
    return inserted

def run(dry_run=False, verbose=False):
    gaps = find_gaps()

    if not gaps:
        print("No knowledge gaps found.")
        return

    print(f"Found {len(gaps)} knowledge gaps:")
    total_inserted = 0

    for gap in gaps:
        topic = gap["topic"]
        need  = min(gap["need"], MAX_SEED)
        print(f"  {topic}: {gap['count']} beliefs (need {need} more)")

        if not dry_run:
            inserted = seed_from_web(topic, n=need)
            total_inserted += inserted
            if verbose:
                print(f"    -> inserted {inserted}")

    print(f"Total inserted: {total_inserted}")
    return total_inserted

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run, verbose=args.verbose)
