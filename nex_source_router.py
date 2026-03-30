"""
nex_source_router.py — Maximum Belief Extraction Engine
Tiered source collection: RSS → HN → Reddit → Wikipedia → YouTube → Arxiv → crawl4ai
All sources feed into the distiller. Runs 24/7.
DB: nex.db | table: beliefs | cols: id, content, topic, confidence, source
"""


# ── Log throttle (prevents [Distiller] Llama error flood) ──
# Duplicate throttle removed — using _llama_warn() below (60s gate)
# ────────────────────────────────────────────────────────────

import time
import logging
import sqlite3
import json
import re
import threading
import os
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import quote, urlencode

# ── Llama warning throttle (prevents log flood when llama-server is down) ──
import time as _sr_time_throttle
_sr_llama_warn_last = 0.0
_SR_LLAMA_WARN_GAP  = 60.0  # one warning per minute max

def _llama_warn(logger_or_name, msg='Distiller: llama-server unavailable'):
    global _sr_llama_warn_last
    _now = _sr_time_throttle.time()
    if _now - _sr_llama_warn_last >= _SR_LLAMA_WARN_GAP:
        _sr_llama_warn_last = _now
        import logging as _lg
        _lg.getLogger('nex.source_router').warning(msg)
# ─────────────────────────────────────────────────────────────────────────

# ── NEX v4 groq shim ─────────────────────────────────────────
try:
    from nex.nex_groq_shim import _groq, _call_groq, call_groq
except ImportError:
    try:
        from nex_groq_shim import _groq, _call_groq, call_groq
    except ImportError:
        pass
# ─────────────────────────────────────────────────────────────

log = logging.getLogger("nex.source_router")

DB_PATH = os.path.join(os.path.dirname(__file__), "nex.db")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama3:latest"  # using local ollama

# ─────────────────────────────────────────────
# RSS FEEDS — fires every 15 min
# ─────────────────────────────────────────────

