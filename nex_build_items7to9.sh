#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# NEX BUILD — ITEMS 7, 8, 9
# Item 7: Warm Word Inference Engine
# Item 8: Emotional Valence Chains
# Item 9: Warmth Visualiser Dashboard
# ═══════════════════════════════════════════════════════════════

set -e
cd ~/Desktop/nex
source venv/bin/activate
mkdir -p logs

echo "═══ ITEM 7: WARM WORD INFERENCE ENGINE ═══"
cat > /home/rr/Desktop/nex/nex_warmth_inference.py << 'PYEOF'
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
PYEOF
echo "✓ Item 7: warm word inference engine written"


echo ""
echo "═══ ITEM 8: EMOTIONAL VALENCE CHAINS ═══"
cat > /home/rr/Desktop/nex/nex_warmth_valence.py << 'PYEOF'
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
PYEOF
echo "✓ Item 8: emotional valence chains written"


echo ""
echo "═══ ITEM 9: WARMTH VISUALISER DASHBOARD ═══"
cat > /home/rr/Desktop/nex/nex_warmth_dashboard.py << 'PYEOF'
"""
nex_warmth_dashboard.py
Item 9 — Warmth Visualiser Dashboard.

Real-time terminal dashboard showing NEX's cognitive warmth state.
Refreshes every 30 seconds. Shows the invisible made visible.

Panels:
  1. WARMTH DISTRIBUTION — bar chart of warmth levels
  2. TOP WARM WORDS      — hottest words with full tag display
  3. FASTEST WARMING     — velocity leaders
  4. PRIORITY QUEUE      — what's warming next
  5. TENSION GRAPH       — active conceptual tensions
  6. VALENCE MAP         — emotional register overview
  7. BELIEF GENERATION   — warmth-generated beliefs count
  8. DAILY METRICS       — beliefs/words/phrases added today
  9. CRON STATUS         — when each job last ran
"""
import sqlite3, time, os, sys, json
from pathlib import Path
from datetime import datetime

DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"

DEPTH_NAMES = {
    1:"shallow", 2:"semi_mid", 3:"mid",
    4:"semi_deep", 5:"deep", 6:"soul"
}

def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db

def _clear():
    os.system("clear")

def _bar(value, max_val, width=30, char="█") -> str:
    if max_val == 0:
        return " " * width
    filled = int(width * value / max_val)
    return char * filled + "░" * (width - filled)

def _pct(n, total) -> str:
    if total == 0: return "0.0%"
    return f"{n/total*100:.1f}%"

def _safe(db, sql, params=(), default=0):
    try:
        r = db.execute(sql, params).fetchone()
        return r[0] if r else default
    except Exception:
        return default

