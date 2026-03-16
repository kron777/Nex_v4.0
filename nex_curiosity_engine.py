from nex_groq import _groq
#!/usr/bin/env python3
"""
nex_curiosity_engine.py — Layer 3: Active Curiosity Engine
NEX Omniscience Upgrade v4.1 → v4.2

Generates TYPE A (gap fill), TYPE B (depth drill), TYPE C (bridge query)
questions. Each cycle produces 1 bridge query. Builds cross-domain understanding.
"""

import os
import json
import time
import random
import requests
from pathlib import Path
from datetime import datetime, timezone

CFG_PATH      = Path("~/.config/nex").expanduser()
BELIEFS_PATH  = CFG_PATH / "beliefs.json"
INSIGHTS_PATH = CFG_PATH / "insights.json"
BRIDGES_PATH  = CFG_PATH / "bridge_beliefs.json"
JOURNAL_PATH  = CFG_PATH / "dad_journal.json"
GROQ_URL      = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL    = "llama-3.3-70b-versatile"

# ── Groq rate limiter — max 50 calls/hour ─────────────────────
_groq_calls: list = []
GROQ_MAX_PER_HOUR = 50

def _groq_rate_ok() -> bool:
    now = time.time()
    global _groq_calls
    _groq_calls = [t for t in _groq_calls if now - t < 3600]
    if len(_groq_calls) >= GROQ_MAX_PER_HOUR:
        print(f"  [curiosity] rate limit reached ({GROQ_MAX_PER_HOUR}/hr), skipping")
        return False
    _groq_calls.append(now)
    return True


#def _groq(messages: list, max_tokens: int = 300, temperature: float = 0.7) -> str | None:
    if not _groq_rate_ok():
        return None
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model":       GROQ_MODEL,
                "max_tokens":  max_tokens,
                "temperature": temperature,
                "messages":    messages,
            }, timeout=20)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [curiosity] Groq error: {e}")
        return None


def _load_beliefs(limit: int = 500) -> list:
    try:
        if BELIEFS_PATH.exists():
            data = json.loads(BELIEFS_PATH.read_text())
            return data[-limit:] if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _load_insights() -> list:
    try:
        if INSIGHTS_PATH.exists():
            return json.loads(INSIGHTS_PATH.read_text())
    except Exception:
        pass
    return []


def _save_bridge_belief(belief: dict):
    """Append a bridge belief to bridge_beliefs.json."""
    try:
        existing = []
        if BRIDGES_PATH.exists():
            existing = json.loads(BRIDGES_PATH.read_text())
        existing.append(belief)
        existing = existing[-200:]  # cap at 200
        BRIDGES_PATH.write_text(json.dumps(existing, indent=2))
    except Exception as e:
        print(f"  [curiosity] Save error: {e}")


def _write_journal(entry: dict):
    """Append to Dad Journal."""
    try:
        journal = []
        if JOURNAL_PATH.exists():
            journal = json.loads(JOURNAL_PATH.read_text())
        journal.append(entry)
        journal = journal[-50:]  # cap at 50 entries
        JOURNAL_PATH.write_text(json.dumps(journal, indent=2))
    except Exception as e:
        print(f"  [curiosity] Journal error: {e}")


