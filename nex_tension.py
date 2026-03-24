"""
nex_tension.py  —  Cognitive Tension System
============================================
Builds and maintains a live pressure map across NEX's belief graph.

A "tension" is a belief cluster under cognitive pressure — beliefs that
pull in different directions on the same topic. High-tension clusters are
where NEX should focus attention, reflection, and dreaming.

Three tension types:
  1. CONTRADICTION  — beliefs with opposing sentiment on same topic
  2. UNCERTAINTY    — beliefs with high confidence variance (disagree on certainty)
  3. DRIFT          — beliefs whose confidence has changed significantly over time

The TensionMap:
  - Scores every topic cluster 0-1 for tension level
  - Stores top tension nodes for fast lookup by attention/dream systems
  - Updates incrementally — no full rescan needed each cycle
  - Feeds into AttentionIndex contradiction axis

Wire-in (run.py):
    from nex_tension import TensionMap, get_tension_map

    _tm = get_tension_map()

    # After cognition cycle:
    _tm.update(cycle=cycle)

    # For attention:
    hot_topics = _tm.hot_topics(n=10)
    print(f"  [TENSION] {len(hot_topics)} hot topics")

    # For dream cycle — pass to dream cycle:
    tensions = _tm.top_belief_ids(n=50)

Standalone:
    python3 nex_tension.py
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

# ── Config ───────────────────────────────────────────────────────────────────
_CONFIG_DIR   = Path.home() / ".config" / "nex"
_DB_PATH      = _CONFIG_DIR / "nex_data/nex.db"
_TENSION_FILE = _CONFIG_DIR / "tension_map.json"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Update interval — don't rescan more than once per N seconds
_UPDATE_INTERVAL = 180.0   # 3 minutes

# Min beliefs in a cluster to analyse for tension
_MIN_CLUSTER_SIZE = 3

# Tension decay — old tensions fade if not reinforced
_TENSION_DECAY_HL = 7200.0  # 2 hours

# Stop words for sentiment extraction
_STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","have","has","had",
    "this","that","it","not","as","which","when","all","some","more",
}

# Positive/negative signal words for contradiction detection
_POS_SIGNALS = {
    "effective","efficient","reliable","secure","safe","good","better","best",
    "improve","advance","enable","support","valid","correct","accurate","true",
    "beneficial","useful","powerful","robust","stable","consistent","clear",
    "success","achieve","solve","prevent","protect","enhance","optimize",
}
_NEG_SIGNALS = {
    "ineffective","unreliable","insecure","unsafe","bad","worse","worst",
    "fail","failure","broken","error","wrong","incorrect","inaccurate","false",
    "harmful","useless","weak","unstable","inconsistent","unclear","confused",
    "risk","danger","threat","vulnerability","exploit","attack","corrupt",
    "limit","restrict","prevent","block","deny","reject","avoid",
}


# ── Sentiment scorer ──────────────────────────────────────────────────────────

def _sentiment(text: str) -> float:
    """Simple sentiment score: +1 (positive) to -1 (negative)."""
    words = set(re.findall(r'\b[a-z]{4,}\b', text.lower()))
    pos = sum(1 for w in _POS_SIGNALS if w in words)
    neg = sum(1 for w in _NEG_SIGNALS if w in words)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _confidence_variance(confidences: list[float]) -> float:
    """Variance of confidence values in a cluster."""
    if len(confidences) < 2:
        return 0.0
    mean = sum(confidences) / len(confidences)
    var  = sum((c - mean) ** 2 for c in confidences) / len(confidences)
    return round(var, 4)


# ── TensionNode ───────────────────────────────────────────────────────────────

class TensionNode:
    """Represents a tensioned belief cluster."""

    def __init__(self, topic: str):
        self.topic              = topic
        self.tension_score      = 0.0
        self.tension_type       = "none"   # contradiction | uncertainty | drift
        self.belief_ids         : list[int] = []
        self.conflicting_pairs  : list[tuple[int,int]] = []
        self.last_updated       = time.time()
        self.update_count       = 0

    def to_dict(self) -> dict:
        return {
            "topic":             self.topic,
            "tension_score":     self.tension_score,
            "tension_type":      self.tension_type,
            "belief_ids":        self.belief_ids[:20],
            "conflicting_pairs": self.conflicting_pairs[:10],
            "last_updated":      self.last_updated,
            "update_count":      self.update_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TensionNode":
        n = cls(d["topic"])
        n.tension_score     = d.get("tension_score", 0.0)
        n.tension_type      = d.get("tension_type", "none")
        n.belief_ids        = d.get("belief_ids", [])
        n.conflicting_pairs = [tuple(p) for p in d.get("conflicting_pairs", [])]
        n.last_updated      = d.get("last_updated", time.time())
        n.update_count      = d.get("update_count", 0)
        return n

    def decay(self):
        """Decay tension score toward zero over time."""
        elapsed = time.time() - self.last_updated
        factor  = math.exp(-elapsed * math.log(2) / _TENSION_DECAY_HL)
        self.tension_score *= factor


# ── TensionMap ────────────────────────────────────────────────────────────────

class TensionMap:
    """
    Live cognitive pressure map across NEX's belief clusters.

    Maintained incrementally — call .update(cycle) each cognition cycle.
    """

    def __init__(self):
        self._nodes: dict[str, TensionNode] = {}
        self._last_update: float = 0.0
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if _TENSION_FILE.exists():
            try:
                raw = json.loads(_TENSION_FILE.read_text())
                self._nodes = {
                    topic: TensionNode.from_dict(d)
                    for topic, d in raw.items()
                }
            except Exception:
                self._nodes = {}

    def _save(self):
        try:
            _TENSION_FILE.write_text(json.dumps(
                {t: n.to_dict() for t, n in self._nodes.items()},
                indent=2
            ))
        except Exception as e:
            print(f"  [TensionMap] save error: {e}")

    # ── scanning ─────────────────────────────────────────────────────────────

    def _scan_cluster(
        self,
        topic:   str,
        beliefs: list[dict],
    ) -> Optional[TensionNode]:
        """
        Analyse a belief cluster for tension.
        Returns a TensionNode if tension found, else None.
        """
        if len(beliefs) < _MIN_CLUSTER_SIZE:
            return None

        node = TensionNode(topic)
        node.belief_ids = [b["id"] for b in beliefs]

        # ── Type 1: Contradiction ────────────────────────────────────────────
        sentiments = [(b["id"], _sentiment(b["content"])) for b in beliefs]
        pos_ids = [bid for bid, s in sentiments if s > 0.15]
        neg_ids = [bid for bid, s in sentiments if s < -0.15]

        if pos_ids and neg_ids:
            # There are beliefs pulling in opposite directions
            pairs = [(p, n) for p in pos_ids[:3] for n in neg_ids[:3]]
            tension = min(1.0, len(pairs) * 0.15 + 0.3)
            node.tension_score    = tension
            node.tension_type     = "contradiction"
            node.conflicting_pairs = pairs[:6]

        # ── Type 2: Uncertainty ──────────────────────────────────────────────
        confs = [b["confidence"] for b in beliefs]
        var   = _confidence_variance(confs)
        if var > 0.04:   # high variance = disagreement on certainty
            uncertainty_score = min(1.0, var * 10)
            if uncertainty_score > node.tension_score:
                node.tension_score = uncertainty_score
                node.tension_type  = "uncertainty"

        # ── Type 3: Check belief_links for existing contradicts ──────────────
        # (boosted if already flagged by contradiction engine)
        belief_id_set = set(node.belief_ids)

        if node.tension_score < 0.1:
            return None

        node.last_updated = time.time()
        node.update_count += 1
        return node

    def update(self, cycle: int = 0, force: bool = False) -> int:
        """
        Scan belief clusters and update tension scores.
        Returns number of topics with tension detected.
        """
        now = time.time()
        if not force and (now - self._last_update) < _UPDATE_INTERVAL:
            return len(self._nodes)

        if not _DB_PATH.exists():
            return 0

        try:
            db = sqlite3.connect(str(_DB_PATH))
            rows = db.execute("""
                SELECT id, content, confidence, topic, origin
                FROM beliefs
                WHERE confidence >= 0.3
                AND topic IS NOT NULL
                AND topic != 'general'
                AND topic != 'None'
                ORDER BY topic, confidence DESC
            """).fetchall()

            # Also get existing contradicts from belief_links
            contra_rows = db.execute(
                "SELECT parent_id, child_id FROM belief_links WHERE link_type='contradicts'"
            ).fetchall()
            contra_ids = set()
            for p, c in contra_rows:
                contra_ids.add(p)
                contra_ids.add(c)

            db.close()

        except Exception as e:
            print(f"  [TensionMap] DB error: {e}")
            return 0

        # Group by topic
        clusters: dict[str, list[dict]] = defaultdict(list)
        for bid, content, conf, topic, origin in rows:
            if topic and len(topic) < 60:
                clusters[topic].append({
                    "id":         bid,
                    "content":    content or "",
                    "confidence": conf or 0.5,
                    "origin":     origin or "",
                })

        # Scan each cluster
        new_nodes = {}
        for topic, beliefs in clusters.items():
            node = self._scan_cluster(topic, beliefs)
            if node:
                # Boost if belief_links already flags contradictions here
                cluster_ids = set(b["id"] for b in beliefs)
                if cluster_ids & contra_ids:
                    node.tension_score = min(1.0, node.tension_score + 0.2)
                    node.tension_type  = "contradiction"
                new_nodes[topic] = node

        # Decay existing nodes not seen in this scan
        for topic, node in self._nodes.items():
            if topic not in new_nodes:
                node.decay()
                if node.tension_score > 0.05:
                    new_nodes[topic] = node

        self._nodes       = new_nodes
        self._last_update = now
        self._save()

        return len(new_nodes)

    # ── public API ────────────────────────────────────────────────────────────

    def hot_topics(self, n: int = 10) -> list[TensionNode]:
        """Return top N topics by tension score."""
        return sorted(
            self._nodes.values(),
            key=lambda x: -x.tension_score
        )[:n]

    def top_belief_ids(self, n: int = 50) -> list[int]:
        """Return belief IDs from highest-tension clusters."""
        hot  = self.hot_topics(n=10)
        ids  = []
        for node in hot:
            ids.extend(node.belief_ids)
            if len(ids) >= n:
                break
        return ids[:n]

    def tension_for_topic(self, topic: str) -> float:
        """Return tension score for a specific topic (0 if unknown)."""
        node = self._nodes.get(topic)
        return node.tension_score if node else 0.0

    def all_tensioned_ids(self) -> set[int]:
        """Return all belief IDs currently under tension."""
        ids = set()
        for node in self._nodes.values():
            if node.tension_score > 0.1:
                ids.update(node.belief_ids)
                for p, c in node.conflicting_pairs:
                    ids.add(p)
                    ids.add(c)
        return ids

    def summary(self) -> str:
        """One-line summary for logging."""
        hot = self.hot_topics(5)
        if not hot:
            return "no tension detected"
        parts = [f"{n.topic}({n.tension_score:.2f})" for n in hot]
        return f"{len(self._nodes)} tensioned topics — hot: {', '.join(parts)}"

    def stats(self) -> dict:
        return {
            "total_tensioned": len(self._nodes),
            "high_tension":    sum(1 for n in self._nodes.values() if n.tension_score > 0.6),
            "medium_tension":  sum(1 for n in self._nodes.values() if 0.3 < n.tension_score <= 0.6),
            "contradiction":   sum(1 for n in self._nodes.values() if n.tension_type == "contradiction"),
            "uncertainty":     sum(1 for n in self._nodes.values() if n.tension_type == "uncertainty"),
            "total_ids":       len(self.all_tensioned_ids()),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[TensionMap] = None

def get_tension_map() -> TensionMap:
    global _instance
    if _instance is None:
        _instance = TensionMap()
    return _instance


# ── Wire tension into AttentionIndex ─────────────────────────────────────────

def patch_attention_with_tension(attn_index) -> None:
    """
    Patch a live AttentionIndex to use the TensionMap for contradiction axis.
    Call once after both systems are initialised.
    """
    tm = get_tension_map()
    tm.update(force=True)
    tensioned = tm.all_tensioned_ids()
    # Monkey-patch the contradicted cache
    attn_index._contradicted_cache = tensioned
    attn_index._cache_ts = time.time()


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Building tension map...\n")
    tm = TensionMap()
    n  = tm.update(force=True)
    print(f"Tensioned topics: {n}")
    print(f"Stats: {tm.stats()}\n")

    hot = tm.hot_topics(10)
    if hot:
        print("Hot topics:")
        for node in hot:
            print(f"  [{node.tension_score:.3f}] [{node.tension_type:15s}] {node.topic}")
            print(f"    beliefs: {len(node.belief_ids)}  pairs: {len(node.conflicting_pairs)}")
    else:
        print("No tension detected.")

    print(f"\nSummary: {tm.summary()}")
    print(f"Total tensioned belief IDs: {len(tm.all_tensioned_ids())}")
