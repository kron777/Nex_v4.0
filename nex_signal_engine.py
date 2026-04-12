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
