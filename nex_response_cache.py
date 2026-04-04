#!/usr/bin/env python3
"""
nex_response_cache.py
Belief Fingerprint Response Cache.

Caches LLM responses keyed to belief activation fingerprints.
Same belief cluster = same cached response. Zero LLM calls on hit.

Fingerprint: sorted tuple of top-8 activated belief IDs + query prefix.
Hit rate improves over time as NEX gets asked familiar questions.
Expected: 30-40% hit rate within weeks of usage.
"""
import sqlite3, json, hashlib, time, logging
from pathlib import Path

log     = logging.getLogger("nex.cache")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

MAX_AGE_DAYS   = 14
MAX_CACHE_SIZE = 5000
MIN_RESPONSE_LEN = 20


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS response_cache (
        fingerprint  TEXT PRIMARY KEY,
        query        TEXT,
        response     TEXT,
        hit_count    INTEGER DEFAULT 0,
        created_at   REAL,
        last_hit     REAL,
        source       TEXT
    )""")
    db.commit()


def _fingerprint(activated_ids: list, query: str = "") -> str:
    top_ids = sorted(activated_ids)[:8]
    query_prefix = " ".join(query.lower().split()[:3])
    key = f"{query_prefix}:{json.dumps(top_ids)}"
    return hashlib.md5(key.encode()).hexdigest()


def get(fingerprint: str, db=None):
    close = False
    if db is None:
        db = sqlite3.connect(str(DB_PATH))
        close = True
    ensure_schema(db)
    cutoff = time.time() - (MAX_AGE_DAYS * 86400)
    row = db.execute(
        "SELECT response FROM response_cache WHERE fingerprint=? AND created_at >= ?",
        (fingerprint, cutoff)).fetchone()
    if row:
        db.execute(
            "UPDATE response_cache SET hit_count=hit_count+1, last_hit=? WHERE fingerprint=?",
            (time.time(), fingerprint))
        db.commit()
        log.debug(f"Cache HIT: {fingerprint[:8]}")
        if close: db.close()
        return row[0]
    if close: db.close()
    return None


def put(fingerprint: str, query: str, response: str, source: str = "llm", db=None):
    if not response or len(response.split()) < MIN_RESPONSE_LEN:
        return
    close = False
    if db is None:
        db = sqlite3.connect(str(DB_PATH))
        close = True
    ensure_schema(db)
    count = db.execute("SELECT COUNT(*) FROM response_cache").fetchone()[0]
    if count >= MAX_CACHE_SIZE:
        db.execute("""DELETE FROM response_cache WHERE fingerprint IN (
            SELECT fingerprint FROM response_cache
            ORDER BY hit_count ASC, last_hit ASC LIMIT 100)""")
    try:
        db.execute("""INSERT OR REPLACE INTO response_cache
            (fingerprint, query, response, hit_count, created_at, last_hit, source)
            VALUES (?,?,?,0,?,?,?)""",
            (fingerprint, query[:200], response, time.time(), time.time(), source))
        db.commit()
        log.debug(f"Cache PUT: {fingerprint[:8]} ({source})")
    except Exception as e:
        log.debug(f"Cache PUT failed: {e}")
    if close: db.close()


def invalidate(db=None):
    close = False
    if db is None:
        db = sqlite3.connect(str(DB_PATH))
        close = True
    ensure_schema(db)
    cutoff = time.time() - (MAX_AGE_DAYS * 86400)
    n = db.execute("DELETE FROM response_cache WHERE created_at < ?", (cutoff,)).rowcount
    db.commit()
    if close: db.close()
    return n


def stats(db=None) -> dict:
    close = False
    if db is None:
        db = sqlite3.connect(str(DB_PATH))
        close = True
    ensure_schema(db)
    total = db.execute("SELECT COUNT(*) FROM response_cache").fetchone()[0]
    hits  = db.execute("SELECT SUM(hit_count) FROM response_cache").fetchone()[0] or 0
    top   = db.execute(
        "SELECT query, hit_count FROM response_cache ORDER BY hit_count DESC LIMIT 5"
    ).fetchall()
    if close: db.close()
    return {"total_entries": total, "total_hits": hits, "top_queries": top}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()
    if args.stats:
        s = stats()
        print(f"Cache entries: {s['total_entries']}")
        print(f"Total hits:    {s['total_hits']}")
        print("Top queries:")
        for q, n in s['top_queries']:
            print(f"  {n:4}x {q[:60]}")
    if args.clear:
        db = sqlite3.connect(str(DB_PATH))
        db.execute("DELETE FROM response_cache")
        db.commit()
        db.close()
        print("Cache cleared")
