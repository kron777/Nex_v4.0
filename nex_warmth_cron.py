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
    parser.add_argument("--n", type=int, default=None)
    args = parser.parse_args()

    if args.cycle == "micro":
        r = run_micro_cycle(**({"n": args.n} if args.n else {}))
    elif args.cycle == "mid":
        r = run_mid_cycle(**({"n": args.n} if args.n else {}))
    elif args.cycle == "deep":
        r = run_deep_cycle(**({"n": args.n} if args.n else {}))
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
