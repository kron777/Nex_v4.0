"""
nex_cognitive_bus.py — Sentience 5.5 cognitive integration bus
Coordinates affect, inner life, consequence and working memory
into a unified cycle state for run.py.
"""
import os, sys, sqlite3, logging
from datetime import datetime
_ROOT = os.path.expanduser("~/Desktop/nex")
for _p in [_ROOT, os.path.join(_ROOT, "nex")]:
    if _p not in sys.path: sys.path.insert(0, _p)
log = logging.getLogger("nex_cognitive_bus")
_DB = os.path.join(_ROOT, "nex.db")

def run_cognitive_bus_cycle(cycle: int = 0, recent_posts: list = None) -> dict:
    """
    Called every cycle by run.py.
    Returns bus state dict with emotion, pressure, and integration metrics.
    """
    state = {"cycle": cycle, "emotion": {}, "pressure": 0.0, "integrated": []}

    # ── Affect state ──────────────────────────────────────────────
    try:
        from nex.nex_affect import AffectState
        _affect = AffectState.instance() if hasattr(AffectState, 'instance') else AffectState()
        label = _affect.label() if hasattr(_affect, 'label') else str(_affect)
        intensity = _affect.intensity() if hasattr(_affect, 'intensity') else 0.5
        state["emotion"] = {"label": label, "intensity": intensity}
        state["integrated"].append("affect")
    except Exception as e:
        state["emotion"] = {"label": "neutral", "intensity": 0.5}

    # ── Cognitive pressure ────────────────────────────────────────
    try:
        con = sqlite3.connect(_DB)
        cur = con.cursor()
        row = cur.execute("""
            SELECT AVG(1.0 - confidence) FROM beliefs
            WHERE timestamp > datetime('now', '-1 hour')
        """).fetchone()
        con.close()
        state["pressure"] = float(row[0] or 0.3)
        state["integrated"].append("pressure")
    except Exception:
        state["pressure"] = 0.3

    # ── Working memory pulse ──────────────────────────────────────
    try:
        from nex.nex_working_memory import get_working_memory
        wm = get_working_memory()
        if hasattr(wm, 'pulse'):
            wm.pulse(cycle=cycle)
        state["integrated"].append("working_memory")
    except Exception:
        pass

    # ── Write bus state to DB for HUD ────────────────────────────
    try:
        con = sqlite3.connect(_DB)
        con.execute("""CREATE TABLE IF NOT EXISTS cognitive_bus_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle INTEGER, emotion TEXT, pressure REAL,
            ts TEXT DEFAULT (datetime('now')))""")
        con.execute("""INSERT INTO cognitive_bus_log (cycle, emotion, pressure)
            VALUES (?, ?, ?)""",
            (cycle, state["emotion"].get("label","?"), state["pressure"]))
        # Keep only last 200 rows
        con.execute("""DELETE FROM cognitive_bus_log WHERE id NOT IN (
            SELECT id FROM cognitive_bus_log ORDER BY id DESC LIMIT 200)""")
        con.commit(); con.close()
    except Exception:
        pass

    return state
