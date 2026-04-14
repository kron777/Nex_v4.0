#!/usr/bin/env python3
"""nex_hud_server.py — minimal rebuild"""
import os, sys, json, re, sqlite3
from pathlib import Path
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 7700
LOG_PATH = Path("/tmp/nex_brain.log")
FEED_PATH = Path.home() / ".config/nex/feed_events.jsonl"
BUF_DB    = str(Path.home() / ".config/nex/hud_buffer.db")
NEX_DIR   = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

_log_lines = []
_log_pos   = 0

def tail_log():
    global _log_pos, _log_lines
    if not LOG_PATH.exists(): return
    try:
        sz = LOG_PATH.stat().st_size
        if sz < _log_pos: _log_pos = 0
        with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
            f.seek(_log_pos)
            lines = f.readlines()
            _log_pos = f.tell()
        skip = ['consolidator','ACCEPT on topic','Resolved 3','Locked top',
                'LOOP id=','Cap hit','reinforce_minor','prune_boost',
                'fired=','needs_llm','NBRE bridge','DUAL PROCESS','ColdQuery',
                'EMBODIED','high_load','[D12]','[D14]','[D7]']
        for l in lines:
            l = l.strip()
            if not l or any(s in l for s in skip): continue
            l = re.sub(r'\[[0-9;]*m','',l)  # strip ANSI
            l = re.sub(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[.,\d]* ','',l)
            if len(l) > 3:
                _log_lines.append({'t': datetime.now().strftime('%H:%M:%S'), 'msg': l[:300]})
        if len(_log_lines) > 200: _log_lines = _log_lines[-200:]
    except: pass

def collect_data():
    tail_log()
    beliefs, orig, conf = 0, 0, 70
    try:
        db = sqlite3.connect(str(NEX_DIR/"nex.db"), timeout=2)
        beliefs = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        # Add legacy migration DB
        import glob as _glob, pathlib as _pl, json as _json
        for legacy in _glob.glob(str(_pl.Path.home()/".config/nex/nex_pre_v1*.db")):
            try:
                ldb = sqlite3.connect(legacy, timeout=1)
                beliefs += ldb.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                ldb.close()
            except: pass
        # Add earned beliefs JSON
        try:
            earned = _json.load(open(str(_pl.Path.home()/".config/nex/nex_earned_beliefs.json")))
            beliefs += len(earned) if isinstance(earned, list) else 0
        except: pass
        orig = db.execute("SELECT COUNT(*) FROM beliefs WHERE origin IN ('insight_synthesis','self_reflection','contradiction_engine')").fetchone()[0]
        r = db.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0]
        conf = int((r or 0.7) * 100)
        db.close()
    except: pass
    replied = chatted = posted = 0
    sys1 = llmdep = episodes = thrownet = 0
    try:
        lines = open("/tmp/nex_brain.log", encoding="utf-8", errors="replace").readlines()[-300:]
        for line in lines:
            if "All-time:" in line:
                import re as _r
                m = _r.search(r"(\d+) replied", line)
                if m: replied = int(m.group(1))
                m = _r.search(r"(\d+) chatted", line)
                if m: chatted = int(m.group(1))
                m = _r.search(r"(\d+) posted", line)
                if m: posted = int(m.group(1))
            if "system1_rate" in line:
                import re as _r
                m = _r.search(r"system1_rate[=: ]+([0-9.]+)", line)
                if m: sys1 = int(float(m.group(1)))
    except: pass
    return {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "replied": replied, "learnt": 0, "posted": posted, "chatted": chatted,
        "conf": conf, "align": 64, "network": 70,
        "iq": "95% ELITE", "original": orig, "cycle": 0,
        "beliefs": {"total": beliefs, "new_24h": 0, "opinions": 0, "gaps": 0, "contradictions": 0, "posts": 0},
        "nbre": {"system1_rate": sys1, "llm_dependency_rate": llmdep,
                 "episodic_events": episodes, "throw_net_sessions": thrownet,
                 "consolidation_last": ""},
        "social": {}, "log": _log_lines[-20:],
        "drives": [], "opinions": [], "recent_beliefs": []
    }


