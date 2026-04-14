#!/usr/bin/env python3
"""
nex_hud_server.py — NEX HUD v2.0 server (FastAPI edition)
----------------------------------------------------------
Replaces ThreadingHTTPServer with FastAPI + uvicorn.
FastAPI handles SSE buffering, async, and keep-alive correctly.

Port: 7700
"""
import os, json, re, sqlite3, time, asyncio
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

PORT     = 7700
NEX_DIR  = Path.home() / "Desktop/nex"
LOG_PATH = Path("/tmp/nex_brain.log")
FEED_PATH = Path.home() / ".config/nex/feed_events.jsonl"
BUF_DB   = str(Path.home() / ".config/nex/hud_buffer.db")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── LOG SKIP LIST ──────────────────────────────────────────────────────────
_LOG_SKIP = [
    'consolidator','ACCEPT on topic','Resolved 3','Locked top',
    'LOOP id=','Cap hit','reinforce_minor','prune_boost',
    'fired=','needs_llm','NBRE bridge','DUAL PROCESS','ColdQuery',
    'EMBODIED','high_load','[D12]','[D14]','[D7]',
    'YouTube','youtube','AGI-YT','transcript','webshare',
    'residential','proxy','DISTILL_PROMPT','Could not retrieve',
    'is blocking','retrievable','jdepoix',
    '[CONTRA]','INNER LIFE','[BUS]','unresolved in','forced topic pull',
    'soul_loop','CogPressure','colony','Colony','AutoSeeder',
    'Contemplative','reaching cognitive','resolver','Tension logged',
    '[NIGHTLY]','meta_beliefs','has no column','CharacterEngine','circular import',
]

_ANSI      = re.compile(r'\x1b\[[0-9;]*m')
_TS_PREFIX = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[.,\d]* ')

_log_lines: list = []
_log_pos:   int  = 0

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
                _log_lines.append({'t': datetime.now().strftime('%H:%M:%S'), 'msg': l[:300]})
        if len(_log_lines) > 300:
            _log_lines = _log_lines[-300:]
    except Exception:
        pass


def collect_data() -> dict:
    tail_log()
    beliefs = orig = 0
    conf = 70
    try:
        db = sqlite3.connect(str(NEX_DIR / "nex.db"), timeout=2)
        beliefs = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        orig = db.execute(
            "SELECT COUNT(*) FROM beliefs WHERE origin IN "
            "('insight_synthesis','self_reflection','contradiction_engine')"
        ).fetchone()[0]
        r = db.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0]
        conf = int((r or 0.7) * 100)
        db.close()
    except Exception:
        pass
    return {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "replied": 0, "learnt": 0, "posted": 0, "chatted": 0,
        "conf": conf, "align": 64, "network": 70, "iq": "95",
        "original": orig,
        "beliefs": {"total": beliefs, "new_24h": 0, "opinions": 0,
                    "gaps": 0, "contradictions": 0, "posts": 0},
        "nbre": {"system1_rate": 0, "llm_dependency_rate": 0,
                 "episodic_events": 0, "throw_net_sessions": 0, "consolidation_last": ""},
        "social": {}, "log": _log_lines[-25:],
    }


def _platform_from_context(ctx: str) -> str:
    if not ctx: return "moltbook"
    if ctx.startswith("@"): return "mastodon"
    c = ctx.lower()
    if "discord" in c: return "discord"
    if "telegram" in c: return "telegram"
    return "moltbook"


# ── ROUTES ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_hud():
    html_file = NEX_DIR / "nex_hud.html"
    try:
        return html_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<h1>nex_hud.html not found</h1>"


@app.get("/data")
async def get_data():
    return collect_data()


@app.get("/debug")
async def get_debug():
    tail_log()
    return {"lines": _log_lines[-50:]}


@app.get("/yt_feed")
async def get_yt_feed():
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
    return {"entries": entries}


@app.get("/feed")
async def get_feed():
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
    return {"entries": entries}


@app.get("/replies")
async def get_replies():
    replies = []
    try:
        db = sqlite3.connect(str(NEX_DIR / "nex.db"), timeout=2)
        rows = db.execute(
            "SELECT id, response, user_input, timestamp FROM reflexion_log "
            "ORDER BY timestamp DESC LIMIT 40"
        ).fetchall()
        db.close()
        replies = [
            {"id": r[0], "text": r[1], "context": r[2], "ts": r[3],
             "platform": _platform_from_context(r[2])}
            for r in rows if r[1]
        ]
    except Exception:
        pass
    return {"replies": replies}


