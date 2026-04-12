"""
nex_memory_manager.py — Memory compression for run.py
Prunes low-confidence, stale beliefs to keep DB lean.
"""
import sqlite3, os, logging
from datetime import datetime, timedelta
log = logging.getLogger("nex_memory_manager")
_DB = os.path.expanduser("~/Desktop/nex/nex.db")

def run_memory_compression(cycle: int = 0, llm_fn=None, db_path: str = _DB) -> int:
    """
    Called every cycle by run.py.
    Returns number of beliefs cleaned/archived.
    Only runs every 50 cycles to avoid constant churn.
    """
    if cycle % 50 != 0:
        return 0
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        # Archive beliefs that are very low confidence AND old AND rarely reinforced
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        cur.execute("""
            DELETE FROM beliefs
            WHERE confidence < 0.25
              AND reinforce_count < 2
              AND (timestamp < ? OR timestamp IS NULL)
              AND topic NOT IN ('identity', 'core_values', 'soul', 'self')
        """, (cutoff,))
        cleaned = cur.rowcount
        con.commit()
        # Decay unreinforced beliefs slightly
        cur.execute("""
            UPDATE beliefs
            SET confidence = MAX(0.1, confidence * 0.98)
            WHERE reinforce_count < 1
              AND timestamp < ?
        """, (cutoff,))
        con.commit()
        con.close()
        if cleaned > 0:
            log.info(f"Memory compression: removed {cleaned} stale beliefs")
        return cleaned
    except Exception as e:
        log.warning(f"run_memory_compression: {e}")
        return 0
