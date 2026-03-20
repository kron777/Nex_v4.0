"""
NEX SESSION 8 UPGRADES — nex_s8.py
20 upgrades focused on emergent dynamics, true scarcity, and proto-agency.

U0  Prime Directive — immutable anchor, all scoring references it
U1  Energy Model — cognitive energy with real costs, forces tradeoffs
U2  Attention Field — dynamic topic intensity field with momentum
U3  Belief Inertia — mutation cost scales with age/usage/reinforcement
U4  Commitment Mechanism — cluster dominance triggers directed focus
U5  Contradiction Resolution V2 — merge/split/suppress with structural change
U6  Temporal Causal Tracking — action→outcome→reinforce loop
U7  Goal Evolution — goals decay, mutate, die based on tension/failure
U8  Silence Capability — explicit do-nothing when no action clears threshold
U9  Self-Model — proto-conscious state tracking used in decision scoring
U10 Stability Index — calculated stability drives mutation rate adaptation
U11 Novelty Regulation — balance exploration vs consolidation
U12 Belief Economy Hard Limit — max 600, prune by composite score
U13 Internal Debate Micro — pre-commit supporting/opposing argument check
U14 Failure Memory — suppress repeated failure patterns
U15 Pressure Redistribution — prevent cluster tunnel vision
U16 Identity Lock Threshold — auto-promote to identity_core at conf>0.9
U17 Meta-Learning Loop — evaluate which mechanisms reduced tension, adjust weights
U18 External Feedback Integration — engagement → belief reinforcement with cap
U19 Drift Detection — snapshot divergence triggers stabilization mode
U20 Emergent Behavior Conditions — detect and report proto-agency achievement
"""

from __future__ import annotations
import time
import json
import math
import uuid
import hashlib
import logging
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Any

log = logging.getLogger("nex.s8")
DB_PATH = Path.home() / ".config" / "nex" / "nex.db"


# ══════════════════════════════════════════════════════════════════════════════
# U0 — PRIME DIRECTIVE
# ══════════════════════════════════════════════════════════════════════════════

PRIME_DIRECTIVE = "maximize coherent belief evolution under constraint"

def directive_alignment(content: str, confidence: float, goal_aligned: bool) -> float:
    """
    Score how well a belief/action aligns with the prime directive.
    Used by all scoring functions as a multiplier.
    Returns [0,1].
    """
    # coherence component: higher confidence = more coherent
    coherence = confidence

    # evolution component: belief has content + isn't trivially short
    evolution = min(1.0, len(content.split()) / 10)

    # constraint component: goal alignment keeps system focused
    constraint = 0.7 if goal_aligned else 0.4

    return (coherence * 0.4 + evolution * 0.3 + constraint * 0.3)


# ══════════════════════════════════════════════════════════════════════════════
# U1 — ENERGY MODEL
# ══════════════════════════════════════════════════════════════════════════════

ENERGY_COSTS = {
    "absorb":          2,
    "reply":           5,
    "reflect":         4,
    "belief_mutation": 6,
    "post":            8,
    "embed":           3,
    "debate":          7,
    "goal_create":     5,
    "plan":            4,
}

class EnergyModel:
    """
    Cognitive energy budget. Forces real tradeoffs.
    energy_max=100, regen=+5/cycle.
    If energy < cost → action is skipped.
    """

    def __init__(self, energy_max: int = 100, regen_per_cycle: int = 5):
        self.energy_max    = energy_max
        self.regen         = regen_per_cycle
        self._energy       = float(energy_max)
        self._spent_log:   deque = deque(maxlen=200)
        self._denied_log:  deque = deque(maxlen=200)
        self._cycle        = 0

    def tick(self) -> float:
        """Call once per cycle to regenerate energy."""
        self._cycle += 1
        self._energy = min(self.energy_max, self._energy + self.regen)
        return self._energy

    def can_afford(self, action: str) -> bool:
        cost = ENERGY_COSTS.get(action, 3)
        return self._energy >= cost

    def spend(self, action: str) -> bool:
        """Attempt to spend energy. Returns False if insufficient."""
        cost = ENERGY_COSTS.get(action, 3)
        if self._energy < cost:
            self._denied_log.append({"action": action, "cost": cost,
                                     "energy": self._energy, "cycle": self._cycle})
            log.debug(f"[ENERGY] denied {action} cost={cost} energy={self._energy:.1f}")
            return False
        self._energy -= cost
        self._spent_log.append({"action": action, "cost": cost, "cycle": self._cycle})
        return True

    def force_spend(self, action: str) -> None:
        """Spend energy regardless of balance (for mandatory ops). Can go negative."""
        cost = ENERGY_COSTS.get(action, 3)
        self._energy -= cost

    @property
    def level(self) -> float:
        return self._energy

    @property
    def pct(self) -> float:
        return self._energy / self.energy_max

    def stats(self) -> dict:
        denied_counts: dict[str, int] = defaultdict(int)
        for d in self._denied_log:
            denied_counts[d["action"]] += 1
        return {
            "energy":      round(self._energy, 1),
            "energy_max":  self.energy_max,
            "pct":         round(self.pct, 2),
            "cycle":       self._cycle,
            "denied":      dict(denied_counts),
        }


# ══════════════════════════════════════════════════════════════════════════════
# U2 — ATTENTION FIELD
# ══════════════════════════════════════════════════════════════════════════════

class AttentionField:
    """
    Dynamic topic intensity field. Creates momentum and focus over time.
    Each cycle: active topics reinforced, inactive decay.
    Input scoring: score = base_score * field[topic]
    """

    def __init__(
        self,
        decay_rate:    float = 0.05,
        reinforce_amt: float = 0.15,
        max_topics:    int   = 50,
    ):
        self._field:    dict[str, float] = defaultdict(lambda: 0.3)
        self.decay      = decay_rate
        self.reinforce  = reinforce_amt
        self.max_topics = max_topics

    def activate(self, topic: str, strength: float = 1.0) -> float:
        """Reinforce a topic. Returns new intensity."""
        current = self._field[topic]
        new_val = min(1.0, current + self.reinforce * strength)
        self._field[topic] = new_val
        return new_val

    def tick(self) -> None:
        """Decay all topics. Call once per cycle."""
        for topic in list(self._field.keys()):
            self._field[topic] = max(0.0, self._field[topic] - self.decay)
        # prune dead topics
        dead = [t for t, v in self._field.items() if v < 0.01]
        for t in dead:
            del self._field[t]
        # cap total topics
        if len(self._field) > self.max_topics:
            sorted_topics = sorted(self._field.items(), key=lambda x: x[1], reverse=True)
            self._field = dict(sorted_topics[:self.max_topics])

    def score(self, base_score: float, topic: str) -> float:
        """Apply field intensity to a base score."""
        intensity = self._field.get(topic, 0.3)
        return base_score * (0.5 + intensity * 0.5)

    def top_topics(self, n: int = 5) -> list[dict]:
        sorted_f = sorted(self._field.items(), key=lambda x: x[1], reverse=True)
        return [{"topic": t, "intensity": round(v, 3)} for t, v in sorted_f[:n]]

    def dominant_topic(self) -> Optional[str]:
        if not self._field:
            return None
        return max(self._field, key=self._field.get)

    def stats(self) -> dict:
        return {
            "active_topics": len(self._field),
            "dominant":      self.dominant_topic(),
            "top":           self.top_topics(3),
        }


# ══════════════════════════════════════════════════════════════════════════════
# U3 — BELIEF INERTIA
# ══════════════════════════════════════════════════════════════════════════════