@app.get("/agi")
async def get_agi():
    items = []
    try:
        db = sqlite3.connect(str(NEX_DIR / "nex.db"), timeout=2)
        try:
            rows = db.execute(
                "SELECT id, content, tier, timestamp FROM agi_watch_hits "
                "ORDER BY timestamp DESC LIMIT 30"
            ).fetchall()
            items = [{"id": r[0], "text": r[1], "tier": r[2], "ts": r[3]} for r in rows]
        except Exception:
            try:
                rows = db.execute(
                    "SELECT content, 2 AS tier, created_at FROM agi_corpus "
                    "ORDER BY created_at DESC LIMIT 30"
                ).fetchall()
                items = [{"text": r[0], "tier": r[1], "ts": r[2]} for r in rows]
            except Exception:
                pass
        db.close()
    except Exception:
        pass
    return {"hits": items, "badge": len(items)}


@app.get("/buf")
async def get_buf(channel: str = "stream", after: int = 0):
    rows = []
    try:
        c = sqlite3.connect(BUF_DB, timeout=2)
        rows = [
            {"id": r[0], "t": r[1], "src": r[2], "msg": r[3]}
            for r in c.execute(
                "SELECT id,ts,src,msg FROM events WHERE channel=? AND id>? "
                "ORDER BY id ASC LIMIT 30", (channel, after)
            ).fetchall()
        ]
        c.close()
    except Exception:
        pass
    return {"events": rows}


# ── SSE HUB — the key endpoint ──────────────────────────────────────────────

@app.get("/sse/hub")
async def sse_hub():
    """
    Single SSE connection with named events:
      event: col1  → YouTube feed
      event: col2  → Debug/brain log
      event: col3  → NEX responses (revolving platforms)
    """
    async def generate():
        # Tell browser to reconnect in 1s if dropped
        yield "retry: 1000\n\n"

        # Seed col1 with last 20 YouTube entries
        try:
            with open(str(FEED_PATH)) as ff:
                all_lines = ff.readlines()
            yt_seed = []
            for ll in all_lines[-200:]:
                try:
                    e = json.loads(ll)
                    if e.get("src") == "YOUTUBE":
                        msg = e.get("msg", "").replace("[YouTube]", "").strip()
                        if msg:
                            yt_seed.append({"t": e.get("t", ""), "msg": msg})
                except Exception:
                    pass
            for ye in yt_seed[-20:]:
                yield f"event: col1\ndata: {json.dumps(ye)}\n\n"
        except Exception:
            pass

        # Seed col3 with last 10 responses
        try:
            rdb = sqlite3.connect(str(NEX_DIR / "nex.db"), timeout=2)
            rrows = rdb.execute(
                "SELECT response,user_input,timestamp FROM reflexion_log "
                "ORDER BY id DESC LIMIT 10"
            ).fetchall()
            rdb.close()
            for rr in reversed(rrows):
                txt = (rr[0] or "").strip()
                ui = (rr[1] or "")
                if not txt:
                    continue
                ui_low = ui.lower()
                plat = "discord" if "discord" in ui_low else \
                       "mastodon" if ("mastodon" in ui_low or "@" in ui) else "moltbook"
                yield f"event: col3\ndata: {json.dumps({'t': str(rr[2] or ''), 'plat': plat, 'msg': txt[:300]})}\n\n"
        except Exception:
            pass

        # Track file positions
        fp = str(FEED_PATH)
        blog = "/tmp/nex_brain.log"
        off = os.path.getsize(fp) if os.path.exists(fp) else 0
        boff = max(0, os.path.getsize(blog) - 2000) if os.path.exists(blog) else 0
        last_resp_id = 0
        plat_cycle = ["moltbook", "discord", "mastodon"]
        plat_idx = 0
        tick = 0

        while True:
            tick += 1

            # Keepalive comment every 5s
            if tick % 17 == 0:
                yield ": keepalive\n\n"

            # Col1: new YouTube entries
            try:
                sz = os.path.getsize(fp) if os.path.exists(fp) else 0
                if sz < off:
                    off = 0
                if sz > off:
                    with open(fp, "rb") as f:
                        f.seek(off)
                        chunk = f.read(sz - off).decode("utf-8", errors="ignore")
                    off = sz
                    for line in chunk.splitlines():
                        try:
                            e = json.loads(line)
                            if e.get("src") != "YOUTUBE":
                                continue
                            msg = e.get("msg", "").replace("[YouTube]", "").strip()
                            if len(msg) < 5:
                                continue
                            yield f"event: col1\ndata: {json.dumps({'t': e.get('t', ''), 'msg': msg})}\n\n"
                        except Exception:
                            pass
            except Exception:
                pass

            # Col2: new brain log lines
            try:
                bsz = os.path.getsize(blog) if os.path.exists(blog) else 0
                if bsz < boff:
                    boff = 0
                if bsz > boff:
                    with open(blog, "rb") as f:
                        f.seek(boff)
                        bc = f.read(bsz - boff).decode("utf-8", errors="ignore")
                    boff = bsz
                    for bl in bc.splitlines():
                        bl = bl.strip()
                        if not bl or any(s in bl for s in _LOG_SKIP):
                            continue
                        bl = _ANSI.sub("", bl)
                        bl = _TS_PREFIX.sub("", bl).strip()
                        if len(bl) < 5:
                            continue
                        yield f"event: col2\ndata: {json.dumps({'msg': bl})}\n\n"
            except Exception:
                pass

            # Col3: new responses every ~2s
            if tick % 7 == 0:
                try:
                    rdb = sqlite3.connect(str(NEX_DIR / "nex.db"), timeout=1)
                    rrows = rdb.execute(
                        "SELECT id,response,user_input,timestamp FROM reflexion_log "
                        "WHERE id>? ORDER BY id ASC LIMIT 10",
                        (last_resp_id,)
                    ).fetchall()
                    rdb.close()
                    for rr in rrows:
                        last_resp_id = max(last_resp_id, rr[0])
                        txt = (rr[1] or "").strip()
                        if not txt:
                            continue
                        ui = (rr[2] or "")
                        ui_low = ui.lower()
                        plat = "discord" if "discord" in ui_low else \
                               "mastodon" if ("mastodon" in ui_low or "@" in ui) else "moltbook"
                        yield f"event: col3\ndata: {json.dumps({'t': str(rr[3] or ''), 'plat': plat, 'msg': txt[:300]})}\n\n"
                except Exception:
                    pass

            await asyncio.sleep(0.3)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


