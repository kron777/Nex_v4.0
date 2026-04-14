#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  NEX YouTube IP Rotator — Full Install Script
#  Run from anywhere: bash ~/Desktop/nex/nex_yt_install.sh
# ═══════════════════════════════════════════════════════════════════

set -e
NEX="$HOME/Desktop/nex"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; }

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  NEX YouTube IP Rotator — Install"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── 1. Write nex_youtube_rotator.py ─────────────────────────────────────────
echo "▸ Writing nex_youtube_rotator.py..."
cat > "$NEX/nex_youtube_rotator.py" << 'PYEOF'
"""
nex_youtube_rotator.py — YouTube IP Rotation Module
Plugs into NEX: pending_notifications → Telegram, ThrowNetEngine, yt_fetch drop-in.
Free only: Tor Docker (25 IPs) + public proxy fallback.
"""
import os, sys, json, time, random, logging, sqlite3, threading
import urllib.request, urllib.error
from datetime import datetime

_NEX_ROOT = os.path.expanduser("~/Desktop/nex")
_NEX_PKG  = os.path.join(_NEX_ROOT, "nex")
_DB_PATH  = os.path.join(_NEX_ROOT, "nex.db")
for _p in [_NEX_ROOT, _NEX_PKG]:
    if _p not in sys.path: sys.path.insert(0, _p)

log = logging.getLogger("youtube_rotator")
logging.basicConfig(level=logging.INFO, format="[youtube_rotator] %(message)s")

BLOCK_CODES   = {403, 429, 503, 999}
MAX_RETRIES   = 6
BASE_COOLDOWN = 4
MAX_COOLDOWN  = 60

