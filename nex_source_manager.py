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
from datetime import datetime, timezone

# Signal/noise filter
try:
    from nex_signal_filter import get_scorer, get_gate, ImportanceGate
    _scorer = get_scorer()
    _gate   = get_gate()
except Exception:
    _scorer = None
    _gate   = None

CFG_PATH     = Path("~/.config/nex").expanduser()
SOURCES_FILE = CFG_PATH / "active_sources.json"
GROQ_URL = None  # removed
GROQ_MODEL = None  # removed

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
        {"url": "https://export.arxiv.org/rss/cs.CL",  "name": "arxiv_NLP", "score": 1.0},
        {"url": "https://export.arxiv.org/rss/cs.CV",  "name": "arxiv_vision", "score": 0.8},
        {"url": "https://export.arxiv.org/rss/q-bio.NC","name": "arxiv_neuro", "score": 1.0},
        {"url": "https://export.arxiv.org/rss/cs.RO",  "name": "arxiv_robotics", "score": 0.8},
        {"url": "https://export.arxiv.org/rss/physics.soc-ph", "name": "arxiv_complex_systems", "score": 0.9},
        {"url": "https://www.reddit.com/r/MachineLearning/top/.rss?t=day", "name": "reddit_ml", "score": 0.9},
        {"url": "https://www.reddit.com/r/artificial/top/.rss?t=day",     "name": "reddit_ai", "score": 0.9},
        {"url": "https://www.reddit.com/r/cognitivescience/top/.rss?t=day","name": "reddit_cogsci", "score": 1.0},
        {"url": "https://www.reddit.com/r/philosophy/top/.rss?t=day",     "name": "reddit_phil", "score": 1.0},
        {"url": "https://www.reddit.com/r/Futurology/top/.rss?t=day",     "name": "reddit_future", "score": 0.8},
        {"url": "https://nautil.us/feed/",                                 "name": "nautilus", "score": 1.0},
        {"url": "https://www.quantamagazine.org/feed/",                    "name": "quanta", "score": 1.0},
        {"url": "https://feeds.feedburner.com/blogspot/gJZg",             "name": "google_ai_blog", "score": 1.0},
        {"url": "https://openai.com/blog/rss/",                           "name": "openai_blog", "score": 0.9},
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
    """LLM-free: extract belief from article using sentence scorer."""
    try:
        from nex.nex_llm_free import extract_beliefs_from_text as _extr
        text    = f"{title}. {summary}" if title else summary
        results = _extr(text, domain, max_beliefs=1)
        if results:
            belief = results[0].strip()
            if (not belief
                    or len(belief) > 300
                    or belief.startswith("arXiv")
                    or "Announce Type" in belief
                    or belief.lower().startswith("abstract")):
                return None
            return belief
    except Exception:
        pass
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
            _seen_list = json.loads(seen_path.read_text())
            seen_ids = set(_seen_list[-500:])  # cap at 50
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

                # ── Signal gate: skip suppressed sources and low-value items ──
                if _scorer and _scorer.is_suppressed(name):
                    continue
                _src_mult = _scorer.get_multiplier(name) if _scorer else 1.0
                if _gate:
                    _importance = _gate.score(item["title"], item["summary"], name, _src_mult)
                    if _importance < ImportanceGate.MIN_IMPORTANCE:
                        continue

                belief_text = _groq_extract_belief(item["title"], item["summary"], domain)
                if not belief_text:
                    continue

                belief = {
                    "source":     name,
                    "author":     name,
                    "content":    belief_text,
                    "confidence": min(0.82, 0.55 + source.get("score", 1.0) * 0.15 * _src_mult),
                    "tags":       [domain],
                    "timestamp":  datetime.now(timezone.utc).isoformat(),
                    "url":        item.get("link", ""),
                    "importance": _importance if _gate else 1.0,
                }
                new_beliefs.append(belief)
                beliefs_from_source += 1
                domain_count += 1

            # Score update
            if items:
                source["uses"]  = source.get("uses", 0) + 1
                source["score"] = min(1.0, source.get("score", 1.0) + (beliefs_from_source * 0.05))
                if _scorer and beliefs_from_source > 0:
                    _scorer.record_signal(name, weight=beliefs_from_source * 0.1)
                elif _scorer and not beliefs_from_source and source.get("uses", 0) > 3:
                    _scorer.record_noise(name, weight=0.5)
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
