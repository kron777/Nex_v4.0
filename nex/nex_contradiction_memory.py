"""
nex_contradiction_memory.py — Persistent Contradiction Memory
=============================================================
Append-only log of every contradiction NEX has processed.
Schema: topic, thesis, antithesis, resolution, cycle, timestamp

Never deletes — the oscillation patterns only become visible
over hundreds of cycles.

Indexed on topic + cycle for fast "what have I contradicted
myself about on topic X?" queries.
"""
from __future__ import annotations
import sqlite3, time, logging, threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.contradiction_memory")

_DB_PATH = Path.home() / ".config/nex/nex.db"
_lock = threading.Lock()


def init_table():
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contradiction_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                topic       TEXT NOT NULL,
                thesis      TEXT,
                antithesis  TEXT,
                resolution  TEXT,
                tension_score REAL DEFAULT 0.0,
                cycle       INTEGER DEFAULT 0,
                timestamp   REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS cm_topic ON contradiction_memory(topic)")
        conn.execute("CREATE INDEX IF NOT EXISTS cm_cycle ON contradiction_memory(cycle)")
        conn.commit()
        conn.close()
        log.info("[ContradMem] table initialised")
        return True
    except Exception as e:
        log.error(f"[ContradMem] init failed: {e}")
        return False


def record(
    topic: str,
    thesis: str,
    antithesis: str,
    resolution: str = "",
    tension_score: float = 0.0,
    cycle: int = 0,
):
    """Append one contradiction record. Never overwrites."""
    try:
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH), timeout=15)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                INSERT INTO contradiction_memory
                (topic, thesis, antithesis, resolution, tension_score, cycle, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (topic, thesis[:400], antithesis[:400],
                  resolution[:400], tension_score, cycle, time.time()))
            conn.commit()
            conn.close()
            log.debug(f"[ContradMem] recorded: {topic}")
    except Exception as e:
        log.debug(f"[ContradMem] record failed: {e}")


def oscillating_topics(min_count: int = 2, limit: int = 10) -> list[dict]:
    """Topics where NEX has contradicted herself multiple times."""
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT topic,
                   COUNT(*) as contradiction_count,
                   AVG(tension_score) as avg_tension,
                   MAX(cycle) as last_cycle,
                   MIN(cycle) as first_cycle
            FROM contradiction_memory
            GROUP BY topic
            HAVING contradiction_count >= ?
            ORDER BY contradiction_count DESC
            LIMIT ?
        """, (min_count, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def history_for(topic: str, limit: int = 20) -> list[dict]:
    """Full contradiction history for one topic."""
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM contradiction_memory
            WHERE topic = ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (topic, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def recent(limit: int = 10) -> list[dict]:
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM contradiction_memory
            ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def total_count() -> int:
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        n = conn.execute("SELECT COUNT(*) FROM contradiction_memory").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def meta_patterns(limit: int = 5) -> list[dict]:
    """
    Detect second-order contradiction patterns:
    - Topics that oscillate together (co-oscillation clusters)
    - Topics where tension_score keeps escalating
    - Topics with longest oscillation history
    Returns list of meta-pattern dicts.
    """
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row

        # Find topic pairs that contradict in nearby cycles
        rows = conn.execute("""
            SELECT a.topic as topic_a, b.topic as topic_b,
                   COUNT(*) as co_count,
                   AVG(ABS(a.cycle - b.cycle)) as avg_cycle_gap
            FROM contradiction_memory a
            JOIN contradiction_memory b
              ON ABS(a.cycle - b.cycle) <= 3
              AND a.topic != b.topic
              AND a.id != b.id
            GROUP BY a.topic, b.topic
            HAVING co_count >= 2
            ORDER BY co_count DESC
            LIMIT ?
        """, (limit,)).fetchall()

        # Find escalating tension topics
        escalating = conn.execute("""
            SELECT topic, COUNT(*) as count,
                   MAX(tension_score) - MIN(tension_score) as tension_range,
                   MAX(cycle) as last_cycle
            FROM contradiction_memory
            GROUP BY topic
            HAVING count >= 3 AND tension_range > 0.2
            ORDER BY tension_range DESC
            LIMIT ?
        """, (limit,)).fetchall()

        conn.close()

        results = []
        for r in rows:
            results.append({
                "type": "co_oscillation",
                "topic_a": r["topic_a"],
                "topic_b": r["topic_b"],
                "co_count": r["co_count"],
                "avg_cycle_gap": round(r["avg_cycle_gap"], 1),
            })
        for r in escalating:
            results.append({
                "type": "escalating_tension",
                "topic": r["topic"],
                "count": r["count"],
                "tension_range": round(r["tension_range"], 3),
                "last_cycle": r["last_cycle"],
            })
        return results
    except Exception:
        return []


def contradiction_summary() -> str:
    """Natural language summary of contradiction patterns."""
    total = total_count()
    osc = oscillating_topics(limit=3)
    meta = meta_patterns(limit=3)

    lines = [f"Contradiction memory: {total} total records."]
    if osc:
        osc_str = ", ".join(f"'{r['topic']}' ({r['contradiction_count']}x)" for r in osc)
        lines.append(f"Oscillating topics: {osc_str}.")
    if meta:
        co = [m for m in meta if m["type"] == "co_oscillation"]
        if co:
            co_str = ", ".join(f"'{m['topic_a']}↔{m['topic_b']}'" for m in co[:2])
            lines.append(f"Co-oscillating pairs: {co_str}.")
    return " ".join(lines)
