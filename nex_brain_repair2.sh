#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  NEX Brain Repair 2 — Missing engine modules
#  Run: bash ~/Desktop/nex/nex_brain_repair2.sh
# ═══════════════════════════════════════════════════════════════════

NEX="$HOME/Desktop/nex"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  NEX Brain Repair 2 — Engine Modules"
echo "═══════════════════════════════════════════════════════"
echo ""

cd "$NEX"
source venv/bin/activate 2>/dev/null || true

# ── 1. nex_mastodon.py ───────────────────────────────────────────────────────
echo "▸ Writing nex_mastodon.py..."
cat > "$NEX/nex_mastodon.py" << 'PYEOF'
"""
nex_mastodon.py — Mastodon integration stub for NEX
Provides start_mastodon_background() used by run.py.
Real credentials go in ~/.config/nex/mastodon.json:
  {"instance": "https://mastodon.social", "token": "YOUR_TOKEN"}
"""
import os, json, time, logging, threading
log = logging.getLogger("nex_mastodon")
_CFG = os.path.expanduser("~/.config/nex/mastodon.json")

def _load_config():
    if os.path.exists(_CFG):
        with open(_CFG) as f:
            return json.load(f)
    return None

def _mastodon_loop():
    cfg = _load_config()
    if not cfg:
        log.info("Mastodon: no config at ~/.config/nex/mastodon.json — running in stub mode")
        return
    try:
        from mastodon import Mastodon
        m = Mastodon(access_token=cfg["token"], api_base_url=cfg["instance"])
        log.info(f"Mastodon: connected to {cfg['instance']}")
        while True:
            try:
                # Pull notifications every 60s
                notifs = m.notifications(limit=5)
                for n in (notifs or []):
                    ntype = n.get("type","")
                    acct  = n.get("account",{}).get("acct","?")
                    if ntype == "mention":
                        log.info(f"Mastodon mention from @{acct}")
            except Exception as e:
                log.warning(f"Mastodon loop error: {e}")
            time.sleep(60)
    except ImportError:
        log.info("Mastodon: Mastodon.py not installed — pip install Mastodon.py to enable")
    except Exception as e:
        log.error(f"Mastodon: failed to connect: {e}")

def start_mastodon_background() -> threading.Thread:
    t = threading.Thread(target=_mastodon_loop, daemon=True, name="nex_mastodon")
    t.start()
    log.info("Mastodon: background thread started")
    return t
PYEOF
ok "nex_mastodon.py written"

# ── 2. nex_adaptive_intelligence.py ─────────────────────────────────────────
echo "▸ Writing nex_adaptive_intelligence.py..."
cat > "$NEX/nex_adaptive_intelligence.py" << 'PYEOF'
"""
nex_adaptive_intelligence.py — Adaptive intelligence layer for NEX
Monitors belief quality and confidence trends, adapts learning rate.
"""
import os, sys, sqlite3, logging, threading
_ROOT = os.path.expanduser("~/Desktop/nex")
for _p in [_ROOT, os.path.join(_ROOT,"nex")]:
    if _p not in sys.path: sys.path.insert(0, _p)
log = logging.getLogger("nex_adaptive_intelligence")
_DB = os.path.join(_ROOT, "nex.db")
_instance = None

class AdaptiveIntelligence:
    def __init__(self):
        self._ready    = False
        self._rate     = 1.0   # learning rate multiplier
        self._health   = 1.0
        self._lock     = threading.Lock()

    def init(self):
        try:
            con = sqlite3.connect(_DB)
            cur = con.cursor()
            # Gauge current belief health
            row = cur.execute("""
                SELECT AVG(confidence), COUNT(*) FROM beliefs
                WHERE timestamp > datetime('now', '-24 hours')
            """).fetchone()
            con.close()
            avg_conf = float(row[0] or 0.5)
            count    = int(row[1] or 0)
            self._health = avg_conf
            self._rate   = 1.0 + (0.5 - avg_conf)  # lower conf → higher rate
            self._ready  = True
            log.info(f"AdaptiveIntelligence init: health={avg_conf:.2f} rate={self._rate:.2f} recent_beliefs={count}")
        except Exception as e:
            log.warning(f"AdaptiveIntelligence.init: {e}")
            self._ready = True  # Don't block startup

    def tick(self, cycle: int = 0) -> dict:
        if cycle % 25 != 0:
            return {}
        try:
            con = sqlite3.connect(_DB)
            row = con.execute("""
                SELECT AVG(confidence) FROM beliefs
                WHERE timestamp > datetime('now', '-1 hour')
            """).fetchone()
            con.close()
            avg = float(row[0] or 0.5)
            with self._lock:
                self._health = avg
                self._rate   = max(0.5, min(2.0, 1.0 + (0.5 - avg)))
            return {"health": self._health, "rate": self._rate}
        except Exception as e:
            log.warning(f"tick: {e}")
            return {}

    def learning_rate(self) -> float:
        with self._lock: return self._rate

    def health(self) -> float:
        with self._lock: return self._health

