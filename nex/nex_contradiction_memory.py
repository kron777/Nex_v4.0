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
