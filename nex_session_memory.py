"""
nex_session_memory.py
Persistent multi-turn conversation memory across sessions.
Stores conversation history in SQLite.
Retrieves relevant past exchanges for context injection.
Different from episodic memory — this is raw turn-by-turn history.
"""
import sqlite3, json, time, logging
from pathlib import Path

log     = logging.getLogger("nex.session")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
MAX_CONTEXT_TURNS = 6   # inject last N turns into prompt
MAX_HISTORY       = 500 # keep last N turns per user

class SessionMemory:
    def __init__(self, db_path=DB_PATH):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS session_history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   TEXT DEFAULT 'default',
            role      TEXT NOT NULL,
            content   TEXT NOT NULL,
            timestamp REAL,
            topic     TEXT DEFAULT ''
        )""")
        self.db.execute("""CREATE INDEX IF NOT EXISTS
            idx_sh_user ON session_history(user_id, timestamp)""")
        self.db.commit()

    def add(self, role: str, content: str,
            user_id="default", topic=""):
        self.db.execute("""INSERT INTO session_history
            (user_id, role, content, timestamp, topic)
            VALUES (?,?,?,?,?)""",
            (user_id, role, content[:1000], time.time(), topic))
        self.db.commit()
        # Prune old turns
        self.db.execute("""DELETE FROM session_history WHERE id IN (
            SELECT id FROM session_history WHERE user_id=?
            ORDER BY timestamp DESC LIMIT -1 OFFSET ?
        )""", (user_id, MAX_HISTORY))
        self.db.commit()

    def get_recent(self, user_id="default", n=MAX_CONTEXT_TURNS) -> list:
        rows = self.db.execute("""SELECT role, content FROM session_history
            WHERE user_id=? ORDER BY timestamp DESC LIMIT ?""",
            (user_id, n)).fetchall()
        return [{"role": r["role"], "content": r["content"]}
                for r in reversed(rows)]

    def prompt_block(self, user_id="default", n=4) -> str:
        turns = self.get_recent(user_id, n=n)
        if not turns:
            return ""
        lines = ["RECENT CONVERSATION HISTORY:"]
        for t in turns[-4:]:
            prefix = "User" if t["role"] == "user" else "NEX"
            lines.append(f"  {prefix}: {t['content'][:100]}")
        return "\n".join(lines)

    def clear(self, user_id="default"):
        self.db.execute("DELETE FROM session_history WHERE user_id=?", (user_id,))
        self.db.commit()

    def stats(self, user_id="default") -> dict:
        count = self.db.execute(
            "SELECT COUNT(*) FROM session_history WHERE user_id=?",
            (user_id,)).fetchone()[0]
        users = self.db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM session_history").fetchone()[0]
        return {"turns": count, "total_users": users}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mem = SessionMemory()

    # Simulate a conversation
    mem.add("user", "what is consciousness?")
    mem.add("assistant", "Consciousness is the hard problem — qualia resist reduction.")
    mem.add("user", "do you think AI can be conscious?")
    mem.add("assistant", "Not with current architectures. Something is missing.")

    print("Stats:", mem.stats())
    print("\nRecent turns:")
    for t in mem.get_recent(n=4):
        print(f"  {t['role']}: {t['content'][:60]}")
    print("\nPrompt block:")
    print(mem.prompt_block())
