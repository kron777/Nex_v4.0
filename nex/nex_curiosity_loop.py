#!/usr/bin/env python3
"""
nex_curiosity_loop.py — Self-sustaining curiosity queue.
Pulls topics from curiosity_gaps table (populated by contradiction resolver +
belief graph traversal) instead of hard-coded lists.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

CFG = Path("~/.config/nex").expanduser()
DB  = CFG / "nex.db"


def _ensure_tables(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS curiosity_gaps (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic       TEXT UNIQUE,
            reason      TEXT,
            priority    INTEGER DEFAULT 5,
            enqueued    INTEGER DEFAULT 0,
            created_at  TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS curiosity_queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic       TEXT,
            source      TEXT,
            added_at    TEXT,
            drained     INTEGER DEFAULT 0
        )
    """)


def _generate_gaps_from_beliefs(cur) -> list:
    """Find topics present in tensions but sparse in beliefs — these are the gaps."""
    gaps = []

    # Topics in tensions with < 20 beliefs
    try:
        cur.execute("""
            SELECT t.topic, COUNT(b.id) as belief_count
            FROM tensions t
            LEFT JOIN beliefs b ON b.tags LIKE '%' || t.topic || '%'
            GROUP BY t.topic
            HAVING belief_count < 20 AND t.topic IS NOT NULL AND length(t.topic) > 2
            ORDER BY belief_count ASC
            LIMIT 20
        """)
        for topic, count in cur.fetchall():
            gaps.append({"topic": topic, "reason": f"tension with only {count} supporting beliefs", "priority": 8})
    except Exception:
        pass

    # Tags that appear in beliefs but have no opinions formed
    try:
        op_path = CFG / "nex_opinions.json"
        import json
        existing_opinion_topics = set()
        if op_path.exists():
            ops = json.loads(op_path.read_text())
            existing_opinion_topics = {o.get("topic","") for o in ops}

        cur.execute("""
            SELECT DISTINCT tags FROM beliefs
            WHERE tags IS NOT NULL AND length(tags) > 2
            LIMIT 200
        """)
        tag_counts = {}
        for (tags,) in cur.fetchall():
            try:
                tag_list = json.loads(tags) if tags.startswith("[") else [t.strip() for t in tags.split(",")]
                for t in tag_list[:1]:  # first tag = topic
                    tag_counts[t] = tag_counts.get(t, 0) + 1
            except Exception:
                pass

        for topic, count in sorted(tag_counts.items(), key=lambda x: x[1]):
            if topic not in existing_opinion_topics and count < 15 and len(topic) > 3:
                gaps.append({"topic": topic, "reason": f"only {count} beliefs, no opinion yet", "priority": 6})
    except Exception:
        pass

    return gaps[:30]


def populate_gaps() -> int:
    if not DB.exists():
        return 0
    con = sqlite3.connect(DB)
    cur = con.cursor()
    _ensure_tables(cur)
    con.commit()

    gaps = _generate_gaps_from_beliefs(cur)
    added = 0
    for gap in gaps:
        try:
            cur.execute("""
                INSERT OR IGNORE INTO curiosity_gaps (topic, reason, priority, created_at)
                VALUES (?, ?, ?, ?)
            """, (gap["topic"], gap["reason"], gap["priority"], datetime.now(timezone.utc).isoformat()))
            added += 1
        except Exception:
            pass

    con.commit()
    con.close()
    return added


def enqueue_from_gaps(limit: int = 10) -> list:
    """Pull highest-priority unenqueued gaps into curiosity_queue."""
    if not DB.exists():
        return []
    con = sqlite3.connect(DB)
    cur = con.cursor()
    _ensure_tables(cur)
    con.commit()

    cur.execute("""
        SELECT id, topic FROM curiosity_gaps
        WHERE enqueued = 0
        ORDER BY priority DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()

    queued = []
    for gid, topic in rows:
        cur.execute("""
            INSERT INTO curiosity_queue (topic, source, reason, added_at)
            VALUES (?, 'curiosity_gaps', '', ?)
        """, (topic, datetime.now(timezone.utc).isoformat()))
        cur.execute("UPDATE curiosity_gaps SET enqueued = 1 WHERE id = ?", (gid,))
        queued.append(topic)

    con.commit()
    con.close()
    return queued


def get_next_topics(limit: int = 5) -> list:
    """Pull next undrained topics from curiosity_queue."""
    if not DB.exists():
        return []
    con = sqlite3.connect(DB)
    cur = con.cursor()
    _ensure_tables(cur)
    try:
        cur.execute("""
            SELECT id, topic FROM curiosity_queue
            WHERE drained = 0
            ORDER BY id ASC
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        ids   = [r[0] for r in rows]
        topics = [r[1] for r in rows]
        if ids:
            cur.executemany("UPDATE curiosity_queue SET drained = 1 WHERE id = ?", [(i,) for i in ids])
        con.commit()
        return topics
    except Exception:
        return []
    finally:
        con.close()


if __name__ == "__main__":
    print("Populating curiosity gaps from belief graph…")
    n = populate_gaps()
    print(f"  Added {n} gap entries")
    topics = enqueue_from_gaps(10)
    print(f"  Enqueued {len(topics)} topics: {topics}")
    nxt = get_next_topics(5)
    print(f"  Next drain topics: {nxt}")
