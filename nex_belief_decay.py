"""
nex_belief_decay.py
Automatic confidence decay for beliefs over time.
Runs nightly via cron.
"""
import sqlite3, logging, argparse
from pathlib import Path

log     = logging.getLogger("nex.decay")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

DECAY_RATE       = 0.98
MIN_CONFIDENCE   = 0.15
HIGH_CONF_SHIELD = 0.90
SEED_SOURCES     = ['nex_seed_v1','nex_seed_v2','nex_seed_v3','nex_seed_v4']

def run_decay(dry_run=False, verbose=False):
    db = sqlite3.connect(str(DB_PATH))

    rows = db.execute("""
        SELECT id, content, confidence, topic, source
        FROM beliefs
        WHERE locked = 0
        AND confidence > ?
        AND confidence < ?
    """, (MIN_CONFIDENCE, HIGH_CONF_SHIELD)).fetchall()

    decayed = shielded = 0

    for bid, content, conf, topic, source in rows:
        if source in SEED_SOURCES and conf >= 0.7:
            shielded += 1
            continue
        new_conf = round(max(conf * DECAY_RATE, MIN_CONFIDENCE), 4)
        if verbose:
            print(f"  [{topic}] {content[:60]} {conf:.3f} -> {new_conf:.3f}")
        if not dry_run:
            db.execute("UPDATE beliefs SET confidence=? WHERE id=?", (new_conf, bid))
        decayed += 1

    deleted = 0
    if not dry_run:
        placeholders = ','.join('?' * len(SEED_SOURCES))
        result = db.execute(f"""
            DELETE FROM beliefs
            WHERE confidence <= ?
            AND locked = 0
            AND source NOT IN ({placeholders})
        """, [MIN_CONFIDENCE] + SEED_SOURCES)
        deleted = result.rowcount
        db.commit()

    db.close()
    print(f"Decay cycle: decayed={decayed} shielded={shielded} deleted={deleted} dry={dry_run}")
    return {"decayed": decayed, "shielded": shielded, "deleted": deleted}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    run_decay(dry_run=args.dry_run, verbose=args.verbose)
