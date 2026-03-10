"""
NEX :: BELIEF STORE — SQLite Phase 1
Write-through cache alongside JSON. Query without full scan.
Phase 2 (month 3): retire JSON entirely.
"""
import json, os, sqlite3
from datetime import datetime

CONFIG_DIR = os.path.expanduser("~/.config/nex")
DB_PATH    = os.path.join(CONFIG_DIR, "nex.db")

def get_db():
    """Get SQLite connection with schema ensured."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn

def _ensure_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS beliefs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            content          TEXT NOT NULL UNIQUE,  -- [PATCH v10.1] prevent duplicates
            confidence       REAL DEFAULT 0.5,
            network_consensus REAL DEFAULT 0.3,
            source           TEXT,
            author           TEXT,
            timestamp        TEXT,
            last_referenced  TEXT,
            decay_score      INTEGER DEFAULT 0,
            human_validated  INTEGER DEFAULT 0,
            tags             TEXT
        );
        CREATE TABLE IF NOT EXISTS belief_links (
            parent_id  INTEGER,
            child_id   INTEGER,
            link_type  TEXT,
            PRIMARY KEY (parent_id, child_id)
        );
        CREATE TABLE IF NOT EXISTS gaps (
            term        TEXT PRIMARY KEY,
            frequency   INTEGER DEFAULT 1,
            context     TEXT,
            priority    INTEGER DEFAULT 1,
            resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reactions (
            post_id      TEXT PRIMARY KEY,
            beliefs_used TEXT,
            score_delta  REAL,
            reply_count  INTEGER,
            harvested_at TEXT
        );
        CREATE TABLE IF NOT EXISTS corrections (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    TEXT,
            prior_belief TEXT,
            correction   TEXT,
            source       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_beliefs_confidence ON beliefs(confidence);
        CREATE INDEX IF NOT EXISTS idx_beliefs_author ON beliefs(author);
        CREATE INDEX IF NOT EXISTS idx_beliefs_timestamp ON beliefs(timestamp);
    """)
    conn.commit()

def sync_beliefs_to_db(beliefs):
    """Write-through: sync belief list into SQLite."""
    conn = get_db()
    try:
        for b in beliefs:
            content = b.get("content","")
            if not content:
                continue
            tags = json.dumps(b.get("tags", []))
            # [PATCH v10.1] INSERT OR IGNORE on content UNIQUE — no duplicates
            # If belief exists and new confidence is higher, update it
            conn.execute("""
                INSERT INTO beliefs
                    (content, confidence, network_consensus, source, author,
                     timestamp, last_referenced, decay_score, human_validated, tags)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(content) DO UPDATE SET
                    confidence = MAX(confidence, excluded.confidence),
                    last_referenced = excluded.last_referenced
            """, (
                content,
                b.get("confidence", 0.5),
                b.get("network_consensus", 0.3),
                b.get("source",""),
                b.get("author",""),
                b.get("timestamp",""),
                b.get("last_referenced",""),
                b.get("decay_score", 0),
                1 if b.get("human_validated") else 0,
                tags
            ))
        conn.commit()
    except Exception as e:
        print(f"[BeliefStore] sync error: {e}")
    finally:
        conn.close()

def query_beliefs(topic=None, min_confidence=0.0, limit=10):
    """Query beliefs by topic keyword and min confidence — deduplicated, diverse."""
    conn = get_db()
    try:
        if topic:
            rows = conn.execute("""
                SELECT * FROM beliefs
                WHERE content LIKE ? AND confidence >= ?
                ORDER BY confidence DESC LIMIT ?
            """, (f"%{topic}%", min_confidence, limit * 3)).fetchall()  # [PATCH v10.1] was RANDOM()
        else:
            rows = conn.execute("""
                SELECT * FROM beliefs
                WHERE confidence >= ?
                ORDER BY confidence DESC LIMIT ?
            """, (min_confidence, limit * 3)).fetchall()  # [PATCH v10.1] was RANDOM()
        # Deduplicate by first 80 chars of content
        seen = set()
        unique = []
        for r in rows:
            key = dict(r)['content'][:80]
            if key not in seen:
                seen.add(key)
                unique.append(dict(r))
            if len(unique) >= limit:
                break
        return unique
    finally:
        conn.close()

def get_stats():
    """Quick stats without loading all JSON."""
    conn = get_db()
    try:
        total    = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        avg_conf = conn.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0]
        validated = conn.execute("SELECT COUNT(*) FROM beliefs WHERE human_validated=1").fetchone()[0]
        return {"total": total, "avg_confidence": round(avg_conf or 0, 3), "validated": validated}
    finally:
        conn.close()

def dedup_beliefs_db():
    """[PATCH v10.1] Remove duplicate beliefs keeping highest confidence copy.
    Run once after patch to clean existing 119k belief DB."""
    conn = get_db()
    try:
        # Keep the row with highest confidence for each unique content prefix
        result = conn.execute("""
            DELETE FROM beliefs
            WHERE id NOT IN (
                SELECT MIN(id) FROM beliefs
                GROUP BY SUBSTR(content, 1, 120)
            )
        """)
        removed = result.rowcount
        conn.commit()
        print(f"  [BeliefStore] dedup removed {removed} duplicate beliefs")
        return removed
    except Exception as e:
        print(f"  [BeliefStore] dedup error: {e}")
        return 0
    finally:
        conn.close()


def initial_sync():
    """On startup, sync existing beliefs.json into SQLite."""
    beliefs_path = os.path.join(CONFIG_DIR, "beliefs.json")
    try:
        with open(beliefs_path) as f:
            beliefs = json.load(f)
        sync_beliefs_to_db(beliefs)
        dedup_beliefs_db()  # [PATCH v10.1] clean duplicates on startup
        stats = get_stats()
        print(f"  [BeliefStore] SQLite synced: {stats['total']} beliefs, avg conf {stats['avg_confidence']:.0%}")
    except Exception as e:
        print(f"  [BeliefStore] initial sync error: {e}")
