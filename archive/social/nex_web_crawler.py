#!/usr/bin/env python3
"""
nex_web_crawler.py
───────────────────
Targeted web crawler for NEX. Given a topic/gap, fetches relevant
content from multiple free sources:
  - Wikipedia (deep factual context)
  - Reddit (opinions, arguments, lived experience)
  - Hacker News (tech, ideas, culture)
  - RSS feeds (news, blogs)
  - arXiv abstracts (science, philosophy)

Returns raw text chunks ready for distillation.
Not a scraper — a targeted epistemic fetcher.
"""

import os, re, json, time, random
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET

TIMEOUT     = 12
USER_AGENT  = "Mozilla/5.0 (NEX epistemic crawler; educational)"
MAX_CHUNKS  = 6   # max text chunks to return per topic


def _fetch(url, timeout=TIMEOUT):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            enc = r.headers.get_content_charset("utf-8")
            return raw.decode(enc, errors="replace")
    except Exception as e:
        return None


def _clean(text):
    """Strip HTML tags and normalise whitespace."""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _truncate(text, words=400):
    parts = text.split()
    return " ".join(parts[:words])


# ── Wikipedia ─────────────────────────────────────────────────────────────────

def fetch_wikipedia(topic):
    """Fetch Wikipedia extract for a topic. Returns text chunk or None."""
    query = urllib.parse.quote(topic.replace("_", " "))
    url   = (
        f"https://en.wikipedia.org/w/api.php"
        f"?action=query&prop=extracts&exintro&explaintext"
        f"&redirects=1&titles={query}&format=json"
    )
    raw = _fetch(url)
    if not raw:
        return None
    try:
        data    = json.loads(raw)
        pages   = data["query"]["pages"]
        page    = next(iter(pages.values()))
        extract = page.get("extract", "")
        if extract and len(extract) > 100:
            return {
                "source": "wikipedia",
                "topic":  topic,
                "url":    f"https://en.wikipedia.org/wiki/{query}",
                "text":   _truncate(_clean(extract), 500),
            }
    except Exception:
        pass
    return None


# ── Reddit (public JSON — no auth needed) ────────────────────────────────────

def fetch_reddit(topic, subreddits=None):
    """Fetch top Reddit posts/comments for a topic. Returns list of chunks."""
    if subreddits is None:
        subreddits = ["all", "philosophy", "psychology", "AskReddit",
                      "changemyview", "self"]

    chunks = []
    sub = random.choice(subreddits)
    query = urllib.parse.quote(topic.replace("_", " "))
    url   = f"https://www.reddit.com/r/{sub}/search.json?q={query}&sort=top&limit=5&t=year"

    raw = _fetch(url)
    if not raw:
        return chunks
    try:
        data  = json.loads(raw)
        posts = data["data"]["children"]
        for post in posts[:3]:
            p = post["data"]
            title    = p.get("title", "")
            selftext = p.get("selftext", "")
            if len(selftext) > 100:
                text = f"{title}. {selftext}"
                chunks.append({
                    "source": "reddit",
                    "topic":  topic,
                    "url":    f"https://reddit.com{p.get('permalink','')}",
                    "text":   _truncate(_clean(text), 300),
                })
    except Exception:
        pass
    return chunks


# ── Hacker News Algolia API ───────────────────────────────────────────────────

def fetch_hackernews(topic):
    """Fetch HN discussions about a topic. Returns list of chunks."""
    query = urllib.parse.quote(topic.replace("_", " "))
    url   = f"https://hn.algolia.com/api/v1/search?query={query}&tags=story&hitsPerPage=5"

    raw = _fetch(url)
    if not raw:
        return []
    chunks = []
    try:
        data = json.loads(raw)
        for hit in data.get("hits", [])[:3]:
            title   = hit.get("title", "")
            story   = hit.get("story_text") or hit.get("comment_text") or ""
            if title:
                text = f"{title}. {story}"
                chunks.append({
                    "source": "hackernews",
                    "topic":  topic,
                    "url":    hit.get("url", ""),
                    "text":   _truncate(_clean(text), 250),
                })
    except Exception:
        pass
    return chunks


# ── arXiv ─────────────────────────────────────────────────────────────────────

