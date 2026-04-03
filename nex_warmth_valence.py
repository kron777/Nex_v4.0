"""
nex_warmth_valence.py
Item 8 — Emotional Valence Chains.

Words with strong emotional valence cluster.
"suffering" pulls "meaning", "growth", "necessity",
"unavoidable" into its negative-valence territory.

Mapping these chains lets NEX pre-load emotional register
for entire argument directions, not just individual words.

This makes NEX's emotional register coherent across a full
response rather than word-by-word. Tone consistency improves
dramatically for deep philosophical territory.

Propagation rules:
  Words 1 hop away: inherit 70% of source valence
  Words 2 hops away: inherit 40%
  Words 3 hops away: inherit 20%
  Words beyond: below threshold, stop

Chain types:
  NEGATIVE  — tension, difficulty, suffering, resistance
  POSITIVE  — resolution, clarity, courage, insight
  MIXED     — paradox, ambiguity, genuine tension
"""
import sqlite3, json, time, logging, sys
from pathlib import Path
from collections import defaultdict, deque

log     = logging.getLogger("nex.valence")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

# Valence propagation decay per hop
HOP_DECAY = [1.0, 0.70, 0.40, 0.20]
MIN_SOURCE_VALENCE = 0.35   # minimum |e| to be a chain source
MIN_PROPAGATED     = 0.10   # minimum valence to store
MAX_CHAIN_DEPTH    = 3      # hops from source


def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def _init_valence_db(db):
    """Create valence chain table."""
    db.execute("""CREATE TABLE IF NOT EXISTS valence_chains (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        source_word TEXT NOT NULL,
        target_word TEXT NOT NULL,
        valence     REAL NOT NULL,
        chain_type  TEXT DEFAULT 'neutral',
        hop_distance INTEGER DEFAULT 1,
        strength    REAL DEFAULT 0.5,
        discovered_at REAL,
        UNIQUE(source_word, target_word)
    )""")
    db.commit()


def _get_high_valence_words(db,
                             min_abs_valence=MIN_SOURCE_VALENCE
                             ) -> list:
    """Get words with strong emotional valence as chain sources."""
    rows = db.execute("""SELECT word, e, w, d,
        pull_toward, association_vector
        FROM word_tags
        WHERE ABS(e) >= ?
        AND w >= 0.2
        ORDER BY ABS(e) DESC""",
        (min_abs_valence,)).fetchall()
    return rows


def _extract_connected_words(row) -> list:
    """Extract words connected to this one."""
    connected = []
    try:
        pull = json.loads(row["pull_toward"] or "[]")
        for item in pull:
            word = (item if isinstance(item, str)
                    else item.get("word",""))
            word = word.lower().strip(".,;:?!'\"()")
            if len(word) >= 4 and word.isalpha():
                connected.append(word)
    except Exception:
        pass
    try:
        assoc = json.loads(row["association_vector"] or "[]")
        for item in assoc:
            if isinstance(item, dict):
                word = item.get("word","").lower()
            else:
                word = str(item).lower()
            word = word.strip(".,;:?!'\"()")
            if len(word) >= 4 and word.isalpha():
                connected.append(word)
    except Exception:
        pass
    return list(set(connected))


def _classify_chain_type(valence: float) -> str:
    """Classify chain type from valence value."""
    if valence <= -0.3:   return "negative"
    elif valence >= 0.3:  return "positive"
    else:                 return "mixed"


def build_valence_chains(db=None) -> dict:
    """
    Build emotional valence chains from all high-valence words.
    Uses BFS from each source, propagating valence with decay.
    """
    close_db = False
    if db is None:
        db = _get_db()
        close_db = True

    _init_valence_db(db)

    sources = _get_high_valence_words(db)
    if not sources:
        print("No high-valence words found yet.")
        if close_db:
            db.close()
        return {"chains": 0, "edges": 0}

    print(f"Building valence chains from "
          f"{len(sources)} source words...")

    total_edges = 0
    total_chains = 0

    for source in sources:
        source_word    = source["word"]
        source_valence = source["e"]

        if abs(source_valence) < MIN_SOURCE_VALENCE:
            continue

        # BFS from source
        queue    = deque([(source_word, source_valence, 0)])
        visited  = {source_word}
        chain_edges = 0

        while queue:
            current_word, current_valence, depth = queue.popleft()

            if depth >= MAX_CHAIN_DEPTH:
                continue

            # Get current word's connections
            current_row = db.execute(
                "SELECT pull_toward, association_vector "
                "FROM word_tags WHERE word=?",
                (current_word,)).fetchone()

            if not current_row:
                continue

            connected = _extract_connected_words(current_row)

            for next_word in connected:
                if next_word in visited:
                    continue
                visited.add(next_word)

                # Propagate valence with hop decay
                hop = depth + 1
                decay = HOP_DECAY[min(hop, len(HOP_DECAY)-1)]
                propagated_valence = current_valence * decay

                if abs(propagated_valence) < MIN_PROPAGATED:
                    continue

                chain_type = _classify_chain_type(
                    propagated_valence)
                strength   = abs(propagated_valence)

                # Store chain edge
                try:
                    db.execute("""INSERT OR REPLACE INTO
                        valence_chains
                        (source_word, target_word, valence,
                         chain_type, hop_distance, strength,
                         discovered_at)
                        VALUES (?,?,?,?,?,?,?)""",
                        (source_word, next_word,
                         round(propagated_valence, 3),
                         chain_type, hop, round(strength, 3),
                         time.time()))
                    chain_edges += 1
                    total_edges += 1
                except Exception:
                    pass

                # Update target word's valence if it shifts it
                target = db.execute(
                    "SELECT e FROM word_tags WHERE word=?",
                    (next_word,)).fetchone()
                if target:
                    # Blend — don't fully override
                    current_e  = target["e"] or 0.0
                    blended_e  = (current_e * 0.6 +
                                  propagated_valence * 0.4)
                    db.execute(
                        "UPDATE word_tags SET e=? "
                        "WHERE word=?",
                        (round(blended_e, 3), next_word))

                # Continue BFS
                queue.append((next_word, propagated_valence,
                              depth + 1))

        db.commit()

        if chain_edges > 0:
            total_chains += 1
            log.info(f"  {source_word:20} "
                     f"e={source_valence:+.2f} "
                     f"→ {chain_edges} edges")

    print(f"\n{'═'*50}")
    print(f"Valence chain build complete:")
    print(f"  Source words    : {len(sources)}")
    print(f"  Chains built    : {total_chains}")
    print(f"  Total edges     : {total_edges}")
    print(f"{'═'*50}")

    if close_db:
        db.close()

    return {"chains": total_chains, "edges": total_edges}


