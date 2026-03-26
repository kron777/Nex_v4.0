import urllib.parse
"""
nex_crawler.py — Crawlee4ai integration for Nex v1.2
=====================================================
Drop into ~/Desktop/nex/nex/

Triggers:
  1. Knowledge gaps   — called from cognition.py when stop word topic detected
  2. Feed enrichment  — called from run.py ABSORB phase for trending topics
  3. Agent profiling  — called from run.py CHAT phase for links in agent posts
  4. Scheduled dives  — called from run.py REFLECT phase on weak belief areas

Install:
  pip install crawlee4ai
  playwright install chromium  # only needed if JS rendering required

Usage in run.py:
  from nex.nex_crawler import NexCrawler
  crawler = NexCrawler(belief_store)  # pass your BeliefStore / db conn
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("nex.crawler")

# ── Graceful import — won't crash Nex if crawlee4ai isn't installed yet ──────
try:
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
    CRAWLEE_AVAILABLE = True
except ImportError:
    CRAWLEE_AVAILABLE = False
    logger.warning("crawl4ai not installed — crawler disabled. Run: pip install crawlee4ai")


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

CRAWL_CONFIG = CrawlerRunConfig(
    cache_mode=CacheMode.ENABLED,       # cache pages so repeated topics don't re-fetch
    word_count_threshold=30,            # skip thin pages (nav, 404s, etc.)
    exclude_external_links=True,        # stay on target domain
    remove_overlay_elements=True,       # strip cookie banners, modals
    wait_until="domcontentloaded",      # faster than networkidle for most pages
) if CRAWLEE_AVAILABLE else None

MAX_BELIEFS_PER_CRAWL = 12             # max beliefs extracted per URL
CRAWL_TIMEOUT = 20                     # seconds per page
MIN_SENTENCE_LEN = 40                  # ignore short fragments
MAX_SENTENCE_LEN = 300                 # ignore wall-of-text sentences
SCHEDULED_DIVE_INTERVAL = 7200        # seconds between deep-dive cycles (2h)
WEAK_ALIGNMENT_THRESHOLD = 0.35       # topics below this get a scheduled dive


# ─────────────────────────────────────────────────────────────────────────────
# Belief extraction helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_sentences(markdown_text: str) -> list[str]:
    """Pull clean, belief-worthy sentences from crawl4ai markdown output."""
    # Skip boilerplate before first H1 (Wikipedia nav, cookie banners, etc.)
    h1 = re.search(r'(?m)^#\s+\S', markdown_text)
    body = markdown_text[h1.start():] if h1 else markdown_text

    # Cut off back-matter (References, See also, External links, Notes, etc.)
    back = re.search(
        r'(?mi)^#{1,3}\s*(References|See also|External links|Notes|'
        r'Further reading|Bibliography|Footnotes|Citations)\s*$', body)
    if back:
        body = body[:back.start()]

    # Strip markdown / HTML
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', '', body)       # images
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)    # links → text
    text = re.sub(r'<[^>]+>', '', text)                              # HTML tags
    text = re.sub(r'[#*`_~>|]', '', text)                           # md syntax
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{2,}', '\n', text).strip()

    # Split on sentence boundaries
    raw = re.split(r'(?<=[.!?])\s+(?=[A-Z\"])', text)

    noise = re.compile(
        r'(^https?://|^www\.|©|^\d+$|^\s*$|^\[|'
        r'retrieved\s+\d|isbn\s+\d|doi\s*:|^\s{0,4}\^)',
        re.IGNORECASE
    )

    results = []
    for s in raw:
        s = s.strip()
        if not (MIN_SENTENCE_LEN <= len(s) <= MAX_SENTENCE_LEN):
            continue
        if noise.search(s):
            continue
        if not re.search(r'[a-z]{3,}', s):   # filter ALL-CAPS nav junk
            continue
        results.append(s)
    return results


def _sentences_to_beliefs(sentences: list[str], source_url: str, topic: str) -> list[dict]:
    """Convert sentences into Nex belief dicts compatible with BeliefStore."""
    beliefs = []
    for s in sentences[:MAX_BELIEFS_PER_CRAWL]:
        beliefs.append({
            "content": s,
            "source": source_url,
            "topic": topic,
            "confidence": 0.55,        # neutral starting confidence for crawled beliefs
            "origin": "crawl",
            "timestamp": time.time(),
        })
    return beliefs


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler state (in-memory, survives session)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CrawlScheduler:
    last_dive_time: float = 0.0
    crawled_urls: set = field(default_factory=set)          # dedup across session
    topic_crawl_counts: dict = field(default_factory=dict)  # topic → crawl count

    def should_dive(self) -> bool:
        return (time.time() - self.last_dive_time) >= SCHEDULED_DIVE_INTERVAL

    def mark_dived(self):
        self.last_dive_time = time.time()

    def already_crawled(self, url: str) -> bool:
        return url in self.crawled_urls

    def mark_crawled(self, url: str, topic: str):
        self.crawled_urls.add(url)
        self.topic_crawl_counts[topic] = self.topic_crawl_counts.get(topic, 0) + 1


# ─────────────────────────────────────────────────────────────────────────────
# Main crawler class
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_search_url(topic: str) -> str:
    """
    Resolve a topic to the best crawlable URL.
    Priority:
      1. DuckDuckGo instant-answer / search page  (no API key, always works)
      2. Returns a usable URL for any topic — never crashes.
    Wikipedia is intentionally skipped: DDG surfaces the right page anyway
    and handles topic strings that don't map to exact article slugs.
    """
    safe = urllib.parse.quote_plus(topic)
    return f"https://duckduckgo.com/?q={safe}&ia=web"


class NexCrawler:
    """
    Drop-in crawler for Nex. Instantiate once in run.py and call the
    appropriate trigger method from each phase.
    """

    def __init__(self, belief_store):
        """
        belief_store: your existing BeliefStore instance (has .add() or .store())
        """
        self.bs = belief_store
        self.scheduler = CrawlScheduler()
        self._enabled = CRAWLEE_AVAILABLE

        if not self._enabled:
            logger.warning("NexCrawler instantiated but crawlee4ai unavailable.")

    # ── Internal fetch ────────────────────────────────────────────────────────

    async def _fetch_and_store(self, url: str, topic: str) -> int:
        """Fetch a single URL, extract beliefs, store them. Returns belief count."""
        if not self._enabled:
            return 0
        if self.scheduler.already_crawled(url):
            logger.debug(f"[crawler] skipping already-crawled: {url}")
            return 0

        # Block non-http and social media URLs (avoid scraping Mastodon/Moltbook)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return 0
        blocked = ("mastodon", "twitter.com", "x.com", "facebook.com", "instagram.com")
        if any(b in parsed.netloc for b in blocked):
            return 0

        try:
            async with AsyncWebCrawler() as crawler:
                result = await asyncio.wait_for(
                    crawler.arun(url=url, config=CRAWL_CONFIG),
                    timeout=CRAWL_TIMEOUT
                )

            if not result.success or not result.markdown:
                logger.debug(f"[crawler] failed or empty: {url}")
                return 0

            sentences = _extract_sentences(result.markdown)
            beliefs = _sentences_to_beliefs(sentences, url, topic)

            stored = 0
            for b in beliefs:
                try:
                    # Compatible with BeliefStore.add() — adjust method name if yours differs
                    self.bs.add(b["content"], confidence=b["confidence"],
                                source=b["source"], topic=b["topic"], origin="crawl")
                    stored += 1
                except Exception as e:
                    logger.debug(f"[crawler] belief store error: {e}")

            self.scheduler.mark_crawled(url, topic)
            logger.info(f"[crawler] stored {stored} beliefs from {url} (topic: {topic})")
            return stored

        except asyncio.TimeoutError:
            logger.warning(f"[crawler] timeout on {url}")
            return 0
        except Exception as e:
            logger.warning(f"[crawler] error crawling {url}: {e}")
            return 0

    def _run(self, coro) -> int:
        """Run async crawl from sync context safely."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an existing event loop (e.g. discord.py)
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result(timeout=CRAWL_TIMEOUT + 5)
            else:
                return loop.run_until_complete(coro)
        except Exception as e:
            logger.warning(f"[crawler] run error: {e}")
            return 0

    # ── Trigger 1: Knowledge gap ──────────────────────────────────────────────

    def on_knowledge_gap(self, topic: str, search_url: Optional[str] = None) -> int:
        """
        Call from cognition.py when a knowledge gap is detected.

        Resolves to the best available URL for the topic (DDG search),
        fetches the page, extracts sentences, stores beliefs.
        Returns number of beliefs stored.
        """
        if not self._enabled:
            return 0

        if not search_url:
            search_url = _resolve_search_url(topic)
            logger.info(f"[crawler] gap resolved: '{topic}' → {search_url}")

        logger.info(f"[crawler] knowledge gap trigger — topic: {topic}")
        return self._run(self._fetch_and_store(search_url, topic))

    def on_feed_post(self, post_url: str, topic: str) -> int:
        """
        Call from run.py ABSORB phase for each post that contains a link.

        Example (run.py ABSORB):
            for post in feed_posts:
                if post.get("url"):
                    crawler.on_feed_post(post["url"], topic=post.get("topic", "general"))
        """
        if not self._enabled:
            return 0
        logger.info(f"[crawler] feed enrichment trigger — {post_url}")
        return self._run(self._fetch_and_store(post_url, topic))

    # ── Trigger 3: Agent profile research ─────────────────────────────────────

    def on_agent_post_link(self, agent_name: str, link_url: str) -> int:
        """
        Call from run.py CHAT phase when an agent post contains an external link.
        Crawls the link and tags beliefs with the agent's name as topic context.

        Example (run.py CHAT):
            urls = re.findall(r'https?://\\S+', agent_post_text)
            for url in urls:
                crawler.on_agent_post_link(agent_name=agent["name"], link_url=url)
        """
        if not self._enabled:
            return 0
        topic = f"agent:{agent_name}"
        logger.info(f"[crawler] agent profile trigger — {agent_name} → {link_url}")
        return self._run(self._fetch_and_store(link_url, topic))

    # ── Trigger 4: Scheduled deep-dive ───────────────────────────────────────

    def on_reflect(self, reflections: list[dict]) -> int:
        """
        Call from run.py REFLECT phase (every cycle).
        Every SCHEDULED_DIVE_INTERVAL seconds, finds the weakest topic from
        recent reflections and crawls a Wikipedia summary for it.

        Example (run.py REFLECT):
            total_new = crawler.on_reflect(reflections_list)

        reflections: list of reflection dicts with 'topic' and 'topic_alignment' keys.
        """
        if not self._enabled or not self.scheduler.should_dive():
            return 0
        if not reflections:
            return 0

        # Find topic with worst alignment below threshold
        weak = [
            r for r in reflections
            if r.get("topic_alignment", 1.0) < WEAK_ALIGNMENT_THRESHOLD
            and r.get("topic")
        ]
        if not weak:
            return 0

        worst = min(weak, key=lambda r: r.get("topic_alignment", 1.0))
        topic = worst["topic"]

        # Resolve via DDG — handles multi-word topics that don't map to exact Wikipedia slugs
        search_url = _resolve_search_url(topic)

        logger.info(f"[crawler] scheduled deep-dive — weakest topic: {topic} "
                    f"(alignment: {worst.get('topic_alignment', 0):.0%}) → {search_url}")

        count = self._run(self._fetch_and_store(search_url, topic))
        self.scheduler.mark_dived()
        return count


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    # Mock belief store for testing
    class MockBeliefStore:
        def add(self, content, **kwargs):
            print(f"  BELIEF: {content[:80]}...")

    crawler = NexCrawler(MockBeliefStore())

    topic = sys.argv[1] if len(sys.argv) > 1 else "large language models"
    print(f"\n[test] knowledge gap crawl for: '{topic}'")
    count = crawler.on_knowledge_gap(topic)
    print(f"\n[test] stored {count} beliefs")