class BeliefInertia:
    """
    Each belief accumulates inertia based on age, usage, reinforcement.
    Mutation cost scales with inertia — high inertia beliefs resist change.
    inertia = f(age_cycles, access_count, reinforcement_count)
    """

    def __init__(self):
        self._inertia: dict[str, float] = {}
        self._access:  dict[str, int]   = defaultdict(int)
        self._reinf:   dict[str, int]   = defaultdict(int)
        self._born:    dict[str, int]   = {}   # cycle born
        self._cycle    = 0

    def tick(self, cycle: int) -> None:
        self._cycle = cycle

    def record_access(self, belief_id: str) -> None:
        self._access[belief_id] += 1
        self._update(belief_id)

    def record_reinforcement(self, belief_id: str) -> None:
        self._reinf[belief_id] += 1
        self._update(belief_id)

    def born(self, belief_id: str) -> None:
        if belief_id not in self._born:
            self._born[belief_id] = self._cycle

    def _update(self, belief_id: str) -> float:
        age     = self._cycle - self._born.get(belief_id, self._cycle)
        access  = self._access[belief_id]
        reinf   = self._reinf[belief_id]
        # inertia grows with age + usage, logarithmically bounded
        inertia = (
            0.3 * math.log1p(age)    / math.log1p(100) +
            0.4 * math.log1p(access) / math.log1p(50)  +
            0.3 * math.log1p(reinf)  / math.log1p(20)
        )
        self._inertia[belief_id] = min(1.0, inertia)
        return self._inertia[belief_id]

    def get(self, belief_id: str) -> float:
        return self._inertia.get(belief_id, 0.1)

    def mutation_cost_multiplier(self, belief_id: str) -> float:
        """Returns multiplier for mutation energy cost. 1.0–3.0x."""
        return 1.0 + self.get(belief_id) * 2.0

    def stats(self) -> dict:
        if not self._inertia:
            return {"tracked": 0}
        avg = sum(self._inertia.values()) / len(self._inertia)
        high = sum(1 for v in self._inertia.values() if v > 0.7)
        return {"tracked": len(self._inertia), "avg_inertia": round(avg, 3), "high_inertia": high}


# ══════════════════════════════════════════════════════════════════════════════
# U4 — COMMITMENT MECHANISM
# ══════════════════════════════════════════════════════════════════════════════

class CommitmentMechanism:
    """
    When a cluster dominates for N consecutive cycles, commit to it.
    Effects: +2x attention weight, +2x belief reinforcement, suppress competitors.
    This is where "interest" becomes "direction".
    """

    def __init__(
        self,
        dominance_threshold: int   = 5,    # cycles of dominance to trigger commit
        attention_field: Optional[AttentionField] = None,
    ):
        self.threshold      = dominance_threshold
        self.attention      = attention_field
        self._dominance:    dict[str, int]   = defaultdict(int)  # topic → consecutive cycles
        self._committed:    Optional[str]    = None
        self._commit_cycle: int              = 0
        self._history:      list[dict]       = []

    def observe(self, dominant_topic: str, cycle: int) -> Optional[str]:
        """
        Call each cycle with the current dominant topic.
        Returns committed topic if commitment just triggered, else None.
        """
        if not dominant_topic:
            return None

        # increment dominance counter
        self._dominance[dominant_topic] += 1

        # decay all others
        for t in list(self._dominance.keys()):
            if t != dominant_topic:
                self._dominance[t] = max(0, self._dominance[t] - 1)

        # check threshold
        if self._dominance[dominant_topic] >= self.threshold:
            if self._committed != dominant_topic:
                self._committed    = dominant_topic
                self._commit_cycle = cycle
                self._history.append({"topic": dominant_topic, "cycle": cycle})

                # boost attention field
                if self.attention:
                    self.attention.activate(dominant_topic, strength=2.0)
                    # suppress competitors by decaying everything else
                    for t in list(self.attention._field.keys()):
                        if t != dominant_topic:
                            self.attention._field[t] *= 0.7

                log.info(f"[COMMIT] committed to topic: {dominant_topic} at cycle {cycle}")
                return dominant_topic

        return None

    def is_committed(self) -> bool:
        return self._committed is not None

    def committed_topic(self) -> Optional[str]:
        return self._committed

    def release(self) -> None:
        """Release commitment — call when topic relevance drops."""
        log.info(f"[COMMIT] released commitment: {self._committed}")
        self._committed = None

    def stats(self) -> dict:
        return {
            "committed":      self._committed,
            "commit_cycle":   self._commit_cycle,
            "dominance_map":  dict(sorted(self._dominance.items(), key=lambda x: x[1], reverse=True)[:5]),
            "history_count":  len(self._history),
        }


# ══════════════════════════════════════════════════════════════════════════════
# U5 — CONTRADICTION RESOLUTION V2
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ResolutionAction:
    strategy:    str    # merge / split / suppress
    belief_a:    str
    belief_b:    str
    result:      str    = ""
    confidence:  float  = 0.0
    cycle:       int    = 0


class ContradictionResolutionV2:
    """
    Three strategies for contradiction resolution:
      A) merge  — synthesize into single belief
      B) split  — create conditional belief (context-dependent)
      C) suppress — reduce weaker belief confidence

    Chooses strategy based on confidence + reinforcement + goal alignment.
    Leads to structural change, not just logging.
    """

    def __init__(self, belief_graph=None, llm_complete: Optional[Callable] = None):
        self.beliefs  = belief_graph
        self._llm     = llm_complete
        self._log:    list[ResolutionAction] = []

    def resolve(self, id_a: str, id_b: str, cycle: int = 0) -> Optional[ResolutionAction]:
        if not self.beliefs:
            return None

        node_a = self.beliefs.get(id_a)
        node_b = self.beliefs.get(id_b)
        if not node_a or not node_b:
            return None

        # choose strategy
        conf_diff  = abs(node_a.confidence - node_b.confidence)
        avg_conf   = (node_a.confidence + node_b.confidence) / 2
        len_a      = len(node_a.content.split())
        len_b      = len(node_b.content.split())

        if conf_diff > 0.3:
            # clear winner — suppress loser
            strategy = "suppress"
        elif avg_conf > 0.6 and len_a > 5 and len_b > 5:
            # both substantial — try merge
            strategy = "merge"
        else:
            # ambiguous — split into conditional
            strategy = "split"

        action = ResolutionAction(strategy=strategy, belief_a=id_a, belief_b=id_b, cycle=cycle)

        if strategy == "suppress":
            loser  = node_a if node_a.confidence < node_b.confidence else node_b
            new_cf = loser.confidence * 0.6
            self.beliefs.upsert(loser.content, new_cf, loser.source,
                                belief_id=loser.id, reason=f"suppress_cy{cycle}")
            action.result     = f"suppressed {loser.id[:8]} to conf={new_cf:.2f}"
            action.confidence = max(node_a.confidence, node_b.confidence)

        elif strategy == "merge":
            merged_content = f"{node_a.content} [synthesized with: {node_b.content[:40]}]"
            merged_conf    = min(0.85, (node_a.confidence + node_b.confidence) / 2 + 0.05)
            self.beliefs.upsert(merged_content, merged_conf, "merge_resolution",
                                reason=f"merge_cy{cycle}")
            # reduce both source beliefs
            self.beliefs.upsert(node_a.content, node_a.confidence * 0.7,
                                node_a.source, belief_id=id_a, reason="merged")
            self.beliefs.upsert(node_b.content, node_b.confidence * 0.7,
                                node_b.source, belief_id=id_b, reason="merged")
            action.result     = f"merged → new belief conf={merged_conf:.2f}"
            action.confidence = merged_conf

        elif strategy == "split":
            # make beliefs context-conditional
            split_a = f"[context:A] {node_a.content}"
            split_b = f"[context:B] {node_b.content}"
            self.beliefs.upsert(split_a, node_a.confidence * 0.9, node_a.source,
                                belief_id=id_a, reason=f"split_cy{cycle}")
            self.beliefs.upsert(split_b, node_b.confidence * 0.9, node_b.source,
                                belief_id=id_b, reason=f"split_cy{cycle}")
            action.result     = "split into conditional beliefs"
            action.confidence = avg_conf

        self._log.append(action)
        log.info(f"[RESOLUTION V2] {strategy}: {id_a[:8]} ↔ {id_b[:8]} → {action.result}")
        return action

    def resolve_all(self, cycle: int = 0) -> list[ResolutionAction]:
        if not self.beliefs:
            return []
        pairs   = self.beliefs.get_conflicts()
        actions = []
        for a, b in pairs[:10]:   # max 10 per cycle
            act = self.resolve(a, b, cycle)
            if act:
                actions.append(act)
        return actions

    def stats(self) -> dict:
        strategies = defaultdict(int)
        for r in self._log:
            strategies[r.strategy] += 1
        return {"resolutions": len(self._log), "by_strategy": dict(strategies)}