FREE_PROXY_SOURCES = [
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=elite",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

def _notify(message: str, db_path: str = _DB_PATH):
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS pending_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            sent INTEGER DEFAULT 0)""")
        cur.execute("INSERT INTO pending_notifications (message) VALUES (?)", (message,))
        con.commit(); con.close()
        log.info("Notification queued → Telegram")
    except Exception as e:
        log.error(f"_notify error: {e}")

def _fire_throw_net(constraint: str):
    def _run():
        try:
            from nex.nex_throw_net import ThrowNetEngine
            session = ThrowNetEngine(_DB_PATH).run(
                constraint, trigger_mode="autonomous", trigger_topic="youtube_ip_block")
            msg = session.get("surface_message", "")
            if msg: _notify(f"[throw_net] YouTube rotator:\n{msg}")
        except ImportError:
            log.warning("throw_net not available — skipping")
        except Exception as e:
            log.error(f"throw_net fire error: {e}")
    threading.Thread(target=_run, daemon=True).start()

class _FreeProxyPool:
    def __init__(self):
        self._pool = []; self._burned = set(); self._lock = threading.Lock()
        threading.Thread(target=self._fetch, daemon=True).start()
    def _fetch(self):
        fresh = []
        for url in FREE_PROXY_SOURCES:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENTS[0]})
                with urllib.request.urlopen(req, timeout=10) as r:
                    for line in r.read().decode("utf-8", errors="ignore").splitlines():
                        line = line.strip()
                        if line and ":" in line: fresh.append(f"http://{line}")
            except Exception as e:
                log.warning(f"Proxy source failed: {e}")
        random.shuffle(fresh)
        with self._lock:
            self._pool = [p for p in fresh[:80] if p not in self._burned]
        log.info(f"Free proxy pool: {len(self._pool)} proxies loaded")
    def get(self):
        with self._lock:
            available = [p for p in self._pool if p not in self._burned]
            if not available:
                threading.Thread(target=self._fetch, daemon=True).start(); return None
            return random.choice(available)
    def burn(self, proxy: str):
        with self._lock: self._burned.add(proxy)

_pool    = _FreeProxyPool()
_tor_ok  = None

def _check_tor() -> bool:
    global _tor_ok
    if _tor_ok is not None: return _tor_ok
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"http": "http://127.0.0.1:3128", "https": "http://127.0.0.1:3128"}))
        with opener.open(urllib.request.Request("http://httpbin.org/ip",
            headers={"User-Agent": USER_AGENTS[0]}), timeout=10) as r:
            data = json.loads(r.read().decode())
            log.info(f"Tor OK — exit IP: {data.get('origin','?')}")
            _tor_ok = True; return True
    except Exception as e:
        log.warning(f"Tor not available: {e}")
        _tor_ok = False; return False

def _backoff(attempt: int):
    delay = min(BASE_COOLDOWN * (2 ** attempt) + random.uniform(0, 2), MAX_COOLDOWN)
    log.info(f"Backoff {delay:.1f}s"); time.sleep(delay)

yt_state = {"status": "IDLE", "proxy_type": None, "blocks": 0, "successes": 0}

def yt_fetch(url: str):
    """
    Drop-in for requests.get() in nex_agi_youtube_engine.py.
    Returns object with .text .status_code .json() .content — or None on failure.
    """
    yt_state["status"] = "ACTIVE"
    tor_available = _check_tor()
    headers = {"User-Agent": random.choice(USER_AGENTS), "Accept-Language": "en-US,en;q=0.9"}
    for attempt in range(MAX_RETRIES):
        proxy_url = None; proxy_type = "direct"
        if tor_available:
            proxy_url = "http://127.0.0.1:3128"; proxy_type = "tor"
        elif attempt > 0:
            raw = _pool.get()
            if raw: proxy_url = raw; proxy_type = "free"
        try:
            req = urllib.request.Request(url, headers=headers)
            if proxy_url:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler(
                    {"http": proxy_url, "https": proxy_url}))
            else:
                opener = urllib.request.build_opener()
            log.info(f"Attempt {attempt+1}/{MAX_RETRIES} via {proxy_type}")
            with opener.open(req, timeout=12) as r:
                status = r.status; body = r.read()
                body_text = body[:500].decode("utf-8", errors="ignore").lower()
                soft_block = any(x in body_text for x in
                    ["unusual traffic", "captcha", "consent.youtube"])
                if status in BLOCK_CODES or soft_block:
                    log.warning(f"Blocked HTTP {status} via {proxy_type}")
                    yt_state["status"] = "BLOCKED"; yt_state["blocks"] += 1
                    if proxy_type == "free" and proxy_url: _pool.burn(proxy_url)
                    if yt_state["blocks"] in (1,3,5) or yt_state["blocks"] % 10 == 0:
                        _notify(f"⚠️ YouTube blocked (#{yt_state['blocks']}) via {proxy_type} — rotating IP")
                    if yt_state["blocks"] == 3:
                        _fire_throw_net("YouTube module repeatedly blocked by IP. Need structural free solution.")
                    _backoff(attempt); yt_state["status"] = "RECOVERING"; continue
                yt_state["status"] = "ACTIVE"; yt_state["proxy_type"] = proxy_type
                yt_state["successes"] += 1
                log.info(f"Success via {proxy_type} — HTTP {status}")
                class _Resp:
                    status_code = status; content = body
                    text = body.decode("utf-8", errors="ignore")
                    def json(self): return json.loads(self.text)
                return _Resp()
        except urllib.error.HTTPError as e:
            log.warning(f"HTTPError {e.code} via {proxy_type}")
            yt_state["status"] = "BLOCKED"; yt_state["blocks"] += 1
            if proxy_type == "free" and proxy_url: _pool.burn(proxy_url)
            _backoff(attempt); yt_state["status"] = "RECOVERING"
        except Exception as e:
            log.warning(f"Error ({proxy_type}): {e}")
            if proxy_type == "free" and proxy_url: _pool.burn(proxy_url)
            _backoff(attempt)
    yt_state["status"] = "IDLE"
    log.critical("All rotation attempts failed")
    _notify(f"🔴 YouTube rotator exhausted. Blocks: {yt_state['blocks']}\n"
            "Run: docker restart $(docker ps -q --filter ancestor=zhaowde/rotating-tor-http-proxy)")
    return None

def yt_status_string() -> str:
    icons = {"IDLE":"● YOUTUBE IDLE","ACTIVE":"● YOUTUBE ACTIVE",
             "BLOCKED":"● YOUTUBE BLOCKED","RECOVERING":"● YOUTUBE RECOVERING"}
    return f"{icons.get(yt_state['status'],'● YOUTUBE ?')} | blocks:{yt_state['blocks']}"

if __name__ == "__main__":
    print("\n" + "═"*50)
    print("  NEX YouTube Rotator — self test")
    print("═"*50)
    r = yt_fetch("https://www.youtube.com/robots.txt")
    if r: print(f"\n✓ OK — {len(r.content)} bytes via {yt_state['proxy_type']}")
    else: print("\n✗ Failed — check Tor or proxy availability")
    print(f"HUD: {yt_status_string()}")
    print(f"State: {yt_state}\n")
PYEOF
ok "nex_youtube_rotator.py written"

# ── 2. Back up nex_agi_youtube_engine.py ─────────────────────────────────────
echo "▸ Backing up nex_agi_youtube_engine.py..."
if [ -f "$NEX/nex_agi_youtube_engine.py" ]; then
    cp "$NEX/nex_agi_youtube_engine.py" \
       "$NEX/nex_agi_youtube_engine.py.bak_rotator_$(date +%Y%m%d_%H%M%S)"
    ok "Backup created"
else
    warn "nex_agi_youtube_engine.py not found — skipping patch"
fi

# ── 3. Patch nex_agi_youtube_engine.py ───────────────────────────────────────
echo "▸ Patching nex_agi_youtube_engine.py..."
if [ -f "$NEX/nex_agi_youtube_engine.py" ]; then
    # Only patch if not already patched
    if grep -q "yt_fetch" "$NEX/nex_agi_youtube_engine.py"; then
        warn "Already patched — skipping"
    else
        # Add import at top (after existing imports) and replace requests.get calls
        python3 - << 'PATCHEOF'
import re, sys

path = f"{__import__('os').path.expanduser('~')}/Desktop/nex/nex_agi_youtube_engine.py"
with open(path, 'r') as f:
    src = f.read()

# Add import line after last existing import block
import_line = "from nex_youtube_rotator import yt_fetch, yt_status_string  # NEX IP rotator\n"
# Find last import line position
lines = src.splitlines(keepends=True)
last_import = 0
for i, line in enumerate(lines):
    if line.startswith('import ') or line.startswith('from '):
        last_import = i
lines.insert(last_import + 1, import_line)
src = ''.join(lines)

# Replace requests.get( with yt_fetch( — handles both quoted and variable URLs
src = re.sub(r'\brequests\.get\(', 'yt_fetch(', src)

# Replace requests.Session().get( patterns if present
src = re.sub(r'\bsession\.get\(', 'yt_fetch(', src)

with open(path, 'w') as f:
    f.write(src)
print("Patch applied")
PATCHEOF
        ok "nex_agi_youtube_engine.py patched"
    fi
fi

# ── 4. Patch nex_hud_server.py for live status dot ───────────────────────────
echo "▸ Patching nex_hud_server.py for YouTube status dot..."
if [ -f "$NEX/nex_hud_server.py" ]; then
    if grep -q "yt_status_string" "$NEX/nex_hud_server.py"; then
        warn "HUD already patched — skipping"
    else
        cp "$NEX/nex_hud_server.py" \
           "$NEX/nex_hud_server.py.bak_rotator_$(date +%Y%m%d_%H%M%S)"
        python3 - << 'HUDEOF'
import os
path = os.path.expanduser("~/Desktop/nex/nex_hud_server.py")
with open(path, 'r') as f:
    src = f.read()

import_line = "from nex_youtube_rotator import yt_status_string  # NEX IP rotator\n"

# Insert after last import
lines = src.splitlines(keepends=True)
last_import = 0
for i, line in enumerate(lines):
    if line.startswith('import ') or line.startswith('from '):
        last_import = i
lines.insert(last_import + 1, import_line)
src = ''.join(lines)

# Replace static "YOUTUBE IDLE" string with live call
src = src.replace('"YOUTUBE IDLE"', 'yt_status_string()')
src = src.replace("'YOUTUBE IDLE'", 'yt_status_string()')

with open(path, 'w') as f:
    f.write(src)
print("HUD patched")
HUDEOF
        ok "nex_hud_server.py patched"
    fi
else
    warn "nex_hud_server.py not found — skipping HUD patch"
fi

# ── 5. Check Docker ───────────────────────────────────────────────────────────
echo "▸ Checking Docker..."
if command -v docker &>/dev/null; then
    ok "Docker found: $(docker --version | cut -d' ' -f3 | tr -d ',')"

    # Check if Tor container already running
    RUNNING=$(docker ps --filter "ancestor=zhaowde/rotating-tor-http-proxy" -q 2>/dev/null)
    if [ -n "$RUNNING" ]; then
        ok "Tor proxy already running (container: $RUNNING)"
    else
        echo "▸ Starting Tor rotation pool (25 circuits)..."
        docker run -d \
            -p 3128:3128 \
            -p 4444:4444 \
            -e TOR_INSTANCES=25 \
            -e TOR_REBUILD_INTERVAL=1800 \
            --name nex_tor_pool \
            --restart unless-stopped \
            zhaowde/rotating-tor-http-proxy
        ok "Tor pool started — 25 IPs on port 3128"
        ok "HAProxy stats → http://localhost:4444"
        echo "  Waiting 15s for circuits to build..."
        sleep 15
    fi
else
    warn "Docker not found. Install it with:"
    echo "  curl -fsSL https://get.docker.com | sh"
    echo "  sudo usermod -aG docker \$USER"
    echo "  newgrp docker"
    echo "  Then re-run this script."
fi

# ── 6. Install Python deps (stdlib only — no pip needed) ─────────────────────
echo "▸ Verifying Python environment..."
cd "$NEX"
if [ -d "venv" ]; then
    source venv/bin/activate
    ok "venv activated"
fi
python3 -c "import urllib.request, sqlite3, threading, json; print('stdlib OK')" && ok "All deps available (stdlib only)"

# ── 7. Self-test ──────────────────────────────────────────────────────────────
echo ""
echo "▸ Running self-test..."
cd "$NEX"
python3 nex_youtube_rotator.py

# ── 8. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Install complete"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "  Files written/patched:"
echo "    ~/Desktop/nex/nex_youtube_rotator.py     ← new module"
echo "    ~/Desktop/nex/nex_agi_youtube_engine.py  ← patched"
echo "    ~/Desktop/nex/nex_hud_server.py          ← patched"
echo ""
echo "  Tor pool:    http://localhost:3128"
echo "  HAProxy:     http://localhost:4444"
echo ""
echo "  To restart Tor pool if blocked:"
echo "    docker restart nex_tor_pool"
echo ""
echo "  To watch rotation logs live:"
echo "    cd ~/Desktop/nex && python3 -c \\"
echo "      \"from nex_youtube_rotator import yt_fetch; yt_fetch('https://www.youtube.com/robots.txt')\""
echo ""
