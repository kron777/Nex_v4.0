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
