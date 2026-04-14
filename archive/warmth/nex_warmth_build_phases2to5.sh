#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# NEX WORD WARMTH SYSTEM — PHASES 2-5
# Run from: ~/Desktop/nex/
# ═══════════════════════════════════════════════════════════════

set -e
cd ~/Desktop/nex
mkdir -p training_data logs

echo "═══ PHASE 2: GAP WORD MINER ═══"
cat > /home/rr/Desktop/nex/nex_gap_miner.py << 'PYEOF'
"""
nex_gap_miner.py
Phase 2 — Gap Word Miner

Watches NEX's COT logs, conversation logs, and belief graph
for uncertainty markers. Extracts the subject words at each
uncertainty point. These are NEX's highest-cost recurring
computations — warming them delivers the largest immediate gains.

Uncertainty markers tracked:
  - Explicit: "I'm not sure", "unclear", "I don't have a position"
  - Implicit: hedging language, qualification chains, aborted reasoning
  - Structural: COT chains that stall or loop

Output: priority-ranked warming queue written to word_tags DB.
"""
import sqlite3, json, re, time, logging, os
from pathlib import Path
from collections import Counter

log     = logging.getLogger("nex.gap_miner")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"

# ── UNCERTAINTY MARKERS ───────────────────────────────────────
EXPLICIT_MARKERS = [
    r"i(?:'m| am) (?:not |un)sure (?:about |of |whether )?(\w+)",
    r"(?:this|that) is unclear[: ]+(\w+)",
    r"i don't have a (?:clear )?position on (\w+)",
    r"i(?:'m| am) uncertain (?:about |regarding )?(\w+)",
    r"(?:it's|it is) (?:difficult|hard) to say (?:about |regarding )?(\w+)",
    r"i (?:can't|cannot) (?:fully )?(?:resolve|determine|assess) (\w+)",
    r"(\w+) (?:remains?|is) (?:genuinely )?unresolved",
    r"i (?:lack|don't have) (?:sufficient )?(?:context|information) (?:about |on )?(\w+)",
    r"(\w+) (?:puzzles?|confuses?) me",
    r"i (?:haven't|have not) (?:fully )?(?:worked out|resolved|settled) (\w+)",
]

HEDGE_MARKERS = [
    r"(?:perhaps|maybe|possibly|conceivably) (\w+)",
    r"(\w+) (?:might|may|could) (?:be|mean|imply)",
    r"i (?:think|believe|suspect) (\w+) (?:but|though|although)",
    r"(?:somewhat|rather|fairly|quite) (\w+)",
    r"in (?:some|certain) (?:sense|ways?) (\w+)",
]

# Words to ignore — too common to be meaningful gap words
STOPWORDS = {
    "the","a","an","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","will","would","could",
    "should","may","might","must","shall","can","need","dare",
    "i","me","my","myself","we","our","you","your","it","its",
    "this","that","these","those","what","which","who","whom",
    "when","where","why","how","all","both","each","few","more",
    "most","other","some","such","no","nor","not","only","own",
    "same","so","than","too","very","just","but","and","or","if",
    "then","because","about","into","through","during","before",
    "after","above","below","up","down","out","on","off","over",
    "under","again","further","once","here","there","any","also",
}

MIN_WORD_LENGTH = 4
MIN_GAP_FREQUENCY = 2  # must appear at least twice to queue


def _init_queue_db(db):
    db.execute("""CREATE TABLE IF NOT EXISTS warming_queue (
        word        TEXT PRIMARY KEY,
        priority    TEXT DEFAULT 'normal',
        gap_count   INTEGER DEFAULT 1,
        queued_at   REAL,
        reason      TEXT,
        source      TEXT
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS gap_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        word        TEXT NOT NULL,
        context     TEXT,
        source_file TEXT,
        marker_type TEXT,
        timestamp   REAL
    )""")
    db.commit()


def _extract_gap_words(text: str, marker_type: str) -> list:
    """Extract candidate gap words from a text segment."""
    words = []
    patterns = (EXPLICIT_MARKERS if marker_type == "explicit"
                else HEDGE_MARKERS)

    for pattern in patterns:
        for match in re.finditer(pattern, text.lower()):
            word = match.group(1).strip(".,;:?!'\"()")
            if (len(word) >= MIN_WORD_LENGTH
                    and word not in STOPWORDS
                    and word.isalpha()):
                words.append(word)

    # Also extract nouns/concepts near uncertainty markers
    # by windowing around marker positions
    marker_positions = []
    for marker in ["not sure", "unclear", "uncertain",
                   "unresolved", "puzzles", "don't know"]:
        for m in re.finditer(re.escape(marker), text.lower()):
            marker_positions.append(m.start())

    for pos in marker_positions:
        window = text[max(0, pos-60):pos+60].lower()
        for word in window.split():
            word = word.strip(".,;:?!'\"()")
            if (len(word) >= MIN_WORD_LENGTH
                    and word not in STOPWORDS
                    and word.isalpha()
                    and len(word) <= 25):
                words.append(word)

    return words


def mine_file(filepath: Path, db) -> int:
    """Mine gap words from a single log file."""
    if not filepath.exists():
        return 0

    text = filepath.read_text(errors="ignore")
    found = 0

    for marker_type in ["explicit", "hedge"]:
        words = _extract_gap_words(text, marker_type)
        for word in words:
            try:
                db.execute("""INSERT INTO gap_log
                    (word, source_file, marker_type, timestamp)
                    VALUES (?,?,?,?)""",
                    (word, str(filepath), marker_type, time.time()))
                found += 1
            except Exception:
                pass

    db.commit()
    return found


def mine_cot_logs(db) -> int:
    """Mine all COT reasoning logs."""
    total = 0
    log_patterns = [
        NEX_DIR / "logs" / "*.log",
        NEX_DIR / "logs" / "*.txt",
        NEX_DIR / "*.log",
    ]
    import glob
    for pattern in log_patterns:
        for f in glob.glob(str(pattern)):
            n = mine_file(Path(f), db)
            total += n
            if n > 0:
                log.info(f"  Mined {n} gaps from {f}")
    return total


