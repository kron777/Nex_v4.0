#!/usr/bin/env python3
"""
nex_memory_api.py — Virtual Memory Filesystem API
==================================================
Deploy to: ~/Desktop/nex/nex/nex_memory_api.py

WHY THIS MATTERS (Grok's #10 done properly):

Grok said "Native memory filesystem — expose beliefs, opinions, contradictions
as /beliefs/, /stances/, /tensions/". That's the right idea but he imagined
a literal filesystem. The correct implementation for a running agent is a
lightweight HTTP API that exposes the same interface.

What this enables:
  - Your web GUI (nex-gui.html) can query live state without WebSocket hacks
  - nex1_tui.py can refresh belief counts without DB imports
  - External tools (n8n, webhook receivers, other agents) can query NEX's state
  - The /coherence and /status commands can pull from this instead of DB directly
  - Eventually: other NEX instances can query each other (multi-agent mode)

Endpoints:
  GET /status           — full system health JSON
  GET /beliefs?topic=X  — top beliefs on topic X
  GET /opinions?topic=X — NEX's formed opinion on topic X  
  GET /tensions         — active tensions (unresolved contradictions)
  GET /concepts         — concept graph summary
  GET /coherence        — audit log metrics
  GET /gaps             — recent conversation gaps
  GET /drives           — active drives state
  GET /memory           — working memory current state
  POST /query           — run kernel.process() via HTTP

Runs on port 8767 (avoids conflict with existing 8765/8766).
Starts as a daemon thread from run.py.

Grok improvement: Grok said "filesystem" — HTTP API is better because:
  1. No OS filesystem mounting required
  2. Cross-process, cross-language accessible
  3. Can be exposed to network for multi-agent queries
  4. JSON responses are immediately consumable by the existing web GUI
"""

from __future__ import annotations

import json
import sqlite3
import time
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Optional

_CFG     = Path("~/.config/nex").expanduser()
_DB_PATH = _CFG / "nex.db"
_PORT    = 8767


def _db() -> Optional[sqlite3.Connection]:
    if not _DB_PATH.exists():
        return None
    try:
        con = sqlite3.connect(str(_DB_PATH), timeout=2)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


def _json_response(data: dict | list) -> bytes:
    return json.dumps(data, default=str, indent=2).encode("utf-8")


# ── Endpoint handlers ─────────────────────────────────────────────────────────

def handle_status() -> dict:
    db = _db()
    result = {"beliefs": 0, "avg_conf": 0, "agents": 0, "tensions": 0,
              "opinions": 0, "uptime": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if not db:
        return result
    try:
        result["beliefs"]  = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        result["avg_conf"] = round(
            float(db.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0] or 0), 3
        )
        for tbl, key in [("agents","agents"), ("tensions","tensions"), ("opinions","opinions")]:
            try:
                result[key] = db.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            except Exception:
                pass
        db.close()
    except Exception:
        try: db.close()
        except: pass
    return result


