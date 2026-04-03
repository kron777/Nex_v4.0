#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# NEX WARMTH EXPANSION — ITEMS 1, 2, 3
# nex_warmth_relational.py    — cascade warming
# nex_warmth_belief_harvest.py — free tepid words from beliefs
# nex_warmth_opposition.py    — opposition network propagation
# Run from: ~/Desktop/nex/
# ═══════════════════════════════════════════════════════════════

set -e
cd ~/Desktop/nex
source venv/bin/activate

echo "═══ ITEM 1: RELATIONAL WARMING CASCADE ═══"
cat > /home/rr/Desktop/nex/nex_warmth_relational.py << 'PYEOF'
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
    inherited_w = min(0.28, 0.20 + inheritance_weight * 0.08)

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
PYEOF
echo "✓ Item 1: relational cascade written"


echo ""
echo "═══ ITEM 2: BELIEF-DERIVED SYNTHETIC TAGS ═══"
cat > /home/rr/Desktop/nex/nex_warmth_belief_harvest.py << 'PYEOF'
"""
nex_warmth_belief_harvest.py
Item 2 — Belief-Derived Synthetic Tags.

NEX has hundreds of high-confidence beliefs. Every significant
word in those beliefs is implicitly positioned — she has used
and reasoned about it already. Mining belief text auto-generates
tepid tags for free. No LLM passes needed.

Process:
  1. Extract all beliefs with confidence >= 0.75
  2. Tokenise — extract meaningful nouns/verbs/adjectives
  3. Score each word by:
       - frequency across beliefs
       - average confidence of beliefs it appears in
       - whether it appears in high-confidence vs low-confidence
  4. Create word_tags entries at w=0.20-0.30 (tepid)
     with belief_density pre-filled from actual count
  5. Queue for proper full warming at appropriate priority

This is the highest ROI step — potentially 500-1000 new tepid
words with zero LLM cost. Every word NEX has ever used in her
own reasoning gets a head start.
"""
import sqlite3, json, re, time, logging, sys
from pathlib import Path
from collections import Counter, defaultdict

log     = logging.getLogger("nex.belief_harvest")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

STOPWORDS = {
    "the","a","an","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","will","would","could",
    "should","may","might","must","shall","can","need",
    "i","me","my","myself","we","our","you","your","it","its",
    "this","that","these","those","what","which","who","whom",
    "when","where","why","how","all","both","each","few","more",
    "most","other","some","such","no","nor","not","only","own",
    "same","so","than","too","very","just","but","and","or","if",
    "then","because","about","into","through","during","before",
    "after","above","below","from","with","they","them","their",
    "there","here","any","also","often","always","never","still",
    "even","also","whether","while","since","though","although",
    "rather","quite","perhaps","maybe","seems","appear","simply",
    "just","already","yet","either","neither","every","many",
    "much","little","long","high","low","large","small","good",
    "well","like","make","take","come","give","know","think",
    "said","says","mean","means","called","named","used","based",
}

MIN_WORD_LENGTH  = 4
MIN_BELIEF_CONF  = 0.72
MIN_WORD_FREQ    = 2   # must appear in at least 2 beliefs


def _get_beliefs(db, min_conf=MIN_BELIEF_CONF) -> list:
    """Fetch all qualifying beliefs."""
    try:
        rows = db.execute("""SELECT content, confidence,
            topic, belief_type
            FROM beliefs
            WHERE confidence >= ?
            ORDER BY confidence DESC""",
            (min_conf,)).fetchall()
        return rows
    except Exception as e:
        log.debug(f"Belief fetch failed: {e}")
        return []


def _tokenise(text: str) -> list:
    """Extract meaningful words from belief text."""
    words = []
    for word in re.findall(r'\b[a-zA-Z]{4,30}\b', text.lower()):
        if word not in STOPWORDS and word.isalpha():
            words.append(word)
    return words


