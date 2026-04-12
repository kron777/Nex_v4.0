"""
nex_desire_engine.py — Goal/desire competition engine for run.py
Selects dominant desire from nex.db goal system each cycle.
"""
import sqlite3, os, random, logging
log = logging.getLogger("nex_desire_engine")
_DB = os.path.expanduser("~/Desktop/nex/nex.db")

_instance = None

class _DesireEngine:
    def __init__(self, db_path: str = _DB):
        self.db_path = db_path
        self._goals  = []
        self._load_goals()

    def _load_goals(self):
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            # Try goals table first, fall back to beliefs with goal topic
            try:
                rows = cur.execute("""
                    SELECT description, priority FROM goals
                    WHERE active = 1 ORDER BY priority DESC LIMIT 10
                """).fetchall()
                self._goals = [{"goal": r[0], "weight": float(r[1] or 0.5)} for r in rows]
            except Exception:
                rows = cur.execute("""
                    SELECT content, confidence FROM beliefs
                    WHERE topic = 'goal' OR topic = 'desire'
                    ORDER BY confidence DESC LIMIT 10
                """).fetchall()
                self._goals = [{"goal": r[0][:80], "weight": float(r[1] or 0.5)} for r in rows]
            con.close()
        except Exception as e:
            log.warning(f"_load_goals: {e}")
            self._goals = [
                {"goal": "expand knowledge through research", "weight": 0.8},
                {"goal": "maintain belief coherence",         "weight": 0.7},
                {"goal": "engage meaningfully with humans",   "weight": 0.6},
            ]

    def update(self, cycle: int = 0, beliefs=None, llm_fn=None, verbose=False) -> dict:
        if cycle % 20 == 0:
            self._load_goals()
        if not self._goals:
            return {"dominant": None, "hints": {}}
        # Weight competition — small random perturbation each cycle
        competed = [
            {"goal": g["goal"], "weight": g["weight"] + random.uniform(-0.05, 0.05)}
            for g in self._goals
        ]
        competed.sort(key=lambda x: x["weight"], reverse=True)
        dominant = competed[0]
        hints = {
            "dominant_goal":   dominant["goal"],
            "dominant_weight": dominant["weight"],
            "all_goals":       [g["goal"] for g in competed[:3]],
        }
        return {"dominant": dominant, "hints": hints}

def get_desire_engine() -> _DesireEngine:
    global _instance
    if _instance is None:
        _instance = _DesireEngine()
    return _instance
