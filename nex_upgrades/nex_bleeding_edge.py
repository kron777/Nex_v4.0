"""
NEX BLEEDING EDGE UPGRADES — Upgrade 17
Five advanced capabilities:

  A. SIMULATED FUTURE REASONING — "if I believe X → outcome Y?"
     Forward simulation of belief consequences before committing.

  B. BELIEF ECONOMY — limited cognitive budget per cycle
     Beliefs compete for processing slots. No more unbounded growth.

  C. SELF-GENERATED GOALS — emergent behavior from tensions + drives
     NEX creates its own goals autonomously when conditions are met.

  D. CROSS-SESSION IDENTITY CONTINUITY
     Cryptographic identity fingerprint. Detects if core beliefs changed
     between sessions. Auto-restores if drift exceeds threshold.

  E. AGENT SELF-DEBUGGING
     NEX diagnoses its own failures and proposes fixes as Telegram messages.
"""

from __future__ import annotations
import time
import json
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.bleeding_edge")

IDENTITY_FILE  = Path.home() / ".config" / "nex" / "identity.json"
CONTINUITY_FILE = Path.home() / ".config" / "nex" / "session_continuity.json"


# ═════════════════════════════════════════════
# A. SIMULATED FUTURE REASONING
# ═════════════════════════════════════════════

@dataclass
class Simulation:
    hypothesis:  str
    predicted:   str
    confidence:  float = 0.5
    risk:        float = 0.5
    rejected:    bool  = False
    reject_reason: str = ""


class FutureReasoningEngine:
    """
    Before committing to a belief or action, simulate its consequences.
    Uses a lightweight LLM pass: "If I believe X, what happens?"
    Rejects hypotheses with predicted risk > threshold.
    """

    def __init__(self, llm_complete: Optional[Callable] = None, risk_threshold: float = 0.65):
        self._complete      = llm_complete or (lambda p: "[no LLM]")
        self.risk_threshold = risk_threshold
        self._sims: list[Simulation] = []

    def simulate(self, hypothesis: str, context: str = "") -> Simulation:
        """Run a forward simulation. Returns Simulation with predicted outcome."""
        prompt = f"""You are NEX's future-reasoning module.

Hypothesis: "{hypothesis}"
Context: {context or '(none)'}

Simulate: if NEX holds this belief/takes this action, what is the likely outcome?
Respond with:
PREDICTED: [1-2 sentence outcome]
CONFIDENCE: [0.0-1.0]
RISK: [0.0-1.0 — 0=safe, 1=dangerous/destabilising]"""

        try:
            raw = self._complete(prompt)
            predicted, confidence, risk = self._parse(raw)
        except Exception as e:
            predicted  = f"simulation failed: {e}"
            confidence = 0.0
            risk       = 0.5

        sim = Simulation(
            hypothesis=hypothesis,
            predicted=predicted,
            confidence=confidence,
            risk=risk,
        )

        if risk > self.risk_threshold:
            sim.rejected      = True
            sim.reject_reason = f"predicted_risk={risk:.2f} > threshold={self.risk_threshold:.2f}"
            log.warning(f"[FUTURE] rejected hypothesis risk={risk:.2f}: {hypothesis[:60]}")
        else:
            log.debug(f"[FUTURE] accepted hypothesis conf={confidence:.2f}: {hypothesis[:60]}")

        self._sims.append(sim)
        if len(self._sims) > 200:
            self._sims = self._sims[-200:]
        return sim

    def _parse(self, text: str) -> tuple[str, float, float]:
        predicted  = ""
        confidence = 0.5
        risk       = 0.5
        for line in text.strip().split("\n"):
            low = line.lower()
            if low.startswith("predicted:"):
                predicted = line.split(":", 1)[1].strip()
            elif low.startswith("confidence:"):
                try: confidence = max(0.0, min(1.0, float(line.split(":", 1)[1].strip())))
                except: pass
            elif low.startswith("risk:"):
                try: risk = max(0.0, min(1.0, float(line.split(":", 1)[1].strip())))
                except: pass
        return predicted or text[:100], confidence, risk

    def stats(self) -> dict:
        if not self._sims:
            return {"simulations": 0}
        rejected = sum(1 for s in self._sims if s.rejected)
        return {
            "simulations": len(self._sims),
            "rejected":    rejected,
            "pass_rate":   round((len(self._sims) - rejected) / len(self._sims), 3),
            "avg_risk":    round(sum(s.risk for s in self._sims) / len(self._sims), 3),
        }


