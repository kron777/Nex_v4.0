"""
nex_goal_system.py
Persistent goal stack for NEX. SQLite-backed.
Goals inject into system prompt at SoulLoop tick.
"""
import sqlite3, time, logging
from pathlib import Path
from enum import Enum

log = logging.getLogger("nex.goals")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

class GoalStatus(str, Enum):
    ACTIVE   = "active"
    PENDING  = "pending"
    COMPLETE = "complete"
    FAILED   = "failed"

class GoalStack:
    def __init__(self, db_path=DB_PATH):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS goals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            priority    REAL DEFAULT 0.5,
            status      TEXT DEFAULT 'active',
            created_at  REAL,
            deadline    REAL,
            parent_id   INTEGER,
            success_criteria TEXT DEFAULT '',
            attempts    INTEGER DEFAULT 0,
            last_result TEXT DEFAULT ''
        )""")
        self.db.commit()

    def push(self, description, priority=0.5, success_criteria="",
             deadline=None, parent_id=None):
        self.db.execute("""INSERT INTO goals
            (description, priority, status, created_at, deadline,
             success_criteria, parent_id)
            VALUES (?,?,?,?,?,?,?)""",
            (description, priority, GoalStatus.ACTIVE,
             time.time(), deadline, success_criteria, parent_id))
        self.db.commit()
        log.info(f"Goal pushed: {description[:60]}")

    def top(self):
        """Highest priority active goal."""
        return self.db.execute("""SELECT * FROM goals
            WHERE status='active'
            ORDER BY priority DESC, created_at ASC LIMIT 1""").fetchone()

    def all_active(self):
        return self.db.execute("""SELECT * FROM goals
            WHERE status='active'
            ORDER BY priority DESC""").fetchall()

    def complete(self, goal_id, result=""):
        self.db.execute("""UPDATE goals SET status='complete',
            last_result=? WHERE id=?""", (result, goal_id))
        self.db.commit()
        log.info(f"Goal {goal_id} completed: {result[:60]}")

    def fail(self, goal_id, reason=""):
        self.db.execute("""UPDATE goals SET status='failed',
            attempts=attempts+1, last_result=? WHERE id=?""",
            (reason, goal_id))
        self.db.commit()

    def decompose(self, goal_id, subgoals: list):
        """Break goal into ordered sub-goals."""
        for sg in subgoals:
            self.push(sg, priority=0.8, parent_id=goal_id)
        log.info(f"Goal {goal_id} decomposed into {len(subgoals)} sub-goals")

    def prompt_block(self):
        """Return active goals formatted for system prompt injection."""
        goals = self.all_active()
        if not goals:
            return ""
        lines = ["ACTIVE GOALS (pursue these across conversations):"]
        for g in goals[:3]:  # top 3 only
            lines.append(f"  [{g['priority']:.1f}] {g['description']}")
        return "\n".join(lines)

    def seed_defaults(self):
        """Seed NEX's initial goals if table is empty."""
        count = self.db.execute(
            "SELECT COUNT(*) FROM goals WHERE status='active'").fetchone()[0]
        if count > 0:
            return
        defaults = [
            ("Maintain belief coherence — detect and resolve contradictions on each anneal cycle", 0.95),
            ("Reach 200 high-confidence beliefs in consciousness, philosophy, science, ethics", 0.85),
            ("Complete each fine-tune cycle — accumulate 125 pairs, train, merge, deploy", 0.80),
            ("Engage every conversation with a stated position, not a survey of views", 0.75),
            ("Build episodic memory — recall relevant past conversations during responses", 0.70),
        ]
        for desc, pri in defaults:
            self.push(desc, priority=pri)
        log.info(f"Seeded {len(defaults)} default goals")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    gs = GoalStack()
    gs.seed_defaults()
    print("\nActive goals:")
    for g in gs.all_active():
        print(f"  [{g['priority']}] {g['description']}")
    print("\nPrompt block:")
    print(gs.prompt_block())
