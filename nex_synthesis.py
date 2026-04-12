"""
nex_synthesis.py — wrapper for run.py
Delegates to nex_synthesis_engine.synthesize()
"""
import logging
log = logging.getLogger("nex_synthesis")

def run_synthesis_cycle(cycle: int = 0) -> int:
    """Called by run.py every cycle. Returns number of synthesis edges created."""
    try:
        from nex_synthesis_engine import synthesize
        import sqlite3, os
        db_path = os.path.expanduser("~/Desktop/nex/nex.db")
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        # Find a recent low-confidence belief to synthesize on
        row = cur.execute("""
            SELECT content FROM beliefs
            WHERE confidence < 0.6 AND LENGTH(content) > 30
            ORDER BY RANDOM() LIMIT 1
        """).fetchone()
        con.close()
        if row:
            result = synthesize(row[0][:120], store=True)
            if result and result.get("stored"):
                log.info(f"Synthesis: stored new belief on '{result.get('topic','?')}'")
                return 1
        return 0
    except Exception as e:
        log.warning(f"run_synthesis_cycle: {e}")
        return 0
