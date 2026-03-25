"""
NEX :: TENSION PRESSURE ESCALATION
====================================
Unresolved tensions cannot be ignored forever.

Each tension has a cycle_count — incremented every cognition cycle.
If unresolved > ESCALATE_AFTER cycles  → bumped to dream priority
If unresolved > PARADOX_AFTER cycles   → marked as paradox
If unresolved > SPLIT_AFTER cycles     → split into two competing beliefs

This module hooks into the existing nex_tension.py infrastructure.
It reads the tensions table (or file), applies pressure, and writes
dream priority hints to a shared queue that nex_dream_cycle.py reads.

Schema: adds cycle_count + escalation_level + is_paradox to tensions.
"""

import sqlite3
import json
import os
from datetime import datetime

CONFIG_DIR = os.path.expanduser("~/.config/nex")
DB_PATH    = os.path.join(CONFIG_DIR, "nex.db")
DREAM_PRIORITY_PATH = os.path.join(CONFIG_DIR, "dream_priority.json")

# ── Tunable thresholds ────────────────────────────────────────────────────────
ESCALATE_AFTER = 8    # cycles before tension gets dream priority
PARADOX_AFTER  = 20    # cycles before tension is marked as paradox
SPLIT_AFTER    = 30   # cycles before tension is split into two beliefs
MAX_DREAM_QUEUE = 25  # max items in dream priority queue


def _ensure_tension_schema():
    """Add escalation columns to tensions table if absent."""
    conn = sqlite3.connect(DB_PATH)
    try:
        # Check if tensions table exists
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tensions'"
        ).fetchone()

        if not exists:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tensions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic        TEXT NOT NULL,
                    description  TEXT,
                    weight       REAL DEFAULT 0.5,
                    cycle_count  INTEGER DEFAULT 0,
                    escalation_level INTEGER DEFAULT 0,
                    is_paradox   INTEGER DEFAULT 0,
                    created_at   TEXT,
                    resolved_at  TEXT
                )
            """)
            conn.commit()
            return

        # Add missing columns to existing table
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tensions)").fetchall()]
        for col, defn in [
            ("cycle_count",       "INTEGER DEFAULT 0"),
            ("escalation_level",  "INTEGER DEFAULT 0"),
            ("is_paradox",        "INTEGER DEFAULT 0"),
            ("created_at",        "TEXT"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE tensions ADD COLUMN {col} {defn}")
        conn.commit()
    finally:
        conn.close()


def _load_tensions_from_file():
    """Fallback: load tensions from JSON if DB table is empty."""
    tension_file = os.path.join(CONFIG_DIR, "tensions.json")
    if os.path.exists(tension_file):
        try:
            with open(tension_file) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def run_pressure_cycle(verbose=False):
    """
    Main cycle call. Increments cycle_count for all unresolved tensions,
    escalates based on thresholds, writes dream priority queue.
    Returns dict with escalated/paradox/split counts.
    """
    _ensure_tension_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    escalated = 0
    paradoxed = 0
    split_actions = []

    try:
        # Increment cycle_count for all unresolved tensions
        conn.execute("""
            UPDATE tensions
            SET cycle_count = cycle_count + 1
            WHERE resolved_at IS NULL
        """)

        # Fetch all unresolved for evaluation
        unresolved = conn.execute("""
            SELECT * FROM tensions
            WHERE resolved_at IS NULL
            ORDER BY cycle_count DESC
        """).fetchall()

        dream_queue = []

        for t in unresolved:
            tid   = t["id"]
            topic = t["topic"]
            cc    = t["cycle_count"]
            desc  = t["description"] or topic

            # Escalate to dream priority
            if cc >= ESCALATE_AFTER and t["escalation_level"] < 1:
                conn.execute("""
                    UPDATE tensions SET escalation_level = 1, weight = MIN(weight + 0.1, 1.0)
                    WHERE id = ?
                """, (tid,))
                dream_queue.append({
                    "type": "tension",
                    "topic": topic,
                    "description": desc,
                    "priority": "high",
                    "cycle_count": cc
                })
                escalated += 1
                if verbose:
                    print(f"  [TensionPressure] ESCALATED [{cc}c]: {topic[:60]}")

            # Mark as paradox
            elif cc >= PARADOX_AFTER and not t["is_paradox"]:
                conn.execute("""
                    UPDATE tensions SET is_paradox = 1, escalation_level = 2,
                    weight = MIN(weight + 0.15, 1.0)
                    WHERE id = ?
                """, (tid,))
                dream_queue.append({
                    "type": "paradox",
                    "topic": topic,
                    "description": desc,
                    "priority": "critical",
                    "cycle_count": cc
                })
                paradoxed += 1
                if verbose:
                    print(f"  [TensionPressure] PARADOX [{cc}c]: {topic[:60]}")

            # Split — already in dream queue, generate two competing beliefs
            elif cc >= SPLIT_AFTER and t["escalation_level"] >= 2:
                split_actions.append({
                    "tension_id": tid,
                    "topic": topic,
                    "description": desc,
                    "cycle_count": cc
                })
                dream_queue.append({
                    "type": "split",
                    "topic": topic,
                    "description": desc,
                    "priority": "critical",
                    "cycle_count": cc
                })
                if verbose:
                    print(f"  [TensionPressure] SPLIT [{cc}c]: {topic[:60]}")

            # Already escalated — keep refreshing dream queue
            elif t["escalation_level"] >= 1 and cc >= ESCALATE_AFTER:
                dream_queue.append({
                    "type": "tension",
                    "topic": topic,
                    "description": desc,
                    "priority": "high",
                    "cycle_count": cc
                })

        conn.commit()

        # Execute splits — create two competing beliefs
        for s in split_actions:
            _split_tension_into_beliefs(conn, s)

    finally:
        conn.close()

    # Write dream priority queue
    _write_dream_queue(dream_queue)

    result = {
        "escalated": escalated,
        "paradoxed": paradoxed,
        "split": len(split_actions),
        "dream_queue_size": len(dream_queue)
    }

    if verbose or escalated or paradoxed:
        print(f"  [TensionPressure] {escalated} escalated | {paradoxed} paradoxed | "
              f"{len(split_actions)} split | queue={len(dream_queue)}")

    return result


def _split_tension_into_beliefs(conn, split_info):
    """
    When a tension is irresolvable, split it into two competing belief seeds.
    These beliefs represent opposite positions on the tension.
    The dream cycle will then attempt synthesis.
    """
    topic = split_info["topic"]
    desc  = split_info["description"]
    now   = datetime.now().isoformat()

    belief_a = f"[THESIS] On '{topic}': {desc} — this pattern is fundamentally stable and self-reinforcing."
    belief_b = f"[ANTITHESIS] On '{topic}': {desc} — this pattern is unstable and requires restructuring."

    for belief_content, side in [(belief_a, "thesis"), (belief_b, "antithesis")]:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO beliefs
                (content, topic, confidence, source, timestamp, last_referenced, tags)
                VALUES (?, ?, 0.4, 'tension_split', ?, ?, ?)
            """, (belief_content, topic[:40], now, now, json.dumps(["tension", "split", side, topic[:30]])))
        except Exception:
            pass

    conn.commit()