def get_adaptive_intelligence() -> AdaptiveIntelligence:
    global _instance
    if _instance is None:
        _instance = AdaptiveIntelligence()
    return _instance
PYEOF
ok "nex_adaptive_intelligence.py written"

# ── 3. nex_signal_engine.py ──────────────────────────────────────────────────
echo "▸ Writing nex_signal_engine.py..."
cat > "$NEX/nex_signal_engine.py" << 'PYEOF'
"""
nex_signal_engine.py — Signal detection engine for NEX
Detects meaningful signals in belief stream: spikes, drops, trends.
"""
import os, sys, sqlite3, logging, threading
from collections import deque
_ROOT = os.path.expanduser("~/Desktop/nex")
for _p in [_ROOT, os.path.join(_ROOT,"nex")]:
    if _p not in sys.path: sys.path.insert(0, _p)
log = logging.getLogger("nex_signal_engine")
_DB = os.path.join(_ROOT, "nex.db")
_instance = None

class SignalEngine:
    def __init__(self):
        self._ready   = False
        self._history = deque(maxlen=50)
        self._signals = []
        self._lock    = threading.Lock()

    def init(self):
        try:
            con = sqlite3.connect(_DB)
            rows = con.execute("""
                SELECT topic, AVG(confidence) as avg_c, COUNT(*) as cnt
                FROM beliefs
                WHERE timestamp > datetime('now', '-6 hours')
                GROUP BY topic ORDER BY cnt DESC LIMIT 20
            """).fetchall()
            con.close()
            with self._lock:
                self._history.append({
                    "topics": [r[0] for r in rows],
                    "avg_conf": [r[1] for r in rows],
                })
            self._ready = True
            log.info(f"SignalEngine init: tracking {len(rows)} topics")
        except Exception as e:
            log.warning(f"SignalEngine.init: {e}")
            self._ready = True

    def tick(self, cycle: int = 0) -> list:
        if cycle % 10 != 0:
            return []
        signals = []
        try:
            con = sqlite3.connect(_DB)
            # Detect confidence spikes — topic gaining fast
            rows = con.execute("""
                SELECT topic, AVG(confidence) as avg_c,
                       MAX(timestamp) as latest
                FROM beliefs
                WHERE timestamp > datetime('now', '-30 minutes')
                GROUP BY topic
                HAVING avg_c > 0.75 AND COUNT(*) >= 3
                ORDER BY avg_c DESC LIMIT 5
            """).fetchall()
            con.close()
            for topic, conf, ts in rows:
                signals.append({"type": "spike", "topic": topic, "confidence": conf})
            with self._lock:
                self._signals = signals
        except Exception as e:
            log.warning(f"tick: {e}")
        return signals

    def latest_signals(self) -> list:
        with self._lock: return list(self._signals)

def get_signal_engine() -> SignalEngine:
    global _instance
    if _instance is None:
        _instance = SignalEngine()
    return _instance
PYEOF
ok "nex_signal_engine.py written"

# ── 4. nex_execution_engine.py ───────────────────────────────────────────────
echo "▸ Writing nex_execution_engine.py..."
cat > "$NEX/nex_execution_engine.py" << 'PYEOF'
"""
nex_execution_engine.py — Execution engine for NEX
Queues and executes deferred actions: research tasks, belief updates,
throw_net sessions triggered by other modules.
"""
import os, sys, sqlite3, json, logging, threading, time
from collections import deque
_ROOT = os.path.expanduser("~/Desktop/nex")
for _p in [_ROOT, os.path.join(_ROOT,"nex")]:
    if _p not in sys.path: sys.path.insert(0, _p)
log = logging.getLogger("nex_execution_engine")
_DB = os.path.join(_ROOT, "nex.db")
_instance = None

