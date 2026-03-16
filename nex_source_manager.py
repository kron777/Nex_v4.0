#!/usr/bin/env python3
"""
nex_source_manager.py — Layer 2: Multi-Source Absorption Engine
NEX Omniscience Upgrade v4.1 → v4.2

Manages RSS + API sources mapped to NEX's knowledge domains.
Scores sources by signal/noise. Drops low performers automatically.
"""

import os
import json
import time
import hashlib
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

CFG_PATH     = Path("~/.config/nex").expanduser()
SOURCES_FILE = CFG_PATH / "active_sources.json"
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"

# ── Default domain-mapped sources ────────────────────────────
# Aligned to NEX's core identity: cognitive architecture, AI agents,
# cybersecurity, philosophy of mind, memory systems
DEFAULT_SOURCES = {
    "cognitive_architecture": [
        {"url": "https://export.arxiv.org/rss/cs.AI",  "name": "arxiv_AI",  "score": 1.0},
        {"url": "https://export.arxiv.org/rss/cs.NE",  "name": "arxiv_NE",  "score": 1.0},
    ],
    "ai_agents": [
        {"url": "https://www.lesswrong.com/feed.xml",  "name": "lesswrong", "score": 1.0},
        {"url": "https://export.arxiv.org/rss/cs.MA",  "name": "arxiv_multiagent", "score": 1.0},
    ],
    "cybersecurity": [
        {"url": "https://feeds.feedburner.com/TheHackersNews", "name": "hackernews_sec", "score": 1.0},
        {"url": "https://export.arxiv.org/rss/cs.CR",  "name": "arxiv_security", "score": 1.0},
    ],
    "philosophy_of_mind": [
        {"url": "https://aeon.co/feed.rss",            "name": "aeon",      "score": 1.0},
        {"url": "https://blog.philosophyofbrains.com/feed", "name": "phil_brains", "score": 1.0},
    ],
    "memory_systems": [
        {"url": "https://export.arxiv.org/rss/cs.LG",  "name": "arxiv_ML",  "score": 1.0},
        {"url": "https://distill.pub/rss.xml",         "name": "distill",   "score": 1.0},
    ],
}

# Min score to keep a source (drops if below after 10+ uses)
MIN_SCORE    = 0.3
MAX_ARTICLES = 5   # per source per run


def _load_sources() -> dict:
    if SOURCES_FILE.exists():
        try:
            data = json.loads(SOURCES_FILE.read_text())
            if isinstance(data, dict):
                return data
            # File is a list — reset to defaults
            print("  [sources] active_sources.json was list format, resetting to defaults")
        except Exception:
            pass
    return DEFAULT_SOURCES.copy()


def _save_sources(sources: dict):
    CFG_PATH.mkdir(parents=True, exist_ok=True)
    SOURCES_FILE.write_text(json.dumps(sources, indent=2))


def _groq_extract_belief(title: str, summary: str, domain: str) -> str | None:
    """Use Groq to extract a clean belief statement from an article."""
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return f"{title}: {summary[:100]}" if title else None
    try:
        prompt = (
            f"Extract ONE clear, factual belief statement from this article.\n"
            f"Domain: {domain}\n"
            f"Title: {title}\n"
            f"Summary: {summary[:300]}\n\n"
            f"Reply with ONE sentence — the most interesting, durable insight from this article. "
            f"No preamble, no 'The article says'. Just the belief itself."
        )
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": GROQ_MODEL,
                "max_tokens": 80,
                "temperature": 0.3,
                "messages": [
                    {"role": "system", "content": "You extract clean belief statements from articles."},
                    {"role": "user",   "content": prompt}
                ]
            }, timeout=15)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return f"{title}: {summary[:100]}" if title else None


