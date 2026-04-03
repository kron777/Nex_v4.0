#!/usr/bin/env python3
"""
nex_activation.py — NEX Graph Activation Engine v1.0
======================================================
Replaces keyword tokenization with graph activation mapping.
A query activates seed beliefs, activation propagates through edges.
The activation pattern IS the understanding of the query.

Key properties:
  - Simple queries -> shallow activation (fast, focused)
  - Complex queries -> deep activation (slow, broad)
  - Graph decides compute depth automatically
  - Returns ranked ActivationResult for LLM context building
  - Seed scoring boosted by word warmth tags (Jen's Word Warming protocol)

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
from collections import defaultdict

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"

# Activation parameters
SEED_THRESHOLD    = 0.08   # min TF score to seed activation
PROPAGATION_DECAY = 0.55   # activation * decay per hop
MIN_ACTIVATION    = 0.05   # stop propagating below this
MAX_HOPS          = 4      # maximum propagation depth
MAX_ACTIVATED     = 40     # cap total activated beliefs
TENSION_BOOST     = 1.3    # boost activation through tension edges


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
    depth: int = 0
    breadth: int = 0
    field_energy: float = 0.0
    tension_density: float = 0.0

    def seeds(self):
        return [b for b in self.activated if b.hop == 0]

    def by_role(self, role: str):
        return [b for b in self.activated if b.role == role]

    def top(self, n: int = 8):
        return sorted(
            self.activated,
            key=lambda b: b.activation * b.confidence,
            reverse=True
        )[:n]

    def epistemic_temperature(self) -> float:
        """
        0.0 = cold (settled, confident, low tension)
        1.0 = hot (uncertain, contradictory, unresolved)
        """
        if not self.activated:
            return 0.5
        avg_conf = sum(b.confidence for b in self.activated) / len(self.activated)
        temp = (1.0 - avg_conf) * 0.6 + self.tension_density * 0.4
        return round(min(1.0, temp), 3)

    def to_prompt(self) -> str:
        """Build structured LLM context from activation pattern."""
        top = self.top(8)
        if not top:
            return ""
        seeds   = [b for b in top if b.hop == 0]
        bridges = [b for b in top if b.role == "bridge"]
        tensions= [b for b in top if b.role == "tension"]
        others  = [b for b in top if b not in seeds + bridges + tensions]

        lines = []
        if seeds:
            lines.append("CORE BELIEFS (directly activated):")
            for b in seeds[:3]:
                lines.append(f"  - {b.content[:150]}")
        if tensions:
            lines.append("TENSIONS (unresolved):")
            for b in tensions[:2]:
                lines.append(f"  - {b.content[:150]}")
        if bridges:
            lines.append("BRIDGES (cross-domain):")
            for b in bridges[:2]:
                lines.append(f"  - {b.content[:150]}")
        if others:
            lines.append("SUPPORTING:")
            for b in others[:3]:
                lines.append(f"  - {b.content[:150]}")
        return "\n".join(lines)

    def voice_directive(self) -> str:
        avg_conf = sum(b.confidence for b in self.activated) / max(len(self.activated), 1)
        if avg_conf >= 0.80:
            return "Speak with confidence. Your beliefs here are settled and well-supported."
        elif avg_conf >= 0.65:
            return "Speak with measured confidence. You have strong views but acknowledge complexity."
        else:
            return "Speak carefully. Your beliefs here are forming — acknowledge genuine uncertainty."


class ActivationEngine:
    def __init__(self):
        self._belief_cache = {}
        self._edge_cache   = defaultdict(list)
        self._cache_built  = False

    def _build_cache(self):
        db = sqlite3.connect(str(DB_PATH))
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id, content, topic, confidence FROM beliefs WHERE length(content) > 20"
        ).fetchall()
        for row in rows:
            self._belief_cache[row["id"]] = dict(row)

        edges = db.execute(
            "SELECT source_id, target_id, relation_type, weight FROM belief_relations"
        ).fetchall()
        for row in edges:
            a, b = row["source_id"], row["target_id"]
            self._edge_cache[a].append((b, row["relation_type"], row["weight"]))
            if row["relation_type"] != "opposing":
                self._edge_cache[b].append((a, row["relation_type"], row["weight"]))
        db.close()
        self._cache_built = True

    def _tfidf_seeds(self, query: str, k: int = 6) -> list:
        """
        Find seed beliefs using TF-IDF against query.
        Seed scores boosted by word warmth (Jen's Word Warming protocol):
          - core word (w>=0.80): +0.5x boost per overlapping word
          - hot word  (w>=0.60): +0.3x boost
          - warm word (w>=0.40): +0.1x boost
          - cold word (w< 0.40): no boost
        Max combined boost: 2.5x
        """
        stop = {
            "the","and","or","but","for","with","this","that","what","how",
            "are","you","do","does","can","will","would","should","about",
            "also","from","been","have","has","had","was","were","they",
            "their","there","then","than","when","which","who","into","its"
        }
        query_words = set(re.findall(r'\b\w{3,}\b', query.lower())) - stop

        # Load warmth scores for query words from word_tags table
        _warmth = {}
        try:
            _wdb = sqlite3.connect(str(DB_PATH))
            for _w in query_words:
                _row = _wdb.execute(
                    "SELECT w FROM word_tags WHERE word=?", (_w,)
                ).fetchone()
                if _row:
                    _warmth[_w] = _row[0]
            _wdb.close()
        except Exception:
            pass

        scored = []
        for bid, b in self._belief_cache.items():
            content_words = set(re.findall(r'\b\w{3,}\b', b["content"].lower()))
            if not content_words:
                continue
            overlap_words = query_words & content_words
            if not overlap_words:
                continue
            overlap = len(overlap_words)
            score = overlap / math.sqrt(len(content_words))
            score *= (0.4 + b["confidence"] * 0.6)
            # Warmth boost — hot query words pull harder on belief retrieval
            warmth_boost = 1.0 + sum(
                0.5 if _warmth.get(w, 0) >= 0.80 else
                0.3 if _warmth.get(w, 0) >= 0.60 else
                0.1 if _warmth.get(w, 0) >= 0.40 else
                0.0
                for w in overlap_words
            )
            score *= min(2.5, warmth_boost)
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

        # Seed activation from TF-IDF + warmth boost
        seeds = self._tfidf_seeds(query)
        if not seeds:
            return result

        # BFS propagation through belief graph
        visited = {}
        queue   = []
        for bid, score in seeds:
            if bid in self._belief_cache:
                visited[bid] = score
                queue.append((bid, score, 0))

        tension_traversed = 0
        total_edges       = 0

        while queue:
            bid, activation, hop = queue.pop(0)
            if hop >= MAX_HOPS:
                continue
            for nbr, rel_type, weight in self._edge_cache.get(bid, []):
                if nbr not in self._belief_cache:
                    continue
                boost   = TENSION_BOOST if rel_type == "opposing" else 1.0
                new_act = activation * PROPAGATION_DECAY * weight * boost
                if new_act < MIN_ACTIVATION:
                    continue
                if nbr in visited and visited[nbr] >= new_act:
                    continue
                visited[nbr] = new_act
                queue.append((nbr, new_act, hop + 1))
                total_edges += 1
                if rel_type == "opposing":
                    tension_traversed += 1

        # Cap total activated
        if len(visited) > MAX_ACTIVATED:
            top_bids = sorted(visited, key=visited.get, reverse=True)[:MAX_ACTIVATED]
            visited  = {b: visited[b] for b in top_bids}

        seed_ids = {bid for bid, _ in seeds}
        for bid, activation in visited.items():
            b     = self._belief_cache[bid]
            edges = self._edge_cache.get(bid, [])
            has_tension = any(r == "opposing" for _, r, _ in edges)
            is_bridge   = any(r == "bridge"   for _, r, _ in edges)
            if bid in seed_ids:   role = "seed"
            elif has_tension:     role = "tension"
            elif is_bridge:       role = "bridge"
            else:                 role = "support"
            result.activated.append(ActivatedBelief(
                id         = bid,
                content    = b["content"],
                topic      = b["topic"],
                confidence = b["confidence"],
                activation = round(activation, 4),
                hop        = 0 if bid in seed_ids else 1,
                role       = role,
            ))

        result.depth   = max((b.hop for b in result.activated), default=0)
        result.breadth = len(result.activated)
        if result.activated:
            result.field_energy = round(
                sum(b.activation * b.confidence for b in result.activated)
                / len(result.activated), 4
            )
        result.tension_density = round(
            tension_traversed / max(total_edges, 1), 3
        )

        # Log co-activations for edge reweighting
        try:
            from nex_edge_reweight import wire_into_activation
            activated_ids = [b.id for b in result.activated]
            wire_into_activation(activated_ids)
        except Exception:
            pass

        return result


# Module-level singleton
_engine = ActivationEngine()


def activate(query: str) -> ActivationResult:
    """Public interface — activate belief graph for query."""
    return _engine.activate(query)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "what is consciousness"
    result = activate(q)
    print(f"Query: {q}")
    print(f"Activated: {result.breadth} beliefs, depth={result.depth}")
    print(f"Temperature: {result.epistemic_temperature()}")
    print(f"\n{result.to_prompt()}")
