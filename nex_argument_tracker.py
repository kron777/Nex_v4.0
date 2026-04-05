#!/usr/bin/env python3
"""
nex_argument_tracker.py — Multi-Turn Reasoning
================================================
Tracks NEX's positions across a conversation so she can:
  1. Build on previous answers rather than starting fresh
  2. Detect when she's contradicting herself in-session
  3. Deepen positions when challenged
  4. Update beliefs when she changes her mind

Wired into nex_api.py — called on each exchange.

Usage:
  from nex_argument_tracker import ArgumentTracker
  tracker = ArgumentTracker(session_id)
  context = tracker.get_context(query)   # inject into LLM prompt
  tracker.record(query, response, topic)
"""
import sqlite3, json, re
from pathlib import Path
from datetime import datetime, timezone

DB = Path.home() / "Desktop/nex/nex.db"


class ArgumentTracker:
    """Tracks positions and arguments across a conversation session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._ensure_table()
        self._positions = self._load_positions()

    def _ensure_table(self):
        try:
            db = sqlite3.connect(str(DB), timeout=3)
            db.execute("""
                CREATE TABLE IF NOT EXISTS argument_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    query TEXT,
                    response TEXT,
                    topic TEXT,
                    position_key TEXT,
                    ts TEXT
                )""")
            db.commit()
            db.close()
        except Exception:
            pass

    def _load_positions(self) -> dict:
        """Load positions taken in this session."""
        try:
            db = sqlite3.connect(str(DB), timeout=3)
            rows = db.execute("""
                SELECT query, response, topic FROM argument_log
                WHERE session_id=?
                ORDER BY id DESC LIMIT 10
            """, (self.session_id,)).fetchall()
            db.close()
            return [{"query": r[0], "response": r[1], "topic": r[2]} for r in reversed(rows)]
        except Exception:
            return []

    def get_context(self, query: str) -> str:
        """
        Build a context string of recent positions for injection into LLM prompt.
        Only includes positions relevant to the current query.
        """
        if not self._positions:
            return ""

        # Find relevant prior positions (simple word overlap)
        query_words = set(re.findall(r'\b\w{4,}\b', query.lower()))
        relevant = []
        for pos in self._positions[-5:]:
            pos_words = set(re.findall(r'\b\w{4,}\b', pos["query"].lower()))
            if len(query_words & pos_words) >= 2:
                relevant.append(pos)

        if not relevant:
            # Just include the last exchange for continuity
            relevant = self._positions[-1:]

        if not relevant:
            return ""

        lines = ["Earlier in this conversation you said:"]
        for pos in relevant[-3:]:
            lines.append(f'  Q: {pos["query"][:60]}')
            lines.append(f'  A: {pos["response"][:100]}')

        lines.append("Be consistent with or explicitly build on these positions.")
        return "\n".join(lines)

    def detect_contradiction(self, query: str, response: str) -> bool:
        """Check if response contradicts a prior position in this session."""
        if not self._positions:
            return False

        # Simple heuristic: if response says opposite of prior response on same topic
        neg_patterns = [
            (r"\bi (do|don't|don\'t) (have|hold|think|believe)", "opinion"),
            (r"\b(is|is not|isn't) conscious", "consciousness"),
            (r"\b(has|doesn't have) free will", "free_will"),
        ]

        for prior in self._positions[-3:]:
            for pattern, topic_hint in neg_patterns:
                prior_match = re.search(pattern, prior["response"].lower())
                curr_match = re.search(pattern, response.lower())
                if prior_match and curr_match:
                    if prior_match.group() != curr_match.group():
                        return True
        return False

    def record(self, query: str, response: str, topic: str = "general"):
        """Record an exchange."""
        self._positions.append({
            "query": query,
            "response": response,
            "topic": topic
        })
        try:
            db = sqlite3.connect(str(DB), timeout=3)
            db.execute("""
                INSERT INTO argument_log
                (session_id, query, response, topic, position_key, ts)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                self.session_id,
                query[:300],
                response[:500],
                topic,
                f"{self.session_id}:{len(self._positions)}",
                datetime.now(timezone.utc).isoformat()
            ))
            db.commit()
            db.close()
        except Exception:
            pass

    def summary(self) -> str:
        """Return a summary of positions taken in this session."""
        if not self._positions:
            return "No positions recorded yet."
        lines = [f"Session {self.session_id} — {len(self._positions)} exchanges:"]
        for p in self._positions[-5:]:
            lines.append(f"  [{p['topic']}] {p['response'][:80]}...")
        return "\n".join(lines)
