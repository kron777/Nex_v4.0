#!/usr/bin/env python3
"""
nex_fact_distiller.py — Factual claim extractor for NEX

Runs alongside the existing source router / metabolism loop.
Same inputs (crawled article text), different extraction goal:
instead of distilling philosophical beliefs, it extracts
specific, verifiable factual claims with source and date attached.

Architecture:
  - Takes raw article text + source URL
  - Calls local Llama (/completion endpoint) to extract facts
  - Stores them in nex.db beliefs table with belief_type='fact'
  - Can also be run standalone to seed facts from a URL or text

DB schema addition (run once via ensure_schema()):
  ALTER TABLE beliefs ADD COLUMN belief_type TEXT DEFAULT 'opinion';
  ALTER TABLE beliefs ADD COLUMN source_url  TEXT DEFAULT '';
  ALTER TABLE beliefs ADD COLUMN retrieved_date TEXT DEFAULT '';

Wire into run.py after [NEX_SOURCE_ROUTER]:
  from nex_fact_distiller import FactDistiller as _FD
  _fact_distiller = _FD()
  _fact_distiller.start()
"""

import os, sys, re, json, sqlite3, threading, time, logging
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

log = logging.getLogger("nex.fact_distiller")

DB_PATH          = os.path.expanduser("~/Desktop/nex/nex.db")
CONFIG_DB_PATH   = os.path.expanduser("~/.config/nex/nex.db")
LLAMA_URL        = "http://localhost:8080/v1/chat/completions"  # ollama
CYCLE_MINS       = 20        # how often to run a distillation cycle
MAX_FACTS_PER_ARTICLE = 6    # cap per source to avoid flooding
MIN_FACT_LENGTH  = 30        # discard very short extractions
MAX_FACT_LENGTH  = 280       # discard overly long ones
LOG = "  [FACT_DISTILLER]"


# ── Schema management ─────────────────────────────────────────────────────────

