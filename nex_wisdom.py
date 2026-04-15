#!/usr/bin/env python3
"""
nex_wisdom.py — U6 Wisdom Layer
Distills NEX's conversation history and reflexion_log into durable wisdom entries.
Runs as part of nightly consolidation (Phase 7b) or standalone.

Wisdom = third-person reflection on first-person experience (Grossmann 2020).
Each wisdom entry is injected into soul_loop REASON as TIER_1 (source=nex_core).
"""
import sqlite3, json, time, logging, requests
from pathlib import Path

DB_PATH   = Path("/media/rr/NEX/nex_core/nex.db")
LLM_URL   = "http://localhost:8080/v1/completions"
LOG       = logging.getLogger("nex.wisdom")

WISDOM_PROMPT = """You are helping NEX, an autonomous AI, distil durable wisdom from her experiences.

NEX's recent exchanges and reflections:
{exchanges}

Based on these experiences, what is ONE durable principle NEX has learned?
- Must be in first person ("I have learned...", "I now hold that...", "My experience shows...")
- Must be specific to these exchanges, not generic
- Must be actionable or belief-shaping
- 1-2 sentences only
- Do NOT start with "As an AI" or "I am an AI"

Wisdom principle:"""


def _db():
    db = sqlite3.connect(str(DB_PATH), timeout=5)
    db.row_factory = sqlite3.Row
    return db


def _ensure_table(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS nex_wisdom (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            principle   TEXT NOT NULL,
            source_type TEXT DEFAULT 'reflexion',
            confidence  REAL DEFAULT 0.85,
            use_count   INTEGER DEFAULT 0,
            created_at  REAL DEFAULT (unixepoch('now')),
            last_used   REAL
        )
    """)
    db.commit()


def _get_recent_exchanges(db, limit=10) -> list:
    """Fetch recent reflexion_log entries as exchange summaries."""
    rows = db.execute(
        "SELECT response, user_input, timestamp FROM reflexion_log "
        "ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    exchanges = []
    for r in rows:
        q = (r['user_input'] or '').strip()[:120]
        a = (r['response'] or '').strip()[:200]
        if q and a:
            exchanges.append(f"Q: {q}\nA: {a}")
    return exchanges


def _call_llm(prompt: str) -> str:
    try:
        r = requests.post(LLM_URL, json={
            "prompt": prompt,
            "max_tokens": 80,
            "temperature": 0.7,
            "stop": ["\n\n", "Q:", "Based on"]
        }, timeout=30)
        if r.status_code == 200:
            text = r.json().get('choices', [{}])[0].get('text', '').strip()
            # Clean up
            for bad in ['As an AI', 'I am an AI', 'As a language model']:
                if bad.lower() in text.lower():
                    return ''
            return text
    except Exception as e:
        LOG.debug(f"LLM call failed: {e}")
    return ''


def _already_have(db, principle: str) -> bool:
    """Check for near-duplicate wisdom."""
    words = set(principle.lower().split())
    rows = db.execute("SELECT principle FROM nex_wisdom").fetchall()
    for r in rows:
        existing_words = set(r['principle'].lower().split())
        overlap = len(words & existing_words) / max(len(words), 1)
        if overlap > 0.6:
            return True
    return False


def inject_wisdom_into_beliefs(db, wisdom_ids: list):
    """Tag new wisdom entries as nex_core beliefs so soul_loop finds them."""
    for wid in wisdom_ids:
        row = db.execute("SELECT principle FROM nex_wisdom WHERE id=?", (wid,)).fetchone()
        if not row:
            continue
        # Check not already in beliefs
        existing = db.execute(
            "SELECT id FROM beliefs WHERE content=?", (row['principle'],)
        ).fetchone()
        if existing:
            continue
        db.execute("""
            INSERT INTO beliefs (content, confidence, source, topic, locked, momentum)
            VALUES (?, 0.92, 'nex_core', 'wisdom', 1, 1.0)
        """, (row['principle'],))
    db.commit()


def run_wisdom_distillation(verbose=True) -> int:
    """
    Main entry point. Call from nightly consolidation or standalone.
    Returns number of new wisdom entries created.
    """
    db = _db()
    _ensure_table(db)

    exchanges = _get_recent_exchanges(db, limit=15)
    if len(exchanges) < 3:
        if verbose:
            print(f"[wisdom] insufficient exchanges ({len(exchanges)}) — skipping")
        db.close()
        return 0

    if verbose:
        print(f"[wisdom] distilling from {len(exchanges)} exchanges...")

    # Process in clusters of 5
    new_ids = []
    for i in range(0, len(exchanges), 5):
        cluster = exchanges[i:i+5]
        if not cluster:
            continue
        prompt = WISDOM_PROMPT.format(exchanges='\n\n'.join(cluster))
        principle = _call_llm(prompt)
        if not principle or len(principle) < 20:
            continue
        if _already_have(db, principle):
            if verbose:
                print(f"[wisdom] duplicate skipped: {principle[:60]}")
            continue
        db.execute(
            "INSERT INTO nex_wisdom (principle, source_type, confidence) VALUES (?,?,?)",
            (principle, 'reflexion_cluster', 0.88)
        )
        db.commit()
        last_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        new_ids.append(last_id)
        if not _is_good_wisdom(principle):
            if verbose:
                print(f"[wisdom] filtered: {principle[:60]}")
            continue
        if verbose:
            print(f"[wisdom] new: {principle[:100]}")

    # Inject into beliefs as nex_core
    if new_ids:
        inject_wisdom_into_beliefs(db, new_ids)
        if verbose:
            print(f"[wisdom] ✓ {len(new_ids)} wisdom entries injected as nex_core beliefs")

    total = db.execute("SELECT COUNT(*) FROM nex_wisdom").fetchone()[0]
    if verbose:
        print(f"[wisdom] total wisdom entries: {total}")

    db.close()
    return len(new_ids)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = run_wisdom_distillation(verbose=True)
    print(f"\nResult: {n} new wisdom entries")
