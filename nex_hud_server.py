#!/usr/bin/env python3
"""
nex_hud_server.py — NEX v1.0 HUD API Server
Serves live cognitive data to the browser HUD.
Runs on localhost:7700
"""

import json, re, sqlite3, time, threading, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

CFG         = Path.home() / ".config" / "nex"
DB_PATH     = CFG / "nex.db"
STATE_PATH  = CFG / "loop_state.json"
LOG_PATH    = CFG / "nex_loop.log"
URG_PATH    = CFG / "drive_urgency.json"
DRIVES_PATH = CFG / "nex_drives.json"
NET_IFACE   = "enp4s0"

PORT = 7700

# ── Data collectors ───────────────────────────────────────────────────────────

_net_prev   = [0, 0, 0.0]
_net_history= []  # last 30 samples (rx_k, tx_k)
_log_pos    = 0
_log_lines  = []  # last 40 lines
_belief_history = []  # (timestamp, count) last 30

def read_net():
    try:
        for line in open("/proc/net/dev"):
            if NET_IFACE in line:
                p = line.split()
                rx, tx = int(p[1]), int(p[9])
                now = time.time()
                pr, ptx, pt = _net_prev
                dt = max(now - pt, 0.1) if pt else 1.0
                rx_k = max(0, (rx-pr)/dt/1024) if pt else 0.0
                tx_k = max(0, (tx-ptx)/dt/1024) if pt else 0.0
                _net_prev[0]=rx; _net_prev[1]=tx; _net_prev[2]=now
                return round(rx_k,1), round(tx_k,1)
    except: pass
    return 0.0, 0.0

def tail_log():
    global _log_pos
    try:
        if not LOG_PATH.exists(): return
        with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
            f.seek(_log_pos)
            for line in f:
                line = line.strip()
                if not line or "DEBUG" in line: continue
                line = re.sub(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ \[INFO\] ','',line)
                line = re.sub(r'nex\.\w+ — ','',line)
                _log_lines.append({"t": datetime.now().strftime("%H:%M:%S"), "msg": line})
                if len(_log_lines) > 60:
                    _log_lines.pop(0)
            _log_pos = f.tell()
    except: pass

def get_db():
    if not DB_PATH.exists(): return None
    try:
        con = sqlite3.connect(str(DB_PATH), timeout=2)
        con.row_factory = sqlite3.Row
        return con
    except: return None

def db_count(con, table, where=""):
    try:
        q = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
        return con.execute(q).fetchone()[0]
    except: return 0

def tbl_ok(con, name):
    try:
        return con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None
    except: return False

def load_json(path):
    try:
        p = Path(path)
        return json.loads(p.read_text()) if p.exists() else {}
    except: return {}

def collect_data():
    tail_log()
    rx_k, tx_k = read_net()
    _net_history.append({"rx": rx_k, "tx": tx_k})
    if len(_net_history) > 30: _net_history.pop(0)

    con  = get_db()
    st   = load_json(STATE_PATH)
    urgs = load_json(URG_PATH)
    drvs_raw = load_json(DRIVES_PATH)

    # Beliefs
    bt = br = op_n = cg = ct = pt = 0
    opinions = []
    recent_beliefs = []
    if con:
        bt  = db_count(con,"beliefs")
        br  = db_count(con,"beliefs","timestamp >= datetime('now','-24 hours')")
        op_n= db_count(con,"opinions") if tbl_ok(con,"opinions") else 0
        cg  = db_count(con,"curiosity_gaps","filled=0") if tbl_ok(con,"curiosity_gaps") else 0
        ct  = db_count(con,"contradiction_pairs") if tbl_ok(con,"contradiction_pairs") else 0
        pt  = db_count(con,"reflections","reflection_type='post_draft'") if tbl_ok(con,"reflections") else 0
        if tbl_ok(con,"opinions"):
            try:
                rows = con.execute(
                    "SELECT topic,stance_score,strength FROM opinions ORDER BY strength DESC LIMIT 6"
                ).fetchall()
                opinions = [{"topic":r["topic"],"stance":round(r["stance_score"],3),
                             "strength":round(r["strength"],3)} for r in rows]
            except: pass
        try:
            rows = con.execute(
                "SELECT content,topic,confidence FROM beliefs ORDER BY rowid DESC LIMIT 8"
            ).fetchall()
            recent_beliefs = [{"content":r["content"][:80],"topic":r["topic"],
                               "confidence":round(float(r["confidence"] or 0),2)} for r in rows]
        except: pass
        try: con.close()
        except: pass

    _belief_history.append({"t": time.time(), "n": bt})
    if len(_belief_history) > 30: _belief_history.pop(0)

    # Drives
    if isinstance(drvs_raw, dict):
        for k in ("primary","secondary","active","drives"):
            if k in drvs_raw: drvs_raw = drvs_raw[k]; break
    drives = []
    if isinstance(drvs_raw, list):
        for d in drvs_raw[:6]:
            did   = d.get("id") or d.get("label","?")
            label = d.get("label",did)
            urg   = (urgs.get(did,{}).get("urgency",d.get("intensity",0.5))
                     if isinstance(urgs,dict) else 0.5)
            drives.append({"id":did,"label":label,"urgency":round(float(urg),3)})
    if not drives and isinstance(urgs,dict):
        for did,e in list(urgs.items())[:6]:
            urg = float(e.get("urgency",0.5)) if isinstance(e,dict) else 0.5
            drives.append({"id":did,"label":did,"urgency":round(urg,3)})

    # LLM status
    llm_online = False
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=1)
        llm_online = any("qwen" in m["name"] for m in r.json().get("models",[]))
    except: pass

    cycle   = st.get("cycle",0)
    last_run= st.get("last_run",0)
    ago     = int(time.time()-last_run) if last_run else 0

    # Social platform status
    social_status = {}
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from nex_social import platform_status
        social_status = platform_status()
    except: pass

    return {
        "ts":        datetime.now().strftime("%H:%M:%S"),
        "cycle":     cycle,
        "last_run_ago": ago,
        "llm_online":llm_online,
        "social":    social_status,
        "beliefs": {
            "total": bt, "new_24h": br, "opinions": op_n,
            "gaps": cg, "contradictions": ct, "posts": pt,
        },
        "opinions":       opinions,
        "recent_beliefs": recent_beliefs,
        "drives":         drives,
        "net": {"rx": rx_k, "tx": tx_k, "history": list(_net_history)},
        "belief_history": list(_belief_history),
        "log":  list(_log_lines[-20:]),
    }

