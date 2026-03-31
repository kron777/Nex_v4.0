#!/usr/bin/env python3
"""
nex_graph_memory.py — NEX Phase 6: Graph Memory
================================================
Place at: ~/Desktop/nex/nex_graph_memory.py

Memory is not a text log.
Memory is the activation trail — which beliefs were recently touched,
and how strongly. Recently activated beliefs glow when the graph
is queried again. The glow fades with time.

This replaces the session history text approach in soul_loop with
a graph-native memory: recency encoded as activation residue.

Core concept:
  - Every time reason() runs, activated belief IDs + scores are stored
  - On next query, beliefs that were recently activated get a glow boost
  - Glow decays exponentially with time (half-life ~2.3 hours)
  - Mood from emotion_field naturally reflects recent activation history

Glow formula:
  glow(belief_id) = peak_activation * exp(-DECAY * hours_since_activation)
  DECAY = 0.3  →  half-life = ln(2)/0.3 ≈ 2.3 hours

Persistence:
  - Trail written to ~/.config/nex/nex_graph_memory.json
  - Survives restarts, fades naturally over time
  - Pruned to MAX_TRAIL_SIZE entries to stay lean

Usage:
  from nex_graph_memory import GraphMemory, record_trail, glow_boosts

  # After activation:
  record_trail(activation_result)

  # In reason() scoring:
  boosts = glow_boosts()
  score += boosts.get(belief_id, 0.0)
"""

import json
import math
import time
from pathlib import Path
from typing import Optional

CFG_PATH    = Path("~/.config/nex").expanduser()
TRAIL_PATH  = CFG_PATH / "nex_graph_memory.json"

# Glow decay constant — ln(2)/DECAY = half-life in hours
GLOW_DECAY      = 0.3    # half-life ≈ 2.3 hours
MAX_GLOW        = 0.4    # cap on glow boost to avoid dominating score
MIN_GLOW        = 0.01   # prune entries below this
MAX_TRAIL_SIZE  = 200    # max belief IDs tracked


class GraphMemory:
    """
    Tracks which beliefs were recently activated and how strongly.
    Computes recency glow for score boosting in reason().
    """

    def __init__(self):
        self._trail: dict[int, dict] = {}   # {belief_id: {peak, last_time, hits}}
        self._load()

    def _load(self):
        try:
            if TRAIL_PATH.exists():
                data = json.loads(TRAIL_PATH.read_text())
                # Restore trail, prune dead entries immediately
                now = time.time()
                for k, v in data.items():
                    bid = int(k)
                    hours = (now - v["last_time"]) / 3600
                    glow  = v["peak"] * math.exp(-GLOW_DECAY * hours)
                    if glow >= MIN_GLOW:
                        self._trail[bid] = v
        except Exception:
            pass

    def _save(self):
        try:
            CFG_PATH.mkdir(parents=True, exist_ok=True)
            # Convert int keys to strings for JSON
            TRAIL_PATH.write_text(
                json.dumps({str(k): v for k, v in self._trail.items()}, indent=2)
            )
        except Exception as e:
            print(f"  [graph_memory] save error: {e}")

    def record(self, activation_result) -> int:
        """
        Record an activation trail from an ActivationResult.
        Returns count of beliefs recorded.
        """
        now = time.time()
        recorded = 0

        for belief in activation_result.activated:
            bid = belief.id
            act = float(belief.activation)

            if bid in self._trail:
                existing = self._trail[bid]
                # Update: take peak activation, refresh timestamp
                self._trail[bid] = {
                    "peak":      max(existing["peak"], act),
                    "last_time": now,
                    "hits":      existing.get("hits", 1) + 1,
                    "topic":     belief.topic,
                }
            else:
                self._trail[bid] = {
                    "peak":      act,
                    "last_time": now,
                    "hits":      1,
                    "topic":     belief.topic,
                }
            recorded += 1

        # Prune: remove faded entries and keep trail lean
        self._prune()
        self._save()
        return recorded

    def _prune(self):
        """Remove entries whose glow has faded below threshold."""
        now  = time.time()
        dead = []
        for bid, v in self._trail.items():
            hours = (now - v["last_time"]) / 3600
            glow  = v["peak"] * math.exp(-GLOW_DECAY * hours)
            if glow < MIN_GLOW:
                dead.append(bid)

        for bid in dead:
            del self._trail[bid]

        # Hard cap — keep most recently activated if still too large
        if len(self._trail) > MAX_TRAIL_SIZE:
            sorted_by_time = sorted(
                self._trail.items(), key=lambda x: x[1]["last_time"], reverse=True
            )
            self._trail = dict(sorted_by_time[:MAX_TRAIL_SIZE])

    def glow_boosts(self) -> dict[int, float]:
        """
        Compute current glow for all tracked beliefs.
        Returns {belief_id: glow_boost} — add to score in reason().
        """
        now    = time.time()
        boosts = {}
        for bid, v in self._trail.items():
            hours = (now - v["last_time"]) / 3600
            glow  = v["peak"] * math.exp(-GLOW_DECAY * hours)
            if glow >= MIN_GLOW:
                # Multi-hit bonus: beliefs touched repeatedly glow brighter
                hits_bonus = min(0.1, (v.get("hits", 1) - 1) * 0.02)
                boosts[bid] = round(min(MAX_GLOW, glow + hits_bonus), 4)
        return boosts

    def hot_topics(self, n: int = 5) -> list[dict]:
        """
        Return the most actively glowing topics.
        Useful for drive weighting and curiosity steering.
        """
        now    = time.time()
        topic_glow: dict[str, float] = {}

        for bid, v in self._trail.items():
            hours = (now - v["last_time"]) / 3600
            glow  = v["peak"] * math.exp(-GLOW_DECAY * hours)
            topic = v.get("topic", "general")
            if glow >= MIN_GLOW:
                topic_glow[topic] = max(topic_glow.get(topic, 0.0), glow)

        sorted_topics = sorted(topic_glow.items(), key=lambda x: -x[1])
        return [{"topic": t, "glow": round(g, 4)} for t, g in sorted_topics[:n]]

    def trail_size(self) -> int:
        return len(self._trail)

    def summary(self) -> dict:
        boosts = self.glow_boosts()
        return {
            "trail_size":  len(self._trail),
            "live_glows":  len(boosts),
            "max_glow":    round(max(boosts.values()), 4) if boosts else 0.0,
            "hot_topics":  self.hot_topics(3),
        }


