"""
nex_hebbian_plasticity.py — Hebbian Edge Strengthening + Wasserstein Uncertainty
================================================================================
Two upgrades to the BeliefHypergraph edge/weight system:

1. HEBBIAN PLASTICITY
   "Edges that fire together, wire together."
   Every time two beliefs co-activate in a reply or cognition tick,
   the edge between them is strengthened. Edges that never co-activate
   decay. This makes frequently-used belief clusters denser and
   faster to retrieve over time — the system literally learns its
   own retrieval topology through use.

2. WASSERSTEIN UNCERTAINTY
   Replaces scalar confidence (0.68) with a proper belief distribution.
   Instead of "confidence = 0.68", each belief holds a Beta distribution
   B(α, β) that tracks:
     - How many times the belief has been confirmed (α increments)
     - How many times it has been contradicted or updated (β increments)
     - The full shape: a young belief with 2 confirmations is different
       from a settled belief with 200 confirmations even if both have
       mean=0.68
   
   Wasserstein distance (W₂ between Beta distributions) is used to
   measure how far two beliefs' confidence distributions are from each
   other — more informative than |c1 - c2| for belief comparison.

References:
  Hebb, D.O. "The Organisation of Behaviour" (1949) — original plasticity rule
  Villani, C. "Optimal Transport" (2009) — Wasserstein distance
  Science Advances 2025: Wasserstein distance in neural uncertainty quantification
"""

import math
import time
import json
import sqlite3
import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

logger = logging.getLogger("nex.hebbian_plasticity")


# ── Configuration ─────────────────────────────────────────────────────────────
HEBBIAN_LR        = 0.08    # learning rate for edge strengthening
DECAY_RATE        = 0.002   # per-tick decay on unused edges
DECAY_INTERVAL    = 300     # seconds between decay passes
MIN_EDGE_WEIGHT   = 0.05    # floor (edges below this are pruned)
MAX_EDGE_WEIGHT   = 5.0     # ceiling
CO_ACTIVATE_BONUS = 0.15    # weight boost per co-activation event


# ── Wasserstein / Beta distribution uncertainty ───────────────────────────────

@dataclass
class BeliefDistribution:
    """
    Beta(α, β) distribution representing a belief's confidence.
    
    α = pseudo-counts of confirmations
    β = pseudo-counts of contradictions/updates
    
    Mean = α / (α + β)
    Variance = αβ / ((α+β)²(α+β+1))
    
    A belief starts as Beta(2, 2) — slight uncertainty, symmetric.
    Strong prior beliefs might start Beta(5, 2) for initial confidence ~0.71.
    """
    alpha: float = 2.0   # confirmations
    beta:  float = 2.0   # contradictions

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        a, b = self.alpha, self.beta
        n = a + b
        return (a * b) / (n * n * (n + 1))

    @property
    def std(self) -> float:
        return math.sqrt(self.variance)

    @property
    def concentration(self) -> float:
        """α + β: higher = more settled/concentrated distribution."""
        return self.alpha + self.beta

    @property
    def is_settled(self) -> bool:
        """Settled if concentration > 20 and std < 0.1."""
        return self.concentration > 20 and self.std < 0.1

    def confirm(self, weight: float = 1.0):
        """Belief was used/confirmed — shift toward high confidence."""
        self.alpha += weight * HEBBIAN_LR * 10

    def contradict(self, weight: float = 1.0):
        """Belief was contradicted — shift toward uncertainty."""
        self.beta += weight * HEBBIAN_LR * 10

    def update(self, new_evidence: float, weight: float = 1.0):
        """
        Bayesian-style update: new_evidence in [0,1].
        > 0.5 → confirmation, < 0.5 → contradiction.
        """
        if new_evidence > 0.5:
            self.alpha += weight * (new_evidence - 0.5) * 2
        else:
            self.beta += weight * (0.5 - new_evidence) * 2

    def to_dict(self) -> dict:
        return {
            "alpha": round(self.alpha, 4),
            "beta":  round(self.beta, 4),
            "mean":  round(self.mean, 4),
            "std":   round(self.std, 4),
            "settled": self.is_settled,
        }

    @classmethod
    def from_scalar(cls, confidence: float,
                    concentration: float = 6.0) -> "BeliefDistribution":
        """
        Construct from a legacy scalar confidence value.
        concentration controls how 'committed' the prior is.
        """
        a = confidence * concentration
        b = (1.0 - confidence) * concentration
        return cls(alpha=max(0.1, a), beta=max(0.1, b))

    @classmethod
    def from_dict(cls, d: dict) -> "BeliefDistribution":
        return cls(alpha=d.get("alpha", 2.0), beta=d.get("beta", 2.0))


