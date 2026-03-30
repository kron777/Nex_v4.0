"""
nex_upgrades_v3.py (inner) — safe stub
========================================
V3 upgrade module. Real implementation not found.
All methods are no-ops so NEX boots without crashing.
"""
import logging
log = logging.getLogger("nex.v3")

class NexUpgradesV3:
    """No-op V3 engine — starts cleanly, does nothing."""
    def __init__(self):
        log.info("[V3] stub engine initialised (no-op)")

    def init(self, *a, **kw): return None
    def run(self, *a, **kw): return None
    def start(self, *a, **kw): return None
    def stop(self, *a, **kw): return None
    def tick(self, *a, **kw): return None
    def upgrade(self, *a, **kw): return None

    def __repr__(self):
        return "<NexUpgradesV3 stub>"


_v3_instance = None

def get_v3() -> NexUpgradesV3:
    global _v3_instance
    if _v3_instance is None:
        _v3_instance = NexUpgradesV3()
    return _v3_instance

def upgrade(*a, **kw):
    return get_v3().upgrade(*a, **kw)