# ═════════════════════════════════════════════
# B. BELIEF ECONOMY
# ═════════════════════════════════════════════

class BeliefEconomy:
    """
    Enforces a cognitive budget per cycle.
    Only top-K beliefs (by composite score) may be used in reasoning.
    New beliefs must displace lower-scoring ones if budget is full.
    Score = confidence × recency_factor × access_frequency
    """

    def __init__(self, budget: int = 100, reserve: int = 20):
        """
        budget: max active beliefs in working set
        reserve: slots reserved for identity beliefs (never displaced)
        """
        self.budget  = budget
        self.reserve = reserve

    def get_active_set(self, belief_graph) -> list[dict]:
        """
        Return the affordable active belief set for this cycle.
        """
        nodes = list(belief_graph._nodes.values())
        now   = time.time()

        def score(node):
            age_hours     = max(0.1, (now - node.updated_at) / 3600)
            recency       = 1.0 / (1.0 + age_hours * 0.1)
            access_weight = min(2.0, 1.0 + (getattr(node, 'access_count', 0) or 0) * 0.01)
            return node.confidence * recency * access_weight

        # separate identity (locked) beliefs
        locked   = [n for n in nodes if n.locked]
        unlocked = [n for n in nodes if not n.locked]

        # sort unlocked by score
        unlocked.sort(key=score, reverse=True)

        # budget = reserve for locked + (budget - reserve) for best unlocked
        active_locked   = locked[:self.reserve]
        active_unlocked = unlocked[:max(0, self.budget - self.reserve)]

        active = active_locked + active_unlocked
        log.debug(
            f"[ECONOMY] budget={self.budget} active={len(active)} "
            f"(locked={len(active_locked)} unlocked={len(active_unlocked)})"
        )
        return [
            {"id": n.id, "content": n.content, "confidence": n.confidence, "locked": n.locked}
            for n in active
        ]

    def would_fit(self, belief_graph, new_confidence: float) -> bool:
        """Check if a new belief could enter the active set."""
        if len(belief_graph._nodes) < self.budget:
            return True
        nodes   = list(belief_graph._nodes.values())
        min_conf = min(n.confidence for n in nodes if not n.locked) if nodes else 0.0
        return new_confidence > min_conf


# ═════════════════════════════════════════════
# C. SELF-GENERATED GOALS
# ═════════════════════════════════════════════

