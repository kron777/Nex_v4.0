"""
nex_position_tracker.py
Tracks what positions NEX has taken on topics across conversations.
Prevents contradiction between sessions.
Injects prior positions into system prompt for consistency.
"""
import sqlite3, json, logging, time, requests
from pathlib import Path

log     = logging.getLogger("nex.positions")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

EXTRACT_PROMPT = """Extract the main position NEX took in this response.
One sentence, 10-25 words, starting with "NEX believes" or "NEX holds".
Response: {response}
Return only the position statement."""

class PositionTracker:
    def __init__(self, db_path=DB_PATH):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS nex_positions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            topic     TEXT NOT NULL,
            question  TEXT,
            position  TEXT NOT NULL,
            confidence REAL DEFAULT 0.7,
            timestamp REAL,
            UNIQUE(topic, position)
        )""")
        self.db.execute("""CREATE INDEX IF NOT EXISTS
            idx_np_topic ON nex_positions(topic)""")
        self.db.commit()

    def extract_position(self, question: str, response: str) -> str:
        """Use LLM to extract the position NEX took."""
        try:
            prompt = EXTRACT_PROMPT.format(response=response[:300])
            r = requests.post(API, json={
                "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
                "n_predict": 60, "temperature": 0.0,
                "stop": ["<|im_end|>","<|im_start|>","\n\n"],
                "cache_prompt": False
            }, timeout=15)
            text = r.json().get("content","").strip()
            if len(text.split()) >= 8:
                return text
        except Exception as e:
            log.debug(f"Position extraction failed: {e}")
        return ""

    def record(self, topic: str, question: str, response: str):
        """Record position NEX took on a topic."""
        position = self.extract_position(question, response)
        if not position:
            return
        try:
            self.db.execute("""INSERT OR IGNORE INTO nex_positions
                (topic, question, position, timestamp)
                VALUES (?,?,?,?)""",
                (topic, question[:200], position, time.time()))
            self.db.commit()
            log.debug(f"Position recorded [{topic}]: {position[:60]}")
        except Exception as e:
            log.debug(f"Record failed: {e}")

    def get_positions(self, topic: str, n=3) -> list:
        """Get NEX's prior positions on a topic."""
        rows = self.db.execute("""SELECT position, confidence, timestamp
            FROM nex_positions WHERE topic=?
            ORDER BY timestamp DESC LIMIT ?""", (topic, n)).fetchall()
        return [{"position": r["position"],
                 "confidence": r["confidence"]} for r in rows]

    def prompt_block(self, topic: str) -> str:
        """Format prior positions for system prompt injection."""
        positions = self.get_positions(topic, n=2)
        if not positions:
            return ""
        lines = [f"YOUR PRIOR POSITIONS ON {topic.upper()}:"]
        for p in positions:
            lines.append(f"  - {p['position']}")
        return "\n".join(lines)

    def stats(self) -> dict:
        total  = self.db.execute("SELECT COUNT(*) FROM nex_positions").fetchone()[0]
        topics = self.db.execute(
            "SELECT COUNT(DISTINCT topic) FROM nex_positions").fetchone()[0]
        return {"total_positions": total, "topics_covered": topics}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pt = PositionTracker()
    print("Stats:", pt.stats())

    # Test
    pt.record("consciousness",
              "what is consciousness",
              "Consciousness is the hard problem — qualia resist any functional reduction.")
    pt.record("ethics",
              "what is ethics",
              "Ethics is the study of what makes actions right or wrong, and I hold that moral progress is real.")

    print("\nPositions on consciousness:")
    for p in pt.get_positions("consciousness"):
        print(f"  {p['position']}")
    print("\nPrompt block:")
    print(pt.prompt_block("consciousness"))
