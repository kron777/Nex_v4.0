"""
nex_warmth_saga_inherit.py
Item 11 — Cross-Saga Warmth Inheritance.

Sagas at DEEP level engage questions containing vocabulary
that also appears in SOUL sagas. When a DEEP saga advances,
it should boost warmth of words it shares with SOUL questions —
because those words just proved their depth.

Soul vocabulary gets continuously reinforced by all the
reasoning happening below it.

Cross-saga inheritance rules:
  DEEP saga advances    → boost shared SOUL words by +0.05
  SEMI_DEEP advances    → boost shared DEEP/SOUL words by +0.03
  MID advances          → boost shared SEMI_DEEP+ words by +0.02

Additionally tracks which saga questions have activated
which words — building a saga-word coverage map that
shows which conceptual territory is most exercised.
"""
import sqlite3, json, re, time, logging, sys
from pathlib import Path
from collections import defaultdict

log     = logging.getLogger("nex.saga_inherit")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

STOPWORDS = {
    "the","and","for","that","this","with","from","have",
    "been","will","would","could","should","just","also",
    "very","more","most","some","any","all","its","what",
    "which","who","how","when","where","why","than","then",
    "rather","quite","perhaps","maybe","seems","simply",
    "already","yet","either","neither","every","many",
}

# Depth boost values per saga level
DEPTH_BOOSTS = {
    "SOUL":      0.0,   # source — doesn't boost itself
    "DEEP":      0.05,  # boosts SOUL vocabulary
    "SEMI_DEEP": 0.03,  # boosts DEEP + SOUL vocabulary
    "MID":       0.02,  # boosts SEMI_DEEP+ vocabulary
    "SEMI_MID":  0.01,  # boosts MID+ vocabulary
    "SHALLOW":   0.00,  # no boost
}

# Which levels each level boosts
BOOST_TARGETS = {
    "DEEP":      {"SOUL"},
    "SEMI_DEEP": {"DEEP", "SOUL"},
    "MID":       {"SEMI_DEEP", "DEEP", "SOUL"},
    "SEMI_MID":  {"MID", "SEMI_DEEP", "DEEP", "SOUL"},
}


def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def _init_coverage_db(db):
    """Create saga-word coverage map table."""
    db.execute("""CREATE TABLE IF NOT EXISTS saga_word_coverage (
        question_hash TEXT NOT NULL,
        word          TEXT NOT NULL,
        depth_level   TEXT NOT NULL,
        activation_count INTEGER DEFAULT 1,
        last_activated REAL,
        PRIMARY KEY (question_hash, word)
    )""")
    db.commit()


def _extract_words(text: str) -> set:
    """Extract meaningful words from text."""
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
    return {w for w in words if w not in STOPWORDS}


def _get_saga_vocabulary() -> dict:
    """
    Build vocabulary map per depth level from saga questions.
    Returns {depth_name: set_of_words}
    """
    try:
        from nex_question_sagas import SAGAS, Depth
        vocab = {}
        for depth, questions in SAGAS.items():
            words = set()
            for q in questions:
                words.update(_extract_words(q))
            vocab[depth.name] = words
        return vocab
    except Exception as e:
        log.debug(f"Saga vocab failed: {e}")
        return {}


def _get_recent_saga_advances(db, hours=24) -> list:
    """Get saga engagements from the last N hours."""
    cutoff = time.time() - (hours * 3600)
    try:
        rows = db.execute("""SELECT question, stage,
            response, depth_level
            FROM question_sagas
            WHERE timestamp > ?
            ORDER BY timestamp DESC""",
            (cutoff,)).fetchall()
        return rows
    except Exception:
        # Try without timestamp
        try:
            rows = db.execute("""SELECT question, stage,
                response FROM question_sagas
                ORDER BY rowid DESC LIMIT 20""").fetchall()
            return rows
        except Exception:
            return []


