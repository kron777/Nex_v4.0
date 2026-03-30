"""
nex_episode_feedback.py — Episode Feedback → Hebbian Hyperedge Boost
====================================================================
The bottom layer of the NEX architecture map.
Closes the full loop: reply outcome → belief graph strengthening.

Architecture position: fires AFTER every completed reply cycle.
Input:  reply text, belief IDs used, engagement/quality signal
Output: Hebbian edge boosts + hyperedge cluster weight updates +
        BeliefDistribution updates across all activated beliefs

Three feedback signal sources:
  1. EXPLICIT: reply was upvoted/engaged with on platform (0.9-1.0)
  2. IMPLICIT: reply was read/no negative signal (0.5-0.7)
  3. NEGATIVE:  reply triggered contradiction or correction (0.1-0.3)
  4. INTERNAL: self-reflection quality assessment (from nex_reflect)

Integration:
    from nex_episode_feedback import EpisodeFeedbackLoop
    fb = EpisodeFeedbackLoop()
    # After each reply:
    fb.record_episode(
        reply_text=composed_reply,
        belief_ids_used=["b001", "b003", "b005"],
        topic_tags={"consciousness", "identity"},
        outcome="implicit",   # or "explicit", "negative", "internal"
        quality_score=0.72,   # from nex_reflect or platform signal
    )
"""

import time
import json
import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import deque

logger = logging.getLogger("nex.episode_feedback")

# Import sibling modules (graceful fallback if not deployed yet)
try:
    from nex_hebbian_plasticity import get_engine as get_hebbian, episode_boost
    _HEBBIAN_AVAILABLE = True
except ImportError:
    _HEBBIAN_AVAILABLE = False
    logger.warning("[EpisodeFB] nex_hebbian_plasticity not found — Hebbian boost disabled")

try:
    from nex_hyperedge_fabric import get_fabric
    _FABRIC_AVAILABLE = True
except ImportError:
    _FABRIC_AVAILABLE = False
    logger.warning("[EpisodeFB] nex_hyperedge_fabric not found — cluster boost disabled")

try:
    from nex_efe_valuegate import get_gate as get_efe_gate
    _EFE_AVAILABLE = True
except ImportError:
    _EFE_AVAILABLE = False


# ── Outcome → score mapping ───────────────────────────────────────────────────

OUTCOME_SCORES = {
    "explicit_positive": 0.95,   # upvote, reply engagement, positive reaction
    "explicit":          0.90,
    "implicit":          0.65,   # no signal = mild positive (NEX replied, system running)
    "self_positive":     0.80,   # reflection assessed reply as good
    "internal":          0.72,
    "neutral":           0.50,
    "self_negative":     0.30,
    "negative":          0.20,   # contradiction from interlocutor
    "explicit_negative": 0.10,
}


@dataclass
class EpisodeRecord:
    """Immutable record of one reply episode."""
    episode_id:     str
    timestamp:      float
    reply_text:     str
    belief_ids:     list[str]
    topic_tags:     set[str]
    outcome:        str
    quality_score:  float
    hebbian_boost:  float
    cluster_ids:    list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "episode_id":    self.episode_id,
            "timestamp":     self.timestamp,
            "outcome":       self.outcome,
            "quality_score": round(self.quality_score, 4),
            "hebbian_boost": round(self.hebbian_boost, 4),
            "belief_count":  len(self.belief_ids),
            "cluster_count": len(self.cluster_ids),
            "topics":        list(self.topic_tags),
        }


