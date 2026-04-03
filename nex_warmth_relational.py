"""
nex_warmth_relational.py
Item 1 — Relational Warming Cascade.

Words do not exist in isolation. When "consciousness" reaches hot,
it should pull its neighborhood into warmth automatically:
  qualia, substrate, phenomenal, awareness, experience...

One well-warmed soul word cascades warmth through 15-20 related
words with zero extra LLM cost for the cascade entries —
associations are inherited from the parent word.

Cascade rules:
  Parent w >= 0.6  → children queued at HIGH, tepid tag created
  Parent w >= 0.8  → children queued at URGENT, richer tag created
  Children inherit: depth_level, emotional_valence, saga_presence
  Children get:     c=0.35 (lower confidence — inherited not earned)
                    f=1    (search still needed until properly warmed)
                    w=0.25 (tepid — enough to reduce search scope)

The cascade is directional — pull_toward words get higher
inheritance than general association_vector words.
"""
import sqlite3, json, time, logging, sys
from pathlib import Path

log     = logging.getLogger("nex.relational")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

STOPWORDS = {
    "the","a","an","is","are","was","were","be","been","i","me",
    "my","we","you","it","this","that","and","or","but","if","in",
    "on","at","to","for","of","with","by","from","as","not","no",
    "so","do","did","has","have","had","will","would","could",
    "should","may","might","can","just","also","very","more",
    "most","some","any","all","its","what","which","who","how",
    "when","where","why","than","then","there","here","now",
}


def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def _get_hot_words(db, min_w=0.6) -> list:
    """Get all words that have reached hot/core territory."""
    rows = db.execute("""SELECT word, w, d, e, s, a,
        pull_toward, association_vector
        FROM word_tags
        WHERE w >= ?
        ORDER BY w DESC""", (min_w,)).fetchall()
    return rows


def _extract_cascade_targets(row) -> list:
    """
    Extract candidate cascade targets from a hot word's tag data.
    Returns list of (word, inheritance_weight) tuples.
    """
    targets = []

    # pull_toward — highest weight (most directionally relevant)
    try:
        pull = json.loads(row["pull_toward"] or "[]")
        for item in pull:
            word = (item if isinstance(item, str)
                    else item.get("word",""))
            word = word.lower().strip(".,;:?!'\"()")
            if (len(word) >= 4 and word not in STOPWORDS
                    and word.isalpha()):
                targets.append((word, 0.75))
    except Exception:
        pass

    # association_vector — medium weight
    try:
        assoc = json.loads(row["association_vector"] or "[]")
        for item in assoc:
            if isinstance(item, dict):
                word   = item.get("word","").lower().strip(".,;:?!'\"()")
                weight = float(item.get("weight", 0.5)) * 0.5
            else:
                word   = str(item).lower().strip(".,;:?!'\"()")
                weight = 0.4
            if (len(word) >= 4 and word not in STOPWORDS
                    and word.isalpha()):
                targets.append((word, weight))
    except Exception:
        pass

    # Deduplicate keeping highest weight per word
    seen = {}
    for word, weight in targets:
        seen[word] = max(seen.get(word, 0), weight)

    return list(seen.items())


