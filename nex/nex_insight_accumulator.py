#!/usr/bin/env python3
"""
nex_insight_accumulator.py — Insight Accumulator
=================================================
Flags and preserves NEX's moments of genuine synthesis —
when cross-domain connections produce something genuinely novel.

An insight is flagged when:
  - Common thread synthesis fires AND
  - Cross-domain connection is present AND
  - Reply quality score > 0.7 AND
  - The synthesised claim is not already in beliefs

Insights are stored in a dedicated table and:
  - Fed back into the belief corpus at higher confidence (0.85)
  - Used to seed training pairs (highest quality)
  - Logged for review

Deploy to: ~/Desktop/nex/nex/nex_insight_accumulator.py
"""

import re, json, time, sqlite3, hashlib
from pathlib import Path

DB_PATH    = Path("~/.config/nex/nex.db").expanduser()
PAIRS_PATH = Path("~/.config/nex/training_pairs.jsonl").expanduser()

_STOP = {'the','a','an','and','or','is','are','was','in','of','to','for',
         'with','as','by','from','this','that','it','its','not','but'}

def _tok(text):
    return set(re.sub(r'[^a-z0-9 ]',' ',text.lower()).split()) - _STOP

def _db():
    con = sqlite3.connect(str(DB_PATH), timeout=10)
    con.row_factory = sqlite3.Row
    return con

def _ensure_table():
    con = _db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS nex_insights (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            query        TEXT,
            reply        TEXT,
            common_thread TEXT,
            cross_domain  TEXT,
            quality_score REAL,
            hash         TEXT UNIQUE,
            created_at   REAL,
            promoted     INTEGER DEFAULT 0
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_insights_quality ON nex_insights(quality_score DESC)")
    con.commit()
    con.close()


# ─────────────────────────────────────────────────────────────
# Insight detection
# ─────────────────────────────────────────────────────────────

_INSIGHT_SIGNALS = {
    'what all of this points toward',
    'the centrality of',
    'what makes this harder to dismiss',
    'an unexpected implication',
    'what connects all of this',
    'the thread running through',
}

_QUALITY_SIGNALS = {
    'lean','hold','argue','position','skeptical','convinced',
    'because','therefore','implies','evidence','contradicts',
    'tension','however','although','despite',
}

def score_insight(query, reply, has_thread, has_cross_domain):
    """Score whether a reply represents a genuine insight."""
    if not reply or len(reply) < 100:
        return 0.0

    t     = reply.lower()
    words = set(re.sub(r'[^a-z ]','',t).split())

    # Check for synthesis markers
    has_synthesis = any(signal in t for signal in _INSIGHT_SIGNALS)
    quality_hits  = len(words & _QUALITY_SIGNALS)
    sents         = len(re.split(r'(?<=[.!?])\s+', reply))

    score = 0.0
    if has_thread:       score += 0.3
    if has_cross_domain: score += 0.2
    if has_synthesis:    score += 0.3
    score += min(quality_hits / 6.0, 0.2)

    return round(score, 3)


def accumulate_insight(
    query:        str,
    reply:        str,
    common_thread: str = "",
    cross_domain:  list = None,
    quality_score: float = 0.0,
) -> bool:
    """
    Evaluate and store a potential insight.
    Returns True if stored as genuine insight.
    """
    has_thread       = bool(common_thread and len(common_thread) > 20)
    has_cross_domain = bool(cross_domain and len(cross_domain) > 0)

    score = score_insight(query, reply, has_thread, has_cross_domain)
    if score < 0.5:
        return False

    # Dedup by content hash
    content_hash = hashlib.md5((query + reply).encode()).hexdigest()[:16]

    try:
        con = _db()
        con.execute(
            "INSERT OR IGNORE INTO nex_insights "
            "(query, reply, common_thread, cross_domain, quality_score, hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                query[:300],
                reply[:1000],
                common_thread[:300] if common_thread else "",
                json.dumps([b.get("content","")[:100] for b in (cross_domain or [])][:3]),
                score,
                content_hash,
                time.time(),
            )
        )
        stored = con.execute("SELECT changes()").fetchone()[0]
        con.commit()

        # If genuinely new and high quality — promote to belief corpus
        if stored and score >= 0.7:
            _promote_to_beliefs(con, common_thread, reply, score)

        con.close()
        return bool(stored)
    except Exception:
        return False


def _promote_to_beliefs(con, common_thread, reply, score):
    """Promote high-quality insight claims to the belief corpus."""
    # Extract the synthesised claim
    claim = ""
    if common_thread and len(common_thread) > 20:
        claim = common_thread
    else:
        # Extract from reply — look for synthesis markers
        for signal in _INSIGHT_SIGNALS:
            if signal in reply.lower():
                idx   = reply.lower().find(signal)
                claim = reply[idx:idx+200].split('.')[0] + '.'
                break

    if not claim or len(claim) < 30:
        return

    try:
        con.execute(
            "INSERT OR IGNORE INTO beliefs (content, confidence, topic, source, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (claim.strip(), min(0.85, 0.65 + score * 0.3), "synthesis", "insight_accumulator", time.time())
        )
    except Exception:
        pass


def get_top_insights(limit=10) -> list:
    """Get NEX's best insights for review."""
    con = _db()
    try:
        rows = con.execute(
            "SELECT query, reply, common_thread, quality_score, created_at "
            "FROM nex_insights ORDER BY quality_score DESC LIMIT ?",
            (limit,)
        ).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception:
        con.close()
        return []


def promote_to_training_pairs(min_score=0.7):
    """Add top insights to training pairs for LoRA."""
    insights = get_top_insights(limit=50)
    added    = 0
    existing = set()

    if PAIRS_PATH.exists():
        for line in PAIRS_PATH.read_text().splitlines():
            try:
                p = json.loads(line)
                existing.add(p.get("prompt","")[:80])
            except Exception:
                pass

    with open(PAIRS_PATH, 'a', encoding='utf-8') as f:
        for ins in insights:
            if ins["quality_score"] < min_score:
                continue
            key = ins["query"][:80]
            if key in existing:
                continue
            existing.add(key)
            pair = {
                "prompt":   ins["query"],
                "response": ins["reply"],
                "quality":  ins["quality_score"],
                "source":   "insight",
            }
            f.write(json.dumps(pair, ensure_ascii=False) + '\n')
            added += 1

    return added


_ensure_table()


if __name__ == "__main__":
    print("=== NEX INSIGHT ACCUMULATOR ===")
    con = _db()
    try:
        count = con.execute("SELECT COUNT(*) FROM nex_insights").fetchone()[0]
        top_q = con.execute("SELECT AVG(quality_score) FROM nex_insights").fetchone()[0] or 0
        con.close()
        print(f"Stored insights: {count}")
        print(f"Avg quality:     {top_q:.3f}")

        insights = get_top_insights(5)
        if insights:
            print(f"\nTop insights:")
            for ins in insights:
                print(f"  [{ins['quality_score']:.2f}] {ins['query'][:60]}")
                if ins.get("common_thread"):
                    print(f"    → {ins['common_thread'][:80]}")

        n = promote_to_training_pairs()
        print(f"\nPromoted {n} insights to training pairs")
    except Exception as e:
        print(f"Error: {e}")
        con.close()
