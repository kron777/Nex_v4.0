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
