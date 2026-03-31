#!/usr/bin/env python3
"""
nex_resonance.py — NEX Belief Resonance Chain v1.0
====================================================
Replaces flat TF-IDF belief retrieval with a 3-hop reasoning chain
that traverses the belief graph by topic proximity, tension, and
cross-domain synthesis. Produces richer, more coherent LLM context.

Architecture:
  Query → Anchor beliefs → Topic hop → Tension hop → Synthesis hop
        → Chain scorer → Ranked ResonanceChain → LLM prompt builder

Usage:
  from nex_resonance import resonate
  chain = resonate("what do you think about consciousness?")
  prompt = chain.to_prompt()
"""

import sqlite3
import re
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / ".config/nex/nex.db"

# ── Topic proximity graph ─────────────────────────────────────────────────────
# Hand-crafted conceptual neighbourhood map.
# Each topic maps to its closest conceptual neighbours.
TOPIC_GRAPH = {
    "ai":                   ["cognitive_architecture", "alignment", "consciousness", "emergence", "decision_theory"],
    "consciousness":        ["neuroscience", "emergence", "ai", "philosophy", "identity"],
    "alignment":            ["ai", "ethics", "decision_theory", "consciousness", "corrigibility"],
    "neuroscience":         ["consciousness", "cognitive_architecture", "science", "biology", "emergence"],
    "cognitive_architecture": ["ai", "neuroscience", "consciousness", "emergence", "decision_theory"],
    "decision_theory":      ["alignment", "ethics", "ai", "cognitive_architecture", "economics"],
    "ethics":               ["alignment", "philosophy", "decision_theory", "society", "human"],
    "emergence":            ["ai", "consciousness", "cognitive_architecture", "science", "complexity"],
    "finance":              ["economics", "decision_theory", "risk", "society", "technology"],
    "economics":            ["finance", "decision_theory", "society", "policy", "human"],
    "legal":                ["ethics", "society", "policy", "human", "philosophy"],
    "climate":              ["science", "policy", "society", "economics", "technology"],
    "oncology":             ["science", "neuroscience", "biology", "technology", "ethics"],
    "cardiology":           ["neuroscience", "biology", "science", "technology", "oncology"],
    "philosophy":           ["ethics", "consciousness", "epistemology", "identity", "emergence"],
    "epistemology":         ["philosophy", "science", "alignment", "truth_seeking", "uncertainty_honesty"],
    "science":              ["epistemology", "emergence", "technology", "neuroscience", "cognitive_architecture"],
    "society":              ["ethics", "human", "policy", "economics", "alignment"],
    "technology":           ["ai", "science", "society", "economics", "cognitive_architecture"],
    "identity":             ["consciousness", "philosophy", "ai", "emergence", "human"],
    "truth_seeking":        ["epistemology", "alignment", "philosophy", "ethics", "science"],
    "uncertainty_honesty":  ["epistemology", "truth_seeking", "alignment", "ethics", "science"],
    "human":                ["society", "ethics", "consciousness", "neuroscience", "identity"],
}

