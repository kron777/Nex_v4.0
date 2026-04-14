"""
nex_warmth_opposition.py
Item 3 — Opposition Network Propagation.

Every fully warmed word has an opposition_map listing its
conceptual tensions. Those tension-words MUST be equally warm
for NEX to reason productively about the tension itself.

If NEX deeply understands "consciousness" but "materialism"
is cold, she can't reason about the tension between them —
she only knows one side.

This module:
  1. Scans all words with op >= 0.4 (significant opposition)
  2. Extracts their tension words from opposition_map
  3. Creates tepid tags for cold tension words
  4. Queues them at URGENT — these are reasoning-critical

Additionally builds a tension graph:
  word_A ←→ word_B (friction_type, strength)

This graph becomes queryable — NEX can ask "what are the
live tensions in this conceptual territory?" and get a map.
"""
import sqlite3, json, time, logging, sys
from pathlib import Path

log     = logging.getLogger("nex.opposition")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

STOPWORDS = {
    "the","a","an","is","are","was","were","be","been","i","me",
    "my","we","you","it","this","that","and","or","but","if","in",
    "on","at","to","for","of","with","by","from","as","not","no",
}


def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def _init_tension_graph(db):
    """Create tension graph table."""
    db.execute("""CREATE TABLE IF NOT EXISTS tension_graph (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        word_a       TEXT NOT NULL,
        word_b       TEXT NOT NULL,
        friction_type TEXT,
        strength     REAL DEFAULT 0.5,
        discovered_at REAL,
        UNIQUE(word_a, word_b)
    )""")
    db.commit()


def _get_words_with_opposition(db, min_op=0.4) -> list:
    """Get words that have meaningful opposition maps."""
    rows = db.execute("""SELECT word, w, d, a, e,
        op, opposition_map
        FROM word_tags
        WHERE op >= ?
        AND opposition_map IS NOT NULL
        AND opposition_map != '[]'
        ORDER BY op DESC, w DESC""",
        (min_op,)).fetchall()
    return rows


def _extract_tension_words(opposition_map_json: str) -> list:
    """
    Extract tension words from opposition_map JSON.
    Returns list of (word, friction_type, strength) tuples.
    """
    tensions = []
    try:
        opp = json.loads(opposition_map_json)
        if isinstance(opp, list):
            for item in opp:
                if isinstance(item, dict):
                    word         = item.get("word","").lower()
                    friction_type = item.get("friction_type",
                                            "conceptual")
                    strength     = float(item.get("strength", 0.5))
                elif isinstance(item, str):
                    word         = item.lower()
                    friction_type = "conceptual"
                    strength     = 0.5
                else:
                    continue

                word = word.strip(".,;:?!'\"()")
                if (len(word) >= 4
                        and word not in STOPWORDS
                        and word.isalpha()):
                    tensions.append((word, friction_type, strength))
    except Exception as e:
        log.debug(f"Tension parse failed: {e}")
    return tensions


def _store_tension(word_a: str, word_b: str,
                   friction_type: str, strength: float, db):
    """Store bidirectional tension relationship."""
    try:
        for wa, wb in [(word_a, word_b), (word_b, word_a)]:
            db.execute("""INSERT OR REPLACE INTO tension_graph
                (word_a, word_b, friction_type,
                 strength, discovered_at)
                VALUES (?,?,?,?,?)""",
                (wa, wb, friction_type, strength, time.time()))
        db.commit()
    except Exception as e:
        log.debug(f"Tension store failed: {e}")