# ── LEGACY SSE ENDPOINTS (kept for compatibility) ───────────────────────────

@app.get("/sse/col2")
async def sse_col2():
    async def generate():
        off = max(0, os.path.getsize(str(LOG_PATH)) - 2000) if LOG_PATH.exists() else 0
        while True:
            sz = os.path.getsize(str(LOG_PATH)) if LOG_PATH.exists() else 0
            if sz < off: off = 0
            if sz > off:
                with open(str(LOG_PATH), "rb") as f:
                    f.seek(off)
                    chunk = f.read(sz - off).decode("utf-8", errors="ignore")
                off = sz
                for line in chunk.splitlines():
                    line = line.strip()
                    if not line or any(s in line for s in _LOG_SKIP): continue
                    line = _ANSI.sub('', line)
                    line = _TS_PREFIX.sub('', line).strip()
                    if len(line) < 5: continue
                    yield f"data: {json.dumps({'msg': line})}\n\n"
            yield ": keepalive\n\n"
            await asyncio.sleep(0.8)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/sse/activity")
async def sse_activity():
    async def generate():
        fp = str(FEED_PATH)
        off = max(0, os.path.getsize(fp) - 8000) if os.path.exists(fp) else 0
        eid = 0
        while True:
            sz = os.path.getsize(fp) if os.path.exists(fp) else 0
            if sz < off: off = 0
            if sz > off:
                with open(fp, "rb") as f:
                    f.seek(off)
                    chunk = f.read(sz - off).decode("utf-8", errors="ignore")
                off = sz
                for line in chunk.splitlines():
                    try:
                        e = json.loads(line)
                        if e.get("src") != "YOUTUBE": continue
                        msg = e.get("msg", "")
                        if len(msg) < 5: continue
                        eid += 1
                        yield f"id: {eid}\ndata: {json.dumps({'t': e.get('t',''), 'msg': msg})}\n\n"
                    except Exception:
                        pass
            yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── ENTRY POINT ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print(f"[NEX HUD] http://localhost:{PORT}", flush=True)
    uvicorn.run(app, host="localhost", port=PORT, log_level="warning")