# ── Chat handler ──────────────────────────────────────────────────────────────
def handle_chat(query: str) -> str:
    con = get_db()
    if not con: return "No belief graph available."
    words = [w for w in query.lower().split() if len(w) > 3]
    try:
        from nex_llm import nex_chat_response, is_online
        if is_online():
            hits = []
            for word in words[:3]:
                rows = con.execute(
                    "SELECT content FROM beliefs WHERE LOWER(content) LIKE ? LIMIT 2",
                    (f"%{word}%",)
                ).fetchall()
                hits.extend([r["content"] for r in rows])
            belief_ctx = "\n".join(hits[:4])
            op_rows = con.execute(
                "SELECT topic,stance_score FROM opinions ORDER BY strength DESC LIMIT 3"
            ).fetchall() if tbl_ok(con,"opinions") else []
            opinion_ctx = " | ".join(f"{r['topic']}:{r['stance_score']:+.2f}" for r in op_rows)
            urgs = load_json(URG_PATH)
            drive_ctx = ""
            if isinstance(urgs,dict) and urgs:
                top = max(urgs.items(), key=lambda x: x[1].get("urgency",0) if isinstance(x[1],dict) else 0)
                drive_ctx = top[0]
            resp = nex_chat_response(query, belief_ctx, opinion_ctx, drive_ctx)
            if resp:
                con.close()
                return resp
    except: pass

    parts = []
    for word in words[:3]:
        rows = con.execute(
            "SELECT content,confidence FROM beliefs "
            "WHERE LOWER(content) LIKE ? AND length(content)<300 "
            "ORDER BY confidence DESC LIMIT 2", (f"%{word}%",)
        ).fetchall()
        for r in rows:
            parts.append(f"[{float(r['confidence']):.2f}] {r['content'][:100]}")
    try: con.close()
    except: pass
    return "\n".join(parts) if parts else f"No beliefs on '{query}'."

# ── HTTP Handler ──────────────────────────────────────────────────────────────

_cached_data = {}
_cache_lock  = threading.Lock()

def _bg_collect():
    while True:
        try:
            d = collect_data()
            with _cache_lock:
                _cached_data.update(d)
        except Exception as e:
            pass
        time.sleep(2)

class HUDHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # silence access log

    def do_GET(self):
        if self.path == "/data":
            with _cache_lock:
                data = dict(_cached_data)
            self._json(data)
        elif self.path == "/":
            self._send_hud()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == "/chat":
            length = int(self.headers.get("Content-Length",0))
            body   = self.rfile.read(length)
            try:
                query = json.loads(body).get("query","")
                response = handle_chat(query)
            except Exception as e:
                response = f"Error: {e}"
            self._json({"response": response})
        else:
            self.send_response(404); self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(body)

    def _send_hud(self):
        hud_path = Path(__file__).parent / "nex_hud.html"
        if not hud_path.exists():
            self.send_response(404); self.end_headers(); return
        body = hud_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type","text/html")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

def start_server():
    threading.Thread(target=_bg_collect, daemon=True).start()
    server = HTTPServer(("localhost", PORT), HUDHandler)
    print(f"  NEX HUD server running at http://localhost:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    start_server()