def _create_inherited_tag(word: str, parent_row,
                          inheritance_weight: float,
                          db) -> bool:
    """
    Create a tepid inherited tag for a cascade target word.
    Does NOT run LLM passes — this is inherited warmth only.
    Returns True if created/updated.
    """
    # Don't overwrite a properly warmed word
    existing = db.execute(
        "SELECT w, r FROM word_tags WHERE word=?",
        (word,)).fetchone()
    if existing and existing["w"] >= 0.4:
        # Already warm — just update belief density hint
        return False

    # Inherit values from parent, discounted by inheritance weight
    inherited_d = parent_row["d"]
    inherited_e = parent_row["e"] * inheritance_weight
    inherited_s = max(0, parent_row["s"] - 1)  # one level lower
    inherited_a = parent_row["a"] * inheritance_weight * 0.7

    # Tepid warmth — enough to reduce search scope
    # but not enough to skip search entirely
    inherited_w = min(0.55, 0.40 + inheritance_weight * 0.15)

    history = [{"pass": 0, "w": inherited_w,
                "ts": time.time(),
                "source": f"cascade:{parent_row['word']}"}]

    try:
        db.execute("""INSERT OR REPLACE INTO word_tags (
            word, w, t, d, a, c, f,
            b, s, g, r, e,
            age, delta, drift, vel,
            warming_history, last_updated
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            word,
            inherited_w,
            inheritance_weight * 0.4,  # t — partial tendency
            inherited_d,
            inherited_a,
            0.30,    # c — low confidence (inherited)
            1,       # f — search still needed
            0,       # b — no direct belief anchors yet
            inherited_s,
            0,       # g — gap frequency starts at 0
            0,       # r — not yet revised
            inherited_e,
            time.time(),   # age
            inherited_w,   # delta
            0.0,           # drift
            0.0,           # vel
            json.dumps(history),
            time.time()
        ))
        db.commit()
        return True
    except Exception as e:
        log.debug(f"Inherited tag failed for '{word}': {e}")
        return False


def _queue_for_warming(word: str, priority: str,
                       parent: str, db):
    """Queue a cascade target for proper warming."""
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS warming_queue (
            word TEXT PRIMARY KEY,
            priority TEXT DEFAULT 'normal',
            gap_count INTEGER DEFAULT 0,
            queued_at REAL,
            reason TEXT,
            source TEXT
        )""")
        db.execute("""INSERT OR REPLACE INTO warming_queue
            (word, priority, gap_count, queued_at,
             reason, source)
            VALUES (?,?,?,?,?,?)""",
            (word, priority, 0, time.time(),
             f"cascade_from:{parent}",
             "relational_cascade"))
        db.commit()
    except Exception as e:
        log.debug(f"Queue failed for '{word}': {e}")


def run_cascade(min_parent_w=0.6,
                max_children_per_parent=15) -> dict:
    """
    Main cascade run.
    Find all hot words, cascade warmth to their neighborhoods.
    """
    db = _get_db()

    # Ensure word_tags exists
    try:
        from nex_word_tag_schema import init_db
        init_db(db)
    except Exception:
        pass

    hot_words = _get_hot_words(db, min_w=min_parent_w)
    if not hot_words:
        print("No hot words found yet — "
              "run seed warming first.")
        db.close()
        return {"cascaded": 0, "new_tepid": 0, "queued": 0}

    total_new    = 0
    total_queued = 0
    processed    = 0

    print(f"\nCascading from {len(hot_words)} hot words...")

    for parent in hot_words:
        targets = _extract_cascade_targets(parent)
        if not targets:
            continue

        # Sort by inheritance weight, take top N
        targets.sort(key=lambda x: x[1], reverse=True)
        targets = targets[:max_children_per_parent]

        parent_new    = 0
        parent_queued = 0

        for word, weight in targets:
            # Create inherited tag
            created = _create_inherited_tag(
                word, parent, weight, db)
            if created:
                total_new += 1
                parent_new += 1

            # Queue for proper warming
            priority = ("urgent" if parent["w"] >= 0.8
                        else "high")
            _queue_for_warming(word, priority,
                               parent["word"], db)
            total_queued += 1
            parent_queued += 1

        if parent_new > 0:
            print(f"  {parent['word']:20} "
                  f"w={parent['w']:.2f} → "
                  f"{parent_new} new tepid, "
                  f"{parent_queued} queued")
        processed += 1

    db.close()

    print(f"\n{'═'*50}")
    print(f"Cascade complete:")
    print(f"  Hot parents processed : {processed}")
    print(f"  New tepid tags created: {total_new}")
    print(f"  Words queued for warm : {total_queued}")
    print(f"{'═'*50}")

    return {
        "hot_parents":  processed,
        "new_tepid":    total_new,
        "queued":       total_queued,
    }


def cascade_report(db=None) -> None:
    """Show cascade coverage."""
    close = False
    if db is None:
        db = _get_db()
        close = True

    total   = db.execute(
        "SELECT COUNT(*) FROM word_tags").fetchone()[0]
    cascade = db.execute(
        "SELECT COUNT(*) FROM word_tags "
        "WHERE warming_history LIKE '%cascade%'"
        ).fetchone()[0]
    proper  = db.execute(
        "SELECT COUNT(*) FROM word_tags "
        "WHERE r > 0").fetchone()[0]

    print(f"\n  Cascade coverage:")
    print(f"    Total words  : {total}")
    print(f"    Cascade tepid: {cascade}")
    print(f"    Properly warm: {proper}")

    if close:
        db.close()


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-w", type=float, default=0.6)
    parser.add_argument("--max-children", type=int, default=15)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.report:
        cascade_report()
    else:
        result = run_cascade(
            min_parent_w=args.min_w,
            max_children_per_parent=args.max_children)
        print(f"\nResult: {result}")
        cascade_report()
