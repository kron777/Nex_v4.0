#!/usr/bin/env python3
"""
nex_dashboard.py — NEX Web Dashboard v1.0
Serves a live monitoring dashboard on port 7824.
Pulls data from NEX API on port 7823.
"""
import os, sys, json, time, sqlite3, threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

NEX_PATH = os.path.expanduser("~/Desktop/nex")
sys.path.insert(0, NEX_PATH)

try:
    from flask import Flask, jsonify, render_template_string
    from flask_cors import CORS
except ImportError:
    os.system(f"{sys.executable} -m pip install flask flask-cors --quiet")
    from flask import Flask, jsonify, render_template_string
    from flask_cors import CORS

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"
AUDIT_DB_PATH = Path("~/.config/nex/audit.db").expanduser()
SESSIONS_PATH = Path("~/.config/nex/sessions.json").expanduser()
API_KEY_PATH  = Path("~/.config/nex/api_keys.json").expanduser()
DASH_PORT     = 7824
NEX_API_PORT  = 7823

app = Flask("nex_dashboard")
CORS(app)

# ── Data helpers ──────────────────────────────────────────────────────────────

def get_api_key():
    try:
        keys = json.loads(API_KEY_PATH.read_text())
        return list(keys.keys())[0] if keys else None
    except:
        return None

def db_query(sql, params=()):
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except:
        return []

def db_scalar(sql, params=()):
    try:
        conn = sqlite3.connect(str(DB_PATH))
        val = conn.execute(sql, params).fetchone()[0]
        conn.close()
        return val
    except:
        return 0

