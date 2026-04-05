#!/usr/bin/env python3
"""
nex_feedback_loop.py — Conversation Feedback Loop
===================================================
After each API exchange:
1. Boost confidence of beliefs that were activated and led to a good response
2. Extract new beliefs from compiler-routed responses (high quality)
3. Penalise beliefs involved in contradictions

Usage: called from nex_api.py after each chat response.
Also runnable standalone: python3 nex_feedback_loop.py --stats
"""

import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timezone

DB = Path.home() / "Desktop/nex/nex.db"

# ── confidence update params ────────────────────────────────────────────────
BOOST_AMOUNT    = 0.005   # per use — small, compounds over time
PENALTY_AMOUNT  = 0.010   # per contradiction
MAX_CONFIDENCE  = 0.98
MIN_CONFIDENCE  = 0.20
BOOST_CAP       = 0.80    # don't boost above this automatically


def boost_activated_beliefs(belief_ids: list, amount: float = BOOST_AMOUNT):
    """Slightly increase confidence of beliefs that were used in a response."""
    if not belief_ids:
        return 0
    db = sqlite3.connect(str(DB))
    updated = 0
    for bid in belief_ids:
        try:
            db.execute("""
                UPDATE beliefs SET confidence = MIN(?, confidence + ?)
                WHERE id = ? AND confidence < ?
            """, (MAX_CONFIDENCE, amount, bid, BOOST_CAP))
            if db.execute("SELECT changes()").fetchone()[0]:
                updated += 1
        except Exception:
            pass
    db.commit()
    db.close()
    return updated


def penalise_contradiction_beliefs(belief_ids: list, amount: float = PENALTY_AMOUNT):
    """Reduce confidence of beliefs involved in contradictions."""
    if not belief_ids:
        return 0
    db = sqlite3.connect(str(DB))
    updated = 0
    for bid in belief_ids:
        try:
            db.execute("""
                UPDATE beliefs SET confidence = MAX(?, confidence - ?)
                WHERE id = ?
            """, (MIN_CONFIDENCE, amount, bid))
            if db.execute("SELECT changes()").fetchone()[0]:
                updated += 1
        except Exception:
            pass
    db.commit()
    db.close()
    return updated


def extract_and_store_from_response(
    response: str,
    query: str,
    topic: str,
    source: str = "compiler"
) -> int:
    """
    Extract new beliefs from a high-quality compiler response.
    Only called when route == 'compiler' — LLM responses are too noisy.
    """
    if not response or len(response.split()) < 5:
        return 0
    try:
        from nex_conversation_extractor import store_conversation_beliefs
        return store_conversation_beliefs(response, query=query, topic=topic)
    except Exception:
        return 0


def record_exchange(
    query: str,
    response: str,
    route: str,           # 'compiler' | 'cache' | 'llm'
    activated_ids: list,  # belief IDs that were activated
    topic: str = "",
    had_contradiction: bool = False,
    contradiction_ids: list = None,
):
    """
    Main entry point — call after each API response.
    
    Args:
        query: user query
        response: NEX response
        route: how the response was generated
        activated_ids: belief IDs that were activated
        topic: domain/topic of the exchange
        had_contradiction: whether contradictions were detected
        contradiction_ids: belief IDs involved in contradictions
    """
    boosted = 0
    penalised = 0
    extracted = 0

    # 1. Boost activated beliefs (all routes)
    if activated_ids:
        boosted = boost_activated_beliefs(activated_ids)

    # 2. Penalise contradiction beliefs
    if had_contradiction and contradiction_ids:
        penalised = penalise_contradiction_beliefs(contradiction_ids)

    # 3. Extract from compiler responses only
    if route == "compiler" and response and len(response.split()) >= 8:
        extracted = extract_and_store_from_response(response, query, topic)

    # 4. Log to DB
    try:
        db = sqlite3.connect(str(DB))
        db.execute("""
            CREATE TABLE IF NOT EXISTS feedback_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                query TEXT,
                route TEXT,
                topic TEXT,
                activated_count INTEGER,
                boosted INTEGER,
                penalised INTEGER,
                extracted INTEGER,
                had_contradiction INTEGER
            )
        """)
        db.execute("""
            INSERT INTO feedback_log
            (ts, query, route, topic, activated_count, boosted, penalised, extracted, had_contradiction)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            query[:200],
            route,
            topic,
            len(activated_ids) if activated_ids else 0,
            boosted,
            penalised,
            extracted,
            1 if had_contradiction else 0,
        ))
        db.commit()
        db.close()
    except Exception:
        pass

    return {"boosted": boosted, "penalised": penalised, "extracted": extracted}


def stats():
    """Print feedback loop statistics."""
    db = sqlite3.connect(str(DB))
    try:
        total = db.execute("SELECT COUNT(*) FROM feedback_log").fetchone()[0]
        by_route = db.execute("""
            SELECT route, COUNT(*), SUM(boosted), SUM(extracted)
            FROM feedback_log GROUP BY route
        """).fetchall()
        recent = db.execute("""
            SELECT ts, query, route, boosted, extracted
            FROM feedback_log ORDER BY id DESC LIMIT 10
        """).fetchall()

        print(f"\nFEEDBACK LOOP STATS — {total} exchanges logged")
        print(f"{'Route':<12} {'Count':>6} {'Boosts':>8} {'Extracted':>10}")
        print("-" * 40)
        for route, count, boosts, extracted in by_route:
            print(f"{route:<12} {count:>6} {boosts or 0:>8} {extracted or 0:>10}")

        print(f"\nRecent exchanges:")
        for ts, query, route, boosted, extracted in recent:
            print(f"  [{route}] {query[:50]} → +{boosted} boosts, +{extracted} beliefs")
    except Exception as e:
        print(f"No feedback data yet: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    if args.stats:
        stats()
