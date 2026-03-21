"""
NEX BDI GOAL + PLANNING ENGINE — Upgrades 5 & 6
Belief-Desire-Intention model + task decomposition.

BDI Components:
  BELIEFS  → existing BeliefGraph (upgrade 4)
  DESIRES  → long-term goals (persistent)
  INTENTIONS → active plans being executed (volatile + persistent)

Planning:
  - Breaks high-level goals into sub-actions
  - Short-horizon (immediate, 1-5 actions) + long-horizon (strategy, N goals)
  - Plan adaptation based on outcome signals
"""

from __future__ import annotations
import time
import uuid
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum
from typing import Optional, Iterator

log = logging.getLogger("nex.bdi")

DB_PATH = Path.home() / ".config" / "nex" / "nex.db"


# ─────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────

class GoalStatus(str, Enum):
    ACTIVE    = "active"
    SUSPENDED = "suspended"
    ACHIEVED  = "achieved"
    FAILED    = "failed"
    DROPPED   = "dropped"

class IntentionStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    DONE     = "done"
    FAILED   = "failed"
    ABORTED  = "aborted"


# ─────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────

@dataclass
class Goal:
    """Long-term desire / objective."""
    id:          str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    name:        str   = ""
    description: str   = ""
    priority:    float = 0.5          # [0,1]
    status:      GoalStatus = GoalStatus.ACTIVE
    created_at:  float = field(default_factory=time.time)
    updated_at:  float = field(default_factory=time.time)
    source:      str   = "internal"   # what triggered this goal
    tension_id:  Optional[str] = None # if spawned from a belief tension
    progress:    float = 0.0          # [0,1]
    success_criteria: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "priority": self.priority, "status": self.status.value,
            "progress": self.progress, "success_criteria": self.success_criteria,
        }


@dataclass
class SubAction:
    """Atomic step in a plan."""
    id:          str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str   = ""
    action_type: str   = "internal"   # internal / post / query / wait
    platform:    str   = ""
    parameters:  dict  = field(default_factory=dict)
    status:      str   = "pending"    # pending / done / failed / skipped
    result:      str   = ""
    created_at:  float = field(default_factory=time.time)
    done_at:     Optional[float] = None


@dataclass
class Intention:
    """Active plan: a goal + ordered list of sub-actions."""
    id:          str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    goal_id:     str   = ""
    name:        str   = ""
    horizon:     str   = "short"      # short / long
    status:      IntentionStatus = IntentionStatus.PENDING
    steps:       list[SubAction] = field(default_factory=list)
    current_step: int  = 0
    created_at:  float = field(default_factory=time.time)
    updated_at:  float = field(default_factory=time.time)
    outcome:     str   = ""
    confidence:  float = 0.5

    def next_step(self) -> Optional[SubAction]:
        pending = [s for s in self.steps if s.status == "pending"]
        return pending[0] if pending else None

    def progress(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps if s.status in ("done", "skipped"))
        return done / len(self.steps)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "goal_id": self.goal_id, "name": self.name,
            "horizon": self.horizon, "status": self.status.value,
            "progress": self.progress(), "steps": len(self.steps),
            "current_step": self.current_step,
        }


# ─────────────────────────────────────────────
# PLANNING ENGINE
# ─────────────────────────────────────────────

