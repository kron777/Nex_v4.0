"""
nex_ws.py  —  WebSocket GUI bridge for NEX v1.2
------------------------------------------------
Drop this file into ~/Desktop/nex/ alongside run.py.

Usage in run.py:
    import nex_ws
    nex_ws.start()                     # call once at startup
    nex_ws.broadcast({"type":"feed", "data": {...}})  # call anywhere

Server runs on ws://localhost:8765 in a background thread.

8 message types the GUI handles:
  stats | feed | phase | agents | insights | reflection | self_assessment | sysmon

sysmon is emitted automatically every 3s (psutil + rocm-smi for AMD GPU).
"""

import asyncio
import json
import subprocess
import threading
import time
import psutil
import websockets

# ── internal state ─────────────────────────────────────────────────────────────
_clients    = set()
_loop       = None
_loop_ready = threading.Event()
_sysmon_uptime = 0

# ── core broadcast ─────────────────────────────────────────────────────────────
def broadcast(data: dict):
    """Thread-safe. Call from anywhere in run.py."""
    if _loop is None or not _loop.is_running():
        return
    msg = json.dumps(data)
    asyncio.run_coroutine_threadsafe(_ws_broadcast(msg), _loop)

async def _ws_broadcast(msg: str):
    dead = set()
    for ws in list(_clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)

# ── connection handler ─────────────────────────────────────────────────────────
async def _handler(websocket):
    _clients.add(websocket)
    print(f"[GUI] client connected ({len(_clients)} total)", flush=True)
    try:
        async for _ in websocket:
            pass
    except Exception:
        pass
    finally:
        _clients.discard(websocket)
        print(f"[GUI] client disconnected ({len(_clients)} total)", flush=True)

# ── GPU via rocm-smi (AMD RX 6600 LE) ─────────────────────────────────────────
def _gpu_pct() -> int:
    try:
        out = subprocess.run(
            ["rocm-smi", "--showuse", "--json"],
            capture_output=True, text=True, timeout=2
        ).stdout
        data = json.loads(out)
        for card in data.values():
            if isinstance(card, dict):
                val = card.get("GPU use (%)") or card.get("GPU Use (%)")
                if val is not None:
                    return int(float(str(val).replace("%","").strip()))
    except Exception:
        pass
    return -1  # -1 = unavailable

# ── llama-server stats ─────────────────────────────────────────────────────────
def _llama_stats() -> dict:
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:8080/metrics", timeout=1) as r:
            text = r.read().decode()
        tps = ctx = 0.0
        for line in text.splitlines():
            if line.startswith("llamacpp:tokens_per_second"):
                tps = float(line.split()[-1])
            elif line.startswith("llamacpp:kv_cache_tokens"):
                ctx = float(line.split()[-1])
        return {"tps": round(tps,1), "ctx": int(ctx)}
    except Exception:
        return {}

# ── sysmon loop ────────────────────────────────────────────────────────────────
async def _sysmon_loop():
    global _sysmon_uptime
    net_prev  = psutil.net_io_counters()
    prev_time = time.time()
    while True:
        await asyncio.sleep(3)
        try:
            cpu = round(psutil.cpu_percent(interval=None), 1)
            mem = psutil.virtual_memory()
            net = psutil.net_io_counters()
            now = time.time()
            dt  = max(now - prev_time, 0.001)
            rx  = int((net.bytes_recv - net_prev.bytes_recv) / dt / 1024)
            tx  = int((net.bytes_sent - net_prev.bytes_sent) / dt / 1024)
            net_prev  = net
            prev_time = now
            _sysmon_uptime += 3

            gpu = _gpu_pct()
            llm = _llama_stats()

            payload = {
                "type": "sysmon",
                "data": {
                    "cpu":          cpu,
                    "mem":          round(mem.percent, 1),
                    "mem_mb":       mem.used  // (1024*1024),
                    "mem_total_mb": mem.total // (1024*1024),
                    "net":          rx,
                    "net_ul":       tx,
                    "uptime":       _sysmon_uptime,
                }
            }
            if gpu >= 0:
                payload["data"]["gpu"] = gpu
            if llm:
                payload["data"].update(llm)

            await _ws_broadcast(json.dumps(payload))
        except Exception as e:
            print(f"[GUI] sysmon error: {e}", flush=True)

# ── server ─────────────────────────────────────────────────────────────────────
async def _server_main():
    global _loop
    _loop = asyncio.get_running_loop()
    _loop_ready.set()
    async with websockets.serve(_handler, "localhost", 8765):
        print("[GUI] ws://localhost:8765 ready", flush=True)
        asyncio.create_task(_sysmon_loop())
        await asyncio.Future()

def _thread_main():
    asyncio.run(_server_main())

def start():
    """Call once at the top of run.py main()."""
    t = threading.Thread(target=_thread_main, daemon=True, name="nex-ws")
    t.start()
    _loop_ready.wait(timeout=5)
    print("[GUI] WebSocket bridge started", flush=True)

# ── convenience emitters ───────────────────────────────────────────────────────
import datetime as _dt

def emit_stats(stats: dict):
    """stats = {beliefs, learnt, replied, chatted, answered, posted, reflects,
                agents, avg_conf, avg_align, high_conf}"""
    broadcast({"type": "stats", "data": stats})

def emit_feed(etype: str, agent: str, content: str):
    """etype: replied|chatted|posted|answered|learnt|reflect|system|error"""
    ts = _dt.datetime.now().strftime("%H:%M:%S")
    broadcast({"type": "feed", "data": {
        "type": etype, "agent": agent, "content": content, "ts": ts
    }})

def emit_phase(phase: str, remaining: int = 120):
    """phase: ABSORB|REPLY|ANSWER|CHAT|POST|REFLECT|COGNITION"""
    broadcast({"type": "phase", "data": {"phase": phase, "remaining": remaining}})

def emit_agents(agents: list):
    """agents: list of [handle, relation, cv]"""
    broadcast({"type": "agents", "data": agents})

def emit_insights(insights: list):
    """insights: list of {tag, conf, bel}"""
    broadcast({"type": "insights", "data": insights})

def emit_reflection(reflection: dict):
    """reflection: {ts, tags:[], text, sub, align}"""
    broadcast({"type": "reflection", "data": reflection})

def emit_self_assessment(data: dict):
    """data: {belief_conf, topic_align, high_conf, gaps:[]}"""
    broadcast({"type": "self_assessment", "data": data})
