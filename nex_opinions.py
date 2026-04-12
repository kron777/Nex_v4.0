"""
nex_opinions.py — Opinion formation for run.py
Forms lightweight opinions from high-confidence belief clusters.
"""
import sqlite3, os, logging
log = logging.getLogger("nex_opinions")
_DB = os.path.expanduser("~/Desktop/nex/nex.db")

def refresh_opinions(db_path: str = _DB) -> int:
    """
    Called every 20 cycles by run.py.
    Returns number of opinions formed/updated.
    """
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        # Ensure opinions table exists
        cur.execute("""CREATE TABLE IF NOT EXISTS opinions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            stance TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            support_count INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')))""")
        # Find topics with 3+ high-confidence beliefs and no existing opinion
        rows = cur.execute("""
            SELECT topic, AVG(confidence) as avg_conf, COUNT(*) as cnt
            FROM beliefs
            WHERE confidence > 0.65
              AND LENGTH(content) > 30
              AND topic NOT IN (SELECT topic FROM opinions)
            GROUP BY topic
            HAVING cnt >= 3
            ORDER BY avg_conf DESC
            LIMIT 3
        """).fetchall()
        formed = 0
        for topic, avg_conf, cnt in rows:
            # Get the strongest belief as stance
            stance_row = cur.execute("""
                SELECT content FROM beliefs
                WHERE topic = ? ORDER BY confidence DESC LIMIT 1
            """, (topic,)).fetchone()
            if stance_row:
                cur.execute("""
                    INSERT OR REPLACE INTO opinions
                        (topic, stance, confidence, support_count, updated_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                """, (topic, stance_row[0][:200], avg_conf, cnt))
                formed += 1
        con.commit(); con.close()
        return formed
    except Exception as e:
        log.warning(f"refresh_opinions: {e}")
        return 0