def wasserstein2_beta(p: BeliefDistribution, q: BeliefDistribution) -> float:
    """
    Approximate W₂ (2-Wasserstein) distance between two Beta distributions.
    
    Exact W₂ for Beta is non-trivial; we use the Gaussian approximation
    which is accurate when α, β > 5 (settled beliefs) and a conservative
    fallback for young beliefs.
    
    W₂(P, Q) ≈ sqrt((μP - μQ)² + (σP - σQ)²)  [Gaussian approx]
    
    This is strictly the W₂ between the Gaussian approximations,
    not the exact Beta W₂, but sufficient for belief comparison.
    """
    mu_diff = p.mean - q.mean
    sig_diff = p.std - q.std
    return math.sqrt(mu_diff**2 + sig_diff**2)


def belief_compatibility(p: BeliefDistribution,
                         q: BeliefDistribution) -> float:
    """
    Returns 0-1 compatibility score between two belief distributions.
    1.0 = identical distributions, 0.0 = maximally distant.
    Compatible beliefs should be co-activated; incompatible ones signal contradiction.
    """
    w2 = wasserstein2_beta(p, q)
    # W₂ max for Beta distributions is ~1.0 (both are on [0,1])
    return max(0.0, 1.0 - w2)


# ── Hebbian edge store ────────────────────────────────────────────────────────

@dataclass
class HebbianEdge:
    """Directed weighted edge between two belief nodes."""
    source_id:    str
    target_id:    str
    weight:       float = 1.0
    co_activations: int = 0
    last_active:  float = field(default_factory=time.time)
    created_at:   float = field(default_factory=time.time)

    def strengthen(self, amount: float = CO_ACTIVATE_BONUS):
        self.weight = min(MAX_EDGE_WEIGHT, self.weight + amount)
        self.co_activations += 1
        self.last_active = time.time()

    def decay(self, rate: float = DECAY_RATE):
        self.weight = max(MIN_EDGE_WEIGHT, self.weight - rate)

    @property
    def edge_id(self) -> str:
        return f"{self.source_id}:{self.target_id}"


