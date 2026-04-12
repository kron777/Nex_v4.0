"""
nex_curiosity_engine.py — wrapper for run.py
Bridges existing nex_curiosity.py + curiosity_engine.py into one interface.
"""
import os, sys, logging
_ROOT = os.path.expanduser("~/Desktop/nex")
for _p in [_ROOT, os.path.join(_ROOT, "nex")]:
    if _p not in sys.path: sys.path.insert(0, _p)
log = logging.getLogger("nex_curiosity_engine")

_instance = None

class _CuriosityEngine:
    def __init__(self):
        self._inner = None
        try:
            from nex.nex_curiosity import NexCuriosity
            self._inner = NexCuriosity()
            log.info("CuriosityEngine: using NexCuriosity")
        except Exception:
            try:
                from nex.curiosity_engine import CuriosityEngine
                self._inner = CuriosityEngine()
                log.info("CuriosityEngine: using curiosity_engine.CuriosityEngine")
            except Exception as e:
                log.warning(f"CuriosityEngine: no backend available: {e}")

    def run_cycle(self, cycle: int = 0) -> dict:
        if self._inner is None:
            return {}
        try:
            # Try run_cycle first, then tick, then update
            for method in ("run_cycle", "tick", "update", "step"):
                fn = getattr(self._inner, method, None)
                if fn:
                    result = fn(cycle=cycle) if method == "run_cycle" else fn()
                    return result if isinstance(result, dict) else {"ran": True}
        except Exception as e:
            log.warning(f"curiosity run_cycle: {e}")
        return {}

def get_curiosity_engine() -> _CuriosityEngine:
    global _instance
    if _instance is None:
        _instance = _CuriosityEngine()
    return _instance