def fetch_arxiv(topic):
    """Fetch arXiv abstracts for philosophical/scientific topics."""
    query = urllib.parse.quote(topic.replace("_", " "))
    url   = (
        f"https://export.arxiv.org/api/query"
        f"?search_query=all:{query}&start=0&max_results=3"
    )
    raw = _fetch(url)
    if not raw:
        return []
    chunks = []
    try:
        root = ET.fromstring(raw)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns)[:2]:
            title   = entry.find("atom:title",   ns)
            summary = entry.find("atom:summary", ns)
            link    = entry.find("atom:id",      ns)
            if title is not None and summary is not None:
                text = f"{title.text.strip()}. {summary.text.strip()}"
                chunks.append({
                    "source": "arxiv",
                    "topic":  topic,
                    "url":    link.text.strip() if link is not None else "",
                    "text":   _truncate(_clean(text), 300),
                })
    except Exception:
        pass
    return chunks


# ── RSS feeds ─────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    "https://feeds.feedburner.com/brainpickings/rss",   # Brain Pickings — ideas
    "https://www.theguardian.com/world/rss",             # Guardian world
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "https://aeon.co/feed.rss",                          # Aeon — philosophy/culture
    "https://nautil.us/feed/",                           # Nautilus — science/philosophy
    "https://psyche.co/feed",                            # Psyche — psychology
]

def fetch_rss(topic):
    """Search RSS feeds for items relevant to a topic. Returns list of chunks."""
    topic_words = set(topic.lower().replace("_", " ").split())
    chunks = []

    feed_url = random.choice(RSS_FEEDS)
    raw = _fetch(feed_url)
    if not raw:
        return chunks

    try:
        root  = ET.fromstring(raw)
        items = root.findall(".//item") or root.findall(
            ".//{http://www.w3.org/2005/Atom}entry"
        )
        for item in items[:20]:
            title_el = (item.find("title") or
                        item.find("{http://www.w3.org/2005/Atom}title"))
            desc_el  = (item.find("description") or
                        item.find("summary") or
                        item.find("{http://www.w3.org/2005/Atom}summary"))
            link_el  = (item.find("link") or
                        item.find("{http://www.w3.org/2005/Atom}link"))

            title = title_el.text if title_el is not None else ""
            desc  = desc_el.text  if desc_el  is not None else ""
            link  = link_el.text  if link_el  is not None else ""

            combined = f"{title} {desc}".lower()
            if any(w in combined for w in topic_words):
                text = f"{title}. {desc}"
                chunks.append({
                    "source": "rss",
                    "topic":  topic,
                    "url":    link or feed_url,
                    "text":   _truncate(_clean(text), 250),
                })
                if len(chunks) >= 2:
                    break
    except Exception:
        pass
    return chunks


# ── Main fetch function ───────────────────────────────────────────────────────

def fetch_for_topic(topic, max_chunks=MAX_CHUNKS):
    """
    Fetch content from multiple sources for a topic.
    Returns list of chunk dicts, each with: source, topic, url, text
    """
    chunks = []

    # Wikipedia first — most reliable signal
    wiki = fetch_wikipedia(topic)
    if wiki:
        chunks.append(wiki)

    # Reddit — lived experience and opinions
    chunks.extend(fetch_reddit(topic))
    if len(chunks) >= max_chunks:
        return chunks[:max_chunks]

    # Hacker News — ideas and discussion
    chunks.extend(fetch_hackernews(topic))
    if len(chunks) >= max_chunks:
        return chunks[:max_chunks]

    # RSS — current context
    chunks.extend(fetch_rss(topic))
    if len(chunks) >= max_chunks:
        return chunks[:max_chunks]

    # arXiv — for abstract/philosophical topics
    abstract_topics = {
        "consciousness", "free_will", "mathematics", "philosophy",
        "paradox", "simulation", "infinity", "language", "empathy",
        "identity", "memory", "meaning", "beauty", "randomness",
    }
    if topic in abstract_topics:
        chunks.extend(fetch_arxiv(topic))

    return chunks[:max_chunks]


if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "consciousness"
    print(f"\n  Fetching content for: {topic}\n")
    chunks = fetch_for_topic(topic)
    for i, c in enumerate(chunks, 1):
        print(f"  [{i}] {c['source'].upper()} — {c['url'][:60]}")
        print(f"      {c['text'][:150]}...")
        print()
    print(f"  Total chunks: {len(chunks)}")
