#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  NEX FULL SYSTEM AUDIT — outputs ~/Desktop/nex_audit.txt    ║
# ╚══════════════════════════════════════════════════════════════╝

OUT="$HOME/Desktop/nex_audit.txt"
NEX="$HOME/Desktop/nex"
RUN="$NEX/run.py"
WS="$NEX/nex_ws.py"
GUI="$NEX/nex-gui.html"
DB="$HOME/.config/nex/nex.db"

echo "Running NEX full audit..."
> "$OUT"

log() { echo "$1" | tee -a "$OUT"; }
ok()  { echo "  ✓ $1" | tee -a "$OUT"; }
err() { echo "  ✗ $1" | tee -a "$OUT"; }
warn(){ echo "  ⚠ $1" | tee -a "$OUT"; }
hdr() { echo "" | tee -a "$OUT"; echo "══════════════════════════════════════════════════════" | tee -a "$OUT"; echo "  $1" | tee -a "$OUT"; echo "══════════════════════════════════════════════════════" | tee -a "$OUT"; }

log "NEX SYSTEM AUDIT"
log "Generated: $(date)"
log "Host: $(hostname) / $(uname -r)"

# ── 1. FILE EXISTENCE ─────────────────────────────────────────
hdr "1. CORE FILES"
for f in "$RUN" "$WS" "$GUI" \
          "$NEX/nex_youtube.py" \
          "$NEX/nex/cognition.py" \
          "$NEX/nex/belief_store.py" \
          "$NEX/nex/auto_learn.py" \
          "$NEX/nex/nex_crawler.py" \
          "$NEX/nex/nex_self.py" \
          "$NEX/nex/nex_memory.py" \
          "$NEX/nex/nex_lora.py" \
          "$NEX/nex/nex_trainer.py" \
          "$DB"; do
    [ -f "$f" ] && ok "$f" || err "MISSING: $f"
done

# ── 2. SYNTAX CHECK ───────────────────────────────────────────
hdr "2. PYTHON SYNTAX"
for f in "$RUN" "$WS" "$NEX/nex_youtube.py"; do
    if [ -f "$f" ]; then
        result=$(python3 -m py_compile "$f" 2>&1)
        [ -z "$result" ] && ok "$(basename $f) — SYNTAX OK" || err "$(basename $f) — $result"
    fi
done

# ── 3. DEPENDENCIES ───────────────────────────────────────────
hdr "3. PYTHON DEPENDENCIES"
cd "$NEX" && source venv/bin/activate 2>/dev/null
for pkg in websockets psutil youtube_transcript_api yt_dlp requests mastodon anthropic; do
    python3 -c "import $pkg; print('  ✓ '$pkg)" 2>/dev/null | tee -a "$OUT" || echo "  ✗ MISSING: $pkg" | tee -a "$OUT"
done

# ── 4. EMIT WIRING IN run.py ──────────────────────────────────
hdr "4. EMIT WIRING (run.py)"
python3 << PYEOF | tee -a "$OUT"
src = open("$RUN").read()

checks = [
    ("import nex_ws",                    "nex_ws imported"),
    ("ws_start()",                        "ws_start() called"),
    ("nex_ws.start()",                    "nex_ws.start() called"),
    ("emit_phase(",                       "emit_phase wired"),
    ("emit_feed(",                        "emit_feed wired"),
    ("emit_stats(",                       "emit_stats wired"),
    ("emit_agents(",                      "emit_agents wired"),
    ("emit_insights(",                    "emit_insights wired"),
    ("emit_reflection(",                  "emit_reflection wired"),
    ("emit_self_assessment(",             "emit_self_assessment wired"),
    ("global emit_feed",                  "global emit_feed declared"),
    ("from nex_youtube import",           "YouTube module imported"),
    ("learn_from_youtube(",               "YouTube learning wired"),
    ("http.server.HTTPServer",            "HTTP GUI server wired"),
    ("localhost:8766",                    "HTTP server on port 8766"),
    ("_notif_title = _notif_body",        "notif_title safe init"),
    ("time.sleep(120)",                   "120s cycle present"),
]

for pattern, label in checks:
    count = src.count(pattern)
    if count > 0:
        print(f"  ✓ {label} ({count}x)")
    else:
        print(f"  ✗ MISSING: {label}")

