"""
nex_belief_calibrator.py
Tracks belief usage in responses and calibrates confidence.
Beliefs that get used frequently and produce good responses -> confidence boost.
Beliefs never used -> gradually decay.
Integrates with nex_belief_decay.py and nex_response_quality.py.
"""
import sqlite3, logging, time
from pathlib import Path

log     = logging.getLogger("nex.calibrator")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

USAGE_BOOST   = 1.02   # multiply conf by this on each quality use
MAX_CONF      = 0.95   # ceiling
MIN_QUALITY   = 0.70   # minimum response quality to count as good use

def _ensure_schema(db):
    """Add use_count and last_used columns if missing."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(beliefs)").fetchall()]
    if "use_count" not in cols:
        db.execute("ALTER TABLE beliefs ADD COLUMN use_count INTEGER DEFAULT 0")
    if "last_used" not in cols:
        db.execute("ALTER TABLE beliefs ADD COLUMN last_used REAL DEFAULT 0")
    db.commit()

def record_usage(belief_ids: list, quality_score: float):
    """Record that these beliefs were used in a response of given quality."""
    if not belief_ids or quality_score < MIN_QUALITY:
        return
    db = sqlite3.connect(str(DB_PATH))
    _ensure_schema(db)
    now = time.time()
    for bid in belief_ids:
        db.execute("""UPDATE beliefs SET
            use_count = COALESCE(use_count, 0) + 1,
            last_used = ?,
            confidence = MIN(?, confidence * ?)
            WHERE id=? AND locked=0""",
            (now, MAX_CONF, USAGE_BOOST, bid))
    db.commit()
    db.close()
    log.debug(f"Recorded usage for {len(belief_ids)} beliefs (quality={quality_score:.2f})")

def calibration_report() -> dict:
    """Report on belief usage statistics."""
    db = sqlite3.connect(str(DB_PATH))
    _ensure_schema(db)

    total = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    used  = db.execute("SELECT COUNT(*) FROM beliefs WHERE COALESCE(use_count,0) > 0").fetchone()[0]
    top   = db.execute("""SELECT content, topic, confidence, COALESCE(use_count,0) as uc
        FROM beliefs ORDER BY uc DESC LIMIT 5""").fetchall()
    never = db.execute("""SELECT COUNT(*) FROM beliefs
        WHERE COALESCE(use_count,0) = 0 AND confidence < 0.6""").fetchone()[0]

    db.close()
    report = {
        "total_beliefs": total,
        "used_beliefs":  used,
        "never_used_low_conf": never,
        "usage_rate": round(used/total, 3) if total else 0,
        "top_used": [{"content": r[0][:60], "topic": r[1],
                      "conf": r[2], "uses": r[3]} for r in top]
    }
    return report

def boost_synthesis_beliefs():
    """Boost beliefs from synthesis/curiosity that have been used."""
    db = sqlite3.connect(str(DB_PATH))
    _ensure_schema(db)
    # Synthesis beliefs that got used get extra boost
    db.execute("""UPDATE beliefs SET confidence = MIN(?, confidence * 1.05)
        WHERE source IN ('nex_synthesis', 'nex_curiosity_answer')
        AND COALESCE(use_count, 0) > 2
        AND locked = 0""", (MAX_CONF,))
    db.commit()
    db.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    report = calibration_report()
    print(f"Total beliefs:    {report['total_beliefs']}")
    print(f"Used beliefs:     {report['used_beliefs']} ({report['usage_rate']*100:.1f}%)")
    print(f"Never used/low:   {report['never_used_low_conf']}")
    print(f"\nTop used beliefs:")
    for b in report["top_used"]:
        print(f"  [{b['uses']} uses] [{b['topic']}] {b['content']}")
