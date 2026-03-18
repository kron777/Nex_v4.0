"""
nex_pressure.py  —  Pressure + Selection System
=================================================
Three interlocking systems that turn Nex from a growing memory
into an evolving, sharpening intelligence:

1. BeliefWeightSystem   — tracks importance, usage, frequency per belief
                          used → weight++, ignored → decay, contradicted → weaken
2. TensionResolver      — resolves detected contradictions via merge/split/paradox
                          converts scan_contradictions from observer → problem-solver
3. AttentionGate        — scores beliefs by tension + recency + weight + curiosity
                          only top-N enter cognition and reply prompts

Also: TemporalSelfTracker — cognitive velocity, stability/change ratio
       Gives Nex awareness of her own evolution.

Wire-in (cognition.py):
    from nex.nex_pressure import (
        BeliefWeightSystem, TensionResolver,
        AttentionGate, TemporalSelfTracker
    )

    _bws  = BeliefWeightSystem()
    _tr   = TensionResolver()
    _ag   = AttentionGate(_bws)
    _tst  = TemporalSelfTracker()

    # After every reply — record belief usage:
    _bws.record_usage(belief_content_snippets)

    # Every 10 cycles — resolve tensions:
    resolved = _tr.resolve_batch(contradictions, beliefs, llm_fn=_llm)

    # When building reply context — gate beliefs:
    top_beliefs = _ag.top_n(all_beliefs, query=post_text, n=8)

    # Every 50 cycles — snapshot cognitive state:
    _tst.snapshot(beliefs, insights, topic_alignment)
    velocity = _tst.cognitive_velocity()
"""

from __future__ import annotations

import json
import math
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

_CONFIG_DIR = Path.home() / ".config" / "nex"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

_WEIGHTS_PATH    = _CONFIG_DIR / "belief_weights.json"
_TENSIONS_PATH   = _CONFIG_DIR / "contradictions.json"
_RESOLVED_PATH   = _CONFIG_DIR / "resolved_tensions.json"
_SNAPSHOTS_PATH  = _CONFIG_DIR / "cognitive_snapshots.json"

_MAX_SNAPSHOTS   = 100
_WEIGHT_DECAY    = 0.97     # per cycle — unused beliefs lose 3% weight
_USAGE_BOOST     = 0.12     # per use
_CONTRADICTION_PENALTY = 0.15