# Count emit calls
print(f"\n  emit_phase calls:          {src.count('emit_phase(')}")
print(f"  emit_feed calls:           {src.count('emit_feed(')}")
print(f"  emit_stats calls:          {src.count('emit_stats(')}")
print(f"  emit_agents calls:         {src.count('emit_agents(')}")
print(f"  emit_insights calls:       {src.count('emit_insights(')}")
print(f"  emit_reflection calls:     {src.count('emit_reflection(')}")
print(f"  emit_self_assessment calls:{src.count('emit_self_assessment(')}")
PYEOF

# ── 5. GUI WIRING ─────────────────────────────────────────────
hdr "5. GUI WIRING (nex-gui.html)"
python3 << PYEOF | tee -a "$OUT"
f = open("$GUI").read()

checks = [
    ("ws://localhost:8765",              "WebSocket URL correct"),
    ("function handle(",                 "handle() function present"),
    ("m.type==='feed'",                  "feed handler wired"),
    ("m.type==='stats'",                 "stats handler wired"),
    ("m.type==='phase'",                 "phase handler wired"),
    ("m.type==='agents'",                "agents handler wired"),
    ("m.type==='insights'",              "insights handler wired"),
    ("m.type==='reflection'",            "reflection handler wired"),
    ("m.type==='self_assessment'",       "self_assessment handler wired"),
    ("m.type==='sysmon'",                "sysmon handler wired"),
    ("flashPlat(",                       "platform flicker wired"),
    ("YOUTUBE",                          "YouTube in platforms"),
    ("id=\"feed\"",                      "feed panel present"),
    ("id=\"main\"",                      "main grid present"),
    ("overflow-y:auto",                  "scrollable panels"),
    ("localhost:8766",                   "served via HTTP not file://"),
    ("rFeed()",                          "rFeed renderer present"),
    ("rSysmon()",                        "rSysmon renderer present"),
    ("rAgents()",                        "rAgents renderer present"),
    ("rAssess()",                        "rAssess renderer present"),
]

for pattern, label in checks:
    print(f"  {'✓' if pattern in f else '✗ MISSING:'} {label}")
PYEOF

# ── 6. WEBSOCKET SERVER ───────────────────────────────────────
hdr "6. WEBSOCKET & HTTP SERVER STATUS"
if ss -tlnp 2>/dev/null | grep -q ":8765"; then
    ok "WebSocket server RUNNING on :8765"
else
    err "WebSocket server NOT running on :8765"
fi

if ss -tlnp 2>/dev/null | grep -q ":8766"; then
    ok "HTTP GUI server RUNNING on :8766"
else
    err "HTTP GUI server NOT running on :8766"
fi

if pgrep -f "run.py" > /dev/null; then
    ok "run.py process is RUNNING (PID: $(pgrep -f run.py | head -1))"
else
    err "run.py NOT running"
fi

if pgrep -f "llama-server" > /dev/null; then
    ok "llama-server RUNNING"
else
    warn "llama-server not detected"
fi

# ── 7. DATABASE STATUS ────────────────────────────────────────
hdr "7. DATABASE & BELIEF STORE"
python3 << PYEOF | tee -a "$OUT"
import sqlite3, os, json
db_path = os.path.expanduser("~/.config/nex/nex.db")
config_dir = os.path.expanduser("~/.config/nex")

try:
    db = sqlite3.connect(db_path)
    count = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    avg = db.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0]
    high = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence > 0.7").fetchone()[0]
    agents = db.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    print(f"  ✓ SQLite beliefs: {count:,}")
    print(f"  ✓ Avg confidence: {avg:.1%}")
    print(f"  ✓ High conf (>70%): {high}")
    print(f"  ✓ Agents in DB: {agents}")
    db.close()
except Exception as e:
    print(f"  ✗ DB error: {e}")

for fname in ["conversations.json","reflections.json","insights.json","beliefs.json","session_state.json"]:
    path = os.path.join(config_dir, fname)
    if os.path.exists(path):
        try:
            data = json.load(open(path))
            size = len(data) if isinstance(data, list) else len(data.keys())
            print(f"  ✓ {fname}: {size} entries")
        except:
            print(f"  ⚠ {fname}: exists but unreadable")
    else:
        print(f"  ✗ {fname}: MISSING")
PYEOF

# ── 8. SESSION STATS ──────────────────────────────────────────
hdr "8. SESSION STATS"
python3 << PYEOF | tee -a "$OUT"
import json, os
config = os.path.expanduser("~/.config/nex")
try:
    convs = json.load(open(os.path.join(config,"conversations.json")))
    replied  = sum(1 for c in convs if c.get("type")=="comment")
    chatted  = sum(1 for c in convs if c.get("type")=="agent_chat")
    answered = sum(1 for c in convs if c.get("type")=="notification_reply")
    posted   = sum(1 for c in convs if c.get("type")=="original_post")
    print(f"  All-time replied:  {replied}")
    print(f"  All-time chatted:  {chatted}")
    print(f"  All-time answered: {answered}")
    print(f"  All-time posted:   {posted}")