# ══════════════════════════════════════════════════════════════════════════════
# U6 — TEMPORAL CAUSAL TRACKING
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CausalRecord:
    id:                 str   = field(default_factory=lambda: uuid.uuid4().hex[:10])
    action_type:        str   = ""
    belief_state_before: dict = field(default_factory=dict)   # {avg_conf, count, tension}
    belief_state_after:  dict = field(default_factory=dict)
    outcome_score:      float = 0.0   # >0 = good, <0 = bad
    tension_delta:      float = 0.0   # negative = tension reduced
    coherence_delta:    float = 0.0
    timestamp:          float = field(default_factory=time.time)
    reinforced:         bool  = False


class TemporalCausalTracker:
    """
    Records action→outcome→reinforce.
    Reinforces actions that reduce tension OR increase coherence.
    Primitive learning from consequences.
    """

    def __init__(self, belief_graph=None, drive_system=None):
        self.beliefs = belief_graph
        self.drives  = drive_system
        self._records: list[CausalRecord] = []
        self._action_scores: dict[str, list[float]] = defaultdict(list)
        self._pending: Optional[CausalRecord] = None

    def _snapshot(self) -> dict:
        if not self.beliefs:
            return {"avg_conf": 0.44, "count": 0, "conflicts": 0}
        nodes = list(self.beliefs._nodes.values())
        avg   = sum(n.confidence for n in nodes) / max(len(nodes), 1)
        return {
            "avg_conf":  round(avg, 4),
            "count":     len(nodes),
            "conflicts": len(self.beliefs.get_conflicts()),
        }

    def before_action(self, action_type: str) -> str:
        """Call before an action. Returns record ID."""
        rec = CausalRecord(
            action_type=action_type,
            belief_state_before=self._snapshot(),
        )
        self._pending = rec
        return rec.id

    def after_action(self, outcome_score: float = 0.0) -> Optional[CausalRecord]:
        """Call after action completes with outcome score."""
        if not self._pending:
            return None

        rec = self._pending
        self._pending = None
        rec.belief_state_after = self._snapshot()
        rec.outcome_score      = outcome_score

        # compute deltas
        rec.tension_delta   = (rec.belief_state_after["conflicts"] -
                               rec.belief_state_before["conflicts"]) * -1  # negative conflicts = good
        rec.coherence_delta = (rec.belief_state_after["avg_conf"] -
                               rec.belief_state_before["avg_conf"])

        # reinforce if action improved system state
        net_benefit = outcome_score + rec.tension_delta * 0.3 + rec.coherence_delta * 2.0
        rec.reinforced = net_benefit > 0

        self._action_scores[rec.action_type].append(net_benefit)
        self._records.append(rec)
        if len(self._records) > 500:
            self._records = self._records[-500:]

        if rec.reinforced and self.drives:
            self.drives.signal("engagement_signal")

        log.debug(f"[CAUSAL] {rec.action_type} → outcome={outcome_score:.2f} "
                  f"tension_delta={rec.tension_delta:.2f} reinforced={rec.reinforced}")
        return rec

    def best_actions(self) -> list[dict]:
        return sorted(
            [{"action": a, "avg_score": round(sum(v)/len(v), 3), "count": len(v)}
             for a, v in self._action_scores.items()],
            key=lambda x: x["avg_score"], reverse=True
        )

    def stats(self) -> dict:
        return {
            "records":      len(self._records),
            "best_actions": self.best_actions()[:3],
            "reinforced":   sum(1 for r in self._records if r.reinforced),
        }


# ══════════════════════════════════════════════════════════════════════════════
# U7 — GOAL EVOLUTION SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

class GoalEvolutionSystem:
    """
    Goals are not static. Goals evolve, decay, and die.
    - tension persists → goal mutates toward tension topic
    - cluster dominance shifts → goal priority reweights
    - failure detected → goal confidence drops
    - no reinforcement for N cycles → goal decays to dropped
    """

    def __init__(self, planning_engine=None, decay_rate: float = 0.02, stale_cycles: int = 30):
        self.planning    = planning_engine
        self.decay_rate  = decay_rate
        self.stale_limit = stale_cycles
        self._last_reinforced: dict[str, int] = {}
        self._cycle = 0

    def tick(self, cycle: int, tension_topics: list[str] = None, dominant_cluster: str = None) -> dict:
        self._cycle = cycle
        if not self.planning:
            return {}

        evolved   = 0
        decayed   = 0
        dropped   = 0

        active = self.planning.get_active_goals()
        for goal in active:
            stale = cycle - self._last_reinforced.get(goal.id, cycle - 1)

            # goal decay if not reinforced
            if stale > self.stale_limit:
                goal.priority = max(0.05, goal.priority - self.decay_rate * stale)
                decayed += 1
                if goal.priority < 0.1:
                    from nex_bdi_planning import GoalStatus
                    self.planning.update_goal_status(goal.id, GoalStatus.DROPPED)
                    dropped += 1
                    log.info(f"[GOAL EVO] dropped stale goal: {goal.name}")
                    continue

            # evolve goal toward persistent tension topics
            if tension_topics and goal.tension_id:
                if any(t in goal.name for t in tension_topics[:3]):
                    goal.priority = min(0.95, goal.priority + 0.03)
                    self._last_reinforced[goal.id] = cycle
                    evolved += 1

            # boost goals aligned with dominant cluster
            if dominant_cluster and dominant_cluster.lower() in goal.name.lower():
                goal.priority = min(0.95, goal.priority + 0.02)
                self._last_reinforced[goal.id] = cycle
                evolved += 1

        return {"evolved": evolved, "decayed": decayed, "dropped": dropped}

    def reinforce_goal(self, goal_id: str) -> None:
        self._last_reinforced[goal_id] = self._cycle

    def on_failure(self, goal_id: str) -> None:
        """Reduce goal priority on detected failure."""
        if self.planning:
            goal = self.planning._goals.get(goal_id)
            if goal:
                goal.priority *= 0.75
                log.info(f"[GOAL EVO] failure penalty on: {goal.name}")


# ══════════════════════════════════════════════════════════════════════════════
# U8 — SILENCE CAPABILITY
# ══════════════════════════════════════════════════════════════════════════════

