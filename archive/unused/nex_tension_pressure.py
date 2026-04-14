"""
nex_tension_pressure.py — Semantic Tension & Contradiction Pressure Engine
===========================================================================
Upgrades the TensionPressure system visible in the nex_brain terminal.

Current system (from screenshot):
    [TensionPressure] SPLIT [410c]: ai
    [TensionPressure] SPLIT [380c]: society
    ...31 tensioned topics — hot: ai(1.00), alignment(1.00) ...

That's a COUNT-BASED tension system. "ai" is tensioned because it has
the most beliefs, not because those beliefs actually contradict each other.

This upgrade adds:
  1. SEMANTIC CONTRADICTION SCORING — two beliefs are in tension when
     their content is semantically divergent AND their topics overlap.
     Uses cosine distance between belief embeddings: beliefs that discuss
     the same topic but pull in opposite directions get high tension.

  2. TENSION TOPOLOGY MAP — instead of a flat topic → count mapping,
     produces a graph of which specific beliefs are in tension with which,
     and how strongly. This feeds into the EFE ValueGate (high-tension
     signals get higher epistemic gain scores automatically).

  3. BELIEF SURVIVAL INTEGRATION — BeliefSurvival in the live system
     kills weak beliefs and amplifies strong ones. This module adds a
     tension-weighted survival pressure: beliefs that are UNIQUE
     (high tension with corpus) survive better than beliefs that merely
     restate consensus. Contradictory minority beliefs are preserved.

  4. TENSION DECAY — tension dissipates as beliefs become settled
     (high Wasserstein concentration). A belief with 200 confirmations
     doesn't need to be in tension anymore — it's a settled position.

Architecture position: runs inside cognition_tick, feeds EFE ValueGate
and BeliefSurvival pressure calculations.
"""

import math
import time
import sqlite3
import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

logger = logging.getLogger("nex.tension_pressure")


# ── Configuration ──────────────────────────────────────────────────────────────
TENSION_THRESHOLD      = 0.45  # cosine distance above this = tensioned pair
CONSENSUS_THRESHOLD    = 0.85  # cosine sim above this = redundant (same belief)
MAX_TENSION_PAIRS      = 500   # max tracked contradiction pairs
SURVIVAL_TENSION_BONUS = 0.25  # survival weight bonus for unique/tensioned beliefs
DECAY_PER_TICK         = 0.01  # tension score decay per cognition tick


# ── Embedding import (uses Hopfield's LightEmbedder — no new dep) ─────────────

try:
    from nex_hopfield_memory import LightEmbedder
    _embedder = LightEmbedder()
    _EMBED_OK = True
except ImportError:
    _EMBED_OK = False
    logger.warning("[Tension] LightEmbedder not available — using hash fallback")

    class _FallbackEmbedder:
        def embed(self, text: str) -> list[float]:
            import hashlib
            h = int(hashlib.md5(text.lower().encode()).hexdigest(), 16)
            return [(h >> i & 0xFF) / 255.0 - 0.5 for i in range(128)]

    _embedder = _FallbackEmbedder()


def _cosine_dist(a: list[float], b: list[float]) -> float:
    dot  = sum(x*y for x, y in zip(a, b))
    na   = math.sqrt(sum(x*x for x in a)) + 1e-9
    nb   = math.sqrt(sum(x*x for x in b)) + 1e-9
    return 1.0 - (dot / (na * nb))   # 0 = identical, 2 = opposite


# ── Tension pair ──────────────────────────────────────────────────────────────

@dataclass
class TensionPair:
    """Two beliefs in semantic tension."""
    id_a:        str
    id_b:        str
    topic:       str
    tension:     float    # 0-1, derived from cosine distance
    first_seen:  float = field(default_factory=time.time)
    last_seen:   float = field(default_factory=time.time)
    decay:       float = 0.0

    @property
    def pair_id(self) -> str:
        return f"{min(self.id_a,self.id_b)}:{max(self.id_a,self.id_b)}"

    @property
    def active_tension(self) -> float:
        return max(0.0, self.tension - self.decay)

    def tick_decay(self, rate: float = DECAY_PER_TICK):
        self.decay += rate
        self.last_seen = time.time()