def _write_dream_queue(items):
    """Write dream priority queue to shared JSON file."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    # Load existing queue and merge, deduplicate by topic
    existing = []
    if os.path.exists(DREAM_PRIORITY_PATH):
        try:
            with open(DREAM_PRIORITY_PATH) as f:
                existing = json.load(f)
        except Exception:
            pass

    # Merge: new items override old ones with same topic
    existing_topics = {e["topic"] for e in existing}
    merged = existing.copy()
    for item in items:
        if item["topic"] not in existing_topics:
            merged.append(item)
            existing_topics.add(item["topic"])
        else:
            # Update priority if escalated
            for e in merged:
                if e["topic"] == item["topic"]:
                    e["cycle_count"] = item["cycle_count"]
                    e["priority"] = item["priority"]
                    break

    # Cap queue size, highest cycle_count first
    merged.sort(key=lambda x: x.get("cycle_count", 0), reverse=True)
    merged = merged[:MAX_DREAM_QUEUE]

    with open(DREAM_PRIORITY_PATH, "w") as f:
        json.dump(merged, f, indent=2)


def get_dream_queue():
    """Read the current dream priority queue."""
    if os.path.exists(DREAM_PRIORITY_PATH):
        try:
            with open(DREAM_PRIORITY_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def resolve_tension(topic):
    """Mark a tension as resolved — removes it from dream queue."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            UPDATE tensions SET resolved_at = ? WHERE topic = ? AND resolved_at IS NULL
        """, (datetime.now().isoformat(), topic))
        conn.commit()
    finally:
        conn.close()

    # Remove from dream queue
    queue = get_dream_queue()
    queue = [q for q in queue if q["topic"] != topic]
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(DREAM_PRIORITY_PATH, "w") as f:
        json.dump(queue, f, indent=2)


def add_tension(topic, description=None, weight=0.5):
    """Add a new tension to track."""
    _ensure_tension_schema()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO tensions (topic, description, weight, created_at)
            VALUES (?, ?, ?, ?)
        """, (topic, description or topic, weight, datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()


def get_pressure_stats():
    """Summary of tension pressure state."""
    _ensure_tension_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN resolved_at IS NULL THEN 1 ELSE 0 END) as unresolved,
                SUM(CASE WHEN is_paradox = 1 THEN 1 ELSE 0 END) as paradoxes,
                SUM(CASE WHEN escalation_level >= 1 AND resolved_at IS NULL THEN 1 ELSE 0 END) as escalated,
                MAX(cycle_count) as max_age
            FROM tensions
        """).fetchone()
        stats = dict(row) if row else {}
        stats["dream_queue"] = len(get_dream_queue())
        return stats
    finally:
        conn.close()


if __name__ == "__main__":
    _ensure_tension_schema()
    stats = get_pressure_stats()
    print(f"  Tension stats before: {stats}")
    result = run_pressure_cycle(verbose=True)
    print(f"  Cycle result: {result}")
    stats = get_pressure_stats()
    print(f"  Tension stats after: {stats}")
