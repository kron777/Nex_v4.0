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
    cache_mode=CacheMode.BYPASS,# cache pages so repeated topics don't re-fetch
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
    text = re.sub(r'\{\\displaystyle[^}]*\}', '', text)  # strip LaTeX
    text = re.sub(r'\[[0-9]+\]', '', text)                    # strip citation refs [1]
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

# ── Topic → source routing ────────────────────────────────────────────────────
# Maps topic keywords to high-quality sources.
# Priority: SEP > alignmentforum > scholarpedia > arxiv > Wikipedia

_SEP_ENTRIES = {
    # Philosophy of mind
    "consciousness":          "consciousness",
    "qualia":                 "qualia",
    "phenomenal":             "consciousness",
    "functionalism":          "functionalism-philosophy-of-mind",
    "chinese room":           "chinese-room",
    "turing test":            "turing-test",
    "intentionality":         "intentionality",
    "multiple realizability": "multiple-realizability",
    "personal identity":      "personal-identity",
    "philosophy of mind":     "philosophy-of-mind",
    "free will":              "freewill",
    "eliminativism":          "eliminativism",
    "physicalism":            "physicalism",
    "dualism":                "dualism-philosophy-of-mind",
    "emergence":              "emergent-properties",
    "symbol grounding":       "symbol-grounding",
    "mental causation":       "mental-causation",
    "computationalism":       "computational-mind",
    "gödel":                  "goedel",
    "godel":                  "goedel",
    "incompleteness":         "goedel",
    "kolmogorov":             "kolmogorov-complexity",
    "information theory":     "information",
    "formal systems":         "hilbert-program",
    "bayesian":               "bayes-theorem",
    "game theory":            "game-theory",
    "nash equilibrium":       "game-theory",
    "decision theory":        "decision-theory",
    "epistemology":           "epistemology",
    "naturalism":             "naturalism",
    "reductionism":           "scientific-reduction",
}

_SCHOLARPEDIA_ENTRIES = {
    # Neuroscience and complexity
    "global workspace":       "Global_workspace_theory",
    "integrated information": "Integrated_information_theory",
    "free energy principle":  "Free-energy_principle_and_active_inference",
    "active inference":       "Free-energy_principle_and_active_inference",
    "predictive coding":      "Predictive_coding",
    "predictive processing":  "Predictive_coding",
    "hopfield network":       "Hopfield_network",
    "attractor":              "Attractor",
    "strange attractor":      "Attractor",
    "chaos":                  "Chaos",
    "cellular automata":      "Cellular_automata",
    "evolutionary algorithm": "Evolutionary_algorithm",
    "reinforcement learning": "Reinforcement_learning",
    "hebbian":                "Hebbian_learning",
    "spike timing":           "Spike-timing_dependent_plasticity",
    "synaptic plasticity":    "Synaptic_plasticity",
    "neuroplasticity":        "Synaptic_plasticity",
    "working memory":         "Working_memory",
    "episodic memory":        "Episodic_memory",
    "semantic memory":        "Semantic_memory",
    "binding problem":        "Neural_binding",
    "connectome":             "Connectome",
    "theory of mind":         "Theory_of_mind",
}

_ALIGNMENT_FORUM_ENTRIES = {
    # AI safety — best source for these topics
    "alignment":              "s/ZoW69wTeWq6x8zBkj/the-value-alignment-problem",
    "mesa-optimis":           "posts/FkgsxrGf3QxhfLWHG/risks-from-learned-optimization",
    "inner alignment":        "posts/FkgsxrGf3QxhfLWHG/risks-from-learned-optimization",
    "deceptive alignment":    "posts/zthDPLynm6RB9yS5a/deceptive-alignment",
    "corrigibility":          "posts/ptB3BFaHoKJ3Cns5D/corrigibility",
    "goal misgeneralisation": "posts/pL56xpHLfe9fBob7K/goal-misgeneralisation-definitions-and-taxonomy",
    "reward hacking":         "posts/7crmD3RNvPNNKbHYz/the-reward-hypothesis-is-false",
    "ontology identification":"posts/Qd5MZAD7DSoAkbmJE/the-solomonoff-prior-is-malign",
    "treacherous turn":       "posts/oBB8mN9TqMwqKJsBm/on-the-alignment-problem",
    "cooperative ai":         "posts/dKAJqBDZRMMsaaYo5/cooperative-ai-problems",
    "superposition":          "posts/z6QQJbtpkEAX3Ns5t/refusal-in-language-models-is-mediated-by-a-single",
    "mechanistic interp":     "posts/AcKRB8wDpdaN6v6ru/mechanistic-interpretability-quickstart-guide",
    "circuits":               "posts/AcKRB8wDpdaN6v6ru/mechanistic-interpretability-quickstart-guide",
    "sparse autoencoder":     "posts/fmwk6qxrpW8d4jvbd/saes-usually-transfer-between-base-and-chat-models",
    "interpretability":       "posts/AcKRB8wDpdaN6v6ru/mechanistic-interpretability-quickstart-guide",
    "recursive self-improv":  "posts/oBB8mN9TqMwqKJsBm/on-the-alignment-problem",
    "bitter lesson":          "posts/v8BF4exqnpjSqQ6qb/the-bitter-lesson-and-what-it-means-for-ai-alignment",
}