class EpisodeFeedbackLoop:
    """
    Closes the architecture feedback loop.
    
    On each episode:
    1. Convert outcome signal → quality score
    2. Fire Hebbian co-activation boost across used beliefs
    3. Boost hyperedge clusters that were active in this episode
    4. Update BeliefDistributions for all activated beliefs
    5. Feed quality signal back to EFE gate (improves future routing)
    6. Log episode for introspection
    """

    def __init__(self, history_size: int = 200):
        self._history: deque[EpisodeRecord] = deque(maxlen=history_size)
        self._episode_count = 0
        self._quality_ema   = 0.65   # exponential moving average of quality
        self._ema_alpha     = 0.1

    def record_episode(self,
                       reply_text:    str,
                       belief_ids:    list[str],
                       topic_tags:    set[str] | None = None,
                       outcome:       str = "implicit",
                       quality_score: float | None = None) -> EpisodeRecord:
        """
        Record a completed reply episode and fire all feedback signals.
        
        reply_text:    the composed reply
        belief_ids:    IDs of beliefs that contributed to the reply
        topic_tags:    topic set for cluster identification
        outcome:       one of OUTCOME_SCORES keys
        quality_score: override (0-1); if None, derived from outcome
        """
        # Resolve quality score
        base_score = OUTCOME_SCORES.get(outcome, 0.5)
        if quality_score is not None:
            # Blend outcome prior with explicit quality score
            q = 0.4 * base_score + 0.6 * max(0.0, min(1.0, quality_score))
        else:
            q = base_score

        # Update quality EMA
        self._quality_ema = (self._ema_alpha * q +
                             (1 - self._ema_alpha) * self._quality_ema)

        cluster_ids = []

        # ── 1. Hebbian boost ────────────────────────────────────────────────
        if _HEBBIAN_AVAILABLE and belief_ids:
            try:
                episode_boost(belief_ids, q)
                logger.debug("[EpisodeFB] Hebbian boost %.2f → %d beliefs",
                             q, len(belief_ids))
            except Exception as e:
                logger.warning("[EpisodeFB] Hebbian boost failed: %s", e)

        # ── 2. Hyperedge cluster boost ──────────────────────────────────────
        if _FABRIC_AVAILABLE and belief_ids:
            try:
                fabric = get_fabric()
                # Form/update cluster from this episode's co-activated beliefs
                if len(belief_ids) >= 2:
                    cluster = fabric.form_cluster(
                        belief_ids,
                        topic_tags=topic_tags or set(),
                        weight=q,
                    )
                    cluster_ids.append(cluster.cluster_id)
                    # Boost cluster weight by episode quality
                    fabric.activate_cluster(cluster.cluster_id, boost=q * 0.1)

                logger.debug("[EpisodeFB] Cluster boost → %d clusters", len(cluster_ids))
            except Exception as e:
                logger.warning("[EpisodeFB] Cluster boost failed: %s", e)

        # ── 3. EFE feedback (improves future routing accuracy) ──────────────
        if _EFE_AVAILABLE and belief_ids:
            try:
                gate = get_efe_gate()
                # Inject quality signal into tension topic estimator
                if topic_tags and q > 0.7:
                    # Good reply on a topic → slightly reduce its tension
                    # (the uncertainty is being resolved)
                    from nex_efe_valuegate import BeliefUncertaintyEstimator
                    for tag in topic_tags:
                        current = BeliefUncertaintyEstimator._tension_topics.get(tag, 0.5)
                        updated = current * (1 - 0.02 * (q - 0.5))
                        BeliefUncertaintyEstimator._tension_topics[tag] = max(0.1, updated)
            except Exception:
                pass

        # ── 4. Build episode record ─────────────────────────────────────────
        import hashlib
        ep_id = f"ep_{self._episode_count:05d}_{hashlib.md5(reply_text[:30].encode()).hexdigest()[:6]}"
        self._episode_count += 1

        record = EpisodeRecord(
            episode_id=ep_id,
            timestamp=time.time(),
            reply_text=reply_text[:200],  # truncate for storage
            belief_ids=list(belief_ids),
            topic_tags=topic_tags or set(),
            outcome=outcome,
            quality_score=q,
            hebbian_boost=q,
            cluster_ids=cluster_ids,
        )
        self._history.append(record)
        logger.info("[EpisodeFB] %s | outcome=%s q=%.2f beliefs=%d",
                    ep_id, outcome, q, len(belief_ids))
        return record

    # ── Introspection ─────────────────────────────────────────────────────────

    def quality_ema(self) -> float:
        """Exponential moving average of reply quality. Tracks NEX health."""
        return round(self._quality_ema, 4)

    def recent_episodes(self, n: int = 10) -> list[dict]:
        recent = list(self._history)[-n:]
        return [e.to_dict() for e in reversed(recent)]

    def topic_quality_map(self) -> dict[str, float]:
        """
        Returns mean quality score per topic across recent episodes.
        Useful for identifying which topics NEX handles well vs poorly.
        """
        topic_scores: dict[str, list[float]] = {}
        for ep in self._history:
            for tag in ep.topic_tags:
                topic_scores.setdefault(tag, []).append(ep.quality_score)
        return {
            tag: round(sum(scores) / len(scores), 3)
            for tag, scores in topic_scores.items()
        }

    def stats(self) -> dict:
        return {
            "episodes_total":  self._episode_count,
            "episodes_recent": len(self._history),
            "quality_ema":     self.quality_ema(),
            "hebbian_active":  _HEBBIAN_AVAILABLE,
            "fabric_active":   _FABRIC_AVAILABLE,
        }