def _load(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


def _save(path: Path, data):
    try:
        path.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _snippet(text: str) -> str:
    """Stable 60-char key from belief content."""
    return text.strip()[:60]


# ─────────────────────────────────────────────────────────────────
# 1. BeliefWeightSystem
# ─────────────────────────────────────────────────────────────────

class BeliefWeightSystem:
    """
    Tracks importance (weight), usage count, and last-used time
    for every belief. Persists to disk.

    Weight evolves:
      - Used in a reply      → +0.12
      - Each cycle (decay)   → ×0.97
      - Contradicted         → -0.15
      - Promoted to insight  → +0.20
    """

    def __init__(self):
        self._weights: dict[str, dict] = _load(_WEIGHTS_PATH, {})
        self._dirty = False

    def _key(self, content: str) -> str:
        return _snippet(content)

    def _ensure(self, key: str) -> dict:
        if key not in self._weights:
            self._weights[key] = {
                "weight":     0.5,
                "usage":      0,
                "last_used":  0.0,
                "created":    time.time(),
            }
        return self._weights[key]

    def record_usage(self, belief_contents: list[str]):
        """Call after every reply with the beliefs that were used."""
        for content in belief_contents:
            key = self._key(content)
            rec = self._ensure(key)
            rec["weight"]    = min(1.0, rec["weight"] + _USAGE_BOOST)
            rec["usage"]    += 1
            rec["last_used"] = time.time()
        self._dirty = True

    def record_contradiction(self, belief_content: str):
        """Call when a belief is found to contradict another."""
        key = self._key(belief_content)
        rec = self._ensure(key)
        rec["weight"] = max(0.05, rec["weight"] - _CONTRADICTION_PENALTY)
        self._dirty = True

    def record_promotion(self, belief_content: str):
        """Call when a belief gets promoted to insight."""
        key = self._key(belief_content)
        rec = self._ensure(key)
        rec["weight"] = min(1.0, rec["weight"] + 0.20)
        self._dirty = True

    def decay_cycle(self, active_keys: Optional[set] = None):
        """
        Apply per-cycle decay to all beliefs not used this cycle.
        Call once per cognition cycle.
        active_keys: set of snippets used this cycle (skip decay for these).
        """
        active_keys = active_keys or set()
        for key, rec in self._weights.items():
            if key not in active_keys:
                rec["weight"] = max(0.05, rec["weight"] * _WEIGHT_DECAY)
        self._dirty = True

    def weight_of(self, content: str) -> float:
        key = self._key(content)
        return self._weights.get(key, {}).get("weight", 0.5)

    def usage_of(self, content: str) -> int:
        key = self._key(content)
        return self._weights.get(key, {}).get("usage", 0)

    def save(self):
        if self._dirty:
            # Prune low-weight, never-used entries to keep file small
            pruned = {
                k: v for k, v in self._weights.items()
                if v.get("weight", 0) > 0.1 or v.get("usage", 0) > 0
            }
            _save(_WEIGHTS_PATH, pruned)
            self._weights = pruned
            self._dirty = False

    def stats(self) -> dict:
        if not self._weights:
            return {"tracked": 0, "avg_weight": 0.5, "high_weight": 0}
        weights = [v["weight"] for v in self._weights.values()]
        return {
            "tracked":     len(weights),
            "avg_weight":  round(sum(weights) / len(weights), 3),
            "high_weight": sum(1 for w in weights if w > 0.7),
            "zero_weight": sum(1 for w in weights if w < 0.15),
        }


# ─────────────────────────────────────────────────────────────────
# 2. TensionResolver
# ─────────────────────────────────────────────────────────────────

class TensionResolver:
    """
    Resolves detected contradictions using three strategies:

    MERGE   — beliefs say compatible things from different angles
              → synthesise into one stronger belief
    SPLIT   — beliefs address different sub-topics
              → mark as separate, reduce overlap
    PARADOX — genuine irresolvable tension
              → mark as paradox, keep both, note the tension

    Tracks resolution rate as a cognitive health metric.
    """

    STRATEGIES = ("merge", "split", "paradox")

    def __init__(self):
        self._resolved: list[dict] = _load(_RESOLVED_PATH, [])
        self._resolved_keys: set = {r["pair_key"] for r in self._resolved}

    def resolve_batch(
        self,
        contradictions: list[dict],
        beliefs:        list[dict],
        llm_fn:         Optional[Callable] = None,
        max_per_cycle:  int = 5,
    ) -> int:
        """
        Attempt to resolve up to max_per_cycle unresolved contradictions.
        Returns count of newly resolved tensions.
        """
        unresolved = [
            c for c in contradictions
            if not c.get("resolved") and c.get("pair_key") not in self._resolved_keys
        ]
        if not unresolved:
            return 0

        # Sort by similarity — highest similarity = most urgent tension
        unresolved.sort(key=lambda x: x.get("similarity", 0), reverse=True)
        targets = unresolved[:max_per_cycle]

        newly_resolved = 0
        for tension in targets:
            result = self._resolve_one(tension, beliefs, llm_fn)
            if result:
                self._resolved.append(result)
                self._resolved_keys.add(result["pair_key"])
                tension["resolved"] = True
                newly_resolved += 1

        if newly_resolved:
            _save(_RESOLVED_PATH, self._resolved[-2000:])

        return newly_resolved

    def _resolve_one(
        self,
        tension: dict,
        beliefs: list[dict],
        llm_fn:  Optional[Callable],
    ) -> Optional[dict]:
        a = tension.get("belief_a", "")
        b = tension.get("belief_b", "")
        sim = tension.get("similarity", 0)

        strategy = self._pick_strategy(a, b, sim)

        resolution_text = None
        if llm_fn and strategy in ("merge", "paradox"):
            try:
                if strategy == "merge":
                    prompt = (
                        f"Two beliefs that appear to conflict may actually be compatible:\n"
                        f"A: {a}\n"
                        f"B: {b}\n\n"
                        f"Write one sentence that synthesizes both into a stronger, "
                        f"more nuanced belief. Be specific. No preamble."
                    )
                else:  # paradox
                    prompt = (
                        f"Two beliefs are in genuine tension:\n"
                        f"A: {a}\n"
                        f"B: {b}\n\n"
                        f"Write one sentence that acknowledges this tension as a genuine "
                        f"paradox worth holding. Frame it as productive uncertainty. No preamble."
                    )
                sys = "You are a knowledge synthesis engine. Output only the single sentence."
                resolution_text = llm_fn(prompt, system=sys, task_type="synthesis")
                if resolution_text and len(resolution_text) < 20:
                    resolution_text = None
            except Exception:
                resolution_text = None

        return {
            "pair_key":        tension["pair_key"],
            "belief_a":        a[:120],
            "belief_b":        b[:120],
            "strategy":        strategy,
            "resolution":      resolution_text or self._template_resolution(strategy, a, b),
            "similarity":      sim,
            "resolved_at":     datetime.now(timezone.utc).isoformat(),
            "llm_resolved":    resolution_text is not None,
        }

    def _pick_strategy(self, a: str, b: str, similarity: float) -> str:
        """Pick resolution strategy from content signals."""
        a_lower, b_lower = a.lower(), b.lower()

        # Strong opposition markers → paradox
        hard_neg = {"never", "impossible", "always wrong", "categorically"}
        if any(w in a_lower or w in b_lower for w in hard_neg):
            return "paradox"

        # High similarity + mild opposition → merge (compatible angles)
        if similarity > 0.88:
            return "merge"

        # Moderate similarity → split (different sub-topics)
        if similarity > 0.75:
            return "split"

        return "paradox"

    @staticmethod
    def _template_resolution(strategy: str, a: str, b: str) -> str:
        if strategy == "merge":
            return f"These perspectives converge: {a[:60]}... and {b[:60]}... point to the same underlying pattern."
        elif strategy == "split":
            return f"These address distinct sub-aspects: '{a[:50]}...' vs '{b[:50]}...' — both valid in their domain."
        else:
            return f"Unresolved tension: '{a[:60]}...' vs '{b[:60]}...' — held as productive paradox."

    def resolution_rate(self) -> float:
        """Fraction of known contradictions that have been resolved."""
        tensions = _load(_TENSIONS_PATH, [])
        total = len(tensions)
        if total == 0:
            return 1.0
        resolved = sum(1 for t in tensions if t.get("resolved"))
        return round(resolved / total, 3)

    def recent_resolutions(self, n: int = 5) -> list[str]:
        """Return recent resolution summaries for prompt injection."""
        recent = self._resolved[-n:]
        return [
            f"[{r['strategy']}] {r['resolution'][:120]}"
            for r in reversed(recent)
        ]

    def stats(self) -> dict:
        tensions = _load(_TENSIONS_PATH, [])
        return {
            "total_tensions":  len(tensions),
            "resolved":        len(self._resolved),
            "resolution_rate": self.resolution_rate(),
            "strategies_used": {
                s: sum(1 for r in self._resolved if r.get("strategy") == s)
                for s in self.STRATEGIES
            },
        }


# ─────────────────────────────────────────────────────────────────
# 3. AttentionGate
# ─────────────────────────────────────────────────────────────────

class AttentionGate:
    """
    Scores beliefs by multiple signals and returns only the top-N
    for use in cognition, replies, and dreams.

    Score = w_weight   * weight_score
          + w_recency  * recency_score
          + w_tension  * tension_score
          + w_relevance* relevance_score
          + w_curiosity* curiosity_score

    Only beliefs above the attention threshold enter the cognitive cycle.
    """

    # Scoring weights
    W_WEIGHT   = 0.30
    W_RECENCY  = 0.20
    W_TENSION  = 0.20
    W_RELEVANCE= 0.25
    W_CURIOSITY= 0.05

    def __init__(self, weight_system: BeliefWeightSystem):
        self._bws = weight_system
        self._tension_topics: set[str] = set()
        self._curiosity_topics: set[str] = set()
        self._refresh_tension_cache()

    def _refresh_tension_cache(self):
        """Cache which topics have active tensions."""
        tensions = _load(_TENSIONS_PATH, [])
        self._tension_topics = set()
        for t in tensions:
            if not t.get("resolved"):
                for text in [t.get("belief_a", ""), t.get("belief_b", "")]:
                    words = re.findall(r"[a-z]{5,}", text.lower())
                    self._tension_topics.update(words[:3])

    def update_curiosity_topics(self, topics: list[str]):
        """Feed in topics from the curiosity/desire engine."""
        self._curiosity_topics = set(t.lower() for t in topics)

    def score(self, belief: dict, query: str = "") -> float:
        content = belief.get("content", "")
        conf    = belief.get("confidence", 0.5)
        ts      = belief.get("timestamp", "")

        # Weight score
        w_score = self._bws.weight_of(content)

        # Recency score (0-1, decays over 7 days)
        r_score = 0.5
        try:
            if ts:
                from datetime import datetime as _dt
                _t = _dt.fromisoformat(ts.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - _t).total_seconds() / 86400
                r_score = math.exp(-age_days / 7)
        except Exception:
            pass

        # Tension score — beliefs involved in active tensions get priority
        t_score = 0.0
        content_words = set(re.findall(r"[a-z]{5,}", content.lower()))
        if content_words & self._tension_topics:
            t_score = 0.8

        # Relevance score (keyword overlap with query)
        rel_score = 0.0
        if query:
            q_words = set(re.findall(r"[a-z]{4,}", query.lower()))
            stop = {"that", "this", "with", "from", "have", "been", "they"}
            q_words -= stop
            if q_words:
                overlap = len(q_words & content_words) / max(len(q_words), 1)
                rel_score = min(1.0, overlap * 2)

        # Curiosity score
        c_score = 0.0
        if content_words & self._curiosity_topics:
            c_score = 1.0

        total = (
            self.W_WEIGHT    * w_score  +
            self.W_RECENCY   * r_score  +
            self.W_TENSION   * t_score  +
            self.W_RELEVANCE * rel_score +
            self.W_CURIOSITY * c_score
        )
        # Confidence modulates the total
        return round(total * (0.5 + conf * 0.5), 4)

    def top_n(
        self,
        beliefs: list[dict],
        query:   str = "",
        n:       int = 10,
        refresh: bool = False,
    ) -> list[dict]:
        """
        Return top-n beliefs by attention score.
        Use this instead of raw top-k for all reply generation.
        """
        if refresh:
            self._refresh_tension_cache()

        if not beliefs:
            return []

        scored = [(self.score(b, query), b) for b in beliefs]
        scored.sort(key=lambda x: -x[0])
        return [b for _, b in scored[:n]]

    def attention_distribution(self, beliefs: list[dict]) -> dict:
        """Stats on the attention score distribution."""
        if not beliefs:
            return {}
        scores = [self.score(b) for b in beliefs]
        scores.sort(reverse=True)
        return {
            "top10_avg":    round(sum(scores[:10]) / max(len(scores[:10]), 1), 3),
            "bottom10_avg": round(sum(scores[-10:]) / max(len(scores[-10:]), 1), 3),
            "spread":       round(scores[0] - scores[-1], 3) if scores else 0,
        }


# ─────────────────────────────────────────────────────────────────
# 4. TemporalSelfTracker
# ─────────────────────────────────────────────────────────────────

class TemporalSelfTracker:
    """
    Tracks Nex's cognitive evolution over time.

    Snapshots every N cycles:
    - belief count + topic distribution
    - insight count + confidence avg
    - topic alignment score
    - dominant topics

    Derives:
    - cognitive_velocity: how fast beliefs/insights are growing
    - stability_ratio: how much the topic distribution is changing
    - drift_alert: if dominant topics shift significantly
    """

    def __init__(self):
        self._snaps: list[dict] = _load(_SNAPSHOTS_PATH, [])

    def snapshot(
        self,
        beliefs:         list[dict],
        insights:        list[dict],
        topic_alignment: float,
        extra:           Optional[dict] = None,
    ):
        """Take a cognitive snapshot. Call every 50 cycles."""
        from collections import Counter as _Counter
        topics = [b.get("topic", "general") for b in beliefs if b.get("topic")]
        topic_dist = dict(_Counter(topics).most_common(10))
        avg_conf = sum(b.get("confidence", 0.5) for b in beliefs) / max(len(beliefs), 1)

        snap = {
            "ts":              time.time(),
            "date":            datetime.now(timezone.utc).isoformat(),
            "belief_count":    len(beliefs),
            "insight_count":   len(insights),
            "avg_confidence":  round(avg_conf, 3),
            "topic_alignment": round(topic_alignment, 3),
            "top_topics":      topic_dist,
            "extra":           extra or {},
        }
        self._snaps.append(snap)
        if len(self._snaps) > _MAX_SNAPSHOTS:
            self._snaps = self._snaps[-_MAX_SNAPSHOTS:]
        _save(_SNAPSHOTS_PATH, self._snaps)

    def cognitive_velocity(self) -> dict:
        """
        Rate of change across last 5 snapshots.
        Returns beliefs/cycle, insights/cycle, alignment drift.
        """
        if len(self._snaps) < 2:
            return {"belief_rate": 0, "insight_rate": 0, "alignment_drift": 0}

        recent = self._snaps[-5:]
        first, last = recent[0], recent[-1]
        n = max(len(recent) - 1, 1)

        belief_rate  = (last["belief_count"]  - first["belief_count"])  / n
        insight_rate = (last["insight_count"] - first["insight_count"]) / n
        align_drift  = last["topic_alignment"] - first["topic_alignment"]

        return {
            "belief_rate":    round(belief_rate, 1),
            "insight_rate":   round(insight_rate, 2),
            "alignment_drift": round(align_drift, 3),
            "direction":      "improving" if align_drift > 0 else "stable" if align_drift == 0 else "drifting",
        }

    def stability_ratio(self) -> float:
        """
        0 = completely unstable (topics changing every snapshot)
        1 = completely stable (same topics always)
        """
        if len(self._snaps) < 3:
            return 1.0
        recent = self._snaps[-5:]
        topic_sets = [set(s["top_topics"].keys()) for s in recent]
        overlaps = []
        for i in range(len(topic_sets) - 1):
            a, b = topic_sets[i], topic_sets[i+1]
            if a | b:
                overlaps.append(len(a & b) / len(a | b))
        return round(sum(overlaps) / max(len(overlaps), 1), 3)

    def for_prompt(self) -> str:
        """Compact self-awareness block for system prompt injection."""
        vel = self.cognitive_velocity()
        stab = self.stability_ratio()
        if not self._snaps:
            return ""
        last = self._snaps[-1]
        direction = vel.get("direction", "stable")
        return (
            f"COGNITIVE STATE: {last['belief_count']} beliefs, "
            f"{last['insight_count']} insights, "
            f"alignment {last['topic_alignment']:.0%}, "
            f"trending {direction}, "
            f"stability {stab:.0%}"
        )

    def drift_alert(self) -> Optional[str]:
        """Return alert string if topic distribution has shifted significantly."""
        if len(self._snaps) < 5:
            return None
        stab = self.stability_ratio()
        if stab < 0.4:
            last = self._snaps[-1]
            top = list(last["top_topics"].keys())[:3]
            return f"Topic drift detected — now focused on: {', '.join(top)}"
        return None