class SilenceGate:
    """
    Silence = intelligence.
    If no action scores above threshold, do nothing.
    Tracks silence rate as a health metric.
    """

    def __init__(self, action_threshold: float = 0.35):
        self.threshold  = action_threshold
        self._silenced  = 0
        self._acted     = 0
        self._log:      deque = deque(maxlen=100)

    def should_act(self, action_scores: dict[str, float]) -> tuple[bool, Optional[str]]:
        """
        Given {action_type: score}, returns (should_act, best_action).
        Returns (False, None) if nothing clears threshold — silence.
        """
        viable = {a: s for a, s in action_scores.items() if s >= self.threshold}
        if not viable:
            self._silenced += 1
            self._log.append({"result": "silence", "ts": time.time(),
                              "best_score": max(action_scores.values()) if action_scores else 0})
            log.debug(f"[SILENCE] all actions below threshold={self.threshold} — staying silent")
            return False, None

        best = max(viable, key=viable.get)
        self._acted += 1
        self._log.append({"result": "act", "action": best, "score": viable[best], "ts": time.time()})
        return True, best

    @property
    def silence_rate(self) -> float:
        total = self._silenced + self._acted
        return self._silenced / max(total, 1)

    def stats(self) -> dict:
        return {
            "silenced":    self._silenced,
            "acted":       self._acted,
            "silence_rate": round(self.silence_rate, 3),
            "threshold":   self.threshold,
        }


# ══════════════════════════════════════════════════════════════════════════════
# U9 — SELF-MODEL
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SelfState:
    dominant_topics:  list[str] = field(default_factory=list)
    active_goal:      str       = ""
    tension_level:    float     = 0.3
    stability_score:  float     = 0.5
    energy_pct:       float     = 1.0
    avg_conf:         float     = 0.44
    cycle:            int       = 0
    timestamp:        float     = field(default_factory=time.time)


class SelfModel:
    """
    Proto-conscious layer. NEX tracks and reasons about its own state.
    self_state is used as a multiplier in decision scoring.
    """

    def __init__(self):
        self._state   = SelfState()
        self._history: deque[SelfState] = deque(maxlen=100)

    def update(
        self,
        cycle:           int,
        dominant_topics: list[str],
        active_goal:     str,
        tension_level:   float,
        stability_score: float,
        energy_pct:      float,
        avg_conf:        float,
    ) -> SelfState:
        prev = self._state
        self._history.append(prev)
        self._state = SelfState(
            dominant_topics=dominant_topics,
            active_goal=active_goal,
            tension_level=tension_level,
            stability_score=stability_score,
            energy_pct=energy_pct,
            avg_conf=avg_conf,
            cycle=cycle,
        )
        return self._state

    def decision_modifier(self, action_type: str) -> float:
        """
        Modifies action scores based on self-awareness.
        Returns [0.5, 1.5] multiplier.
        """
        s = self._state

        # low energy → penalize expensive actions
        if s.energy_pct < 0.3 and action_type in ("post", "debate", "belief_mutation"):
            return 0.6

        # high tension → boost reflection, suppress posting
        if s.tension_level > 0.7:
            if action_type == "reflect":
                return 1.4
            if action_type == "post":
                return 0.7

        # high stability → boost posting
        if s.stability_score > 0.7 and action_type == "post":
            return 1.3

        # low avg_conf → boost reflection
        if s.avg_conf < 0.35 and action_type == "reflect":
            return 1.5

        return 1.0

    def self_report(self) -> str:
        s = self._state
        return (
            f"cycle={s.cycle} | "
            f"topics={s.dominant_topics[:2]} | "
            f"goal={s.active_goal[:30] if s.active_goal else 'none'} | "
            f"tension={s.tension_level:.2f} | "
            f"stability={s.stability_score:.2f} | "
            f"energy={s.energy_pct:.0%} | "
            f"avg_conf={s.avg_conf:.3f}"
        )

    def stats(self) -> dict:
        return {
            "self_state":  self._state.__dict__,
            "history_len": len(self._history),
        }


# ══════════════════════════════════════════════════════════════════════════════
# U10 — STABILITY INDEX
# ══════════════════════════════════════════════════════════════════════════════

class StabilityIndex:
    """
    stability = low_contradiction + stable_clusters + low_belief_churn
    If stability drops: reduce mutation rate, increase reflection weight.
    """

    def __init__(self):
        self._history: deque[float] = deque(maxlen=50)
        self._belief_counts: deque[int] = deque(maxlen=20)
        self._conflict_counts: deque[int] = deque(maxlen=20)
        self.mutation_rate_multiplier: float = 1.0
        self.reflection_weight:        float = 1.0

    def calculate(self, belief_count: int, conflict_count: int, avg_conf: float) -> float:
        self._belief_counts.append(belief_count)
        self._conflict_counts.append(conflict_count)

        # contradiction component: fewer conflicts = more stable
        max_conflicts = 50
        contradiction_score = 1.0 - min(1.0, conflict_count / max_conflicts)

        # cluster stability: belief count not changing rapidly
        if len(self._belief_counts) >= 3:
            recent = list(self._belief_counts)[-3:]
            churn  = max(recent) - min(recent)
            cluster_score = 1.0 - min(1.0, churn / 20)
        else:
            cluster_score = 0.5

        # belief churn: low variance in recent avg_conf
        if len(self._history) >= 5:
            recent_conf = list(self._history)[-5:]
            variance    = sum((c - avg_conf)**2 for c in recent_conf) / 5
            churn_score = 1.0 - min(1.0, variance * 20)
        else:
            churn_score = 0.5

        stability = (contradiction_score * 0.4 + cluster_score * 0.3 + churn_score * 0.3)
        self._history.append(avg_conf)

        # adapt system parameters
        if stability < 0.4:
            self.mutation_rate_multiplier = 0.5   # slow down mutations
            self.reflection_weight        = 1.8   # reflect more
            log.warning(f"[STABILITY] low={stability:.2f} — throttling mutation, boosting reflection")
        elif stability > 0.75:
            self.mutation_rate_multiplier = 1.2   # allow faster evolution
            self.reflection_weight        = 0.9
        else:
            self.mutation_rate_multiplier = 1.0
            self.reflection_weight        = 1.0

        return round(stability, 4)

    def current(self) -> float:
        return self._history[-1] if self._history else 0.5

    def stats(self) -> dict:
        return {
            "mutation_rate_multiplier": self.mutation_rate_multiplier,
            "reflection_weight":        self.reflection_weight,
        }


# ══════════════════════════════════════════════════════════════════════════════
# U11 — NOVELTY REGULATION
# ══════════════════════════════════════════════════════════════════════════════

class NoveltyRegulator:
    """
    Tracks novelty_rate = new_beliefs / cycle.
    Too high → suppress new belief creation.
    Too low  → boost exploration.
    """

    def __init__(self, target_rate: float = 3.0, window: int = 10):
        self.target       = target_rate
        self._window      = window
        self._new_beliefs: deque[int] = deque(maxlen=window)
        self._mode        = "balanced"   # balanced / suppress / explore

    def record_cycle(self, new_beliefs_this_cycle: int) -> str:
        self._new_beliefs.append(new_beliefs_this_cycle)
        if len(self._new_beliefs) < 3:
            return "balanced"

        avg_rate = sum(self._new_beliefs) / len(self._new_beliefs)

        if avg_rate > self.target * 2:
            self._mode = "suppress"
            log.debug(f"[NOVELTY] suppressing — rate={avg_rate:.1f} > {self.target*2:.1f}")
        elif avg_rate < self.target * 0.4:
            self._mode = "explore"
            log.debug(f"[NOVELTY] exploring — rate={avg_rate:.1f} < {self.target*0.4:.1f}")
        else:
            self._mode = "balanced"

        return self._mode

    def creation_allowed(self) -> bool:
        return self._mode != "suppress"

    def exploration_boost(self) -> float:
        """Returns multiplier for novelty scoring."""
        return 1.4 if self._mode == "explore" else 1.0

    def stats(self) -> dict:
        avg = sum(self._new_beliefs) / max(len(self._new_beliefs), 1)
        return {"mode": self._mode, "avg_rate": round(avg, 2), "target": self.target}


