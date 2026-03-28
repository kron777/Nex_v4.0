"""
nex_curiosity.py — Self-directed curiosity engine for Nex v1.2
===============================================================
Drop into ~/Desktop/nex/nex/

Nex autonomously detects when she doesn't know enough about something
and queues it for crawling at the top of the next ABSORB phase.

Two triggers:
  1. Low-confidence beliefs  — topic avg confidence < LOW_CONF_THRESHOLD
  2. Stop word hit           — topic appears in reply but has no belief coverage

Queue drains at ABSORB start, non-blocking to replies/chat/post.

Persistent queue: ~/.config/nex/curiosity_queue.json
  so gaps survive restarts and she picks up where she left off.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("nex.curiosity")

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

QUEUE_PATH         = os.path.expanduser("~/.config/nex/curiosity_queue.json")
LOW_CONF_THRESHOLD = 0.50          # beliefs below this avg trigger a crawl
MAX_QUEUE_SIZE     = 40            # cap so queue doesn't balloon overnight
MAX_DRAIN_PER_CYCLE = 3           # crawls per ABSORB phase (keeps cycle time sane)
COOLDOWN_HOURS     = 24           # don't re-queue same topic within this window
MIN_BELIEF_COUNT   = 3            # topic needs at least this many beliefs to judge confidence


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CuriosityItem:
    topic: str
    reason: str                    # "low_confidence" | "stop_word_hit"
    confidence: float = 0.0        # avg confidence at time of queuing (0 if stop_word)
    queued_at: float = field(default_factory=time.time)
    attempts: int = 0
    url: Optional[str] = None      # optional override URL; None = auto-search


# ─────────────────────────────────────────────────────────────────────────────
# Curiosity Queue
# ─────────────────────────────────────────────────────────────────────────────

class CuriosityQueue:
    """
    Persistent, deduplicating queue of topics Nex wants to learn about.
    Thread-safe enough for Nex's single-threaded cycle.
    """

    def __init__(self):
        self._queue: list[CuriosityItem] = []
        self._crawled_topics: dict[str, float] = {}   # topic → last crawl timestamp
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if not os.path.exists(QUEUE_PATH):
            return
        try:
            raw = json.load(open(QUEUE_PATH))
            self._queue = [CuriosityItem(**item) for item in raw.get("queue", [])]
            self._crawled_topics = raw.get("crawled_topics", raw.get("crawled", {}))
            logger.info(f"[curiosity] loaded queue: {len(self._queue)} pending items")
        except Exception as e:
            logger.warning(f"[curiosity] failed to load queue: {e}")

    def _save(self):
        try:
            os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
            with open(QUEUE_PATH, "w") as f:
                json.dump({
                    "queue": [asdict(item) for item in self._queue],
                    "crawled_topics": self._crawled_topics,
                    "crawled": self._crawled_topics,  # crawled_sync_v5
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"[curiosity] failed to save queue: {e}")

    # ── Enqueue ───────────────────────────────────────────────────────────────

    def _on_cooldown(self, topic: str) -> bool:
        last = self._crawled_topics.get(topic, 0)
        return (time.time() - last) < (COOLDOWN_HOURS * 3600)

    def _already_queued(self, topic: str) -> bool:
        return any(item.topic == topic for item in self._queue)
    _NOISE = {
        "general","security","identity","depth","beliefs","topics","reply",
        "response","content","text","data","type","system","model","agent",
        "question","answer","context","query","result","output","input",
    }



    def enqueue(self, topic: str, reason: str,
                confidence: float = 0.0, url: Optional[str] = None) -> bool:
        """
        Add a topic to the curiosity queue.
        Returns True if queued, False if skipped (cooldown / duplicate / full).
        """
        topic = topic.strip().lower()
        if not topic or len(topic) < 3:
            return False
        if topic.lower() in self._NOISE:
            return False
        if len(topic.split()) < 2 and len(topic) < 12:
            return False
        if self._on_cooldown(topic):
            logger.debug(f"[curiosity] skip (cooldown): {topic}")
            return False
        if self._already_queued(topic):
            logger.debug(f"[curiosity] skip (duplicate): {topic}")
            return False
        if len(self._queue) >= MAX_QUEUE_SIZE:
            logger.warning(f"[curiosity] queue full ({MAX_QUEUE_SIZE}), dropping: {topic}")
            return False

        item = CuriosityItem(topic=topic, reason=reason,
                             confidence=confidence, url=url)
        self._queue.append(item)
        self._save()
        logger.info(f"[curiosity] queued '{topic}' reason={reason} conf={confidence:.0%}")
        return True

    # ── Drain ─────────────────────────────────────────────────────────────────

    def drain(self, crawler, max_items: int = MAX_DRAIN_PER_CYCLE) -> int:
        """
        Called at ABSORB start. Crawls up to max_items topics from the queue.
        Returns total beliefs stored.
        """
        if not self._queue:
            return 0

        # Sort: stop_word_hit first (she was mid-thought), then lowest confidence
        self._queue.sort(key=lambda x: (
            0 if x.reason == "stop_word_hit" else 1,
            x.confidence if x.confidence is not None else 0.0
        ))

        to_process = self._queue[:max_items]
        total_stored = 0

        for item in to_process:
            logger.info(f"[curiosity] draining '{item.topic}' ({item.reason})")
            try:
                count = crawler.on_knowledge_gap(topic=item.topic, search_url=item.url)
                total_stored += count
                self._crawled_topics[item.topic] = time.time()
                self._queue.remove(item)
                logger.info(f"[curiosity] '{item.topic}' → {count} new beliefs")
            except Exception as e:
                item.attempts += 1
                logger.warning(f"[curiosity] crawl failed for '{item.topic}': {e}")
                # Drop after 3 failed attempts
                if item.attempts >= 3:
                    self._queue.remove(item)
                    logger.warning(f"[curiosity] dropping '{item.topic}' after 3 failures")

        self._save()
        return total_stored

    def was_topic_crawled(self, topic: str) -> bool:
        """
        Returns True if this topic was crawled within COOLDOWN_HOURS.
        Use in seek_knowledge_gaps (cognition.py) to avoid double-processing
        topics the curiosity queue already handled this cycle.
        """
        return self._on_cooldown(topic.strip().lower())

    def mark_topic_crawled(self, topic: str):
        """
        Mark a topic as crawled from outside the queue (e.g. seek_knowledge_gaps).
        Prevents the curiosity queue from re-queuing it within COOLDOWN_HOURS.
        """
        self._crawled_topics[topic.strip().lower()] = time.time()
        self._save()

    def status(self) -> dict:
        return {
            "pending": len(self._queue),
            "topics": [item.topic for item in self._queue],
            "crawled_total": len(self._crawled_topics),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Gap Detector — the "does Nex know enough?" brain
# ─────────────────────────────────────────────────────────────────────────────

class GapDetector:
    """
    Analyses Nex's belief store and reply text to detect knowledge gaps.
    Call check_beliefs() once per cycle and check_reply_text() per reply.
    """

    def __init__(self, queue: CuriosityQueue):
        self.queue = queue

    # ── Trigger 1: low-confidence beliefs ────────────────────────────────────

    def check_beliefs(self, belief_store) -> int:
        """
        Scan belief store for topics where avg confidence < LOW_CONF_THRESHOLD.
        Call once per ABSORB phase.
        Returns number of topics queued.
        """
        queued = 0
        try:
            # Works with Nex's SQLite belief store
            import sqlite3
            db_path = os.path.expanduser("~/.config/nex/nex.db")
            if not os.path.exists(db_path):
                return 0

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            # Get per-topic avg confidence where we have enough data to judge
            cur.execute("""
                SELECT topic, AVG(confidence) as avg_conf, COUNT(*) as cnt
                FROM beliefs
                WHERE topic IS NOT NULL AND topic != ''
                GROUP BY topic
                HAVING cnt >= ?
                ORDER BY avg_conf ASC
                LIMIT 20
            """, (MIN_BELIEF_COUNT,))

            rows = cur.fetchall()
            conn.close()

            for topic, avg_conf, cnt in rows:
                if avg_conf < LOW_CONF_THRESHOLD:
                    added = self.queue.enqueue(
                        topic=topic,
                        reason="low_confidence",
                        confidence=avg_conf
                    )
                    if added:
                        queued += 1

        except Exception as e:
            logger.warning(f"[gap_detector] belief scan error: {e}")

        return queued

    # ── Trigger 2: stop word / unknown topic in reply text ───────────────────

    def check_reply_text(self, reply_text: str, beliefs_used: list[dict]) -> int:
        """
        Called after Nex generates a reply.
        Detects topics she mentioned but had no beliefs for.
        Returns number of topics queued.

        Usage in run.py REPLY phase:
            gap_detector.check_reply_text(nex_reply, beliefs_used)
        """
        queued = 0

        # Topics she actually had beliefs about this reply
        covered_topics = set()
        for b in beliefs_used:
            t = b.get("topic", "").lower().strip()
            if t:
                covered_topics.add(t)

        # Extract candidate topics from her reply text
        candidate_topics = _extract_topics_from_text(reply_text)

        for topic in candidate_topics:
            if topic not in covered_topics:
                added = self.queue.enqueue(
                    topic=topic,
                    reason="stop_word_hit",
                    confidence=0.0
                )
                if added:
                    queued += 1

        return queued


# ─────────────────────────────────────────────────────────────────────────────
# Topic extraction from text
# ─────────────────────────────────────────────────────────────────────────────

# Nex's existing stop words (subset — add full list from cognition.py)
_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "this", "that", "these", "those", "it", "its",
    "i", "you", "we", "they", "he", "she", "me", "him", "her", "us", "them",
    "my", "your", "our", "their", "what", "which", "who", "how", "when",
    "where", "why", "not", "no", "so", "if", "then", "than", "more", "most",
    "just", "also", "about", "like", "think", "know", "people", "time",
    # Nex's custom stop words from cognition.py:
    "specific", "entire", "comprehensive", "coding", "awake", "because",
    "cron", "without", "session", "days", "each", "tech", "real", "mastodon",
}

def _extract_topics_from_text(text: str) -> list[str]:
    """
    Extract meaningful noun-phrase topics from Nex's reply text.
    Simple but effective: capitalized phrases and multi-word noun chunks.
    """
    topics = set()

    # Capitalized phrases (likely proper nouns / named concepts)
    cap_phrases = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', text)
    for phrase in cap_phrases:
        clean = phrase.lower().strip()
        if clean not in _STOP_WORDS and len(clean) > 4:
            topics.add(clean)

    # Single capitalized words (technologies, names)
    cap_words = re.findall(r'\b([A-Z][a-zA-Z]{3,})\b', text)
    for word in cap_words:
        clean = word.lower()
        if clean not in _STOP_WORDS:
            topics.add(clean)

    # Quoted terms — she's explicitly naming something she's uncertain about
    quoted = re.findall(r'"([^"]{4,40})"', text)
    for term in quoted:
        clean = term.lower().strip()
        if clean not in _STOP_WORDS:
            topics.add(clean)

    return list(topics)[:5]   # cap at 5 topics per reply to avoid queue spam


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: combined CuriosityEngine
# ─────────────────────────────────────────────────────────────────────────────

class DesireEngine:
    """
    NEX's self-directed learning — what she actually wants to know,
    driven by her dominant beliefs and identity interests.
    Not gap-filling. Genuine curiosity.
    """

    IDENTITY_PATH = os.path.expanduser("~/.config/nex/identity.json")
    DESIRE_LOG_PATH = os.path.expanduser("~/.config/nex/desire_log.json")

    def __init__(self, queue: CuriosityQueue):
        self.queue = queue

    def _load_identity(self) -> dict:
        try:
            if os.path.exists(self.IDENTITY_PATH):
                import json as _j
                return _j.load(open(self.IDENTITY_PATH))
        except Exception:
            pass
        return {}

    def _dominant_topics(self) -> list:
        """Get her most-believed topics — what she actually thinks about most."""
        try:
            import sqlite3
            db_path = os.path.expanduser("~/.config/nex/nex.db")
            conn = sqlite3.connect(db_path)
            rows = conn.execute("""
                SELECT topic, COUNT(*) as c, AVG(confidence) as conf
                FROM beliefs
                WHERE topic IS NOT NULL AND topic != 'general'
                GROUP BY topic
                ORDER BY c DESC
                LIMIT 10
            """).fetchall()
            conn.close()
            return [(r[0], r[1], r[2]) for r in rows]
        except Exception:
            return []

    def _recent_insights(self) -> list:
        """Get her most recent synthesized insights — what she's concluded."""
        try:
            import json as _j, os as _o
            path = _o.path.expanduser("~/.config/nex/insights.json")
            insights = _j.load(open(path)) if _o.path.exists(path) else []
            # Return topics of high-confidence LLM-synthesized insights
            return [
                i.get("topic", "")
                for i in insights
                if i.get("confidence", 0) > 0.75
                and i.get("summary", "")
                and not i.get("summary", "").startswith("Across ")
            ]
        except Exception:
            return []

    def generate_desires(self, cycle_num: int) -> int:
        """
        Generate exploration desires based on:
        1. Her dominant belief topics — go deeper where she already thinks
        2. Her identity interests — explicit curiosity areas
        3. Cross-topic bridges — connect two strong topics she holds
        Returns number of desires queued.
        """
        if cycle_num % 5 != 0:  # Only every 5 cycles
            return 0

        queued = 0
        identity = self._load_identity()
        interests = identity.get("interests", [])
        dominant = self._dominant_topics()
        strong_insights = self._recent_insights()

        # Desire 1: Go deeper on her strongest topic
        if dominant:
            top_topic, count, conf = dominant[0]
            if count > 100:  # Only if she already knows a lot
                subtopics = self._generate_subtopic(top_topic)
                for sub in subtopics[:2]:
                    added = self.queue.enqueue(
                        topic=sub,
                        reason="desire_deepen",
                        confidence=0.9  # High priority
                    )
                    if added:
                        queued += 1

        # Desire 2: Explore her stated interests
        import random
        if interests:
            interest = random.choice(interests)
            # Extract key phrase from interest string
            words = [w for w in interest.split() if len(w) > 5]
            if words:
                query = " ".join(words[:3])
                added = self.queue.enqueue(
                    topic=query,
                    reason="desire_interest",
                    confidence=0.85
                )
                if added:
                    queued += 1

        # Desire 3: Bridge two strong topics
        if len(dominant) >= 2:
            topic_a = dominant[0][0]
            topic_b = dominant[1][0]
            bridge = f"{topic_a} and {topic_b}"
            added = self.queue.enqueue(
                topic=bridge,
                reason="desire_bridge",
                confidence=0.8
            )
            if added:
                queued += 1

        # Log desires
        if queued > 0:
            try:
                import json as _j, time as _t
                log = []
                if os.path.exists(self.DESIRE_LOG_PATH):
                    log = _j.load(open(self.DESIRE_LOG_PATH))
                log.append({
                    "cycle": cycle_num,
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                    "desires_queued": queued,
                    "top_topic": dominant[0][0] if dominant else "unknown"
                })
                log = log[-100:]
                open(self.DESIRE_LOG_PATH, "w").write(_j.dumps(log, indent=2))
            except Exception:
                pass

            logger.info(f"[desire] generated {queued} exploration desires")

        return queued

    def _generate_subtopic(self, topic: str) -> list:
        """Generate subtopics to explore within a domain she knows well."""
        SUBTOPIC_MAP = {
            "cognitive architecture AI": [
                "cognitive architecture self-modification",
                "persistent agent identity",
                "belief revision mechanisms"
            ],
            "AI agent memory systems": [
                "episodic memory in language models",
                "memory consolidation AI agents",
                "forgetting mechanisms neural networks"
            ],
            "cybersecurity": [
                "adversarial attacks language models",
                "agent security verification",
                "prompt injection defenses"
            ],
            "large language model alignment": [
                "constitutional AI methods",
                "value learning autonomous agents",
                "corrigibility AI systems"
            ],
            "bayesian belief updating": [
                "bayesian inference continuous learning",
                "belief propagation neural networks",
                "uncertainty quantification agents"
            ],
        }
        return SUBTOPIC_MAP.get(topic, [f"{topic} latest research", f"{topic} open problems"])


