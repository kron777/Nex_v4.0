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
