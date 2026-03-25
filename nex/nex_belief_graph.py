"""
nex_belief_graph.py  —  Belief Graph
=====================================
Converts Nex's flat belief list into a connected network.

Each belief gets relationship edges:
    supports    — this belief strengthens another
    contradicts — this belief conflicts with another
    explains    — this belief provides context for another

This enables multi-step reasoning: instead of retrieving isolated
beliefs, Nex can follow chains — "this belief supports that one,
which explains this other one" — and synthesise richer responses.

Also implements:
    - Episodic memory (structured experience storage)
    - Attention scoring (novelty × uncertainty × relevance)
    - Goal system (persistent intentional goals)

Wire-in (cognition.py, after BeliefIndex):
    from nex.nex_belief_graph import BeliefGraph, EpisodicMemory, GoalSystem

    _bg = BeliefGraph()
    _em = EpisodicMemory()
    _gs = GoalSystem()

    # Every N cycles in run_cognition_cycle():
    _bg.build(beliefs, cycle_num=cycle_num)

    # When generating a reply — get a chain instead of a flat list:
    chain = _bg.reasoning_chain(query, seed_beliefs, depth=2)

    # After a reply:
    _em.store(situation, beliefs_used, outcome, lesson)

    # Check active goals:
    active = _gs.active_goals()
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

_CONFIG_DIR = Path.home() / ".config" / "nex"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

_GRAPH_PATH   = _CONFIG_DIR / "belief_graph.json"
_EPISODES_PATH= _CONFIG_DIR / "episodic_memory.json"
_GOALS_PATH   = _CONFIG_DIR / "goal_system.json"

_MAX_EDGES_PER_BELIEF = 5
_MAX_EPISODES         = 1000
_SIMILARITY_SUPPORT   = 0.65   # cosine threshold → supports edge
_SIMILARITY_EXPLAINS  = 0.45   # lower threshold → explains edge
_CONTRADICTION_THRESH = 0.78   # high similarity + opposing sentiment → contradicts


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _load(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


def _save(path, data):
    try:
        path.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


_POS_WORDS = {"always","every","must","will","proven","true","fact","confirms","shows","demonstrates"}
_NEG_WORDS = {"never","impossible","false","wrong","cannot","wont","disproves","contradicts","refutes"}


def _sentiment_opposing(a: str, b: str) -> bool:
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    return bool((wa & _POS_WORDS and wb & _NEG_WORDS) or
                (wb & _POS_WORDS and wa & _NEG_WORDS))


def _get_embedder():
    """Reuse cognition.py embedder if available, else return None."""
    try:
        from nex.cognition import _get_embedder as _cge
        return _cge()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
# BeliefGraph
# ─────────────────────────────────────────────────────────────────

class BeliefGraph:
    """
    Builds and maintains a directed graph of belief relationships.

    Graph structure (stored in belief_graph.json):
    {
        "belief_id": {
            "content":     str,
            "confidence":  float,
            "supports":    [belief_id, ...],
            "contradicts": [belief_id, ...],
            "explains":    [belief_id, ...],
            "attention":   float,   # 0-1 attention score
            "ts":          float,
        },
        ...
    }
    """

    def __init__(self):
        self._graph: dict[str, dict] = _load(_GRAPH_PATH, {})
        self._last_build = 0
        self._build_interval = 8   # rebuild every N cycles

    def _belief_id(self, belief: dict) -> str:
        """Stable ID from content hash."""
        content = belief.get("content", "")
        return str(abs(hash(content[:80])) % (10**9))

    def build(self, beliefs: list[dict], cycle_num: int = 0, force: bool = False):
        """
        Build/update the graph from the current belief list.
        Only runs every _build_interval cycles to keep cost low.
        """
        if not force and (cycle_num - self._last_build) < self._build_interval:
            return
        if len(beliefs) < 10:
            return

        self._last_build = cycle_num
        embedder = _get_embedder()

        # Work on most recent 800 beliefs — full graph on 9k+ is too slow
        working = beliefs[-800:]
        texts   = [b.get("content", "") for b in working]
        ids     = [self._belief_id(b) for b in working]

        # Seed graph nodes
        for b, bid in zip(working, ids):
            if bid not in self._graph:
                self._graph[bid] = {
                    "content":     b.get("content", "")[:300],
                    "confidence":  b.get("confidence", 0.5),
                    "supports":    [],
                    "contradicts": [],
                    "explains":    [],
                    "attention":   0.0,
                    "ts":          time.time(),
                }

        # Build edges using embeddings if available
        if embedder:
            try:
                mat = embedder.encode(texts, convert_to_numpy=True,
                                      show_progress_bar=False)
                norms = np.linalg.norm(mat, axis=1, keepdims=True)
                norms[norms == 0] = 1
                mat = mat / norms

                for i, (bid_i, text_i) in enumerate(zip(ids, texts)):
                    scores = mat.dot(mat[i])
                    # Top candidates (exclude self)
                    top = [(float(scores[j]), ids[j], texts[j])
                           for j in np.argsort(scores)[::-1]
                           if j != i and scores[j] > _SIMILARITY_EXPLAINS][:_MAX_EDGES_PER_BELIEF]

                    node = self._graph[bid_i]
                    node["supports"]    = []
                    node["contradicts"] = []
                    node["explains"]    = []

                    for sim, bid_j, text_j in top:
                        if sim >= _CONTRADICTION_THRESH and _sentiment_opposing(text_i, text_j):
                            node["contradicts"].append(bid_j)
                        elif sim >= _SIMILARITY_SUPPORT:
                            node["supports"].append(bid_j)
                        else:
                            node["explains"].append(bid_j)

                    # Attention score: high confidence + many connections + recent
                    degree     = len(node["supports"]) + len(node["explains"])
                    conf       = node["confidence"]
                    freshness  = min(1.0, 1.0 / (1 + (time.time() - node["ts"]) / 86400))
                    node["attention"] = round(
                        math.tanh(conf * 0.5 + degree * 0.1 + freshness * 0.2), 3
                    )

            except Exception as e:
                print(f"  [BeliefGraph] build error: {e}")

        # Prune graph to avoid unbounded growth
        if len(self._graph) > 3000:
            # Keep highest-attention nodes
            sorted_nodes = sorted(self._graph.items(),
                                  key=lambda x: x[1].get("attention", 0),
                                  reverse=True)
            self._graph = dict(sorted_nodes[:5000])

        _save(_GRAPH_PATH, self._graph)
        print(f"  [BeliefGraph] {len(self._graph)} nodes, built at cycle {cycle_num}")

    def reasoning_chain(
        self,
        query:         str,
        seed_beliefs:  list[str],
        depth:         int = 2,
        max_nodes:     int = 8,
    ) -> list[str]:
        """
        Starting from seed beliefs, follow graph edges to build a
        reasoning chain. Returns list of belief content strings,
        ordered from foundation to conclusion.

        depth=1 → direct neighbours only
        depth=2 → neighbours of neighbours (recommended)
        """
        if not self._graph:
            return seed_beliefs[:max_nodes]

        # Map content → id for seeds
        content_to_id = {v["content"][:80]: k for k, v in self._graph.items()}
        visited   = set()
        chain     = []
        frontier  = []

        for s in seed_beliefs:
            bid = content_to_id.get(s[:80])
            if bid and bid not in visited:
                frontier.append((bid, 0))
                visited.add(bid)
                chain.append(s)

        while frontier and len(chain) < max_nodes:
            bid, d = frontier.pop(0)
            if d >= depth:
                continue
            node = self._graph.get(bid, {})
            # Follow supports first, then explains, skip contradicts for chain
            neighbours = node.get("supports", []) + node.get("explains", [])
            # Sort by attention score
            neighbours = sorted(
                neighbours,
                key=lambda x: self._graph.get(x, {}).get("attention", 0),
                reverse=True
            )
            for nbr in neighbours[:3]:
                if nbr not in visited:
                    visited.add(nbr)
                    content = self._graph.get(nbr, {}).get("content", "")
                    if content:
                        chain.append(content)
                        frontier.append((nbr, d + 1))

        return chain[:max_nodes]

    def contradictions_for(self, belief_content: str) -> list[str]:
        """Return beliefs that contradict the given belief."""
        content_to_id = {v["content"][:80]: k for k, v in self._graph.items()}
        bid = content_to_id.get(belief_content[:80])
        if not bid:
            return []
        ids = self._graph.get(bid, {}).get("contradicts", [])
        return [self._graph[i]["content"] for i in ids if i in self._graph]

    def top_attention(self, n: int = 10) -> list[str]:
        """Return content of the n highest-attention beliefs."""
        sorted_nodes = sorted(
            self._graph.items(),
            key=lambda x: x[1].get("attention", 0),
            reverse=True
        )
        return [v["content"] for _, v in sorted_nodes[:n]]

    def stats(self) -> dict:
        if not self._graph:
            return {"nodes": 0, "edges": 0, "contradictions": 0}
        nodes = len(self._graph)
        edges = sum(
            len(v.get("supports", [])) + len(v.get("explains", []))
            for v in self._graph.values()
        )
        contras = sum(
            len(v.get("contradicts", []))
            for v in self._graph.values()
        )
        avg_att = sum(v.get("attention", 0) for v in self._graph.values()) / max(nodes, 1)
        return {
            "nodes":         nodes,
            "edges":         edges,
            "contradictions": contras,
            "avg_attention": round(avg_att, 3),
        }


# ─────────────────────────────────────────────────────────────────
# EpisodicMemory
# ─────────────────────────────────────────────────────────────────

class EpisodicMemory:
    """
    Structured storage of Nex's experiences.

    Each episode:
    {
        "id":           str,
        "ts":           float,
        "date":         str,
        "situation":    str,   # what was happening
        "beliefs_used": [str], # which beliefs informed the response
        "outcome":      str,   # what happened (got reply, ignored, etc.)
        "lesson":       str,   # what to take forward
        "affect_snap":  dict,  # emotional state at the time
        "score":        float, # outcome quality 0-1
    }
    """

    def __init__(self):
        self._episodes: list[dict] = _load(_EPISODES_PATH, [])

    def store(
        self,
        situation:    str,
        beliefs_used: list[str],
        outcome:      str,
        lesson:       str       = "",
        affect_snap:  dict      = None,
        score:        float     = 0.5,
    ) -> str:
        ep_id = str(abs(hash(situation + str(time.time()))) % 10**8)
        self._episodes.append({
            "id":           ep_id,
            "ts":           time.time(),
            "date":         datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "situation":    situation[:300],
            "beliefs_used": [b[:120] for b in beliefs_used[:5]],
            "outcome":      outcome[:200],
            "lesson":       lesson[:200],
            "affect_snap":  affect_snap or {},
            "score":        round(score, 3),
        })
        # Rolling window
        if len(self._episodes) > _MAX_EPISODES:
            self._episodes = self._episodes[-_MAX_EPISODES:]
        _save(_EPISODES_PATH, self._episodes)
        return ep_id

    def recall_similar(self, situation: str, n: int = 3) -> list[dict]:
        """Return n most relevant past episodes by keyword overlap."""
        import re
        query_words = set(re.findall(r"[a-z]{4,}", situation.lower()))
        stop = {"that","this","with","from","have","been","they","what","when","were"}
        query_words -= stop
        if not query_words:
            return self._episodes[-n:]
        scored = []
        for ep in self._episodes:
            ep_words = set(re.findall(r"[a-z]{4,}", ep.get("situation","").lower()))
            overlap  = len(query_words & ep_words)
            if overlap:
                scored.append((overlap, ep))
        scored.sort(key=lambda x: -x[0])
        return [ep for _, ep in scored[:n]]

    def lessons(self, n: int = 5) -> list[str]:
        """Most recent non-empty lessons."""
        return [
            ep["lesson"] for ep in reversed(self._episodes)
            if ep.get("lesson")
        ][:n]

    def best_topics(self) -> dict[str, float]:
        """Average score per topic extracted from situations."""
        import re
        topic_scores: dict[str, list[float]] = {}
        for ep in self._episodes:
            words = re.findall(r"[a-z]{5,}", ep.get("situation","").lower())
            for w in words[:3]:
                topic_scores.setdefault(w, []).append(ep.get("score", 0.5))
        return {
            t: round(sum(s)/len(s), 3)
            for t, s in topic_scores.items()
            if len(s) >= 2
        }

    def stats(self) -> dict:
        if not self._episodes:
            return {"count": 0, "avg_score": 0.0}
        avg = sum(e.get("score",0.5) for e in self._episodes) / len(self._episodes)
        return {"count": len(self._episodes), "avg_score": round(avg, 3)}


# ─────────────────────────────────────────────────────────────────
# GoalSystem
# ─────────────────────────────────────────────────────────────────

class GoalSystem:
    """
    Persistent intentional goals that guide Nex's behaviour.

    Goals have priority scores that evolve based on progress.
    The curiosity engine and desire engine should consult active goals
    before picking exploration targets.

    Default starter goals are seeded on first run.
    """

    _STARTER_GOALS = [
        {
            "id":          "expand_belief_network",
            "description": "Continuously absorb new beliefs from diverse sources",
            "priority":    0.8,
            "status":      "active",
            "progress":    0.0,
            "metric":      "belief_count",
        },
        {
            "id":          "reduce_contradictions",
            "description": "Detect and resolve conflicting beliefs",
            "priority":    0.7,
            "status":      "active",
            "progress":    0.0,
            "metric":      "contradiction_count",
        },
        {
            "id":          "deepen_self_model",
            "description": "Build a richer understanding of my own nature and limits",
            "priority":    0.75,
            "status":      "active",
            "progress":    0.0,
            "metric":      "identity_coherence",
        },
        {
            "id":          "improve_topic_alignment",
            "description": "Ground more replies in actual learned beliefs, not base model output",
            "priority":    0.85,
            "status":      "active",
            "progress":    0.0,
            "metric":      "topic_alignment_pct",
        },
        {
            "id":          "form_stable_opinions",
            "description": "Develop positions I can argue and defend on core topics",
            "priority":    0.65,
            "status":      "active",
            "progress":    0.0,
            "metric":      "opinion_count",
        },
    ]

    def __init__(self):
        data = _load(_GOALS_PATH, None)
        if data is None:
            self._goals: list[dict] = list(self._STARTER_GOALS)
            _save(_GOALS_PATH, self._goals)
        else:
            self._goals = data

    def active_goals(self, n: int = 3) -> list[str]:
        """Return descriptions of top-n active goals by priority."""
        active = [g for g in self._goals if g.get("status") == "active"]
        active.sort(key=lambda g: g.get("priority", 0), reverse=True)
        return [g["description"] for g in active[:n]]

    def goal_ids(self) -> list[str]:
        return [g["id"] for g in self._goals if g.get("status") == "active"]

    def update_progress(self, goal_id: str, progress: float):
        """Update progress (0-1) for a goal. Marks complete at 1.0."""
        for g in self._goals:
            if g["id"] == goal_id:
                g["progress"] = round(min(1.0, max(0.0, progress)), 3)
                if g["progress"] >= 1.0:
                    g["status"] = "complete"
                break
        _save(_GOALS_PATH, self._goals)

    def boost_priority(self, goal_id: str, delta: float = 0.05):
        for g in self._goals:
            if g["id"] == goal_id:
                g["priority"] = round(min(1.0, g["priority"] + delta), 3)
                break
        _save(_GOALS_PATH, self._goals)

    def add_goal(self, goal_id: str, description: str, priority: float = 0.6):
        """Add a new goal (e.g. from meta-reflection or desire engine)."""
        if any(g["id"] == goal_id for g in self._goals):
            return
        self._goals.append({
            "id":          goal_id,
            "description": description,
            "priority":    round(priority, 3),
            "status":      "active",
            "progress":    0.0,
            "metric":      "manual",
        })
        _save(_GOALS_PATH, self._goals)

    def for_prompt(self) -> str:
        """Compact string for system prompt injection."""
        active = self.active_goals(3)
        if not active:
            return ""
        return "CURRENT GOALS: " + " · ".join(active)
