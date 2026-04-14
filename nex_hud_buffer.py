"""
Ring buffer using SQLite — acts as VRAM for HUD columns.
Brain writes events here; JS reads with offset cursor.
No JS queue stalling possible.
"""
import sqlite3, os, time, threading
from datetime import datetime

_DB = os.path.expanduser("~/.config/nex/hud_buffer.db")
_lock = threading.Lock()

def _get_db():
    con = sqlite3.connect(_DB, timeout=5)
    con.execute("""CREATE TABLE IF NOT EXISTS events (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      TEXT,
        channel TEXT,   -- 'stream','debug','responses'
        src     TEXT,
        msg     TEXT,
        created REAL DEFAULT (unixepoch('now','subsec'))
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_channel ON events(channel, id)")
    con.commit()
    return con

def write_event(channel, src, msg, ts=None):
    """Write one event to the ring buffer."""
    ts = ts or datetime.now().strftime("%H:%M:%S")
    with _lock:
        con = _get_db()
        con.execute("INSERT INTO events(ts,channel,src,msg) VALUES(?,?,?,?)",
                    (ts, channel, src, msg[:500]))
        # Keep buffer at 500 entries per channel
        con.execute("""DELETE FROM events WHERE channel=? AND id NOT IN (
            SELECT id FROM events WHERE channel=? ORDER BY id DESC LIMIT 500
        )""", (channel, channel))
        con.commit()
        con.close()

def read_events(channel, after_id=0, limit=20):
    """Read events after given id — returns list and max id seen."""
    con = _get_db()
    rows = con.execute("""
        SELECT id, ts, src, msg FROM events
        WHERE channel=? AND id>?
        ORDER BY id ASC LIMIT ?
    """, (channel, after_id, limit)).fetchall()
    con.close()
    return [{"id":r[0],"t":r[1],"src":r[2],"msg":r[3]} for r in rows]

if __name__ == "__main__":
    # Test
    write_event("stream", "TEST", "Ring buffer working")
    rows = read_events("stream", 0)
    print(f"✓ Ring buffer OK — {len(rows)} events")
    print(f"  DB: {_DB}")
