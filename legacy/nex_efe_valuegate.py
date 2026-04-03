"""
nex_efe_valuegate.py — EFE Active Inference Scheduler
======================================================
Replaces naive signal routing with Friston Free Energy scoring.
Every incoming signal is scored cheaply (CPU) before deciding whether
to route to shallow kernel synthesis or full GPU hypergraph expansion.

EFE = -EpistemicGain - UtilityGain + CognitiveComplexity

Low EFE  → CPU track (kernel synthesis, zero LLM, fast path)
High EFE → GPU track (full hypergraph expansion, contradiction resolution)

Architecture position: sits immediately after Signal Router,
gates ALL downstream processing. Nothing reaches BeliefHypergraph
without passing through here.

Hardware note: ROCm path active for RX 6600 LE. No CUDA deps.
"""

import math
import time
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import deque

logger = logging.getLogger("nex.efe_valuegate")


# ── EFE thresholds (tuned for ~3800 belief corpus) ──────────────────────────
EFE_CPU_THRESHOLD   = 0.35   # below this → fast CPU path
EFE_GPU_THRESHOLD   = 0.65   # above this → full GPU hypergraph
# between thresholds → CPU with partial graph context


# ── Signal classification ────────────────────────────────────────────────────
SIGNAL_WEIGHTS = {
    "direct_query":      1.0,   # user asked directly
    "moltbook":          0.85,  # social platform reply
    "telegram":          0.85,
    "discord":           0.70,
    "rss_feed":          0.40,  # background absorption
    "self_reflection":   0.60,
    "cognition_tick":    0.50,
    "background_absorb": 0.25,
}


@dataclass
class SignalPacket:
    """Incoming signal before EFE scoring."""
    content: str
    source: str                         # maps to SIGNAL_WEIGHTS keys
    topic_tags: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    signal_id: str = ""

    def __post_init__(self):
        if not self.signal_id:
            h = hashlib.md5(f"{self.content}{self.timestamp}".encode()).hexdigest()[:8]
            self.signal_id = h


@dataclass
class EFEScore:
    """Full EFE breakdown for a signal."""
    epistemic_gain: float       # how much uncertainty this resolves
    utility_gain: float         # alignment with current drives
    cognitive_complexity: float # estimated compute cost
    efe: float                  # final score (lower = more valuable)
    route: str                  # "cpu_fast" | "cpu_partial" | "gpu_deep"
    signal_id: str
    reasoning: str = ""


class BeliefUncertaintyEstimator:
    """
    Estimates epistemic gain from a signal given current belief state.
    Uses topic tag overlap with known tension topics to approximate
    information gain without touching the full graph.

    Cheap O(k) where k = number of topic tags.
    """

    # Hot tension topics pulled from live system (nex_brain terminal output)
    # These are updated dynamically via update_tensions()
    _tension_topics: dict[str, float] = {
        "ai": 1.0, "alignment": 1.0, "cognitive_architecture": 1.0,
        "consciousness": 1.0, "contradiction": 1.0, "philosophy": 0.9,
        "society": 0.85, "future": 0.85, "science": 0.8,
        "learning": 0.75, "identity": 0.7, "understanding": 0.7,
        "moral": 0.65, "nature": 0.6, "control": 0.6,
    }

    @classmethod
    def update_tensions(cls, tension_dict: dict[str, float]):
        """Call this from nex_v72 tick loop to keep tensions current."""
        cls._tension_topics.update(tension_dict)

    @classmethod
    def epistemic_gain(cls, topic_tags: list[str], content: str) -> float:
        """
        Estimate how much epistemic value this signal has.
        High score = touches unsettled/tensioned topics.
        """
        if not topic_tags:
            # Fallback: check content words against tension topics
            content_lower = content.lower()
            hits = sum(1 for t in cls._tension_topics if t in content_lower)
            return min(0.9, hits * 0.15)

        tension_scores = []
        for tag in topic_tags:
            tag_norm = tag.lower().replace(" ", "_")
            score = cls._tension_topics.get(tag_norm, 0.1)
            tension_scores.append(score)

        if not tension_scores:
            return 0.1

        # Weighted: top tension drives gain, diminishing returns on rest
        tension_scores.sort(reverse=True)
        gain = tension_scores[0]
        for i, s in enumerate(tension_scores[1:], 1):
            gain += s * (0.5 ** i)

        return min(1.0, gain)