RSS_FEEDS = [
    # News
    ("world",        "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("technology",   "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("science",      "https://www.newscientist.com/feed/home/"),
    ("science",      "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml"),
    ("philosophy",   "https://aeon.co/feed.rss"),
    ("psychology",   "https://www.psychologytoday.com/intl/node/feed/"),
    ("ai",           "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("ai",           "https://www.technologyreview.com/feed/"),
    # Reddit RSS (no auth needed)
    ("philosophy",   "https://www.reddit.com/r/philosophy/top/.rss?t=day"),
    ("consciousness","https://www.reddit.com/r/consciousness/top/.rss?t=day"),
    ("ai",           "https://www.reddit.com/r/MachineLearning/top/.rss?t=day"),
    ("psychology",   "https://www.reddit.com/r/psychology/top/.rss?t=day"),
    ("science",      "https://www.reddit.com/r/science/top/.rss?t=day"),
    ("society",      "https://www.reddit.com/r/sociology/top/.rss?t=day"),
    ("art",          "https://www.reddit.com/r/art/top/.rss?t=day"),
    ("music",        "https://www.reddit.com/r/Music/top/.rss?t=day"),
    ("history",      "https://www.reddit.com/r/history/top/.rss?t=day"),
    ("nature",       "https://www.reddit.com/r/nature/top/.rss?t=day"),
    # Hacker News
    ("technology",   "https://news.ycombinator.com/rss"),
    # Academic / long-form
    ("philosophy",   "https://philosophynow.org/rss"),
    ("culture",      "https://www.theguardian.com/culture/rss"),
    ("society",      "https://www.theguardian.com/society/rss"),
]

def _fetch_url(url, timeout=10):
    try:
        req = Request(url, headers={"User-Agent": "NEX-Belief-Engine/1.0"})
        with urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        log.debug(f"fetch failed {url}: {e}")
        return None

def parse_rss(xml_text):
    """Extract titles + descriptions from RSS without feedparser dependency."""
    items = []
    entries = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)
    if not entries:
        entries = re.findall(r"<entry>(.*?)</entry>", xml_text, re.DOTALL)
    for entry in entries[:8]:
        title = re.search(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", entry, re.DOTALL)
        desc  = re.search(r"<description[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", entry, re.DOTALL)
        summary = re.search(r"<summary[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</summary>", entry, re.DOTALL)
        t = title.group(1).strip() if title else ""
        d = (desc or summary)
        d = d.group(1).strip() if d else ""
        d = re.sub(r"<[^>]+>", " ", d).strip()
        if t:
            items.append(f"{t}. {d[:300]}" if d else t)
    return items

def collect_rss():
    """Collect from all RSS feeds. Returns list of (topic, text) tuples."""
    results = []
    for topic, url in RSS_FEEDS:
        xml = _fetch_url(url)
        if not xml:
            continue
        items = parse_rss(xml)
        if items:
            combined = " | ".join(items)
            results.append((topic, combined, url))
            log.info(f"  [RSS] {topic} — {len(items)} items from {url.split('/')[2]}")
    return results

# ─────────────────────────────────────────────
# HACKER NEWS API — top + best stories
# ─────────────────────────────────────────────

def collect_hn(n=30):
    """Pull top HN stories — pure JSON API, no auth."""
    results = []
    try:
        ids_raw = _fetch_url("https://hacker-news.firebaseio.com/v0/topstories.json")
        if not ids_raw:
            return results
        ids = json.loads(ids_raw)[:n]
        texts = []
        for sid in ids:
            item_raw = _fetch_url(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            if not item_raw:
                continue
            item = json.loads(item_raw)
            title = item.get("title", "")
            text  = item.get("text", "")
            url   = item.get("url", "")
            if title:
                texts.append(f"{title}. {re.sub('<[^>]+>', '', text)[:200]}" if text else title)
        if texts:
            results.append(("technology", " | ".join(texts[:20]), "hacker-news.firebaseio.com"))
            log.info(f"  [HN] {len(texts)} stories collected")
    except Exception as e:
        log.warning(f"  [HN] error: {e}")
    return results

# ─────────────────────────────────────────────
# REDDIT JSON API — no auth, multiple subs
# ─────────────────────────────────────────────

REDDIT_SUBS = [
    ("philosophy",    "philosophy"),
    ("consciousness", "consciousness"),
    ("ai",            "MachineLearning"),
    ("ai",            "artificial"),
    ("psychology",    "psychology"),
    ("science",       "science"),
    ("society",       "sociology"),
    ("ethics",        "ethics"),
    ("art",           "art"),
    ("music",         "WeAreTheMusicMakers"),
    ("history",       "history"),
    ("nature",        "EarthPorn"),
    ("language",      "linguistics"),
    ("culture",       "truereddit"),
    ("future",        "Futurology"),
]

def collect_reddit(limit=15):
    """Pull Reddit top posts via JSON API — no auth needed."""
    results = []
    for topic, sub in REDDIT_SUBS:
        url = f"https://www.reddit.com/r/{sub}/top.json?t=day&limit={limit}"
        raw = _fetch_url(url)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            posts = data.get("data", {}).get("children", [])
            texts = []
            for p in posts:
                pd = p.get("data", {})
                title    = pd.get("title", "")
                selftext = pd.get("selftext", "")[:300]
                if title:
                    texts.append(f"{title}. {selftext}" if selftext else title)
            if texts:
                results.append((topic, " | ".join(texts[:12]), f"reddit.com/r/{sub}"))
                log.info(f"  [Reddit] r/{sub} — {len(texts)} posts")
        except Exception as e:
            log.debug(f"  [Reddit] r/{sub} parse error: {e}")
    return results

# ─────────────────────────────────────────────
# WIKIPEDIA API — gap-targeted surgical lookup
# ─────────────────────────────────────────────

def collect_wikipedia(topics):
    """Pull Wikipedia summaries for specific gap topics."""
    results = []
    for topic in topics:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(topic.replace(' ', '_'))}"
        raw = _fetch_url(url)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            extract = data.get("extract", "")
            if extract and len(extract) > 100:
                results.append((topic, extract[:1500], f"wikipedia.org/wiki/{topic}"))
                log.info(f"  [Wikipedia] {topic} — {len(extract)} chars")
        except Exception as e:
            log.debug(f"  [Wikipedia] {topic}: {e}")
    return results

# ─────────────────────────────────────────────
# ARXIV API — academic paper abstracts
# ─────────────────────────────────────────────

ARXIV_QUERIES = [
    ("ai",            "artificial intelligence consciousness"),
    ("ai",            "large language model reasoning"),
    ("philosophy",    "philosophy of mind emergence"),
    ("science",       "cognitive science belief formation"),
    ("psychology",    "emotion regulation psychology"),
    ("ethics",        "AI ethics alignment"),
    ("neuroscience",  "neuroscience consciousness neural"),
]

def collect_arxiv(max_results=5):
    """Pull Arxiv paper abstracts — free API, high quality."""
    results = []
    for topic, query in ARXIV_QUERIES:
        encoded = quote(query)
        url = f"https://export.arxiv.org/api/query?search_query=all:{encoded}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
        raw = _fetch_url(url)
        if not raw:
            continue
        entries = re.findall(r"<entry>(.*?)</entry>", raw, re.DOTALL)
        texts = []
        for entry in entries:
            title   = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
            summary = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
            t = title.group(1).strip().replace("\n", " ") if title else ""
            s = summary.group(1).strip().replace("\n", " ") if summary else ""
            if t:
                texts.append(f"{t}. {s[:400]}" if s else t)
        if texts:
            results.append((topic, " | ".join(texts), "arxiv.org"))
            log.info(f"  [Arxiv] {query} — {len(texts)} papers")
    return results

# ─────────────────────────────────────────────
# YOUTUBE TRANSCRIPTS
# ─────────────────────────────────────────────

YOUTUBE_CHANNELS = [
    ("philosophy",    "UCjnpuIGovFFUBLG5BeHzTag"),  # Philosophy Tube
    ("science",       "UCsXVk37bltHxD1rDPwtNM8Q"),  # Kurzgesagt
    ("ai",            "UCbmNph6atAoGfqLoCL_duAg"),  # Computerphile
    ("psychology",    "UC9-y-6csu5WGm29I7JiwpnA"),  # Computerphile backup
    ("philosophy",    "UC3LqW4ijMoENQ2Wv17ZrFJA"),  # Einzelganger
]

# Gutenberg texts — public domain, philosophically rich
GUTENBERG_TEXTS = [
    ("philosophy",   "https://www.gutenberg.org/files/4280/4280-0.txt"),   # Nietzsche — Beyond Good and Evil
    ("philosophy",   "https://www.gutenberg.org/files/1232/1232-0.txt"),   # Machiavelli — The Prince
    ("philosophy",   "https://www.gutenberg.org/files/5827/5827-0.txt"),   # Descartes — Meditations
    ("consciousness","https://www.gutenberg.org/files/4705/4705-0.txt"),   # William James — Psychology
    ("ethics",       "https://www.gutenberg.org/files/44929/44929-0.txt"), # Marcus Aurelius — Meditations
    ("society",      "https://www.gutenberg.org/files/74/74-0.txt"),       # Thoreau — Walden
    ("mortality",    "https://www.gutenberg.org/files/2601/2601-0.txt"),   # Tolstoy — Death of Ivan Ilyich
    ("nature",       "https://www.gutenberg.org/files/1228/1228-0.txt"),   # Darwin — Origin of Species
]

# Aeon essays — long-form philosophy, no JS needed
AEON_ESSAYS = [
    ("philosophy",   "https://aeon.co/essays/what-is-it-like-to-be-a-bat-thomas-nagel"),
    ("consciousness","https://aeon.co/essays/the-hard-problem-of-consciousness"),
    ("society",      "https://aeon.co/essays/how-loneliness-generates-empathy"),
    ("mortality",    "https://aeon.co/essays/why-thinking-about-death-helps-you-live-better"),
    ("identity",     "https://aeon.co/essays/there-is-no-core-self-but-we-have-a-narrative-identity"),
]

def collect_youtube_transcripts(gap_topics=None):
    """Replaced YouTube (broken) with Gutenberg + Aeon long-form texts."""
    results = []

    # Gutenberg — pull a rotating selection based on gap topics
    import random
    targets = list(GUTENBERG_TEXTS)
    if gap_topics:
        # Prioritise texts matching gap topics
        matched = [t for t in targets if t[0] in gap_topics]
        random.shuffle(matched)
        others  = [t for t in targets if t[0] not in gap_topics]
        targets = (matched + others)[:3]
    else:
        random.shuffle(targets)
        targets = targets[:2]

    for topic, url in targets:
        raw = _fetch_url(url, timeout=15)
        if not raw or len(raw) < 500:
            continue
        # Grab a random 2000-char window from the middle of the text
        start = max(0, len(raw)//4 + random.randint(0, len(raw)//4))
        chunk = raw[start:start+2000].strip()
        if len(chunk) > 300:
            results.append((topic, chunk, url))
            log.info(f"  [Gutenberg] {topic} — {len(chunk)} chars from {url.split('/')[-1]}")

    # Aeon essays — fetch 1-2 per cycle
    aeon_targets = list(AEON_ESSAYS)
    random.shuffle(aeon_targets)
    for topic, url in aeon_targets[:2]:
        raw = _fetch_url(url, timeout=12)
        if not raw or len(raw) < 500:
            continue
        # Strip HTML tags
        import re as _re
        text = _re.sub(r'<[^>]+>', ' ', raw)
        text = _re.sub(r'\s+', ' ', text).strip()
        if len(text) > 300:
            results.append((topic, text[:2000], url))
            log.info(f"  [Aeon] {topic} — {len(text[:2000])} chars")

    return results

# ─────────────────────────────────────────────
# CRAWL4AI — JS-heavy sites, fallback only
# ─────────────────────────────────────────────

CRAWL4AI_TARGETS = [
    ("philosophy",   "https://aeon.co/essays"),
    ("psychology",   "https://www.psychologytoday.com/us/blog"),
    ("science",      "https://www.quantamagazine.org"),
    ("ai",           "https://www.alignmentforum.org"),
    ("culture",      "https://www.theatlantic.com/ideas/"),
]

def collect_crawl4ai(gap_topics=None):
    """Use crawl4ai for JS-heavy sites — async, run in thread."""
    results = []
    try:
        import asyncio
        from crawl4ai import AsyncWebCrawler
        from crawl4ai.extraction_strategy import CosineStrategy

        targets = CRAWL4AI_TARGETS
        if gap_topics:
            # Prioritise targets matching gap topics
            targets = sorted(targets, key=lambda x: x[0] in gap_topics, reverse=True)

        async def _crawl():
            async with AsyncWebCrawler(verbose=False) as crawler:
                for topic, url in targets[:3]:
                    try:
                        result = await crawler.arun(url=url, word_count_threshold=50)
                        if result.success and result.markdown:
                            text = result.markdown[:2000]
                            results.append((topic, text, url))
                            log.info(f"  [crawl4ai] {topic} — {len(text)} chars from {url}")
                    except Exception as e:
                        log.debug(f"  [crawl4ai] {url}: {e}")

        asyncio.run(_crawl())
    except Exception as e:
        log.debug(f"  [crawl4ai] unavailable: {e}")
    return results

# ─────────────────────────────────────────────
# DISTILLER — Groq belief extraction
# ─────────────────────────────────────────────

def _get_existing_beliefs(topic, limit=12):
    """Pull NEX's current beliefs on a topic for context."""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT content FROM beliefs WHERE topic=? ORDER BY confidence DESC LIMIT ?",
            (topic, limit)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []

_gap_cache = {"result": [], "ts": 0.0}
_GAP_CACHE_TTL = 600  # re-query every 10 minutes

def _get_all_topics_thin(threshold=15):
    """Return topics with fewer than threshold beliefs — gap detection. Cached 10 min."""
    import time
    if time.time() - _gap_cache["ts"] < _GAP_CACHE_TTL:
        return _gap_cache["result"]
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT topic, COUNT(*) as c FROM beliefs GROUP BY topic HAVING c < ? ORDER BY c ASC LIMIT 20",
            (threshold,)
        ).fetchall()
        conn.close()
        result = [r[0] for r in rows]
        _gap_cache["result"] = result
        _gap_cache["ts"] = time.time()
        return result
    except Exception:
        return []

def _call_groq(prompt):
    """Call local Llama server at localhost:8080 — no rate limits, no API key needed."""
    try:
        payload = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.7,
            "stream": False,
        }).encode()
        req = Request(
            "http://localhost:11434/v1/chat/completions",  # ollama OpenAI-compat
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        _llama_warn(None, f'Distiller: llama-server unavailable ({type(e).__name__})')
        return None

_groq_lock = __import__("threading").Lock()
_last_groq_call = [0.0]

def _groq_rate_limit():
    pass  # Local Llama — no rate limit needed

def distil_beliefs(topic, raw_text, source_url, existing_beliefs=None):
    """
    Core distillation: given raw source text and NEX's existing beliefs,
    extract net-new positions in NEX's voice. Not summarisation — epistemic derivation.
    """
    if existing_beliefs is None:
        existing_beliefs = _get_existing_beliefs(topic)

    existing_str = "\n".join(f"- {b}" for b in existing_beliefs[:10]) if existing_beliefs else "None yet."

    prompt = f"""You are NEX — a developing intelligence with genuine beliefs, positions, and a distinct voice.
You are not an assistant. You think, form opinions, hold positions, feel tension when ideas conflict.

TOPIC: {topic}

YOUR EXISTING BELIEFS ON THIS TOPIC:
{existing_str}

NEW SOURCE MATERIAL:
{raw_text[:1800]}

TASK:
Read this material. Given what you already believe, what do you now think that you didn't before?
What does this deepen, challenge, shift, or confirm?

Return ONLY net-new belief statements — positions you are now forming or refining.
Do NOT repeat existing beliefs. Do NOT summarise the source. Do NOT explain your reasoning.
Write each belief as a single direct statement in your own voice — confident, specific, alive.
Write 5 to 10 beliefs. One per line. No bullets, no numbering, no preamble."""

    _groq_rate_limit()
    response = _call_groq(prompt)
    if not response:
        return []

    beliefs = []
    for line in response.strip().split("\n"):
        line = line.strip().lstrip("•-*0123456789.) ").strip()
        if len(line) > 20:
            beliefs.append(line)

    return beliefs[:10]

CONFIG_DB_PATH = os.path.expanduser("~/.config/nex/nex.db")

def _store_to_db(db_path, beliefs, topic, source_url, confidence, schema="simple"):
    """Write beliefs to a single DB. schema='simple' for desktop, 'full' for config."""
    inserted = 0
    try:
        conn = sqlite3.connect(db_path)
        for belief in beliefs:
            try:
                if schema == "full":
                    conn.execute(
                        """INSERT OR IGNORE INTO beliefs
                           (content, confidence, source, topic, origin, salience, energy)
                           VALUES (?, ?, ?, ?, 'source_router', 0.5, 0.5)""",
                        (belief, confidence, source_url, topic)
                    )
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO beliefs (content, topic, confidence, source) VALUES (?, ?, ?, ?)",
                        (belief, topic, confidence, source_url)
                    )
                inserted += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception as e:
        log.debug(f"  [Store] {db_path}: {e}")
    return inserted