def _infer_depth(word: str, avg_conf: float,
                 belief_topics: list) -> int:
    """
    Infer depth level from the beliefs this word appears in.
    Higher confidence + self/consciousness topics = deeper.
    """
    topic_set = set(t.lower() for t in belief_topics if t)

    # Topic-based depth inference
    if any(t in topic_set for t in
           ["self","consciousness","identity","existence"]):
        return 5
    elif any(t in topic_set for t in
             ["ethics","morality","value","meaning"]):
        return 4
    elif any(t in topic_set for t in
             ["mind","knowledge","truth","reality"]):
        return 4
    elif avg_conf >= 0.88:
        return 4
    elif avg_conf >= 0.80:
        return 3
    else:
        return 2


def _infer_emotional_valence(word: str,
                              belief_texts: list) -> float:
    """
    Infer emotional valence from context words in beliefs.
    Crude but fast — no LLM needed.
    """
    positive_context = {
        "clarity","resolution","understanding","growth",
        "genuine","authentic","honest","courage","depth",
        "insight","truth","wisdom","clear","good","right",
        "meaningful","valuable","important","real","direct"
    }
    negative_context = {
        "suffering","uncertain","unclear","difficult","hard",
        "problem","tension","conflict","unresolved","doubt",
        "confusion","struggle","resist","refuse","deny","wrong",
        "false","contradiction","paradox","impossible","fails"
    }

    pos_count = 0
    neg_count = 0

    for text in belief_texts:
        words = set(text.lower().split())
        pos_count += len(words & positive_context)
        neg_count += len(words & negative_context)

    total = pos_count + neg_count
    if total == 0:
        return 0.0
    return round((pos_count - neg_count) / total, 2)


