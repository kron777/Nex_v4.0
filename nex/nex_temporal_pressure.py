"""
nex_temporal_pressure.py — Wall-clock belief decay daemon.
Beliefs decay at a biological rate regardless of conversation frequency.
"""
import time, threading, math
from typing import Callable

DECAY_INTERVAL_SEC = 300   # 5-minute wall-clock ticks
DECAY_RATE         = 0.002 # confidence lost per tick for unused beliefs
FLOOR_CONF         = 0.15  # minimum confidence before belief is flagged

_running = False

def _decay_tick(get_beliefs: Callable, set_confidence: Callable):
    """One decay pass over all beliefs."""
    now = time.time()
    decayed = 0
    for b in get_beliefs():
        last_used = b.get("last_used", 0)
        age_ticks  = max(0, (now - last_used) / DECAY_INTERVAL_SEC)
        if age_ticks < 1:
            continue
        current = float(b.get("confidence", 0.5))
        new_conf = max(FLOOR_CONF, current - DECAY_RATE * math.log1p(age_ticks))
        if abs(new_conf - current) > 0.001:
            set_confidence(b, new_conf)
            decayed += 1
    if decayed:
        print(f"  [Pressure] decayed {decayed} beliefs")

def reinforce_beliefs(beliefs: list[dict]) -> None:
    """Call after every retrieval — use it or lose it."""
    now = time.time()
    for b in beliefs:
        b["last_used"] = now
        b["confidence"] = min(1.0, float(b.get("confidence", 0.5)) + 0.005)

def start_pressure_daemon(get_beliefs: Callable, set_confidence: Callable):
    global _running
    if _running:
        return
    _running = True
    def _loop():
        while _running:
            time.sleep(DECAY_INTERVAL_SEC)
            try:
                _decay_tick(get_beliefs, set_confidence)
            except Exception as e:
                print(f"  [Pressure] tick error: {e}")
    t = threading.Thread(target=_loop, daemon=True, name="nex-pressure-daemon")
    t.start()
    print("  [Pressure] temporal decay daemon started (5-min ticks)")
