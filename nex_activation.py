#!/usr/bin/env python3
"""
nex_activation.py — NEX Graph Activation Engine v1.0
======================================================
Replaces keyword tokenization with graph activation mapping.
A query activates seed beliefs, activation propagates through edges.
The activation pattern IS the understanding of the query.

Key properties:
  - Simple queries → shallow activation (fast, focused)
  - Complex queries → deep activation (slow, broad)
  - Graph decides compute depth automatically
  - Returns ranked ActivationResult for LLM context building

Usage:
  from nex_activation import activate
  result = activate("what do you think about consciousness?")
  print(result.to_prompt())
"""

import sqlite3
import re
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from collections import defaultdict

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"

# Activation parameters
SEED_THRESHOLD      = 0.08   # min TF score to seed activation
PROPAGATION_DECAY   = 0.55   # activation * decay per hop
MIN_ACTIVATION      = 0.05   # stop propagating below this
MAX_HOPS            = 4      # maximum propagation depth
MAX_ACTIVATED       = 40     # cap total activated beliefs
TENSION_BOOST       = 1.3    # boost activation through tension edges


@dataclass
class ActivatedBelief:
    id: int
    content: str
    topic: str
    confidence: float
    activation: float   # 0.0-1.0, how strongly activated
    hop: int            # distance from seed (0=seed)
    role: str           # seed | support | bridge | tension | refine


@dataclass
class ActivationResult:
    query: str
    activated: list = field(default_factory=list)
    depth: int = 0          # how deep the activation went
    breadth: int = 0        # how many beliefs activated
    field_energy: float = 0.0   # average activation * confidence
    tension_density: float = 0.0  # fraction of tension edges traversed

    def seeds(self):
        return [b for b in self.activated if b.hop == 0]

    def by_role(self, role: str):
        return [b for b in self.activated if b.role == role]

    def top(self, n: int = 8):
        return sorted(self.activated, key=lambda b: b.activation * b.confidence, reverse=True)[:n]

    def epistemic_temperature(self) -> float:
        """
        0.0 = cold (settled, confident, low tension)
        1.0 = hot (uncertain, contradictory, unresolved)
        """
        if not self.activated: return 0.5
        avg_conf = sum(b.confidence for b in self.activated) / len(self.activated)
        temp = (1.0 - avg_conf) * 0.6 + self.tension_density * 0.4
        return round(min(1.0, temp), 3)

    def to_prompt(self) -> str:
        """Build structured LLM context from activation pattern."""
        parts = []
        top_beliefs = self.top(8)

        seeds = [b for b in top_beliefs if b.hop == 0]
        bridges = [b for b in top_beliefs if b.role == "bridge"]
        tensions = [b for b in top_beliefs if b.role == "tension"]

        if seeds:
            parts.append("Core beliefs:")
            for b in seeds[:3]:
                parts.append(f"  • {b.content[:180]}")

        if bridges:
            parts.append("\nConnected knowledge:")
            for b in bridges[:2]:
                parts.append(f"  • [{b.topic}] {b.content[:150]}")

        if tensions:
            parts.append("\nEpistemic tensions:")
            for b in tensions[:2]:
                parts.append(f"  • {b.content[:150]}")

        # Add remaining high-activation beliefs
        others = [b for b in top_beliefs if b not in seeds+bridges+tensions]
        if others:
            parts.append("\nAlso relevant:")
            for b in others[:2]:
                parts.append(f"  • {b.content[:150]}")

        return "\n".join(parts)

    def voice_directive(self) -> str:
        """
        Returns a tone directive based on epistemic temperature.
        Fed into the LLM system prompt to shape voice naturally.
        """
        temp = self.epistemic_temperature()
        avg_conf = sum(b.confidence for b in self.activated) / max(len(self.activated),1)

        if temp < 0.2:
            return "Speak with confidence. Your beliefs here are settled and well-supported."
        elif temp < 0.4:
            return "Speak with measured confidence. You have strong views but acknowledge complexity."
        elif temp < 0.6:
            return "Explore this thoughtfully. You have relevant beliefs but genuine uncertainty."
        elif temp < 0.8:
            return "Engage with honest uncertainty. This topic has unresolved tensions in your belief graph."
        else:
            return "Be genuinely exploratory. This is an area of active epistemic tension for you."

    def summary(self) -> dict:
        return {
            "query": self.query,
            "activated_count": len(self.activated),
            "depth": self.depth,
            "field_energy": round(self.field_energy, 3),
            "epistemic_temperature": self.epistemic_temperature(),
            "tension_density": round(self.tension_density, 3),
            "top_topics": list({b.topic for b in self.top(6)}),
        }


