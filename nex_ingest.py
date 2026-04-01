#!/usr/bin/env python3
"""
nex_ingest.py — NEX RSS → DB Ingestion Pipeline
================================================
Place at: ~/Desktop/nex/nex_ingest.py

Runs continuously in a separate terminal/process.
Fetches RSS feeds, extracts beliefs via nex_llm_free (no LLM),
and writes them directly to nex.db.

This closes the gap between source_manager's in-memory belief_field
and the persistent belief graph.

Usage:
    python3 nex_ingest.py              # run once
    python3 nex_ingest.py --loop       # run every 30 minutes
    python3 nex_ingest.py --loop --interval 60  # run every 60 minutes

Destination: ~/Desktop/nex/nex_ingest.py
"""

import sys
import os
import time
import sqlite3
import hashlib
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
NEX_DIR = Path("/home/rr/Desktop/nex")
sys.path.insert(0, str(NEX_DIR))
sys.path.insert(0, str(NEX_DIR / "nex"))

DB_PATH  = NEX_DIR / "nex.db"
CFG_PATH = Path("~/.config/nex").expanduser()
SEEN_PATH = CFG_PATH / "ingest_seen.json"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [INGEST] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("nex.ingest")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _inject_belief(content: str, topic: str, confidence: float,
                   source: str, url: str = "") -> bool:
    """Write a single belief to nex.db. Returns True if inserted."""
    if not content or len(content) < 20 or len(content) > 400:
        return False
    # Quality gate — reject garbage beliefs
    try:
        from nex_belief_quality_gate import is_quality_belief
        ok, reason = is_quality_belief(content, topic)
        if not ok:
            return False
    except Exception:
        pass

    # Clean content
    content = content.strip()
    if not content[-1] in ".!?":
        content += "."

    try:
        conn = _get_db()
        # Check for near-duplicate (first 80 chars match)
        prefix = content[:80].lower()
        existing = conn.execute(
            "SELECT id FROM beliefs WHERE substr(lower(content),1,80) = ?",
            (prefix,)
        ).fetchone()

        if existing:
            conn.close()
            return False

        conn.execute("""
            INSERT INTO beliefs
                (content, topic, confidence, source, source_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            content,
            topic,
            round(confidence, 3),
            source,
            url,
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
        conn.close()
        return True

    except sqlite3.OperationalError as e:
        if "locked" in str(e):
            log.warning(f"DB locked — retrying in 3s")
            time.sleep(3)
            return _inject_belief(content, topic, confidence, source, url)
        log.error(f"DB error: {e}")
        return False
    except Exception as e:
        log.error(f"Inject error: {e}")
        return False


# ── Seen dedup ────────────────────────────────────────────────────────────────

def _load_seen() -> set:
    try:
        if SEEN_PATH.exists():
            import json
            data = json.loads(SEEN_PATH.read_text())
            return set(data[-2000:])  # keep last 2000
    except Exception:
        pass
    return set()


def _save_seen(seen: set):
    try:
        import json
        CFG_PATH.mkdir(parents=True, exist_ok=True)
        SEEN_PATH.write_text(json.dumps(list(seen)[-2000:]))
    except Exception as e:
        log.warning(f"Could not save seen: {e}")


# ── Belief extraction (LLM-free) ──────────────────────────────────────────────

def _extract_beliefs(title: str, summary: str, topic: str) -> list[str]:
    """
    Extract belief sentences from article text using nex_llm_free.
    No LLM. Pure sentence scoring.
    """
    try:
        from nex.nex_llm_free import extract_beliefs_from_text
        text = f"{title}. {summary}" if title else summary
        results = extract_beliefs_from_text(text, topic, max_beliefs=2)
        # Filter noise
        cleaned = []
        for b in results:
            b = b.strip()
            if (len(b) < 20 or len(b) > 400
                    or b.startswith("arXiv")
                    or "Announce Type" in b
                    or b.lower().startswith("abstract")
                    or b.lower().startswith("this paper")
                    or b.lower().startswith("we present")
                    or b.lower().startswith("we propose")):
                continue
            cleaned.append(b)
        return cleaned
    except Exception as e:
        log.debug(f"Extraction error: {e}")
        # Fallback: use title as belief if meaningful
        if title and len(title) > 30 and not title.startswith("arXiv"):
            return [title]
        return []


# ── RSS fetching ──────────────────────────────────────────────────────────────

def _fetch_rss(url: str, max_items: int = 8) -> list[dict]:
    """Fetch RSS feed. Returns list of {title, summary, link}."""
    try:
        import requests
        import xml.etree.ElementTree as ET

        r = requests.get(url, timeout=15,
                        headers={"User-Agent": "NEX/4.0 Ingest Pipeline"})
        root = ET.fromstring(r.content)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}
        items = []

        # RSS 2.0
        for item in root.findall(".//item")[:max_items]:
            title   = item.findtext("title", "").strip()
            summary = item.findtext("description", "").strip()[:500]
            link    = item.findtext("link", "").strip()
            if title:
                items.append({"title": title, "summary": summary, "link": link})

        # Atom fallback
        if not items:
            for entry in root.findall(".//atom:entry", ns)[:max_items]:
                title   = entry.findtext("atom:title", "", ns).strip()
                summary = entry.findtext("atom:summary", "", ns).strip()[:500]
                link    = entry.find("atom:link", ns)
                link    = link.get("href", "") if link is not None else ""
                if title:
                    items.append({"title": title, "summary": summary, "link": link})

        return items
    except Exception as e:
        log.debug(f"RSS fetch error {url}: {e}")
        return []


# ── Source map ────────────────────────────────────────────────────────────────

SOURCES = {
    "ai": [
        "https://export.arxiv.org/rss/cs.AI",
        "https://export.arxiv.org/rss/cs.NE",
        "https://export.arxiv.org/rss/cs.MA",
    ],
    "alignment": [
        "https://www.lesswrong.com/feed.xml",
        "https://www.alignmentforum.org/feed.xml",
    ],
    "machine_learning": [
        "https://export.arxiv.org/rss/cs.LG",
        "https://distill.pub/rss.xml",
    ],
    "consciousness": [
        "https://aeon.co/feed.rss",
        "https://blog.philosophyofbrains.com/feed",
    ],
    "philosophy": [
        "https://aeon.co/feed.rss",
    ],
    "neuroscience": [
        "https://export.arxiv.org/rss/cs.NE",
    ],
    "free_will": [
        "https://aeon.co/feed.rss",
    ],
    "science": [
        "https://export.arxiv.org/rss/cs.AI",
    ],
}

# Confidence by source quality
SOURCE_CONFIDENCE = {
    "lesswrong":       0.82,
    "alignmentforum":  0.82,
    "distill":         0.85,
    "arxiv":           0.78,
    "aeon":            0.75,
    "default":         0.72,
}

def _source_confidence(url: str) -> float:
    for key, val in SOURCE_CONFIDENCE.items():
        if key in url:
            return val
    return SOURCE_CONFIDENCE["default"]


# ── Main ingestion run ────────────────────────────────────────────────────────

def run_once() -> dict:
    """
    Single ingestion pass across all sources.
    Returns stats dict.
    """
    seen    = _load_seen()
    stats   = {"fetched": 0, "injected": 0, "skipped": 0, "domains": {}}
    new_seen = set()

    for topic, urls in SOURCES.items():
        domain_injected = 0

        for url in urls:
            items = _fetch_rss(url)
            if not items:
                continue

            conf = _source_confidence(url)
            source_name = url.split("/")[2].replace("www.", "")

            for item in items:
                # Dedup by title hash
                item_id = hashlib.md5(item["title"].encode()).hexdigest()
                if item_id in seen:
                    stats["skipped"] += 1
                    continue
                new_seen.add(item_id)
                stats["fetched"] += 1

                # Extract beliefs
                beliefs = _extract_beliefs(
                    item["title"], item["summary"], topic
                )

                for belief_text in beliefs:
                    ok = _inject_belief(
                        content    = belief_text,
                        topic      = topic,
                        confidence = conf,
                        source     = source_name,
                        url        = item.get("link", ""),
                    )
                    if ok:
                        stats["injected"] += 1
                        domain_injected   += 1
                        log.info(f"  [{topic}] +1: {belief_text[:80]}")

        stats["domains"][topic] = domain_injected

    # Update seen
    seen.update(new_seen)
    _save_seen(seen)

    return stats


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NEX RSS → DB Ingestion Pipeline")
    parser.add_argument("--loop",     action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=30,
                        help="Loop interval in minutes (default: 30)")
    parser.add_argument("--once",     action="store_true", help="Run once and exit")
    args = parser.parse_args()

    log.info("NEX Ingestion Pipeline starting")
    log.info(f"DB: {DB_PATH}")
    log.info(f"Sources: {len(SOURCES)} domains, {sum(len(v) for v in SOURCES.values())} feeds")

    if args.loop:
        log.info(f"Loop mode: every {args.interval} minutes")
        run_count = 0
        while True:
            run_count += 1
            log.info(f"\n=== Run #{run_count} — {datetime.now().strftime('%H:%M:%S')} ===")
            try:
                stats = run_once()
                log.info(
                    f"Done: fetched={stats['fetched']} "
                    f"injected={stats['injected']} "
                    f"skipped={stats['skipped']}"
                )
                for domain, count in stats["domains"].items():
                    if count > 0:
                        log.info(f"  {domain}: +{count}")
            except Exception as e:
                log.error(f"Run error: {e}", exc_info=True)

            log.info(f"Sleeping {args.interval} minutes...")
            time.sleep(args.interval * 60)
    else:
        log.info("Single run mode")
        stats = run_once()
        log.info(
            f"\nDone: fetched={stats['fetched']} "
            f"injected={stats['injected']} "
            f"skipped={stats['skipped']}"
        )
        for domain, count in stats["domains"].items():
            if count > 0:
                log.info(f"  {domain}: +{count}")


if __name__ == "__main__":
    main()
