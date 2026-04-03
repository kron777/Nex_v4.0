"""
nex_belief_strength.py
Ranks beliefs by composite strength score.
strength = confidence * log(1 + use_count) * recency_factor
Identifies NEX's core convictions vs peripheral beliefs.
Used to prioritise FAISS retrieval and fine-tune data selection.
"""
import sqlite3, math, logging, time
from pathlib import Path

log     = logging.getLogger("nex.strength")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

def compute_strength(confidence: float, use_count: int,
                     last_used: float, created_at: float = 0) -> float:
    """
    Composite strength score 0.0-1.0.
    - confidence: base score
    - use_count: logarithmic boost (diminishing returns)
    - recency: beliefs used recently score higher
    """
    now = time.time()
    # Use count boost — log scale so 100 uses isn't 100x better than 1
    use_boost = math.log(1 + max(use_count, 0)) * 0.15

    # Recency factor — beliefs used in last 7 days get full score
    age_hours = (now - max(last_used, created_at or now)) / 3600
    if age_hours < 24:
        recency = 1.0
    elif age_hours < 168:  # 7 days
        recency = 0.9
    elif age_hours < 720:  # 30 days
        recency = 0.7
    else:
        recency = 0.5

    strength = min(1.0, confidence * recency + use_boost)
    return round(strength, 4)

def update_strengths(db_path=DB_PATH):
    """Compute and store strength scores for all beliefs."""
    db = sqlite3.connect(str(db_path))

    # Ensure strength column exists
    cols = [r[1] for r in db.execute("PRAGMA table_info(beliefs)").fetchall()]
    if "strength" not in cols:
        db.execute("ALTER TABLE beliefs ADD COLUMN strength REAL DEFAULT 0.0")
        db.commit()

    rows = db.execute("""SELECT id, confidence,
        COALESCE(use_count, 0),
        COALESCE(last_used, 0),
        COALESCE(created_at, '')
        FROM beliefs""").fetchall()

    updated = 0
    for bid, conf, uc, lu, ca in rows:
        # Parse created_at if it's a string timestamp
        created_ts = 0
        if ca:
            try:
                import datetime
                created_ts = datetime.datetime.fromisoformat(ca).timestamp()
            except Exception:
                pass
        s = compute_strength(conf, uc, lu, created_ts)
        db.execute("UPDATE beliefs SET strength=? WHERE id=?", (s, bid))
        updated += 1

    db.commit()
    db.close()
    print(f"Strength scores updated: {updated} beliefs")
    return updated

def get_core_convictions(topic=None, n=10, db_path=DB_PATH) -> list:
    """Return NEX's strongest beliefs — her core convictions."""
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    cols = [r[1] for r in db.execute("PRAGMA table_info(beliefs)").fetchall()]
    if "strength" not in cols:
        db.close()
        update_strengths(db_path)
        db = sqlite3.connect(str(db_path))
        db.row_factory = sqlite3.Row

    q = """SELECT content, topic, confidence, COALESCE(strength, confidence) as s,
                  COALESCE(use_count, 0) as uc
           FROM beliefs WHERE confidence >= 0.7"""
    if topic:
        q += f" AND topic='{topic}'"
    q += " ORDER BY s DESC LIMIT ?"

    rows = db.execute(q, (n,)).fetchall()
    db.close()
    return [{"content": r["content"][:100], "topic": r["topic"],
             "confidence": r["confidence"], "strength": r["s"],
             "uses": r["uc"]} for r in rows]

def conviction_report(db_path=DB_PATH):
    """Print NEX's top convictions across all topics."""
    update_strengths(db_path)
    convictions = get_core_convictions(n=15)
    print(f"\nNEX's Core Convictions (top 15 by strength):")
    print("-" * 60)
    for i, c in enumerate(convictions, 1):
        print(f"{i:2}. [{c['topic']}] conf={c['confidence']:.2f} uses={c['uses']}")
        print(f"    {c['content']}")

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=None)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()

    if args.update or args.report:
        update_strengths()
    if args.report:
        conviction_report()
    elif args.topic:
        convictions = get_core_convictions(topic=args.topic, n=5)
        print(f"\nTop convictions on {args.topic}:")
        for c in convictions:
            print(f"  [{c['strength']:.3f}] {c['content']}")