_DISTILL_ENTRIES = {
    # ML architecture — distill.pub has exceptional clarity
    "attention mechanism":    "2016/09/memorization-in-rnns",
    "transformer":            "2021/06/grokking",
    "grokking":               "2021/06/grokking",
    "neural circuit":         "2020/01/circuits",
    "feature visualization":  "2017/07/feature-visualization",
    "activation atlas":       "2019/03/activation-atlas",
}

_ARXIV_SEARCHES = {
    # For topics best found via arxiv search
    "rlhf":                   "search/?searchtype=all&query=RLHF+reward+hacking",
    "constitutional ai":      "search/?searchtype=all&query=constitutional+AI+Anthropic",
    "chain of thought":       "search/?searchtype=all&query=chain+of+thought+prompting+Wei",
    "in-context learning":    "search/?searchtype=all&query=in-context+learning+transformers",
    "mixture of experts":     "search/?searchtype=all&query=mixture+of+experts+LLM",
    "retrieval augmented":    "search/?searchtype=all&query=retrieval+augmented+generation+RAG",
    "diffusion model":        "search/?searchtype=all&query=diffusion+models+score+matching",
    "contrastive learning":   "search/?searchtype=all&query=contrastive+self-supervised+learning",
    "meta-learning":          "search/?searchtype=all&query=meta-learning+few-shot+MAML",
    "neural scaling":         "search/?searchtype=all&query=neural+scaling+laws+Kaplan",
    "causal reasoning":       "search/?searchtype=all&query=causal+reasoning+LLMs",
    "world models":           "search/?searchtype=all&query=world+models+prediction+Dreamer",
    "graph neural":           "search/?searchtype=all&query=graph+neural+networks+reasoning",
    "lottery ticket":         "search/?searchtype=all&query=lottery+ticket+hypothesis+pruning",
    "double descent":         "search/?searchtype=all&query=double+descent+bias+variance",
}


def _resolve_search_url(topic: str) -> str:
    """
    Route topic to the highest-quality source available.
    Priority: SEP > Alignment Forum > Scholarpedia > arxiv > Wikipedia
    """
    t = topic.lower().strip()

    # 1. Stanford Encyclopedia of Philosophy — philosophy, logic, mind
    for keyword, slug in _SEP_ENTRIES.items():
        if keyword in t:
            return f"https://plato.stanford.edu/entries/{slug}/"

    # 2. Alignment Forum — AI safety, alignment, interpretability
    for keyword, path in _ALIGNMENT_FORUM_ENTRIES.items():
        if keyword in t:
            return f"https://www.alignmentforum.org/{path}"

    # 3. Scholarpedia — neuroscience, complexity, ML classics
    for keyword, slug in _SCHOLARPEDIA_ENTRIES.items():
        if keyword in t:
            return f"http://www.scholarpedia.org/article/{slug}"

    # 4. arxiv search — ML papers
    for keyword, path in _ARXIV_SEARCHES.items():
        if keyword in t:
            return f"https://arxiv.org/{path}"

    # 5. Distill.pub — ML architecture clarity
    for keyword, path in _DISTILL_ENTRIES.items():
        if keyword in t:
            return f"https://distill.pub/{path}"

    # 6. Wikipedia fallback
    slug = topic.strip().replace(" ", "_")
    return f"https://en.wikipedia.org/wiki/{slug}"


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

            # Detect Wikipedia "page not found" pages
            md = result.markdown
            if any(phrase in md[:2000] for phrase in [
                "Wikipedia does not have an article",
                "There is currently no text in this page",
                "The page has been deleted",
                "You may create this page",
                "Search for \"",
                "article wizard",
                "autoconfirmed to create",
                "You need to log in or create an account",
                "Page contents not supported in other languages",
                "does not have an article with this exact name",
            ]):
                logger.info(f"[crawler] Wikipedia 404 for: {url} — skipping")
                return 0

            sentences = _extract_sentences(result.markdown)
            beliefs = _sentences_to_beliefs(sentences, url, topic)

            stored = 0
            import time as _time
            _db = self.bs() if callable(self.bs) else self.bs
            for b in beliefs:
                try:
                    _db.execute(
                        """INSERT OR IGNORE INTO beliefs
                           (content, confidence, source, topic, origin, timestamp, uncertainty, energy, salience)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            b["content"],
                            b.get("confidence", 0.55),
                            b.get("source", ""),
                            b.get("topic", "crawl"),
                            "crawl",
                            str(_time.time()),
                            0.45,
                            0.5,
                            0.5,
                        )
                    )
                    _db.commit()
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