def harvest_beliefs(db) -> dict:
    """
    Main harvest run.
    Extract vocabulary from belief graph and create tepid tags.
    """
    # Ensure schema exists
    try:
        from nex_word_tag_schema import init_db
        init_db(db)
    except Exception:
        pass

    beliefs = _get_beliefs(db)
    if not beliefs:
        print("No beliefs found — check DB path.")
        return {"harvested": 0, "queued": 0}

    print(f"Processing {len(beliefs)} beliefs...")

    # Build word statistics across all beliefs
    word_freq       = Counter()
    word_conf_sum   = defaultdict(float)
    word_topics     = defaultdict(list)
    word_texts      = defaultdict(list)

    for belief in beliefs:
        content    = belief["content"] or ""
        confidence = belief["confidence"] or 0.0
        topic      = belief["topic"] or ""

        words = _tokenise(content)
        for word in words:
            word_freq[word] += 1
            word_conf_sum[word] += confidence
            if topic:
                word_topics[word].append(topic)
            word_texts[word].append(content[:80])

    # Filter to words appearing in multiple beliefs
    qualifying = {
        word: count
        for word, count in word_freq.items()
        if count >= MIN_WORD_FREQ
    }

    print(f"Qualifying words (freq>={MIN_WORD_FREQ}): "
          f"{len(qualifying)}")

    # Create or update tepid tags
    created  = 0
    updated  = 0
    skipped  = 0
    queued   = 0

    for word, freq in sorted(
            qualifying.items(),
            key=lambda x: x[1], reverse=True):

        # Skip already properly warmed words
        existing = db.execute(
            "SELECT w, b, r FROM word_tags "
            "WHERE word=?", (word,)).fetchone()

        if existing and existing["w"] >= 0.4:
            # Already warm — just update belief density
            db.execute(
                "UPDATE word_tags SET b=MAX(b,?) "
                "WHERE word=?",
                (min(freq, 99), word))
            updated += 1
            continue

        # Calculate tag values from belief statistics
        avg_conf  = word_conf_sum[word] / freq
        depth     = _infer_depth(
            word, avg_conf, word_topics[word])
        valence   = _infer_emotional_valence(
            word, word_texts[word][:5])

        # Warmth score based on frequency and confidence
        # More frequent in high-confidence beliefs = warmer
        warmth = min(0.32,
            0.15 +
            min(freq / 20, 1) * 0.08 +
            (avg_conf - MIN_BELIEF_CONF) * 0.15
        )

        history = [{
            "pass": 0,
            "w": warmth,
            "ts": time.time(),
            "source": f"belief_harvest:freq={freq}"
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
                min(avg_conf * 0.4, 0.4),  # t — partial tendency
                depth,
                0.0,          # a — alignment unknown yet
                min(avg_conf * 0.5, 0.45),  # c — from belief conf
                1,            # f — search still needed
                min(freq, 99),# b — actual belief density!
                0,            # s — saga presence unknown
                0,            # g — gap frequency
                0,            # r — not revised yet
                valence,      # e — inferred valence
                time.time(),
                warmth,
                0.0,
                0.0,
                json.dumps(history),
                time.time()
            ))
            db.commit()
            created += 1

            # Queue for proper warming
            priority = ("high"   if freq >= 10
                       else "high" if depth >= 4
                       else "normal")

            db.execute("""INSERT OR REPLACE INTO warming_queue
                (word, priority, gap_count, queued_at,
                 reason, source)
                VALUES (?,?,?,?,?,?)""",
                (word, priority, freq, time.time(),
                 f"belief_harvest:freq={freq}:conf={avg_conf:.2f}",
                 "belief_harvest"))
            db.commit()
            queued += 1

        except Exception as e:
            log.debug(f"Tag failed for '{word}': {e}")
            skipped += 1

    print(f"\n{'═'*50}")
    print(f"Belief harvest complete:")
    print(f"  Beliefs processed    : {len(beliefs)}")
    print(f"  Qualifying words     : {len(qualifying)}")
    print(f"  New tepid tags       : {created}")
    print(f"  Belief density update: {updated}")
    print(f"  Queued for warming   : {queued}")
    print(f"  Skipped              : {skipped}")
    print(f"{'═'*50}")

    # Show top harvested words
    top_words = db.execute("""SELECT word, w, b, d, e
        FROM word_tags
        WHERE b >= 3
        ORDER BY b DESC, w DESC
        LIMIT 15""").fetchall()

    if top_words:
        print(f"\nTop belief-dense words:")
        depth_n = {1:"shallow",2:"semi_mid",3:"mid",
                   4:"semi_deep",5:"deep",6:"soul"}
        for r in top_words:
            print(f"  {r['word']:22} "
                  f"beliefs={r['b']:3} "
                  f"w={r['w']:.2f} "
                  f"depth={depth_n.get(r['d'],'?')}")

    return {
        "beliefs_processed": len(beliefs),
        "qualifying_words":  len(qualifying),
        "new_tepid":         created,
        "updated":           updated,
        "queued":            queued,
    }


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-conf", type=float,
                        default=MIN_BELIEF_CONF)
    parser.add_argument("--min-freq", type=int,
                        default=MIN_WORD_FREQ)
    args = parser.parse_args()

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    result = harvest_beliefs(db)
    print(f"\nFinal result: {result}")
    db.close()
PYEOF
echo "✓ Item 2: belief harvest written"


echo ""
echo "═══ ITEM 3: OPPOSITION NETWORK PROPAGATION ═══"
cat > /home/rr/Desktop/nex/nex_warmth_opposition.py << 'PYEOF'
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
PYEOF
echo "✓ Item 3: opposition propagation written"


echo ""
echo "═══ WIRING INTO CRONTAB ═══"
CRON_TMP=$(mktemp)
crontab -l 2>/dev/null > "$CRON_TMP"

