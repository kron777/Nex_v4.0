"""
nex_belief_versions.py — Temporal Belief Versioning Engine
===========================================================
Every belief change is recorded in a separate belief_versions table.
Schema: (belief_id, version, confidence, content, updated_at,
         update_reason, cycle, prev_confidence)

This gives NEX genuine autobiographical memory:
  - "What did I believe about X at cycle 100?"
  - "How has my confidence in Y changed over time?"
  - "Which topics have I changed my mind about most?"

Used by: self-proposer, narrative thread, meta-cognition layer.
"""
from __future__ import annotations
import sqlite3, time, logging, threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.belief_versions")

_DB_PATH = Path.home() / ".config/nex/nex.db"
_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_table():
    """Create belief_versions table if not exists."""
    try:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS belief_versions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                belief_id       INTEGER NOT NULL,
                version         INTEGER NOT NULL DEFAULT 1,
                confidence      REAL,
                prev_confidence REAL,
                content         TEXT,
                topic           TEXT,
                update_reason   TEXT,
                updated_at      REAL NOT NULL,
                cycle           INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS bv_belief_id ON belief_versions(belief_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS bv_topic     ON belief_versions(topic)")
        conn.execute("CREATE INDEX IF NOT EXISTS bv_cycle     ON belief_versions(cycle)")
        conn.commit()
        conn.close()
        log.info("[BelVer] belief_versions table initialised")
        return True
    except Exception as e:
        log.error(f"[BelVer] init failed: {e}")
        return False


def record(
    belief_id: int,
    version: int,
    confidence: float,
    content: str,
    topic: str,
    update_reason: str,
    cycle: int = 0,
    prev_confidence: Optional[float] = None,
):
    """Append one version record. Never deletes — append-only."""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute("""
                INSERT INTO belief_versions
                (belief_id, version, confidence, prev_confidence,
                 content, topic, update_reason, updated_at, cycle)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (belief_id, version, confidence, prev_confidence,
                  content[:500], topic, update_reason, time.time(), cycle))
            conn.commit()
            conn.close()
    except Exception as e:
        log.debug(f"[BelVer] record failed: {e}")


def record_update(belief_id: int, new_conf: float, old_conf: float,
                  content: str, topic: str, reason: str, cycle: int = 0):
    """Record a confidence update. Fetches current version from beliefs table."""
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT version FROM beliefs WHERE id = ?", (belief_id,)
        ).fetchone()
        conn.close()
        ver = (row[0] if row else 1)
        record(belief_id, ver, new_conf, content, topic, reason, cycle, old_conf)
    except Exception as e:
        log.debug(f"[BelVer] record_update failed: {e}")


def get_history(belief_id: int) -> list[dict]:
    """Full version history for one belief."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM belief_versions
            WHERE belief_id = ?
            ORDER BY updated_at ASC
        """, (belief_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_trajectory(topic: str, limit: int = 20) -> list[dict]:
    """Confidence trajectory for a topic over time."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT bv.cycle, bv.confidence, bv.prev_confidence,
                   bv.update_reason, bv.updated_at
            FROM belief_versions bv
            WHERE bv.topic = ?
            ORDER BY bv.updated_at ASC
            LIMIT ?
        """, (topic, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def most_changed(since_cycle: int = 0, limit: int = 10) -> list[dict]:
    """Topics with highest confidence delta since cycle N."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT topic,
                   COUNT(*) as changes,
                   MAX(confidence) - MIN(confidence) as conf_range,
                   MAX(cycle) as last_change_cycle
            FROM belief_versions
            WHERE cycle >= ?
            GROUP BY topic
            ORDER BY conf_range DESC
            LIMIT ?
        """, (since_cycle, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def oscillating_topics(min_changes: int = 3, limit: int = 10) -> list[dict]:
    """Topics where NEX keeps changing her mind — oscillation detection."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT topic, COUNT(*) as changes,
                   AVG(ABS(confidence - prev_confidence)) as avg_swing
            FROM belief_versions
            WHERE prev_confidence IS NOT NULL
            GROUP BY topic
            HAVING changes >= ?
            ORDER BY avg_swing DESC
            LIMIT ?
        """, (min_changes, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def epistemic_summary(last_n_cycles: int = 50) -> str:
    """Natural language summary of recent belief evolution."""
    try:
        conn = _get_conn()
        max_cycle = conn.execute(
            "SELECT MAX(cycle) FROM belief_versions"
        ).fetchone()[0] or 0
        since = max(0, max_cycle - last_n_cycles)

        changed = most_changed(since_cycle=since, limit=5)
        oscillating = oscillating_topics(limit=3)
        total = conn.execute(
            "SELECT COUNT(*) FROM belief_versions WHERE cycle >= ?", (since,)
        ).fetchone()[0]
        conn.close()

        lines = [f"In the last {last_n_cycles} cycles: {total} belief updates recorded."]
        if changed:
            tops = ", ".join(f"'{r['topic']}' (±{r['conf_range']:.2f})" for r in changed[:3])
            lines.append(f"Most evolved: {tops}.")
        if oscillating:
            osc = ", ".join(f"'{r['topic']}'" for r in oscillating[:2])
            lines.append(f"Oscillating topics (keep changing): {osc}.")
        return " ".join(lines)
    except Exception as e:
        return f"[BelVer] summary failed: {e}"


def total_count() -> int:
    """Total number of belief version records."""
    try:
        conn = _get_conn()
        n = conn.execute("SELECT COUNT(*) FROM belief_versions").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0