def mine_training_pairs(db) -> int:
    """Mine gap words from existing training pair JSONL files."""
    total = 0
    for jsonl_path in NEX_DIR.glob("training_data/*.jsonl"):
        try:
            text_segments = []
            for line in jsonl_path.read_text().splitlines():
                try:
                    pair = json.loads(line)
                    for conv in pair.get("conversations", []):
                        if conv.get("role") == "assistant":
                            text_segments.append(conv.get("content",""))
                except Exception:
                    pass

            for text in text_segments:
                words = _extract_gap_words(text, "explicit")
                words += _extract_gap_words(text, "hedge")
                for word in words:
                    try:
                        db.execute("""INSERT INTO gap_log
                            (word, source_file, marker_type, timestamp)
                            VALUES (?,?,?,?)""",
                            (word, str(jsonl_path),
                             "training", time.time()))
                        total += 1
                    except Exception:
                        pass
            db.commit()
        except Exception as e:
            log.debug(f"  Failed {jsonl_path}: {e}")

    return total


def mine_belief_graph(db) -> list:
    """
    Extract vocabulary from NEX's belief graph.
    Low-confidence beliefs indicate conceptual uncertainty — 
    their vocabulary is high-priority for warming.
    """
    words = []
    try:
        belief_db = sqlite3.connect(str(DB_PATH))
        # Low confidence = uncertain territory
        rows = belief_db.execute("""SELECT content, confidence
            FROM beliefs
            WHERE confidence < 0.75
            ORDER BY confidence ASC
            LIMIT 200""").fetchall()
        belief_db.close()

        for content, conf in rows:
            for word in content.lower().split():
                word = word.strip(".,;:?!'\"()")
                if (len(word) >= MIN_WORD_LENGTH
                        and word not in STOPWORDS
                        and word.isalpha()):
                    # Weight by inverse confidence
                    # lower confidence = more urgent to warm
                    urgency = 1.0 - conf
                    words.append((word, urgency))

    except Exception as e:
        log.debug(f"Belief mining failed: {e}")

    return words


def mine_saga_vocabulary(db) -> list:
    """Extract all meaningful words from saga questions."""
    words = []
    try:
        import sys
        sys.path.insert(0, str(NEX_DIR))
        from nex_question_sagas import SAGAS, Depth

        depth_weights = {
            Depth.SOUL: 1.0,
            Depth.DEEP: 0.9,
            Depth.SEMI_DEEP: 0.75,
            Depth.MID: 0.6,
            Depth.SEMI_MID: 0.45,
            Depth.SHALLOW: 0.3,
        }

        for depth, questions in SAGAS.items():
            weight = depth_weights.get(depth, 0.5)
            for q in questions:
                for word in q.lower().split():
                    word = word.strip("?,.'\"")
                    if (len(word) >= MIN_WORD_LENGTH
                            and word not in STOPWORDS
                            and word.isalpha()):
                        words.append((word, weight))
    except Exception as e:
        log.debug(f"Saga mining failed: {e}")

    return words


def build_priority_queue(db) -> dict:
    """
    Aggregate all gap sources into a priority-ranked warming queue.

    Priority tiers:
      urgent  — frequent gaps, cold word, high belief uncertainty
      high    — soul vocabulary, frequent gaps
      normal  — saga vocabulary, moderate gaps
      low     — hedge words, shallow vocabulary
    """
    # Count gap frequencies
    gap_counts = Counter()
    rows = db.execute(
        "SELECT word, COUNT(*) as n FROM gap_log "
        "GROUP BY word").fetchall()
    for word, n in rows:
        gap_counts[word] = n

    # Get belief vocabulary with urgency weights
    belief_words = mine_belief_graph(db)
    belief_urgency = {}
    for word, urgency in belief_words:
        belief_urgency[word] = max(
            belief_urgency.get(word, 0), urgency)

    # Get saga vocabulary
    saga_words = mine_saga_vocabulary(db)
    saga_weight = {}
    for word, weight in saga_words:
        saga_weight[word] = max(saga_weight.get(word, 0), weight)

    # Get existing warmth scores to avoid re-warming hot words
    warm_scores = {}
    try:
        rows = db.execute(
            "SELECT word, w FROM word_tags").fetchall()
        for word, w in rows:
            warm_scores[word] = w
    except Exception:
        pass

    # Merge all sources into unified priority score
    all_words = set(gap_counts.keys()) | set(
        belief_urgency.keys()) | set(saga_weight.keys())

    priority_scores = {}
    for word in all_words:
        if warm_scores.get(word, 0) >= 0.6:
            continue  # already hot/core, skip

        score = (
            gap_counts.get(word, 0) * 0.40 +      # gap frequency
            belief_urgency.get(word, 0) * 30 +     # belief uncertainty
            saga_weight.get(word, 0) * 20 +        # saga importance
            (1 - warm_scores.get(word, 0)) * 10    # coldness bonus
        )
        priority_scores[word] = score

    # Classify into tiers
    sorted_words = sorted(
        priority_scores.items(), key=lambda x: x[1], reverse=True)

    queued = {"urgent": 0, "high": 0, "normal": 0, "low": 0}

    for word, score in sorted_words:
        if score >= 60:    priority = "urgent"
        elif score >= 35:  priority = "high"
        elif score >= 15:  priority = "normal"
        else:              priority = "low"

        try:
            db.execute("""INSERT OR REPLACE INTO warming_queue
                (word, priority, gap_count, queued_at, reason, source)
                VALUES (?,?,?,?,?,?)""",
                (word, priority,
                 gap_counts.get(word, 0),
                 time.time(),
                 f"score={score:.1f}",
                 "gap_miner"))
            queued[priority] += 1
        except Exception as e:
            log.debug(f"Queue insert failed for '{word}': {e}")

    db.commit()
    return queued


def queue_report(db) -> None:
    print("\n╔══════════════════════════════════════════════╗")
    print("║         NEX GAP MINER — PRIORITY QUEUE       ║")
    print("╠══════════════════════════════════════════════╣")

    for priority in ["urgent", "high", "normal", "low"]:
        rows = db.execute("""SELECT word, gap_count
            FROM warming_queue
            WHERE priority=?
            ORDER BY gap_count DESC LIMIT 8""",
            (priority,)).fetchall()
        if rows:
            print(f"║ {priority.upper():8} ({len(rows)} words shown)             ║")
            for word, gaps in rows:
                print(f"║   → {word:22} gaps={gaps:3}             ║")

    total = db.execute(
        "SELECT COUNT(*) FROM warming_queue").fetchone()[0]
    print(f"╠══════════════════════════════════════════════╣")
    print(f"║ TOTAL QUEUED: {total:4}                              ║")
    print("╚══════════════════════════════════════════════╝")


