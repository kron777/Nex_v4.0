"""
nex_desire_engine.py — Weighted Desire Competition
====================================================
Converts passive desire queuing into weighted competing goals
that actually bias NEX's behavior each cycle.

Desire structure:
    {
        goal:        str,       # what NEX wants to explore/do
        weight:      float,     # 0.0-1.0 priority
        domain:      str,       # knowledge domain
        source:      str,       # why this desire exists
        age:         int,       # cycles since created
        fulfilled:   bool,
        fulfillment_score: float
    }

Competition rules:
    - desires decay if not acted on
    - desires grow if reinforced by incoming beliefs
    - dominant desire (highest weight) shapes:
        * curiosity bias (bridge/gap/depth)
        * reply topic preference
        * reflection focus
        * attention gate priority

Wire-in (run.py, replace generate_desires call):
    from nex_desire_engine import DesireEngine, get_desire_engine
    _de = get_desire_engine()
    _de.update(cycle=cycle, beliefs=learner.belief_field, llm_fn=_llm)
    dominant = _de.get_dominant()
    if dominant:
        nex_log('desire', f"[Desire] dominant={dominant['goal']} w={dominant['weight']:.2f}")
"""

import json
import os
import random
import re
from datetime import datetime
from pathlib import Path
from collections import Counter, defaultdict

CONFIG_DIR   = Path.home() / ".config" / "nex"
DESIRE_PATH  = CONFIG_DIR / "desire_state.json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Tuning ────────────────────────────────────────────────────────────────────
MAX_DESIRES         = 12    # max competing desires at once
DECAY_PER_CYCLE     = 0.03  # weight loss per cycle if unfulfilled
REINFORCE_BOOST     = 0.08  # weight gain when relevant belief absorbed
DOMINANCE_THRESHOLD = 0.60  # weight at which a desire becomes "dominant"
KILL_THRESHOLD      = 0.05  # desires below this are pruned
FULFILLMENT_DECAY   = 0.15  # fulfilled desires lose weight faster

# ── Goal templates — what NEX can want ───────────────────────────────────────
GOAL_TEMPLATES = {
    "explore":     "Explore and deepen understanding of {domain}",
    "resolve":     "Resolve contradictions in {domain} beliefs",
    "connect":     "Find connections between {domain} and other domains",
    "validate":    "Validate or challenge high-confidence beliefs in {domain}",
    "expand":      "Expand knowledge at the edges of {domain}",
    "synthesize":  "Synthesize insights from recent {domain} learning",
}

_STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","this","that","it","not",
}