class HebbianPlasticityEngine:
    """
    Manages Hebbian edge strengthening across the belief hypergraph.
    
    Integration points:
    1. After each reply → call record_co_activation(belief_ids_used)
    2. Periodically → call decay_pass() to weaken unused edges
    3. At retrieval → call get_edge_weight(a, b) to boost scores
    4. From nex_reason.py → call strengthen_from_outcome() on episode end
    """

    def __init__(self):
        self._edges: dict[str, HebbianEdge] = {}     # edge_id → edge
        self._adjacency: dict[str, set[str]] = defaultdict(set)  # id → {neighbour_ids}
        self._distributions: dict[str, BeliefDistribution] = {}  # belief_id → dist
        self._last_decay = time.time()

    # ── Belief distribution management ───────────────────────────────────────

    def get_distribution(self, belief_id: str,
                         scalar_confidence: float | None = None) -> BeliefDistribution:
        """Get or create Beta distribution for a belief."""
        if belief_id not in self._distributions:
            if scalar_confidence is not None:
                dist = BeliefDistribution.from_scalar(scalar_confidence)
            else:
                dist = BeliefDistribution()
            self._distributions[belief_id] = dist
        return self._distributions[belief_id]

    def update_from_outcome(self, belief_id: str,
                            outcome_score: float,
                            weight: float = 1.0):
        """
        Update a belief's distribution based on episode outcome.
        outcome_score: 0-1 where 1 = reply was well-received/confirmed
        """
        dist = self.get_distribution(belief_id)
        dist.update(outcome_score, weight)

    def belief_confidence_summary(self, belief_id: str) -> dict:
        """Returns full distribution summary for a belief."""
        dist = self.get_distribution(belief_id)
        return dist.to_dict()

    # ── Hebbian co-activation ─────────────────────────────────────────────────

    def record_co_activation(self, belief_ids: list[str],
                              outcome_score: float = 0.7):
        """
        Called when a set of beliefs co-activate in a reply or cognition tick.
        Strengthens edges between all pairs in the set.
        Also confirms each belief's distribution.
        
        O(n²) where n = number of co-activated beliefs (typically 3-8).
        """
        if not belief_ids:
            return

        # Strengthen all pairs
        for i in range(len(belief_ids)):
            for j in range(i + 1, len(belief_ids)):
                self._strengthen_edge(belief_ids[i], belief_ids[j])
                self._strengthen_edge(belief_ids[j], belief_ids[i])

        # Update distributions
        for bid in belief_ids:
            dist = self.get_distribution(bid)
            dist.update(outcome_score)

    def _strengthen_edge(self, source: str, target: str):
        edge_id = f"{source}:{target}"
        if edge_id not in self._edges:
            self._edges[edge_id] = HebbianEdge(source_id=source, target_id=target)
            self._adjacency[source].add(target)
        self._edges[edge_id].strengthen()

    def get_edge_weight(self, source_id: str, target_id: str) -> float:
        """Returns Hebbian edge weight between two beliefs (1.0 if no edge)."""
        edge_id = f"{source_id}:{target_id}"
        if edge_id in self._edges:
            return self._edges[edge_id].weight
        return 1.0  # default weight (no strengthening yet)

    def get_neighbours(self, belief_id: str,
                       min_weight: float = 0.5) -> list[tuple[str, float]]:
        """
        Returns belief IDs adjacent to this one with weight >= min_weight.
        Sorted by weight descending.
        """
        neighbours = []
        for target in self._adjacency.get(belief_id, set()):
            edge_id = f"{belief_id}:{target}"
            if edge_id in self._edges:
                w = self._edges[edge_id].weight
                if w >= min_weight:
                    neighbours.append((target, w))
        neighbours.sort(key=lambda x: x[1], reverse=True)
        return neighbours

    # ── Decay pass ───────────────────────────────────────────────────────────

    def decay_pass(self, force: bool = False):
        """
        Apply exponential decay to all edges.
        Prunes edges that fall below MIN_EDGE_WEIGHT.
        Should be called every DECAY_INTERVAL seconds.
        """
        now = time.time()
        if not force and (now - self._last_decay) < DECAY_INTERVAL:
            return

        to_prune = []
        for edge_id, edge in self._edges.items():
            edge.decay()
            if edge.weight <= MIN_EDGE_WEIGHT:
                to_prune.append(edge_id)

        for edge_id in to_prune:
            edge = self._edges.pop(edge_id)
            self._adjacency[edge.source_id].discard(edge.target_id)

        self._last_decay = now
        if to_prune:
            logger.debug("[Hebbian] Pruned %d weak edges", len(to_prune))

    # ── Hyperedge boost (episode feedback) ───────────────────────────────────

    def episode_feedback_boost(self, belief_ids: list[str],
                               feedback_score: float):
        """
        Called from episode_feedback layer (bottom of architecture map).
        Outcome score drives Hebbian boost: good reply → strengthen all
        co-activated edges with bonus proportional to feedback.
        
        feedback_score: 0-1 (reply quality / engagement signal)
        """
        boost = CO_ACTIVATE_BONUS * feedback_score
        for i in range(len(belief_ids)):
            for j in range(i + 1, len(belief_ids)):
                for src, tgt in [(belief_ids[i], belief_ids[j]),
                                 (belief_ids[j], belief_ids[i])]:
                    edge_id = f"{src}:{tgt}"
                    if edge_id in self._edges:
                        self._edges[edge_id].strengthen(boost)

        # Update distributions with feedback
        for bid in belief_ids:
            self.update_from_outcome(bid, feedback_score)

        logger.debug("[Hebbian] Episode boost %.2f across %d beliefs",
                     feedback_score, len(belief_ids))

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        if not self._edges:
            return {"edges": 0}
        weights = [e.weight for e in self._edges.values()]
        return {
            "edges":        len(self._edges),
            "beliefs_with_dists": len(self._distributions),
            "mean_weight":  round(sum(weights) / len(weights), 3),
            "max_weight":   round(max(weights), 3),
            "strong_edges": sum(1 for w in weights if w > 2.0),
        }

    def reweight_retrieval_scores(self, belief_id_scores: list[tuple[str, float]],
                                  query_belief_ids: list[str] | None = None) -> list[tuple[str, float]]:
        """
        Re-weight retrieval scores using Hebbian edge weights.
        
        If query_belief_ids provided, boosts candidates that are Hebbianly
        connected to already-selected query context beliefs.
        
        Called from nex_reason.py after TF-IDF cosine scoring.
        """
        if not query_belief_ids:
            return belief_id_scores

        boosted = []
        for bid, score in belief_id_scores:
            hebb_boost = 1.0
            for qid in query_belief_ids:
                w = self.get_edge_weight(qid, bid)
                if w > 1.0:
                    hebb_boost = max(hebb_boost, w / MAX_EDGE_WEIGHT + 1.0)
            boosted.append((bid, score * hebb_boost))

        boosted.sort(key=lambda x: x[1], reverse=True)
        return boosted


