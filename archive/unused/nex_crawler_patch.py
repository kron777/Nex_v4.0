"""
nex_crawler_patch.py
────────────────────
Drop-in replacements for three functions in nex/nex_crawler.py:

  1. _extract_sentences()     — fixed + hardened
  2. _sentences_to_beliefs()  — unchanged but included for completeness
  3. NexCrawler.on_knowledge_gap()  — now resolves real Wikipedia URLs

HOW TO APPLY
────────────
Replace the three corresponding blocks in nex/nex_crawler.py with the
code below.  Everything else in the file stays the same.
"""

import re
import time
import urllib.parse
import urllib.request
import json
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Constants (already defined in nex_crawler.py — don't duplicate)
# ─────────────────────────────────────────────────────────────────────────────
# MAX_BELIEFS_PER_CRAWL = 12
# MIN_SENTENCE_LEN = 40
# MAX_SENTENCE_LEN = 300


# ─────────────────────────────────────────────────────────────────────────────
# 1. _extract_sentences  (REPLACEMENT)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_sentences(markdown_text: str) -> list[str]:
    """
    Pull clean, belief-worthy sentences from crawl4ai markdown output.

    Improvements over the old version:
      • Skips Wikipedia nav boilerplate before the first H1 (article title).
      • Cuts off at References / See also / External links sections.
      • Strips markdown syntax before splitting.
      • Filters noise lines (URLs, copyright, bare numbers, nav fragments).
    """

    # ── Step 1: isolate article body for Wikipedia pages ─────────────────────
    # Wikipedia markdown starts with nav links, then the article H1, then body.
    # Everything before the first "# Title" line is boilerplate — drop it.
    h1_match = re.search(r'(?m)^#\s+\S', markdown_text)
    if h1_match:
        body = markdown_text[h1_match.start():]
    else:
        body = markdown_text

    # ── Step 2: cut off back-matter sections ─────────────────────────────────
    # References, See also, External links, Notes, Further reading, etc.
    back_matter = re.search(
        r'(?mi)^#{1,3}\s*(References|See also|External links|Notes|'
        r'Further reading|Bibliography|Footnotes|Citations)\s*$',
        body
    )
    if back_matter:
        body = body[:back_matter.start()]

    # ── Step 3: strip markdown syntax ────────────────────────────────────────
    text = body

    # Remove image tags entirely
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', '', text)

    # Collapse links to their display text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # Remove heading markers, bold, italic, code, blockquote, strikethrough
    text = re.sub(r'[#*`_~>]', '', text)

    # Remove HTML tags that occasionally leak through
    text = re.sub(r'<[^>]+>', '', text)

    # Remove table formatting characters
    text = re.sub(r'\|', ' ', text)

    # Collapse whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{2,}', '\n', text)

    # ── Step 4: split into sentences ─────────────────────────────────────────
    # Split on sentence-ending punctuation followed by whitespace + capital.
    # This is intentionally simple — good enough for encyclopedic prose.
    raw_sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z\"])', text)

    # ── Step 5: filter ───────────────────────────────────────────────────────
    NOISE_PATTERNS = [
        r'^https?://',            # bare URLs
        r'^www\.',
        r'©',                     # copyright lines
        r'^\d+$',                 # bare numbers
        r'^\s*$',                 # blank
        r'^\[',                   # leftover link fragments
        r'retrieved\s+\d{1,2}',  # citation retrieval lines (case-insensitive)
        r'isbn\s+\d',             # ISBN lines
        r'doi\s*:',               # DOI lines
        r'^\s{0,4}\^',            # footnote markers
    ]
    noise_re = re.compile('|'.join(NOISE_PATTERNS), re.IGNORECASE)

    results = []
    for s in raw_sentences:
        s = s.strip()

        # Length gate
        if not (MIN_SENTENCE_LEN <= len(s) <= MAX_SENTENCE_LEN):
            continue

        # Noise gate
        if noise_re.search(s):
            continue

        # Must contain at least one lowercase word (filters ALL-CAPS nav junk)
        if not re.search(r'[a-z]{3,}', s):
            continue

        results.append(s)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 2. _sentences_to_beliefs  (unchanged — included for reference)
# ─────────────────────────────────────────────────────────────────────────────

def _sentences_to_beliefs(sentences: list[str], source_url: str, topic: str) -> list[dict]:
    """Convert sentences into Nex belief dicts compatible with BeliefStore."""
    beliefs = []
    for s in sentences[:MAX_BELIEFS_PER_CRAWL]:
        beliefs.append({
            "content": s,
            "source": source_url,
            "topic": topic,
            "confidence": 0.55,
            "origin": "crawl",
            "timestamp": time.time(),
        })
    return beliefs


# ─────────────────────────────────────────────────────────────────────────────
# 3. NexCrawler.on_knowledge_gap  (REPLACEMENT — resolves real Wikipedia URLs)
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_wikipedia_url(topic: str) -> Optional[str]:
    """
    Use the Wikipedia opensearch API to resolve a topic string into a real
    article URL.  Returns None if nothing is found.

    This avoids the previous bug where made-up slugs like
    'RLHF_human_feedback_training' silently returned cached empty pages.

    The API call is synchronous and fast (~100 ms) — fine for a pre-fetch step.
    """
    endpoint = "https://en.wikipedia.org/w/api.php"
    params = urllib.parse.urlencode({
        "action": "opensearch",
        "search": topic,
        "limit": 1,
        "namespace": 0,
        "format": "json",
    })
    url = f"{endpoint}?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NexCrawler/1.0 (knowledge-gap resolver)"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            # opensearch returns [query, [titles], [descriptions], [urls]]
            urls = data[3] if len(data) >= 4 else []
            if urls:
                resolved = urls[0]
                return resolved
    except Exception as e:
        # Non-fatal: fall back to None so caller can try DuckDuckGo instead
        import logging
        logging.getLogger("nex.crawler").debug(
            f"[crawler] Wikipedia opensearch failed for '{topic}': {e}"
        )

    return None


def _resolve_duckduckgo_url(topic: str) -> str:
    """
    Fallback: build a DuckDuckGo search URL.
    crawl4ai can scrape DDG results and still yield useful sentences.
    """
    safe = urllib.parse.quote_plus(topic)
    return f"https://duckduckgo.com/?q={safe}&ia=web"


# ── Replace NexCrawler.on_knowledge_gap with this method ─────────────────────

def on_knowledge_gap(self, topic: str, search_url: Optional[str] = None) -> int:
    """
    Call from cognition.py when a stop-word / knowledge gap is detected.

    Resolution order (if no URL supplied):
      1. Wikipedia opensearch API  → real article URL
      2. DuckDuckGo search page    → fallback

    Returns number of beliefs stored.
    """
    if not self._enabled:
        return 0

    if not search_url:
        search_url = _resolve_wikipedia_url(topic)

        if search_url:
            logger.info(f"[crawler] Wikipedia resolved '{topic}' → {search_url}")
        else:
            search_url = _resolve_duckduckgo_url(topic)
            logger.info(f"[crawler] Wikipedia lookup failed, falling back to DDG: {search_url}")

    logger.info(f"[crawler] knowledge gap trigger — topic: {topic}")
    return self._run(self._fetch_and_store(search_url, topic))


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test  (run this file directly to verify before patching)
# ─────────────────────────────────────────────────────────────────────────────
#
#   python3 nex_crawler_patch.py
#
# Expected output: 3 sample sentences from the RLHF Wikipedia article,
# and a resolved URL printed for each topic.

if __name__ == "__main__":
    # Minimal stubs so we can test without the full Nex stack
    MAX_BELIEFS_PER_CRAWL = 12
    MIN_SENTENCE_LEN = 40
    MAX_SENTENCE_LEN = 300

    print("=" * 60)
    print("TEST 1: Wikipedia URL resolution")
    print("=" * 60)

    test_topics = [
        "reinforcement learning from human feedback",  # should resolve cleanly
        "large language model alignment",              # should resolve
        "RLHF human feedback training",                # was previously broken
        "curiosity and security",                      # ambiguous — may fall back
    ]
    for t in test_topics:
        url = _resolve_wikipedia_url(t)
        status = "✅" if url else "⚠️  (will use DDG fallback)"
        print(f"  {status}  '{t}'\n       → {url or _resolve_duckduckgo_url(t)}")

    print()
    print("=" * 60)
    print("TEST 2: _extract_sentences on live Wikipedia page")
    print("=" * 60)

    import asyncio
    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode

        CRAWL_CONFIG = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=30,
            exclude_external_links=True,
            remove_overlay_elements=True,
            wait_until="domcontentloaded",
        )

        async def _test_extract():
            url = _resolve_wikipedia_url("reinforcement learning from human feedback")
            print(f"  Fetching: {url}")
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url, config=CRAWL_CONFIG)

            if not result.success:
                print("  ❌ Fetch failed")
                return

            sentences = _extract_sentences(result.markdown)
            print(f"\n  Extracted {len(sentences)} sentences (showing first 5):\n")
            for i, s in enumerate(sentences[:5], 1):
                print(f"  [{i}] {s}\n")

        asyncio.run(_test_extract())

    except ImportError:
        print("  crawl4ai not available — skipping live fetch test")
        print("  (URL resolution test above is still valid)")
