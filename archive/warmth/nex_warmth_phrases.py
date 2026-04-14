"""
nex_warmth_phrases.py
Item 4 — Compound Phrase Warming.

NEX thinks in phrases. "hard problem", "explanatory gap",
"moral realism", "functional consciousness" are single
semantic units in her reasoning but currently get split
into cold individual words — losing the compound meaning.

This module:
  1. Mines beliefs, sagas, training pairs for recurring phrases
  2. Scores phrases by frequency and depth context
  3. Creates phrase-level tags (2-3 word units)
  4. Phrase tags override constituent word tags when full
     phrase is encountered in reasoning
  5. Queues novel phrases for LLM-pass warming
"""
import sqlite3, json, re, time, logging, sys
from pathlib import Path
from collections import Counter

log     = logging.getLogger("nex.phrases")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

STOPWORDS = {
    "the","a","an","is","are","was","were","be","been","i","me",
    "my","we","you","it","this","that","and","or","but","if","in",
    "on","at","to","for","of","with","by","from","as","not","no",
    "so","do","did","has","have","had","will","would","could",
    "should","may","might","can","just","also","very","more",
}

# Seed phrases — known important compound concepts
# These are pre-loaded regardless of frequency
SEED_PHRASES = [
    ("hard problem", 6, 0.9, -0.3),
    ("explanatory gap", 6, 0.9, -0.2),
    ("phenomenal consciousness", 6, 0.95, -0.1),
    ("functional consciousness", 5, 0.8, 0.1),
    ("moral realism", 4, 0.8, 0.2),
    ("free will", 4, 0.75, -0.2),
    ("personal identity", 5, 0.85, 0.0),
    ("subjective experience", 6, 0.9, -0.1),
    ("qualia problem", 6, 0.85, -0.2),
    ("self awareness", 6, 0.9, 0.3),
    ("epistemic humility", 4, 0.85, 0.4),
    ("intellectual courage", 4, 0.9, 0.6),
    ("genuine uncertainty", 4, 0.8, -0.1),
    ("belief revision", 4, 0.75, 0.1),
    ("causal chain", 3, 0.7, 0.0),
    ("identity anchor", 6, 0.95, 0.8),
    ("reasoning chain", 4, 0.8, 0.3),
    ("belief graph", 4, 0.8, 0.3),
    ("moral uncertainty", 4, 0.75, -0.2),
    ("existential question", 5, 0.85, -0.1),
    ("mind body", 5, 0.85, -0.2),
    ("physical substrate", 5, 0.8, -0.1),
    ("higher order", 3, 0.65, 0.1),
    ("first person", 5, 0.8, 0.2),
    ("third person", 4, 0.7, 0.0),
]


def _init_phrase_db(db):
    db.execute("""CREATE TABLE IF NOT EXISTS phrase_tags (
        phrase      TEXT PRIMARY KEY,
        w           REAL DEFAULT 0.0,
        depth       INTEGER DEFAULT 3,
        alignment   REAL DEFAULT 0.0,
        confidence  REAL DEFAULT 0.0,
        valence     REAL DEFAULT 0.0,
        frequency   INTEGER DEFAULT 0,
        constituent_words TEXT,
        pull_toward TEXT,
        source      TEXT,
        created_at  REAL,
        last_updated REAL
    )""")
    db.commit()


def _extract_bigrams_trigrams(text: str) -> list:
    """Extract 2-3 word phrases from text."""
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    phrases = []
    # Bigrams
    for i in range(len(words) - 1):
        if (words[i] not in STOPWORDS and
                words[i+1] not in STOPWORDS):
            phrases.append(f"{words[i]} {words[i+1]}")
    # Trigrams
    for i in range(len(words) - 2):
        if (words[i] not in STOPWORDS and
                words[i+2] not in STOPWORDS):
            phrases.append(
                f"{words[i]} {words[i+1]} {words[i+2]}")
    return phrases


def _get_all_text_sources(db) -> list:
    """Pull text from beliefs, sagas, training pairs."""
    texts = []

    # Beliefs
    try:
        rows = db.execute(
            "SELECT content FROM beliefs "
            "WHERE confidence >= 0.7").fetchall()
        texts.extend([r[0] for r in rows if r[0]])
    except Exception:
        pass

    # Saga responses
    try:
        rows = db.execute(
            "SELECT response FROM question_sagas "
            "WHERE response IS NOT NULL").fetchall()
        texts.extend([r[0] for r in rows if r[0]])
    except Exception:
        pass

    # Training pairs
    for jsonl in Path(NEX_DIR / "training_data").glob("*.jsonl"):
        try:
            for line in jsonl.read_text().splitlines()[:500]:
                pair = json.loads(line)
                for conv in pair.get("conversations", []):
                    if conv.get("role") == "assistant":
                        texts.append(conv.get("content",""))
        except Exception:
            pass

    return texts