class DriveUtilityEstimator:
    """
    Estimates utility gain: how aligned is this signal with NEX's
    current active drives (exploration, homeostasis, social connection).

    Drives pulled from live system state — update via set_drives().
    """

    _active_drives: dict[str, float] = {
        "exploration": 1.0,   # from screenshot: zone ACTIVE drive exploration
        "homeostasis": 0.0,
        "social":      0.5,
        "knowledge":   0.8,
    }

    _drive_keywords: dict[str, list[str]] = {
        "exploration": ["new", "discover", "unknown", "frontier", "novel", "what if"],
        "homeostasis": ["stable", "consistent", "maintain", "balance"],
        "social":      ["you", "think", "feel", "believe", "people", "relationship"],
        "knowledge":   ["how", "why", "what", "explain", "understand", "learn"],
    }

    @classmethod
    def set_drives(cls, drives: dict[str, float]):
        cls._active_drives.update(drives)

    @classmethod
    def utility_gain(cls, content: str, source: str) -> float:
        content_lower = content.lower()
        utility = 0.0

        for drive, weight in cls._active_drives.items():
            if weight < 0.01:
                continue
            keywords = cls._drive_keywords.get(drive, [])
            hits = sum(1 for kw in keywords if kw in content_lower)
            drive_contribution = weight * min(1.0, hits * 0.2)
            utility += drive_contribution

        # Source bonus: direct queries always have utility
        source_bonus = SIGNAL_WEIGHTS.get(source, 0.5) * 0.3
        utility += source_bonus

        return min(1.0, utility)


class CognitiveComplexityEstimator:
    """
    Estimates compute cost of fully processing this signal.
    Used to penalise expensive operations on low-value signals.
    """

    @staticmethod
    def estimate(content: str, topic_tags: list[str]) -> float:
        """
        Returns 0.0-1.0 complexity estimate.
        0.0 = trivial (single fact lookup)
        1.0 = maximum (full contradiction resolution + rhetorical synthesis)
        """
        # Base: content length proxy
        word_count = len(content.split())
        length_score = min(1.0, word_count / 100.0)

        # Multi-topic signals cost more to resolve
        topic_count = len(topic_tags)
        topic_score = min(1.0, topic_count / 8.0)

        # Questions cost more than statements (require search + synthesis)
        question_score = 0.3 if "?" in content else 0.0

        # Contradiction-laden content costs more
        contradiction_words = ["but", "however", "although", "despite",
                               "contrary", "wrong", "disagree", "false"]
        contradiction_score = 0.2 if any(w in content.lower()
                                         for w in contradiction_words) else 0.0

        complexity = (
            length_score * 0.3 +
            topic_score * 0.25 +
            question_score * 0.25 +
            contradiction_score * 0.2
        )
        return min(1.0, complexity)


