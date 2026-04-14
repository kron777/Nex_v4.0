import sqlite3, os, time, re
from datetime import datetime

BRAIN_LOG = "/tmp/nex_brain.log"
BUF_DB    = os.path.expanduser("~/.config/nex/hud_buffer.db")
SKIP = ['consolidator','ACCEPT on topic','Resolved 3 contra','Locked top 30',
        'LOOP id=','Cap hit id=','reinforce_minor','prune_boost',
        'BeliefIndex','singleton lock','NBRE bridge injected',
        'fired=0 conf','needs_llm=True rate=0','conf=0.00 needs_llm=False rate=0.0']

def init_db():
    con = sqlite3.connect(BUF_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, channel TEXT, src TEXT, msg TEXT
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ch ON events(channel,id)")
    con.commit()
    return con

def run():
    con = init_db()
    # Start from end of file — only new lines
    offset = os.path.getsize(BRAIN_LOG) if os.path.exists(BRAIN_LOG) else 0
    print(f"Starting at offset {offset} (end of file — live only)")
    while True:
        try:
            sz = os.path.getsize(BRAIN_LOG) if os.path.exists(BRAIN_LOG) else 0
            if sz < offset:  # log rotated
                offset = 0
            if sz > offset:
                with open(BRAIN_LOG, 'rb') as f:
                    f.seek(offset)
                    raw = f.read(sz - offset).decode('utf-8', errors='ignore')
                offset = sz
                entries = []
                for line in raw.splitlines():
                    line = line.strip()
                    if len(line) < 8: continue
                    if any(s in line for s in SKIP): continue
                    line = re.sub(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[.,\d]* ', '', line)
                    line = re.sub(r'^\[\s*\]\s*', '', line).strip()
                    if len(line) < 5: continue
                    entries.append(line)
                if entries:
                    for e in entries:
                        con.execute("INSERT INTO events(ts,channel,src,msg) VALUES(datetime('now'),'stream','BRAIN',?)", (e[:400],))
                    con.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 800)")
                    con.commit()
                    print(f"+{len(entries)} entries (total: {con.execute('SELECT COUNT(*) FROM events').fetchone()[0]})")
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(1)

if __name__ == "__main__":
    print("Buf daemon — live tail only")
    run()
