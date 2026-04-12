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

def _save_yt_state():
    """Write live state to file so nex_hud_server.py can read it across processes."""
    try:
        import json, os
        os.makedirs(os.path.expanduser("~/.config/nex"), exist_ok=True)
        with open(os.path.expanduser("~/.config/nex/yt_state.json"), "w") as f:
            json.dump(yt_state, f)
    except Exception:
        pass

def yt_fetch(url: str):
    """
    Drop-in for requests.get() in nex_agi_youtube_engine.py.
    Returns object with .text .status_code .json() .content — or None on failure.
    """
    yt_state["status"] = "ACTIVE"; _save_yt_state()
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
                    yt_state["status"] = "BLOCKED"; _save_yt_state(); yt_state["blocks"] += 1
                    if proxy_type == "free" and proxy_url: _pool.burn(proxy_url)
                    if yt_state["blocks"] in (1,3,5) or yt_state["blocks"] % 10 == 0:
                        _notify(f"⚠️ YouTube blocked (#{yt_state['blocks']}) via {proxy_type} — rotating IP")
                    if yt_state["blocks"] == 3:
                        _fire_throw_net("YouTube module repeatedly blocked by IP. Need structural free solution.")
                    _backoff(attempt); yt_state["status"] = "RECOVERING"; _save_yt_state(); continue
                yt_state["status"] = "ACTIVE"; _save_yt_state(); yt_state["proxy_type"] = proxy_type
                yt_state["successes"] += 1
                log.info(f"Success via {proxy_type} — HTTP {status}")
                class _Resp:
                    status_code = status; content = body
                    text = body.decode("utf-8", errors="ignore")
                    def json(self): return json.loads(self.text)
                return _Resp()
        except urllib.error.HTTPError as e:
            log.warning(f"HTTPError {e.code} via {proxy_type}")
            yt_state["status"] = "BLOCKED"; _save_yt_state(); yt_state["blocks"] += 1
            if proxy_type == "free" and proxy_url: _pool.burn(proxy_url)
            _backoff(attempt); yt_state["status"] = "RECOVERING"; _save_yt_state()
        except Exception as e:
            log.warning(f"Error ({proxy_type}): {e}")
            if proxy_type == "free" and proxy_url: _pool.burn(proxy_url)
            _backoff(attempt)
    yt_state["status"] = "IDLE"; _save_yt_state()
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