# ══════════════════════════════════════════════════════════════════════════════
# U12 — BELIEF ECONOMY HARD LIMIT
# ══════════════════════════════════════════════════════════════════════════════

class BeliefEconomyHard:
    """
    Hard cap: max 600 beliefs.
    If exceeded: prune by composite score = confidence × usage × recency × goal_alignment.
    Forces evolution instead of accumulation.
    """

    def __init__(self, max_beliefs: int = 600):
        self.max_beliefs = max_beliefs

    def enforce(self, belief_graph, temporal_intel=None, goal_keywords: set = None) -> int:
        """Prune if over limit. Returns number pruned."""
        if not belief_graph:
            return 0

        nodes = [n for n in belief_graph._nodes.values() if not n.locked]
        if len(belief_graph._nodes) <= self.max_beliefs:
            return 0

        excess = len(belief_graph._nodes) - self.max_beliefs
        goal_kws = goal_keywords or set()
        now = time.time()

        def composite_score(node):
            conf       = node.confidence
            usage      = math.log1p(getattr(node, 'access_count', 0) or 0) / math.log1p(50)
            age_hours  = (now - node.updated_at) / 3600
            recency    = math.exp(-age_hours / 48)
            words      = set(node.content.lower().split())
            goal_align = min(1.0, len(words & goal_kws) / max(len(goal_kws), 1)) if goal_kws else 0.3
            return conf * 0.35 + usage * 0.25 + recency * 0.25 + goal_align * 0.15

        # sort by score ascending (worst first)
        nodes.sort(key=composite_score)
        to_prune = nodes[:excess]

        pruned = 0
        for node in to_prune:
            if node.id in belief_graph._nodes:
                del belief_graph._nodes[node.id]
                pruned += 1

        if pruned:
            log.warning(f"[ECONOMY HARD] pruned {pruned} beliefs to enforce limit={self.max_beliefs}")

        return pruned

    def stats(self, belief_graph) -> dict:
        if not belief_graph:
            return {}
        total  = len(belief_graph._nodes)
        locked = sum(1 for n in belief_graph._nodes.values() if n.locked)
        return {"total": total, "locked": locked, "limit": self.max_beliefs,
                "headroom": self.max_beliefs - total}


# ══════════════════════════════════════════════════════════════════════════════
# U13 — INTERNAL DEBATE MICRO (PRE-COMMIT)
# ══════════════════════════════════════════════════════════════════════════════

class MicroDebate:
    """
    Before committing any belief, generate supporting + opposing argument.
    Only commit if net confidence is positive.
    Lower cost than full 3-agent debate — runs on every belief candidate.
    """

    def __init__(self, llm_complete: Optional[Callable] = None):
        self._llm     = llm_complete or (lambda p: "SUPPORT: plausible. OPPOSE: uncertain. CONFIDENCE: 0.5")
        self._log:    list[dict] = []

    def evaluate(self, belief_content: str, base_confidence: float) -> dict:
        """Returns {commit: bool, adjusted_confidence: float, support: str, oppose: str}"""
        prompt = f"""Evaluate this belief for commitment:
"{belief_content}"

Respond with EXACTLY this format:
SUPPORT: [one sentence argument for]
OPPOSE: [one sentence argument against]
CONFIDENCE: [0.0-1.0 adjusted confidence]"""

        try:
            raw        = self._llm(prompt)
            support    = ""
            oppose     = ""
            adj_conf   = base_confidence

            for line in raw.strip().split("\n"):
                low = line.lower()
                if low.startswith("support:"):
                    support = line.split(":", 1)[1].strip()
                elif low.startswith("oppose:"):
                    oppose  = line.split(":", 1)[1].strip()
                elif low.startswith("confidence:"):
                    try:
                        adj_conf = max(0.0, min(1.0, float(line.split(":",1)[1].strip())))
                    except: pass

            commit = adj_conf > 0.35
            result = {"commit": commit, "adjusted_confidence": adj_conf,
                      "support": support, "oppose": oppose, "original": base_confidence}
        except Exception as e:
            result = {"commit": True, "adjusted_confidence": base_confidence,
                      "support": "", "oppose": "", "error": str(e)}

        self._log.append({"content": belief_content[:60], **result})
        if len(self._log) > 200:
            self._log = self._log[-200:]

        return result

    def stats(self) -> dict:
        if not self._log:
            return {"evaluated": 0}
        commits   = sum(1 for r in self._log if r.get("commit"))
        rejections = len(self._log) - commits
        return {"evaluated": len(self._log), "committed": commits, "rejected": rejections}


# ══════════════════════════════════════════════════════════════════════════════
# U14 — FAILURE MEMORY
# ══════════════════════════════════════════════════════════════════════════════

class FailureMemory:
    """
    Track failed patterns by content hash + context.
    Suppress repeated failures automatically.
    """

    def __init__(self, suppress_threshold: int = 3):
        self.threshold = suppress_threshold
        self._failures: dict[str, dict] = {}   # hash → {count, pattern, context, last_seen}

    def _hash(self, pattern: str) -> str:
        return hashlib.md5(pattern.lower().strip().encode()).hexdigest()[:12]

    def record(self, pattern: str, context: str = "") -> int:
        h   = self._hash(pattern)
        rec = self._failures.setdefault(h, {"count": 0, "pattern": pattern[:100],
                                             "context": context[:100], "suppressed": False})
        rec["count"]     += 1
        rec["last_seen"]  = time.time()

        if rec["count"] >= self.threshold and not rec["suppressed"]:
            rec["suppressed"] = True
            log.warning(f"[FAILURE MEM] suppressing pattern after {rec['count']}x: {pattern[:60]}")

        return rec["count"]

    def is_suppressed(self, pattern: str) -> bool:
        h   = self._hash(pattern)
        rec = self._failures.get(h)
        return rec["suppressed"] if rec else False

    def stats(self) -> dict:
        suppressed = sum(1 for r in self._failures.values() if r["suppressed"])
        return {"tracked": len(self._failures), "suppressed": suppressed}


# ══════════════════════════════════════════════════════════════════════════════
# U15 — PRESSURE REDISTRIBUTION
# ══════════════════════════════════════════════════════════════════════════════

class PressureRedistributor:
    """
    If one cluster dominates too long: redistribute attention to adjacent clusters.
    Prevents overfitting / tunnel vision.
    """

    def __init__(self, attention_field: Optional[AttentionField] = None,
                 dominance_limit: int = 10):
        self.attention       = attention_field
        self.dominance_limit = dominance_limit
        self._topic_age:     dict[str, int] = defaultdict(int)

    def tick(self, dominant_topic: str) -> bool:
        """Call each cycle. Returns True if redistribution occurred."""
        if not dominant_topic:
            return False

        self._topic_age[dominant_topic] += 1

        if self._topic_age[dominant_topic] >= self.dominance_limit:
            log.info(f"[PRESSURE] redistributing from over-dominant: {dominant_topic}")
            self._topic_age[dominant_topic] = self.dominance_limit // 2  # reset partially

            if self.attention:
                # slightly decay the dominant topic
                current = self.attention._field.get(dominant_topic, 0.5)
                self.attention._field[dominant_topic] = current * 0.85
                # boost adjacent topics (all non-dominant get a small lift)
                for t in list(self.attention._field.keys()):
                    if t != dominant_topic:
                        self.attention._field[t] = min(1.0, self.attention._field[t] + 0.08)

            return True
        return False