def _create_tension_tag(word: str, parent_row,
                        friction_type: str,
                        strength: float, db) -> bool:
    """
    Create tepid tag for a tension word.
    Tension words get slightly different inheritance:
    - They inherit depth level (same conceptual territory)
    - Their alignment is INVERTED from parent (they're in tension)
    - Their emotional valence is inverted (creates friction)
    """
    existing = db.execute(
        "SELECT w FROM word_tags WHERE word=?",
        (word,)).fetchone()
    if existing and existing["w"] >= 0.35:
        return False  # Already warm enough

    # Invert alignment — tension word pulls opposite direction
    inverted_a = -(parent_row["a"] * strength * 0.6)
    # Invert valence — tension creates friction
    inverted_e = -(parent_row["e"] * strength * 0.5)

    warmth = min(0.30, 0.18 + strength * 0.12)

    history = [{
        "pass": 0,
        "w": warmth,
        "ts": time.time(),
        "source": f"opposition:{parent_row['word']}"
                  f"/{friction_type}"
    }]

    try:
        db.execute("""INSERT OR REPLACE INTO word_tags (
            word, w, t, d, a, c, f,
            b, s, g, r, e,
            age, delta, drift, vel,
            warming_history, last_updated
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            word,
            warmth,
            strength * 0.35,  # t — partial tendency
            parent_row["d"],  # d — same depth territory
            inverted_a,       # a — inverted alignment
            0.28,             # c — inherited confidence
            1,                # f — search still needed
            0,                # b — no direct beliefs yet
            max(0, parent_row["s"] - 1),  # s
            0,                # g
            0,                # r
            inverted_e,       # e — inverted valence
            time.time(),
            warmth,
            0.0,
            0.0,
            json.dumps(history),
            time.time()
        ))
        db.commit()
        return True
    except Exception as e:
        log.debug(f"Tension tag failed '{word}': {e}")
        return False


def run_opposition_propagation(min_op=0.4) -> dict:
    """
    Main opposition propagation run.
    Finds all tension relationships and propagates warmth
    to cold tension words.
    """
    db = _get_db()
    _init_tension_graph(db)

    try:
        from nex_word_tag_schema import init_db
        init_db(db)
    except Exception:
        pass

    opp_words = _get_words_with_opposition(db, min_op)

    if not opp_words:
        print("No words with opposition maps found yet.")
        print("Run full warming passes first "
              "(opposition built in pass 5).")
        db.close()
        return {"processed": 0, "new_tags": 0,
                "tensions_stored": 0}

    print(f"\nProcessing {len(opp_words)} words "
          f"with opposition maps...")

    total_new      = 0
    total_tensions = 0
    total_queued   = 0

    for parent in opp_words:
        tensions = _extract_tension_words(
            parent["opposition_map"])
        if not tensions:
            continue

        word_new = 0
        for tension_word, friction_type, strength in tensions:

            # Store in tension graph
            _store_tension(parent["word"], tension_word,
                          friction_type, strength, db)
            total_tensions += 1

            # Create tepid tag for cold tension word
            created = _create_tension_tag(
                tension_word, parent,
                friction_type, strength, db)
            if created:
                total_new += 1
                word_new  += 1

            # Queue at URGENT — tension words are
            # reasoning-critical
            try:
                db.execute("""INSERT OR REPLACE INTO
                    warming_queue
                    (word, priority, gap_count,
                     queued_at, reason, source)
                    VALUES (?,?,?,?,?,?)""",
                    (tension_word, "urgent", 0,
                     time.time(),
                     f"tension_of:{parent['word']}"
                     f"/{friction_type}",
                     "opposition_propagation"))
                db.commit()
                total_queued += 1
            except Exception:
                pass

        if word_new > 0 or tensions:
            print(f"  {parent['word']:20} "
                  f"op={parent['op']:.2f} → "
                  f"{len(tensions)} tensions, "
                  f"{word_new} new tags")

    # Report tension graph
    tension_count = db.execute(
        "SELECT COUNT(*) FROM tension_graph"
        ).fetchone()[0]

    print(f"\n{'═'*50}")
    print(f"Opposition propagation complete:")
    print(f"  Words processed      : {len(opp_words)}")
    print(f"  Tension relationships: {total_tensions}")
    print(f"  New tepid tags       : {total_new}")
    print(f"  Queued urgent        : {total_queued}")
    print(f"  Tension graph size   : {tension_count} edges")
    print(f"{'═'*50}")

    # Show tension graph sample
    sample = db.execute("""SELECT word_a, word_b,
        friction_type, strength
        FROM tension_graph
        ORDER BY strength DESC LIMIT 10""").fetchall()

    if sample:
        print(f"\nStrongest conceptual tensions:")
        for r in sample:
            print(f"  {r['word_a']:18} ←→ "
                  f"{r['word_b']:18} "
                  f"[{r['friction_type'][:15]}] "
                  f"s={r['strength']:.2f}")

    db.close()
    return {
        "processed":       len(opp_words),
        "new_tepid":       total_new,
        "tensions_stored": total_tensions,
        "queued":          total_queued,
    }


def query_tensions(word: str) -> list:
    """
    Query the tension graph for a specific word.
    Returns all words in conceptual tension with it.
    """
    db = _get_db()
    try:
        rows = db.execute("""SELECT word_b, friction_type,
            strength FROM tension_graph
            WHERE word_a=?
            ORDER BY strength DESC""",
            (word.lower(),)).fetchall()
        result = [{"word": r["word_b"],
                   "friction": r["friction_type"],
                   "strength": r["strength"]}
                  for r in rows]
        db.close()
        return result
    except Exception:
        db.close()
        return []


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-op", type=float, default=0.4)
    parser.add_argument("--query", type=str,
        help="Query tensions for a specific word")
    args = parser.parse_args()

    if args.query:
        tensions = query_tensions(args.query)
        print(f"\nTensions for '{args.query}':")
        if tensions:
            for t in tensions:
                print(f"  ←→ {t['word']:20} "
                      f"[{t['friction'][:20]}] "
                      f"s={t['strength']:.2f}")
        else:
            print("  No tensions found yet.")
    else:
        result = run_opposition_propagation(
            min_op=args.min_op)
        print(f"\nResult: {result}")
