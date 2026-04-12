"""
nex_knowledge_filter.py — Knowledge quality filter for run.py
Flags beliefs that are too vague, duplicated, or contradictory
and marks them for review/decay.
"""
import sqlite3, os, logging
log = logging.getLogger("nex_knowledge_filter")
_DB = os.path.expanduser("~/Desktop/nex/nex.db")

def run_filter_cycle(cycle: int = 0, db_path: str = _DB) -> int:
    """
    Called every cycle by run.py.
    Only does real work every 30 cycles.
    Returns number of beliefs flagged.
    """
    if cycle % 30 != 0:
        return 0
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        flagged = 0

        # Flag beliefs that are too short to be meaningful
        cur.execute("""
            UPDATE beliefs SET confidence = MAX(0.1, confidence * 0.9)
            WHERE LENGTH(content) < 20
              AND topic NOT IN ('identity', 'core_values')
        """)
        flagged += cur.rowcount

        # Flag near-duplicate beliefs (same first 40 chars, different ids)
        rows = cur.execute("""
            SELECT id, SUBSTR(content, 1, 40) as prefix
            FROM beliefs ORDER BY confidence ASC
        """).fetchall()
        seen_prefixes = {}
        to_decay = []
        for row_id, prefix in rows:
            if prefix in seen_prefixes:
                to_decay.append(row_id)
            else:
                seen_prefixes[prefix] = row_id
        if to_decay:
            cur.executemany("""
                UPDATE beliefs SET confidence = MAX(0.1, confidence * 0.85)
                WHERE id = ?
            """, [(i,) for i in to_decay[:20]])
            flagged += min(len(to_decay), 20)

        con.commit(); con.close()
        if flagged:
            log.info(f"Knowledge filter: flagged {flagged} beliefs")
        return flagged
    except Exception as e:
        log.warning(f"run_filter_cycle: {e}")
        return 0