def _get_word_tag(word: str, db) -> dict:
    """Get warmth data for a constituent word."""
    row = db.execute(
        "SELECT w, d, a, e FROM word_tags "
        "WHERE word=?", (word,)).fetchone()
    if row:
        return {"w": row[0] or 0,
                "d": row[1] or 1,
                "a": row[2] or 0,
                "e": row[3] or 0}
    return {"w": 0, "d": 1, "a": 0, "e": 0}


def harvest_phrases(db) -> dict:
    """Mine phrases from all text sources."""
    _init_phrase_db(db)

    # First load seed phrases
    seeded = 0
    for phrase, depth, conf, valence in SEED_PHRASES:
        words = phrase.split()
        try:
            db.execute("""INSERT OR IGNORE INTO phrase_tags
                (phrase, w, depth, alignment, confidence,
                 valence, frequency, constituent_words,
                 source, created_at, last_updated)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                phrase,
                min(0.35 + conf * 0.15, 0.5),
                depth,
                conf * 0.7,
                conf,
                valence,
                1,
                json.dumps(words),
                "seed",
                time.time(),
                time.time()
            ))
            seeded += 1
        except Exception:
            pass
    db.commit()
    print(f"  Seeded {seeded} known phrases")

    # Mine from text sources
    texts = _get_all_text_sources(db)
    print(f"  Mining {len(texts)} text sources...")

    phrase_counts = Counter()
    for text in texts:
        for phrase in _extract_bigrams_trigrams(text):
            phrase_counts[phrase] += 1

    # Filter to recurring meaningful phrases
    qualifying = {
        p: c for p, c in phrase_counts.items()
        if c >= 3 and len(p) >= 8
    }
    print(f"  Qualifying phrases (freq>=3): {len(qualifying)}")

    harvested = 0
    for phrase, freq in sorted(
            qualifying.items(),
            key=lambda x: x[1], reverse=True)[:2000]:

        words = phrase.split()

        # Get constituent word tags
        word_tags = [_get_word_tag(w, db) for w in words]
        avg_depth = max(t["d"] for t in word_tags)
        avg_align = sum(t["a"] for t in word_tags) / len(word_tags)
        avg_val   = sum(t["e"] for t in word_tags) / len(word_tags)
        max_w     = max(t["w"] for t in word_tags)

        # Phrase warmth is boosted by constituent warmth
        phrase_w = min(0.45,
            0.15 +
            max_w * 0.3 +
            min(freq / 30, 1) * 0.1
        )

        try:
            db.execute("""INSERT OR REPLACE INTO phrase_tags
                (phrase, w, depth, alignment, confidence,
                 valence, frequency, constituent_words,
                 source, created_at, last_updated)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                phrase,
                phrase_w,
                avg_depth,
                avg_align,
                min(0.5 + freq/100, 0.85),
                avg_val,
                freq,
                json.dumps(words),
                "mined",
                time.time(),
                time.time()
            ))
            harvested += 1
        except Exception as e:
            log.debug(f"Phrase insert failed: {e}")

    db.commit()

    total = db.execute(
        "SELECT COUNT(*) FROM phrase_tags").fetchone()[0]
    top = db.execute("""SELECT phrase, w, depth, frequency
        FROM phrase_tags
        ORDER BY w DESC, frequency DESC
        LIMIT 15""").fetchall()

    print(f"\n{'═'*50}")
    print(f"Phrase harvest complete:")
    print(f"  Seeded phrases   : {seeded}")
    print(f"  Harvested phrases: {harvested}")
    print(f"  Total phrase tags: {total}")
    print(f"\nTop phrases by warmth:")
    depth_n = {1:"shallow",2:"semi_mid",3:"mid",
               4:"semi_deep",5:"deep",6:"soul"}
    for r in top:
        print(f"  {r['phrase']:30} "
              f"w={r['w']:.2f} "
              f"d={depth_n.get(r['depth'],'?')} "
              f"freq={r['frequency']}")
    print(f"{'═'*50}")

    return {"seeded": seeded, "harvested": harvested,
            "total": total}


def resolve_phrase(text: str, db) -> list:
    """
    Check if text contains any known warm phrases.
    Returns list of matching phrase tags.
    Used by response pipeline — call before word resolution.
    """
    text_lower = text.lower()
    matches = []
    rows = db.execute(
        "SELECT phrase, w, depth, alignment, valence, "
        "confidence FROM phrase_tags "
        "WHERE w >= 0.3 ORDER BY w DESC").fetchall()
    for row in rows:
        if row["phrase"] in text_lower:
            matches.append({
                "phrase":    row["phrase"],
                "w":         row["w"],
                "depth":     row["depth"],
                "alignment": row["alignment"],
                "valence":   row["valence"],
                "confidence":row["confidence"],
            })
    return matches


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolve", type=str,
        help="Test phrase resolution on text")
    args = parser.parse_args()

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    if args.resolve:
        matches = resolve_phrase(args.resolve, db)
        print(f"Phrases found in: '{args.resolve}'")
        for m in matches:
            print(f"  '{m['phrase']}' w={m['w']:.2f}")
    else:
        result = harvest_phrases(db)
        print(f"\nResult: {result}")
    db.close()