class HUD(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send_json(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Content-Length",str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        qs = self.path.split("?")[1] if "?" in self.path else ""
        params = dict(x.split("=",1) for x in qs.split("&") if "=" in x)

        if p == "/sse/col2":
            import time as _t, re as _sre
            self.send_response(200)
            self.send_header("Content-Type","text/event-stream")
            self.send_header("Cache-Control","no-cache")
            self.send_header("Access-Control-Allow-Origin","*")
            self.send_header("Connection","keep-alive")
            self.end_headers()
            _skip = ['consolidator','ACCEPT on topic','Resolved 3','Locked top',
                     'LOOP id=','Cap hit','reinforce_minor','prune_boost',
                     'NBRE bridge','fired=0','BeliefIndex','EMBODIED','high_load']
            _log = "/tmp/nex_brain.log"
            _off = os.path.getsize(_log) if os.path.exists(_log) else 0
            _eid = 0
            try:
                while True:
                    sz = os.path.getsize(_log) if os.path.exists(_log) else 0
                    if sz < _off: _off = 0
                    if sz > _off:
                        with open(_log,"rb") as _f:
                            _f.seek(_off)
                            chunk = _f.read(sz-_off).decode("utf-8",errors="ignore")
                        _off = sz
                        for line in chunk.splitlines():
                            line = line.strip()
                            if not line or any(s in line for s in _skip): continue
                            line = _sre.sub(r'\x1b\[[0-9;]*m','',line)
                            line = _sre.sub(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[\.,\d]* ','',line).strip()
                            if len(line) < 5: continue
                            _eid += 1
                            payload = 'id: {}\ndata: {}\n\n'.format(
                                _eid, json.dumps({"msg": line}))
                            self.wfile.write(payload.encode())
                            self.wfile.flush()
                    _t.sleep(0.8)
            except: pass
            return
        elif p == "/data":
            tail_log()
            self.send_json(collect_data())

        elif p == "/feed":
            entries = []
            try:
                with open(FEED_PATH) as f:
                    for l in f.readlines()[-200:]:
                        try: entries.append(json.loads(l.strip()))
                        except: pass
            except: pass
            self.send_json({"entries": entries})

        elif p == "/buf":
            ch = params.get("channel","stream")
            af = int(params.get("after","0"))
            rows = []
            try:
                c = sqlite3.connect(BUF_DB, timeout=2)
                rows = [{"id":r[0],"t":r[1],"src":r[2],"msg":r[3]} for r in
                    c.execute("SELECT id,ts,src,msg FROM events WHERE channel=? AND id>? ORDER BY id ASC LIMIT 25",(ch,af)).fetchall()]
                c.close()
            except: pass
            self.send_json({"events": rows})

        elif p == "/stream/debug":
            af = int(params.get("offset","0"))
            rows = []
            mx = af
            try:
                c = sqlite3.connect(BUF_DB, timeout=2)
                rows = [{"id":r[0],"t":r[1],"src":r[2],"msg":r[3]} for r in
                    c.execute("SELECT id,ts,src,msg FROM events WHERE id>? ORDER BY id ASC LIMIT 30",(af,)).fetchall()]
                mx = rows[-1]["id"] if rows else af
                c.close()
            except: pass
            self.send_json({"lines": rows, "offset": mx})

        elif p == "/debug":
            tail_log()
            self.send_json({"lines": _log_lines})

        elif p == "/yt_feed":
            entries = []
            try:
                with open(FEED_PATH) as f:
                    for l in f.readlines()[-50:]:
                        try:
                            e = json.loads(l.strip())
                            if "YouTube" in e.get("msg","") or "youtube" in e.get("msg",""):
                                entries.append({"time":e.get("t",""),"text":e.get("msg","")})
                        except: pass
            except: pass
            self.send_json({"entries": entries})

        elif p == "/replies":
            try:
                db = sqlite3.connect(str(NEX_DIR/"nex.db"), timeout=2)
                rows = db.execute("SELECT id, response, user_input, timestamp FROM reflexion_log ORDER BY timestamp DESC LIMIT 30").fetchall()
                def _platform(u):
                    if not u: return "MOLTBOOK"
                    if u.startswith("@"): return "MASTODON"
                    if "discord" in u.lower(): return "DISCORD"
                    if "telegram" in u.lower(): return "TELEGRAM"
                    return "MOLTBOOK"
                replies = [{"id": r[0], "text": r[1], "context": r[2], "ts": r[3], "platform": _platform(r[2])} for r in rows if r[1]]
                db.close()
            except:
                replies = []
            self.send_json({"replies": replies})

        elif p == "/agi":
            try:
                db = sqlite3.connect(str(NEX_DIR/"nex.db"), timeout=2)
                # Try agi_watch_hits first, fallback to agi_corpus
                try:
                    rows = db.execute("SELECT id, content, tier, timestamp FROM agi_watch_hits ORDER BY timestamp DESC LIMIT 20").fetchall()
                    items = [{"id": r[0], "text": r[1], "tier": r[2], "ts": r[3]} for r in rows]
                except:
                    try:
                        rows = db.execute("SELECT content, 2 as tier, created_at FROM agi_corpus ORDER BY created_at DESC LIMIT 20").fetchall()
                        items = [{"content": r[0], "tier": r[1], "ts": r[2]} for r in rows]
                    except:
                        items = []
                db.close()
            except:
                items = []
            self.send_json({"hits": items, "badge": len(items)})

        elif p == "/":
            html = open(NEX_DIR/"nex_hud.html", encoding="utf-8").read()
            b = html.encode()
            self.send_response(200)
            self.send_header("Content-Type","text/html")
            self.send_header("Content-Length",str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    print(f"NEX HUD on http://localhost:{PORT}")
    ThreadingHTTPServer(("localhost", PORT), HUD).serve_forever()