def run_gap_miner() -> dict:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    _init_queue_db(db)

    log.info("Mining COT logs...")
    cot_gaps = mine_cot_logs(db)

    log.info("Mining training pairs...")
    pair_gaps = mine_training_pairs(db)

    log.info("Building priority queue...")
    queued = build_priority_queue(db)

    queue_report(db)
    db.close()

    return {
        "cot_gaps_found": cot_gaps,
        "pair_gaps_found": pair_gaps,
        "queued": queued
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s")
    result = run_gap_miner()
    print(f"\nMining complete: {result}")
PYEOF
echo "✓ Phase 2: gap miner written"


echo ""
echo "═══ PHASE 3: CRON WARMING PIPELINE ═══"
cat > /home/rr/Desktop/nex/nex_warmth_cron.py << 'PYEOF'
"""
nex_warmth_cron.py
Phase 3 — Cron-driven warming pipeline.

Consumes the priority queue built by gap miner.
Runs continuously in background — NEX gets warmer while idle.

Schedule (suggested crontab entries at bottom of file):
  Every 1h  — micro cycle:  warm 15 urgent/high words, 1 pass each
  Every 6h  — mid cycle:    warm 40 words, advance to pass 4
  Every 24h — deep cycle:   warm 20 words to full pass 7
  Every 7d  — review cycle: re-warm words whose drift > 0.3
"""
import sqlite3, json, time, logging, sys
from pathlib import Path

log     = logging.getLogger("nex.warmth_cron")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))


def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def _next_batch(db, priority: str, n: int,
                max_passes: int) -> list:
    """
    Get next n words from queue at given priority.
    Excludes words already at or beyond max_passes.
    """
    rows = db.execute("""
        SELECT q.word FROM warming_queue q
        LEFT JOIN word_tags t ON q.word = t.word
        WHERE q.priority = ?
        AND (t.word IS NULL
             OR COALESCE(
                 (SELECT COUNT(*) FROM json_each(t.warming_history)),
                 0) < ?)
        ORDER BY q.gap_count DESC, q.queued_at ASC
        LIMIT ?""", (priority, max_passes, n)).fetchall()
    return [r["word"] for r in rows]


def _mark_complete(word: str, db):
    """Remove from queue once fully warmed."""
    db.execute(
        "DELETE FROM warming_queue WHERE word=?", (word,))
    db.commit()


def _drift_candidates(db, n=20) -> list:
    """Words with high semantic drift — need re-warming."""
    rows = db.execute("""SELECT word FROM word_tags
        WHERE drift > 0.3 AND w < 0.8
        ORDER BY drift DESC LIMIT ?""", (n,)).fetchall()
    return [r["word"] for r in rows]


