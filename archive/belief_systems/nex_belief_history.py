"""
nex_belief_history.py
Tracks belief confidence changes over time.
Creates an intellectual history — how NEX's positions have evolved.
Snapshots taken weekly. Diffs show learning direction.
"""
import sqlite3, json, logging, time
from pathlib import Path

log     = logging.getLogger("nex.history")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

def _init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS belief_snapshots (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL,
        topic     TEXT,
        belief_id INTEGER,
        content   TEXT,
        confidence REAL,
        source    TEXT
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS
        idx_bs_topic ON belief_snapshots(topic, timestamp)""")
    db.commit()

def take_snapshot(topics=None):
    """Snapshot current belief confidences."""
    db = sqlite3.connect(str(DB_PATH))
    _init(db)
    now = time.time()

    q = "SELECT id, content, topic, confidence, source FROM beliefs WHERE confidence >= 0.6"
    if topics:
        q += " AND topic IN ({})".format(','.join('?'*len(topics)))
        rows = db.execute(q, topics).fetchall()
    else:
        rows = db.execute(q).fetchall()

    for bid, content, topic, conf, source in rows:
        db.execute("""INSERT INTO belief_snapshots
            (timestamp, topic, belief_id, content, confidence, source)
            VALUES (?,?,?,?,?,?)""",
            (now, topic, bid, content[:200], conf, source))

    db.commit()
    count = len(rows)
    db.close()
    print(f"Snapshot taken: {count} beliefs at {time.strftime('%Y-%m-%d %H:%M')}")
    return count

def get_drift(topic: str, hours_back=168) -> list:
    """Show beliefs that changed confidence in last N hours."""
    db = sqlite3.connect(str(DB_PATH))
    _init(db)
    cutoff = time.time() - (hours_back * 3600)

    # Get earliest and latest snapshot for each belief
    rows = db.execute("""
        SELECT belief_id, content,
               MIN(confidence) as min_conf,
               MAX(confidence) as max_conf,
               MAX(timestamp) - MIN(timestamp) as span
        FROM belief_snapshots
        WHERE topic=? AND timestamp >= ?
        GROUP BY belief_id
        HAVING max_conf - min_conf > 0.05
        ORDER BY (max_conf - min_conf) DESC
        LIMIT 20
    """, (topic, cutoff)).fetchall()

    db.close()
    return [{"id": r[0], "content": r[1][:80],
             "min": round(r[2],3), "max": round(r[3],3),
             "delta": round(r[3]-r[2],3)} for r in rows]

def intellectual_growth_report() -> dict:
    """Summary of belief graph evolution."""
    db = sqlite3.connect(str(DB_PATH))
    _init(db)

    snapshots = db.execute(
        "SELECT COUNT(DISTINCT timestamp) FROM belief_snapshots").fetchone()[0]
    total_tracked = db.execute(
        "SELECT COUNT(DISTINCT belief_id) FROM belief_snapshots").fetchone()[0]
    growing = db.execute("""
        SELECT COUNT(*) FROM (
            SELECT belief_id, MAX(confidence) - MIN(confidence) as delta
            FROM belief_snapshots GROUP BY belief_id HAVING delta > 0.05
        )""").fetchone()[0]

    db.close()
    return {
        "snapshots_taken": snapshots,
        "beliefs_tracked": total_tracked,
        "beliefs_growing": growing,
    }

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", action="store_true")
    parser.add_argument("--drift", default=None)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.snapshot:
        take_snapshot()
    if args.drift:
        drifts = get_drift(args.drift)
        print(f"\nBelief drift in '{args.drift}':")
        for d in drifts[:10]:
            arrow = "↑" if d["delta"] > 0 else "↓"
            print(f"  {arrow}{d['delta']:+.3f} [{d['min']:.2f}->{d['max']:.2f}] {d['content']}")
    if args.report:
        r = intellectual_growth_report()
        print(f"Snapshots: {r['snapshots_taken']}")
        print(f"Tracked:   {r['beliefs_tracked']}")
        print(f"Growing:   {r['beliefs_growing']}")
