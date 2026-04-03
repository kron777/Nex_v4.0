#!/usr/bin/env python3
"""
nex_reasoning_cache.py — Stage 1 reasoning cache for NEX v4.0

Sits in front of nex_graph_reasoner.reason() and nex_cot_engine.reason().
On cache hit: returns stored chain in <1ms, zero FAISS, zero LLM.
On cache miss: calls graph reasoner (or LLM fallback), stores result.

Cache key: normalized question hash (lowercase, stripped, punctuation removed)
Cache store: SQLite table in nex.db (no extra files)
Cache invalidation: TTL-based (default 7 days) + manual flush

Usage as drop-in:
    from nex_reasoning_cache import cached_reason
    chain = cached_reason(question, beliefs)

Usage CLI:
    python3 nex_reasoning_cache.py --stats
    python3 nex_reasoning_cache.py --flush
    python3 nex_reasoning_cache.py --flush-older 3      # flush entries > 3 days
    python3 nex_reasoning_cache.py -q "is consciousness computational"
"""

import sqlite3
import hashlib
import re
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta

log     = logging.getLogger("nex.reasoning_cache")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

# ── Config ────────────────────────────────────────────────────────────────────
TTL_DAYS      = 7      # cache entries expire after this many days
MAX_ENTRIES   = 10000  # hard cap — evict LRU beyond this
MIN_CHAIN_LEN = 20     # don't cache empty or trivial chains

# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS reasoning_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    q_hash      TEXT NOT NULL UNIQUE,
    question    TEXT NOT NULL,
    chain       TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'graph',  -- 'graph' or 'llm'
    hit_count   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    last_hit    TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rc_hash    ON reasoning_cache(q_hash);
CREATE INDEX IF NOT EXISTS idx_rc_expires ON reasoning_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_rc_hits    ON reasoning_cache(hit_count DESC);
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(question: str) -> str:
    """Normalize question to a stable cache key."""
    q = question.lower().strip()
    q = re.sub(r"[^\w\s]", "", q)       # strip punctuation
    q = re.sub(r"\s+", " ", q).strip()  # collapse whitespace
    return q


def _hash(normalized: str) -> str:
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.utcnow().isoformat()


def _expires() -> str:
    return (datetime.utcnow() + timedelta(days=TTL_DAYS)).isoformat()


def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.executescript(SCHEMA)
    db.commit()
    return db


# ── Core cache ops ────────────────────────────────────────────────────────────

def cache_get(question: str) -> dict | None:
    """
    Look up a question in the cache.
    Returns dict with 'chain' and 'source' on hit, None on miss/expired.
    """
    norm = _normalize(question)
    key  = _hash(norm)
    now  = _now()

    db  = _get_db()
    row = db.execute(
        "SELECT id, chain, source, hit_count FROM reasoning_cache "
        "WHERE q_hash=? AND expires_at > ?",
        (key, now)
    ).fetchone()

    if not row:
        db.close()
        return None

    rid, chain, source, hit_count = row[0], row[1], row[2], row[3]

    # Update hit stats
    db.execute(
        "UPDATE reasoning_cache SET hit_count=?, last_hit=? WHERE id=?",
        (hit_count + 1, now, rid)
    )
    db.commit()
    db.close()

    log.debug(f"Cache HIT [{key}] hits={hit_count+1}")
    return {"chain": chain, "source": source}


def cache_set(question: str, chain: str, source: str = "graph") -> bool:
    """
    Store a reasoning chain in the cache.
    Returns True if stored, False if skipped (chain too short).
    """
    if not chain or len(chain) < MIN_CHAIN_LEN:
        return False

    norm = _normalize(question)
    key  = _hash(norm)
    now  = _now()
    exp  = _expires()

    db = _get_db()

    # Evict if over cap (remove oldest by last_hit)
    count = db.execute("SELECT COUNT(*) FROM reasoning_cache").fetchone()[0]
    if count >= MAX_ENTRIES:
        db.execute(
            "DELETE FROM reasoning_cache WHERE id IN ("
            "  SELECT id FROM reasoning_cache ORDER BY last_hit ASC LIMIT ?)",
            (count - MAX_ENTRIES + 1,)
        )

    db.execute(
        """INSERT INTO reasoning_cache
           (q_hash, question, chain, source, hit_count, created_at, last_hit, expires_at)
           VALUES (?, ?, ?, ?, 0, ?, ?, ?)
           ON CONFLICT(q_hash) DO UPDATE SET
               chain=excluded.chain,
               source=excluded.source,
               expires_at=excluded.expires_at,
               last_hit=excluded.last_hit""",
        (key, question[:500], chain, source, now, now, exp)
    )
    db.commit()
    db.close()

    log.debug(f"Cache SET [{key}] source={source} len={len(chain)}")
    return True


def cache_flush(older_than_days: int = None):
    """Flush cache. If older_than_days set, only flush entries older than N days."""
    db = _get_db()
    if older_than_days is not None:
        cutoff = (datetime.utcnow() - timedelta(days=older_than_days)).isoformat()
        n = db.execute(
            "DELETE FROM reasoning_cache WHERE created_at < ?", (cutoff,)
        ).rowcount
        db.commit()
        print(f"Flushed {n} entries older than {older_than_days} days")
    else:
        n = db.execute("DELETE FROM reasoning_cache").rowcount
        db.commit()
        print(f"Flushed all {n} cache entries")
    db.close()


