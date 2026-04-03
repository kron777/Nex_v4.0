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
