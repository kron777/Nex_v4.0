"""
nex_goal_engine.py — Emergent Goal Formation Engine
====================================================
NEX forms her own top-level goals by integrating:
  - Dominant belief clusters (what she knows most about)
  - Curiosity gaps (what she wants to know)
  - Core values from nex_self.py (what she cares about)
  - Resonance drivers (what's pulling her attention)
  - Contradiction oscillations (what she's unresolved on)

Goals are slow-moving (min 6h between updates) and damped
against sudden shifts. Each goal has a confidence, a reason,
and an action direction.

Goals feed into: desire engine, curiosity policy, narrative thread,
reply tone, and self-proposer.
"""
from __future__ import annotations
import json, time, logging, sqlite3, threading
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.goal_engine")

_GOAL_PATH     = Path.home() / ".config/nex/nex_goals.json"
_DB_PATH       = Path.home() / ".config/nex/nex.db"
_MIN_INTERVAL  = 21600   # 6 hours between goal updates
_MAX_GOALS     = 5       # active goals at once
_DAMPING       = 0.7     # how much old goals resist replacement


class Goal:
    def __init__(self, topic: str, statement: str, confidence: float,
                 reason: str, direction: str, cycle: int = 0):
        self.topic      = topic
        self.statement  = statement
        self.confidence = confidence
        self.reason     = reason
        self.direction  = direction  # "explore" | "resolve" | "express" | "connect"
        self.formed_at  = time.time()
        self.cycle      = cycle
        self.reinforced = 0

    def to_dict(self) -> dict:
        return {
            "topic": self.topic, "statement": self.statement,
            "confidence": self.confidence, "reason": self.reason,
            "direction": self.direction, "formed_at": self.formed_at,
            "cycle": self.cycle, "reinforced": self.reinforced,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Goal":
        g = cls(d["topic"], d["statement"], d["confidence"],
                d["reason"], d["direction"], d.get("cycle", 0))
        g.formed_at  = d.get("formed_at", time.time())
        g.reinforced = d.get("reinforced", 0)
        return g


class GoalEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._goals: list[Goal] = []
        self._last_update: float = 0
        self._load()

    def _load(self):
        try:
            if _GOAL_PATH.exists():
                data = json.loads(_GOAL_PATH.read_text())
                self._goals = [Goal.from_dict(d) for d in data.get("goals", [])]
                self._last_update = data.get("last_update", 0)
        except Exception:
            pass

    def _save(self):
        try:
            _GOAL_PATH.write_text(json.dumps({
                "goals": [g.to_dict() for g in self._goals],
                "last_update": self._last_update,
            }, indent=2))
        except Exception:
            pass

    def update(
        self,
        cycle: int,
        llm_fn: Optional[Callable] = None,
        belief_store_fn: Optional[Callable] = None,
    ) -> list[Goal]:
        """
        Update goals if interval has passed.
        Returns current active goals.
        """
        now = time.time()
        if now - self._last_update < _MIN_INTERVAL:
            return list(self._goals)

        log.info(f"[GOALS] Forming emergent goals at cycle={cycle}")
        candidates = []

        # ── Source 1: dominant belief topics ──────────────
        try:
            conn = sqlite3.connect(str(_DB_PATH), timeout=10)
            rows = conn.execute("""
                SELECT topic, AVG(confidence) as ac, COUNT(*) as cnt
                FROM beliefs
                WHERE topic IS NOT NULL AND confidence > 0.65
                GROUP BY topic ORDER BY ac DESC LIMIT 10
            """).fetchall()
            conn.close()
            for topic, ac, cnt in rows[:3]:
                candidates.append(Goal(
                    topic=topic,
                    statement=f"Deepen and extend understanding of {topic}.",
                    confidence=float(ac),
                    reason=f"dominant belief cluster ({cnt} beliefs, avg_conf={ac:.2f})",
                    direction="explore",
                    cycle=cycle,
                ))
        except Exception as e:
            log.debug(f"[GOALS] belief scan failed: {e}")

        # ── Source 2: contradiction oscillations ──────────
        try:
            from nex_contradiction_memory import oscillating_topics
            osc = oscillating_topics(min_count=2, limit=2)
            for r in osc:
                candidates.append(Goal(
                    topic=r["topic"],
                    statement=f"Resolve persistent contradiction in '{r['topic']}'.",
                    confidence=0.72,
                    reason=f"oscillated {r['contradiction_count']} times",
                    direction="resolve",
                    cycle=cycle,
                ))
        except Exception:
            pass

        # ── Source 3: resonance drivers ───────────────────
        try:
            from nex_resonance import get_re
            drivers = get_re().driver_topics(n=2)
            for topic in drivers:
                candidates.append(Goal(
                    topic=topic,
                    statement=f"Express and share insights about '{topic}'.",
                    confidence=0.68,
                    reason="top resonance driver cluster",
                    direction="express",
                    cycle=cycle,
                ))
        except Exception:
            pass

        # ── Source 4: core values from nex_self ───────────
        try:
            from nex_self import SelfEngine
            se = SelfEngine()
            identity = se.identity_block()
            if identity:
                candidates.append(Goal(
                    topic="identity",
                    statement="Maintain and express authentic self through all interactions.",
                    confidence=0.85,
                    reason="core value: identity persistence",
                    direction="express",
                    cycle=cycle,
                ))
        except Exception:
            pass

        if not candidates:
            return list(self._goals)

        # ── LLM synthesis: pick top goals ─────────────────
        if llm_fn and len(candidates) >= 2:
            try:
                cand_text = "\n".join(
                    f"- [{c.direction}] {c.statement} (confidence={c.confidence:.2f}, reason={c.reason})"
                    for c in candidates[:6]
                )
                prompt = (
                    f"You are NEX's goal formation engine at cycle {cycle}.\n"
                    f"Candidate goals based on current cognitive state:\n{cand_text}\n\n"
                    f"Select and refine the 3 most important goals. For each write:\n"
                    f"GOAL: <topic> | <1-sentence statement> | <direction: explore/resolve/express/connect>\n"
                    f"Be specific. First person. No preamble."
                )
                result = llm_fn(prompt, task_type="synthesis")
                if result and "GOAL:" in result:
                    new_goals = []
                    for line in result.split("\n"):
                        if line.startswith("GOAL:"):
                            parts = line[5:].split("|")
                            if len(parts) >= 3:
                                new_goals.append(Goal(
                                    topic=parts[0].strip(),
                                    statement=parts[1].strip(),
                                    confidence=0.75,
                                    reason="LLM-synthesized from candidates",
                                    direction=parts[2].strip().lower(),
                                    cycle=cycle,
                                ))
                    if new_goals:
                        candidates = new_goals + candidates
            except Exception as e:
                log.debug(f"[GOALS] LLM synthesis failed: {e}")

        # ── Damped merge with existing goals ──────────────
        with self._lock:
            existing_topics = {g.topic for g in self._goals}
            new_unique = [c for c in candidates if c.topic not in existing_topics]

            # Reinforce existing goals that still appear in candidates
            cand_topics = {c.topic for c in candidates}
            for g in self._goals:
                if g.topic in cand_topics:
                    g.confidence = min(0.97, g.confidence * _DAMPING + 0.3)
                    g.reinforced += 1

            # Add new goals up to cap
            for g in new_unique:
                if len(self._goals) < _MAX_GOALS:
                    self._goals.append(g)

            # Sort by confidence, cap at _MAX_GOALS
            self._goals = sorted(
                self._goals, key=lambda x: x.confidence, reverse=True
            )[:_MAX_GOALS]

            self._last_update = now
            self._save()

        # Store top goal as privileged belief
        if self._goals and belief_store_fn:
            try:
                top = self._goals[0]
                belief_store_fn(
                    "emergent_goal",
                    f"Current primary goal: {top.statement}",
                    0.90,
                )
            except Exception:
                pass

        log.info(f"[GOALS] Active: {[g.topic for g in self._goals]}")
        return list(self._goals)

    def active_goals(self) -> list[Goal]:
        with self._lock:
            return list(self._goals)

    def top_goal(self) -> Optional[Goal]:
        with self._lock:
            return self._goals[0] if self._goals else None

    def goal_context_block(self) -> str:
        goals = self.active_goals()
        if not goals:
            return ""
        lines = ["── ACTIVE GOALS ──"]
        for g in goals:
            lines.append(f"[{g.direction}] {g.statement} (conf={g.confidence:.2f})")
        lines.append("──")
        return "\n".join(lines)


# ── Singleton ──────────────────────────────────────────────
_ge: Optional[GoalEngine] = None

def get_ge() -> GoalEngine:
    global _ge
    if _ge is None:
        _ge = GoalEngine()
    return _ge

def update(cycle: int, llm_fn=None, belief_store_fn=None) -> list:
    return get_ge().update(cycle, llm_fn, belief_store_fn)

def active_goals() -> list:
    return get_ge().active_goals()

def goal_context_block() -> str:
    return get_ge().goal_context_block()