def audit_query(sql, params=()):
    try:
        conn = sqlite3.connect(str(AUDIT_DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except:
        return []

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

# ── API routes for dashboard data ─────────────────────────────────────────────

@app.route("/dash/stats")
def dash_stats():
    total      = db_scalar("SELECT COUNT(*) FROM beliefs")
    hi_conf    = db_scalar("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.8")
    topics     = db_query("SELECT topic, COUNT(*) as count FROM beliefs GROUP BY topic ORDER BY count DESC LIMIT 10")
    sources    = db_scalar("SELECT COUNT(DISTINCT source) FROM beliefs")
    sessions   = {}
    try:
        sessions = json.loads(SESSIONS_PATH.read_text()) if SESSIONS_PATH.exists() else {}
    except:
        pass
    keys = {}
    try:
        keys = json.loads(API_KEY_PATH.read_text()) if API_KEY_PATH.exists() else {}
    except:
        pass
    total_requests = sum(v.get("requests", 0) for v in keys.values())

    # Quality scorer data from nex_belief_quality if available
    avg_quality  = None
    quality_dist = None
    scored_by    = "confidence_fallback"
    try:
        has_qs = db_scalar(
            "SELECT COUNT(*) FROM pragma_table_info('beliefs') WHERE name='quality_score'"
        )
        if has_qs:
            avg_quality = round(float(db_scalar(
                "SELECT AVG(quality_score) FROM beliefs WHERE quality_score IS NOT NULL"
            ) or 0), 3)
            quality_dist = {
                "elite":  db_scalar("SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.70"),
                "high":   db_scalar("SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.50 AND quality_score < 0.70"),
                "medium": db_scalar("SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.30 AND quality_score < 0.50"),
                "low":    db_scalar("SELECT COUNT(*) FROM beliefs WHERE quality_score < 0.30"),
            }
            scored_by = "quality_scorer"
    except Exception:
        pass

    return jsonify({
        "total_beliefs":    total,
        "hi_conf_beliefs":  hi_conf,
        "unique_sources":   sources,
        "active_sessions":  len(sessions),
        "total_requests":   total_requests,
        "avg_quality":      avg_quality,
        "quality_dist":     quality_dist,
        "scored_by":        scored_by,
        "timestamp":        _now_iso()
    })

@app.route("/dash/topics")
def dash_topics():
    rows = db_query(
        "SELECT topic, COUNT(*) as count, AVG(confidence) as avg_conf "
        "FROM beliefs GROUP BY topic ORDER BY count DESC LIMIT 12"
    )
    return jsonify(rows)

@app.route("/dash/belief-growth")
def dash_belief_growth():
    """Simulate belief growth timeline from DB rowids as proxy for insertion order."""
    total = db_scalar("SELECT COUNT(*) FROM beliefs")
    if total == 0:
        return jsonify([])
    # Sample 20 evenly-spaced points across belief IDs
    rows = db_query("SELECT id FROM beliefs ORDER BY id ASC")
    if not rows:
        return jsonify([])
    ids   = [r["id"] for r in rows]
    n     = min(20, len(ids))
    step  = max(1, len(ids) // n)
    points = []
    for i, idx in enumerate(range(0, len(ids), step)):
        points.append({"x": i + 1, "y": idx + 1, "label": f"Point {i+1}"})
    points.append({"x": len(points) + 1, "y": total, "label": "Now"})
    return jsonify(points)

@app.route("/dash/gaps")
def dash_gaps():
    rows = db_query(
        "SELECT topic, gap_description, priority FROM curiosity_gaps "
        "ORDER BY priority DESC LIMIT 15"
    )
    return jsonify(rows)

@app.route("/dash/domain-activity")
def dash_domain_activity():
    TARGET  = 200
    domains = ["oncology","cardiology","finance","legal","ai","climate","neuroscience"]
    result  = []
    for d in domains:
        # Exact topic match — avoids overcounting from source LIKE
        count = db_scalar(
            "SELECT COUNT(*) FROM beliefs WHERE topic = ?", (d,)
        )
        result.append({
            "domain": d,
            "count":  count,
            "target": TARGET,
            "gap":    max(0, TARGET - count),
            "pct":    round(min(count / TARGET, 1.0) * 100, 1),
            "done":   count >= TARGET,
        })
    result.sort(key=lambda x: -x["count"])
    return jsonify(result)

@app.route("/dash/saturation")
def dash_saturation():
    """Proxy scheduler saturation status for dashboard. Falls back to DB counts."""
    TARGET  = 200
    domains = ["oncology","cardiology","finance","legal","ai","climate","neuroscience"]
    try:
        import requests as req
        r = req.get("http://localhost:7825/scheduler/status", timeout=2)
        if r.status_code == 200:
            data = r.json()
            return jsonify({
                "status":       data.get("status", "unknown"),
                "last_run":     data.get("saturation", {}).get("last_run"),
                "domain_status": data.get("saturation", {}).get("domain_status", {}),
                "total_beliefs": data.get("total_beliefs", 0),
            })
    except Exception:
        pass
    # Fallback: read directly from DB
    domain_status = {}
    for d in domains:
        count = db_scalar("SELECT COUNT(*) FROM beliefs WHERE topic = ?", (d,))
        domain_status[d] = {"count": count, "gap": max(0, TARGET - count), "done": count >= TARGET}
    return jsonify({"status": "unknown", "last_run": None, "domain_status": domain_status})

@app.route("/dash/recent-audit")
def dash_recent_audit():
    rows = audit_query(
        "SELECT ts, endpoint, method, status_code, latency_ms, query "
        "FROM audit_log ORDER BY ts DESC LIMIT 20"
    )
    return jsonify(rows)

@app.route("/dash/sources")
def dash_sources():
    rows = db_query(
        "SELECT source, COUNT(*) as count, AVG(confidence) as avg_conf "
        "FROM beliefs GROUP BY source ORDER BY count DESC LIMIT 10"
    )
    return jsonify(rows)

@app.route("/dash/webhooks")
def dash_webhooks():
    """Return webhook delivery stats from api_keys.json."""
    try:
        keys = json.loads(API_KEY_PATH.read_text()) if API_KEY_PATH.exists() else {}
        webhooks_path = Path("~/.config/nex/webhooks.json").expanduser()
        hooks = json.loads(webhooks_path.read_text()) if webhooks_path.exists() else {}
        stats = []
        for wid, w in hooks.items():
            stats.append({
                "id":           wid,
                "url":          w.get("url","")[:60],
                "events":       w.get("events", []),
                "deliveries":   w.get("deliveries", 0),
                "failures":     w.get("failures", 0),
                "last_fired":   w.get("last_fired", "—"),
                "api_key":      w.get("api_key","")[:12] + "...",
            })
        stats.sort(key=lambda x: -x["deliveries"])
        return jsonify({"webhooks": stats, "count": len(stats)})
    except Exception as e:
        return jsonify({"webhooks": [], "count": 0, "error": str(e)})

# ── Dashboard HTML ─────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEX — Intelligence Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@300;400;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
  :root {
    --bg:        #080b0f;
    --bg2:       #0d1117;
    --bg3:       #111820;
    --border:    #1a2535;
    --accent:    #00ffe1;
    --accent2:   #0066ff;
    --accent3:   #ff3e6c;
    --gold:      #f0b429;
    --text:      #c8d8e8;
    --text-dim:  #4a6080;
    --text-mono: #7ab8d0;
    --glow:      0 0 12px rgba(0,255,225,0.25);
    --glow2:     0 0 20px rgba(0,102,255,0.2);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Rajdhani', sans-serif;
    font-size: 15px;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* Scanline overlay */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0,0,0,0.08) 2px,
      rgba(0,0,0,0.08) 4px
    );
    pointer-events: none;
    z-index: 1000;
  }

  /* Grid noise texture */
  body::after {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      radial-gradient(ellipse at 20% 50%, rgba(0,102,255,0.04) 0%, transparent 60%),
      radial-gradient(ellipse at 80% 20%, rgba(0,255,225,0.04) 0%, transparent 50%);
    pointer-events: none;
    z-index: 0;
  }

  /* ── Header ── */
  header {
    position: relative;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 18px 32px;
    border-bottom: 1px solid var(--border);
    background: rgba(8,11,15,0.95);
    backdrop-filter: blur(10px);
  }

  .logo {
    display: flex;
    align-items: baseline;
    gap: 12px;
  }

  .logo-nex {
    font-family: 'Share Tech Mono', monospace;
    font-size: 28px;
    color: var(--accent);
    text-shadow: var(--glow);
    letter-spacing: 6px;
  }

  .logo-sub {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-dim);
    letter-spacing: 3px;
    text-transform: uppercase;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 24px;
  }

  .status-pill {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 5px 14px;
    border: 1px solid var(--accent);
    border-radius: 2px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    color: var(--accent);
    letter-spacing: 2px;
  }

  .pulse-dot {
    width: 7px;
    height: 7px;
    background: var(--accent);
    border-radius: 50%;
    box-shadow: 0 0 8px var(--accent);
    animation: pulse 2s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%       { opacity: 0.4; transform: scale(0.8); }
  }

  .clock {
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    color: var(--text-dim);
    letter-spacing: 2px;
  }

  /* ── Stat bar ── */
  .stat-bar {
    position: relative;
    z-index: 10;
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    border-bottom: 1px solid var(--border);
  }

  .stat-item {
    padding: 16px 24px;
    border-right: 1px solid var(--border);
    position: relative;
    overflow: hidden;
    transition: background 0.3s;
  }

  .stat-item:last-child { border-right: none; }

  .stat-item::before {
    content: '';
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 2px;
    background: var(--accent2);
    transform: scaleX(0);
    transition: transform 0.4s ease;
    transform-origin: left;
  }

  .stat-item:hover::before { transform: scaleX(1); }
  .stat-item:hover { background: rgba(0,102,255,0.04); }

  .stat-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 3px;
    color: var(--text-dim);
    text-transform: uppercase;
    margin-bottom: 6px;
  }

  .stat-value {
    font-family: 'Share Tech Mono', monospace;
    font-size: 28px;
    color: var(--accent);
    text-shadow: var(--glow);
    transition: all 0.5s ease;
  }

  .stat-sub {
    font-size: 11px;
    color: var(--text-dim);
    margin-top: 2px;
    font-family: 'Share Tech Mono', monospace;
  }

  /* ── Main grid ── */
  .main-grid {
    position: relative;
    z-index: 10;
    display: grid;
    grid-template-columns: 1fr 1fr 360px;
    grid-template-rows: auto auto;
    gap: 1px;
    background: var(--border);
    margin: 0;
  }

  .panel {
    background: var(--bg2);
    padding: 24px;
    position: relative;
    overflow: hidden;
  }

  .panel::after {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--accent2), transparent);
    opacity: 0.4;
  }

  .panel-full  { grid-column: 1 / -1; }
  .panel-wide  { grid-column: 1 / 3; }
  .panel-right { grid-column: 3; }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20px;
  }

  .panel-title {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 4px;
    color: var(--text-dim);
    text-transform: uppercase;
  }

  .panel-title span {
    color: var(--accent2);
    margin-right: 8px;
  }

  .panel-badge {
    font-family: 'Share Tech Mono', monospace;
    font-size: 10px;
    color: var(--accent);
    letter-spacing: 1px;
    opacity: 0.6;
  }

  /* ── Chart containers ── */
  .chart-wrap {
    position: relative;
    height: 220px;
  }

  /* ── Topic bars ── */
  .topic-list { display: flex; flex-direction: column; gap: 8px; }

  .topic-row {
    display: grid;
    grid-template-columns: 100px 1fr 50px;
    align-items: center;
    gap: 10px;
  }

  .topic-name {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    color: var(--text-mono);
    text-transform: uppercase;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .topic-bar-wrap {
    height: 6px;
    background: var(--bg3);
    border-radius: 1px;
    overflow: hidden;
  }

  .topic-bar {
    height: 100%;
    border-radius: 1px;
    transition: width 1s cubic-bezier(0.4,0,0.2,1);
  }

  .topic-count {
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    color: var(--text-dim);
    text-align: right;
  }

  /* ── Domain heatmap ── */
  .domain-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
  }

  .domain-cell {
    padding: 14px 10px;
    border: 1px solid var(--border);
    border-radius: 2px;
    text-align: center;
    position: relative;
    overflow: hidden;
    transition: all 0.3s;
    cursor: default;
  }

  .domain-cell::before {
    content: '';
    position: absolute;
    inset: 0;
    opacity: 0.12;
    transition: opacity 0.3s;
  }

  .domain-cell:hover::before { opacity: 0.22; }
  .domain-cell:hover { border-color: var(--accent2); transform: translateY(-2px); }

  .domain-name {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--text-dim);
    margin-bottom: 6px;
  }

  .domain-count {
    font-family: 'Share Tech Mono', monospace;
    font-size: 22px;
    font-weight: 400;
  }

  /* ── Gaps table ── */
  .gaps-list { display: flex; flex-direction: column; gap: 6px; max-height: 280px; overflow-y: auto; }

  .gaps-list::-webkit-scrollbar { width: 3px; }
  .gaps-list::-webkit-scrollbar-track { background: var(--bg3); }
  .gaps-list::-webkit-scrollbar-thumb { background: var(--accent2); }

  .gap-row {
    display: grid;
    grid-template-columns: 80px 1fr 32px;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    background: var(--bg3);
    border-left: 2px solid transparent;
    transition: all 0.2s;
    border-radius: 1px;
  }

  .gap-row:hover { border-left-color: var(--accent3); background: rgba(255,62,108,0.05); }

  .gap-topic {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--accent3);
  }

  .gap-desc {
    font-size: 12px;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .gap-priority {
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    color: var(--gold);
    text-align: right;
  }

  .no-gaps {
    font-family: 'Share Tech Mono', monospace;
    font-size: 12px;
    color: var(--text-dim);
    padding: 20px;
    text-align: center;
    letter-spacing: 2px;
  }

  /* ── Sources list ── */
  .sources-list { display: flex; flex-direction: column; gap: 5px; max-height: 260px; overflow-y: auto; }

  .source-row {
    display: grid;
    grid-template-columns: 1fr 40px;
    align-items: center;
    gap: 8px;
    padding: 7px 10px;
    background: var(--bg3);
    border-radius: 1px;
    transition: background 0.2s;
  }

  .source-row:hover { background: rgba(0,102,255,0.08); }

  .source-name {
    font-size: 11px;
    color: var(--text-mono);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .source-count {
    font-family: 'Share Tech Mono', monospace;
    font-size: 12px;
    color: var(--accent2);
    text-align: right;
  }

  /* ── Audit feed ── */
  .audit-feed { display: flex; flex-direction: column; gap: 4px; max-height: 300px; overflow-y: auto; }

  .audit-feed::-webkit-scrollbar { width: 3px; }
  .audit-feed::-webkit-scrollbar-thumb { background: var(--accent2); }

  .audit-row {
    display: grid;
    grid-template-columns: 70px 45px 1fr 55px;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    background: var(--bg3);
    border-radius: 1px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    transition: background 0.2s;
  }

  .audit-row:hover { background: rgba(0,255,225,0.04); }

  .audit-time { color: var(--text-dim); }
  .audit-method { color: var(--gold); }
  .audit-endpoint { color: var(--text-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .audit-status { text-align: right; }
  .status-200 { color: var(--accent); }
  .status-4xx { color: var(--accent3); }

  .audit-empty {
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    color: var(--text-dim);
    padding: 16px;
    text-align: center;
    letter-spacing: 2px;
  }

  /* ── Footer ── */
  footer {
    position: relative;
    z-index: 10;
    padding: 12px 32px;
    border-top: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .footer-left {
    font-family: 'Share Tech Mono', monospace;
    font-size: 10px;
    color: var(--text-dim);
    letter-spacing: 2px;
  }

  .footer-right {
    font-family: 'Share Tech Mono', monospace;
    font-size: 10px;
    color: var(--text-dim);
    letter-spacing: 1px;
  }

  /* ── Refresh indicator ── */
  .refresh-bar {
    position: fixed;
    bottom: 0; left: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--accent2), var(--accent));
    width: 0%;
    z-index: 9999;
    transition: width linear;
  }

  /* ── Animations ── */
  @keyframes fadeInUp {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  .panel { animation: fadeInUp 0.5s ease both; }
  .panel:nth-child(1) { animation-delay: 0.05s; }
  .panel:nth-child(2) { animation-delay: 0.10s; }
  .panel:nth-child(3) { animation-delay: 0.15s; }
  .panel:nth-child(4) { animation-delay: 0.20s; }
  .panel:nth-child(5) { animation-delay: 0.25s; }
  .panel:nth-child(6) { animation-delay: 0.30s; }

  /* iq meter */
  .iq-block {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 14px 20px;
    border: 1px solid var(--border);
    background: var(--bg3);
    border-radius: 2px;
  }

  .iq-label {
    font-size: 10px;
    letter-spacing: 3px;
    font-weight: 700;
    color: var(--text-dim);
    text-transform: uppercase;
    white-space: nowrap;
  }

  .iq-bar-wrap {
    flex: 1;
    height: 6px;
    background: var(--bg);
    border-radius: 1px;
    overflow: hidden;
  }

  .iq-bar {
    height: 100%;
    width: 92%;
    background: linear-gradient(90deg, var(--accent2), var(--accent));
    box-shadow: 0 0 10px rgba(0,255,225,0.4);
    border-radius: 1px;
  }

  .iq-value {
    font-family: 'Share Tech Mono', monospace;
    font-size: 16px;
    color: var(--accent);
    white-space: nowrap;
  }
</style>
</head>
<body>

<div class="refresh-bar" id="refreshBar"></div>

<!-- Header -->
<header>
  <div class="logo">
    <div class="logo-nex">NEX</div>
    <div class="logo-sub">Intelligence Dashboard · v4.0</div>
  </div>
  <div class="header-right">
    <div class="status-pill">
      <div class="pulse-dot"></div>
      ONLINE
    </div>
    <div class="clock" id="clock">--:--:--</div>
  </div>
</header>

<!-- Stat bar -->
<div class="stat-bar">
  <div class="stat-item">
    <div class="stat-label">Total Beliefs</div>
    <div class="stat-value" id="statBeliefs">—</div>
    <div class="stat-sub" id="statHiConf">— high confidence</div>
  </div>
  <div class="stat-item">
    <div class="stat-label">Unique Sources</div>
    <div class="stat-value" id="statSources">—</div>
    <div class="stat-sub">absorbed</div>
  </div>
  <div class="stat-item">
    <div class="stat-label">Active Sessions</div>
    <div class="stat-value" id="statSessions">—</div>
    <div class="stat-sub">this hour</div>
  </div>
  <div class="stat-item">
    <div class="stat-label">API Requests</div>
    <div class="stat-value" id="statRequests">—</div>
    <div class="stat-sub">total</div>
  </div>
  <div class="stat-item">
    <div class="stat-label">NEX IQ</div>
    <div class="stat-value" id="statIQVal" style="color:var(--gold)">—</div>
    <div class="stat-sub" id="statIQLabel" style="color:var(--gold)">ELITE</div>
  </div>
</div>

<!-- IQ bar -->
<div style="padding: 16px 1px 0; background: var(--border); position:relative;z-index:10;">
  <div style="background:var(--bg2);padding:16px 24px;">
    <div class="iq-block">
      <div class="iq-label">Cognitive Rating</div>
      <div class="iq-bar-wrap"><div class="iq-bar" id="iqBar"></div></div>
      <div class="iq-value" id="iqValue">— · —</div>
    </div>
  </div>
</div>

<!-- Main grid -->
<div class="main-grid">

  <!-- Belief Growth -->
  <div class="panel panel-wide">
    <div class="panel-header">
      <div class="panel-title"><span>01</span>Belief Growth</div>
      <div class="panel-badge" id="growthBadge">loading...</div>
    </div>
    <div class="chart-wrap">
      <canvas id="growthChart"></canvas>
    </div>
  </div>

  <!-- Domain Saturation -->
  <div class="panel panel-right">
    <div class="panel-header">
      <div class="panel-title"><span>02</span>Domain Saturation</div>
      <div class="panel-badge">target: 200</div>
    </div>
    <div class="domain-grid" id="domainGrid">
      <!-- populated by JS -->
    </div>
  </div>

  <!-- Topic Distribution -->
  <div class="panel">
    <div class="panel-header">
      <div class="panel-title"><span>03</span>Topic Distribution</div>
      <div class="panel-badge" id="topicBadge"></div>
    </div>
    <div class="topic-list" id="topicList"></div>
  </div>

  <!-- Curiosity Gaps -->
  <div class="panel">
    <div class="panel-header">
      <div class="panel-title"><span>04</span>Curiosity Gaps</div>
      <div class="panel-badge" id="gapBadge"></div>
    </div>
    <div class="gaps-list" id="gapsList"></div>
  </div>

  <!-- Top Sources -->
  <div class="panel panel-right">
    <div class="panel-header">
      <div class="panel-title"><span>05</span>Top Sources</div>
    </div>
    <div class="sources-list" id="sourcesList"></div>
  </div>

  <!-- Audit Feed -->
  <div class="panel panel-full">
    <div class="panel-header">
      <div class="panel-title"><span>06</span>Recent API Activity</div>
      <div class="panel-badge" id="auditBadge">audit trail</div>
    </div>
    <div class="audit-feed" id="auditFeed"></div>
  </div>
  <div class="panel panel-full">
    <div class="panel-header">
      <div class="panel-title"><span>07</span>Webhook Delivery</div>
      <div class="panel-badge" id="webhookBadge">delivery stats</div>
    </div>
    <div class="audit-feed" id="webhookFeed"></div>
  </div>

</div>

<footer>
  <div class="footer-left">NEX v4.0 · ZORIN/UBUNTU · AMD RX 6600 · MISTRAL-7B Q4_K_M</div>
  <div class="footer-right" id="footerTs">last updated —</div>
</footer>

<script>
// ── Clock ──────────────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toUTCString().slice(17, 25) + ' UTC';
}
setInterval(updateClock, 1000);
updateClock();

// ── Chart setup ────────────────────────────────────────────────────────────
Chart.defaults.color = '#4a6080';
Chart.defaults.borderColor = '#1a2535';
Chart.defaults.font.family = "'Share Tech Mono', monospace";
Chart.defaults.font.size = 11;

let growthChart = null;

function initGrowthChart(data) {
  const ctx = document.getElementById('growthChart').getContext('2d');
  if (growthChart) growthChart.destroy();

  const gradient = ctx.createLinearGradient(0, 0, 0, 220);
  gradient.addColorStop(0, 'rgba(0,255,225,0.18)');
  gradient.addColorStop(1, 'rgba(0,255,225,0)');

  growthChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.map(d => d.label),
      datasets: [{
        data: data.map(d => d.y),
        borderColor: '#00ffe1',
        borderWidth: 2,
        backgroundColor: gradient,
        fill: true,
        tension: 0.4,
        pointBackgroundColor: '#00ffe1',
        pointRadius: 3,
        pointHoverRadius: 6,
        pointBorderColor: '#080b0f',
        pointBorderWidth: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 800, easing: 'easeInOutQuart' },
      plugins: { legend: { display: false }, tooltip: {
        backgroundColor: '#0d1117',
        borderColor: '#1a2535',
        borderWidth: 1,
        titleColor: '#00ffe1',
        bodyColor: '#c8d8e8',
        callbacks: { label: ctx => ` ${ctx.parsed.y.toLocaleString()} beliefs` }
      }},
      scales: {
        x: { grid: { color: '#111820' }, ticks: { maxTicksLimit: 8 } },
        y: { grid: { color: '#111820' }, ticks: {
          callback: v => v >= 1000 ? (v/1000).toFixed(1)+'k' : v
        }}
      }
    }
  });
}

// ── Colour palette ─────────────────────────────────────────────────────────
const PALETTE = [
  '#00ffe1','#0066ff','#7c3aed','#f0b429',
  '#ff3e6c','#10b981','#f97316','#06b6d4',
  '#8b5cf6','#ec4899','#14b8a6','#a3e635'
];

const DOMAIN_COLORS = {
  ai:           '#00ffe1',
  neuroscience: '#7c3aed',
  oncology:     '#ff3e6c',
  cardiology:   '#f0b429',
  finance:      '#10b981',
  legal:        '#0066ff',
  climate:      '#06b6d4'
};

// ── Render functions ───────────────────────────────────────────────────────
function renderStats(d) {
  animateNumber('statBeliefs', d.total_beliefs);
  animateNumber('statSources', d.unique_sources);
  animateNumber('statSessions', d.active_sessions);
  animateNumber('statRequests', d.total_requests);
  document.getElementById('statHiConf').textContent =
    `${d.hi_conf_beliefs} high confidence`;
  document.getElementById('footerTs').textContent =
    'last updated ' + new Date().toLocaleTimeString();
}

function animateNumber(id, target) {
  const el = document.getElementById(id);
  const start = parseInt(el.textContent.replace(/\D/g,'')) || 0;
  const diff = target - start;
  const steps = 30;
  let step = 0;
  const timer = setInterval(() => {
    step++;
    const val = Math.round(start + diff * (step / steps));
    el.textContent = val.toLocaleString();
    if (step >= steps) clearInterval(timer);
  }, 16);
}

function renderTopics(rows) {
  const max = rows[0]?.count || 1;
  const list = document.getElementById('topicList');
  list.innerHTML = rows.map((r, i) => `
    <div class="topic-row">
      <div class="topic-name">${r.topic || '—'}</div>
      <div class="topic-bar-wrap">
        <div class="topic-bar" style="width:${(r.count/max*100).toFixed(1)}%;background:${PALETTE[i%PALETTE.length]};box-shadow:0 0 6px ${PALETTE[i%PALETTE.length]}44"></div>
      </div>
      <div class="topic-count">${r.count}</div>
    </div>
  `).join('');
  document.getElementById('topicBadge').textContent = `${rows.length} topics`;
}

function renderDomains(rows) {
  const TARGET = 200;
  const grid   = document.getElementById('domainGrid');
  grid.innerHTML = rows.map(r => {
    const color   = DOMAIN_COLORS[r.domain] || '#4a6080';
    const pct     = r.pct ?? Math.min((r.count / TARGET) * 100, 100);
    const done    = r.done ?? r.count >= TARGET;
    const gap     = r.gap  ?? Math.max(0, TARGET - r.count);
    const barCol  = done ? '#10b981' : (pct > 50 ? color : '#ff3e6c');
    const status  = done ? '✓' : `${gap} to go`;
    return `
      <div class="domain-cell" style="border-color:${color}33;padding:12px 10px;">
        <div class="domain-name" style="position:relative;color:${done ? '#10b981' : 'var(--text-dim)'}">
          ${r.domain}
        </div>
        <div class="domain-count" style="position:relative;color:${barCol};text-shadow:0 0 10px ${barCol}66;font-size:18px">
          ${r.count}
        </div>
        <div style="margin-top:6px;height:3px;background:var(--bg);border-radius:1px;overflow:hidden;">
          <div style="height:100%;width:${pct}%;background:${barCol};transition:width 1s ease;border-radius:1px;box-shadow:0 0 4px ${barCol}88;"></div>
        </div>
        <div style="font-family:'Share Tech Mono',monospace;font-size:8px;color:${done ? '#10b981' : 'var(--text-dim)'};margin-top:4px;letter-spacing:1px;">
          ${status}
        </div>
      </div>
    `;
  }).join('');
}

function renderQuality(stats) {
  const q = stats.avg_quality;
  if (q === null || q === undefined) return;
  const pct     = Math.round(q * 100);
  const bar     = document.getElementById('iqBar');
  const val     = document.getElementById('iqValue');
  const label   = pct >= 70 ? 'ELITE' : pct >= 50 ? 'HIGH' : pct >= 30 ? 'MEDIUM' : 'LOW';
  const col     = pct >= 70 ? 'var(--accent)' : pct >= 50 ? 'var(--gold)' : 'var(--accent3)';
  if (bar) {
    bar.style.width = pct + '%';
    bar.style.background = `linear-gradient(90deg, var(--accent2), ${col})`;
  }
  if (val) {
    val.textContent = `${pct}% · ${label}`;
    val.style.color = col;
  }
  // Also update stat bar IQ
  const statIQ    = document.getElementById('statIQVal');
  const statLabel = document.getElementById('statIQLabel');
  if (statIQ)    { statIQ.textContent    = pct + '%'; statIQ.style.color = col; }
  if (statLabel) { statLabel.textContent = label; statLabel.style.color = col; }
}

function renderGrowth(data) {
  if (!data.length) return;
  initGrowthChart(data);
  const last = data[data.length - 1];
  document.getElementById('growthBadge').textContent =
    `${last.y.toLocaleString()} total`;
}

function renderGaps(rows) {
  const el = document.getElementById('gapsList');
  document.getElementById('gapBadge').textContent = `${rows.length} open`;
  if (!rows.length) {
    el.innerHTML = '<div class="no-gaps">[ NO GAPS DETECTED ]</div>';
    return;
  }
  el.innerHTML = rows.map(r => `
    <div class="gap-row">
      <div class="gap-topic">${r.topic || '—'}</div>
      <div class="gap-desc">${r.gap_description || '—'}</div>
      <div class="gap-priority">${(r.priority||0).toFixed(1)}</div>
    </div>
  `).join('');
}

function renderSources(rows) {
  const el = document.getElementById('sourcesList');
  el.innerHTML = rows.map(r => {
    let name = r.source || '—';
    try {
      const u = new URL(name);
      name = u.hostname.replace('www.','');
    } catch(e) {}
    return `
      <div class="source-row">
        <div class="source-name" title="${r.source}">${name}</div>
        <div class="source-count">${r.count}</div>
      </div>
    `;
  }).join('');
}

function renderAudit(rows) {
  const el = document.getElementById('auditFeed');
  if (!rows.length) {
    el.innerHTML = '<div class="audit-empty">[ NO AUDIT RECORDS — ACTIVITY WILL APPEAR HERE ]</div>';
    return;
  }
  el.innerHTML = rows.map(r => {
    const ts   = r.ts ? r.ts.slice(11,19) : '—';
    const cls  = r.status_code === 200 ? 'status-200' : 'status-4xx';
    const lat  = r.latency_ms ? `${r.latency_ms}ms` : '—';
    return `
      <div class="audit-row">
        <div class="audit-time">${ts}</div>
        <div class="audit-method">${r.method || 'GET'}</div>
        <div class="audit-endpoint">${r.endpoint || '—'}</div>
        <div class="audit-status ${cls}">${r.status_code || '—'} · ${lat}</div>
      </div>
    `;
  }).join('');
  document.getElementById('auditBadge').textContent = `${rows.length} records`;
}

// ── Fetch + refresh cycle ──────────────────────────────────────────────────
const REFRESH_MS = 15000;

function renderWebhooks(data) {
  const feed = document.getElementById('webhookFeed');
  if (!feed) return;
  const hooks = data.webhooks || [];
  document.getElementById('webhookBadge').textContent = hooks.length + ' registered';
  if (!hooks.length) {
    feed.innerHTML = '<div class="audit-row"><span style="color:var(--muted)">No webhooks registered</span></div>';
    return;
  }
  feed.innerHTML = hooks.map(h => {
    const rate = h.deliveries > 0 ? Math.round((1 - h.failures/h.deliveries)*100) : 100;
    const col = rate >= 90 ? 'var(--g)' : rate >= 70 ? 'var(--y)' : 'var(--r)';
    return `<div class="audit-row">
      <span style="color:var(--p2)">${h.last_fired.slice(11,19)||'—'}</span>
      <span style="color:var(--w)">${h.url}</span>
      <span style="color:var(--tx2)">${h.events.join(', ')||'all'}</span>
      <span style="color:${col}">${rate}% (${h.deliveries} sent / ${h.failures} failed)</span>
    </div>`;
  }).join('');
}

async function fetchAll() {
  try {
    const [stats, topics, growth, gaps, domains, audit, sources, webhooks] = await Promise.all([
      fetch('/dash/stats').then(r=>r.json()),
      fetch('/dash/topics').then(r=>r.json()),
      fetch('/dash/belief-growth').then(r=>r.json()),
      fetch('/dash/gaps').then(r=>r.json()),
      fetch('/dash/domain-activity').then(r=>r.json()),
      fetch('/dash/recent-audit').then(r=>r.json()),
      fetch('/dash/sources').then(r=>r.json()),
      fetch('/dash/webhooks').then(r=>r.json())
    ]);
    renderStats(stats);
    renderQuality(stats);
    renderTopics(topics);
    renderGrowth(growth);
    renderGaps(gaps);
    renderDomains(domains);
    renderAudit(audit);
    renderSources(sources);
    renderWebhooks(webhooks);
  } catch(e) {
    console.error('Dashboard fetch error:', e);
  }
}

// Refresh bar animation
function animateRefreshBar() {
  const bar = document.getElementById('refreshBar');
  bar.style.transition = 'none';
  bar.style.width = '0%';
  setTimeout(() => {
    bar.style.transition = `width ${REFRESH_MS}ms linear`;
    bar.style.width = '100%';
  }, 50);
}

fetchAll();
animateRefreshBar();
setInterval(() => {
  fetchAll();
  animateRefreshBar();
}, REFRESH_MS);
</script>
</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)

# ── Startup ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"  NEX Dashboard v1.0 — http://localhost:{DASH_PORT}")
    print(f"  Pulling from NEX API at port {NEX_API_PORT}")
    print(f"  Auto-refresh: 15s")
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=DASH_PORT, debug=False, use_reloader=False),
        daemon=True, name="nex-dashboard"
    ).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  [Dashboard] Shutting down.")