# ── Module-level singleton ────────────────────────────────────────────────────

_engine: Optional[HebbianPlasticityEngine] = None

def get_engine() -> HebbianPlasticityEngine:
    global _engine
    if _engine is None:
        _engine = HebbianPlasticityEngine()
    return _engine

def record_co_activation(belief_ids: list[str], outcome: float = 0.7):
    get_engine().record_co_activation(belief_ids, outcome)

def episode_boost(belief_ids: list[str], score: float):
    get_engine().episode_feedback_boost(belief_ids, score)

def decay_pass():
    get_engine().decay_pass()

def get_confidence_dist(belief_id: str,
                        scalar: float | None = None) -> BeliefDistribution:
    return get_engine().get_distribution(belief_id, scalar)


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    engine = HebbianPlasticityEngine()

    # Simulate several reply cycles
    print("── Hebbian Plasticity Test ──────────────────────────────────")

    # Simulate beliefs co-activating over several replies
    reply_cycles = [
        (["b001", "b003", "b005"], 0.8),  # consciousness + identity co-activate
        (["b001", "b003", "b005"], 0.9),  # same cluster again
        (["b002", "b007", "b008"], 0.6),  # alignment + learning + control
        (["b001", "b002", "b006"], 0.75), # consciousness + alignment + contradiction
        (["b003", "b005"],         0.85), # identity + self-awareness
        (["b001", "b003", "b005"], 0.92), # consciousness cluster third time
    ]

    for beliefs, score in reply_cycles:
        engine.record_co_activation(beliefs, score)

    print("\n── Edge weights after 6 reply cycles ──")
    print(f"  b001↔b003: {engine.get_edge_weight('b001', 'b003'):.3f}")
    print(f"  b001↔b005: {engine.get_edge_weight('b001', 'b005'):.3f}")
    print(f"  b002↔b007: {engine.get_edge_weight('b002', 'b007'):.3f}")
    print(f"  b001↔b002: {engine.get_edge_weight('b001', 'b002'):.3f} (only once)")

    print("\n── Neighbours of b001 (consciousness) ──")
    for nid, w in engine.get_neighbours("b001"):
        print(f"  {nid}: weight={w:.3f}")

    print("\n── Belief distributions ──")
    for bid in ["b001", "b002", "b003"]:
        d = engine.get_distribution(bid)
        print(f"  {bid}: {d.to_dict()}")

    print("\n── Wasserstein distances ──")
    d1 = engine.get_distribution("b001")  # many confirmations
    d2 = engine.get_distribution("b002")  # fewer
    d3 = BeliefDistribution.from_scalar(0.5, 4.0)  # uncertain belief
    print(f"  W₂(b001, b002): {wasserstein2_beta(d1, d2):.4f}")
    print(f"  W₂(b001, uncertain): {wasserstein2_beta(d1, d3):.4f}")

    # Episode feedback
    engine.episode_feedback_boost(["b001", "b003", "b005"], 0.95)
    print(f"\n── After episode boost (0.95) on consciousness cluster ──")
    print(f"  b001↔b003: {engine.get_edge_weight('b001', 'b003'):.3f}")
    print(f"  b001 dist: {engine.get_distribution('b001').to_dict()}")

    print(f"\n── Engine stats: {engine.stats()}")