def apply_saga_inheritance(db=None,
                           hours=168) -> dict:  # 1 week
    """
    Apply cross-saga warmth inheritance.
    For each recent saga advance, boost shared vocabulary
    with higher-depth sagas.
    """
    close_db = False
    if db is None:
        db = _get_db()
        close_db = True

    _init_coverage_db(db)

    saga_vocab = _get_saga_vocabulary()
    if not saga_vocab:
        print("No saga vocabulary available.")
        if close_db:
            db.close()
        return {"boosts": 0}

    recent = _get_recent_saga_advances(db, hours=hours)
    if not recent:
        print("No recent saga advances found.")
        if close_db:
            db.close()
        return {"boosts": 0}

    print(f"Processing {len(recent)} saga advances...")

    total_boosts = 0
    coverage_updates = 0

    for row in recent:
        question = row["question"] or ""
        response = row["response"] or ""

        # Detect depth level from question content
        # Try to get it from the row or infer
        try:
            depth_name = row["depth_level"] or "DEEP"
        except Exception:
            depth_name = "DEEP"  # default

        boost_val = DEPTH_BOOSTS.get(depth_name, 0.0)
        target_levels = BOOST_TARGETS.get(depth_name, set())

        if boost_val == 0 or not target_levels:
            continue

        # Words activated by this saga engagement
        activated_words = _extract_words(
            question + " " + response)

        # Find words shared with higher-depth sagas
        words_to_boost = set()
        for target_level in target_levels:
            target_vocab = saga_vocab.get(target_level, set())
            shared = activated_words & target_vocab
            words_to_boost.update(shared)

        # Apply warmth boost to shared words
        q_hash = str(hash(question))[:16]

        for word in words_to_boost:
            # Apply boost to word tag
            existing = db.execute(
                "SELECT w, r FROM word_tags "
                "WHERE word=?", (word,)).fetchone()

            if existing:
                new_w = min(1.0,
                    (existing["w"] or 0) + boost_val)
                db.execute(
                    "UPDATE word_tags "
                    "SET w=?, vel=? "
                    "WHERE word=?",
                    (round(new_w, 3),
                     round(boost_val, 3),
                     word))
                total_boosts += 1

            # Update coverage map
            try:
                db.execute("""INSERT OR REPLACE INTO
                    saga_word_coverage
                    (question_hash, word, depth_level,
                     activation_count, last_activated)
                    VALUES (
                        ?,?,?,
                        COALESCE(
                            (SELECT activation_count + 1
                             FROM saga_word_coverage
                             WHERE question_hash=?
                             AND word=?),
                            1),
                        ?)""",
                    (q_hash, word, depth_name,
                     q_hash, word, time.time()))
                coverage_updates += 1
            except Exception:
                pass

        db.commit()

    print(f"\n{'═'*50}")
    print(f"Cross-saga inheritance complete:")
    print(f"  Saga advances processed: {len(recent)}")
    print(f"  Warmth boosts applied  : {total_boosts}")
    print(f"  Coverage updates       : {coverage_updates}")
    print(f"{'═'*50}")

    # Show most-activated words
    try:
        top_coverage = db.execute("""SELECT word,
            SUM(activation_count) as total,
            depth_level
            FROM saga_word_coverage
            GROUP BY word
            ORDER BY total DESC LIMIT 10""").fetchall()

        if top_coverage:
            print(f"\nMost saga-activated words:")
            for r in top_coverage:
                print(f"  {r['word']:22} "
                      f"activations={r['total']:3} "
                      f"depth={r['depth_level']}")
    except Exception:
        pass

    if close_db:
        db.close()

    return {
        "advances_processed": len(recent),
        "boosts_applied":     total_boosts,
        "coverage_updates":   coverage_updates,
    }


def seed_saga_coverage(db=None) -> dict:
    """
    Seed coverage map from all existing saga questions.
    Runs once to bootstrap the coverage tracking.
    """
    close_db = False
    if db is None:
        db = _get_db()
        close_db = True

    _init_coverage_db(db)

    try:
        from nex_question_sagas import SAGAS, Depth
    except Exception as e:
        print(f"Cannot load sagas: {e}")
        if close_db:
            db.close()
        return {"seeded": 0}

    seeded = 0
    for depth, questions in SAGAS.items():
        for question in questions:
            words = _extract_words(question)
            q_hash = str(hash(question))[:16]
            for word in words:
                try:
                    db.execute("""INSERT OR IGNORE INTO
                        saga_word_coverage
                        (question_hash, word, depth_level,
                         activation_count, last_activated)
                        VALUES (?,?,?,?,?)""",
                        (q_hash, word, depth.name,
                         1, time.time()))
                    seeded += 1
                except Exception:
                    pass
    db.commit()

    # Apply initial warmth boosts from coverage
    try:
        from nex_question_sagas import SAGAS, Depth
        soul_words = set()
        deep_words = set()
        for q in SAGAS.get(Depth.SOUL, []):
            soul_words.update(_extract_words(q))
        for q in SAGAS.get(Depth.DEEP, []):
            deep_words.update(_extract_words(q))

        boosted = 0
        for word in soul_words:
            existing = db.execute(
                "SELECT w FROM word_tags WHERE word=?",
                (word,)).fetchone()
            if existing:
                new_w = min(1.0, (existing["w"] or 0) + 0.03)
                db.execute(
                    "UPDATE word_tags SET w=? WHERE word=?",
                    (round(new_w, 3), word))
                boosted += 1
        db.commit()
        print(f"  Initial soul-word boosts: {boosted}")
    except Exception:
        pass

    if close_db:
        db.close()

    return {"seeded": seeded}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--hours", type=int, default=168)
    args = parser.parse_args()

    if args.seed:
        result = seed_saga_coverage()
        print(f"Seed result: {result}")
    if args.run:
        result = apply_saga_inheritance(hours=args.hours)
        print(f"Inheritance result: {result}")
    if not args.seed and not args.run:
        # Run both
        print("Seeding coverage map...")
        seed_result = seed_saga_coverage()
        print(f"  Seeded: {seed_result}")
        print("\nApplying inheritance...")
        result = apply_saga_inheritance(hours=args.hours)
        print(f"  Result: {result}")