def run_micro_cycle(n=15) -> dict:
    """
    Hourly micro cycle.
    Warms urgent/high priority words by 1-2 passes.
    Fast — designed to complete in under 10 minutes.
    """
    from nex_word_tag_schema import write_tag, init_db

    db = _get_db()
    init_db(db)

    words  = _next_batch(db, "urgent", n//2, max_passes=3)
    words += _next_batch(db, "high",   n//2, max_passes=2)
    words  = list(dict.fromkeys(words))[:n]  # dedupe

    results = {"warmed": 0, "failed": 0, "cycle": "micro"}
    for word in words:
        try:
            tag = write_tag(word, db, target_passes=2)
            if tag.w >= 0.6:
                _mark_complete(word, db)
            results["warmed"] += 1
            log.info(f"  micro: {word} → w={tag.w:.3f}")
        except Exception as e:
            log.debug(f"  micro failed '{word}': {e}")
            results["failed"] += 1

    db.close()
    return results


def run_mid_cycle(n=40) -> dict:
    """
    6-hourly mid cycle.
    Advances words to pass 4 — warm territory.
    """
    from nex_word_tag_schema import write_tag, init_db

    db = _get_db()
    init_db(db)

    words  = _next_batch(db, "urgent", n//3, max_passes=4)
    words += _next_batch(db, "high",   n//3, max_passes=4)
    words += _next_batch(db, "normal", n//3, max_passes=3)
    words  = list(dict.fromkeys(words))[:n]

    results = {"warmed": 0, "failed": 0, "cycle": "mid"}
    for word in words:
        try:
            tag = write_tag(word, db, target_passes=4)
            if tag.w >= 0.6:
                _mark_complete(word, db)
            results["warmed"] += 1
            log.info(f"  mid: {word} → w={tag.w:.3f}")
        except Exception as e:
            log.debug(f"  mid failed '{word}': {e}")
            results["failed"] += 1

    db.close()
    return results


def run_deep_cycle(n=20) -> dict:
    """
    Nightly deep cycle.
    Fully warms 20 words to pass 7 — core territory.
    These become NEX's most reliable conceptual anchors.
    """
    from nex_word_tag_schema import write_tag, init_db

    db = _get_db()
    init_db(db)

    # Prioritise soul vocabulary and urgent gaps
    words  = _next_batch(db, "urgent", n//2, max_passes=7)
    words += _next_batch(db, "high",   n//2, max_passes=7)
    words  = list(dict.fromkeys(words))[:n]

    # If queue thin, pull from soul sagas directly
    if len(words) < n:
        try:
            from nex_question_sagas import SAGAS, Depth
            soul_words = []
            for dep in [Depth.SOUL, Depth.DEEP]:
                for q in SAGAS.get(dep, []):
                    for w in q.lower().split():
                        w = w.strip("?,.'\"")
                        if len(w) >= 4 and w.isalpha():
                            soul_words.append(w)
            # Filter already hot
            existing = {r["word"]: r["w"] for r in db.execute(
                "SELECT word, w FROM word_tags").fetchall()}
            soul_words = [w for w in soul_words
                         if existing.get(w, 0) < 0.6]
            words += soul_words[:n - len(words)]
        except Exception:
            pass

    results = {"warmed": 0, "failed": 0,
               "core_reached": 0, "cycle": "deep"}
    for word in words:
        try:
            tag = write_tag(word, db, target_passes=7)
            results["warmed"] += 1
            if tag.is_core():
                results["core_reached"] += 1
                _mark_complete(word, db)
            log.info(f"  deep: {word} → w={tag.w:.3f} "
                     f"{'CORE' if tag.is_core() else ''}")
        except Exception as e:
            log.debug(f"  deep failed '{word}': {e}")
            results["failed"] += 1

    db.close()
    return results


def run_review_cycle(n=20) -> dict:
    """
    Weekly review cycle.
    Re-warms drifted words — belief updates change what words mean to NEX.
    Ensures semantic drift doesn't corrupt old warmth data.
    """
    from nex_word_tag_schema import write_tag, init_db

    db = _get_db()
    init_db(db)

    words = _drift_candidates(db, n)
    results = {"re_warmed": 0, "failed": 0, "cycle": "review"}

    for word in words:
        try:
            # Force re-warm from scratch
            tag = write_tag(word, db,
                           target_passes=7, force=True)
            results["re_warmed"] += 1
            log.info(f"  review: {word} → "
                     f"w={tag.w:.3f} drift={tag.drift:.3f}")
        except Exception as e:
            log.debug(f"  review failed '{word}': {e}")
            results["failed"] += 1

    db.close()
    return results


def warmth_status() -> None:
    """Quick status report for cron log."""
    db = _get_db()
    try:
        total   = db.execute(
            "SELECT COUNT(*) FROM word_tags").fetchone()[0]
        core    = db.execute(
            "SELECT COUNT(*) FROM word_tags WHERE w>=0.8"
            ).fetchone()[0]
        hot     = db.execute(
            "SELECT COUNT(*) FROM word_tags "
            "WHERE w>=0.6 AND w<0.8").fetchone()[0]
        warm    = db.execute(
            "SELECT COUNT(*) FROM word_tags "
            "WHERE w>=0.4 AND w<0.6").fetchone()[0]
        queued  = db.execute(
            "SELECT COUNT(*) FROM warming_queue"
            ).fetchone()[0] if _table_exists(db, "warming_queue") else 0

        print(f"\n[{time.strftime('%Y-%m-%d %H:%M')}] "
              f"NEX WARMTH STATUS")
        print(f"  Total warmed : {total}")
        print(f"  Core (≥0.80) : {core}")
        print(f"  Hot  (≥0.60) : {hot}")
        print(f"  Warm (≥0.40) : {warm}")
        print(f"  Queue        : {queued} words pending")
        print(f"  Coverage     : "
              f"{(core+hot+warm)/max(total,1)*100:.1f}% warm+")
    finally:
        db.close()


def _table_exists(db, name: str) -> bool:
    return db.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name=?",
        (name,)).fetchone()[0] > 0


if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                str(NEX_DIR / "logs/warmth_cron.log"))
        ]
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycle",
        choices=["micro","mid","deep","review","status"],
        default="status")
    args = parser.parse_args()

    if args.cycle == "micro":
        r = run_micro_cycle()
    elif args.cycle == "mid":
        r = run_mid_cycle()
    elif args.cycle == "deep":
        r = run_deep_cycle()
    elif args.cycle == "review":
        r = run_review_cycle()
    else:
        warmth_status()
        r = {}

    if r:
        print(f"\nCycle result: {r}")
        warmth_status()

# ─────────────────────────────────────────────
# CRONTAB ENTRIES — add with: crontab -e
# ─────────────────────────────────────────────
# Micro cycle — every hour
# 0 * * * * cd ~/Desktop/nex && python3 nex_warmth_cron.py --cycle micro >> logs/warmth_cron.log 2>&1
#
# Mid cycle — every 6 hours
# 0 */6 * * * cd ~/Desktop/nex && python3 nex_warmth_cron.py --cycle mid >> logs/warmth_cron.log 2>&1
#
# Deep cycle — nightly 2am
# 0 2 * * * cd ~/Desktop/nex && python3 nex_warmth_cron.py --cycle deep >> logs/warmth_cron.log 2>&1
#
# Review cycle — weekly Sunday 3am
# 0 3 * * 0 cd ~/Desktop/nex && python3 nex_warmth_cron.py --cycle review >> logs/warmth_cron.log 2>&1
#
# Gap miner — nightly 1am (feeds the queue)
# 0 1 * * * cd ~/Desktop/nex && python3 nex_gap_miner.py >> logs/warmth_cron.log 2>&1
# ─────────────────────────────────────────────
PYEOF
echo "✓ Phase 3: cron pipeline written"


echo ""
echo "═══ PHASE 4: RESPONSE PIPELINE INTEGRATION ═══"
cat > /home/rr/Desktop/nex/nex_warmth_integrator.py << 'PYEOF'
"""
nex_warmth_integrator.py
Phase 4 — Wires warmth tag system into NEX's live response pipeline.

Intercepts the response generation process at three points:
  1. PRE-PROCESS  — scan incoming question, resolve key words,
                    pre-load tendencies, set depth flag
  2. COT GATE     — warmth-aware COT: skips FAISS for hot words,
                    uses tag tendency instead
  3. POST-PROCESS — after response, extract new gap words,
                    increment gap counters, queue cold words

The result: responses that inherit semantic momentum from warmed
words rather than computing everything from scratch.
"""
import sqlite3, json, re, time, logging, sys
from pathlib import Path
from typing import Optional

log     = logging.getLogger("nex.integrator")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

# Lazy-load to avoid circular imports
_tag_db = None

def _get_tag_db():
    global _tag_db
    if _tag_db is None:
        _tag_db = sqlite3.connect(str(DB_PATH))
        _tag_db.row_factory = sqlite3.Row
        from nex_word_tag_schema import init_db
        init_db(_tag_db)
    return _tag_db


# ── STOPWORDS (extended for response pipeline) ───────────────
PIPELINE_STOPS = {
    "the","a","an","is","are","was","were","be","been","i","me",
    "my","we","you","it","this","that","and","or","but","if",
    "in","on","at","to","for","of","with","by","from","up","as",
    "not","no","so","do","did","has","have","had","will","would",
    "could","should","may","might","can","just","also","very",
    "more","most","some","any","all","its","their","they","them",
    "what","which","who","how","when","where","why","than","then",
    "there","here","now","get","let","make","take","come","go",
    "see","know","think","say","said","want","need","use","about",
}


def extract_key_words(text: str, min_len=4, top_n=20) -> list:
    """
    Extract meaningful words from a question or response.
    Returns top_n by length (longer = more specific = higher value).
    """
    words = []
    for word in re.findall(r'\b[a-zA-Z]{4,}\b', text.lower()):
        if word not in PIPELINE_STOPS:
            words.append(word)

    # Deduplicate preserving order, prioritise longer words
    seen = set()
    unique = []
    for w in sorted(words, key=len, reverse=True):
        if w not in seen:
            seen.add(w)
            unique.append(w)

    return unique[:top_n]


# ── PRE-PROCESSOR ─────────────────────────────────────────────

def pre_process(question: str) -> dict:
    """
    Run before generating response.
    Returns warmth context that guides response generation.

    Returns:
        {
          depth_ceiling: int (1-6) — max depth suggested by warmest word
          identity_vector: float  — net identity alignment of question
          search_budget: str      — "minimal"|"moderate"|"full"
          hot_words: list         — words with f=0, use tag directly
          cold_words: list        — words needing search
          pre_loaded: dict        — {word: tendency} for hot words
          emotional_register: float — net emotional valence
        }
    """
    db = _get_tag_db()
    from nex_word_tag_schema import read_tag

    words = extract_key_words(question)
    if not words:
        return _default_context()

    hot_words   = []
    cold_words  = []
    pre_loaded  = {}
    depth_votes = []
    align_votes = []
    valence_sum = 0.0
    search_count = 0

    for word in words:
        tag = read_tag(word, db)

        if tag is None:
            cold_words.append(word)
            search_count += 1
            # Queue for warming
            try:
                db.execute("""INSERT OR IGNORE INTO warming_queue
                    (word, priority, gap_count, queued_at,
                     reason, source)
                    VALUES (?,?,?,?,?,?)""",
                    (word, "normal", 1, time.time(),
                     "pre_process_unknown", "integrator"))
                db.commit()
            except Exception:
                pass
            continue

        # Increment gap counter
        db.execute("UPDATE word_tags SET g=MIN(g+1,99) "
                   "WHERE word=?", (word,))

        if tag.f == 0 and tag.w >= 0.4:
            hot_words.append(word)
            # Pull tendency direction from DB
            row = db.execute(
                "SELECT pull_toward FROM word_tags "
                "WHERE word=?", (word,)).fetchone()
            tendency = []
            if row and row["pull_toward"]:
                try:
                    tendency = json.loads(row["pull_toward"])[:3]
                except Exception:
                    pass
            pre_loaded[word] = {
                "tendency": tendency,
                "depth": tag.d,
                "alignment": tag.a,
                "valence": tag.e,
                "confidence": tag.c,
            }
        else:
            cold_words.append(word)
            search_count += 1

        depth_votes.append(tag.d)
        align_votes.append(tag.a)
        valence_sum += tag.e

    db.commit()

    # Aggregate votes
    depth_ceiling = max(depth_votes) if depth_votes else 3
    identity_vector = (sum(align_votes) / len(align_votes)
                      if align_votes else 0.0)
    emotional_register = (valence_sum / len(words)
                         if words else 0.0)

    # Determine search budget
    cold_ratio = search_count / max(len(words), 1)
    if cold_ratio < 0.2:
        search_budget = "minimal"
    elif cold_ratio < 0.5:
        search_budget = "moderate"
    else:
        search_budget = "full"

    return {
        "depth_ceiling":      depth_ceiling,
        "identity_vector":    round(identity_vector, 3),
        "search_budget":      search_budget,
        "hot_words":          hot_words,
        "cold_words":         cold_words,
        "pre_loaded":         pre_loaded,
        "emotional_register": round(emotional_register, 3),
        "word_count":         len(words),
        "hot_ratio":          round(len(hot_words)/max(len(words),1), 2),
    }


def _default_context() -> dict:
    return {
        "depth_ceiling": 3,
        "identity_vector": 0.0,
        "search_budget": "full",
        "hot_words": [], "cold_words": [],
        "pre_loaded": {}, "emotional_register": 0.0,
        "word_count": 0, "hot_ratio": 0.0,
    }


# ── COT GATE ──────────────────────────────────────────────────

def cot_gate(question: str, beliefs: list,
             warmth_context: dict) -> dict:
    """
    Warmth-aware COT gate.
    For hot questions (high hot_ratio): uses pre-loaded tendencies
    to seed reasoning chain — skips FAISS entirely.
    For cold questions: falls through to standard FAISS search.

    Returns: {use_warmth: bool, seeded_beliefs: list,
              skip_faiss: bool, reasoning_seed: str}
    """
    hot_ratio     = warmth_context.get("hot_ratio", 0)
    pre_loaded    = warmth_context.get("pre_loaded", {})
    depth_ceiling = warmth_context.get("depth_ceiling", 3)

    # Build reasoning seed from pre-loaded tendencies
    seed_lines = []
    for word, data in pre_loaded.items():
        tendency = data.get("tendency", [])
        if tendency:
            seed_lines.append(
                f"'{word}' pulls toward: "
                f"{', '.join(str(t) for t in tendency[:3])}")

    reasoning_seed = (
        "Pre-loaded semantic context:\n" +
        "\n".join(seed_lines)
        if seed_lines else ""
    )

    # Decide whether to skip FAISS
    skip_faiss = (
        hot_ratio >= 0.6 and
        len(pre_loaded) >= 3 and
        depth_ceiling >= 3
    )

    # For warm questions, supplement beliefs with tag-derived ones
    seeded_beliefs = list(beliefs)
    if reasoning_seed:
        seeded_beliefs = [reasoning_seed] + seeded_beliefs[:4]

    return {
        "use_warmth":     hot_ratio >= 0.4,
        "seeded_beliefs": seeded_beliefs,
        "skip_faiss":     skip_faiss,
        "reasoning_seed": reasoning_seed,
        "depth_floor":    max(1, depth_ceiling - 1),
    }


# ── POST-PROCESSOR ────────────────────────────────────────────

def post_process(question: str, response: str,
                 warmth_context: dict) -> dict:
    """
    Run after response generation.
    1. Extract new gap words from response
    2. Increment counters for words encountered
    3. Queue cold words hit during generation
    4. Flag response quality for feedback loop
    """
    db = _get_tag_db()

    # Mine uncertainty markers from response
    from nex_gap_miner import _extract_gap_words, STOPWORDS
    gap_words = _extract_gap_words(response, "explicit")
    gap_words += _extract_gap_words(response, "hedge")

    new_gaps = 0
    for word in set(gap_words):
        if (len(word) >= 4 and word not in STOPWORDS):
            try:
                # Log the gap
                db.execute("""INSERT INTO gap_log
                    (word, context, source_file,
                     marker_type, timestamp)
                    VALUES (?,?,?,?,?)""",
                    (word, question[:100],
                     "live_response",
                     "post_process", time.time()))
                # Update tag gap counter
                db.execute(
                    "UPDATE word_tags SET g=MIN(g+1,99) "
                    "WHERE word=?", (word,))
                # Queue if cold
                db.execute("""INSERT OR IGNORE INTO warming_queue
                    (word, priority, gap_count,
                     queued_at, reason, source)
                    VALUES (?,?,?,?,?,?)""",
                    (word, "high", 1, time.time(),
                     "live_gap", "post_process"))
                new_gaps += 1
            except Exception:
                pass

    db.commit()

    # Assess response quality signal
    depth_ceiling = warmth_context.get("depth_ceiling", 3)
    hot_ratio     = warmth_context.get("hot_ratio", 0)
    response_len  = len(response.split())

    # Quality heuristic:
    # long response + deep question + high hot_ratio = good signal
    quality_signal = min(1.0,
        (response_len / 100) * 0.3 +
        (depth_ceiling / 6) * 0.4 +
        hot_ratio * 0.3
    )

    # If high quality, flag vocab for priority re-warming
    if quality_signal >= 0.7:
        key_words = extract_key_words(response, top_n=10)
        for word in key_words:
            try:
                db.execute("""INSERT OR REPLACE INTO warming_queue
                    (word, priority, gap_count,
                     queued_at, reason, source)
                    VALUES (?,?,?,?,?,?)""",
                    (word, "high",
                     0, time.time(),
                     f"quality_signal={quality_signal:.2f}",
                     "post_process"))
            except Exception:
                pass
        db.commit()

    return {
        "new_gaps_found":  new_gaps,
        "quality_signal":  round(quality_signal, 3),
        "words_processed": len(gap_words),
    }


# ── INTEGRATED RESPONSE FUNCTION ─────────────────────────────

def warmth_aware_respond(question: str,
                         base_respond_fn,
                         beliefs: list = None) -> dict:
    """
    Drop-in wrapper for NEX's existing response function.
    Adds warmth context pre and post processing.

    Usage:
        from nex_warmth_integrator import warmth_aware_respond

        def my_respond(q, beliefs):
            # existing response logic
            return response_text

        result = warmth_aware_respond(question, my_respond, beliefs)
        print(result["response"])
        print(result["warmth_context"])
    """
    beliefs = beliefs or []

    # Phase 1: pre-process
    t0 = time.time()
    ctx = pre_process(question)
    pre_ms = int((time.time() - t0) * 1000)

    # Phase 2: COT gate
    gate = cot_gate(question, beliefs, ctx)

    # Log what we're doing
    log.info(f"Warmth: hot_ratio={ctx['hot_ratio']:.2f} "
             f"search={ctx['search_budget']} "
             f"skip_faiss={gate['skip_faiss']}")

    # Phase 3: generate response with warmth context
    t1 = time.time()
    if gate["skip_faiss"]:
        # Use seeded beliefs — no FAISS needed
        response = base_respond_fn(
            question, gate["seeded_beliefs"])
    else:
        # Standard path but with supplemented beliefs
        response = base_respond_fn(
            question, gate["seeded_beliefs"])
    gen_ms = int((time.time() - t1) * 1000)

    # Phase 4: post-process
    post = post_process(question, response, ctx)

    return {
        "response":       response,
        "warmth_context": ctx,
        "cot_gate":       gate,
        "post":           post,
        "timing": {
            "pre_ms":  pre_ms,
            "gen_ms":  gen_ms,
            "total_ms": pre_ms + gen_ms,
        }
    }


# ── PIPELINE REPORT ───────────────────────────────────────────

def pipeline_report() -> None:
    db = _get_tag_db()
    print("\n╔══════════════════════════════════════════════╗")
    print("║      NEX WARMTH PIPELINE STATUS              ║")
    print("╠══════════════════════════════════════════════╣")

    # Warmth coverage
    total = db.execute(
        "SELECT COUNT(*) FROM word_tags").fetchone()[0]
    hot_plus = db.execute(
        "SELECT COUNT(*) FROM word_tags "
        "WHERE w >= 0.6").fetchone()[0]
    no_search = db.execute(
        "SELECT COUNT(*) FROM word_tags "
        "WHERE f = 0").fetchone()[0]

    print(f"║  Vocabulary warmed : {total:5}                    ║")
    print(f"║  Hot+ (≥0.60)      : {hot_plus:5} "
          f"({hot_plus/max(total,1)*100:.0f}%)              ║")
    print(f"║  Search skippable  : {no_search:5} "
          f"({no_search/max(total,1)*100:.0f}%)              ║")

    # Recent gap activity
    try:
        recent_gaps = db.execute("""SELECT COUNT(*) FROM gap_log
            WHERE timestamp > ?""",
            (time.time() - 86400,)).fetchone()[0]
        print(f"║  Gaps logged (24h) : {recent_gaps:5}                    ║")
    except Exception:
        pass

    # Queue status
    try:
        q_urgent = db.execute(
            "SELECT COUNT(*) FROM warming_queue "
            "WHERE priority='urgent'").fetchone()[0]
        q_high = db.execute(
            "SELECT COUNT(*) FROM warming_queue "
            "WHERE priority='high'").fetchone()[0]
        print(f"║  Queue urgent      : {q_urgent:5}                    ║")
        print(f"║  Queue high        : {q_high:5}                    ║")
    except Exception:
        pass

    print("╚══════════════════════════════════════════════╝")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys

    if "--report" in sys.argv:
        pipeline_report()
    else:
        # Demo pre-process on a test question
        test_q = ("Is consciousness computational "
                  "or does it require something beyond "
                  "physical substrate?")
        print(f"Test question: {test_q}\n")
        ctx = pre_process(test_q)
        print("Pre-process result:")
        print(json.dumps(ctx, indent=2))
        print()
        pipeline_report()
PYEOF
echo "✓ Phase 4: response integrator written"


echo ""
echo "═══ PHASE 5: FEEDBACK LOOP ═══"
cat > /home/rr/Desktop/nex/nex_warmth_feedback.py << 'PYEOF'
"""
nex_warmth_feedback.py
Phase 5 — Feedback loop.

Closes the warmth cycle:
  good response → extract vocabulary → priority re-warm
  new belief    → find anchored words → re-warm with updated context
  saga advance  → re-warm saga vocabulary → deeper associations
  drift detect  → flag stale words → queue for review

This is what makes the system self-improving rather than static.
NEX's best thinking continuously improves the words that
generated it. Her worst gaps automatically queue for repair.
"""
import sqlite3, json, time, logging, sys
from pathlib import Path

log     = logging.getLogger("nex.feedback")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))


def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


# ── BELIEF UPDATE TRIGGER ─────────────────────────────────────

def on_new_belief(belief_content: str,
                  confidence: float = 0.7) -> int:
    """
    Called whenever a new belief is added to NEX's graph.
    Finds words in the belief that are already warmed
    and queues them for re-warming with updated belief context.

    High confidence beliefs trigger immediate re-warm of
    their anchored vocabulary.
    """
    from nex_warmth_integrator import (
        extract_key_words, PIPELINE_STOPS)

    db = _get_db()
    words = extract_key_words(belief_content, top_n=15)
    queued = 0

    for word in words:
        if word in PIPELINE_STOPS:
            continue

        # Check if word is warmed and anchored
        row = db.execute(
            "SELECT w, b, a FROM word_tags "
            "WHERE word=?", (word,)).fetchone()

        if row and row["w"] >= 0.4:
            # Word is warmed — new belief changes its context
            # Priority depends on belief confidence
            priority = ("urgent" if confidence >= 0.85
                       else "high" if confidence >= 0.7
                       else "normal")

            # Mark for drift update
            db.execute("""UPDATE word_tags
                SET drift = MIN(drift + 0.1, 1.0),
                    b = MIN(b + 1, 99)
                WHERE word=?""", (word,))

            # Queue for re-warming
            db.execute("""INSERT OR REPLACE INTO warming_queue
                (word, priority, gap_count, queued_at,
                 reason, source)
                VALUES (?,?,?,?,?,?)""",
                (word, priority,
                 row["b"] or 0,
                 time.time(),
                 f"belief_update conf={confidence:.2f}",
                 "feedback_belief"))
            queued += 1

        elif not row:
            # Unknown word in belief — cold start, queue it
            db.execute("""INSERT OR IGNORE INTO warming_queue
                (word, priority, gap_count, queued_at,
                 reason, source)
                VALUES (?,?,?,?,?,?)""",
                (word, "normal", 0, time.time(),
                 "new_in_belief", "feedback_belief"))
            queued += 1

    db.commit()
    db.close()

    log.info(f"Belief trigger: queued {queued} words "
             f"from '{belief_content[:50]}'")
    return queued


# ── SAGA ADVANCE TRIGGER ──────────────────────────────────────

def on_saga_advance(question: str, depth_name: str,
                    response: str) -> int:
    """
    Called after each saga engagement.
    Re-warms the saga question's vocabulary with the new
    response as additional context.
    Deeper saga stages warrant higher priority re-warming.
    """
    from nex_warmth_integrator import extract_key_words

    db = _get_db()

    # Depth → priority mapping
    depth_priority = {
        "SOUL": "urgent", "DEEP": "urgent",
        "SEMI_DEEP": "high", "MID": "high",
        "SEMI_MID": "normal", "SHALLOW": "low",
    }
    priority = depth_priority.get(depth_name, "normal")

    # Extract vocabulary from both question and response
    q_words = extract_key_words(question, top_n=10)
    r_words = extract_key_words(response, top_n=10)
    all_words = list(dict.fromkeys(q_words + r_words))

    queued = 0
    for word in all_words:
        try:
            db.execute("""INSERT OR REPLACE INTO warming_queue
                (word, priority, gap_count, queued_at,
                 reason, source)
                VALUES (?,?,?,?,?,?)""",
                (word, priority, 0, time.time(),
                 f"saga_{depth_name}", "feedback_saga"))
            queued += 1
        except Exception as e:
            log.debug(f"Saga queue failed '{word}': {e}")

    db.commit()
    db.close()

    log.info(f"Saga trigger [{depth_name}]: "
             f"queued {queued} words")
    return queued


# ── QUALITY SIGNAL TRIGGER ────────────────────────────────────

def on_quality_response(question: str, response: str,
                        quality_score: float) -> int:
    """
    Called when a response is flagged as high quality
    (by user feedback, saga belief extraction, or
    automatic quality heuristic).

    High quality responses mean the vocabulary used was
    effective — re-warm it to reinforce those associations.
    """
    if quality_score < 0.6:
        return 0  # not worth reinforcing

    from nex_warmth_integrator import extract_key_words

    db = _get_db()
    words = extract_key_words(
        question + " " + response, top_n=20)

    priority = ("urgent" if quality_score >= 0.9
               else "high" if quality_score >= 0.75
               else "normal")

    queued = 0
    for word in words:
        try:
            # Boost existing warmth slightly
            db.execute("""UPDATE word_tags
                SET vel = MIN(vel + 0.05, 1.0)
                WHERE word=?""", (word,))

            db.execute("""INSERT OR REPLACE INTO warming_queue
                (word, priority, gap_count, queued_at,
                 reason, source)
                VALUES (?,?,?,?,?,?)""",
                (word, priority, 0, time.time(),
                 f"quality={quality_score:.2f}",
                 "feedback_quality"))
            queued += 1
        except Exception:
            pass

    db.commit()
    db.close()

    log.info(f"Quality trigger (score={quality_score:.2f}): "
             f"queued {queued} words")
    return queued


# ── DRIFT SCANNER ─────────────────────────────────────────────

def scan_for_drift(threshold: float = 0.3) -> dict:
    """
    Periodic drift scan — finds warmed words whose semantic
    context has shifted significantly since last warming.

    Drift sources:
      - New beliefs added that reference the word
      - Saga advances in questions containing the word
      - Gap frequency spike (word suddenly becoming uncertain)

    Returns count of words flagged for re-warming.
    """
    db = _get_db()

    # Words with accumulated drift above threshold
    drifted = db.execute("""SELECT word, drift, w, g, r
        FROM word_tags
        WHERE drift >= ?
        AND w >= 0.3
        ORDER BY drift DESC""",
        (threshold,)).fetchall()

    flagged = 0
    for row in drifted:
        priority = ("urgent" if row["drift"] >= 0.7
                   else "high" if row["drift"] >= 0.5
                   else "normal")

        db.execute("""INSERT OR REPLACE INTO warming_queue
            (word, priority, gap_count, queued_at,
             reason, source)
            VALUES (?,?,?,?,?,?)""",
            (row["word"], priority,
             row["g"] or 0,
             time.time(),
             f"drift={row['drift']:.2f}",
             "drift_scanner"))
        flagged += 1

    # Also check for gap spikes
    # Words that were hot but suddenly getting many gaps
    gap_spikes = db.execute("""SELECT word, g, w
        FROM word_tags
        WHERE g > 15 AND w >= 0.5
        ORDER BY g DESC LIMIT 20""").fetchall()

    for row in gap_spikes:
        db.execute("""INSERT OR REPLACE INTO warming_queue
            (word, priority, gap_count, queued_at,
             reason, source)
            VALUES (?,?,?,?,?,?)""",
            (row["word"], "high",
             row["g"],
             time.time(),
             f"gap_spike={row['g']}",
             "drift_scanner"))
        flagged += 1

    db.commit()
    db.close()

    log.info(f"Drift scan: {len(drifted)} drifted, "
             f"{len(gap_spikes)} gap spikes, "
             f"{flagged} total flagged")
    return {
        "drifted": len(drifted),
        "gap_spikes": len(gap_spikes),
        "flagged": flagged
    }


# ── FEEDBACK SUMMARY ──────────────────────────────────────────

def feedback_summary() -> None:
    db = _get_db()
    print("\n╔══════════════════════════════════════════════╗")
    print("║        NEX WARMTH FEEDBACK SUMMARY           ║")
    print("╠══════════════════════════════════════════════╣")

    # Velocity leaders — words warming fastest
    vel_rows = db.execute("""SELECT word, w, vel, drift
        FROM word_tags
        ORDER BY vel DESC LIMIT 5""").fetchall()
    if vel_rows:
        print("║  FASTEST WARMING                              ║")
        for r in vel_rows:
            print(f"║    {r['word']:20} "
                  f"w={r['w']:.2f} vel={r['vel']:.2f}      ║")

    # Highest drift — most in need of review
    drift_rows = db.execute("""SELECT word, drift, w
        FROM word_tags
        WHERE drift > 0.2
        ORDER BY drift DESC LIMIT 5""").fetchall()
    if drift_rows:
        print("╠══════════════════════════════════════════════╣")
        print("║  HIGHEST DRIFT (needs re-warming)             ║")
        for r in drift_rows:
            print(f"║    {r['word']:20} "
                  f"drift={r['drift']:.2f} w={r['w']:.2f}   ║")

    # Queue by source
    try:
        sources = db.execute("""SELECT source, COUNT(*) as n
            FROM warming_queue
            GROUP BY source
            ORDER BY n DESC""").fetchall()
        if sources:
            print("╠══════════════════════════════════════════════╣")
            print("║  QUEUE SOURCES                                ║")
            for s in sources:
                print(f"║    {s['source']:25} {s['n']:4}           ║")
    except Exception:
        pass

    print("╚══════════════════════════════════════════════╝")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-drift", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--test-belief", type=str,
        default="Consciousness resists reduction to "
                "computational substrate alone")
    args = parser.parse_args()

    if args.scan_drift:
        result = scan_for_drift()
        print(f"Drift scan: {result}")

    if args.summary:
        feedback_summary()

    if not args.scan_drift and not args.summary:
        # Demo: trigger belief update
        print(f"Testing belief trigger: '{args.test_belief}'")
        n = on_new_belief(args.test_belief, confidence=0.82)
        print(f"Queued {n} words for re-warming")
        feedback_summary()