def fetch_rss(url: str, max_items: int = MAX_ARTICLES) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of {title, summary, link}."""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "NEX/4.2 RSS Reader"})
        root = ET.fromstring(r.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = []

        # RSS 2.0
        for item in root.findall(".//item")[:max_items]:
            title   = item.findtext("title", "").strip()
            summary = item.findtext("description", "").strip()[:400]
            link    = item.findtext("link", "").strip()
            if title:
                items.append({"title": title, "summary": summary, "link": link})

        # Atom
        if not items:
            for entry in root.findall(".//atom:entry", ns)[:max_items]:
                title   = entry.findtext("atom:title", "", ns).strip()
                summary = entry.findtext("atom:summary", "", ns).strip()[:400]
                link    = entry.find("atom:link", ns)
                link    = link.get("href", "") if link is not None else ""
                if title:
                    items.append({"title": title, "summary": summary, "link": link})

        return items
    except Exception as e:
        print(f"  [sources] RSS fetch error {url}: {e}")
        return []


def absorb_from_sources(learner=None, cycle: int = 0) -> dict:
    """
    Main entry point. Absorb beliefs from all active sources.
    Called from run.py every 3 cycles.
    Returns: {domain: beliefs_added}
    """
    if cycle % 3 != 0:
        return {"skipped": True}

    sources   = _load_sources()
    seen_path = CFG_PATH / "sources_seen.json"
    seen_ids  = set()
    try:
        if seen_path.exists():
            seen_ids = set(json.loads(seen_path.read_text()))
    except Exception:
        pass

    stats         = {}
    new_beliefs   = []
    new_seen      = set()

    for domain, source_list in sources.items():
        domain_count = 0
        for source in source_list:
            url   = source.get("url", "")
            name  = source.get("name", url)
            items = fetch_rss(url)

            beliefs_from_source = 0
            for item in items:
                # Deduplicate by title hash
                item_id = hashlib.md5(item["title"].encode()).hexdigest()
                if item_id in seen_ids:
                    continue
                new_seen.add(item_id)

                belief_text = _groq_extract_belief(item["title"], item["summary"], domain)
                if not belief_text:
                    continue

                belief = {
                    "source":     name,
                    "author":     name,
                    "content":    belief_text,
                    "confidence": 0.55,
                    "tags":       [domain],
                    "timestamp":  datetime.utcnow().isoformat(),
                    "url":        item.get("link", ""),
                }
                new_beliefs.append(belief)
                beliefs_from_source += 1
                domain_count += 1

            # Score update
            if items:
                source["uses"]  = source.get("uses", 0) + 1
                source["score"] = min(1.0, source.get("score", 1.0) + (beliefs_from_source * 0.05))
            print(f"  [sources] {name}: {beliefs_from_source} beliefs")

        # Drop low-scoring sources
        sources[domain] = [
            s for s in source_list
            if s.get("uses", 0) < 10 or s.get("score", 1.0) >= MIN_SCORE
        ]
        stats[domain] = domain_count

    # Ingest into learner belief field if available
    if learner and new_beliefs:
        for b in new_beliefs:
            learner.belief_field.append(b)

    # Persist seen IDs (cap at 5000)
    seen_ids.update(new_seen)
    seen_path.write_text(json.dumps(list(seen_ids)[-5000:]))
    _save_sources(sources)

    total = sum(stats.values())
    print(f"  [sources] Total absorbed: {total} beliefs from {len(sources)} domains")
    return {"stats": stats, "total": total, "beliefs": new_beliefs}


def add_source(domain: str, url: str, name: str):
    """Add a new RSS source for a domain. Called when NEX finds a knowledge gap."""
    sources = _load_sources()
    if domain not in sources:
        sources[domain] = []
    # Check not already present
    if not any(s["url"] == url for s in sources[domain]):
        sources[domain].append({"url": url, "name": name, "score": 1.0, "uses": 0})
        _save_sources(sources)
        print(f"  [sources] Added source: {name} → {domain}")


def get_source_report() -> str:
    """Return a readable summary of active sources and their scores."""
    sources = _load_sources()
    lines   = ["Active Sources:"]
    for domain, source_list in sources.items():
        lines.append(f"  {domain}:")
        for s in source_list:
            lines.append(f"    {s['name']:20} score={s.get('score',1.0):.2f} uses={s.get('uses',0)}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(get_source_report())
    print("\nRunning absorption test...")
    result = absorb_from_sources(cycle=0)
    print(f"Result: {result.get('total', 0)} beliefs absorbed")