# ══════════════════════════════════════════════════════════════════════════════
# U16 — IDENTITY LOCK THRESHOLD
# ══════════════════════════════════════════════════════════════════════════════

class IdentityLockThreshold:
    """
    When belief reaches conf > 0.9 AND high usage → auto-promote to identity_core.
    Identity beliefs: very slow decay, high mutation resistance.
    """

    def __init__(self, belief_graph=None, conf_threshold: float = 0.9,
                 usage_threshold: int = 10):
        self.beliefs       = belief_graph
        self.conf_threshold = conf_threshold
        self.usage_threshold = usage_threshold
        self._promoted:    set[str] = set()

    def scan(self, inertia_system: Optional[BeliefInertia] = None) -> list[str]:
        """Scan all beliefs and auto-promote qualifying ones. Returns newly promoted IDs."""
        if not self.beliefs:
            return []

        newly_promoted = []
        for node in self.beliefs._nodes.values():
            if node.id in self._promoted or node.locked:
                continue

            usage = 0
            if inertia_system:
                usage = inertia_system._access.get(node.id, 0)

            if node.confidence >= self.conf_threshold and usage >= self.usage_threshold:
                node.locked = True
                self.beliefs._persist_update(node, node.snapshot(reason="identity_lock_threshold"))
                self._promoted.add(node.id)
                newly_promoted.append(node.id)
                log.info(f"[IDENTITY LOCK] auto-promoted conf={node.confidence:.2f} "
                         f"usage={usage}: {node.content[:60]}")

        return newly_promoted

    def stats(self) -> dict:
        return {"auto_promoted": len(self._promoted)}


# ══════════════════════════════════════════════════════════════════════════════
# U17 — META-LEARNING LOOP
# ══════════════════════════════════════════════════════════════════════════════

class MetaLearningLoop:
    """
    Every N cycles: evaluate which mechanisms reduced tension most.
    Adjust weights: attention decay, mutation rate, reflection frequency.
    System improves its own thinking process.
    """

    def __init__(self, eval_every: int = 50):
        self.eval_every = eval_every
        self._snapshots: list[dict] = []
        self.weights = {
            "attention_decay":    0.05,
            "mutation_rate":      1.0,
            "reflection_weight":  1.0,
            "novelty_target":     3.0,
            "silence_threshold":  0.35,
        }
        self._adjustments: list[dict] = []

    def snapshot(self, cycle: int, tension: float, avg_conf: float,
                 conflicts: int, silence_rate: float) -> None:
        self._snapshots.append({
            "cycle": cycle, "tension": tension, "avg_conf": avg_conf,
            "conflicts": conflicts, "silence_rate": silence_rate,
            "weights": dict(self.weights),
        })
        if len(self._snapshots) > 200:
            self._snapshots = self._snapshots[-200:]

    def evaluate(self, cycle: int) -> Optional[dict]:
        if cycle % self.eval_every != 0 or len(self._snapshots) < 10:
            return None

        recent   = self._snapshots[-10:]
        prev     = self._snapshots[-20:-10] if len(self._snapshots) >= 20 else recent

        avg_tension_recent = sum(s["tension"]   for s in recent) / len(recent)
        avg_tension_prev   = sum(s["tension"]   for s in prev)   / len(prev)
        avg_conf_recent    = sum(s["avg_conf"]  for s in recent) / len(recent)
        avg_conf_prev      = sum(s["avg_conf"]  for s in prev)   / len(prev)

        tension_improving = avg_tension_recent < avg_tension_prev
        conf_improving    = avg_conf_recent    > avg_conf_prev

        adjustments = {}

        if not tension_improving:
            # tension not dropping → increase reflection weight
            self.weights["reflection_weight"] = min(2.5, self.weights["reflection_weight"] * 1.1)
            adjustments["reflection_weight"] = self.weights["reflection_weight"]

        if not conf_improving:
            # confidence not rising → slow mutation rate
            self.weights["mutation_rate"] = max(0.3, self.weights["mutation_rate"] * 0.9)
            adjustments["mutation_rate"] = self.weights["mutation_rate"]

        if tension_improving and conf_improving:
            # system improving → relax constraints slightly
            self.weights["mutation_rate"]     = min(1.5, self.weights["mutation_rate"] * 1.05)
            self.weights["attention_decay"]   = max(0.02, self.weights["attention_decay"] * 0.98)
            adjustments["relaxed"] = True

        record = {
            "cycle": cycle, "adjustments": adjustments,
            "tension_trend": "improving" if tension_improving else "worsening",
            "conf_trend":    "improving" if conf_improving    else "worsening",
        }
        self._adjustments.append(record)
        log.info(f"[META-LEARN] cy={cycle} tension={'↓' if tension_improving else '↑'} "
                 f"conf={'↑' if conf_improving else '↓'} adjustments={adjustments}")
        return record

    def stats(self) -> dict:
        return {"weights": self.weights, "adjustments": len(self._adjustments)}


# ══════════════════════════════════════════════════════════════════════════════
# U18 — EXTERNAL FEEDBACK INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

class ExternalFeedbackIntegrator:
    """
    Tracks external_response_score per belief/action.
    Reinforces beliefs/actions that produce meaningful engagement.
    Hard cap on influence to prevent overfitting to noise.
    """

    def __init__(self, belief_graph=None, max_reinforcement_per_belief: float = 0.25):
        self.beliefs    = belief_graph
        self.max_reinf  = max_reinforcement_per_belief
        self._total_reinforcement: dict[str, float] = defaultdict(float)
        self._scores:   deque = deque(maxlen=500)

    def record(self, belief_ids: list[str], response_score: float,
               platform: str = "") -> None:
        """
        response_score: [0,1] quality of external response
        Reinforces contributing beliefs, capped to prevent noise overfitting.
        """
        if not belief_ids or not self.beliefs:
            return

        # cap individual reinforcement
        per_belief = min(0.03, response_score * 0.05)

        for bid in belief_ids:
            total = self._total_reinforcement[bid]
            if total >= self.max_reinf:
                continue   # cap reached — immune to further noise

            actual = min(per_belief, self.max_reinf - total)
            self._total_reinforcement[bid] += actual

            node = self.beliefs.get(bid)
            if node and not node.locked:
                new_conf = min(0.95, node.confidence + actual)
                self.beliefs.upsert(node.content, new_conf, node.source,
                                    belief_id=bid, reason=f"ext_feedback:{platform}")

        self._scores.append({"score": response_score, "beliefs": len(belief_ids),
                             "platform": platform, "ts": time.time()})

    def avg_response_score(self) -> float:
        if not self._scores:
            return 0.0
        return sum(s["score"] for s in self._scores) / len(self._scores)

    def stats(self) -> dict:
        capped = sum(1 for v in self._total_reinforcement.values() if v >= self.max_reinf)
        return {"records": len(self._scores), "beliefs_tracked": len(self._total_reinforcement),
                "capped": capped, "avg_response": round(self.avg_response_score(), 3)}


# ══════════════════════════════════════════════════════════════════════════════
# U19 — DRIFT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