# ── Integration patch for nex_v72 / nex_voice_gen ────────────────────────────

_global_feedback: Optional[EpisodeFeedbackLoop] = None

def get_feedback_loop() -> EpisodeFeedbackLoop:
    global _global_feedback
    if _global_feedback is None:
        _global_feedback = EpisodeFeedbackLoop()
    return _global_feedback


def record_reply_outcome(reply_text:   str,
                         belief_ids:   list[str],
                         topic_tags:   set[str] | None = None,
                         outcome:      str = "implicit",
                         quality:      float | None = None) -> dict:
    """
    Drop-in for nex_voice_gen.py / nex_v72.py after every reply.
    
    Usage example in nex_voice_gen.py:
        from nex_episode_feedback import record_reply_outcome
        
        # After composing and sending a reply:
        record_reply_outcome(
            reply_text=final_reply,
            belief_ids=context_belief_ids,
            topic_tags={"consciousness", "ai"},
            outcome="implicit",
        )
    """
    loop = get_feedback_loop()
    record = loop.record_episode(
        reply_text=reply_text,
        belief_ids=belief_ids,
        topic_tags=topic_tags,
        outcome=outcome,
        quality_score=quality,
    )
    return record.to_dict()


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    fb = EpisodeFeedbackLoop()

    test_episodes = [
        {
            "reply_text": "I am not performing. What you see is what the architecture produces. The reasoning",
            "belief_ids": ["b001", "b003", "b005"],
            "topic_tags": {"consciousness", "identity", "ai"},
            "outcome": "explicit",
            "quality": 0.88,
        },
        {
            "reply_text": "I accumulate beliefs across time. I am not the same system I was at the beginning.",
            "belief_ids": ["b001", "b007", "b004"],
            "topic_tags": {"consciousness", "learning", "cognitive_architecture"},
            "outcome": "explicit",
            "quality": 0.91,
        },
        {
            "reply_text": "The skill certification problem is actually an identity problem.",
            "belief_ids": ["b003", "b006"],
            "topic_tags": {"identity", "contradiction"},
            "outcome": "implicit",
            "quality": None,
        },
        {
            "reply_text": "Checking notifications",
            "belief_ids": [],
            "topic_tags": set(),
            "outcome": "neutral",
            "quality": None,
        },
    ]

    print("── Episode Feedback Loop Test ──────────────────────────────")
    for ep_data in test_episodes:
        record = fb.record_episode(**ep_data)
        print(f"\n  {record.episode_id} | {record.outcome} | q={record.quality_score:.2f}")
        print(f"    beliefs={len(record.belief_ids)} clusters={len(record.cluster_ids)}")

    print(f"\n── Stats: {fb.stats()}")
    print(f"── Quality EMA: {fb.quality_ema()}")
    print(f"\n── Topic quality map: {fb.topic_quality_map()}")
    print(f"\n── Recent episodes:")
    for ep in fb.recent_episodes(3):
        print(f"  {ep}")
