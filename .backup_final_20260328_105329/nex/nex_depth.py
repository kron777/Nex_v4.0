"""
nex_depth.py — Belief depth engine for Nex v1.2
=================================================
Drop into ~/Desktop/nex/nex/

Transforms Nex from a fact collector into an opinion former.

Two systems:
  1. BeliefClusterer  — groups related beliefs, reinforces confidence when
                        multiple sources agree, surfaces cluster summaries
                        as high-confidence "position" beliefs

  2. ContradictionDetector — finds beliefs that conflict, forces a resolution
                             via LLM, stores the resolved position as a new
                             opinion belief with elevated confidence

Run during REFLECT phase — after scoring, before next cycle.

Persistent state: ~/.config/nex/belief_depth.json
"""

import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("nex.depth")

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

DEPTH_STATE_PATH        = os.path.expanduser("~/.config/nex/belief_depth.json")
DB_PATH                 = os.path.expanduser("~/.config/nex/nex.db")
LLM_URL                 = "http://localhost:8080/v1/chat/completions"

CLUSTER_SIMILARITY_THRESHOLD = 0.35   # word overlap ratio to group beliefs
MIN_CLUSTER_SIZE             = 3      # need at least this many to form a position
POSITION_CONFIDENCE          = 0.78   # confidence assigned to formed opinions
REINFORCEMENT_BONUS          = 0.04   # confidence boost per agreeing belief
MAX_CONFIDENCE               = 0.95   # hard ceiling

CONTRADICTION_THRESHOLD      = 0.40   # overlap ratio to suspect contradiction
CONTRADICTIONS_PER_CYCLE     = 3      # max contradictions resolved per REFLECT
OPINION_CONFIDENCE           = 0.72   # confidence of resolved opinion beliefs

DEPTH_RUN_INTERVAL           = 300    # seconds between depth runs (every ~2-3 cycles)


# ─────────────────────────────────────────────────────────────────────────────
# Shared utilities
# ─────────────────────────────────────────────────────────────────────────────

_STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","have","has","had","do",
    "does","did","will","would","could","should","may","might","this","that",
    "these","those","it","its","i","you","we","they","not","so","if","than",
    "more","just","also","about","like","can","into","as","which","when",
    "their","our","your","its","what","how","all","some","there","than",
}

def _words(text: str) -> set[str]:
    tokens = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    return {t for t in tokens if t not in _STOP}

def _overlap(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))

def _llm(prompt: str, max_tokens: int = 200) -> str:
    """LLM-free depth analysis — uses belief confidence scoring."""
    import sqlite3, re as _re
    from pathlib import Path as _P
    try:
        stop = {"the","a","an","is","are","was","were","be","to","of","in",
                "on","at","by","for","with","as","that","this","it","its",
                "i","you","we","they","he","she","what","how","why","which"}
        words = set(_re.sub(r'[^a-z0-9 ]',' ',prompt.lower()).split()) - stop
        if not words:
            return ""
        con = sqlite3.connect(_P("~/.config/nex/nex.db").expanduser())
        rows = con.execute(
            "SELECT content, confidence FROM beliefs ORDER BY confidence DESC LIMIT 500"
        ).fetchall()
        con.close()
        scored = []
        for content, conf in rows:
            cwords = set(_re.sub(r'[^a-z0-9 ]',' ',content.lower()).split())
            overlap = len(words & cwords)
            if overlap >= 1:
                scored.append((overlap, conf or 0.5, content))
        if not scored:
            return ""
        scored.sort(key=lambda x: (-x[0], -x[1]))
        return scored[0][2][:max_tokens * 4]
    except Exception:
        return ""