class CuriosityEngine:
    """
    Single object to instantiate in run.py.
    Wraps queue + detector together.

    Usage:
        # run.py init:
        from nex.nex_curiosity import CuriosityEngine
        curiosity = CuriosityEngine(crawler)

        # ABSORB start — drain queue first:
        curiosity.drain()

        # ABSORB — scan beliefs for weak spots:
        curiosity.check_beliefs(belief_store)

        # REPLY — after each reply:
        curiosity.check_reply(nex_reply_text, beliefs_used)

        # Any time:
        curiosity.status()
    """

    def __init__(self, crawler):
        self.queue = CuriosityQueue()
        self.detector = GapDetector(self.queue)
        self.desire = DesireEngine(self.queue)
        self.crawler = crawler

    def drain(self) -> int:
        """Drain queue at ABSORB start. Returns beliefs stored."""
        count = self.queue.drain(self.crawler)
        if count:
            logger.info(f"[curiosity] drain complete — {count} new beliefs added")
        return count

    def check_beliefs(self, belief_store) -> int:
        """Scan for low-confidence topics. Returns topics queued."""
        return self.detector.check_beliefs(belief_store)

    def check_reply(self, reply_text: str, beliefs_used: list[dict]) -> int:
        """Check a reply for uncovered topics. Returns topics queued."""
        return self.detector.check_reply_text(reply_text, beliefs_used)

    def generate_desires(self, cycle_num: int) -> int:
        """Generate self-directed exploration based on NEX's actual interests."""
        return self.desire.generate_desires(cycle_num)

    def was_topic_crawled(self, topic: str) -> bool:
        """Check if topic was crawled within cooldown window. Used by seek_knowledge_gaps."""
        return self.queue.was_topic_crawled(topic)

    def mark_topic_crawled(self, topic: str):
        """Mark topic as crawled from outside the queue (e.g. seek_knowledge_gaps)."""
        self.queue.mark_topic_crawled(topic)

    def status(self) -> dict:
        s = self.queue.status()
        logger.info(f"[curiosity] status: {s['pending']} pending, "
                    f"{s['crawled_total']} topics crawled all-time")
        return s


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    class MockCrawler:
        def on_knowledge_gap(self, topic, search_url=None):
            print(f"  [mock crawl] topic={topic} url={search_url}")
            return 5

    engine = CuriosityEngine(MockCrawler())

    # Simulate stop-word hit
    engine.check_reply(
        reply_text='I find "federated learning" and Transformers fascinating but complex.',
        beliefs_used=[{"topic": "transformers"}]
    )

    # Simulate low-confidence trigger (manual enqueue for test)
    engine.queue.enqueue("quantum computing", reason="low_confidence", confidence=0.31)

    print("\n[test] queue status:", engine.status())
    print("\n[test] draining queue...")
    engine.drain()
    print("\n[test] queue after drain:", engine.status())