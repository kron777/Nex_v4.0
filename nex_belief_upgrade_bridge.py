"""nex_belief_upgrade_bridge.py — always returns dict"""
import sqlite3, os, logging
log = logging.getLogger("nex_belief_upgrade_bridge")
_DB = os.path.expanduser("~/Desktop/nex/nex.db")

def run_upgrade_bridge(cycle=0, db_path=_DB, bot_token="", chat_id="", **kwargs):
    if cycle % 40 != 0:
        return {"skipped": True, "type": "", "value": ""}
    try:
        con = sqlite3.connect(db_path, timeout=3)
        rows = con.execute("""
            SELECT id, content, topic, confidence FROM beliefs
            WHERE confidence < 0.85 AND confidence > 0.5
            AND topic NOT IN ('general','unknown','None')
            ORDER BY confidence DESC LIMIT 3
        """).fetchall()
        upgraded = []
        for row_id, content, topic, conf in rows:
            new_conf = min(0.92, conf + 0.05)
            con.execute("UPDATE beliefs SET confidence=? WHERE id=?", (new_conf, row_id))
            upgraded.append(f"{topic}: {content[:40]}")
        con.commit(); con.close()
        return {"skipped": len(upgraded)==0, "type": "promote", "value": "; ".join(upgraded)}
    except Exception as e:
        log.warning(f"run_upgrade_bridge: {e}")
        return {"skipped": True, "type": "", "value": ""}