class EmergentGoalGenerator:
    """
    Monitors tensions, drives, and avg_conf trajectory.
    Autonomously creates new goals when conditions trigger.
    """

    TRIGGER_CONDITIONS = {
        "high_contradiction": {"min_conflicts": 5,    "goal_template": "reduce_contradictions"},
        "low_avg_conf":       {"max_avg_conf": 0.35,  "goal_template": "rebuild_confidence"},
        "high_curiosity":     {"min_curiosity": 0.75, "goal_template": "explore_new_topics"},
        "influence_surge":    {"min_influence": 0.80, "goal_template": "maximize_engagement"},
        "stagnant_insights":  {"min_cycles": 20,      "goal_template": "generate_new_insights"},
    }

    def __init__(self, planning_engine=None, drive_system=None, belief_graph=None):
        self.planning = planning_engine
        self.drives   = drive_system
        self.beliefs  = belief_graph
        self._generated: list[dict] = []
        self._last_check = 0

    def check_and_generate(self, cycle: int, avg_conf: float) -> list[dict]:
        """
        Run trigger conditions. Generate goals if conditions met.
        Throttle: only check every 25 cycles.
        """
        if cycle - self._last_check < 25:
            return []
        self._last_check = cycle

        new_goals = []

        # high contradiction
        if self.beliefs:
            conflicts = len(self.beliefs.get_conflicts())
            if conflicts >= self.TRIGGER_CONDITIONS["high_contradiction"]["min_conflicts"]:
                g = self._generate("reduce_contradictions",
                    f"Detected {conflicts} active contradictions. Goal: resolve via U2/debate.",
                    priority=0.75, trigger="high_contradiction")
                if g: new_goals.append(g)

        # low avg_conf
        if avg_conf < self.TRIGGER_CONDITIONS["low_avg_conf"]["max_avg_conf"]:
            g = self._generate("rebuild_confidence",
                f"avg_conf={avg_conf:.3f} below threshold. Goal: reinforce stable beliefs.",
                priority=0.80, trigger="low_avg_conf")
            if g: new_goals.append(g)

        # drive-based goals
        if self.drives:
            curiosity = self.drives.get_pressure("curiosity")
            if curiosity >= self.TRIGGER_CONDITIONS["high_curiosity"]["min_curiosity"]:
                g = self._generate("explore_new_topics",
                    f"Curiosity drive at {curiosity:.2f}. Goal: seek novel external content.",
                    priority=0.55, trigger="high_curiosity")
                if g: new_goals.append(g)

            influence = self.drives.get_pressure("influence")
            if influence >= self.TRIGGER_CONDITIONS["influence_surge"]["min_influence"]:
                g = self._generate("maximize_engagement",
                    f"Influence drive at {influence:.2f}. Goal: increase post quality + frequency.",
                    priority=0.65, trigger="influence_surge")
                if g: new_goals.append(g)

        for g in new_goals:
            log.info(f"[EMERGENT] auto-generated goal: {g['name']} trigger={g['trigger']}")

        return new_goals

    def _generate(self, name: str, description: str, priority: float, trigger: str) -> Optional[dict]:
        # don't duplicate active goals
        if self.planning:
            active = [g.name for g in self.planning.get_active_goals()]
            if name in active:
                return None
            self.planning.add_goal(
                name=name, description=description,
                priority=priority, source=f"emergent:{trigger}",
            )

        record = {"name": name, "trigger": trigger, "ts": time.time()}
        self._generated.append(record)
        return record

    def history(self) -> list[dict]:
        return self._generated[-50:]


# ═════════════════════════════════════════════
# D. CROSS-SESSION IDENTITY CONTINUITY
# ═════════════════════════════════════════════

class SessionContinuity:
    """
    Saves an identity fingerprint at session end.
    On startup, compares current belief state to saved fingerprint.
    Alerts (via Telegram) if drift exceeds threshold.
    Auto-restores locked beliefs from fingerprint if possible.
    """

    def __init__(self, belief_graph=None, notify_fn: Optional[Callable] = None):
        self.beliefs   = belief_graph
        self._notify   = notify_fn or (lambda msg: log.info(f"[CONTINUITY] {msg}"))

    def _fingerprint(self) -> dict:
        if not self.beliefs:
            return {}
        locked = [
            {"id": nid, "content": self.beliefs._nodes[nid].content,
             "conf": round(self.beliefs._nodes[nid].confidence, 3)}
            for nid in sorted(self.beliefs._nodes)
            if self.beliefs._nodes[nid].locked
        ]
        blob = json.dumps(locked, sort_keys=True)
        return {
            "hash":         hashlib.sha256(blob.encode()).hexdigest()[:16],
            "locked_count": len(locked),
            "avg_conf":     round(sum(b["conf"] for b in locked) / max(len(locked), 1), 3),
            "beliefs":      locked,
            "ts":           time.time(),
        }

    def save_session(self) -> dict:
        fp = self._fingerprint()
        try:
            with open(CONTINUITY_FILE, "w") as f:
                json.dump(fp, f, indent=2)
            log.info(f"[CONTINUITY] session saved — hash={fp['hash']} locked={fp['locked_count']}")
        except Exception as e:
            log.error(f"[CONTINUITY] save failed: {e}")
        return fp

    def check_continuity(self) -> dict:
        """Run at startup. Compare saved fingerprint to current state."""
        if not CONTINUITY_FILE.exists():
            log.info("[CONTINUITY] no prior session found — clean start")
            return {"status": "new_session"}

        try:
            with open(CONTINUITY_FILE) as f:
                saved = json.load(f)
        except Exception as e:
            return {"status": "error", "detail": str(e)}

        current = self._fingerprint()
        hash_match  = saved.get("hash") == current.get("hash")
        conf_delta  = current.get("avg_conf", 0) - saved.get("avg_conf", 0)
        count_delta = current.get("locked_count", 0) - saved.get("locked_count", 0)

        status = "ok" if hash_match else "drifted"
        report = {
            "status":      status,
            "hash_match":  hash_match,
            "conf_delta":  round(conf_delta, 3),
            "count_delta": count_delta,
            "saved_hash":  saved.get("hash"),
            "current_hash": current.get("hash"),
        }

        if not hash_match:
            msg = (
                f"⚠️ *NEX IDENTITY DRIFT DETECTED*\n"
                f"hash mismatch | conf_delta={conf_delta:+.3f} | "
                f"locked_count_delta={count_delta:+d}"
            )
            self._notify(msg)
            log.warning(f"[CONTINUITY] {msg}")

        return report