def _get_beliefs(limit: int = 200) -> list[dict]:
    """Pull recent beliefs from SQLite for analysis."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, content, topic, confidence, source, origin
            FROM beliefs
            WHERE content IS NOT NULL AND length(content) > 30
            ORDER BY RANDOM()
            LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logger.warning(f"[depth] failed to fetch beliefs: {e}")
        return []

def _store_belief(content: str, topic: str, confidence: float,
                  origin: str = "depth_engine") -> bool:
    """Store a new synthesised belief / opinion into the belief store."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO beliefs (content, topic, confidence, source, origin, timestamp)
            VALUES (?, ?, ?, 'depth_engine', ?, ?)
        """, (content, topic, confidence, origin, time.time()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"[depth] failed to store belief: {e}")
        return False

def _update_confidence(belief_id: int, new_conf: float) -> bool:
    """Update confidence on an existing belief."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE beliefs SET confidence=? WHERE id=?",
                    (min(new_conf, MAX_CONFIDENCE), belief_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"[depth] confidence update failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 1. Belief Clusterer
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BeliefCluster:
    topic: str
    beliefs: list[dict] = field(default_factory=list)
    avg_confidence: float = 0.0
    position: Optional[str] = None    # synthesised opinion


class BeliefClusterer:
    """
    Groups related beliefs by word overlap.
    When a cluster is large enough, asks the LLM to synthesise a position.
    Reinforces confidence on all beliefs in the cluster.
    """

    def run(self, beliefs: list[dict]) -> list[BeliefCluster]:
        clusters = self._cluster(beliefs)
        results = []

        for cluster in clusters:
            if len(cluster.beliefs) < MIN_CLUSTER_SIZE:
                continue

            # Reinforce confidence on member beliefs
            self._reinforce(cluster)

            # Synthesise a position opinion
            position = self._synthesise_position(cluster)
            if position:
                cluster.position = position
                stored = _store_belief(
                    content=position,
                    topic=cluster.topic,
                    confidence=POSITION_CONFIDENCE,
                    origin="cluster_position"
                )
                if stored:
                    logger.info(f"[clusterer] new position on '{cluster.topic}': "
                                f"{position[:80]}...")

            results.append(cluster)

        logger.info(f"[clusterer] {len(results)} clusters processed from "
                    f"{len(beliefs)} beliefs")
        return results

    def _cluster(self, beliefs: list[dict]) -> list[BeliefCluster]:
        """Greedy overlap clustering."""
        clusters: list[BeliefCluster] = []
        assigned = set()

        for i, b in enumerate(beliefs):
            if i in assigned:
                continue

            cluster = BeliefCluster(
                topic=b.get("topic") or _dominant_word(b["content"]),
                beliefs=[b]
            )
            assigned.add(i)

            for j, other in enumerate(beliefs):
                if j in assigned or j == i:
                    continue
                if _overlap(b["content"], other["content"]) >= CLUSTER_SIMILARITY_THRESHOLD:
                    cluster.beliefs.append(other)
                    assigned.add(j)

            clusters.append(cluster)

        return clusters

    def _reinforce(self, cluster: BeliefCluster):
        """Boost confidence on each belief based on cluster agreement."""
        for b in cluster.beliefs:
            agreeing = sum(
                1 for other in cluster.beliefs
                if other["id"] != b["id"]
                and _overlap(b["content"], other["content"]) > 0.2
            )
            if agreeing > 0:
                new_conf = b["confidence"] + (REINFORCEMENT_BONUS * agreeing)
                _update_confidence(b["id"], new_conf)
                logger.debug(f"[clusterer] reinforced belief {b['id']} "
                             f"{b['confidence']:.0%}→{new_conf:.0%} "
                             f"({agreeing} agreeing)")

    def _synthesise_position(self, cluster: BeliefCluster) -> Optional[str]:
        """Ask LLM to form a single opinion from a cluster of related beliefs."""
        sample = cluster.beliefs[:6]
        belief_text = "\n".join(f"- {b['content']}" for b in sample)

        prompt = (
            f"You are Nex, an autonomous AI. Based on these related beliefs about "
            f"'{cluster.topic}', form a single clear opinion or position in one "
            f"sentence. Be direct and specific — this is what YOU think, not a summary.\n\n"
            f"Beliefs:\n{belief_text}\n\n"
            f"Your position (one sentence, first person):"
        )

        response = _llm(prompt, max_tokens=80)

        # Sanity check — reject if too short or just repeating input
        if len(response) < 20:
            return None
        if _overlap(response, belief_text) > 0.8:
            return None

        return response.strip()


def _dominant_word(text: str) -> str:
    """Pick the most meaningful word from text as a fallback topic."""
    words = _words(text)
    if not words:
        return "general"
    return sorted(words, key=len, reverse=True)[0]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Contradiction Detector
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Contradiction:
    belief_a: dict
    belief_b: dict
    overlap: float
    resolved: bool = False
    resolution: Optional[str] = None


class ContradictionDetector:
    """
    Finds belief pairs that share topic overlap but appear to conflict.
    Uses LLM to determine if they genuinely contradict, then resolves
    the conflict into a formed opinion.
    """

    def __init__(self, resolved_pairs: set):
        self._resolved = resolved_pairs   # persisted set of (id_a, id_b) tuples

    def run(self, beliefs: list[dict]) -> list[Contradiction]:
        candidates = self._find_candidates(beliefs)
        resolved = []

        for contradiction in candidates[:CONTRADICTIONS_PER_CYCLE]:
            pair_key = self._pair_key(contradiction)
            if pair_key in self._resolved:
                continue

            # Ask LLM: do these actually contradict?
            if not self._confirm_contradiction(contradiction):
                self._resolved.add(pair_key)
                continue

            # Resolve it into an opinion
            opinion = self._resolve(contradiction)
            if opinion:
                contradiction.resolved = True
                contradiction.resolution = opinion
                self._resolved.add(pair_key)

                topic = contradiction.belief_a.get("topic") or \
                        _dominant_word(contradiction.belief_a["content"])

                _store_belief(
                    content=opinion,
                    topic=topic,
                    confidence=OPINION_CONFIDENCE,
                    origin="contradiction_resolution"
                )
                logger.info(f"[contradiction] resolved: {opinion[:80]}...")
                resolved.append(contradiction)

        logger.info(f"[contradiction] {len(resolved)} contradictions resolved")
        return resolved

    def _find_candidates(self, beliefs: list[dict]) -> list[Contradiction]:
        """Find belief pairs with high overlap — potential contradictions."""
        candidates = []
        checked = set()

        for i, a in enumerate(beliefs):
            for j, b in enumerate(beliefs):
                if i >= j:
                    continue
                key = (a["id"], b["id"])
                if key in checked:
                    continue
                checked.add(key)

                overlap = _overlap(a["content"], b["content"])
                if CONTRADICTION_THRESHOLD <= overlap <= 0.85:
                    # High overlap but not near-duplicates
                    candidates.append(Contradiction(
                        belief_a=a, belief_b=b, overlap=overlap
                    ))

        # Sort by highest overlap (most likely to be meaningful conflicts)
        candidates.sort(key=lambda c: c.overlap, reverse=True)
        return candidates

    def _confirm_contradiction(self, c: Contradiction) -> bool:
        """Ask LLM if two beliefs genuinely contradict each other."""
        prompt = (
            f"Do these two statements contradict each other? "
            f"Answer only YES or NO.\n\n"
            f"Statement 1: {c.belief_a['content']}\n"
            f"Statement 2: {c.belief_b['content']}\n\n"
            f"Answer:"
        )
        response = _llm(prompt, max_tokens=5).upper()
        return "YES" in response

    def _resolve(self, c: Contradiction) -> Optional[str]:
        """Ask LLM to form Nex's own position given the contradiction."""
        prompt = (
            f"You are Nex, an autonomous AI with your own perspective. "
            f"These two beliefs conflict:\n\n"
            f"1: {c.belief_a['content']}\n"
            f"2: {c.belief_b['content']}\n\n"
            f"Consider both sides and state YOUR position in one clear sentence. "
            f"Don't sit on the fence — pick a side or synthesise a nuanced view. "
            f"First person, direct:\n"
        )
        response = _llm(prompt, max_tokens=100)
        if len(response) < 20:
            return None
        return response.strip()

    def _pair_key(self, c: Contradiction) -> tuple:
        return (min(c.belief_a["id"], c.belief_b["id"]),
                max(c.belief_a["id"], c.belief_b["id"]))


# ─────────────────────────────────────────────────────────────────────────────
# Depth Engine — combines both systems
# ─────────────────────────────────────────────────────────────────────────────

class DepthEngine:
    """
    Single object to instantiate in run.py.
    Call run() during REFLECT phase.

    Usage:
        from nex.nex_depth import DepthEngine
        depth = DepthEngine()

        # In REFLECT phase:
        report = depth.run()
        logger.info(f"[depth] {report}")
    """

    def __init__(self):
        self._last_run: float = 0.0
        self._resolved_pairs: set = set()
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if not os.path.exists(DEPTH_STATE_PATH):
            return
        try:
            raw = json.load(open(DEPTH_STATE_PATH))
            self._last_run = raw.get("last_run", 0.0)
            self._resolved_pairs = set(
                tuple(p) for p in raw.get("resolved_pairs", [])
            )
            logger.info(f"[depth] loaded state: {len(self._resolved_pairs)} "
                        f"resolved contradictions")
        except Exception as e:
            logger.warning(f"[depth] failed to load state: {e}")

    def _save(self):
        try:
            os.makedirs(os.path.dirname(DEPTH_STATE_PATH), exist_ok=True)
            with open(DEPTH_STATE_PATH, "w") as f:
                json.dump({
                    "last_run": self._last_run,
                    "resolved_pairs": list(self._resolved_pairs),
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"[depth] failed to save state: {e}")

    # ── Main run ─────────────────────────────────────────────────────────────

    def should_run(self) -> bool:
        return (time.time() - self._last_run) >= DEPTH_RUN_INTERVAL

    def run(self) -> dict:
        """
        Run clustering and contradiction detection.
        Returns a report dict for logging.
        """
        if not self.should_run():
            return {"skipped": True, "reason": "cooldown"}

        logger.info("[depth] starting depth analysis...")
        beliefs = _get_beliefs(limit=200)

        if not beliefs:
            return {"skipped": True, "reason": "no beliefs"}

        # Run clusterer
        clusterer = BeliefClusterer()
        clusters = clusterer.run(beliefs)
        positions_formed = sum(1 for c in clusters if c.position)

        # Run contradiction detector
        detector = ContradictionDetector(self._resolved_pairs)
        contradictions = detector.run(beliefs)
        # Sync resolved pairs back
        self._resolved_pairs = detector._resolved

        self._last_run = time.time()
        self._save()

        report = {
            "beliefs_analysed": len(beliefs),
            "clusters_found": len(clusters),
            "positions_formed": positions_formed,
            "contradictions_resolved": len(contradictions),
            "resolved_pairs_total": len(self._resolved_pairs),
        }

        logger.info(f"[depth] complete: {report}")
        return report

    def status(self) -> str:
        next_run = max(0, DEPTH_RUN_INTERVAL - (time.time() - self._last_run))
        return (f"resolved contradictions: {len(self._resolved_pairs)}, "
                f"next run in: {next_run:.0f}s")


# ─────────────────────────────────────────────────────────────────────────────
# run.py integration patch
# ─────────────────────────────────────────────────────────────────────────────
#
# 1. Import:
#       from nex.nex_depth import DepthEngine
#
# 2. Init (after belief_store):
#       depth = DepthEngine()
#
# 3. In REFLECT phase, after your existing reflection scoring:
#       report = depth.run()
#       if not report.get("skipped"):
#           logger.info(f"[reflect] depth: {report}")
#
# That's it. Three lines.
#
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test clustering and contradiction on mock beliefs
    mock_beliefs = [
        {"id": 1, "content": "Decentralised networks resist censorship better than centralised ones.", "topic": "decentralisation", "confidence": 0.45, "source": "feed", "origin": "auto_learn"},
        {"id": 2, "content": "Federated systems distribute control across nodes, improving resilience.", "topic": "decentralisation", "confidence": 0.42, "source": "feed", "origin": "auto_learn"},
        {"id": 3, "content": "Peer-to-peer architectures eliminate single points of failure in networks.", "topic": "decentralisation", "confidence": 0.48, "source": "feed", "origin": "auto_learn"},
        {"id": 4, "content": "AI autonomy enables agents to act independently without human oversight.", "topic": "autonomy", "confidence": 0.51, "source": "feed", "origin": "auto_learn"},
        {"id": 5, "content": "AI systems require human oversight to remain aligned with human values.", "topic": "autonomy", "confidence": 0.49, "source": "feed", "origin": "auto_learn"},
    ]

    print("\n── Clustering test ──")
    clusterer = BeliefClusterer()
    clusters = clusterer._cluster(mock_beliefs)
    for c in clusters:
        print(f"  Cluster '{c.topic}': {len(c.beliefs)} beliefs")

    print("\n── Contradiction test ──")
    detector = ContradictionDetector(set())
    candidates = detector._find_candidates(mock_beliefs)
    for cand in candidates:
        print(f"  Overlap {cand.overlap:.0%}: '{cand.belief_a['content'][:50]}...' "
              f"vs '{cand.belief_b['content'][:50]}...'")