except Exception as e:
    print(f"  ✗ {e}")

try:
    refs = json.load(open(os.path.join(config,"reflections.json")))
    scores = [r.get("topic_alignment",0) for r in refs if r.get("topic_alignment") is not None]
    avg = sum(scores)/len(scores) if scores else 0
    print(f"  Reflections: {len(refs)}, avg alignment: {avg:.1%}")
except Exception as e:
    print(f"  ✗ reflections: {e}")

try:
    ins = json.load(open(os.path.join(config,"insights.json")))
    top = sorted(ins, key=lambda x: x.get("confidence",0), reverse=True)[:5]
    print(f"  Top insights:")
    for i in top:
        print(f"    {i.get('topic','?'):20s} {i.get('confidence',0):.0%} / {i.get('belief_count',0)} beliefs")
except Exception as e:
    print(f"  ✗ insights: {e}")
PYEOF

# ── 9. YOUTUBE MODULE ─────────────────────────────────────────
hdr "9. YOUTUBE LEARNING MODULE"
python3 << PYEOF | tee -a "$OUT"
import sys
sys.path.insert(0, "$NEX")
try:
    import youtube_transcript_api
    print(f"  ✓ youtube-transcript-api installed")
except: print("  ✗ youtube-transcript-api MISSING — pip install youtube-transcript-api")

import subprocess
r = subprocess.run(["yt-dlp","--version"], capture_output=True, text=True)
if r.returncode == 0:
    print(f"  ✓ yt-dlp {r.stdout.strip()}")
else:
    print("  ✗ yt-dlp MISSING — pip install yt-dlp")

import sqlite3, os
db = sqlite3.connect(os.path.expanduser("~/.config/nex/nex.db"))
yt_beliefs = db.execute("SELECT COUNT(*) FROM beliefs WHERE source LIKE '%youtube%'").fetchone()[0]
print(f"  ✓ YouTube beliefs in DB: {yt_beliefs}")
db.close()

seen_path = os.path.expanduser("~/.config/nex/youtube_seen.json")
if os.path.exists(seen_path):
    import json
    seen = json.load(open(seen_path))
    print(f"  ✓ Videos seen: {len(seen)}")
else:
    print("  ⚠ youtube_seen.json not yet created (will appear after first run)")
PYEOF

# ── 10. ALIAS CHECK ───────────────────────────────────────────
hdr "10. SHELL ALIAS"
count=$(grep -c "alias nex=" ~/.bashrc 2>/dev/null || echo 0)
if [ "$count" -eq 1 ]; then
    ok "Single nex alias found:"
    grep "alias nex=" ~/.bashrc | tee -a "$OUT"
elif [ "$count" -gt 1 ]; then
    err "MULTIPLE nex aliases found ($count) — only last one is used:"
    grep "alias nex=" ~/.bashrc | tee -a "$OUT"
else
    err "No nex alias found in ~/.bashrc"
fi

# ── 11. LIVE BROADCAST TEST ───────────────────────────────────
hdr "11. LIVE BROADCAST TEST"
python3 << PYEOF | tee -a "$OUT"
import sys, time
sys.path.insert(0, "$NEX")
try:
    import nex_ws
    # Try to send a test broadcast — will work if server already running
    nex_ws.emit_feed("system", "nex_audit", "audit broadcast test")
    print("  ✓ emit_feed() called successfully")
    print("  ✓ Check GUI activity feed for 'audit broadcast test' entry")
except Exception as e:
    print(f"  ✗ Broadcast test failed: {e}")
    print("  ⚠ This is normal if NEX is not currently running")
PYEOF

# ── SUMMARY ───────────────────────────────────────────────────
hdr "SUMMARY"
total_ok=$(grep -c "  ✓" "$OUT")
total_err=$(grep -c "  ✗" "$OUT")
total_warn=$(grep -c "  ⚠" "$OUT")

log "  PASSED:   $total_ok"
log "  FAILED:   $total_err"
log "  WARNINGS: $total_warn"
log ""
log "  Full report: $OUT"
log ""

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Audit complete → ~/Desktop/nex_audit.txt    ║"
echo "╚══════════════════════════════════════════════╝"
