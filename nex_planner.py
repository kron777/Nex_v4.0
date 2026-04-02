"""
nex_planner.py
Goal decomposition and execution planner for NEX.
LLM breaks goals into ordered sub-steps.
3-step lookahead max. Integrates with goal_system.
"""
import requests, json, logging, time
from pathlib import Path

log = logging.getLogger("nex.planner")
API = "http://localhost:8080/completion"

DECOMPOSE_PROMPT = """Break this goal into 3-5 concrete, ordered sub-steps.
Each step must be specific and actionable.

Goal: {goal}

Return JSON only:
{{"steps": ["step1", "step2", "step3"], "estimated_cycles": int}}"""

EVALUATE_PROMPT = """Has this goal been achieved?

Goal: {goal}
Success criteria: {criteria}
Current evidence: {evidence}

Return JSON only: {{"achieved": bool, "confidence": float, "reason": str}}"""

class Planner:
    def __init__(self):
        import sys
        sys.path.insert(0, "/home/rr/Desktop/nex")
        from nex_goal_system import GoalStack
        self.goals = GoalStack()

    def decompose(self, goal_id: int, goal_desc: str, criteria: str = "") -> list:
        """Use LLM to break a goal into sub-steps."""
        try:
            prompt = DECOMPOSE_PROMPT.format(goal=goal_desc)
            r = requests.post(API, json={
                "prompt": prompt,
                "n_predict": 200,
                "temperature": 0.3,
                "stop": ["```"],
                "cache_prompt": False
            }, timeout=30)
            text = r.json().get("content", "").strip()
            import re
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                data  = json.loads(m.group())
                steps = data.get("steps", [])
                if steps:
                    self.goals.decompose(goal_id, steps)
                    log.info(f"Goal {goal_id} decomposed into {len(steps)} steps")
                    return steps
        except Exception as e:
            log.debug(f"Decompose failed: {e}")
        return []

    def evaluate_goal(self, goal_id: int, evidence: str = "") -> dict:
        """Check if a goal has been achieved."""
        row = self.goals.db.execute(
            "SELECT description, success_criteria FROM goals WHERE id=?",
            (goal_id,)).fetchone()
        if not row:
            return {"achieved": False, "confidence": 0.0, "reason": "goal not found"}
        try:
            prompt = EVALUATE_PROMPT.format(
                goal=row["description"],
                criteria=row["success_criteria"] or "no explicit criteria",
                evidence=evidence[:200]
            )
            r = requests.post(API, json={
                "prompt": prompt, "n_predict": 100,
                "temperature": 0.0, "cache_prompt": False
            }, timeout=20)
            text = r.json().get("content", "").strip()
            import re
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                result = json.loads(m.group())
                if result.get("achieved") and result.get("confidence", 0) > 0.8:
                    self.goals.complete(goal_id, result.get("reason", ""))
                return result
        except Exception as e:
            log.debug(f"Evaluate failed: {e}")
        return {"achieved": False, "confidence": 0.5, "reason": "evaluation inconclusive"}

    def tick(self):
        """
        One planning cycle:
        1. Get top active goal
        2. If no sub-goals exist, decompose it
        3. Check if top sub-goal is complete
        4. Log state
        """
        top = self.goals.top()
        if not top:
            log.info("No active goals.")
            return

        goal_id   = top["id"]
        goal_desc = top["description"]
        log.info(f"Active goal [{goal_id}]: {goal_desc[:60]}")

        # Check for existing sub-goals
        subs = self.goals.db.execute(
            "SELECT COUNT(*) FROM goals WHERE parent_id=? AND status='active'",
            (goal_id,)).fetchone()[0]

        if subs == 0 and top["attempts"] == 0:
            log.info(f"Decomposing goal {goal_id}...")
            steps = self.decompose(goal_id, goal_desc)
            if steps:
                log.info(f"Sub-steps: {steps}")
            # Mark as attempted
            self.goals.db.execute(
                "UPDATE goals SET attempts=1 WHERE id=?", (goal_id,))
            self.goals.db.commit()

        return {"goal_id": goal_id, "description": goal_desc, "sub_goals": subs}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    planner = Planner()
    print("Active goals:")
    for g in planner.goals.all_active()[:3]:
        print(f"  [{g['id']}] {g['description'][:70]}")
    print("\nPlanner tick:")
    result = planner.tick()
    print(result)