class ExecutionEngine:
    def __init__(self):
        self._queue   = deque(maxlen=100)
        self._ready   = False
        self._lock    = threading.Lock()
        self._worker  = None

    def init(self):
        try:
            con = sqlite3.connect(_DB)
            con.execute("""CREATE TABLE IF NOT EXISTS execution_queue (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type  TEXT NOT NULL,
                payload    TEXT,
                status     TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now')),
                run_at     TEXT DEFAULT (datetime('now')))""")
            con.commit()
            # Load pending tasks
            rows = con.execute("""
                SELECT id, task_type, payload FROM execution_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC LIMIT 20
            """).fetchall()
            con.close()
            with self._lock:
                for row in rows:
                    self._queue.append({
                        "id": row[0], "type": row[1],
                        "payload": json.loads(row[2] or "{}")
                    })
            self._ready = True
            self._worker = threading.Thread(
                target=self._run_loop, daemon=True, name="nex_execution")
            self._worker.start()
            log.info(f"ExecutionEngine init: {len(rows)} pending tasks loaded")
        except Exception as e:
            log.warning(f"ExecutionEngine.init: {e}")
            self._ready = True

    def enqueue(self, task_type: str, payload: dict = None):
        with self._lock:
            self._queue.append({"type": task_type, "payload": payload or {}})
        try:
            con = sqlite3.connect(_DB)
            con.execute("""INSERT INTO execution_queue (task_type, payload)
                VALUES (?, ?)""", (task_type, json.dumps(payload or {})))
            con.commit(); con.close()
        except Exception as e:
            log.warning(f"enqueue DB write: {e}")

    def _run_loop(self):
        while True:
            task = None
            with self._lock:
                if self._queue:
                    task = self._queue.popleft()
            if task:
                self._execute(task)
            time.sleep(5)

    def _execute(self, task: dict):
        ttype = task.get("type","")
        payload = task.get("payload", {})
        try:
            if ttype == "throw_net":
                from nex.nex_throw_net import ThrowNetEngine
                constraint = payload.get("constraint", "general improvement")
                ThrowNetEngine(_DB).run(constraint, trigger_mode="autonomous")
            elif ttype == "research":
                query = payload.get("query", "")
                if query:
                    log.info(f"[EE] research: {query[:60]}")
            else:
                log.info(f"[EE] task: {ttype}")
            # Mark done
            task_id = task.get("id")
            if task_id:
                con = sqlite3.connect(_DB)
                con.execute("""UPDATE execution_queue SET status='done'
                    WHERE id=?""", (task_id,))
                con.commit(); con.close()
        except Exception as e:
            log.warning(f"_execute {ttype}: {e}")

    def queue_size(self) -> int:
        with self._lock: return len(self._queue)

def get_execution_engine() -> ExecutionEngine:
    global _instance
    if _instance is None:
        _instance = ExecutionEngine()
    return _instance
PYEOF
ok "nex_execution_engine.py written"

# ── 5. Verify ─────────────────────────────────────────────────────────────────
echo ""
echo "▸ Verifying all modules..."
python3 << 'VERIFYEOF'
import sys, os
sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))
sys.path.insert(0, os.path.expanduser("~/Desktop/nex/nex"))

modules = [
    ("nex_mastodon",               "start_mastodon_background"),
    ("nex_adaptive_intelligence",  "get_adaptive_intelligence"),
    ("nex_signal_engine",          "get_signal_engine"),
    ("nex_execution_engine",       "get_execution_engine"),
]
all_ok = True
for mod, fn in modules:
    try:
        m = __import__(mod)
        assert hasattr(m, fn), f"missing {fn}"
        print(f"  \033[0;32m[✓]\033[0m {mod}.{fn}")
    except Exception as e:
        print(f"  \033[1;33m[!]\033[0m {mod}: {e}")
        all_ok = False

# chromadb
try:
    import chromadb
    print(f"  \033[0;32m[✓]\033[0m chromadb {chromadb.__version__}")
except Exception as e:
    print(f"  \033[1;33m[!]\033[0m chromadb: {e}")
    all_ok = False

print()
if all_ok:
    print("\033[0;32m All engine modules OK — restart NEX with: nex\033[0m")
else:
    print("\033[1;33m Some modules need attention\033[0m")
VERIFYEOF

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Done. Now run: nex"
echo "═══════════════════════════════════════════════════════"
echo ""