def handle_beliefs(topic: str = "", limit: int = 10) -> list:
    db = _db()
    if not db:
        return []
    try:
        if topic:
            rows = db.execute(
                "SELECT id, content, confidence, topic FROM beliefs "
                "WHERE (topic LIKE ? OR content LIKE ?) AND content IS NOT NULL "
                "ORDER BY confidence DESC LIMIT ?",
                (f"%{topic}%", f"%{topic}%", limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, content, confidence, topic FROM beliefs "
                "WHERE content IS NOT NULL ORDER BY confidence DESC LIMIT ?",
                (limit,)
            ).fetchall()
        db.close()
        return [{"id": r["id"], "content": r["content"][:200],
                 "confidence": round(float(r["confidence"] or 0.5), 3),
                 "topic": r["topic"]} for r in rows]
    except Exception:
        try: db.close()
        except: pass
        return []


def handle_opinions(topic: str = "", limit: int = 10) -> list:
    db = _db()
    if not db:
        return []
    try:
        if topic:
            rows = db.execute(
                "SELECT topic, stance_score, strength, belief_ids FROM opinions "
                "WHERE topic LIKE ? ORDER BY strength DESC LIMIT ?",
                (f"%{topic}%", limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT topic, stance_score, strength FROM opinions "
                "ORDER BY strength DESC LIMIT ?", (limit,)
            ).fetchall()
        db.close()
        return [{"topic": r["topic"],
                 "stance": round(float(r["stance_score"] or 0), 3),
                 "strength": round(float(r["strength"] or 0), 3)} for r in rows]
    except Exception:
        try: db.close()
        except: pass
        return []


def handle_tensions(limit: int = 20) -> list:
    db = _db()
    if not db:
        return []
    try:
        rows = db.execute(
            "SELECT topic, description, weight, cycle_count FROM tensions "
            "WHERE resolved_at IS NULL ORDER BY weight DESC LIMIT ?", (limit,)
        ).fetchall()
        db.close()
        return [{"topic": r["topic"],
                 "description": (r["description"] or "")[:100],
                 "weight": round(float(r["weight"] or 0), 3),
                 "cycles": r["cycle_count"]} for r in rows]
    except Exception:
        try: db.close()
        except: pass
        return []


def handle_coherence() -> dict:
    met_path = _CFG / "coherence_metrics.json"
    if met_path.exists():
        try:
            return json.loads(met_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"error": "audit log not yet populated"}


def handle_concepts() -> dict:
    graph_path = _CFG / "concept_graph.json"
    if graph_path.exists():
        try:
            g = json.loads(graph_path.read_text(encoding="utf-8"))
            return {
                "meta":     g.get("meta", {}),
                "concepts": list(g.get("concepts", {}).keys()),
            }
        except Exception:
            pass
    return {"error": "concept graph not yet built"}


def handle_gaps(limit: int = 10) -> list:
    gap_path = _CFG / "conversation_gaps.jsonl"
    if not gap_path.exists():
        return []
    try:
        lines = gap_path.read_text(encoding="utf-8").splitlines()
        gaps  = []
        for line in reversed(lines[-100:]):
            try:
                gaps.append(json.loads(line))
            except Exception:
                pass
            if len(gaps) >= limit:
                break
        return gaps
    except Exception:
        return []


def handle_drives() -> dict:
    drives_path = _CFG / "nex_drives.json"
    if drives_path.exists():
        try:
            data = json.loads(drives_path.read_text(encoding="utf-8"))
            return {
                "active":  data.get("active", {}),
                "primary": [
                    {"label": d.get("label"), "intensity": d.get("intensity")}
                    for d in data.get("primary", [])[:5]
                ],
            }
        except Exception:
            pass
    return {"error": "drives not available"}


def handle_memory() -> dict:
    wm_path = _CFG / "working_memory.json"
    if wm_path.exists():
        try:
            data   = json.loads(wm_path.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
            recent  = entries[-3:] if entries else []
            return {
                "turns":  len(entries),
                "recent": [
                    {"ts":     e.get("ts", "")[:19],
                     "intent": e.get("intent", ""),
                     "topic":  e.get("topic", ""),
                     "query":  e.get("clean", e.get("query", ""))[:60]}
                    for e in recent
                ],
                "active_topic":   entries[-1].get("topic", "") if entries else "",
                "active_concept": entries[-1].get("concept", "") if entries else "",
            }
        except Exception:
            pass
    return {"turns": 0, "recent": [], "active_topic": "", "active_concept": ""}


def handle_query(body: bytes) -> dict:
    """POST /query — run kernel.process() and return response."""
    try:
        data  = json.loads(body.decode("utf-8"))
        query = data.get("query", "").strip()
        if not query:
            return {"error": "query field required"}

        # Import kernel lazily to avoid circular imports at startup
        from nex.nex_kernel import get_kernel
        k      = get_kernel()
        reply  = k.process(query)
        status = k.status()
        return {"query": query, "reply": reply, "status": status}
    except Exception as exc:
        return {"error": str(exc)}


# ── HTTP handler ──────────────────────────────────────────────────────────────

class NexMemoryHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # silence access log

    def _send(self, data: dict | list, status: int = 200):
        body = _json_response(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        path   = parsed.path.rstrip("/")

        routes = {
            "/status":    lambda: handle_status(),
            "/beliefs":   lambda: handle_beliefs(params.get("topic",""), int(params.get("limit",10))),
            "/opinions":  lambda: handle_opinions(params.get("topic",""), int(params.get("limit",10))),
            "/tensions":  lambda: handle_tensions(int(params.get("limit",20))),
            "/coherence": lambda: handle_coherence(),
            "/concepts":  lambda: handle_concepts(),
            "/gaps":      lambda: handle_gaps(int(params.get("limit",10))),
            "/drives":    lambda: handle_drives(),
            "/memory":    lambda: handle_memory(),
        }

        handler = routes.get(path)
        if handler:
            try:
                self._send(handler())
            except Exception as exc:
                self._send({"error": str(exc)}, 500)
        else:
            self._send({
                "endpoints": list(routes.keys()) + ["/query (POST)"],
                "port": _PORT,
            })

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)

        if path == "/query":
            try:
                self._send(handle_query(body))
            except Exception as exc:
                self._send({"error": str(exc)}, 500)
        else:
            self._send({"error": "unknown endpoint"}, 404)


# ── Server lifecycle ──────────────────────────────────────────────────────────

_server: Optional[HTTPServer] = None

def start_memory_api(port: int = _PORT, daemon: bool = True) -> bool:
    """Start the memory API server in a daemon thread."""
    global _server
    if _server:
        return True
    try:
        import socket
        # Check if port already in use
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        in_use = s.connect_ex(("127.0.0.1", port)) == 0
        s.close()
        if in_use:
            return True  # already running

        _server = HTTPServer(("127.0.0.1", port), NexMemoryHandler)
        t = threading.Thread(target=_server.serve_forever, daemon=daemon)
        t.start()
        print(f"  [MemoryAPI] http://localhost:{port}/ — 9 endpoints active")
        return True
    except Exception as exc:
        print(f"  [MemoryAPI] Failed to start: {exc}")
        return False


def stop_memory_api():
    global _server
    if _server:
        _server.shutdown()
        _server = None


if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        # Quick endpoint test
        import urllib.request
        start_memory_api(daemon=False)
        time.sleep(0.5)

        for endpoint in ["/status", "/beliefs?topic=consciousness&limit=3",
                         "/opinions", "/tensions", "/coherence", "/memory"]:
            try:
                url  = f"http://localhost:{_PORT}{endpoint}"
                resp = urllib.request.urlopen(url, timeout=3)
                data = json.loads(resp.read())
                print(f"  ✓  {endpoint}: {str(data)[:80]}")
            except Exception as exc:
                print(f"  ✗  {endpoint}: {exc}")
    else:
        print(f"Starting NEX Memory API on port {_PORT}...")
        print(f"Endpoints: /status /beliefs /opinions /tensions /coherence /concepts /gaps /drives /memory")
        print(f"POST: /query")
        start_memory_api(daemon=False)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            stop_memory_api()