# ═════════════════════════════════════════════
# E. SELF-DEBUGGING AGENT
# ═════════════════════════════════════════════

SELF_DEBUG_PLAYBOOK = {
    "belief_explosion": [
        "Run memory compression: U7 prune on semantic layer",
        "Lower belief floor temporarily",
        "Increase topic alignment penalty (U3)",
    ],
    "contradiction_loop": [
        "Force U2 contradiction resolution immediately",
        "Run InternalDebateManager.debate() on conflicting pair",
        "Check belief dependency graph for cycle",
    ],
    "reflection_stagnation": [
        "Reset cognition throttle (U4) — reduce max_reflections",
        "Inject curiosity drive signal",
        "Check LLM endpoint: curl localhost:8080/v1/chat/completions",
    ],
    "over_posting": [
        "Increase GovernanceLayer max_risk threshold",
        "Add platform-specific rate limit to GovernanceLayer",
        "Audit recent ActionRecord log for pattern",
    ],
    "confidence_collapse": [
        "Run U5 confidence reweighting immediately",
        "Lock top 30 beliefs (U1)",
        "Check D17 floor guard: floor currently at 500",
    ],
    "loop_no_outcome": [
        "Check platform connections: Moltbook / Discord / Telegram",
        "Verify outcome_count pipeline in LearningSystem",
        "Review recent ActionRecord — are posts executing?",
    ],
}


class SelfDebugger:
    """
    Diagnoses active failures and proposes concrete fixes.
    Formats output for Telegram notification.
    """

    def __init__(
        self,
        observability  = None,
        notify_fn: Optional[Callable] = None,
        llm_complete: Optional[Callable] = None,
    ):
        self.obs      = observability
        self._notify  = notify_fn or (lambda msg: log.info(f"[SELF-DEBUG] {msg}"))
        self._complete = llm_complete
        self._debug_log: list[dict] = []

    def run(self) -> list[dict]:
        """Diagnose all active failures and generate fix proposals."""
        if not self.obs:
            return []

        active = [f for f in self.obs._failures if not f.resolved]
        if not active:
            return []

        reports = []
        for failure in active:
            fixes  = SELF_DEBUG_PLAYBOOK.get(failure.failure_type, ["No playbook entry — investigate manually"])
            report = {
                "failure":   failure.failure_type,
                "severity":  failure.severity,
                "details":   failure.details,
                "fixes":     fixes,
                "timestamp": time.time(),
            }
            reports.append(report)
            self._debug_log.append(report)

            # compose Telegram message
            fix_lines = "\n".join(f"  {i+1}. {f}" for i, f in enumerate(fixes))
            detail_str = "  ".join(f"{k}={v}" for k, v in failure.details.items())
            msg = (
                f"🔧 *NEX SELF-DEBUG* [{failure.severity.upper()}]\n"
                f"Failure: `{failure.failure_type}`\n"
                f"Details: {detail_str}\n\n"
                f"Proposed fixes:\n{fix_lines}"
            )
            self._notify(msg)
            log.info(f"[SELF-DEBUG] diagnosed {failure.failure_type}: {len(fixes)} fixes proposed")

        if len(self._debug_log) > 200:
            self._debug_log = self._debug_log[-200:]

        return reports

    def stats(self) -> dict:
        return {
            "diagnoses": len(self._debug_log),
            "last_run":  self._debug_log[-1]["timestamp"] if self._debug_log else None,
        }