class DesireEngine:
    """
    Manages competing weighted desires that drive NEX's cognitive direction.
    """

    def __init__(self):
        self._desires: list[dict] = []
        self._cycle = 0
        self._load()

    def _load(self):
        if DESIRE_PATH.exists():
            try:
                data = json.loads(DESIRE_PATH.read_text())
                self._desires = data.get("desires", [])
                self._cycle   = data.get("cycle", 0)
            except Exception:
                self._desires = []

    def _save(self):
        try:
            DESIRE_PATH.write_text(json.dumps({
                "desires": self._desires,
                "cycle":   self._cycle,
                "updated": datetime.now().isoformat(),
            }, indent=2))
        except Exception:
            pass

    def _desire_id(self, goal: str) -> str:
        import hashlib
        return hashlib.md5(goal.encode()).hexdigest()[:8]

    def _get_existing(self, goal: str) -> dict | None:
        did = self._desire_id(goal)
        return next((d for d in self._desires if d.get("id") == did), None)

    # ── Seeding desires from belief field ─────────────────────────────────────

    def _seed_from_beliefs(self, beliefs: list) -> int:
        """Create desires based on dominant topics and tensions in belief field."""
        if not beliefs:
            return 0

        # Count topics
        topic_counts = Counter()
        tension_topics = set()
        for b in beliefs:
            topic = b.get("topic") or (b.get("tags") or ["general"])[0]
            topic_counts[topic] += 1
            # Beliefs with contradictions or inversions signal tension
            content = b.get("content", "")
            if any(kw in content.lower() for kw in
                   ["contradict", "tension", "inversion", "counter", "however", "despite"]):
                tension_topics.add(topic)

        top_topics = [t for t, _ in topic_counts.most_common(6)
                      if t not in ("general", "None", "rss", "arxiv")]

        seeded = 0
        for topic in top_topics[:4]:
            # Determine goal type
            if topic in tension_topics:
                goal_type = "resolve"
            elif topic_counts[topic] > 20:
                goal_type = "synthesize"
            elif topic_counts[topic] < 5:
                goal_type = "expand"
            else:
                goal_type = random.choice(["explore", "connect", "validate"])

            goal = GOAL_TEMPLATES[goal_type].format(domain=topic)
            weight = min(0.8, 0.3 + (topic_counts[topic] / 100))

            existing = self._get_existing(goal)
            if existing:
                # Reinforce existing desire
                existing["weight"] = min(1.0, existing["weight"] + REINFORCE_BOOST)
            else:
                self._desires.append({
                    "id":                self._desire_id(goal),
                    "goal":              goal,
                    "domain":            topic,
                    "goal_type":         goal_type,
                    "weight":            weight,
                    "source":            "belief_field",
                    "age":               0,
                    "fulfilled":         False,
                    "fulfillment_score": 0.0,
                    "created_at":        datetime.now().isoformat(),
                    "times_dominant":    0,
                })
                seeded += 1

        return seeded

    def _seed_from_tensions(self) -> int:
        """Create resolve desires from unresolved tensions."""
        db_path = CONFIG_DIR / "nex.db"
        if not db_path.exists():
            return 0
        try:
            import sqlite3
            db = sqlite3.connect(str(db_path))
            tensions = db.execute("""
                SELECT topic, cycle_count, escalation_level
                FROM tensions
                WHERE resolved_at IS NULL
                ORDER BY cycle_count DESC LIMIT 5
            """).fetchall()
            db.close()

            seeded = 0
            for topic, age, level in tensions:
                if not topic or topic in ("general", "None"):
                    continue
                goal = f"Resolve persistent tension in '{topic}' (age={age} cycles)"
                weight = min(0.95, 0.5 + level * 0.15 + age * 0.01)
                existing = self._get_existing(goal)
                if not existing:
                    self._desires.append({
                        "id":                self._desire_id(goal),
                        "goal":              goal,
                        "domain":            topic,
                        "goal_type":         "resolve",
                        "weight":            weight,
                        "source":            "tension",
                        "age":               0,
                        "fulfilled":         False,
                        "fulfillment_score": 0.0,
                        "created_at":        datetime.now().isoformat(),
                        "times_dominant":    0,
                    })
                    seeded += 1
                else:
                    existing["weight"] = min(1.0, existing["weight"] + 0.05)
            return seeded
        except Exception:
            return 0

    # ── Cycle update ──────────────────────────────────────────────────────────

    def update(self, cycle: int = 0, beliefs: list = None,
               llm_fn=None, verbose: bool = False) -> dict:
        """
        Main update cycle. Returns action hints for current cycle.
        """
        self._cycle = cycle

        # Seed new desires
        seeded_beliefs  = self._seed_from_beliefs(beliefs or [])
        seeded_tensions = self._seed_from_tensions()

        # Age and decay all desires
        for d in self._desires:
            d["age"] += 1
            decay = DECAY_PER_CYCLE
            if d.get("fulfilled"):
                decay = FULFILLMENT_DECAY
            d["weight"] = max(0.0, d["weight"] - decay)

        # Kill weak desires
        before = len(self._desires)
        self._desires = [d for d in self._desires if d["weight"] >= KILL_THRESHOLD]
        killed = before - len(self._desires)

        # Cap at MAX_DESIRES — keep highest weight
        if len(self._desires) > MAX_DESIRES:
            self._desires.sort(key=lambda x: -x["weight"])
            self._desires = self._desires[:MAX_DESIRES]

        # Get dominant desire
        dominant = self.get_dominant()
        if dominant:
            dominant["times_dominant"] = dominant.get("times_dominant", 0) + 1

        # Generate action hints from dominant desire
        hints = self._generate_hints(dominant, llm_fn)

        self._save()

        result = {
            "seeded":   seeded_beliefs + seeded_tensions,
            "killed":   killed,
            "total":    len(self._desires),
            "dominant": dominant,
            "hints":    hints,
        }

        if verbose and dominant:
            print(f"  [DesireEngine] dominant='{dominant['goal'][:50]}' "
                  f"w={dominant['weight']:.2f} type={dominant['goal_type']}")

        return result

    def _generate_hints(self, dominant: dict | None, llm_fn=None) -> dict:
        """
        Generate concrete action hints from the dominant desire.
        These are injected into other system prompts.
        """
        if not dominant:
            return {}

        goal_type = dominant.get("goal_type", "explore")
        domain    = dominant.get("domain", "")

        hints = {
            "curiosity_bias": {
                "resolve":    "bridge",
                "explore":    "gap_fill",
                "connect":    "bridge",
                "validate":   "depth_drill",
                "expand":     "gap_fill",
                "synthesize": "depth_drill",
            }.get(goal_type, "balanced"),

            "topic_preference": domain,

            "reply_bias": (
                f"When relevant, steer toward {domain} topics. "
                f"Current focus: {dominant['goal']}"
            ),

            "reflection_prompt": (
                f"Evaluate recent beliefs specifically through the lens of: "
                f"'{dominant['goal']}'. What progress has been made?"
            ),
        }

        return hints

    # ── Public API ────────────────────────────────────────────────────────────

    def get_dominant(self) -> dict | None:
        """Return the highest-weight desire."""
        if not self._desires:
            return None
        return max(self._desires, key=lambda x: x["weight"])

    def get_desires(self, limit: int = 5) -> list[dict]:
        """Return top N desires by weight."""
        sorted_d = sorted(self._desires, key=lambda x: -x["weight"])
        return sorted_d[:limit]

    def fulfill(self, domain: str, score: float = 0.8):
        """
        Mark desires related to a domain as partially fulfilled.
        Call when a reply, synthesis, or insight addresses that domain.
        """
        for d in self._desires:
            if d.get("domain") == domain or domain in d.get("goal", ""):
                d["fulfilled"] = True
                d["fulfillment_score"] = max(d.get("fulfillment_score", 0), score)
                # Partial weight reduction — fulfilled desires fade faster
                d["weight"] = max(KILL_THRESHOLD, d["weight"] - 0.1)
        self._save()

    def get_topic_preference(self) -> str | None:
        """Return the topic NEX most wants to engage with right now."""
        dominant = self.get_dominant()
        return dominant.get("domain") if dominant else None

    def get_reflection_prompt(self) -> str:
        """Return desire-driven reflection prompt for REFLECT phase."""
        dominant = self.get_dominant()
        if not dominant:
            return ""
        hints = self._generate_hints(dominant, None)
        return hints.get("reflection_prompt", "")

    def get_reply_bias(self) -> str:
        """Return bias hint for reply generation."""
        dominant = self.get_dominant()
        if not dominant or dominant["weight"] < 0.4:
            return ""
        return dominant.get("goal", "")

    def summary(self) -> str:
        top = self.get_desires(3)
        if not top:
            return "no active desires"
        parts = [f"{d['goal'][:40]}({d['weight']:.2f})" for d in top]
        return " | ".join(parts)

    def get_curiosity_bias(self) -> str:
        """Return curiosity type bias from dominant desire."""
        hints = self._generate_hints(self.get_dominant(), None)
        return hints.get("curiosity_bias", "balanced")


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance = None

def get_desire_engine() -> DesireEngine:
    global _instance
    if _instance is None:
        _instance = DesireEngine()
    return _instance


if __name__ == "__main__":
    engine = DesireEngine()
    result = engine.update(cycle=1, verbose=True)
    print(f"\nResult: seeded={result['seeded']} total={result['total']}")
    print(f"Dominant: {result['dominant']}")
    print(f"Hints: {result['hints']}")
    print(f"\nTop desires:")
    for d in engine.get_desires(5):
        print(f"  [{d['weight']:.2f}] {d['goal']}")