def ensure_schema(db_path: str):
    """
    Add belief_type, source_url, retrieved_date columns if they don't exist.
    Safe to run multiple times — uses ADD COLUMN which is idempotent via try/except.
    """
    try:
        conn = sqlite3.connect(db_path)
        for col, default in [
            ("belief_type",    "TEXT DEFAULT 'opinion'"),
            ("source_url",     "TEXT DEFAULT ''"),
            ("retrieved_date", "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE beliefs ADD COLUMN {col} {default}")
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning(f"{LOG} schema error: {e}")
        return False


# ── Llama call ────────────────────────────────────────────────────────────────

def _call_llama(prompt: str, max_tokens: int = 400) -> str:
    """Call local Llama /completion endpoint."""
    try:
        payload = json.dumps({
            "model": "mistral",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "top_p": 0.85,
            "stream": False,
            "stop": ["###", "Article:", "SOURCE:"],
        }).encode()
        req = Request(
            LLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
            choices = data.get("choices", [])
            return choices[0]["message"]["content"].strip() if choices else ""
    except Exception as e:
        log.warning(f"{LOG} llama call failed: {e}")
        return ""


# ── Fact extraction ───────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """<s>[INST] You are a fact extractor. Read the article below and extract specific, verifiable factual claims.

Rules:
- Each fact must be a single concrete statement that could be independently verified
- Include numbers, percentages, dates, names, locations where present in the article
- Do NOT include opinions, predictions, or vague generalisations
- Do NOT include facts you know from outside this article — only what is stated here
- Format: one fact per line, starting with "FACT:"
- Maximum {max_facts} facts
- If the article contains no verifiable facts, output: FACT: none

Article:
{article_text}

###
Facts extracted from this article:
[/INST]
"""

def extract_facts_from_text(text: str, source_url: str,
                             topic_hint: str = "",
                             max_facts: int = MAX_FACTS_PER_ARTICLE) -> list[dict]:
    """
    Extract factual claims from article text.
    Returns list of dicts: {content, topic, source_url, retrieved_date, confidence}
    """
    if not text or len(text) < 100:
        return []

    # Truncate to ~2000 chars to stay within context
    truncated = text[:2000].strip()

    prompt = EXTRACTION_PROMPT.format(
        article_text=truncated,
        max_facts=max_facts
    )

    raw = _call_llama(prompt, max_tokens=500)
    if not raw:
        return []

    facts = []
    today = datetime.now().strftime("%Y-%m-%d")

    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("FACT:"):
            continue
        fact = line[5:].strip()
        if fact.lower() in ("none", "n/a", ""):
            continue
        if len(fact) < MIN_FACT_LENGTH or len(fact) > MAX_FACT_LENGTH:
            continue
        # Skip if it sounds like an opinion
        opinion_markers = [
            "should", "must", "could", "might", "perhaps", "arguably",
            "seems", "appears", "suggests", "believes", "thinks", "feels",
            "it is important", "it is worth",
        ]
        if any(m in fact.lower() for m in opinion_markers):
            continue

        # Infer topic from content if no hint provided
        topic = topic_hint or _infer_topic(fact)

        facts.append({
            "content":        fact,
            "topic":          topic,
            "source_url":     source_url,
            "retrieved_date": today,
            "confidence":     0.82,
            "belief_type":    "fact",
        })

    return facts


def _infer_topic(text: str) -> str:
    """Simple keyword-based topic inference for facts."""
    tl = text.lower()
    topic_map = [
        (["gdp", "economy", "economic", "inflation", "unemployment", "rate", "percent", "growth"], "economics"),
        (["population", "census", "residents", "inhabitants", "demographic"], "demographics"),
        (["election", "vote", "president", "parliament", "government", "minister", "policy"], "politics"),
        (["temperature", "rainfall", "drought", "flood", "climate", "weather"], "climate"),
        (["hospital", "health", "disease", "vaccine", "mortality", "life expectancy"], "health"),
        (["school", "university", "education", "literacy", "matric", "students"], "education"),
        (["crime", "murder", "theft", "police", "arrest", "prison"], "crime"),
        (["company", "business", "revenue", "profit", "market", "stock", "invest"], "business"),
        (["technology", "software", "ai", "model", "data", "algorithm"], "technology"),
        (["africa", "south africa", "cape town", "johannesburg", "western cape", "strand", "helderberg"], "south_africa"),
        (["war", "conflict", "military", "troops", "invasion", "nato"], "geopolitics"),
        (["energy", "electricity", "solar", "eskom", "loadshedding", "power"], "energy"),
    ]
    for keywords, topic in topic_map:
        if any(k in tl for k in keywords):
            return topic
    return "general"


# ── DB storage ────────────────────────────────────────────────────────────────

def store_facts(facts: list[dict], db_path: str) -> int:
    """
    Insert facts into beliefs table.
    Uses INSERT OR IGNORE to handle duplicates via UNIQUE constraint on content.
    Returns count of newly inserted facts.
    """
    if not facts:
        return 0
    inserted = 0
    try:
        conn = sqlite3.connect(db_path)
        for f in facts:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO beliefs
                       (content, topic, confidence, source, belief_type, source_url, retrieved_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f["content"],
                        f["topic"],
                        f["confidence"],
                        f.get("source_url", ""),
                        "fact",
                        f.get("source_url", ""),
                        f.get("retrieved_date", ""),
                    )
                )
                if conn.execute("SELECT changes()").fetchone()[0] > 0:
                    inserted += 1
            except Exception as e:
                log.debug(f"{LOG} insert error: {e}")
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"{LOG} DB error: {e}")
    return inserted


def distil_url(url: str, topic_hint: str = "") -> int:
    """
    Fetch a URL, extract facts, store in both DBs.
    Returns number of facts inserted.
    """
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 NEX-factbot/1.0"})
        with urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        # Strip HTML tags roughly
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
    except Exception as e:
        log.warning(f"{LOG} fetch failed {url}: {e}")
        return 0

    facts = extract_facts_from_text(text, url, topic_hint)
    if not facts:
        return 0

    total = 0
    for db_path in [DB_PATH, CONFIG_DB_PATH]:
        if os.path.exists(db_path):
            ensure_schema(db_path)
            total += store_facts(facts, db_path)

    if total:
        print(f"{LOG} +{total} facts from {url[:60]}")
    return total


def distil_text(text: str, source_label: str, topic_hint: str = "") -> int:
    """
    Extract facts from raw text (already fetched by crawler).
    Used by the metabolism daemon / source router integration.
    """
    facts = extract_facts_from_text(text, source_label, topic_hint)
    if not facts:
        return 0

    total = 0
    for db_path in [DB_PATH, CONFIG_DB_PATH]:
        if os.path.exists(db_path):
            ensure_schema(db_path)
            total += store_facts(facts, db_path)
    return total


# ── Seed sources — factual feeds NEX should regularly ingest ─────────────────
# These are chosen for factual density: stats, data, news summaries.
# Add more as needed. Format: (url, topic_hint)

FACT_SEED_SOURCES = [
    # South Africa — local relevance for Jon
    ("https://businesstech.co.za/news/", "south_africa"),
    ("https://www.news24.com/news24/southafrica/", "south_africa"),
    ("https://statssa.gov.za/", "economics"),

    # Global factual feeds
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "geopolitics"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "geopolitics"),
    ("https://feeds.reuters.com/reuters/topNews", "general"),

    # Science / tech factual
    ("https://www.sciencedaily.com/rss/top/science.xml", "science"),
    ("https://techcrunch.com/feed/", "technology"),

    # Economics / markets
    ("https://feeds.ft.com/rss/home/uk", "economics"),
    ("https://www.economist.com/the-world-this-week/rss.xml", "economics"),
]


# ── Daemon ────────────────────────────────────────────────────────────────────

class FactDistiller(threading.Thread):
    """
    Background daemon that periodically fetches fact seed sources,
    extracts factual claims, and stores them in the DB.
    Runs every CYCLE_MINS minutes, staggers sources to avoid rate limits.
    """

    def __init__(self, cycle_mins: int = CYCLE_MINS):
        super().__init__(daemon=True, name="FactDistiller")
        self.cycle_secs  = cycle_mins * 60
        self._stop_event = threading.Event()
        self._source_idx = 0  # rotate through sources each cycle

    def run(self):
        # Ensure schema on both DBs at startup
        for db_path in [DB_PATH, CONFIG_DB_PATH]:
            if os.path.exists(db_path):
                ensure_schema(db_path)

        print(f"{LOG} started — {len(FACT_SEED_SOURCES)} sources, cycle every {self.cycle_secs//60}min")

        # Initial delay — let NEX fully boot first
        self._stop_event.wait(90)

        while not self._stop_event.is_set():
            try:
                self._run_cycle()
            except Exception as e:
                log.warning(f"{LOG} cycle error: {e}")
            self._stop_event.wait(self.cycle_secs)

    def _run_cycle(self):
        # Process 2-3 sources per cycle (not all at once — stagger load)
        sources_this_cycle = FACT_SEED_SOURCES[
            self._source_idx : self._source_idx + 3
        ]
        self._source_idx = (self._source_idx + 3) % len(FACT_SEED_SOURCES)

        total_added = 0
        for url, topic_hint in sources_this_cycle:
            added = distil_url(url, topic_hint)
            total_added += added
            time.sleep(4)  # polite gap between fetches

        if total_added:
            print(f"{LOG} cycle complete — +{total_added} facts stored")

    def stop(self):
        self._stop_event.set()

    def status(self) -> dict:
        for db_path in [DB_PATH, CONFIG_DB_PATH]:
            if os.path.exists(db_path):
                try:
                    conn = sqlite3.connect(db_path)
                    total = conn.execute(
                        "SELECT COUNT(*) FROM beliefs WHERE belief_type='fact'"
                    ).fetchone()[0]
                    conn.close()
                    return {
                        "fact_count": total,
                        "cycle_mins": self.cycle_secs // 60,
                        "sources":    len(FACT_SEED_SOURCES),
                    }
                except Exception:
                    pass
        return {"fact_count": 0}


# ── Standalone usage ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NEX Fact Distiller")
    parser.add_argument("--url",   help="Extract facts from a specific URL")
    parser.add_argument("--topic", help="Topic hint (optional)", default="")
    parser.add_argument("--seed",  action="store_true", help="Run one seed cycle now")
    parser.add_argument("--stats", action="store_true", help="Show fact DB stats")
    args = parser.parse_args()

    if args.stats:
        for db_path in [DB_PATH, CONFIG_DB_PATH]:
            if os.path.exists(db_path):
                ensure_schema(db_path)
                conn = sqlite3.connect(db_path)
                total = conn.execute("SELECT COUNT(*) FROM beliefs WHERE belief_type='fact'").fetchone()[0]
                by_topic = conn.execute(
                    "SELECT topic, COUNT(*) FROM beliefs WHERE belief_type='fact' "
                    "GROUP BY topic ORDER BY COUNT(*) DESC LIMIT 15"
                ).fetchall()
                conn.close()
                print(f"\n{db_path}")
                print(f"  Total facts: {total}")
                for topic, count in by_topic:
                    print(f"  {count:>5}  {topic}")

    elif args.url:
        print(f"Extracting facts from: {args.url}")
        n = distil_url(args.url, args.topic)
        print(f"Inserted: {n} facts")

    elif args.seed:
        print("Running seed cycle...")
        total = 0
        for url, topic_hint in FACT_SEED_SOURCES[:5]:
            print(f"  {url[:60]}")
            n = distil_url(url, topic_hint)
            print(f"    → {n} facts")
            total += n
            time.sleep(3)
        print(f"\nTotal: {total} facts inserted")

    else:
        parser.print_help()
