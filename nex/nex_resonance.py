"""
nex_resonance.py — Belief Field Resonance Engine
=================================================
Measures directional coupling strength between belief clusters.
A→B resonance (how much cluster A drives cluster B) is distinct
from B→A (how much B drives A).

The asymmetry reveals:
  - Which clusters are DRIVING (high out-resonance)
  - Which clusters are FOLLOWING (high in-resonance)
  - Which pairs are mutually resonant (bidirectional)

Results feed the GWT spotlight as high-salience attractor signals.

Based on: attractor_map.py concept clusters + belief graph edges
"""
from __future__ import annotations
import json, time, logging, math
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.resonance")

_GRAPH_PATH   = Path.home() / ".config/nex/belief_graph.json"
_RESONANCE_LOG = Path.home() / ".config/nex/resonance_log.json"
_RUN_INTERVAL  = 180   # seconds between resonance computations


class ResonanceEngine:
    def __init__(self):
        self._last_run: float = 0
        self._resonance_matrix: dict[str, dict[str, float]] = {}
        self._drivers: list[tuple[str, float]] = []
        self._followers: list[tuple[str, float]] = []

    def _topic_of(self, node: dict) -> str:
        return node.get("topic", node.get("content", "?")[:30])

    def compute(self, graph: Optional[dict] = None) -> dict:
        """
        Compute directional resonance matrix from belief graph.
        Returns summary dict with drivers, followers, top pairs.
        """
        now = time.time()
        if now - self._last_run < _RUN_INTERVAL and self._resonance_matrix:
            return self._summary()

        if graph is None:
            try:
                if _GRAPH_PATH.exists():
                    graph = json.loads(_GRAPH_PATH.read_text())
                else:
                    return {}
            except Exception:
                return {}

        self._last_run = now

        # Build topic → node_ids mapping
        topic_nodes: dict[str, list[str]] = {}
        for nid, node in graph.items():
            t = self._topic_of(node)
            topic_nodes.setdefault(t, []).append(nid)

        topics = list(topic_nodes.keys())
        if len(topics) < 2:
            return {}

        # Compute directed edge counts between topic clusters
        # A→B: count edges from nodes in A pointing to nodes in B
        matrix: dict[str, dict[str, float]] = {t: {} for t in topics}

        for src_topic, src_nodes in topic_nodes.items():
            for sid in src_nodes:
                node = graph.get(sid, {})
                for edge_type in ("supports", "explains", "contradicts"):
                    weight = 1.0 if edge_type != "contradicts" else 0.5
                    for target_id in node.get(edge_type, []):
                        if target_id in graph:
                            tgt_topic = self._topic_of(graph[target_id])
                            if tgt_topic != src_topic:
                                matrix[src_topic][tgt_topic] = (
                                    matrix[src_topic].get(tgt_topic, 0) + weight
                                )

        # Normalize rows by node count
        for src_topic in topics:
            n_src = max(len(topic_nodes[src_topic]), 1)
            for tgt_topic in matrix[src_topic]:
                matrix[src_topic][tgt_topic] /= n_src

        self._resonance_matrix = matrix

        # Compute out-resonance (driver score) and in-resonance (follower score)
        out_res = {t: sum(matrix[t].values()) for t in topics}
        in_res  = {t: sum(matrix[s].get(t, 0) for s in topics) for t in topics}

        self._drivers   = sorted(out_res.items(),  key=lambda x: x[1], reverse=True)[:5]
        self._followers = sorted(in_res.items(),   key=lambda x: x[1], reverse=True)[:5]

        summary = self._summary()
        try:
            _RESONANCE_LOG.write_text(json.dumps({
                "timestamp": now,
                "drivers": self._drivers,
                "followers": self._followers,
                "top_pairs": summary.get("top_pairs", []),
            }, indent=2))
        except Exception:
            pass

        log.info(f"[RESONANCE] drivers={[d[0] for d in self._drivers[:3]]} "
                 f"followers={[f[0] for f in self._followers[:3]]}")

        # Submit to GWT
        try:
            from nex_gwt import get_gwb, SalienceSignal
            if self._drivers:
                top_driver = self._drivers[0]
                get_gwb().submit(SalienceSignal(
                    source="resonance",
                    content=f"Driver cluster: '{top_driver[0]}' (out-res={top_driver[1]:.2f})",
                    salience=min(1.0, 0.5 + top_driver[1] * 0.1),
                    payload={"type": "driver", "topic": top_driver[0]},
                ))
        except Exception:
            pass

        return summary

    def _summary(self) -> dict:
        # Find top mutually resonant pairs
        top_pairs = []
        seen = set()
        for src, tgts in self._resonance_matrix.items():
            for tgt, fwd in tgts.items():
                bwd = self._resonance_matrix.get(tgt, {}).get(src, 0)
                key = tuple(sorted([src, tgt]))
                if key not in seen and (fwd > 0 or bwd > 0):
                    seen.add(key)
                    top_pairs.append({
                        "a": src, "b": tgt,
                        "a_drives_b": round(fwd, 3),
                        "b_drives_a": round(bwd, 3),
                        "asymmetry":  round(abs(fwd - bwd), 3),
                    })
        top_pairs = sorted(top_pairs, key=lambda x: x["a_drives_b"] + x["b_drives_a"],
                           reverse=True)[:10]
        return {
            "drivers":   [(t, round(s, 3)) for t, s in self._drivers],
            "followers": [(t, round(s, 3)) for t, s in self._followers],
            "top_pairs": top_pairs,
        }

    def driver_topics(self, n: int = 3) -> list[str]:
        return [t for t, _ in self._drivers[:n]]

    def follower_topics(self, n: int = 3) -> list[str]:
        return [t for t, _ in self._followers[:n]]


# ── Singleton ──────────────────────────────────────────────
_re: Optional[ResonanceEngine] = None

def get_re() -> ResonanceEngine:
    global _re
    if _re is None:
        _re = ResonanceEngine()
    return _re

def compute(graph=None) -> dict:
    return get_re().compute(graph)
