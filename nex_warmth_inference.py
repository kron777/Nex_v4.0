"""
nex_warmth_inference.py
Item 7 — Warm Word Inference Engine.

Unknown word encountered. Rather than cold start, find its
position in semantic space relative to known hot words.
Infer approximate tag values by vector interpolation.

"epiphenomenalism" unknown, but geometrically close to
"consciousness"(hot) + "causation"(warm)
→ infer d=5, a=+0.6, search=Y but reduced scope.

This eliminates most cold-start costs. NEX approaches unknown
territory with approximate warmth rather than complete blindness.

Method:
  1. Encode unknown word with sentence-transformers
  2. Find K nearest hot words in FAISS belief index
  3. Weight-average their tag values by similarity
  4. Assign as provisional tag at c=0.35 (low confidence)
  5. Queue for proper warming to confirm

The provisional tag is enough to:
  - Reduce search radius by ~60%
  - Infer approximate depth level
  - Guess identity alignment direction
  - Set emotional register expectation
"""
import sqlite3, json, time, logging, sys
import numpy as np
from pathlib import Path

log     = logging.getLogger("nex.inference")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

MIN_HOT_W        = 0.45   # minimum warmth to use as anchor
MAX_NEIGHBORS    = 5      # how many hot words to interpolate from
INFERRED_CONF    = 0.35   # confidence cap for inferred tags
MIN_SIMILARITY   = 0.35   # minimum cosine similarity to use


def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def _load_model():
    """Load sentence transformer — cached after first load."""
    if not hasattr(_load_model, "_model"):
        try:
            from sentence_transformers import SentenceTransformer
            _load_model._model = SentenceTransformer(
                "all-MiniLM-L6-v2")
            log.info("Inference model loaded")
        except Exception as e:
            log.debug(f"Model load failed: {e}")
            _load_model._model = None
    return _load_model._model


def _get_hot_word_vectors(db) -> tuple:
    """
    Get all hot words with their tag values and embeddings.
    Returns (words, tags, vectors) or None if unavailable.
    """
    rows = db.execute("""SELECT word, w, d, a, c, e, t, b, s
        FROM word_tags WHERE w >= ?
        ORDER BY w DESC""", (MIN_HOT_W,)).fetchall()

    if not rows:
        return None, None, None

    model = _load_model()
    if model is None:
        return None, None, None

    words = [r["word"] for r in rows]
    tags  = [{
        "w": r["w"] or 0.0,
        "d": r["d"] or 1,
        "a": r["a"] or 0.0,
        "c": r["c"] or 0.0,
        "e": r["e"] or 0.0,
        "t": r["t"] or 0.0,
        "b": r["b"] or 0,
        "s": r["s"] or 0,
    } for r in rows]

    try:
        vectors = model.encode(
            words,
            normalize_embeddings=True,
            show_progress_bar=False
        ).astype(np.float32)
        return words, tags, vectors
    except Exception as e:
        log.debug(f"Encoding failed: {e}")
        return None, None, None