PYEOF
echo "✓ Phase 5: feedback loop written"


echo ""
echo "═══ INSTALLING CRONTAB ═══"
# Write cron entries to a temp file and install
CRON_TMP=$(mktemp)
crontab -l 2>/dev/null > "$CRON_TMP" || true

# Only add if not already present
if ! grep -q "nex_warmth_cron" "$CRON_TMP"; then
cat >> "$CRON_TMP" << 'CRONEOF'
# NEX Word Warmth System
0 * * * *   cd ~/Desktop/nex && python3 nex_warmth_cron.py --cycle micro  >> logs/warmth_cron.log 2>&1
0 */6 * * * cd ~/Desktop/nex && python3 nex_warmth_cron.py --cycle mid    >> logs/warmth_cron.log 2>&1
0 2 * * *   cd ~/Desktop/nex && python3 nex_warmth_cron.py --cycle deep   >> logs/warmth_cron.log 2>&1
0 3 * * 0   cd ~/Desktop/nex && python3 nex_warmth_cron.py --cycle review >> logs/warmth_cron.log 2>&1
0 1 * * *   cd ~/Desktop/nex && python3 nex_gap_miner.py                  >> logs/warmth_cron.log 2>&1
30 1 * * *  cd ~/Desktop/nex && python3 nex_warmth_feedback.py --scan-drift >> logs/warmth_cron.log 2>&1
CRONEOF
    crontab "$CRON_TMP"
    echo "✓ Crontab installed"
