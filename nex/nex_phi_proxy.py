"""
nex_phi_proxy.py — IIT Φ Proxy for NEX Belief Graph
=====================================================
Approximates integrated information (Φ) for NEX's belief graph.
Real Φ is NP-hard. This uses a tractable proxy:
  Φ_proxy(node) = bidirectional_edge_count × recurrence_depth × confidence_weight

Used as intrinsic reward in BeliefMarket:
  - High Φ_proxy beliefs get boosted (more causally integrated)
  - Low Φ_proxy beliefs face faster decay (isolated nodes → zombies)

Based on: IIT 4.0 (Tononi 2023), Akbari arXiv 2601.22786
"""
from __future__ import annotations
import logging, time
from typing import Optional

log = logging.getLogger("nex.phi_proxy")

_PHI_BOOST_THRESHOLD  = 0.4   # Φ_proxy above this → belief gets boosted
_PHI_DECAY_THRESHOLD  = 0.1   # Φ_proxy below this → belief faces decay


def compute_phi_proxy(
    belief_id: str,
    graph: dict,          # belief_graph.json structure
    max_depth: int = 3,
) -> float:
    """
    Compute Φ_proxy for a single belief node.

    Graph node structure (from nex_belief_graph.py):
    {
        "content": str,
        "confidence": float,
        "supports": [id, ...],
        "contradicts": [id, ...],
        "explains": [id, ...],
        "attention": float,
    }

    Returns float in [0, 1].
    """
    if belief_id not in graph:
        return 0.0

    node = graph[belief_id]
    conf = node.get("confidence", 0.5)

    # Count outgoing edges
    out_edges = (
        len(node.get("supports", [])) +
        len(node.get("explains", [])) +
        len(node.get("contradicts", []))
    )

    # Count incoming edges (bidirectional check)
    in_edges = 0
    for nid, n in graph.items():
        if nid == belief_id:
            continue
        if belief_id in n.get("supports", []) + n.get("explains", []) + n.get("contradicts", []):
            in_edges += 1

    # Bidirectional ratio — IIT cares about causal power in both directions
    total_edges = out_edges + in_edges
    if total_edges == 0:
        return 0.0

    bidir_ratio = min(out_edges, in_edges) / max(out_edges, in_edges, 1)

    # Recurrence depth — how many hops back to this node
    recurrence = _recurrence_depth(belief_id, graph, max_depth)

    # Φ_proxy formula
    phi = (
        0.35 * bidir_ratio +
        0.35 * min(1.0, recurrence / max_depth) +
        0.20 * conf +
        0.10 * min(1.0, total_edges / 10.0)
    )
    return round(min(1.0, phi), 4)


def _recurrence_depth(node_id: str, graph: dict, max_depth: int) -> int:
    """
    How many steps from node_id can we follow edges and return to node_id.
    Bounded BFS — returns depth of shortest cycle found.
    """
    if node_id not in graph:
        return 0

    visited = {node_id}
    frontier = [(node_id, 0)]
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        node = graph.get(current, {})
        neighbors = (
            node.get("supports", []) +
            node.get("explains", []) +
            node.get("contradicts", [])
        )
        for nb in neighbors:
            if nb == node_id and depth > 0:
                return depth + 1  # found cycle
            if nb not in visited:
                visited.add(nb)
                frontier.append((nb, depth + 1))
    return 0


def score_all(graph: dict) -> dict[str, float]:
    """Score every node in graph. Returns {belief_id: phi_proxy}."""
    scores = {}
    for bid in graph:
        scores[bid] = compute_phi_proxy(bid, graph)
    return scores


def phi_confidence_modifier(phi: float) -> float:
    """
    Returns a confidence delta based on Φ_proxy.
    Integrated beliefs gain confidence; isolated beliefs lose it.
    Range: [-0.05, +0.05]
    """
    if phi >= _PHI_BOOST_THRESHOLD:
        return 0.005 * (phi - _PHI_BOOST_THRESHOLD) / (1.0 - _PHI_BOOST_THRESHOLD) * 10
    if phi <= _PHI_DECAY_THRESHOLD:
        return -0.005 * (_PHI_DECAY_THRESHOLD - phi) / _PHI_DECAY_THRESHOLD * 10
    return 0.0


class PhiMonitor:
    """Runs Φ_proxy scoring on the belief graph and reports stats."""

    def __init__(self):
        self._last_scores: dict[str, float] = {}
        self._last_run: float = 0
        self._run_interval: float = 300  # every 5 min

    def tick(self, graph: dict) -> dict:
        """
        Run scoring if interval has passed.
        Returns summary stats dict.
        """
        now = time.time()
        if now - self._last_run < self._run_interval and self._last_scores:
            return self._summary()

        self._last_scores = score_all(graph)
        self._last_run = now

        summary = self._summary()
        log.info(f"[Φ] nodes={summary['nodes']} "
                 f"mean={summary['mean_phi']:.3f} "
                 f"high={summary['high_integration']} "
                 f"isolated={summary['isolated']}")
        return summary

    def _summary(self) -> dict:
        if not self._last_scores:
            return {"nodes": 0, "mean_phi": 0.0, "high_integration": 0, "isolated": 0}
        vals = list(self._last_scores.values())
        return {
            "nodes": len(vals),
            "mean_phi": round(sum(vals) / len(vals), 4),
            "max_phi": round(max(vals), 4),
            "high_integration": sum(1 for v in vals if v >= _PHI_BOOST_THRESHOLD),
            "isolated": sum(1 for v in vals if v <= _PHI_DECAY_THRESHOLD),
            "scores": self._last_scores,
        }

    def get_modifier(self, belief_id: str) -> float:
        phi = self._last_scores.get(belief_id, 0.0)
        return phi_confidence_modifier(phi)


# ── Singleton ──────────────────────────────────────────────
_monitor: Optional[PhiMonitor] = None

def get_monitor() -> PhiMonitor:
    global _monitor
    if _monitor is None:
        _monitor = PhiMonitor()
    return _monitor