def infer_tag(word: str, db=None) -> dict:
    """
    Infer tag values for an unknown word by interpolating
    from nearest hot words in semantic space.

    Returns inferred tag dict or empty dict if inference fails.
    """
    close_db = False
    if db is None:
        db = _get_db()
        close_db = True

    # Check if word already has a tag
    existing = db.execute(
        "SELECT w FROM word_tags WHERE word=?",
        (word.lower(),)).fetchone()
    if existing and existing["w"] >= 0.2:
        if close_db:
            db.close()
        return {}  # Already known, don't infer

    model = _load_model()
    if model is None:
        if close_db:
            db.close()
        return {}

    # Get hot word vectors
    hot_words, hot_tags, hot_vectors = _get_hot_word_vectors(db)
    if hot_words is None or len(hot_words) < 3:
        if close_db:
            db.close()
        return {}

    # Encode target word
    try:
        word_vec = model.encode(
            [word],
            normalize_embeddings=True,
            show_progress_bar=False
        ).astype(np.float32)
    except Exception as e:
        log.debug(f"Word encoding failed: {e}")
        if close_db:
            db.close()
        return {}

    # Compute cosine similarities
    similarities = np.dot(hot_vectors, word_vec.T).flatten()

    # Get top K neighbors above threshold
    top_k_idx = np.argsort(similarities)[::-1][:MAX_NEIGHBORS]
    neighbors = [
        (hot_words[i], hot_tags[i], float(similarities[i]))
        for i in top_k_idx
        if float(similarities[i]) >= MIN_SIMILARITY
    ]

    if not neighbors:
        if close_db:
            db.close()
        return {}

    # Weighted interpolation of tag values
    total_sim = sum(sim for _, _, sim in neighbors)
    if total_sim == 0:
        if close_db:
            db.close()
        return {}

    inferred = {
        "w": 0.0, "d": 0.0, "a": 0.0,
        "e": 0.0, "t": 0.0, "b": 0.0, "s": 0.0
    }

    for neighbor_word, tag, sim in neighbors:
        weight = sim / total_sim
        for key in inferred:
            inferred[key] += tag[key] * weight

    # Round and clamp
    inferred["d"] = max(1, min(6, round(inferred["d"])))
    inferred["a"] = max(-1.0, min(1.0, inferred["a"]))
    inferred["e"] = max(-1.0, min(1.0, inferred["e"]))
    inferred["w"] = min(0.30,  # cap inferred warmth
        max(0.15, inferred["w"] * 0.5))  # discount heavily
    inferred["c"] = INFERRED_CONF
    inferred["f"] = 1  # search still needed
    inferred["r"] = 0  # not revised

    # Build neighbor summary for history
    neighbor_summary = [
        {"word": w, "sim": round(s, 3)}
        for w, _, s in neighbors[:3]
    ]

    history = [{
        "pass": 0,
        "w": inferred["w"],
        "ts": time.time(),
        "source": f"inferred:neighbors="
                  f"{[n['word'] for n in neighbor_summary]}"
    }]

    # Store inferred tag
    try:
        db.execute("""INSERT OR IGNORE INTO word_tags (
            word, w, t, d, a, c, f,
            b, s, g, r, e,
            age, delta, drift, vel,
            warming_history, last_updated
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            word.lower(),
            inferred["w"],
            inferred["t"],
            inferred["d"],
            inferred["a"],
            INFERRED_CONF,
            1,  # search still needed
            int(inferred["b"]),
            int(inferred["s"]),
            0,  # gap frequency
            0,  # revision count
            inferred["e"],
            time.time(),
            inferred["w"],
            0.0,
            0.0,
            json.dumps(history),
            time.time()
        ))
        db.commit()

        # Queue for proper warming
        db.execute("""INSERT OR IGNORE INTO warming_queue
            (word, priority, gap_count, queued_at,
             reason, source)
            VALUES (?,?,?,?,?,?)""",
            (word.lower(), "normal", 0, time.time(),
             f"inferred:d={inferred['d']}"
             f":a={inferred['a']:.2f}",
             "inference_engine"))
        db.commit()

    except Exception as e:
        log.debug(f"Inferred tag store failed: {e}")

    result = {
        "word":      word,
        "inferred":  True,
        "w":         round(inferred["w"], 3),
        "d":         inferred["d"],
        "a":         round(inferred["a"], 3),
        "e":         round(inferred["e"], 3),
        "c":         INFERRED_CONF,
        "neighbors": neighbor_summary,
        "search_needed": True,
        "cost_reduction": f"~{int(max(0, inferred['d']/6)*60)}%",
    }

    log.info(f"Inferred '{word}': d={inferred['d']} "
             f"a={inferred['a']:+.2f} "
             f"neighbors={[n['word'] for n in neighbor_summary]}")

    if close_db:
        db.close()

    return result


def batch_infer(words: list, db=None) -> dict:
    """
    Run inference on a batch of unknown words.
    More efficient than calling infer_tag() one at a time
    since it loads the model and hot vectors once.
    """
    close_db = False
    if db is None:
        db = _get_db()
        close_db = True

    model = _load_model()
    if model is None:
        if close_db:
            db.close()
        return {"inferred": 0, "failed": len(words)}

    hot_words, hot_tags, hot_vectors = _get_hot_word_vectors(db)
    if hot_words is None:
        if close_db:
            db.close()
        return {"inferred": 0, "failed": len(words)}

    results = {"inferred": 0, "skipped": 0, "failed": 0}

    for word in words:
        word = word.lower().strip()
        if not word or len(word) < 4:
            results["skipped"] += 1
            continue

        # Skip already known
        existing = db.execute(
            "SELECT w FROM word_tags WHERE word=?",
            (word,)).fetchone()
        if existing and existing["w"] >= 0.2:
            results["skipped"] += 1
            continue

        try:
            result = infer_tag(word, db)
            if result:
                results["inferred"] += 1
            else:
                results["skipped"] += 1
        except Exception as e:
            log.debug(f"Batch infer failed '{word}': {e}")
            results["failed"] += 1

    if close_db:
        db.close()

    return results


def infer_cold_queue(n=100) -> dict:
    """
    Run inference on the coldest high-frequency gap words.
    These are words NEX hits often but has no tag for yet.
    """
    db = _get_db()

    # Find cold words in queue that have no tag yet
    cold_words = db.execute("""SELECT q.word
        FROM warming_queue q
        LEFT JOIN word_tags t ON q.word = t.word
        WHERE t.word IS NULL
        AND q.gap_count >= 2
        ORDER BY q.gap_count DESC
        LIMIT ?""", (n,)).fetchall()

    words = [r["word"] for r in cold_words]
    if not words:
        db.close()
        return {"inferred": 0, "message": "No cold queue words"}

    print(f"Running inference on {len(words)} cold queue words...")
    result = batch_infer(words, db)

    db.close()
    return result


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--word", type=str,
        help="Infer tag for a single word")
    parser.add_argument("--cold-queue", action="store_true",
        help="Run inference on cold queue words")
    parser.add_argument("--n", type=int, default=100)
    args = parser.parse_args()

    if args.word:
        result = infer_tag(args.word)
        import json
        print(json.dumps(result, indent=2))
    elif args.cold_queue:
        result = infer_cold_queue(args.n)
        print(f"Batch inference: {result}")
    else:
        # Demo on known unknown words
        test_words = [
            "epiphenomenalism", "qualia", "substrate",
            "phenomenology", "reductionism", "emergence",
            "determinism", "causation", "ontological"
        ]
        db = _get_db()
        print("Inference demo on unknown philosophical terms:\n")
        for word in test_words:
            result = infer_tag(word, db)
            if result:
                neighbors = [n['word'] for n in
                            result.get('neighbors',[])]
                print(f"  {word:25} "
                      f"d={result['d']} "
                      f"a={result['a']:+.2f} "
                      f"w={result['w']:.3f} "
                      f"← {neighbors}")
            else:
                print(f"  {word:25} already known or "
                      f"inference failed")
        db.close()