def cache_stats() -> dict:
    db  = _get_db()
    now = _now()

    total   = db.execute("SELECT COUNT(*) FROM reasoning_cache").fetchone()[0]
    active  = db.execute("SELECT COUNT(*) FROM reasoning_cache WHERE expires_at > ?", (now,)).fetchone()[0]
    expired = total - active
    hits    = db.execute("SELECT SUM(hit_count) FROM reasoning_cache").fetchone()[0] or 0
    graph_n = db.execute("SELECT COUNT(*) FROM reasoning_cache WHERE source='graph'").fetchone()[0]
    llm_n   = db.execute("SELECT COUNT(*) FROM reasoning_cache WHERE source='llm'").fetchone()[0]

    top = db.execute(
        "SELECT question, hit_count, source FROM reasoning_cache "
        "ORDER BY hit_count DESC LIMIT 5"
    ).fetchall()

    db.close()
    return {
        "total": total, "active": active, "expired": expired,
        "total_hits": hits, "graph_entries": graph_n, "llm_entries": llm_n,
        "top_questions": [{"q": r[0], "hits": r[1], "src": r[2]} for r in top]
    }


# ── Drop-in cached_reason ─────────────────────────────────────────────────────

def cached_reason(question: str, beliefs: list = None,
                  warmth_ctx: dict = None) -> str:
    """
    Drop-in replacement for nex_graph_reasoner.reason() and nex_cot_engine.reason().

    Flow:
      1. Check cache → return immediately on hit
      2. Try graph reasoner with warmth context (0 LLM calls)
      3. Fall back to LLM via nex_cot_engine if graph insufficient
      4. Store result in cache
      5. Return chain
    """
    t0 = time.time()

    # 1. Cache check — skip if warmth signals are strong (warm questions
    #    deserve fresh graph traversal with hot-word boosting)
    hot_ratio = (warmth_ctx or {}).get("hot_ratio", 0.0)
    if hot_ratio < 0.6:
        hit = cache_get(question)
        if hit:
            elapsed = (time.time() - t0) * 1000
            log.info(f"Cache HIT ({elapsed:.1f}ms) src={hit['source']}: {question[:50]}")
            return hit["chain"]

    # 2. Graph reasoner — pass warmth context
    chain  = ""
    source = "graph"
    try:
        from nex_graph_reasoner import reason as graph_reason
        chain = graph_reason(question, beliefs, warmth_ctx=warmth_ctx)
    except Exception as e:
        log.debug(f"Graph reasoner error: {e}")

    # 3. LLM fallback
    if not chain:
        source = "llm"
        try:
            from nex_cot_engine import reason as llm_reason
            chain = llm_reason(question, beliefs or [])
        except Exception as e:
            log.debug(f"LLM fallback error: {e}")

    # 4. Store in cache (only for cold/tepid questions)
    if chain and hot_ratio < 0.6:
        cache_set(question, chain, source)
        elapsed = (time.time() - t0) * 1000
        log.info(f"Cache MISS → {source} ({elapsed:.0f}ms): {question[:50]}")
    elif chain:
        elapsed = (time.time() - t0) * 1000
        log.info(f"Warm MISS → {source} ({elapsed:.0f}ms): {question[:50]}")

    return chain


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NEX reasoning cache — Stage 1")
    parser.add_argument("--stats",        action="store_true", help="Show cache statistics")
    parser.add_argument("--flush",        action="store_true", help="Flush entire cache")
    parser.add_argument("--flush-older",  type=int, metavar="DAYS", help="Flush entries older than N days")
    parser.add_argument("-q", "--question", type=str, help="Test cached_reason with a question")
    args = parser.parse_args()

    if args.stats:
        s = cache_stats()
        print(f"\n{'═'*50}")
        print(f"  Reasoning Cache Stats")
        print(f"{'═'*50}")
        print(f"  Total entries : {s['total']}")
        print(f"  Active        : {s['active']}")
        print(f"  Expired       : {s['expired']}")
        print(f"  Total hits    : {s['total_hits']}")
        print(f"  Graph entries : {s['graph_entries']}")
        print(f"  LLM entries   : {s['llm_entries']}")
        if s["top_questions"]:
            print(f"\n  Top questions:")
            for t in s["top_questions"]:
                print(f"    [{t['hits']} hits] ({t['src']}) {t['q'][:60]}")
        print(f"{'═'*50}\n")
        return

    if args.flush:
        cache_flush()
        return

    if args.flush_older:
        cache_flush(older_than_days=args.flush_older)
        return

    if args.question:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        print(f"\nQuestion: {args.question}")
        print(f"{'─'*50}")
        t0    = time.time()
        chain = cached_reason(args.question)
        elapsed = (time.time() - t0) * 1000
        if chain:
            print(chain)
            print(f"\n[{elapsed:.1f}ms]")
        else:
            print("No chain returned.")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