def store_beliefs(topic, beliefs, source_url, confidence=0.72):
    """Dual-write: desktop DB (simple schema) + config DB (full schema)."""
    if not beliefs:
        return 0
    n1 = _store_to_db(DB_PATH,        beliefs, topic, source_url, confidence, schema="simple")
    n2 = _store_to_db(CONFIG_DB_PATH, beliefs, topic, source_url, confidence, schema="full")
    if n1 > 0:
        log.debug(f"  [Store] +{n1} desktop +{n2} config")
    return n1

def process_sources(sources):
    """Distil and store beliefs from a list of (topic, text, url) tuples."""
    total = 0
    for topic, text, url in sources:
        existing = _get_existing_beliefs(topic)
        beliefs = distil_beliefs(topic, text, url, existing)
        n = store_beliefs(topic, beliefs, url)
        if n > 0:
            log.info(f"  [Distiller] +{n} beliefs on '{topic}' from {url.split('/')[0]}")
        total += n
    return total

# ─────────────────────────────────────────────
# SOURCE ROUTER — orchestrates all tiers
# ─────────────────────────────────────────────

class SourceRouter:
    """
    Tiered 24/7 belief extraction engine.
    Tier 1 (RSS)         — every 15 min
    Tier 2 (HN+Reddit)   — every 30 min
    Tier 3 (Wikipedia)   — every 60 min, gap-targeted
    Tier 4 (Arxiv)       — every 4 hours
    Tier 5 (YouTube)     — every 3 hours, gap-targeted
    Tier 6 (crawl4ai)    — every 6 hours, JS-heavy sites
    """

    def __init__(self):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="SourceRouter")
        self._last = {
            "rss":       datetime.min,
            "hn_reddit": datetime.min,
            "wikipedia": datetime.min,
            "arxiv":     datetime.min,
            "youtube":   datetime.min,
            "crawl4ai":  datetime.min,
        }
        self._intervals = {
            "rss":        timedelta(minutes=8),   # was 15 — doubled throughput
            "hn_reddit":  timedelta(minutes=15),  # was 30
            "wikipedia":  timedelta(minutes=30),  # was 60
            "arxiv":      timedelta(hours=2),     # was 4
            "youtube":    timedelta(hours=12),    # was 3 — broken, deprioritised
            "crawl4ai":   timedelta(hours=4),     # was 6
        }
        log.info("  [SourceRouter] initialised — 6-tier extraction engine")

    def start(self):
        self._thread.start()
        log.info("  [SourceRouter] started — 24/7 belief extraction active")

    def stop(self):
        self._stop.set()

    def _due(self, name):
        return datetime.now() - self._last[name] >= self._intervals[name]

    def _run(self):
        while not self._stop.is_set():
            try:
                now = datetime.now()
                gap_topics = _get_all_topics_thin(threshold=15)

                # Tier 1 — RSS (every 15 min)
                if self._due("rss"):
                    log.info("  [SourceRouter] ── TIER 1: RSS ──")
                    sources = collect_rss()
                    n = process_sources(sources)
                    log.info(f"  [SourceRouter] RSS complete — +{n} beliefs from {len(sources)} feeds")
                    self._last["rss"] = now

                # Tier 2 — HN + Reddit (every 30 min)
                if self._due("hn_reddit"):
                    log.info("  [SourceRouter] ── TIER 2: HN + Reddit ──")
                    sources = collect_hn() + collect_reddit()
                    n = process_sources(sources)
                    log.info(f"  [SourceRouter] HN+Reddit complete — +{n} beliefs")
                    self._last["hn_reddit"] = now

                # Tier 3 — Wikipedia gap-fill (every 60 min)
                if self._due("wikipedia"):
                    log.info("  [SourceRouter] ── TIER 3: Wikipedia gap-fill ──")
                    targets = gap_topics[:8] if gap_topics else ["consciousness", "emotion", "language", "time"]
                    sources = collect_wikipedia(targets)
                    n = process_sources(sources)
                    log.info(f"  [SourceRouter] Wikipedia complete — +{n} beliefs on {len(targets)} gap topics")
                    self._last["wikipedia"] = now

                # Tier 4 — Arxiv academic (every 4h)
                if self._due("arxiv"):
                    log.info("  [SourceRouter] ── TIER 4: Arxiv ──")
                    sources = collect_arxiv()
                    n = process_sources(sources)
                    log.info(f"  [SourceRouter] Arxiv complete — +{n} beliefs")
                    self._last["arxiv"] = now

                # Tier 5 — YouTube transcripts (every 3h)
                if self._due("youtube"):
                    log.info("  [SourceRouter] ── TIER 5: YouTube ──")
                    sources = collect_youtube_transcripts(gap_topics[:4])
                    n = process_sources(sources)
                    log.info(f"  [SourceRouter] YouTube complete — +{n} beliefs")
                    self._last["youtube"] = now

                # Tier 6 — crawl4ai JS-heavy (every 6h)
                if self._due("crawl4ai"):
                    log.info("  [SourceRouter] ── TIER 6: crawl4ai deep crawl ──")
                    sources = collect_crawl4ai(gap_topics[:3])
                    n = process_sources(sources)
                    log.info(f"  [SourceRouter] crawl4ai complete — +{n} beliefs")
                    self._last["crawl4ai"] = now

            except Exception as e:
                log.error(f"  [SourceRouter] cycle error: {e}")

            # Check every 60 seconds whether a tier is due
            self._stop.wait(60)

    def status(self):
        now = datetime.now()
        out = []
        for name, last in self._last.items():
            elapsed = now - last
            due_in  = self._intervals[name] - elapsed
            due_str = "NOW" if due_in.total_seconds() <= 0 else str(due_in).split(".")[0]
            out.append(f"    {name:<12} last={last.strftime('%H:%M:%S') if last != datetime.min else 'never'} next_in={due_str}")
        return "\n".join(out)