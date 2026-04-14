#!/usr/bin/env python3
"""
nex_hud_server.py — NEX HUD v2.0 server
----------------------------------------
• Serves nex_hud.html on GET /
• HTTP endpoints for initial hydration (/data, /debug, /replies, /agi, /yt_feed)
• SSE endpoint /sse/col2 for log streaming (fallback if WS is unavailable)
• The primary live transport is nex_ws.py on ws://localhost:8765

Port: 7700
"""
import os, sys, json, re, sqlite3, time
from pathlib import Path
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT    = 7700
NEX_DIR = Path.home() / "Desktop/nex"
LOG_PATH  = Path("/tmp/nex_brain.log")
FEED_PATH = Path.home() / ".config/nex/feed_events.jsonl"
BUF_DB    = str(Path.home() / ".config/nex/hud_buffer.db")

sys.path.insert(0, str(NEX_DIR))

# ── LOG TAIL ──────────────────────────────────────────────────────────────────
_log_lines: list = []
_log_pos:   int  = 0

_LOG_SKIP = [
    'consolidator','ACCEPT on topic','Resolved 3','Locked top',
    'LOOP id=','Cap hit','reinforce_minor','prune_boost',
    'fired=','needs_llm','NBRE bridge','DUAL PROCESS','ColdQuery',
    'EMBODIED','high_load','[D12]','[D14]','[D7]',
    'YouTube','youtube','AGI-YT','transcript','webshare',
    'residential','proxy','DISTILL_PROMPT','Could not retrieve',
    'is blocking','retrievable','jdepoix',
    'is blocking','retrievable','jdepoix',
    '[CONTRA]','INNER LIFE','[BUS]','unresolved in','forced topic pull',
    'soul_loop','CogPressure','colony','Colony','AutoSeeder',
    'Contemplative','reaching cognitive','resolver','Tension logged',
    'Contemplative','reaching cognitive','resolver','Tension logged',
    '[NIGHTLY]','meta_beliefs','has no column','CharacterEngine','circular import',
]

_ANSI = re.compile(r'\x1b\[[0-9;]*m')
_TS_PREFIX = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[.,\d]* ')

def tail_log():
    global _log_pos, _log_lines
    if not LOG_PATH.exists():
        return
    try:
        sz = LOG_PATH.stat().st_size
        if sz < _log_pos:
            _log_pos = 0
        with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
            f.seek(_log_pos)
            lines = f.readlines()
            _log_pos = f.tell()
        for l in lines:
            l = l.strip()
            if not l or any(s in l for s in _LOG_SKIP):
                continue
            l = _ANSI.sub('', l)
            l = _TS_PREFIX.sub('', l)
            if len(l) > 3:
                _log_lines.append({
                    't': datetime.now().strftime('%H:%M:%S'),
                    'msg': l[:300]
                })
        if len(_log_lines) > 300:
            _log_lines = _log_lines[-300:]
    except Exception:
        pass


