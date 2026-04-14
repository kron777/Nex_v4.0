"""
nex_belief_sync.py — Belief store consolidator
Syncs beliefs.json, nex_earned_beliefs.json, bridge_beliefs.json → nex.db
Run standalone or import sync_all_beliefs() from run.py
"""
import os, json, sqlite3, logging
from datetime import datetime
log = logging.getLogger("nex_belief_sync")
_DB  = os.path.expanduser("~/Desktop/nex/nex.db")
_CFG = os.path.expanduser("~/.config/nex")

SOURCES = [
    (os.path.join(_CFG, "beliefs.json"),          "beliefs_json"),
    (os.path.join(_CFG, "nex_earned_beliefs.json"), "earned_beliefs"),
    (os.path.join(_CFG, "bridge_beliefs.json"),    "bridge_beliefs"),
]

def sync_all_beliefs(db_path=_DB) -> int:
    total = 0
    try:
        con = sqlite3.connect(db_path)
        for fpath, source_tag in SOURCES:
            if not os.path.exists(fpath):
                continue
            try:
                data = json.load(open(fpath))
                items = data if isinstance(data, list) else data.get("beliefs", list(data.values()) if isinstance(data, dict) else [])
                for item in items:
                    if isinstance(item, str):
                        content, confidence, topic = item, 0.6, "general"
                    elif isinstance(item, dict):
                        content    = item.get("content") or item.get("text") or item.get("belief","")
                        confidence = float(item.get("confidence", item.get("score", 0.6)))
                        topic      = item.get("topic","general")
                    else:
                        continue
                    content = str(content).strip()
                    if len(content) < 15:
                        continue
                    con.execute("""INSERT OR IGNORE INTO beliefs
                        (content, confidence, source, topic, timestamp)
                        VALUES (?,?,?,?,?)""",
                        (content, confidence, source_tag, topic,
                         datetime.now().isoformat()))
                    total += con.execute("SELECT changes()").fetchone()[0]
            except Exception as e:
                log.warning(f"sync {fpath}: {e}")
        con.commit(); con.close()
        if total: log.info(f"Synced {total} new beliefs into nex.db")
    except Exception as e:
        log.error(f"sync_all_beliefs: {e}")
    return total

if __name__ == "__main__":
    n = sync_all_beliefs()
    print(f"✓ Synced {n} new beliefs into nex.db")
    import sqlite3 as _s
    db = _s.connect(_DB)
    total = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    db.close()
    print(f"  Total in nex.db: {total}")