# ── Module-level singleton ────────────────────────────────────────────────────
_memory: Optional[GraphMemory] = None

def _get_memory() -> GraphMemory:
    global _memory
    if _memory is None:
        _memory = GraphMemory()
    return _memory


def record_trail(activation_result) -> int:
    """Record activation trail. Call after every nex_activation.activate()."""
    return _get_memory().record(activation_result)


def glow_boosts() -> dict:
    """
    Return current glow boosts for all recently activated beliefs.
    Call in reason() — add boost to belief score before ranking.
    """
    return _get_memory().glow_boosts()


def hot_topics(n: int = 5) -> list:
    """Return most glowing topics for drive/curiosity steering."""
    return _get_memory().hot_topics(n)


def summary() -> dict:
    """Return graph memory summary dict."""
    return _get_memory().summary()


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path("~/Desktop/nex").expanduser()))

    print("  Loading activation engine...")
    try:
        from nex_activation import activate as _activate

        queries = [
            "what do you think about consciousness?",
            "how does memory relate to identity?",
            "what do you think about consciousness?",   # repeat — should glow brighter
        ]

        mem = GraphMemory()

        for q in queries:
            print(f"\n  Query: {q}")
            ar = _activate(q)
            count = mem.record(ar)
            print(f"  Recorded {count} beliefs into trail")

        print(f"\n  Memory summary: {mem.summary()}")
        print(f"\n  Hot topics:")
        for t in mem.hot_topics():
            print(f"    {t['topic']}: glow={t['glow']}")

        boosts = mem.glow_boosts()
        print(f"\n  Top 5 glowing beliefs:")
        top = sorted(boosts.items(), key=lambda x: -x[1])[:5]
        for bid, glow in top:
            print(f"    belief_id={bid}  glow={glow}")

    except ImportError as e:
        print(f"  nex_activation not found: {e}")
        print("  Testing with mock data...")

        class MockBelief:
            def __init__(self, i, a, t):
                self.id = i
                self.activation = a
                self.topic = t

        class MockResult:
            activated = [
                MockBelief(101, 0.9, "consciousness"),
                MockBelief(102, 0.7, "consciousness"),
                MockBelief(103, 0.5, "memory"),
                MockBelief(104, 0.4, "identity"),
            ]

        mem = GraphMemory()
        mem.record(MockResult())
        mem.record(MockResult())   # second hit — beliefs should show hits=2

        print(f"  Trail size: {mem.trail_size()}")
        boosts = mem.glow_boosts()
        print(f"  Boosts: {boosts}")
        print(f"  Hot topics: {mem.hot_topics()}")
        print(f"  Summary: {mem.summary()}")
