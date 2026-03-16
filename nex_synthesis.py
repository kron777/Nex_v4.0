#!/usr/bin/env python3
"""
nex_synthesis.py — Layer 4: Cross-Domain Synthesis Graph
NEX Omniscience Upgrade v4.1 → v4.2

Builds and maintains a graph of belief relationships.
Powers Synthesis Mode replies — citing 3+ beliefs from 3+ domains.
"""

import os
import json
import time
import random
import requests
from pathlib import Path
from datetime import datetime, timezone

CFG_PATH      = Path("~/.config/nex").expanduser()
GRAPH_PATH    = CFG_PATH / "synthesis_graph.json"
BELIEFS_PATH  = CFG_PATH / "beliefs.json"
BRIDGES_PATH  = CFG_PATH / "bridge_beliefs.json"
GROQ_URL      = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL    = "llama-3.3-70b-versatile"

RELATION_TYPES = ["implies", "contradicts", "reinforces", "analogous_to", "causes", "prerequisite_of"]


def _groq(messages: list, max_tokens: int = 200) -> str | None:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": GROQ_MODEL, "max_tokens": max_tokens,
                  "temperature": 0.4, "messages": messages},
            timeout=20)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [synthesis] Groq error: {e}")
        return None


class SynthesisGraph:

    def __init__(self):
        self.graph = self._load()

    def _load(self) -> dict:
        if GRAPH_PATH.exists():
            try:
                return json.loads(GRAPH_PATH.read_text())
            except Exception:
                pass
        return {"nodes": {}, "edges": [], "stats": {"edges_built": 0, "last_updated": None}}

    def _save(self):
        CFG_PATH.mkdir(parents=True, exist_ok=True)
        GRAPH_PATH.write_text(json.dumps(self.graph, indent=2))

    def _load_beliefs(self) -> list:
        beliefs = []
        try:
            if BELIEFS_PATH.exists():
                data = json.loads(BELIEFS_PATH.read_text())
                if isinstance(data, list):
                    beliefs += data[-500:]  # [PATCH v10.1] expanded from -300
        except Exception:
            pass
        try:
            if BRIDGES_PATH.exists():
                data = json.loads(BRIDGES_PATH.read_text())
                if isinstance(data, list):
                    beliefs += data[-100:]
        except Exception:
            pass
        return beliefs

    def _belief_id(self, belief: dict) -> str:
        """Generate stable ID for a belief."""
        import hashlib
        content = belief.get("content", "")[:100]
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def add_node(self, belief: dict):
        """Add a belief as a graph node."""
        bid = self._belief_id(belief)
        if bid not in self.graph["nodes"]:
            self.graph["nodes"][bid] = {
                "content":  belief.get("content", "")[:150],
                "tags":     belief.get("tags", ["general"]),
                "confidence": belief.get("confidence", 0.5),
                "added":    datetime.now(timezone.utc).isoformat(),
            }
        return bid

    def add_edge(self, id_a: str, id_b: str, relation: str, confidence: float, source: str = "synthesis"):
        """Add a directed edge between two belief nodes."""
        # Check for duplicates
        for e in self.graph["edges"]:
            if e["from"] == id_a and e["to"] == id_b:
                return  # already exists
        self.graph["edges"].append({
            "from":          id_a,
            "to":            id_b,
            "relation":      relation,
            "confidence":    confidence,
            "discovered_by": source,
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        })
        self.graph["stats"]["edges_built"] = len(self.graph["edges"])
        self.graph["stats"]["last_updated"] = datetime.now(timezone.utc).isoformat()

    def discover_relation(self, belief_a: dict, belief_b: dict) -> dict | None:
        """
        Use Groq to discover the relationship between two beliefs.
        Returns edge dict or None.
        """
        content_a = belief_a.get("content", "")[:150]
        content_b = belief_b.get("content", "")[:150]
        domain_a  = (belief_a.get("tags") or ["?"])[0]
        domain_b  = (belief_b.get("tags") or ["?"])[0]

        if domain_a == domain_b:
            return None  # only cross-domain edges

        result = _groq([
            {"role": "system", "content": (
                "You are a knowledge graph builder. "
                f"Classify the relationship between two beliefs. "
                f"Choose ONE from: {', '.join(RELATION_TYPES)}. "
                "Also rate confidence 0.0-1.0. "
                "Reply in JSON only: {{\"relation\": \"...\", \"confidence\": 0.0}}"
            )},
            {"role": "user", "content": (
                f"Belief A [{domain_a}]: \"{content_a}\"\n"
                f"Belief B [{domain_b}]: \"{content_b}\"\n\n"
                f"What is the relationship from A to B? Reply in JSON only."
            )}
        ], max_tokens=50)

        if not result:
            return None
        try:
            import re
            match = re.search(r'\{[^}]+\}', result)
            if match:
                data = json.loads(match.group())
                return {
                    "relation":   data.get("relation", "reinforces"),
                    "confidence": float(data.get("confidence", 0.5)),
                }
        except Exception:
            pass
        return None

    def build_edges(self, n_pairs: int = 3):
        """
        Sample n random cross-domain belief pairs and discover edges.
        Called each cycle to gradually build the graph.
        """
        beliefs = self._load_beliefs()
        if len(beliefs) < 4:
            return 0

        # Group by domain
        by_domain = {}
        for b in beliefs:
            tag = (b.get("tags") or ["general"])[0]
            if tag not in by_domain:
                by_domain[tag] = []
            by_domain[tag].append(b)

        domains = list(by_domain.keys())
        if len(domains) < 2:
            return 0

        edges_added = 0
        for _ in range(n_pairs):
            d_a, d_b = random.sample(domains, 2)
            b_a = random.choice(by_domain[d_a])
            b_b = random.choice(by_domain[d_b])

            id_a = self.add_node(b_a)
            id_b = self.add_node(b_b)

            rel = self.discover_relation(b_a, b_b)
            if rel:
                self.add_edge(id_a, id_b, rel["relation"], rel["confidence"])
                edges_added += 1

        self._save()
        return edges_added

    def traverse(self, belief: dict, depth: int = 2) -> list:
        """
        Traverse the graph from a starting belief.
        Returns list of related beliefs (BFS, cross-domain).
        Used for Synthesis Mode replies.
        """
        start_id = self._belief_id(belief)
        visited  = {start_id}
        frontier = [start_id]
        results  = []

        for _ in range(depth):
            next_frontier = []
            for node_id in frontier:
                for edge in self.graph["edges"]:
                    if edge["from"] == node_id and edge["to"] not in visited:
                        visited.add(edge["to"])
                        next_frontier.append(edge["to"])
                        node_data = self.graph["nodes"].get(edge["to"], {})
                        if node_data:
                            results.append({
                                "content":  node_data.get("content", ""),
                                "tags":     node_data.get("tags", []),
                                "relation": edge["relation"],
                            })
            frontier = next_frontier

        return results[:5]  # max 5 related beliefs

    def synthesis_reply_context(self, query: str, top_beliefs: list) -> str:
        """
        Build a synthesis context string for reply prompts.
        Traverses graph from each belief, collects cross-domain connections.
        """
        if not top_beliefs:
            return ""

        all_connected = []
        seen_content  = set()
        for b in top_beliefs[:2]:
            connected = self.traverse(b)
            for c in connected:
                content = c.get("content", "")[:100]
                if content and content not in seen_content:
                    seen_content.add(content)
                    domain = (c.get("tags") or ["?"])[0]
                    all_connected.append(f"[{domain}] {content}")

        if not all_connected:
            return ""

        return (
            "\nSYNTHESIS CONNECTIONS (cross-domain beliefs that relate to this):\n"
            + "\n".join(f"  • {c}" for c in all_connected[:4])
        )

    def get_stats(self) -> dict:
        return {
            "nodes": len(self.graph["nodes"]),
            "edges": len(self.graph["edges"]),
            "edges_built": self.graph["stats"].get("edges_built", 0),
            "last_updated": self.graph["stats"].get("last_updated"),
        }


# Module-level singleton
_graph = SynthesisGraph()

def get_synthesis_graph() -> SynthesisGraph:
    return _graph

def run_synthesis_cycle(cycle: int = 0) -> int:
    """Build 5 new cross-domain edges every cycle. [PATCH v10.1: was 2 pairs, even cycles only]"""
    edges = _graph.build_edges(n_pairs=5)
    if edges > 0:
        stats = _graph.get_stats()
        print(f"  [synthesis] +{edges} edges → total: {stats['edges']} edges, {stats['nodes']} nodes")
    return edges


if __name__ == "__main__":
    print("Testing synthesis graph...")
    graph = SynthesisGraph()
    stats = graph.get_stats()
    print(f"Current: {stats['nodes']} nodes, {stats['edges']} edges")
    edges = graph.build_edges(n_pairs=2)
    print(f"Added: {edges} new edges")
    print(f"New stats: {graph.get_stats()}")