def get_valence_context(question: str, db=None) -> dict:
    """
    Get emotional valence context for a question.
    Pre-loads the dominant emotional register so NEX
    can modulate tone before generating response.

    Returns:
        {
          dominant_valence: float,
          register: "negative"|"positive"|"mixed"|"neutral",
          chain_words: list,  -- words in active valence chains
          tone_guidance: str  -- what this means for response tone
        }
    """
    close_db = False
    if db is None:
        db = _get_db()
        close_db = True

    import re
    words = re.findall(r'\b[a-zA-Z]{4,}\b', question.lower())

    valences = []
    chain_words = []

    for word in words:
        # Check direct tag valence
        row = db.execute(
            "SELECT e FROM word_tags WHERE word=?",
            (word,)).fetchone()
        if row and row["e"] and abs(row["e"]) >= 0.1:
            valences.append(row["e"])
            chain_words.append(word)

        # Check valence chain membership
        chain_row = db.execute("""SELECT valence, chain_type
            FROM valence_chains
            WHERE target_word=?
            ORDER BY ABS(valence) DESC LIMIT 1""",
            (word,)).fetchone()
        if chain_row:
            valences.append(chain_row["valence"] * 0.5)
            chain_words.append(word)

    if not valences:
        result = {
            "dominant_valence": 0.0,
            "register": "neutral",
            "chain_words": [],
            "tone_guidance": "Standard register"
        }
    else:
        dominant = sum(valences) / len(valences)
        register = _classify_chain_type(dominant)

        guidance_map = {
            "negative": "Slow down. Go deeper. "
                       "Don't rush to resolution. "
                       "Acknowledge genuine difficulty.",
            "positive": "Engage with clarity and directness. "
                       "Resolution is appropriate here.",
            "mixed":    "Hold the tension. "
                       "Don't collapse ambiguity prematurely.",
            "neutral":  "Standard register"
        }

        result = {
            "dominant_valence": round(dominant, 3),
            "register":         register,
            "chain_words":      list(set(chain_words)),
            "tone_guidance":    guidance_map.get(
                register, "Standard register")
        }

    if close_db:
        db.close()

    return result


def valence_report(db=None) -> None:
    """Show valence chain coverage."""
    close_db = False
    if db is None:
        db = _get_db()
        close_db = True

    try:
        total = db.execute(
            "SELECT COUNT(*) FROM valence_chains"
            ).fetchone()[0]
        neg   = db.execute(
            "SELECT COUNT(*) FROM valence_chains "
            "WHERE chain_type='negative'").fetchone()[0]
        pos   = db.execute(
            "SELECT COUNT(*) FROM valence_chains "
            "WHERE chain_type='positive'").fetchone()[0]
        mixed = db.execute(
            "SELECT COUNT(*) FROM valence_chains "
            "WHERE chain_type='mixed'").fetchone()[0]

        print(f"\n  Valence chains  : {total} edges")
        print(f"    negative      : {neg}")
        print(f"    positive      : {pos}")
        print(f"    mixed         : {mixed}")

        top_sources = db.execute("""SELECT source_word,
            COUNT(*) as n, AVG(valence) as avg_v
            FROM valence_chains
            GROUP BY source_word
            ORDER BY n DESC LIMIT 8""").fetchall()

        if top_sources:
            print(f"\n  Top chain sources:")
            for r in top_sources:
                print(f"    {r['source_word']:20} "
                      f"edges={r['n']:3} "
                      f"avg_v={r['avg_v']:+.2f}")
    except Exception:
        print("  valence_chains: not yet built")

    if close_db:
        db.close()


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--context", type=str,
        help="Get valence context for a question")
    args = parser.parse_args()

    if args.build:
        result = build_valence_chains()
        print(f"\nResult: {result}")
        valence_report()
    elif args.context:
        result = get_valence_context(args.context)
        import json
        print(json.dumps(result, indent=2))
    else:
        valence_report()
        # Demo context
        test_q = ("What is the relationship between "
                  "suffering and meaning?")
        print(f"\nValence context for: '{test_q}'")
        result = get_valence_context(test_q)
        import json
        print(json.dumps(result, indent=2))