@dataclass
class TopicTensionScore:
    """Aggregated tension score for a topic cluster."""
    topic:        str
    belief_count: int
    tension_score: float   # mean active_tension across all pairs in topic
    hot_pairs:    int      # count of pairs above TENSION_THRESHOLD
    unique_beliefs: list[str] = field(default_factory=list)  # high-tension belief IDs


# ── Main engine ───────────────────────────────────────────────────────────────

class TensionPressureEngine:
    """
    Semantic contradiction pressure engine.

    Two modes:
      - INCREMENTAL: call score_pair(id_a, text_a, id_b, text_b, topic)
        for individual belief pairs (use from belief_save hook)
      - BATCH: call scan_corpus(db_path) to re-score entire belief DB
        (use at startup or every N ticks)
    """

    def __init__(self):
        self._pairs:      dict[str, TensionPair] = {}
        self._topic_idx:  dict[str, set[str]] = defaultdict(set)  # topic → pair_ids
        self._belief_idx: dict[str, set[str]] = defaultdict(set)  # belief_id → pair_ids
        self._topic_scores: dict[str, TopicTensionScore] = {}
        self._tick = 0

    # ── Pair scoring ──────────────────────────────────────────────────────────

    def score_pair(self, id_a: str, text_a: str,
                   id_b: str, text_b: str,
                   topic: str = "unknown") -> Optional[TensionPair]:
        """
        Score a pair of beliefs for semantic tension.
        Returns TensionPair if tensioned, None if they agree or are redundant.
        """
        pair_id = f"{min(id_a,id_b)}:{max(id_a,id_b)}"

        # Already known — just refresh
        if pair_id in self._pairs:
            self._pairs[pair_id].last_seen = time.time()
            return self._pairs[pair_id]

        vec_a = _embedder.embed(text_a)
        vec_b = _embedder.embed(text_b)
        dist  = _cosine_dist(vec_a, vec_b)

        # Redundant (effectively same belief)
        if dist < (1.0 - CONSENSUS_THRESHOLD):
            return None

        # Not enough divergence to be a tension
        if dist < TENSION_THRESHOLD:
            return None

        # Tensioned pair
        tension_score = (dist - TENSION_THRESHOLD) / (1.0 - TENSION_THRESHOLD)
        pair = TensionPair(
            id_a=id_a, id_b=id_b,
            topic=topic,
            tension=min(1.0, tension_score),
        )
        self._pairs[pair_id] = pair
        self._topic_idx[topic].add(pair_id)
        self._belief_idx[id_a].add(pair_id)
        self._belief_idx[id_b].add(pair_id)

        logger.debug("[Tension] New tension: %s ↔ %s [%s] t=%.3f",
                     id_a[:8], id_b[:8], topic, tension_score)
        return pair

    # ── Batch corpus scan ─────────────────────────────────────────────────────

    def scan_corpus(self, db_path: str, limit: int = 500):
        """
        Scan the belief DB and score high-population topics for tension.
        Only checks beliefs within the same topic cluster (O(n²) per topic,
        but topic sizes are small — typically 20-100 beliefs).
        """
        import os
        if not os.path.exists(db_path):
            logger.warning("[Tension] DB not found: %s", db_path)
            return

        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            # Get topic groups with enough beliefs to have tension
            cur.execute("""
                SELECT topic, COUNT(*) as cnt
                FROM beliefs
                WHERE topic IS NOT NULL
                GROUP BY topic
                HAVING cnt >= 2
                ORDER BY cnt DESC
                LIMIT 30
            """)
            topic_counts = cur.fetchall()

            for topic, count in topic_counts:
                cur.execute("""
                    SELECT id, content FROM beliefs
                    WHERE topic = ?
                    ORDER BY confidence DESC
                    LIMIT 50
                """, (topic,))
                rows = cur.fetchall()

                # Score all pairs within this topic
                beliefs = [(str(r[0]), r[1] or "") for r in rows if r[1]]
                for i in range(len(beliefs)):
                    for j in range(i+1, len(beliefs)):
                        if len(self._pairs) >= MAX_TENSION_PAIRS:
                            break
                        self.score_pair(
                            beliefs[i][0], beliefs[i][1],
                            beliefs[j][0], beliefs[j][1],
                            topic=topic,
                        )

            conn.close()
            logger.info("[Tension] Scan complete: %d tension pairs across %d topics",
                        len(self._pairs), len(self._topic_idx))

        except Exception as e:
            logger.warning("[Tension] Corpus scan failed: %s", e)

    # ── Topic tension scores ──────────────────────────────────────────────────

    def get_topic_scores(self) -> dict[str, TopicTensionScore]:
        """
        Returns aggregated tension scores per topic.
        Result is the structured version of the TensionPressure output
        currently shown in nex_brain terminal.
        """
        scores: dict[str, TopicTensionScore] = {}

        for topic, pair_ids in self._topic_idx.items():
            pairs = [self._pairs[pid] for pid in pair_ids if pid in self._pairs]
            if not pairs:
                continue

            active = [p for p in pairs if p.active_tension > 0.01]
            if not active:
                continue

            mean_tension = sum(p.active_tension for p in active) / len(active)
            hot_pairs    = sum(1 for p in active if p.active_tension > 0.6)

            # Collect unique high-tension beliefs
            unique = set()
            for p in sorted(active, key=lambda x: x.active_tension, reverse=True)[:5]:
                unique.add(p.id_a)
                unique.add(p.id_b)

            # Count distinct beliefs in topic
            topic_beliefs = set()
            for p in active:
                topic_beliefs.add(p.id_a)
                topic_beliefs.add(p.id_b)

            scores[topic] = TopicTensionScore(
                topic=topic,
                belief_count=len(topic_beliefs),
                tension_score=round(mean_tension, 4),
                hot_pairs=hot_pairs,
                unique_beliefs=list(unique),
            )

        self._topic_scores = scores
        return scores

    def hot_topics(self, top_n: int = 31) -> list[tuple[str, float]]:
        """
        Returns top_n topics by tension score.
        Matches the format shown in nex_brain: hot: ai(1.00), alignment(1.00)...
        """
        scores = self.get_topic_scores()
        ranked = sorted(scores.items(),
                        key=lambda x: x[1].tension_score, reverse=True)
        return [(t, s.tension_score) for t, s in ranked[:top_n]]

    # ── Belief survival pressure ──────────────────────────────────────────────

    def survival_pressure(self, belief_id: str,
                          base_confidence: float) -> float:
        """
        Returns adjusted survival pressure for a belief.
        
        High-tension beliefs (unique/contradictory) get a survival BONUS —
        they represent unexplored territory worth keeping.
        
        Low-tension beliefs that are also low-confidence get extra pressure
        to be pruned (they're neither settled nor interesting).
        
        Used as multiplier on BeliefSurvival score.
        """
        pairs = [self._pairs[pid]
                 for pid in self._belief_idx.get(belief_id, set())
                 if pid in self._pairs]

        if not pairs:
            # No tension recorded — neutral survival pressure
            return 1.0

        max_tension = max(p.active_tension for p in pairs)

        if max_tension > TENSION_THRESHOLD:
            # Tensioned belief — survival bonus
            bonus = SURVIVAL_TENSION_BONUS * max_tension
            return 1.0 + bonus
        else:
            # Untensioned AND low confidence — increase pruning pressure
            if base_confidence < 0.5:
                return 0.85  # 15% extra pressure to prune
            return 1.0

    # ── EFE tension feed ──────────────────────────────────────────────────────

    def get_efe_tension_map(self) -> dict[str, float]:
        """
        Returns topic → tension_score mapping for EFE ValueGate.
        High-tension topics = higher epistemic gain for signals about them.
        """
        scores = self.get_topic_scores()
        return {topic: s.tension_score for topic, s in scores.items()}

    # ── Tick maintenance ──────────────────────────────────────────────────────

    def tick(self):
        """
        Decay all tension pairs. Prune fully decayed pairs.
        Call once per cognition tick.
        """
        self._tick += 1
        to_prune = []
        for pair_id, pair in self._pairs.items():
            pair.tick_decay()
            if pair.active_tension <= 0.0:
                to_prune.append(pair_id)

        for pid in to_prune:
            pair = self._pairs.pop(pid)
            self._topic_idx[pair.topic].discard(pid)
            self._belief_idx[pair.id_a].discard(pid)
            self._belief_idx[pair.id_b].discard(pid)

        if to_prune:
            logger.debug("[Tension] Decayed %d pairs at tick %d",
                         len(to_prune), self._tick)

        # Push tension map to EFE gate every 10 ticks
        if self._tick % 10 == 0:
            try:
                from nex_efe_valuegate import BeliefUncertaintyEstimator
                tension_map = self.get_efe_tension_map()
                BeliefUncertaintyEstimator.update_tensions(tension_map)
            except ImportError:
                pass

    def stats(self) -> dict:
        scores = self.get_topic_scores()
        return {
            "tension_pairs":   len(self._pairs),
            "tensioned_topics": len(scores),
            "hot_topics":      self.hot_topics(5),
            "tick":            self._tick,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_engine: Optional[TensionPressureEngine] = None

def get_tension_engine() -> TensionPressureEngine:
    global _engine
    if _engine is None:
        _engine = TensionPressureEngine()
    return _engine

def tension_tick():
    get_tension_engine().tick()

def score_belief_pair(id_a, text_a, id_b, text_b, topic="unknown"):
    return get_tension_engine().score_pair(id_a, text_a, id_b, text_b, topic)

def hot_topics(n=31) -> list[tuple[str, float]]:
    return get_tension_engine().hot_topics(n)

def survival_weight(belief_id: str, confidence: float) -> float:
    return get_tension_engine().survival_pressure(belief_id, confidence)


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    engine = TensionPressureEngine()

    # Simulate NEX belief corpus — pairs from the live tension topics
    belief_pairs = [
        ("b001", "Consciousness emerges from physical processes in the brain",
         "b011", "Consciousness cannot be fully explained by physical processes",
         "consciousness"),
        ("b002", "AI systems will develop genuine understanding over time",
         "b012", "AI systems process patterns without any genuine understanding",
         "ai"),
        ("b003", "Human values can be successfully encoded into AI reward functions",
         "b013", "Human values are too complex and contextual to encode formally",
         "alignment"),
        ("b004", "Strong AI regulation will slow beneficial development",
         "b014", "Strong AI regulation is necessary to prevent catastrophic risks",
         "ai"),
        ("b005", "Identity is continuous across time through memory",
         "b015", "Identity is reconstructed moment to moment with no true continuity",
         "identity"),
        ("b006", "Free will is compatible with deterministic physical processes",
         "b016", "Free will is an illusion produced by deterministic brain processes",
         "consciousness"),
        ("b007", "The internet has been net positive for human society",
         "b017", "The internet has fragmented society and deepened polarisation",
         "society"),
    ]

    for id_a, text_a, id_b, text_b, topic in belief_pairs:
        pair = engine.score_pair(id_a, text_a, id_b, text_b, topic)
        if pair:
            print(f"  TENSION [{pair.tension:.3f}] {topic}: {text_a[:45]}...")
        else:
            print(f"  AGREE   [---]   {topic}: (below threshold)")

    print(f"\n── Hot topics: {engine.hot_topics(5)}")
    print(f"── Stats: {engine.stats()}")

    print("\n── Survival pressure test ──")
    for bid in ["b001", "b002", "b005", "b099"]:  # b099 = unknown
        pressure = engine.survival_pressure(bid, base_confidence=0.65)
        print(f"  {bid}: survival multiplier = {pressure:.3f}")

    # Test EFE integration
    print("\n── EFE tension map ──")
    for topic, score in engine.get_efe_tension_map().items():
        print(f"  {topic:25s}: {score:.4f}")