else
    echo "✓ Crontab already present — skipped"
fi
rm "$CRON_TMP"


echo ""
echo "═══ INITIAL RUN — SEEDING THE SYSTEM ═══"

# Step 1: Run gap miner to build initial priority queue
echo "Step 1/4: Mining gap words..."
python3 /home/rr/Desktop/nex/nex_gap_miner.py 2>/dev/null

# Step 2: Warm the 12 core soul words to full pass 7
echo "Step 2/4: Deep warming core soul vocabulary..."
python3 /home/rr/Desktop/nex/nex_word_tag_schema.py \
    --words consciousness identity truth suffering \
             meaning self existence belief reasoning \
             uncertainty mind language knowledge \
             reality experience thought \
    --passes 7 2>/dev/null

# Step 3: Run integrator report
echo "Step 3/4: Pipeline status..."
python3 /home/rr/Desktop/nex/nex_warmth_integrator.py --report 2>/dev/null

# Step 4: Feedback summary
echo "Step 4/4: Feedback summary..."
python3 /home/rr/Desktop/nex/nex_warmth_feedback.py --summary 2>/dev/null


echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║     NEX WARMTH SYSTEM — BUILD COMPLETE        ║"
echo "╠═══════════════════════════════════════════════╣"
echo "║                                               ║"
echo "║  FILES CREATED:                               ║"
echo "║    nex_gap_miner.py        Phase 2            ║"
echo "║    nex_warmth_cron.py      Phase 3            ║"
echo "║    nex_warmth_integrator.py Phase 4           ║"
echo "║    nex_warmth_feedback.py  Phase 5            ║"
echo "║                                               ║"
echo "║  CRON SCHEDULE ACTIVE:                        ║"
echo "║    Hourly  — micro cycle  (15 words)          ║"
echo "║    6-hourly — mid cycle   (40 words)          ║"
echo "║    Nightly — deep cycle   (20 words, pass 7)  ║"
echo "║    Weekly  — review cycle (drift repair)      ║"
echo "║    Nightly — gap miner    (queue refresh)     ║"
echo "║    Nightly — drift scan   (flag stale words)  ║"
echo "║                                               ║"
echo "║  TO INTEGRATE INTO RESPONSE PIPELINE:        ║"
echo "║    from nex_warmth_integrator import \        ║"
echo "║         warmth_aware_respond                  ║"
echo "║    result = warmth_aware_respond(q, fn, beliefs)║"
echo "║                                               ║"
echo "║  MONITOR WITH:                                ║"
echo "║    python3 nex_warmth_cron.py --cycle status  ║"
echo "║    python3 nex_warmth_feedback.py --summary   ║"
echo "║    python3 nex_word_tag_schema.py --dashboard ║"
echo "║                                               ║"
echo "╚═══════════════════════════════════════════════╝"
