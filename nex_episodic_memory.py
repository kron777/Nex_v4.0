#!/usr/bin/env python3
"""
nex_episodic_memory.py — Specific event memory for NEX
Stores and retrieves specific conversation moments, not just beliefs.
NEX remembers: who asked what, when, what changed, what was interesting.
"""
import sqlite3, json, re
from pathlib import Path
from datetime import datetime, timezone

DB = Path.home() / "Desktop/nex/nex.db"

def _ensure_table():
    db = sqlite3.connect(str(DB), timeout=3)
    db.execute("""CREATE TABLE IF NOT EXISTS episodic_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,
        session_id TEXT,
        query TEXT,
        response TEXT,
        topic TEXT,
        significance REAL DEFAULT 0.5,
        tags TEXT DEFAULT '[]',
        changed_mind INTEGER DEFAULT 0,
        interesting INTEGER DEFAULT 0
    )""")
    db.commit()
    db.close()

def store_episode(session_id: str, query: str, response: str, topic: str = "general",
                  changed_mind: bool = False) -> bool:
    """Store a significant conversation moment."""
    _ensure_table()
    # Score significance — longer queries, philosophical topics score higher
    sig = 0.5
    if len(query.split()) > 8: sig += 0.15
    if topic in ["consciousness", "philosophy", "ethics", "free_will", "self"]: sig += 0.2
    if changed_mind: sig += 0.3
    if any(w in query.lower() for w in ["why", "how do you", "do you think", "what do you"]): sig += 0.1
    sig = min(1.0, sig)

    # Only store significant episodes
    if sig < 0.55:
        return False

    tags = []
    if "consciousness" in query.lower() or "conscious" in response.lower(): tags.append("consciousness")
    if "you" in query.lower() and any(w in query.lower() for w in ["think","feel","believe","opinion"]): tags.append("self-reflection")
    if "?" in query: tags.append("question")
    if changed_mind: tags.append("mind-change")

    try:
        db = sqlite3.connect(str(DB), timeout=3)
        db.execute("""INSERT INTO episodic_memory
            (ts, session_id, query, response, topic, significance, tags, changed_mind, interesting)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (datetime.now(timezone.utc).isoformat(), session_id,
             query[:300], response[:500], topic, sig,
             json.dumps(tags), int(changed_mind), int(sig > 0.75)))
        db.commit()
        db.close()
        return True
    except Exception:
        return False

def recall_relevant(query: str, n: int = 3) -> list:
    """Find episodic memories relevant to current query."""
    _ensure_table()
    try:
        q_words = set(re.findall(r'\b\w{4,}\b', query.lower()))
        db = sqlite3.connect(str(DB), timeout=3)
        rows = db.execute("""SELECT query, response, topic, ts, significance
            FROM episodic_memory ORDER BY significance DESC, id DESC LIMIT 50""").fetchall()
        db.close()
        scored = []
        for row in rows:
            r_words = set(re.findall(r'\b\w{4,}\b', row[0].lower()))
            overlap = len(q_words & r_words)
            if overlap >= 2:
                scored.append((overlap * row[4], row))
        scored.sort(reverse=True)
        return [r for _, r in scored[:n]]
    except Exception:
        return []

def format_for_prompt(memories: list) -> str:
    """Format episodic memories for injection into prompt."""
    if not memories:
        return ""
    lines = ["From a previous conversation:"]
    for query, response, topic, ts, sig in memories:
        date = ts[:10] if ts else "recently"
        lines.append(f'  Someone asked: "{query[:80]}"')
        lines.append(f'  You said: "{response[:100]}"')
    return "\n".join(lines)

def stats():
    _ensure_table()
    db = sqlite3.connect(str(DB), timeout=3)
    total = db.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0]
    interesting = db.execute("SELECT COUNT(*) FROM episodic_memory WHERE interesting=1").fetchone()[0]
    db.close()
    print(f"Episodic memory: {total} episodes, {interesting} significant")

_ensure_table()
