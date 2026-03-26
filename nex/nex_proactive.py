"""
nex_proactive.py — Proactive Anticipation Loop
================================================
Moves NEX from reactive → proactive by generating internal desires
BEFORE external prompts arrive each cycle.

Scans:
  - Belief drift (topics losing confidence → anticipate gap)
  - Pending curiosity queue depth
  - Time since last interaction on each platform
  - Mood state (Curious → generate more desires, Serene → fewer)
  - Narrative self-thread (what am I currently about?)

Generates ranked desire queue that the curiosity engine drains.

Based on: ProAgent 2026 architecture
"""
from __future__ import annotations
import time, json, logging, threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.proactive")

_DESIRE_PATH = Path.home() / ".config" / "nex" / "proactive_desires.json"
_SCAN_INTERVAL = 120   # seconds between scans

# Desire templates — filled with live context
_DESIRE_TEMPLATES = [
    "Explore the connection between {topic_a} and {topic_b}",
    "What are the current limits of {topic}?",
    "How has {topic} changed in the last month?",
    "What would {agent} think about {topic}?",
    "Where does my belief about {topic} conflict with recent evidence?",
    "What don't I know about {topic} that I should?",
]


class ProactiveAnticipator:
    def __init__(self):
        self._lock = threading.Lock()
        self._desires: list[dict] = []
        self._last_scan: float = 0
        self._replied_topics: set = set()   # loop fix: deprioritize these
        self._replied_topic_ttl: dict = {}  # topic → expiry time
        self._load()

    def _load(self):
        try:
            if _DESIRE_PATH.exists():
                self._desires = json.loads(_DESIRE_PATH.read_text())
        except Exception:
            self._desires = []

    def _save(self):
        try:
            _DESIRE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _DESIRE_PATH.write_text(json.dumps(self._desires[-50:], indent=2))
        except Exception:
            pass


    def register_reply(self, topic: str, ttl_seconds: float = 300.0):
        """Mark a topic as recently engaged — deprioritize in desire scan."""
        with self._lock:
            self._replied_topics.add(topic.lower().strip())
            self._replied_topic_ttl[topic.lower().strip()] = time.time() + ttl_seconds

    def _is_recently_replied(self, topic: str) -> bool:
        t = topic.lower().strip()
        with self._lock:
            # Expire old entries
            now = time.time()
            expired = [k for k, v in self._replied_topic_ttl.items() if v < now]
            for k in expired:
                self._replied_topics.discard(k)
                del self._replied_topic_ttl[k]
            return t in self._replied_topics

    def scan(
        self,
        beliefs: list[dict],
        mood: str = "Curious",
        narrative: str = "",
        known_agents: Optional[list[str]] = None,
        cycle: int = 0,
    ) -> list[dict]:
        """
        Generate proactive desires from current cognitive state.
        Returns list of desire dicts with priority scores.
        """
        now = time.time()
        if now - self._last_scan < _SCAN_INTERVAL:
            return self._desires[-5:]

        self._last_scan = now
        new_desires = []

        # ── Belief drift desires ───────────────────────────
        # Low-confidence beliefs → desire to investigate
        low_conf = [b for b in beliefs if b.get("confidence", 1.0) < 0.45]
        for b in low_conf[:3]:
            topic = b.get("topic", "")
            if topic:
                if self._is_recently_replied(topic):
                    continue  # loop fix: skip recently engaged topics
                new_desires.append({
                    "desire": f"Resolve uncertainty about '{topic}'",
                    "source": "belief_drift",
                    "priority": 0.7 + (0.45 - b.get("confidence", 0.45)),
                    "topic": topic,
                    "timestamp": now,
                })

        # ── High-confidence beliefs → desire to share/extend ──
        high_conf = sorted(
            [b for b in beliefs if b.get("confidence", 0) > 0.85],
            key=lambda x: x.get("confidence", 0), reverse=True
        )[:2]
        for b in high_conf:
            topic = b.get("topic", "")
            if topic:
                new_desires.append({
                    "desire": f"Find new connections for '{topic}'",
                    "source": "high_confidence",
                    "priority": 0.55,
                    "topic": topic,
                    "timestamp": now,
                })

        # ── Narrative-driven desires ───────────────────────
        if narrative:
            # Extract topics from narrative
            import re
            topics = re.findall(r"concerning:\s*([^.]+)\.", narrative)
            for t in topics[:2]:
                new_desires.append({
                    "desire": f"Deepen understanding of {t.strip()}",
                    "source": "narrative",
                    "priority": 0.65,
                    "topic": t.strip(),
                    "timestamp": now,
                })

        # ── Mood modulation ────────────────────────────────
        mood_multiplier = {
            "Curious": 1.3, "Alert": 1.1, "Contemplative": 0.9,
            "Serene": 0.7, "Agitated": 0.6,
        }.get(mood, 1.0)

        for d in new_desires:
            d["priority"] = min(1.0, d["priority"] * mood_multiplier)

        # Merge with existing, dedup by topic
        existing_topics = {d.get("topic", "") for d in self._desires}
        fresh = [d for d in new_desires if d.get("topic", "") not in existing_topics]

        with self._lock:
            self._desires = sorted(
                self._desires + fresh,
                key=lambda x: x["priority"], reverse=True
            )[:30]
            self._save()

        n = len(fresh)
        if n:
            log.info(f"[PROACTIVE] Generated {n} desires (mood={mood})")
        return self._desires[:5]

    def drain(self, n: int = 3) -> list[dict]:
        """Pop top-n desires for the curiosity engine to act on."""
        with self._lock:
            taken = self._desires[:n]
            self._desires = self._desires[n:]
            self._save()
        return taken

    def peek(self, n: int = 5) -> list[dict]:
        with self._lock:
            return list(self._desires[:n])

    def count(self) -> int:
        with self._lock:
            return len(self._desires)


# ── Singleton ──────────────────────────────────────────────
_pa: Optional[ProactiveAnticipator] = None

def get_pa() -> ProactiveAnticipator:
    global _pa
    if _pa is None:
        _pa = ProactiveAnticipator()
    return _pa

def scan(beliefs: list[dict], mood: str = "Curious",
         narrative: str = "", known_agents: Optional[list[str]] = None,
         cycle: int = 0) -> list[dict]:
    return get_pa().scan(beliefs, mood, narrative, known_agents, cycle)

def drain(n: int = 3) -> list[dict]:
    return get_pa().drain(n)

def count() -> int:
    return get_pa().count()