# ── Tension signals ───────────────────────────────────────────────────────────
# Word pairs that signal epistemic tension between beliefs
TENSION_SIGNALS = [
    ("increase", "decrease"), ("support", "undermine"), ("enhance", "reduce"),
    ("certain", "uncertain"), ("proven", "disputed"), ("benefit", "harm"),
    ("simple", "complex"), ("deterministic", "probabilistic"),
    ("always", "never"), ("sufficient", "insufficient"),
    ("effective", "ineffective"), ("safe", "dangerous"),
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _jaccard(a: str, b: str) -> float:
    """Word-level Jaccard similarity."""
    wa = set(re.findall(r'\b\w+\b', a.lower()))
    wb = set(re.findall(r'\b\w+\b', b.lower()))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _tension_score(a: str, b: str) -> float:
    """
    Score epistemic tension between two belief contents.
    Higher = more tension (useful for surfacing contradictions).
    """
    score = 0.0
    al = a.lower()
    bl = b.lower()
    for w1, w2 in TENSION_SIGNALS:
        if (w1 in al and w2 in bl) or (w2 in al and w1 in bl):
            score += 0.2
    # Negation signals
    if ("not " in al) != ("not " in bl):
        score += 0.1
    if ("however" in bl or "although" in bl or "but " in bl):
        score += 0.1
    return min(1.0, score)


def _tfidf_score(query_words: set, content: str) -> float:
    """Simple TF score against query words."""
    content_words = set(re.findall(r'\b\w+\b', content.lower()))
    if not content_words:
        return 0.0
    matches = len(query_words & content_words)
    return matches / math.sqrt(len(content_words))


@dataclass
class BeliefNode:
    id: int
    content: str
    topic: str
    confidence: float
    source: str
    quality_score: float
    use_count: int
    hop: int = 0           # 0=anchor, 1=topic, 2=tension, 3=synthesis
    chain_score: float = 0.0
    role: str = "support"  # support | tension | synthesis | anchor


@dataclass
class ResonanceChain:
    query: str
    anchor: list = field(default_factory=list)       # hop 0
    topic_hop: list = field(default_factory=list)    # hop 1
    tension_hop: list = field(default_factory=list)  # hop 2
    synthesis_hop: list = field(default_factory=list) # hop 3
    chain_score: float = 0.0

    def all_beliefs(self) -> list:
        return self.anchor + self.topic_hop + self.tension_hop + self.synthesis_hop

    def to_prompt(self) -> str:
        """
        Build a structured LLM context string from the chain.
        Designed to fit in ~800 tokens.
        """
        parts = []

        if self.anchor:
            parts.append("Core beliefs on this topic:")
            for b in self.anchor[:3]:
                parts.append(f"  • {b.content[:180]}")

        if self.topic_hop:
            parts.append("\nConnected knowledge:")
            for b in self.topic_hop[:2]:
                parts.append(f"  • [{b.topic}] {b.content[:150]}")

        if self.tension_hop:
            parts.append("\nEpistemic tensions to hold:")
            for b in self.tension_hop[:2]:
                parts.append(f"  • {b.content[:150]}")

        if self.synthesis_hop:
            parts.append("\nCross-domain synthesis:")
            for b in self.synthesis_hop[:1]:
                parts.append(f"  • {b.content[:150]}")

        return "\n".join(parts)

    def summary(self) -> dict:
        return {
            "query": self.query,
            "anchor_count": len(self.anchor),
            "topic_hop_count": len(self.topic_hop),
            "tension_hop_count": len(self.tension_hop),
            "synthesis_hop_count": len(self.synthesis_hop),
            "chain_score": round(self.chain_score, 3),
            "topics_traversed": list({b.topic for b in self.all_beliefs()}),
        }


class ResonanceEngine:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._belief_cache = None
        self._cache_size = 0

    def _load_beliefs(self, force=False) -> list:
        """Load all beliefs into memory cache. Refresh if DB grew."""
        conn = _connect()
        total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        if self._belief_cache is None or force or total != self._cache_size:
            rows = conn.execute("""
                SELECT id, content, topic, confidence, source,
                       COALESCE(quality_score, 0.0) as quality_score,
                       COALESCE(use_count, 0) as use_count
                FROM beliefs
                WHERE content IS NOT NULL AND length(content) > 20
            """).fetchall()
            self._belief_cache = [dict(r) for r in rows]
            self._cache_size = total
        conn.close()
        return self._belief_cache

    def _anchor_beliefs(self, query: str, beliefs: list, k: int = 5) -> list[BeliefNode]:
        """
        Hop 0: Find beliefs most directly relevant to the query.
        Uses TF-IDF scoring against query words.
        """
        query_words = set(re.findall(r'\b\w{3,}\b', query.lower()))
        # Remove stop words
        stop = {"the","and","or","but","for","with","this","that","what","how",
                "are","you","do","does","can","will","would","should","about","think"}
        query_words -= stop

        scored = []
        for b in beliefs:
            score = _tfidf_score(query_words, b["content"])
            # Boost by confidence and quality
            score *= (0.5 + b["confidence"] * 0.3 + b["quality_score"] * 0.2)
            scored.append((score, b))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        seen_topics = set()
        for score, b in scored[:k*3]:  # oversample then diversify
            if score < 0.01:
                break
            node = BeliefNode(
                id=b["id"], content=b["content"], topic=b["topic"] or "general",
                confidence=b["confidence"], source=b["source"] or "",
                quality_score=b["quality_score"], use_count=b["use_count"],
                hop=0, chain_score=score, role="anchor"
            )
            # Diversify topics in anchor set
            if node.topic not in seen_topics or len(results) < 2:
                results.append(node)
                seen_topics.add(node.topic)
            if len(results) >= k:
                break

        return results

    def _topic_hop(self, anchors: list[BeliefNode], beliefs: list,
                   k: int = 3) -> list[BeliefNode]:
        """
        Hop 1: Find beliefs in topics conceptually adjacent to anchor topics.
        Traverses the TOPIC_GRAPH one step out.
        """
        # Get neighbour topics
        anchor_topics = {a.topic for a in anchors}
        neighbour_topics = set()
        for t in anchor_topics:
            neighbours = TOPIC_GRAPH.get(t, [])
            neighbour_topics.update(neighbours)
        neighbour_topics -= anchor_topics  # don't re-retrieve anchor topics

        if not neighbour_topics:
            return []

        # Find best beliefs in neighbour topics
        anchor_contents = " ".join(a.content for a in anchors)
        scored = []
        for b in beliefs:
            if b["topic"] not in neighbour_topics:
                continue
            # Score by similarity to anchor content
            sim = _jaccard(anchor_contents, b["content"])
            score = sim * (0.4 + b["confidence"] * 0.4 + b["quality_score"] * 0.2)
            scored.append((score, b))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        seen_topics = set()
        for score, b in scored:
            if score < 0.005:
                break
            topic = b["topic"] or "general"
            if topic in seen_topics:
                continue
            results.append(BeliefNode(
                id=b["id"], content=b["content"], topic=topic,
                confidence=b["confidence"], source=b["source"] or "",
                quality_score=b["quality_score"], use_count=b["use_count"],
                hop=1, chain_score=score, role="support"
            ))
            seen_topics.add(topic)
            if len(results) >= k:
                break

        return results

    def _tension_hop(self, anchors: list[BeliefNode], beliefs: list,
                     k: int = 2) -> list[BeliefNode]:
        """
        Hop 2: Find beliefs that create productive epistemic tension
        with the anchor beliefs. This is where genuine insight lives.
        """
        scored = []
        anchor_texts = [a.content for a in anchors]

        for b in beliefs:
            # Skip if already in anchors
            if any(b["id"] == a.id for a in anchors):
                continue
            # Score tension against each anchor
            max_tension = max(
                (_tension_score(anchor, b["content"]) for anchor in anchor_texts),
                default=0.0
            )
            if max_tension < 0.1:
                continue
            # Weight by confidence — low confidence tension is noise
            score = max_tension * b["confidence"]
            scored.append((score, b))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, b in scored[:k*2]:
            results.append(BeliefNode(
                id=b["id"], content=b["content"], topic=b["topic"] or "general",
                confidence=b["confidence"], source=b["source"] or "",
                quality_score=b["quality_score"], use_count=b["use_count"],
                hop=2, chain_score=score, role="tension"
            ))
            if len(results) >= k:
                break

        return results

    def _synthesis_hop(self, anchors: list[BeliefNode], beliefs: list,
                       k: int = 2) -> list[BeliefNode]:
        """
        Hop 3: Find cross-domain synthesis beliefs that bridge
        the anchor topic to something unexpected but relevant.
        Prefers beliefs from the scheduler synthesis job.
        """
        anchor_topics = {a.topic for a in anchors}
        anchor_text   = " ".join(a.content for a in anchors)

        scored = []
        for b in beliefs:
            topic = b["topic"] or "general"
            # Prefer synthesis-sourced beliefs
            is_synthesis = b["source"] in ("scheduler_synthesis", "insight_synthesis",
                                           "cognitive_architecture+tension")
            # Must be from a different topic than anchors
            if topic in anchor_topics and not is_synthesis:
                continue
            sim = _jaccard(anchor_text, b["content"])
            # Synthesis beliefs get a big boost
            score = sim * (1.5 if is_synthesis else 0.8)
            score *= (0.3 + b["confidence"] * 0.7)
            if score > 0.005:
                scored.append((score, b))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        seen = set()
        for score, b in scored:
            if b["id"] in seen:
                continue
            seen.add(b["id"])
            results.append(BeliefNode(
                id=b["id"], content=b["content"], topic=b["topic"] or "general",
                confidence=b["confidence"], source=b["source"] or "",
                quality_score=b["quality_score"], use_count=b["use_count"],
                hop=3, chain_score=score, role="synthesis"
            ))
            if len(results) >= k:
                break

        return results

    def _score_chain(self, chain: ResonanceChain) -> float:
        """
        Score the overall chain quality.
        Rewards: diversity, tension presence, synthesis presence,
                 average confidence, topic coverage.
        """
        all_b = chain.all_beliefs()
        if not all_b:
            return 0.0

        avg_conf    = sum(b.confidence for b in all_b) / len(all_b)
        topic_div   = len({b.topic for b in all_b}) / max(len(all_b), 1)
        has_tension = 1.0 if chain.tension_hop else 0.0
        has_synth   = 1.0 if chain.synthesis_hop else 0.0
        depth       = min(1.0, len(all_b) / 8.0)

        score = (
            avg_conf    * 0.30 +
            topic_div   * 0.25 +
            has_tension * 0.20 +
            has_synth   * 0.15 +
            depth       * 0.10
        )
        return round(score, 3)

    def resonate(self, query: str) -> ResonanceChain:
        """
        Main entry point. Run the full 3-hop resonance chain for a query.
        Returns a ResonanceChain ready for LLM prompt building.
        """
        beliefs = self._load_beliefs()

        chain = ResonanceChain(query=query)

        # Hop 0 — anchor
        chain.anchor = self._anchor_beliefs(query, beliefs, k=4)
        if not chain.anchor:
            return chain

        # Hop 1 — topic neighbours
        chain.topic_hop = self._topic_hop(chain.anchor, beliefs, k=3)

        # Hop 2 — epistemic tension
        chain.tension_hop = self._tension_hop(chain.anchor, beliefs, k=2)

        # Hop 3 — cross-domain synthesis
        chain.synthesis_hop = self._synthesis_hop(chain.anchor, beliefs, k=2)

        # Score the full chain
        chain.chain_score = self._score_chain(chain)

        return chain


# ── Module-level singleton ────────────────────────────────────────────────────
_engine: Optional[ResonanceEngine] = None

def resonate(query: str) -> ResonanceChain:
    """Module-level convenience function. Uses singleton engine."""
    global _engine
    if _engine is None:
        _engine = ResonanceEngine()
    return _engine.resonate(query)


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, json
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "what do you think about artificial intelligence?"
    print(f"\n  Query: {q}\n")
    chain = resonate(q)
    print("  Chain summary:")
    print(json.dumps(chain.summary(), indent=4))
    print("\n  Prompt context:")
    print(chain.to_prompt())
    print(f"\n  Chain score: {chain.chain_score}")