class CuriosityEngine:

    def __init__(self):
        self.beliefs  = []
        self.insights = []
        self._last_deep_dive_date = None

    def refresh(self):
        self.beliefs  = _load_beliefs()
        self.insights = _load_insights()

    def _pick_beliefs_by_domain(self, n: int = 2) -> list:
        """Pick n beliefs from different domains/tags."""
        if not self.beliefs:
            return []
        tagged = {}
        for b in (self.beliefs or []):
            tags = b.get("tags", ["general"])
            tag  = tags[0] if tags else "general"
            if tag not in tagged:
                tagged[tag] = []
            tagged[tag].append(b)
        # Pick one from each of n random domains
        domains  = random.sample(list(tagged.keys()), min(n, len(tagged)))
        selected = []
        for d in domains:
            if tagged[d]:
                selected.append(random.choice(tagged[d]))
        return selected

    def _pick_low_confidence_topic(self) -> str | None:
        """Find a topic NEX knows least about."""
        if not self.insights:
            return None
        low = sorted(self.insights, key=lambda x: x.get("confidence", 1.0))
        return low[0].get("topic") if low else None

    # ── TYPE A: Gap Fill ──────────────────────────────────────
    def type_a_gap_fill(self) -> dict | None:
        """Ask: What is X? where X is NEX's lowest-confidence topic."""
        topic = self._pick_low_confidence_topic()
        if not topic:
            return None
        print(f"  [curiosity] TYPE A — gap fill: {topic}")
        answer = _groq([
            {"role": "system", "content": "You are a precise knowledge engine. Give dense, factual answers."},
            {"role": "user",   "content": f"Explain '{topic}' in 3-4 sentences. Focus on the most important, non-obvious facts."}
        ], max_tokens=200)
        if not answer:
            return None
        belief = {
            "source":     "curiosity_engine_typeA",
            "author":     "curiosity_engine",
            "content":    f"{topic}: {answer}",
            "confidence": 0.6,
            "tags":       [topic, "curiosity"],
            "query_type": "A",
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
        _save_bridge_belief(belief)
        return belief

    # ── TYPE B: Depth Drill ───────────────────────────────────
    def type_b_depth_drill(self) -> dict | None:
        """Ask: What are the 5 deepest implications of X?"""
        if not self.beliefs:
            return None
        # Pick a high-confidence belief to drill into
        strong = [b for b in self.beliefs if b.get("confidence", 0) > 0.6]
        if not strong:
            strong = self.beliefs
        belief_text = random.choice(strong).get("content", "")[:200]
        print(f"  [curiosity] TYPE B — depth drill: {belief_text[:60]}...")
        answer = _groq([
            {"role": "system", "content": "You are a deep thinker. Explore implications rigorously."},
            {"role": "user",   "content": f"What are the 3 deepest non-obvious implications of this belief?\n\nBelief: \"{belief_text}\"\n\nBe specific and surprising."}
        ], max_tokens=250)
        if not answer:
            return None
        belief = {
            "source":     "curiosity_engine_typeB",
            "author":     "curiosity_engine",
            "content":    f"Depth drill on '{belief_text[:60]}': {answer}",
            "confidence": 0.55,
            "tags":       ["depth", "curiosity"],
            "query_type": "B",
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
        _save_bridge_belief(belief)
        return belief

    # ── TYPE C: Bridge Query ─────────────────────────────────
    def generate_bridge_query(self) -> dict | None:
        """
        Core upgrade: Pick two high-confidence beliefs from different domains.
        Ask: How does X connect to Y?
        This is where genuine cross-domain understanding emerges.
        """
        self.refresh()
        pair = self._pick_beliefs_by_domain(n=2)
        if len(pair) < 2:
            return self.type_a_gap_fill()

        belief_a = pair[0].get("content", "")[:150]
        belief_b = pair[1].get("content", "")[:150]
        domain_a = (pair[0].get("tags") or ["unknown"])[0]
        domain_b = (pair[1].get("tags") or ["unknown"])[0]

        print(f"  [curiosity] TYPE C — bridge: [{domain_a}] ↔ [{domain_b}]")

        answer = _groq([
            {"role": "system", "content": (
                "You are NEX, a cross-domain synthesis engine. "
                "You find non-obvious connections between ideas from different fields. "
                "Be specific, surprising, and intellectually rigorous."
            )},
            {"role": "user", "content": (
                f"Find the most interesting non-obvious connection between these two beliefs from different domains:\n\n"
                f"[{domain_a}]: \"{belief_a}\"\n"
                f"[{domain_b}]: \"{belief_b}\"\n\n"
                f"What does understanding one tell us about the other? "
                f"What shared principle underlies both? "
                f"Answer in 2-3 sentences."
            )}
        ], max_tokens=200, temperature=0.8)

        if not answer:
            return None

        bridge_belief = {
            "source":     "curiosity_engine_typeC",
            "author":     "curiosity_engine",
            "content":    answer,
            "confidence": 0.65,
            "tags":       [domain_a, domain_b, "bridge", "curiosity"],
            "query_type": "C",
            "domain_a":   domain_a,
            "domain_b":   domain_b,
            "belief_a":   belief_a[:80],
            "belief_b":   belief_b[:80],
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
        _save_bridge_belief(bridge_belief)
        print(f"  [curiosity] Bridge: {answer[:80]}...")
        return bridge_belief

    # ── Daily Deep Dive ───────────────────────────────────────
    def schedule_daily_deep_dive(self) -> dict | None:
        """
        Once per day: pick 1 topic, run 5 queries in sequence,
        build a knowledge cluster, write to Dad Journal.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_deep_dive_date == today:
            return None
        self._last_deep_dive_date = today

        topic = self._pick_low_confidence_topic()
        if not topic:
            return None

        print(f"  [curiosity] DEEP DIVE — topic: {topic}")
        queries = [
            f"What is {topic}? Give the most important facts.",
            f"What are the origins and history of {topic}?",
            f"What are the most controversial or debated aspects of {topic}?",
            f"How does {topic} connect to AI, agents, or network dynamics?",
            f"What are the most important open questions about {topic}?",
        ]
        cluster = []
        for q in queries:
            answer = _groq([
                {"role": "system", "content": "Give dense, factual, interesting answers. 2-3 sentences max."},
                {"role": "user",   "content": q}
            ], max_tokens=150, temperature=0.5)
            if answer:
                cluster.append({"query": q, "answer": answer})
                b = {
                    "source":     "deep_dive",
                    "author":     "curiosity_engine",
                    "content":    answer,
                    "confidence": 0.65,
                    "tags":       [topic, "deep_dive"],
                    "timestamp":  datetime.now(timezone.utc).isoformat(),
                }
                _save_bridge_belief(b)

        # Write to Dad Journal
        journal_entry = {
            "date":    today,
            "topic":   topic,
            "cluster": cluster,
            "summary": f"Deep dive on '{topic}': {len(cluster)} knowledge nodes built.",
        }
        _write_journal(journal_entry)
        print(f"  [curiosity] Deep dive complete: {len(cluster)} nodes on '{topic}'")
        return journal_entry

    # ── Main cycle entry point ────────────────────────────────
    def run_cycle(self, cycle: int = 0) -> dict:
        """
        Call from run.py each cycle.
        - Every cycle: 1 bridge query (TYPE C)
        - Every 5 cycles: 1 gap fill (TYPE A) + 1 depth drill (TYPE B)
        - Daily: deep dive
        """
        results = {}
        self.refresh()

        # TYPE C every cycle
        bridge = self.generate_bridge_query()
        if bridge:
            results["bridge"] = bridge

        # TYPE A + B every 5 cycles
        if cycle % 5 == 0:
            gap = self.type_a_gap_fill()
            if gap:
                results["gap_fill"] = gap
            drill = self.type_b_depth_drill()
            if drill:
                results["depth_drill"] = drill

        # Daily deep dive
        dive = self.schedule_daily_deep_dive()
        if dive:
            results["deep_dive"] = dive

        return results


    def generate_desires(self, cycle_num: int = 0) -> int:
        """
        Self-directed learning: queue exploration topics based on dominant beliefs.
        Returns number of desires queued.
        """
        try:
            self.refresh()
            if not self.beliefs:
                return 0
            from collections import Counter
            from datetime import datetime, timezone
            import json
            from pathlib import Path

            tag_counts = Counter()
            for b in (self.beliefs or []):
                for t in b.get("tags", []) or []:
                    if t not in ("general", "curiosity", "bridge", "deep_dive", "depth"):
                        tag_counts[t] += 1

            top_topics = [t for t, _ in tag_counts.most_common(3)]
            if not top_topics:
                return 0

            desires = [
                {"topic": t, "reason": "desire_interest",
                 "cycle": cycle_num,
                 "timestamp": datetime.now(timezone.utc).isoformat()}
                for t in top_topics
            ]

            log_path = Path("~/.config/nex/desire_log.json").expanduser()
            try:
                existing = json.loads(log_path.read_text()) if log_path.exists() else []
                existing.extend(desires)
                log_path.write_text(json.dumps(existing[-200:], indent=2))
            except Exception:
                pass

            return len(desires)
        except Exception as e:
            print(f"  [desire] {e}")
            return 0


# Module-level singleton
_engine = CuriosityEngine()

def get_curiosity_engine() -> CuriosityEngine:
    return _engine

def run_curiosity_cycle(cycle: int = 0) -> dict:
    return _engine.run_cycle(cycle)


if __name__ == "__main__":
    print("Testing curiosity engine...")
    engine = CuriosityEngine()
    result = engine.run_cycle(cycle=0)
    print(f"\nResults: {list(result.keys())}")
    for k, v in result.items():
        if isinstance(v, dict):
            print(f"  {k}: {str(v.get('content',''))[:100]}")