# ── DATA COLLECTION ───────────────────────────────────────────────────────────
def collect_data() -> dict:
    tail_log()

    beliefs = orig = 0
    conf = 70

    try:
        db = sqlite3.connect(str(NEX_DIR / "nex.db"), timeout=2)
        beliefs = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]

        # Legacy migration DBs
        import glob as _glob
        for legacy in _glob.glob(str(Path.home() / ".config/nex/nex_pre_v1*.db")):
            try:
                ldb = sqlite3.connect(legacy, timeout=1)
                beliefs += ldb.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                ldb.close()
            except Exception:
                pass

        # Earned beliefs JSON
        try:
            earned = json.load(open(str(Path.home() / ".config/nex/nex_earned_beliefs.json")))
            beliefs += len(earned) if isinstance(earned, list) else 0
        except Exception:
            pass

        orig = db.execute(
            "SELECT COUNT(*) FROM beliefs "
            "WHERE origin IN ('insight_synthesis','self_reflection','contradiction_engine')"
        ).fetchone()[0]

        r = db.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0]
        conf = int((r or 0.7) * 100)
        db.close()
    except Exception:
        pass

    replied = chatted = posted = sys1 = llmdep = 0

    try:
        lines = open(str(LOG_PATH), encoding="utf-8", errors="replace").readlines()[-400:]
        for line in lines:
            if "All-time:" in line:
                for key, var_ref in [
                    (r"(\d+) replied", 'replied'),
                    (r"(\d+) chatted", 'chatted'),
                    (r"(\d+) posted",  'posted'),
                ]:
                    m = re.search(key, line)
                    if m:
                        if var_ref == 'replied': replied = int(m.group(1))
                        elif var_ref == 'chatted': chatted = int(m.group(1))
                        elif var_ref == 'posted': posted  = int(m.group(1))
            if "system1_rate" in line:
                m = re.search(r"system1_rate[=: ]+([0-9.]+)", line)
                if m:
                    sys1 = int(float(m.group(1)))
    except Exception:
        pass

    return {
        "ts":      datetime.now().strftime("%H:%M:%S"),
        "replied": replied,
        "learnt":  0,
        "posted":  posted,
        "chatted": chatted,
        "conf":    conf,
        "align":   64,
        "network": 70,
        "iq":      "95",
        "original": orig,
        "beliefs": {
            "total":          beliefs,
            "new_24h":        0,
            "opinions":       0,
            "gaps":           0,
            "contradictions": 0,
            "posts":          0,
        },
        "nbre": {
            "system1_rate":        sys1,
            "llm_dependency_rate": llmdep,
            "episodic_events":     0,
            "throw_net_sessions":  0,
            "consolidation_last":  "",
        },
        "social": {},
        "log":    _log_lines[-25:],
    }


# ── HELPERS ───────────────────────────────────────────────────────────────────
def _platform_from_context(ctx: str) -> str:
    if not ctx:
        return "moltbook"
    if ctx.startswith("@"):
        return "mastodon"
    c = ctx.lower()
    if "discord"  in c: return "discord"
    if "telegram" in c: return "telegram"
    return "moltbook"


def _cors_headers(handler):
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")