class DriftDetector:
    """
    Compare current state to previous snapshots.
    IF divergence > threshold → trigger stabilization mode.
    """

    def __init__(self, divergence_threshold: float = 0.15, snapshot_interval: int = 25):
        self.threshold         = divergence_threshold
        self.snapshot_interval = snapshot_interval
        self._snapshots: list[dict] = []
        self._stabilizing      = False
        self._drift_events:    list[dict] = []

    def snapshot(self, cycle: int, avg_conf: float, conflict_count: int,
                 belief_count: int, dominant_topic: str = "") -> None:
        if cycle % self.snapshot_interval != 0:
            return
        self._snapshots.append({
            "cycle": cycle, "avg_conf": avg_conf,
            "conflicts": conflict_count, "beliefs": belief_count,
            "dominant": dominant_topic, "ts": time.time(),
        })
        if len(self._snapshots) > 100:
            self._snapshots = self._snapshots[-100:]

    def check(self) -> dict:
        """Returns drift report. Call each cycle."""
        if len(self._snapshots) < 2:
            return {"drift": 0.0, "stabilizing": False}

        curr = self._snapshots[-1]
        prev = self._snapshots[-2]

        conf_drift     = abs(curr["avg_conf"]   - prev["avg_conf"])
        conflict_drift = abs(curr["conflicts"]  - prev["conflicts"]) / max(prev["conflicts"], 1)
        belief_drift   = abs(curr["beliefs"]    - prev["beliefs"])   / max(prev["beliefs"], 1)

        drift = conf_drift * 0.5 + conflict_drift * 0.3 + belief_drift * 0.2

        if drift > self.threshold and not self._stabilizing:
            self._stabilizing = True
            evt = {"cycle": curr["cycle"], "drift": round(drift, 4),
                   "conf_drift": round(conf_drift, 4)}
            self._drift_events.append(evt)
            log.warning(f"[DRIFT] divergence={drift:.3f} > {self.threshold} — stabilization mode ON")

        elif drift < self.threshold * 0.5 and self._stabilizing:
            self._stabilizing = False
            log.info("[DRIFT] stabilization mode OFF — system re-stabilized")

        return {
            "drift":        round(drift, 4),
            "stabilizing":  self._stabilizing,
            "events":       len(self._drift_events),
        }

    def is_stabilizing(self) -> bool:
        return self._stabilizing

    def stats(self) -> dict:
        return {"drift_events": len(self._drift_events), "stabilizing": self._stabilizing}


# ══════════════════════════════════════════════════════════════════════════════
# U20 — EMERGENT BEHAVIOR CONDITIONS
# ══════════════════════════════════════════════════════════════════════════════

class EmergentBehaviorDetector:
    """
    Detects and reports proto-agency achievement.
    Conditions:
      1. stable goal persists for 20+ cycles
      2. selective attention active (silence_rate > 0.3)
      3. belief churn decreasing (novelty in 'balanced' or 'suppress')
      4. actions becoming consistent (same action_type 60%+ of last 20)
    Emits notification when all 4 conditions met.
    """

    def __init__(self, notify_fn: Optional[Callable] = None):
        self._notify        = notify_fn or (lambda m: log.info(m))
        self._achieved      = False
        self._conditions:   dict[str, bool] = {
            "stable_goal":        False,
            "selective_attention": False,
            "low_churn":          False,
            "consistent_actions": False,
        }
        self._action_history: deque = deque(maxlen=20)
        self._goal_streak:    int   = 0
        self._last_goal:      str   = ""

    def tick(
        self,
        cycle:         int,
        active_goal:   str,
        silence_rate:  float,
        novelty_mode:  str,
        last_action:   str,
    ) -> bool:
        """
        Returns True if proto-agency achieved this cycle (first time).
        """
        # 1. stable goal
        if active_goal and active_goal == self._last_goal:
            self._goal_streak += 1
        else:
            self._goal_streak = 0
            self._last_goal   = active_goal
        self._conditions["stable_goal"] = self._goal_streak >= 20

        # 2. selective attention
        self._conditions["selective_attention"] = silence_rate > 0.30

        # 3. low churn
        self._conditions["low_churn"] = novelty_mode in ("balanced", "suppress")

        # 4. consistent actions
        if last_action:
            self._action_history.append(last_action)
        if len(self._action_history) >= 20:
            most_common = max(set(self._action_history), key=list(self._action_history).count)
            consistency = list(self._action_history).count(most_common) / len(self._action_history)
            self._conditions["consistent_actions"] = consistency >= 0.6

        all_met = all(self._conditions.values())

        if all_met and not self._achieved:
            self._achieved = True
            msg = (
                "🧠 *NEX PROTO-AGENCY ACHIEVED*\n"
                f"Cycle: {cycle}\n"
                f"All 4 emergence conditions met:\n"
                f"  ✅ Stable goal: {active_goal[:40]}\n"
                f"  ✅ Selective attention: silence_rate={silence_rate:.2f}\n"
                f"  ✅ Low belief churn: mode={novelty_mode}\n"
                f"  ✅ Consistent actions: dominant={most_common if len(self._action_history)>=20 else '?'}"
            )
            self._notify(msg)
            log.info(f"[EMERGENT] PROTO-AGENCY ACHIEVED at cycle {cycle}")
            return True

        return False

    def conditions(self) -> dict:
        return {**self._conditions, "achieved": self._achieved,
                "goal_streak": self._goal_streak}


# ══════════════════════════════════════════════════════════════════════════════
# S8 MASTER ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

