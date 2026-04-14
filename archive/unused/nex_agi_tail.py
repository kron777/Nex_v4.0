import sqlite3, time, sys
from pathlib import Path

db = Path.home() / ".config/nex/nex.db"
log = Path.home() / "Desktop/nex/agi.log"
last_id = 0

print(f"AGI tail running → {log}")
while True:
    try:
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM agi_watch_hits WHERE id > ? ORDER BY id",
            (last_id,)
        ).fetchall()
        con.close()
        if rows:
            with open(log, "a") as f:
                for r in rows:
                    line = f"[{r['created_at']}] T{r['tier']} | {r['matched_phrase'][:60]}\n  {r['content'][:200]}\n\n"
                    f.write(line)
                    print(line.strip())
                    last_id = r['id']
    except Exception as e:
        print(f"err: {e}")
    time.sleep(10)
