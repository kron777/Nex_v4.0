#!/usr/bin/env python3
"""
nex_session_persist.py — Persistent session history across API restarts
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB = Path.home() / "Desktop/nex/nex.db"
MAX_TURNS = 10  # load last N turns per session on startup

def ensure_table():
    db = sqlite3.connect(str(DB))
    db.execute("""CREATE TABLE IF NOT EXISTS session_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,
        content TEXT,
        ts TEXT
    )""")
    db.commit()
    db.close()

def save_turn(session_id: str, query: str, response: str):
    """Save a conversation turn to persistent storage."""
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        now = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO session_history (session_id,role,content,ts) VALUES (?,?,?,?)",
                   (session_id, "user", query[:500], now))
        db.execute("INSERT INTO session_history (session_id,role,content,ts) VALUES (?,?,?,?)",
                   (session_id, "assistant", response[:500], now))
        db.commit()
        db.close()
    except Exception:
        pass

def load_history(session_id: str, n: int = MAX_TURNS) -> list:
    """Load last N turns for a session as [(query, response), ...]"""
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        rows = db.execute("""
            SELECT role, content FROM session_history
            WHERE session_id=?
            ORDER BY id DESC LIMIT ?
        """, (session_id, n*2)).fetchall()
        db.close()
        rows = list(reversed(rows))
        turns = []
        i = 0
        while i < len(rows) - 1:
            if rows[i][0] == "user" and rows[i+1][0] == "assistant":
                turns.append((rows[i][1], rows[i+1][1]))
                i += 2
            else:
                i += 1
        return turns
    except Exception:
        return []

def stats() -> dict:
    """Return session persistence stats."""
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        total = db.execute("SELECT COUNT(*) FROM session_history").fetchone()[0]
        sessions = db.execute("SELECT COUNT(DISTINCT session_id) FROM session_history").fetchone()[0]
        db.close()
        return {"total_turns": total, "sessions": sessions}
    except Exception:
        return {}

ensure_table()