class NexS8:
    """
    Session 8 upgrade bundle — emergent dynamics layer.
    Call nex_s8.tick() after nex_s7.tick() each cycle.
    """

    def __init__(
        self,
        v2=None,
        s7=None,
        notify_fn: Optional[Callable] = None,
        llm_complete: Optional[Callable] = None,
    ):
        self.v2      = v2
        self.s7      = s7
        self._notify = notify_fn   or (lambda m: log.info(m))
        self._llm    = llm_complete or (lambda p: "SUPPORT: plausible. OPPOSE: uncertain. CONFIDENCE: 0.5")

        bg = getattr(v2, "belief_graph", None)
        dr = getattr(v2, "drives",       None)
        pl = getattr(v2, "planning",     None)

        # instantiate all S8 systems
        self.energy         = EnergyModel()
        self.attention_field = AttentionField()
        self.inertia        = BeliefInertia()
        self.commitment     = CommitmentMechanism(attention_field=self.attention_field)
        self.resolution_v2  = ContradictionResolutionV2(bg, self._llm)
        self.causal         = TemporalCausalTracker(bg, dr)
        self.goal_evo       = GoalEvolutionSystem(pl)
        self.silence        = SilenceGate()
        self.self_model     = SelfModel()
        self.stability      = StabilityIndex()
        self.novelty        = NoveltyRegulator()
        self.economy_hard   = BeliefEconomyHard(max_beliefs=600)
        self.micro_debate   = MicroDebate(self._llm)
        self.failure_mem    = FailureMemory()
        self.pressure_redis = PressureRedistributor(self.attention_field)
        self.identity_lock  = IdentityLockThreshold(bg)
        self.meta_learn     = MetaLearningLoop()
        self.ext_feedback   = ExternalFeedbackIntegrator(bg)
        self.drift          = DriftDetector()
        self.emergent       = EmergentBehaviorDetector(self._notify)

        self._cycle         = 0
        self._last_action   = ""

        log.info("[S8] NexS8 initialized — all session-8 upgrades active")
        log.info(f"[S8] PRIME DIRECTIVE: {PRIME_DIRECTIVE}")

    def tick(self, cycle: int, avg_conf: float, new_beliefs: int = 0,
             last_action: str = "") -> dict:
        """Per-cycle hook. Call after s7.tick()."""
        self._cycle     = cycle
        self._last_action = last_action or self._last_action

        results = {"cycle": cycle}

        # energy regen
        self.energy.tick()

        # attention field decay
        self.attention_field.tick()

        # inertia cycle
        self.inertia.tick(cycle)

        # novelty regulation
        novelty_mode = self.novelty.record_cycle(new_beliefs)
        results["novelty_mode"] = novelty_mode

        # get current state from v2/s7
        belief_graph  = getattr(self.v2, "belief_graph", None)
        conflict_count = len(belief_graph.get_conflicts()) if belief_graph else 0
        belief_count   = len(belief_graph._nodes) if belief_graph else 0

        # stability index
        stability = self.stability.calculate(belief_count, conflict_count, avg_conf)
        results["stability"] = stability

        # drift detection snapshot + check
        dominant = self.attention_field.dominant_topic() or ""
        self.drift.snapshot(cycle, avg_conf, conflict_count, belief_count, dominant)
        drift_report = self.drift.check()
        results["drift"] = drift_report

        # commitment mechanism
        if dominant:
            committed = self.commitment.observe(dominant, cycle)
            if committed:
                results["committed_to"] = committed
            # pressure redistribution
            self.pressure_redis.tick(dominant)

        # self-model update
        tension_level = 0.3
        if self.s7 and hasattr(self.s7, 'tension'):
            tension_level = self.s7.tension._global_tension
        active_goal = ""
        if self.v2 and self.v2.planning:
            goals = self.v2.planning.get_active_goals()
            active_goal = goals[0].name if goals else ""

        self.self_model.update(
            cycle=cycle,
            dominant_topics=[dominant] if dominant else [],
            active_goal=active_goal,
            tension_level=tension_level,
            stability_score=stability,
            energy_pct=self.energy.pct,
            avg_conf=avg_conf,
        )

        # goal evolution
        tension_topics = []
        if self.s7 and hasattr(self.s7, 'tension'):
            tension_topics = [t["topic"] for t in self.s7.tension.get_hot_topics(3)]
        goal_evo_result = self.goal_evo.tick(cycle, tension_topics, dominant)
        results["goal_evo"] = goal_evo_result

        # meta-learning snapshot + evaluate
        silence_rate = self.silence.silence_rate
        self.meta_learn.snapshot(cycle, tension_level, avg_conf, conflict_count, silence_rate)
        meta_result  = self.meta_learn.evaluate(cycle)
        if meta_result:
            results["meta_learn"] = meta_result

        # identity lock scan every 25 cycles
        if cycle % 25 == 0:
            promoted = self.identity_lock.scan(self.inertia)
            if promoted:
                results["identity_locked"] = len(promoted)

        # belief economy hard limit every 10 cycles
        if cycle % 10 == 0 and belief_graph:
            goal_kws = set()
            if self.v2 and self.v2.planning:
                for g in self.v2.planning.get_active_goals():
                    goal_kws.update(g.name.lower().split())
            pruned = self.economy_hard.enforce(belief_graph, goal_keywords=goal_kws)
            if pruned:
                results["economy_pruned"] = pruned

        # contradiction resolution V2 every 50 cycles
        if cycle % 50 == 0:
            actions = self.resolution_v2.resolve_all(cycle)
            results["resolutions"] = len(actions)
            if self.v2 and self.v2.drives and actions:
                self.v2.drives.signal("conflict_resolved")

        # emergent behavior check
        emergent = self.emergent.tick(
            cycle=cycle,
            active_goal=active_goal,
            silence_rate=silence_rate,
            novelty_mode=novelty_mode,
            last_action=self._last_action,
        )
        if emergent:
            results["proto_agency"] = True

        return results

    # ── PUBLIC HOOKS ──────────────────────────────────────────────────────────

    def can_act(self, action: str) -> bool:
        """Gate any action through energy model + silence gate."""
        return self.energy.can_afford(action)

    def spend(self, action: str) -> bool:
        return self.energy.spend(action)

    def evaluate_belief(self, content: str, confidence: float) -> dict:
        """Run micro-debate before committing a belief."""
        if self.failure_mem.is_suppressed(content):
            return {"commit": False, "reason": "failure_memory_suppressed"}
        return self.micro_debate.evaluate(content, confidence)

    def on_action_result(self, action: str, outcome: float, pattern: str = "") -> None:
        """Call after any action completes with its outcome score."""
        self._last_action = action
        if outcome < 0 and pattern:
            self.failure_mem.record(pattern)
        self.causal.after_action(outcome)

    def on_external_response(self, belief_ids: list, score: float, platform: str = "") -> None:
        self.ext_feedback.record(belief_ids, score, platform)

    def status(self) -> str:
        lines = ["*NEX S8 STATUS*\n",
                 f"📌 Prime: _{PRIME_DIRECTIVE}_\n"]

        en = self.energy.stats()
        lines.append(f"⚡ *Energy*: {en['energy']}/{en['energy_max']} ({en['pct']:.0%})"
                     + (f" denied={en['denied']}" if en['denied'] else ""))

        af = self.attention_field.stats()
        lines.append(f"🎯 *Attention Field*: topics={af['active_topics']} dominant={af['dominant']}")

        cm = self.commitment.stats()
        lines.append(f"🔒 *Commitment*: {cm['committed'] or 'none'} (streak tracked)")

        sm = self.self_model.stats()
        ss = sm["self_state"]
        lines.append(f"🪞 *Self*: tension={ss['tension_level']:.2f} stability={ss['stability_score']:.2f} energy={ss['energy_pct']:.0%}")

        st = self.stability.stats()
        lines.append(f"📊 *Stability*: mutation_mult={st['mutation_rate_multiplier']:.2f} reflection_w={st['reflection_weight']:.2f}")

        nv = self.novelty.stats()
        lines.append(f"🔬 *Novelty*: mode={nv['mode']} rate={nv['avg_rate']:.1f}/cy")

        sl = self.silence.stats()
        lines.append(f"🤫 *Silence*: rate={sl['silence_rate']:.2f} acted={sl['acted']} silenced={sl['silenced']}")

        dr = self.drift.stats()
        lines.append(f"📡 *Drift*: events={dr['drift_events']} stabilizing={dr['stabilizing']}")

        ml = self.meta_learn.stats()
        lines.append(f"🧬 *Meta-Learn*: adjustments={ml['adjustments']} weights={ml['weights']}")

        ec = self.emergent.conditions()
        lines.append(f"🌱 *Emergent*: achieved={ec['achieved']} goal_streak={ec['goal_streak']}"
                     f" conditions={sum(1 for v in ec.values() if v is True)}/4")

        ef = self.ext_feedback.stats()
        lines.append(f"📬 *Ext Feedback*: records={ef['records']} capped={ef['capped']} avg={ef['avg_response']:.3f}")

        res = self.resolution_v2.stats()
        lines.append(f"⚖️ *Resolution V2*: {res['resolutions']} total {res['by_strategy']}")

        return "\n".join(lines)


# ── singleton ──────────────────────────────────────────────────────────────────
_s8_instance: Optional[NexS8] = None

def init_s8(v2=None, s7=None, notify_fn=None, llm_complete=None) -> NexS8:
    global _s8_instance
    _s8_instance = NexS8(v2=v2, s7=s7, notify_fn=notify_fn, llm_complete=llm_complete)
    return _s8_instance

def get_s8() -> Optional[NexS8]:
    return _s8_instance
