#!/usr/bin/env python3
"""nex_knowledge_filter.py — prunes, deduplicates and decays beliefs."""
import sqlite3, time
from pathlib import Path

DB_PATH = Path.home() / ".config" / "nex" / "nex.db"

BELIEF_FLOOR = 500  # must match nex_directives.py

def run_filter_cycle(cycle: int = 0) -> int:
    if cycle % 3 != 0:
        return 0
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # ── Floor check — never prune below BELIEF_FLOOR ─────────────────────
        cur.execute("SELECT COUNT(*) FROM beliefs")
        total = cur.fetchone()[0]
        if total <= BELIEF_FLOOR:
            print(f"  [FILTER] skipped — at floor ({total}/{BELIEF_FLOOR})")
            conn.close()
            return 0
        # Prune low confidence — but stop at floor
        cur.execute("""
            DELETE FROM beliefs WHERE confidence < 0.40
            AND id NOT IN (
                SELECT id FROM beliefs
                ORDER BY confidence DESC
                LIMIT ?
            )
        """, (BELIEF_FLOOR,))
        pruned = cur.rowcount
        # Cap 300 per topic — floor-aware
        cur.execute("SELECT COUNT(*) FROM beliefs")
        total = cur.fetchone()[0]
        cur.execute("SELECT DISTINCT topic FROM beliefs")
        topics = [r[0] for r in cur.fetchall()]
        capped = 0
        for topic in topics:
            if total <= BELIEF_FLOOR:
                break
            cur.execute("SELECT id FROM beliefs WHERE topic=? ORDER BY confidence DESC", (topic,))
            ids = [r[0] for r in cur.fetchall()]
            if len(ids) > 300:
                to_remove = min(len(ids) - 300, total - BELIEF_FLOOR)
                for eid in ids[300:300 + to_remove]:
                    cur.execute("DELETE FROM beliefs WHERE id=?", (eid,))
                    capped += 1
                    total -= 1
        # Decay stale beliefs
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 30*86400))
        cur.execute("UPDATE beliefs SET confidence=MIN(confidence,0.85) WHERE timestamp < ? AND confidence > 0.45", (cutoff,))
        decayed = cur.rowcount
        conn.commit()
        conn.close()
        if pruned or capped or decayed:
            print(f"  [FILTER] pruned={pruned} capped={capped} decayed={decayed}")
        return pruned + capped
    except Exception as e:
        print(f"  [FILTER] error: {e}")
        return 0