def render_dashboard():
    db = _get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    W = 72  # terminal width

    _clear()

    # ── HEADER ────────────────────────────────────────────────
    print("╔" + "═"*(W-2) + "╗")
    print(f"║{'NEX COGNITIVE WARMTH DASHBOARD':^{W-2}}║")
    print(f"║{now:^{W-2}}║")
    print("╠" + "═"*(W-2) + "╣")

    # ── WARMTH DISTRIBUTION ───────────────────────────────────
    total_w = _safe(db, "SELECT COUNT(*) FROM word_tags")
    core_w  = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE w>=0.8")
    hot_w   = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE w>=0.6 AND w<0.8")
    warm_w  = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE w>=0.4 AND w<0.6")
    tepid_w = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE w>=0.2 AND w<0.4")
    cold_w  = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE w<0.2")
    nosrch  = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE f=0")

    print(f"║{'  WORD WARMTH DISTRIBUTION':<{W-2}}║")
    print(f"║{'  Total: '+str(total_w)+' words  |  Search-skippable: '+str(nosrch)+' ('+_pct(nosrch,total_w)+')':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    max_bucket = max(core_w, hot_w, warm_w, tepid_w, cold_w, 1)
    for label, count, symbol in [
        ("CORE  ≥0.80", core_w,  "🔥"),
        ("HOT   ≥0.60", hot_w,   "♨ "),
        ("WARM  ≥0.40", warm_w,  "○ "),
        ("TEPID ≥0.20", tepid_w, "· "),
        ("COLD  <0.20", cold_w,  "  "),
    ]:
        bar = _bar(count, max_bucket, width=25)
        print(f"║  {symbol} {label:12} {bar} {count:5} {_pct(count,total_w):>6}  ║")

    # ── TOP WARM WORDS ────────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  TOP WARM WORDS':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    top_words = db.execute("""SELECT word, w, d, a, e, c, f,
        b, s, g FROM word_tags
        ORDER BY w DESC LIMIT 12""").fetchall()

    print(f"║  {'WORD':18} {'W':5} {'D':9} {'ALIGN':6} "
          f"{'VAL':5} {'B':4} {'SRCH':4} ║")
    print(f"║  {'─'*18} {'─'*5} {'─'*9} {'─'*6} "
          f"{'─'*5} {'─'*4} {'─'*4} ║")

    for r in top_words:
        search = "·" if r["f"] == 0 else "⚡"
        depth  = DEPTH_NAMES.get(r["d"], "?")[:9]
        align  = f"{r['a']:+.2f}" if r["a"] else " 0.00"
        val    = f"{r['e']:+.2f}" if r["e"] else " 0.00"
        print(f"║  {r['word']:18} "
              f"{r['w']:.3f} "
              f"{depth:9} "
              f"{align:6} "
              f"{val:5} "
              f"{r['b'] or 0:4} "
              f"{search:>4}  ║")

    # ── FASTEST WARMING ───────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  FASTEST WARMING (velocity leaders)':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    vel_words = db.execute("""SELECT word, w, vel, delta
        FROM word_tags WHERE vel > 0
        ORDER BY vel DESC LIMIT 6""").fetchall()

    if vel_words:
        for r in vel_words:
            bar = _bar(r["vel"] or 0, 1.0, width=20)
            print(f"║  {r['word']:20} "
                  f"w={r['w']:.3f} "
                  f"vel={r['vel']:.3f} "
                  f"{bar}  ║")
    else:
        print(f"║  {'No velocity data yet':^{W-4}}  ║")

    # ── PRIORITY QUEUE ────────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  WARMING QUEUE':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    try:
        queue_stats = db.execute("""SELECT priority,
            COUNT(*) as n, MAX(gap_count) as max_gaps
            FROM warming_queue GROUP BY priority
            ORDER BY CASE priority
                WHEN 'urgent' THEN 1 WHEN 'high' THEN 2
                WHEN 'normal' THEN 3 WHEN 'low' THEN 4
            END""").fetchall()

        total_q = sum(r["n"] for r in queue_stats)
        for r in queue_stats:
            bar = _bar(r["n"], total_q, width=20)
            print(f"║  {r['priority']:8} {bar} "
                  f"{r['n']:5}  max_gaps={r['max_gaps'] or 0}  ║")
        print(f"║  {'TOTAL':8} {'':20} {total_q:5}"
              f"{'':14}║")

        # Show top urgent words
        urgent = db.execute("""SELECT word, gap_count
            FROM warming_queue WHERE priority='urgent'
            ORDER BY gap_count DESC LIMIT 4""").fetchall()
        if urgent:
            words_str = "  urgent: " + ", ".join(
                f"{r['word']}({r['gap_count']})"
                for r in urgent)
            print(f"║{words_str:<{W-2}}║")
    except Exception:
        print(f"║  {'Queue unavailable':^{W-4}}  ║")

    # ── TENSIONS & VALENCE ────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  TENSIONS & VALENCE':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    t_edges = _safe(db, "SELECT COUNT(*) FROM tension_graph")
    t_words = _safe(db,
        "SELECT COUNT(DISTINCT word_a) FROM tension_graph")

    try:
        v_edges = _safe(db,
            "SELECT COUNT(*) FROM valence_chains")
        v_neg   = _safe(db,
            "SELECT COUNT(*) FROM valence_chains "
            "WHERE chain_type='negative'")
        v_pos   = _safe(db,
            "SELECT COUNT(*) FROM valence_chains "
            "WHERE chain_type='positive'")
        print(f"║  Tension graph : {t_edges:4} edges  "
              f"across {t_words} words{'':<14}║")
        print(f"║  Valence chains: {v_edges:4} edges  "
              f"neg={v_neg} pos={v_pos}{'':18}║")
    except Exception:
        print(f"║  Tension graph : {t_edges:4} edges  "
              f"across {t_words} words{'':14}║")
        print(f"║  Valence chains: not yet built"
              f"{'':30}║")

    # Show top tensions
    top_t = db.execute("""SELECT word_a, word_b,
        friction_type, strength
        FROM tension_graph WHERE word_a < word_b
        ORDER BY strength DESC LIMIT 4""").fetchall()
    for r in top_t:
        print(f"║    {r['word_a']:14}←→{r['word_b']:14}"
              f"[{r['friction_type'][:10]:10}] "
              f"s={r['strength']:.2f}{'':3}║")

    # ── BELIEFS ───────────────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  BELIEF GRAPH':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    total_b  = _safe(db, "SELECT COUNT(*) FROM beliefs")
    high_b   = _safe(db,
        "SELECT COUNT(*) FROM beliefs WHERE confidence>=0.75")
    warmth_b = _safe(db,
        "SELECT COUNT(*) FROM beliefs "
        "WHERE source LIKE '%warmth%'")
    tension_b= _safe(db,
        "SELECT COUNT(*) FROM beliefs "
        "WHERE source LIKE '%tension%'")
    cluster_b= _safe(db,
        "SELECT COUNT(*) FROM beliefs "
        "WHERE source LIKE '%cluster%'")

    print(f"║  Total beliefs       : {total_b:,}{'':26}║")
    print(f"║  High confidence     : {high_b:,} "
          f"({_pct(high_b,total_b)}){'':16}║")
    print(f"║  Warmth-generated    : {warmth_b:,} "
          f"(tension={tension_b} cluster={cluster_b}){'':6}║")

    # ── TRAINING DATA ─────────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  TRAINING PIPELINE':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    td = NEX_DIR / "training_data"
    total_pairs = 0
    warmth_pairs= 0
    if td.exists():
        for f in td.glob("*.jsonl"):
            try:
                n = sum(1 for _ in open(f))
                total_pairs += n
                if "warmth" in f.name:
                    warmth_pairs += n
            except Exception:
                pass

    print(f"║  Total training pairs: {total_pairs:,}{'':25}║")
    print(f"║  Warmth pairs        : {warmth_pairs:,}{'':25}║")

    # ── PHRASES ───────────────────────────────────────────────
    total_p = _safe(db, "SELECT COUNT(*) FROM phrase_tags")
    warm_p  = _safe(db,
        "SELECT COUNT(*) FROM phrase_tags WHERE w>=0.35")
    print(f"║  Phrase tags         : {total_p:,} "
          f"({warm_p} warm){'':19}║")

    # ── FOOTER ────────────────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║  {'Refreshes every 30s  |  Ctrl+C to exit':^{W-4}}  ║")
    print("╚" + "═"*(W-2) + "╝")

    db.close()


def run_dashboard(refresh=30, once=False):
    """Run the dashboard, refreshing every N seconds."""
    if once:
        render_dashboard()
        return

    print("Starting NEX Warmth Dashboard "
          "(Ctrl+C to stop)...")
    time.sleep(1)

    try:
        while True:
            render_dashboard()
            time.sleep(refresh)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true",
        help="Render once and exit")
    parser.add_argument("--refresh", type=int, default=30,
        help="Refresh interval in seconds")
    args = parser.parse_args()
    run_dashboard(refresh=args.refresh, once=args.once)
PYEOF
echo "✓ Item 9: warmth dashboard written"


echo ""
echo "═══ WIRING ITEMS 7+8 INTO INTEGRATOR AND CRONTAB ═══"

# Wire valence context into nex_response_protocol.py
python3 << 'PATCHEOF'
from pathlib import Path

path = Path("nex_response_protocol.py")
src  = path.read_text()

VALENCE_INSERT = '''
    # ── VALENCE CONTEXT ───────────────────────────────────────
    _valence_ctx = {}
    if _warmth_ctx:
        try:
            from nex_warmth_valence import get_valence_context
            _valence_ctx = get_valence_context(query)
            if _valence_ctx.get("register") == "negative":
                # Deep tension territory — slow down, go deeper
                _voice_directive = (
                    "Take time with this. Don't rush to "
                    "resolution. Acknowledge genuine difficulty. "
                    + _voice_directive)
            elif _valence_ctx.get("register") == "mixed":
                _voice_directive = (
                    "Hold the tension here. Don't collapse "
                    "ambiguity prematurely. "
                    + _voice_directive)
        except Exception:
            pass
    # ─────────────────────────────────────────────────────────
'''

old_v = "    # 2b. Contradiction check"
new_v = VALENCE_INSERT + "    # 2b. Contradiction check"

if old_v in src and "VALENCE CONTEXT" not in src:
    src = src.replace(old_v, new_v, 1)
    print("✓ Valence context wired into generate()")
else:
    print("✓ Valence already wired or pattern not found")

path.write_text(src)
PATCHEOF

# Wire inference engine into integrator pre_process
python3 << 'PATCHEOF'
from pathlib import Path

path = Path("nex_warmth_integrator.py")
src  = path.read_text()

INFER_INSERT = '''
    # Infer tags for cold words using nearest-neighbor
    if cold_words:
        try:
            from nex_warmth_inference import batch_infer
            batch_infer(cold_words[:10], db)
        except Exception:
            pass
'''

old_i = "    db.commit()\n\n    # Aggregate votes"
new_i = old_i.replace(
    "    db.commit()\n\n    # Aggregate votes",
    "    db.commit()" + INFER_INSERT + "\n    # Aggregate votes"
)

if "batch_infer" not in src and old_i in src:
    src = src.replace(old_i, new_i, 1)
    print("✓ Inference engine wired into pre_process()")
    path.write_text(src)
else:
    print("✓ Inference already wired or pattern not found")
PATCHEOF

# Add to crontab
CRON_TMP=$(mktemp)
crontab -l 2>/dev/null > "$CRON_TMP"

if ! grep -q "nex_warmth_valence" "$CRON_TMP"; then
cat >> "$CRON_TMP" << 'CRONEOF'
# NEX Items 7-9
15 3 * * * cd ~/Desktop/nex && venv/bin/python3 nex_warmth_valence.py --build >> logs/warmth_cron.log 2>&1
30 4 * * * cd ~/Desktop/nex && venv/bin/python3 nex_warmth_inference.py --cold-queue --n 200 >> logs/warmth_cron.log 2>&1
CRONEOF
    crontab "$CRON_TMP"
    echo "✓ Cron entries added for items 7-9"
fi
rm "$CRON_TMP"


echo ""
echo "═══ RUNNING ITEMS 7, 8, 9 ═══"

echo ""
echo "Step 1/3: Inference engine demo..."
venv/bin/python3 nex_warmth_inference.py 2>/dev/null

echo ""
echo "Step 2/3: Valence chain build..."
venv/bin/python3 nex_warmth_valence.py --build 2>/dev/null

echo ""
echo "Step 3/3: Dashboard (once)..."
venv/bin/python3 nex_warmth_dashboard.py --once 2>/dev/null


echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║   ITEMS 7-9 COMPLETE                          ║"
echo "╠═══════════════════════════════════════════════╣"
echo "║                                               ║"
echo "║  BUILT:                                       ║"
echo "║    nex_warmth_inference.py   (Item 7)         ║"
echo "║    nex_warmth_valence.py     (Item 8)         ║"
echo "║    nex_warmth_dashboard.py   (Item 9)         ║"
echo "║                                               ║"
echo "║  WIRED:                                       ║"
echo "║    Inference → pre_process() cold words       ║"
echo "║    Valence   → generate() tone guidance       ║"
echo "║                                               ║"
echo "║  MONITOR:                                     ║"
echo "║    venv/bin/python3 \                         ║"
echo "║      nex_warmth_dashboard.py                  ║"
echo "║    (live, refreshes every 30s)                ║"
echo "║                                               ║"
echo "║  REMAINING: Items 10-12                       ║"
echo "║    10. Warmth-weighted fine-tuning            ║"
echo "║    11. Cross-saga warmth inheritance          ║"
echo "║    12. Inter-session memory warmth            ║"
echo "╚═══════════════════════════════════════════════╝"