class PlanningEngine:
    """
    Manages goals and intentions.
    Decomposes goals into step sequences.
    Adapts plans based on outcomes.
    """

    def __init__(self, db_path: Path = DB_PATH, llm_client=None):
        self.db_path  = db_path
        self.llm      = llm_client
        self._goals:      dict[str, Goal]      = {}
        self._intentions: dict[str, Intention] = {}
        self._init_db()
        self._load()
        log.info(f"[PLANNING] loaded {len(self._goals)} goals, {len(self._intentions)} intentions")

    # ── SETUP ─────────────────────────────────
    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS goals (
                    id                TEXT PRIMARY KEY,
                    name              TEXT,
                    description       TEXT,
                    priority          REAL DEFAULT 0.5,
                    status            TEXT DEFAULT 'active',
                    created_at        REAL,
                    updated_at        REAL,
                    source            TEXT,
                    tension_id        TEXT,
                    progress          REAL DEFAULT 0.0,
                    success_criteria  TEXT
                );
                CREATE TABLE IF NOT EXISTS intentions (
                    id           TEXT PRIMARY KEY,
                    goal_id      TEXT,
                    name         TEXT,
                    horizon      TEXT DEFAULT 'short',
                    status       TEXT DEFAULT 'pending',
                    steps        TEXT DEFAULT '[]',
                    current_step INTEGER DEFAULT 0,
                    created_at   REAL,
                    updated_at   REAL,
                    outcome      TEXT,
                    confidence   REAL DEFAULT 0.5,
                    FOREIGN KEY (goal_id) REFERENCES goals(id)
                );
                CREATE INDEX IF NOT EXISTS idx_goals_status    ON goals(status);
                CREATE INDEX IF NOT EXISTS idx_goals_priority  ON goals(priority DESC);
                CREATE INDEX IF NOT EXISTS idx_intent_status   ON intentions(status);
                CREATE INDEX IF NOT EXISTS idx_intent_goal     ON intentions(goal_id);
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _load(self) -> None:
        with self._conn() as conn:
            for row in conn.execute("SELECT * FROM goals").fetchall():
                g = Goal(
                    id=row["id"], name=row["name"], description=row["description"],
                    priority=row["priority"], status=GoalStatus(row["status"]),
                    created_at=row["created_at"], updated_at=row["updated_at"],
                    source=row["source"] or "internal",
                    tension_id=row["tension_id"],
                    progress=row["progress"] or 0.0,
                    success_criteria=row["success_criteria"] or "",
                )
                self._goals[g.id] = g

            for row in conn.execute("SELECT * FROM intentions").fetchall():
                steps_raw = json.loads(row["steps"] or "[]")
                steps = [
                    SubAction(
                        id=s.get("id", str(uuid.uuid4())[:8]),
                        description=s.get("description", ""),
                        action_type=s.get("action_type", "internal"),
                        platform=s.get("platform", ""),
                        parameters=s.get("parameters", {}),
                        status=s.get("status", "pending"),
                        result=s.get("result", ""),
                    )
                    for s in steps_raw
                ]
                i = Intention(
                    id=row["id"], goal_id=row["goal_id"],
                    name=row["name"], horizon=row["horizon"],
                    status=IntentionStatus(row["status"]),
                    steps=steps,
                    current_step=row["current_step"] or 0,
                    created_at=row["created_at"], updated_at=row["updated_at"],
                    outcome=row["outcome"] or "",
                    confidence=row["confidence"] or 0.5,
                )
                self._intentions[i.id] = i

    # ── GOAL MANAGEMENT ───────────────────────
    def add_goal(
        self,
        name: str,
        description: str = "",
        priority: float  = 0.5,
        source: str      = "internal",
        tension_id: Optional[str] = None,
        success_criteria: str = "",
    ) -> Goal:
        goal = Goal(
            name=name, description=description, priority=priority,
            source=source, tension_id=tension_id,
            success_criteria=success_criteria,
        )
        self._goals[goal.id] = goal
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO goals
                   (id, name, description, priority, status, created_at, updated_at, source, tension_id, progress, success_criteria)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (goal.id, goal.name, goal.description, goal.priority, goal.status.value,
                 goal.created_at, goal.updated_at, goal.source, goal.tension_id,
                 goal.progress, goal.success_criteria),
            )
        log.info(f"[PLANNING] goal created: {goal.name} (p={goal.priority:.2f})")
        return goal

    def spawn_goal_from_tension(self, tension_belief: dict) -> Optional[Goal]:
        """Automatically generate a goal from a detected belief contradiction/tension."""
        content = tension_belief.get("content", "")
        if not content:
            return None
        name = f"resolve_tension:{content[:40]}"
        return self.add_goal(
            name=name,
            description=f"Resolve internal tension: {content}",
            priority=0.7,
            source="tension_detection",
            tension_id=tension_belief.get("id"),
            success_criteria="Contradiction resolved, avg_conf increased",
        )

    def update_goal_status(self, goal_id: str, status: GoalStatus, progress: float = None) -> bool:
        goal = self._goals.get(goal_id)
        if not goal:
            return False
        goal.status = status
        goal.updated_at = time.time()
        if progress is not None:
            goal.progress = progress
        with self._conn() as conn:
            conn.execute(
                "UPDATE goals SET status=?, updated_at=?, progress=? WHERE id=?",
                (status.value, goal.updated_at, goal.progress, goal_id),
            )
        return True

    # ── TASK DECOMPOSITION ────────────────────
    def decompose(self, cog_result: dict) -> dict:
        """
        Called by ControlLayer planning phase.
        Returns current active intention's next step.
        """
        active = self.get_active_intentions()
        if not active:
            return {"intentions": 0, "next_step": None}

        # priority: highest-priority goal's intention
        top = max(
            active,
            key=lambda i: self._goals.get(i.goal_id, Goal()).priority,
        )
        next_step = top.next_step()
        return {
            "intentions": len(active),
            "top_intention": top.to_dict(),
            "next_step": {
                "id":          next_step.id,
                "description": next_step.description,
                "action_type": next_step.action_type,
                "platform":    next_step.platform,
            } if next_step else None,
        }

    def create_intention(
        self,
        goal_id:  str,
        name:     str,
        steps:    list[dict],     # list of SubAction-compatible dicts
        horizon:  str = "short",
        confidence: float = 0.5,
    ) -> Intention:
        sub_actions = [
            SubAction(
                description=s.get("description", ""),
                action_type=s.get("action_type", "internal"),
                platform=s.get("platform", ""),
                parameters=s.get("parameters", {}),
            )
            for s in steps
        ]
        intent = Intention(
            goal_id=goal_id, name=name, horizon=horizon,
            steps=sub_actions, confidence=confidence,
            status=IntentionStatus.PENDING,
        )
        self._intentions[intent.id] = intent
        self._persist_intention(intent)
        log.info(f"[PLANNING] intention created: {name} ({len(sub_actions)} steps)")
        return intent

    def _persist_intention(self, intent: Intention) -> None:
        steps_json = json.dumps([
            {"id": s.id, "description": s.description, "action_type": s.action_type,
             "platform": s.platform, "parameters": s.parameters,
             "status": s.status, "result": s.result}
            for s in intent.steps
        ])
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO intentions
                   (id, goal_id, name, horizon, status, steps, current_step, created_at, updated_at, outcome, confidence)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (intent.id, intent.goal_id, intent.name, intent.horizon,
                 intent.status.value, steps_json, intent.current_step,
                 intent.created_at, intent.updated_at, intent.outcome, intent.confidence),
            )

    # ── PLAN ADAPTATION ───────────────────────
    def record_outcome(self, intention_id: str, success: bool, notes: str = "") -> None:
        """Adapt future plans based on step outcomes."""
        intent = self._intentions.get(intention_id)
        if not intent:
            return

        # mark current step
        ns = intent.next_step()
        if ns:
            ns.status = "done" if success else "failed"
            ns.result = notes
            ns.done_at = time.time()
            intent.current_step += 1

        # if all steps done, mark intention complete
        if intent.progress() >= 1.0:
            intent.status = IntentionStatus.DONE
            intent.outcome = "achieved"
            # mark goal progress
            goal = self._goals.get(intent.goal_id)
            if goal:
                self.update_goal_status(goal.id, GoalStatus.ACHIEVED, progress=1.0)
        elif not success:
            # on failure: lower confidence, possibly suspend
            intent.confidence *= 0.8
            if intent.confidence < 0.2:
                intent.status = IntentionStatus.ABORTED
                log.warning(f"[PLANNING] intention {intention_id[:8]} aborted (low confidence)")

        intent.updated_at = time.time()
        self._persist_intention(intent)

    # ── QUERIES ───────────────────────────────
    def get_active_goals(self) -> list[Goal]:
        return sorted(
            [g for g in self._goals.values() if g.status == GoalStatus.ACTIVE],
            key=lambda g: g.priority,
            reverse=True,
        )

    def get_active_intentions(self) -> list[Intention]:
        return [
            i for i in self._intentions.values()
            if i.status in (IntentionStatus.PENDING, IntentionStatus.RUNNING)
        ]

    def stats(self) -> dict:
        goals_by_status = {}
        for g in self._goals.values():
            goals_by_status[g.status.value] = goals_by_status.get(g.status.value, 0) + 1
        intents_by_status = {}
        for i in self._intentions.values():
            intents_by_status[i.status.value] = intents_by_status.get(i.status.value, 0) + 1
        return {
            "goals":      goals_by_status,
            "intentions": intents_by_status,
        }