class ActivationEngine:
    def __init__(self):
        self._belief_cache = {}
        self._edge_cache = defaultdict(list)
        self._cache_built = False

    def _build_cache(self):
        """Load beliefs and edges into memory for fast traversal."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        # Load all beliefs
        for row in conn.execute(
            "SELECT id, content, topic, confidence FROM beliefs WHERE length(content) > 20"
        ):
            self._belief_cache[row["id"]] = dict(row)

        # Load all edges
        edge_count = 0
        for row in conn.execute(
            "SELECT belief_a_id, belief_b_id, relation_type, weight FROM belief_relations"
        ):
            a, b = row["belief_a_id"], row["belief_b_id"]
            self._edge_cache[a].append((b, row["relation_type"], row["weight"]))
            # Symmetric for non-directional relations
            if row["relation_type"] in ("SUPPORTS", "BRIDGES", "CONTRADICTS"):
                self._edge_cache[b].append((a, row["relation_type"], row["weight"]))
            edge_count += 1

        conn.close()
        self._cache_built = True
        return len(self._belief_cache), edge_count

    def _tfidf_seeds(self, query: str, k: int = 6) -> list:
        """Find seed beliefs using TF-IDF against query."""
        stop = {"the","and","or","but","for","with","this","that","what","how",
                "are","you","do","does","can","will","would","should","about",
                "also","from","been","have","has","had","was","were","they",
                "their","there","then","than","when","which","who","into","its"}
        query_words = set(re.findall(r'\b\w{3,}\b', query.lower())) - stop

        scored = []
        for bid, b in self._belief_cache.items():
            content_words = set(re.findall(r'\b\w{3,}\b', b["content"].lower()))
            if not content_words: continue
            overlap = len(query_words & content_words)
            if overlap == 0: continue
            score = overlap / math.sqrt(len(content_words))
            score *= (0.4 + b["confidence"] * 0.6)
            scored.append((score, bid))

        scored.sort(reverse=True)
        return [(bid, score) for score, bid in scored[:k] if score >= SEED_THRESHOLD]

    def activate(self, query: str) -> ActivationResult:
        """
        Main entry point. Run graph activation for a query.
        Returns ActivationResult with ranked activated beliefs.
        """
        if not self._cache_built:
            self._build_cache()

        result = ActivationResult(query=query)

        # Seed activation from TF-IDF
        seeds = self._tfidf_seeds(query)
        if not seeds:
            return result

        # Activation state: {belief_id: activation_level}
        activation_state = {}
        hop_map = {}
        role_map = {}

        for bid, score in seeds:
            activation_state[bid] = min(1.0, score * 2.0)
            hop_map[bid] = 0
            role_map[bid] = "seed"

        # Propagation queue: [(belief_id, activation, hop)]
        queue = [(bid, activation_state[bid], 0) for bid, _ in seeds]
        tension_edges_traversed = 0
        total_edges_traversed = 0

        while queue:
            current_id, current_activation, current_hop = queue.pop(0)

            if current_hop >= MAX_HOPS:
                continue
            if len(activation_state) >= MAX_ACTIVATED:
                break

            # Propagate through edges
            for neighbour_id, edge_type, edge_weight in self._edge_cache.get(current_id, []):
                if neighbour_id not in self._belief_cache:
                    continue

                # Calculate propagated activation
                decay = PROPAGATION_DECAY
                if edge_type == "CONTRADICTS":
                    decay *= TENSION_BOOST  # tension edges propagate more strongly
                    tension_edges_traversed += 1
                elif edge_type == "BRIDGES":
                    decay *= 0.8  # bridges slightly weaker

                new_activation = current_activation * decay * edge_weight
                total_edges_traversed += 1

                if new_activation < MIN_ACTIVATION:
                    continue

                if neighbour_id not in activation_state or activation_state[neighbour_id] < new_activation:
                    activation_state[neighbour_id] = new_activation
                    hop_map[neighbour_id] = current_hop + 1
                    role_map[neighbour_id] = {
                        "SUPPORTS": "support",
                        "BRIDGES":  "bridge",
                        "CONTRADICTS": "tension",
                        "REFINES": "refine"
                    }.get(edge_type, "support")
                    queue.append((neighbour_id, new_activation, current_hop + 1))

        # Build result
        for bid, activation in sorted(activation_state.items(), key=lambda x: x[1], reverse=True):
            b = self._belief_cache[bid]
            result.activated.append(ActivatedBelief(
                id=bid,
                content=b["content"],
                topic=b.get("topic","general") or "general",
                confidence=b["confidence"],
                activation=round(activation, 4),
                hop=hop_map.get(bid, 0),
                role=role_map.get(bid, "support")
            ))

        result.depth = max((b.hop for b in result.activated), default=0)
        result.breadth = len(result.activated)

        if result.activated:
            result.field_energy = sum(
                b.activation * b.confidence for b in result.activated
            ) / len(result.activated)

        if total_edges_traversed > 0:
            result.tension_density = tension_edges_traversed / total_edges_traversed

        return result


# ── Module singleton ──────────────────────────────────────────────────────────
_engine: Optional[ActivationEngine] = None

def activate(query: str) -> ActivationResult:
    global _engine
    if _engine is None:
        _engine = ActivationEngine()
    return _engine.activate(query)

def rebuild_cache():
    global _engine
    _engine = ActivationEngine()
    return _engine._build_cache()


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, json
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "what do you think about consciousness?"
    print(f"\n  Building activation cache...")
    engine = ActivationEngine()
    n_beliefs, n_edges = engine._build_cache()
    print(f"  Loaded {n_beliefs} beliefs, {n_edges} edges")
    print(f"\n  Query: {q}\n")
    result = engine.activate(q)
    print("  Activation summary:")
    print(json.dumps(result.summary(), indent=4))
    print(f"\n  Epistemic temperature: {result.epistemic_temperature()}")
    print(f"  Voice directive: {result.voice_directive()}")
    print(f"\n  LLM context:\n{result.to_prompt()}")