if ! grep -q "nex_warmth_relational" "$CRON_TMP"; then
cat >> "$CRON_TMP" << 'CRONEOF'
# NEX Warmth Expansion — Items 1,2,3
15 2 * * * cd ~/Desktop/nex && venv/bin/python3 nex_warmth_relational.py >> logs/warmth_cron.log 2>&1
45 2 * * * cd ~/Desktop/nex && venv/bin/python3 nex_warmth_belief_harvest.py >> logs/warmth_cron.log 2>&1
0  4 * * * cd ~/Desktop/nex && venv/bin/python3 nex_warmth_opposition.py >> logs/warmth_cron.log 2>&1
CRONEOF
    crontab "$CRON_TMP"
    echo "✓ Cron entries added"
else
    echo "✓ Cron entries already present"
fi
rm "$CRON_TMP"


echo ""
echo "═══ RUNNING ALL THREE NOW ═══"

echo ""
echo "Step 1/3: Relational cascade..."
venv/bin/python3 nex_warmth_relational.py 2>/dev/null

echo ""
echo "Step 2/3: Belief harvest..."
venv/bin/python3 nex_warmth_belief_harvest.py 2>/dev/null

echo ""
echo "Step 3/3: Opposition propagation..."
venv/bin/python3 nex_warmth_opposition.py 2>/dev/null

echo ""
echo "═══ FINAL DASHBOARD ═══"
venv/bin/python3 nex_word_tag_schema.py --dashboard 2>/dev/null

echo ""
echo "═══ QUEUE STATUS ═══"
venv/bin/python3 -c "
import sqlite3
from pathlib import Path
db = sqlite3.connect(str(Path.home() / 'Desktop/nex/nex.db'))
db.row_factory = sqlite3.Row
total  = db.execute('SELECT COUNT(*) FROM word_tags').fetchone()[0]
warm   = db.execute('SELECT COUNT(*) FROM word_tags WHERE w>=0.4').fetchone()[0]
tepid  = db.execute('SELECT COUNT(*) FROM word_tags WHERE w>=0.2 AND w<0.4').fetchone()[0]
cold   = db.execute('SELECT COUNT(*) FROM word_tags WHERE w<0.2').fetchone()[0]
try:
    q = db.execute('SELECT priority, COUNT(*) as n FROM warming_queue GROUP BY priority').fetchall()
    print('Queue:')
    for r in q: print(f'  {r[\"priority\"]:10} {r[\"n\"]}')
except: pass
try:
    t = db.execute('SELECT COUNT(*) FROM tension_graph').fetchone()[0]
    print(f\"Tension graph: {t} edges\")
except: pass
print(f'Word tags total : {total}')
print(f'  warm+         : {warm}')
print(f'  tepid         : {tepid}')
print(f'  cold          : {cold}')
db.close()
" 2>/dev/null

echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║   NEX WARMTH EXPANSION — BUILD COMPLETE       ║"
echo "╠═══════════════════════════════════════════════╣"
echo "║                                               ║"
echo "║  BUILT:                                       ║"
echo "║    nex_warmth_relational.py   (cascade)       ║"
echo "║    nex_warmth_belief_harvest.py (harvest)     ║"
echo "║    nex_warmth_opposition.py   (tensions)      ║"
echo "║                                               ║"
echo "║  CRON ADDED:                                  ║"
echo "║    2:15am  — relational cascade               ║"
echo "║    2:45am  — belief harvest                   ║"
echo "║    4:00am  — opposition propagation           ║"
echo "║                                               ║"
echo "║  NEXT BUILD:                                  ║"
echo "║    Item 4 — Compound phrase warming           ║"
echo "║    Item 5 — Session warmth layer              ║"
echo "║    Item 6 — Contextual re-weighting           ║"
echo "║                                               ║"
echo "║  MONITOR:                                     ║"
echo "║    venv/bin/python3 nex_word_tag_schema.py \  ║"
echo "║      --dashboard                              ║"
echo "║    venv/bin/python3 \                         ║"
echo "║      nex_warmth_opposition.py --query \       ║"
echo "║      consciousness                            ║"
echo "╚═══════════════════════════════════════════════╝"