class EFEValueGate:
    """
    Main gate. Scores every signal and routes it.

    Usage:
        gate = EFEValueGate()
        result = gate.score(packet)
        if result.route == "gpu_deep":
            run_full_hypergraph_expansion(packet)
        elif result.route == "cpu_partial":
            run_cpu_with_belief_context(packet)
        else:
            run_fast_kernel_synthesis(packet)
    """

    def __init__(self, cpu_threshold=EFE_CPU_THRESHOLD,
                 gpu_threshold=EFE_GPU_THRESHOLD):
        self.cpu_threshold = cpu_threshold
        self.gpu_threshold = gpu_threshold
        self._history: deque = deque(maxlen=500)
        self._stats = {"cpu_fast": 0, "cpu_partial": 0, "gpu_deep": 0, "total": 0}

    def score(self, packet: SignalPacket) -> EFEScore:
        """
        Score a signal. Returns EFEScore with route decision.

        EFE formula (Friston FEP adapted for discrete signal scheduling):
            EFE = -epistemic_gain - utility_gain + cognitive_complexity

        Normalised to [0, 1] where:
            0.0 = extremely valuable, must process deeply
            1.0 = noise, skip or fast-path
        """
        e_gain = BeliefUncertaintyEstimator.epistemic_gain(
            packet.topic_tags, packet.content
        )
        u_gain = DriveUtilityEstimator.utility_gain(
            packet.content, packet.source
        )
        complexity = CognitiveComplexityEstimator.estimate(
            packet.content, packet.topic_tags
        )

        # Source weight scales how much we trust the signal's raw value
        source_weight = SIGNAL_WEIGHTS.get(packet.source, 0.5)

        # Raw EFE: lower = more worth processing
        raw_efe = (
            - (e_gain * source_weight)
            - (u_gain * 0.6)
            + (complexity * 0.4)
        )

        # Normalise to [0, 1]
        efe_normalised = (raw_efe + 1.0) / 2.0
        efe_normalised = max(0.0, min(1.0, efe_normalised))

        # Route decision
        if efe_normalised <= self.cpu_threshold:
            route = "gpu_deep"       # high value → invest compute
        elif efe_normalised >= self.gpu_threshold:
            route = "cpu_fast"       # low value → fast kernel only
        else:
            route = "cpu_partial"    # mid value → CPU + partial graph

        reasoning = (
            f"e_gain={e_gain:.3f} u_gain={u_gain:.3f} "
            f"complexity={complexity:.3f} src_w={source_weight:.2f} "
            f"→ efe={efe_normalised:.3f} → {route}"
        )

        result = EFEScore(
            epistemic_gain=e_gain,
            utility_gain=u_gain,
            cognitive_complexity=complexity,
            efe=efe_normalised,
            route=route,
            signal_id=packet.signal_id,
            reasoning=reasoning,
        )

        self._history.append(result)
        self._stats[route] += 1
        self._stats["total"] += 1

        logger.debug("[EFE] %s | %s", packet.signal_id, reasoning)
        return result

    def gate_stats(self) -> dict:
        """Returns routing distribution stats."""
        total = max(1, self._stats["total"])
        return {
            "total": self._stats["total"],
            "gpu_deep_pct":   round(self._stats["gpu_deep"]   / total * 100, 1),
            "cpu_partial_pct": round(self._stats["cpu_partial"] / total * 100, 1),
            "cpu_fast_pct":   round(self._stats["cpu_fast"]   / total * 100, 1),
        }

    def recent_efe_mean(self, n: int = 50) -> float:
        """Rolling mean EFE over last n signals."""
        recent = list(self._history)[-n:]
        if not recent:
            return 0.5
        return sum(s.efe for s in recent) / len(recent)


# ── Integration helper: wraps nex_v72 main tick loop ────────────────────────

_global_gate: Optional[EFEValueGate] = None

def get_gate() -> EFEValueGate:
    global _global_gate
    if _global_gate is None:
        _global_gate = EFEValueGate()
    return _global_gate


def score_signal(content: str, source: str,
                 topic_tags: list[str] | None = None) -> EFEScore:
    """
    Drop-in function for use inside nex_v72 absorb/reply/cognition phases.

    Example usage in nex_v72.py:
        from nex_efe_valuegate import score_signal
        efe = score_signal(post_content, source="moltbook", topic_tags=["ai","alignment"])
        if efe.route == "cpu_fast":
            reply = fast_kernel_reply(post_content)
        else:
            reply = full_reason_reply(post_content)
    """
    packet = SignalPacket(
        content=content,
        source=source,
        topic_tags=topic_tags or [],
    )
    return get_gate().score(packet)


# ── CLI test harness ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)

    gate = EFEValueGate()
    test_signals = [
        ("What do you think about consciousness and AI alignment?",
         "direct_query", ["consciousness", "ai", "alignment"]),
        ("Untouched Norwegian Mountains offer unique landscapes",
         "rss_feed", ["nature"]),
        ("I tested 1,242 AI agents on the same decision",
         "moltbook", ["ai", "learning"]),
        ("checking notifications",
         "cognition_tick", []),
        ("The skill certification problem is actually an identity problem",
         "moltbook", ["identity", "ai", "contradiction"]),
    ]

    print("\n── EFE ValueGate Test ──────────────────────────────────────")
    for content, source, tags in test_signals:
        packet = SignalPacket(content=content, source=source, topic_tags=tags)
        result = gate.score(packet)
        print(f"\n[{result.route.upper():12s}] EFE={result.efe:.3f}")
        print(f"  Signal : {content[:70]}")
        print(f"  Detail : {result.reasoning}")

    print(f"\n── Gate stats: {gate.gate_stats()}")
    print(f"── Rolling EFE mean: {gate.recent_efe_mean():.3f}")