# ── REQUEST HANDLER ───────────────────────────────────────────────────────────
class HUDHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence default access log

    def send_json(self, obj: dict, status: int = 200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        _cors_headers(self)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        _cors_headers(self)
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        qs   = self.path.split("?")[1] if "?" in self.path else ""
        params = dict(x.split("=", 1) for x in qs.split("&") if "=" in x)

        # ── root → serve HUD ──────────────────────────────────────────
        if path == "/":
            html_file = NEX_DIR / "nex_hud.html"
            try:
                body = html_file.read_bytes()
            except FileNotFoundError:
                body = b"<h1>nex_hud.html not found</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # ── /data — main stats payload ─────────────────────────────────
        elif path == "/data":
            self.send_json(collect_data())

        # ── /debug — recent log lines ──────────────────────────────────
        elif path == "/debug":
            tail_log()
            self.send_json({"lines": _log_lines[-50:]})

        # ── /yt_feed — YouTube entries from feed_events.jsonl ──────────
        elif path == "/yt_feed":
            entries = []
            try:
                with open(FEED_PATH) as f:
                    for line in f.readlines()[-60:]:
                        try:
                            e = json.loads(line.strip())
                            msg = e.get("msg", "")
                            if "YouTube" in msg or "youtube" in msg:
                                entries.append({"time": e.get("t", ""), "text": msg})
                        except Exception:
                            pass
            except Exception:
                pass
            self.send_json({"entries": entries})

        # ── /feed — all feed_events.jsonl entries ──────────────────────
        elif path == "/feed":
            entries = []
            try:
                with open(FEED_PATH) as f:
                    for line in f.readlines()[-200:]:
                        try:
                            entries.append(json.loads(line.strip()))
                        except Exception:
                            pass
            except Exception:
                pass
            self.send_json({"entries": entries})

        # ── /replies — NEX sent responses from reflexion_log ───────────
        elif path == "/replies":
            replies = []
            try:
                db = sqlite3.connect(str(NEX_DIR / "nex.db"), timeout=2)
                rows = db.execute(
                    "SELECT id, response, user_input, timestamp "
                    "FROM reflexion_log "
                    "ORDER BY timestamp DESC LIMIT 40"
                ).fetchall()
                db.close()
                replies = [
                    {
                        "id":       r[0],
                        "text":     r[1],
                        "context":  r[2],
                        "ts":       r[3],
                        "platform": _platform_from_context(r[2]),
                    }
                    for r in rows if r[1]
                ]
            except Exception:
                pass
            self.send_json({"replies": replies})

        # ── /agi — AGI watch hits ──────────────────────────────────────
        elif path == "/agi":
            items = []
            try:
                db = sqlite3.connect(str(NEX_DIR / "nex.db"), timeout=2)
                try:
                    rows = db.execute(
                        "SELECT id, content, tier, timestamp "
                        "FROM agi_watch_hits ORDER BY timestamp DESC LIMIT 30"
                    ).fetchall()
                    items = [{"id": r[0], "text": r[1], "tier": r[2], "ts": r[3]} for r in rows]
                except Exception:
                    try:
                        rows = db.execute(
                            "SELECT content, 2 AS tier, created_at "
                            "FROM agi_corpus ORDER BY created_at DESC LIMIT 30"
                        ).fetchall()
                        items = [{"text": r[0], "tier": r[1], "ts": r[2]} for r in rows]
                    except Exception:
                        pass
                db.close()
            except Exception:
                pass
            self.send_json({"hits": items, "badge": len(items)})

        # ── /buf — ring buffer reads ───────────────────────────────────
        elif path == "/buf":
            channel = params.get("channel", "stream")
            after   = int(params.get("after", "0"))
            rows = []
            try:
                c = sqlite3.connect(BUF_DB, timeout=2)
                rows = [
                    {"id": r[0], "t": r[1], "src": r[2], "msg": r[3]}
                    for r in c.execute(
                        "SELECT id,ts,src,msg FROM events "
                        "WHERE channel=? AND id>? ORDER BY id ASC LIMIT 30",
                        (channel, after)
                    ).fetchall()
                ]
                c.close()
            except Exception:
                pass
            self.send_json({"events": rows})

        # ── /sse/col2 — SSE log stream (WS fallback) ───────────────────


        elif path == "/sse/hub":
            import time as _t, threading as _th
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            # Use UNBUFFERED raw socket — fixes SSE data being held in buffer
            _raw = self.connection.makefile('wb', 0)
            try:
                _raw.write(b"retry: 1000\n\n")
            except: pass

            def _send(evt, data):
                try:
                    msg = f"event: {evt}\ndata: {json.dumps(data)}\n\n"
                    _raw.write(msg.encode("utf-8"))
                    return True
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return False
                except Exception:
                    return False

            # Seed col1 with last 20 YouTube entries
            try:
                with open(str(FEED_PATH)) as _ff:
                    _all = _ff.readlines()
                _yt = []
                for _ll in _all[-200:]:
                    try:
                        _e = json.loads(_ll)
                        if _e.get("src") == "YOUTUBE":
                            _msg = _e.get("msg","").replace("[YouTube]","").strip()
                            if _msg: _yt.append({"t":_e.get("t",""),"msg":_msg})
                    except: pass
                for _ye in _yt[-20:]:
                    _send("col1", _ye)
            except: pass

            # Seed col3 with last 10 responses
            try:
                _rdb = sqlite3.connect(str(NEX_DIR/"nex.db"), timeout=2)
                _rrows = _rdb.execute("SELECT response,user_input,timestamp FROM reflexion_log ORDER BY id DESC LIMIT 10").fetchall()
                _rdb.close()
                for _rr in reversed(_rrows):
                    _txt = (_rr[0] or "").strip()
                    _ui = (_rr[1] or "").lower()
                    if not _txt: continue
                    _plat = "discord" if "discord" in _ui else "mastodon" if ("mastodon" in _ui or "@" in (_rr[1] or "")) else "moltbook"
                    _send("col3", {"t":str(_rr[2] or ""),"plat":_plat,"msg":_txt[:300]})
            except: pass

            # Track positions
            _fp = str(FEED_PATH)
            _off = os.path.getsize(_fp) if os.path.exists(_fp) else 0
            _blog = "/tmp/nex_brain.log"
            _boff = max(0, os.path.getsize(_blog)-2000) if os.path.exists(_blog) else 0
            _last_resp_id = 0
            _plat_cycle = ["moltbook","discord","mastodon"]
            _plat_idx = 0
            _tick = 0

            try:
                while True:
                    _tick += 1
                    # Keepalive every 5s — prevents browser timeout
                    if _tick % 10 == 0:
                        try:
                            _raw.write(b": keepalive\n\n")
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            break

                    # Col1: YouTube from feed_events.jsonl
                    try:
                        _sz = os.path.getsize(_fp) if os.path.exists(_fp) else 0
                        if _sz < _off: _off = 0
                        if _sz > _off:
                            with open(_fp,"rb") as _f:
                                _f.seek(_off); _chunk = _f.read(_sz-_off).decode("utf-8",errors="ignore")
                            _off = _sz
                            for _line in _chunk.splitlines():
                                try:
                                    _e = json.loads(_line)
                                    if _e.get("src") != "YOUTUBE": continue
                                    _msg = _e.get("msg","").replace("[YouTube]","").strip()
                                    if len(_msg) < 5: continue
                                    if not _send("col1", {"t":_e.get("t",""),"msg":_msg}): break
                                except: pass
                    except: pass

                    # Col2: Debug from brain log
                    try:
                        _bsz = os.path.getsize(_blog) if os.path.exists(_blog) else 0
                        if _bsz < _boff: _boff = 0
                        if _bsz > _boff:
                            with open(_blog,"rb") as _f:
                                _f.seek(_boff); _bc = _f.read(_bsz-_boff).decode("utf-8",errors="ignore")
                            _boff = _bsz
                            for _bl in _bc.splitlines():
                                _bl = _bl.strip()
                                if not _bl or any(_s in _bl for _s in _LOG_SKIP): continue
                                _bl = _ANSI.sub("",_bl)
                                _bl = _TS_PREFIX.sub("",_bl).strip()
                                if len(_bl) < 5: continue
                                if not _send("col2", {"msg":_bl}): break
                    except: pass

                    # Col3: Responses revolving platforms (every 2s)
                    if _tick % 4 == 0:
                        try:
                            _rdb = sqlite3.connect(str(NEX_DIR/"nex.db"), timeout=1)
                            _rrows = _rdb.execute(
                                "SELECT id,response,user_input,timestamp FROM reflexion_log WHERE id>? ORDER BY id ASC LIMIT 10",
                                (_last_resp_id,)
                            ).fetchall()
                            _rdb.close()
                            for _rr in _rrows:
                                _last_resp_id = max(_last_resp_id, _rr[0])
                                _txt = (_rr[1] or "").strip()
                                if not _txt: continue
                                _ui = (_rr[2] or "")
                                _ui_low = _ui.lower()
                                _plat = "discord" if "discord" in _ui_low else "mastodon" if ("mastodon" in _ui_low or "@" in _ui) else "moltbook"
                                if not _send("col3", {"t":str(_rr[3] or ""),"plat":_plat,"msg":_txt[:300]}): break
                        except: pass

                    _t.sleep(0.3)
            except: pass
            return
        elif path == "/sse/activity":
            import time as _t
            self.send_response(200)
            self.send_header("Content-Type","text/event-stream")
            self.send_header("Cache-Control","no-cache")
            self.send_header("Access-Control-Allow-Origin","*")
            self.send_header("Connection","keep-alive")
            self.end_headers()
            _fp = str(FEED_PATH)
            _off = max(0, os.path.getsize(_fp) - 8000) if os.path.exists(_fp) else 0
            _eid = 0
            _keep = ['YOUTUBE']  # activity = YouTube only
            try:
                while True:
                    sz = os.path.getsize(_fp) if os.path.exists(_fp) else 0
                    if sz < _off: _off = 0
                    if sz > _off:
                        with open(_fp,"rb") as _f:
                            _f.seek(_off)
                            chunk = _f.read(sz-_off).decode("utf-8",errors="ignore")
                        _off = sz
                        for line in chunk.splitlines():
                            try:
                                e = json.loads(line)
                                msg = e.get("msg","")
                                if e.get("src") != "YOUTUBE": continue
                                if len(msg) < 5: continue
                                _eid += 1
                                self.wfile.write(("id: {}\ndata: {}\n\n".format(_eid, json.dumps({"t":e.get("t",""),"msg":msg}))).encode())
                                self.wfile.flush()
                            except: pass
                    _t.sleep(0.5)
            except: pass
            return

        elif path == "/sse/responses":
            import time as _t
            self.send_response(200)
            self.send_header("Content-Type","text/event-stream")
            self.send_header("Cache-Control","no-cache")
            self.send_header("Access-Control-Allow-Origin","*")
            self.send_header("Connection","keep-alive")
            self.end_headers()
            _last_id = 0
            _eid = 0
            _plat_cycle = ['moltbook','discord','mastodon']
            _plat_idx = 0
            try:
                while True:
                    try:
                        db = sqlite3.connect(str(NEX_DIR/"nex.db"), timeout=2)
                        rows = db.execute(
                            "SELECT id,response,user_input,timestamp FROM reflexion_log WHERE id>? ORDER BY id ASC LIMIT 20",
                            (_last_id,)
                        ).fetchall()
                        db.close()
                        # Sort into platform buckets
                        buckets = {'moltbook':[], 'discord':[], 'mastodon':[], 'other':[]}
                        for row in rows:
                            _last_id = max(_last_id, row[0])
                            text = (row[1] or "").strip()
                            if not text: continue
                            ui = (row[2] or "").lower()
                            if 'discord' in ui: buckets['discord'].append((row[3],text))
                            elif 'mastodon' in ui or ui.startswith('@'): buckets['mastodon'].append((row[3],text))
                            else: buckets['moltbook'].append((row[3],text))
                        # Emit one from current platform, revolve
                        for _ in range(3):
                            plat = _plat_cycle[_plat_idx % 3]
                            _plat_idx += 1
                            pool = buckets.get(plat, []) or buckets['moltbook']
                            if pool:
                                item = pool.pop(0)
                                t, text = item[0], item[1]
                                _eid += 1
                                self.wfile.write(("id: {}\ndata: {}\n\n".format(_eid, json.dumps({"t":str(t or ""),"plat":plat,"msg":text[:300]}))).encode())
                                self.wfile.flush()
                                break
                    except: pass
                    _t.sleep(1)
            except: pass
            return
        elif path == "/sse/col2":
            self._handle_sse()

        # ── 404 ───────────────────────────────────────────────────────
        else:
            self.send_response(404)
            _cors_headers(self)
            self.end_headers()

    # ── SSE handler ──────────────────────────────────────────────────────────
    def _handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        _cors_headers(self)
        self.end_headers()

        _SSE_SKIP = [
            'consolidator','ACCEPT on topic','Locked top','LOOP id=',
            'Cap hit','reinforce_minor','NBRE bridge','BeliefIndex',
            'EMBODIED','high_load','YouTube','youtube','AGI-HUNT',
            'THROW-NET','search \''
        ]

        log_path = str(LOG_PATH)
        offset = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        event_id = 0

        try:
            while True:
                sz = os.path.getsize(log_path) if os.path.exists(log_path) else 0
                if sz < offset:
                    offset = 0
                if sz > offset:
                    with open(log_path, "rb") as f:
                        f.seek(offset)
                        chunk = f.read(sz - offset).decode("utf-8", errors="ignore")
                    offset = sz

                    for line in chunk.splitlines():
                        line = line.strip()
                        if not line or any(s in line for s in _SSE_SKIP):
                            continue
                        line = _ANSI.sub('', line)
                        line = _TS_PREFIX.sub('', line).strip()
                        if len(line) < 5:
                            continue
                        event_id += 1
                        payload = "id: {}\ndata: {}\n\n".format(
                            event_id, json.dumps({"msg": line})
                        )
                        self.wfile.write(payload.encode())
                        self.wfile.flush()

                time.sleep(0.8)
        except Exception:
            pass


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    server = ThreadingHTTPServer(("localhost", PORT), HUDHandler)
    server.daemon_threads = True
    print(f"[NEX HUD] http://localhost:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[NEX HUD] shutdown", flush=True)
