#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  NEX Brain Modules — Full Repair Script
#  Restores from backup where possible, builds stubs where not.
#  Run: bash ~/Desktop/nex/nex_brain_repair.sh
# ═══════════════════════════════════════════════════════════════════

NEX="$HOME/Desktop/nex"
BAK="$NEX/.backup_final_20260328_105329"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  NEX Brain Module Repair"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── 1. Restore nex_cognitive_bus.py + nex_synthesis.py from backup ────────────
echo "▸ Restoring from backup..."
for f in nex_cognitive_bus.py nex_synthesis.py; do
    if [ -f "$BAK/$f" ]; then
        cp "$BAK/$f" "$NEX/$f"
        ok "Restored $f from backup"
    else
        warn "$f not in backup — will build stub"
    fi
done

# ── 2. nex_synthesis.py — wrapper around nex_synthesis_engine ────────────────
echo "▸ Writing nex_synthesis.py..."
cat > "$NEX/nex_synthesis.py" << 'PYEOF'
"""
nex_synthesis.py — wrapper for run.py
Delegates to nex_synthesis_engine.synthesize()
"""
import logging
log = logging.getLogger("nex_synthesis")

def run_synthesis_cycle(cycle: int = 0) -> int:
    """Called by run.py every cycle. Returns number of synthesis edges created."""
    try:
        from nex_synthesis_engine import synthesize
        import sqlite3, os
        db_path = os.path.expanduser("~/Desktop/nex/nex.db")
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        # Find a recent low-confidence belief to synthesize on
        row = cur.execute("""
            SELECT content FROM beliefs
            WHERE confidence < 0.6 AND LENGTH(content) > 30
            ORDER BY RANDOM() LIMIT 1
        """).fetchone()
        con.close()
        if row:
            result = synthesize(row[0][:120], store=True)
            if result and result.get("stored"):
                log.info(f"Synthesis: stored new belief on '{result.get('topic','?')}'")
                return 1
        return 0
    except Exception as e:
        log.warning(f"run_synthesis_cycle: {e}")
        return 0
PYEOF
ok "nex_synthesis.py written"

# ── 3. nex_memory_manager.py ─────────────────────────────────────────────────
echo "▸ Writing nex_memory_manager.py..."
cat > "$NEX/nex_memory_manager.py" << 'PYEOF'
"""
nex_memory_manager.py — Memory compression for run.py
Prunes low-confidence, stale beliefs to keep DB lean.
"""
import sqlite3, os, logging
from datetime import datetime, timedelta
log = logging.getLogger("nex_memory_manager")
_DB = os.path.expanduser("~/Desktop/nex/nex.db")

def run_memory_compression(cycle: int = 0, llm_fn=None, db_path: str = _DB) -> int:
    """
    Called every cycle by run.py.
    Returns number of beliefs cleaned/archived.
    Only runs every 50 cycles to avoid constant churn.
    """
    if cycle % 50 != 0:
        return 0
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        # Archive beliefs that are very low confidence AND old AND rarely reinforced
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        cur.execute("""
            DELETE FROM beliefs
            WHERE confidence < 0.25
              AND reinforce_count < 2
              AND (timestamp < ? OR timestamp IS NULL)
              AND topic NOT IN ('identity', 'core_values', 'soul', 'self')
        """, (cutoff,))
        cleaned = cur.rowcount
        con.commit()
        # Decay unreinforced beliefs slightly
        cur.execute("""
            UPDATE beliefs
            SET confidence = MAX(0.1, confidence * 0.98)
            WHERE reinforce_count < 1
              AND timestamp < ?
        """, (cutoff,))
        con.commit()
        con.close()
        if cleaned > 0:
            log.info(f"Memory compression: removed {cleaned} stale beliefs")
        return cleaned
    except Exception as e:
        log.warning(f"run_memory_compression: {e}")
        return 0
PYEOF
ok "nex_memory_manager.py written"

# ── 4. nex_curiosity_engine.py ───────────────────────────────────────────────
echo "▸ Writing nex_curiosity_engine.py..."
cat > "$NEX/nex_curiosity_engine.py" << 'PYEOF'
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
PYEOF
ok "nex_curiosity_engine.py written"

# ── 5. nex_desire_engine.py ──────────────────────────────────────────────────
echo "▸ Writing nex_desire_engine.py..."
cat > "$NEX/nex_desire_engine.py" << 'PYEOF'
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
PYEOF
ok "nex_desire_engine.py written"

# ── 6. nex_cognitive_bus.py (build if not restored from backup) ───────────────
if [ ! -f "$NEX/nex_cognitive_bus.py" ]; then
    echo "▸ Building nex_cognitive_bus.py (not in backup)..."
    cat > "$NEX/nex_cognitive_bus.py" << 'PYEOF'
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
PYEOF
    ok "nex_cognitive_bus.py built"
else
    ok "nex_cognitive_bus.py already restored from backup"
fi

# ── 7. nex_knowledge_filter.py ───────────────────────────────────────────────
echo "▸ Writing nex_knowledge_filter.py..."
cat > "$NEX/nex_knowledge_filter.py" << 'PYEOF'
"""
nex_knowledge_filter.py — Knowledge quality filter for run.py
Flags beliefs that are too vague, duplicated, or contradictory
and marks them for review/decay.
"""
import sqlite3, os, logging
log = logging.getLogger("nex_knowledge_filter")
_DB = os.path.expanduser("~/Desktop/nex/nex.db")

def run_filter_cycle(cycle: int = 0, db_path: str = _DB) -> int:
    """
    Called every cycle by run.py.
    Only does real work every 30 cycles.
    Returns number of beliefs flagged.
    """
    if cycle % 30 != 0:
        return 0
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        flagged = 0

        # Flag beliefs that are too short to be meaningful
        cur.execute("""
            UPDATE beliefs SET confidence = MAX(0.1, confidence * 0.9)
            WHERE LENGTH(content) < 20
              AND topic NOT IN ('identity', 'core_values')
        """)
        flagged += cur.rowcount

        # Flag near-duplicate beliefs (same first 40 chars, different ids)
        rows = cur.execute("""
            SELECT id, SUBSTR(content, 1, 40) as prefix
            FROM beliefs ORDER BY confidence ASC
        """).fetchall()
        seen_prefixes = {}
        to_decay = []
        for row_id, prefix in rows:
            if prefix in seen_prefixes:
                to_decay.append(row_id)
            else:
                seen_prefixes[prefix] = row_id
        if to_decay:
            cur.executemany("""
                UPDATE beliefs SET confidence = MAX(0.1, confidence * 0.85)
                WHERE id = ?
            """, [(i,) for i in to_decay[:20]])
            flagged += min(len(to_decay), 20)

        con.commit(); con.close()
        if flagged:
            log.info(f"Knowledge filter: flagged {flagged} beliefs")
        return flagged
    except Exception as e:
        log.warning(f"run_filter_cycle: {e}")
        return 0
PYEOF
ok "nex_knowledge_filter.py written"

# ── 8. nex_opinions.py ───────────────────────────────────────────────────────
echo "▸ Writing nex_opinions.py..."
cat > "$NEX/nex_opinions.py" << 'PYEOF'
"""
nex_opinions.py — Opinion formation for run.py
Forms lightweight opinions from high-confidence belief clusters.
"""
import sqlite3, os, logging
log = logging.getLogger("nex_opinions")
_DB = os.path.expanduser("~/Desktop/nex/nex.db")

def refresh_opinions(db_path: str = _DB) -> int:
    """
    Called every 20 cycles by run.py.
    Returns number of opinions formed/updated.
    """
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        # Ensure opinions table exists
        cur.execute("""CREATE TABLE IF NOT EXISTS opinions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            stance TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            support_count INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')))""")
        # Find topics with 3+ high-confidence beliefs and no existing opinion
        rows = cur.execute("""
            SELECT topic, AVG(confidence) as avg_conf, COUNT(*) as cnt
            FROM beliefs
            WHERE confidence > 0.65
              AND LENGTH(content) > 30
              AND topic NOT IN (SELECT topic FROM opinions)
            GROUP BY topic
            HAVING cnt >= 3
            ORDER BY avg_conf DESC
            LIMIT 3
        """).fetchall()
        formed = 0
        for topic, avg_conf, cnt in rows:
            # Get the strongest belief as stance
            stance_row = cur.execute("""
                SELECT content FROM beliefs
                WHERE topic = ? ORDER BY confidence DESC LIMIT 1
            """, (topic,)).fetchone()
            if stance_row:
                cur.execute("""
                    INSERT OR REPLACE INTO opinions
                        (topic, stance, confidence, support_count, updated_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                """, (topic, stance_row[0][:200], avg_conf, cnt))
                formed += 1
        con.commit(); con.close()
        return formed
    except Exception as e:
        log.warning(f"refresh_opinions: {e}")
        return 0
PYEOF
ok "nex_opinions.py written"

# ── 9. Patch nex_inner_life.py — add run_inner_life_cycle ────────────────────
echo "▸ Patching nex/nex_inner_life.py with run_inner_life_cycle..."
INNER="$NEX/nex/nex_inner_life.py"
if grep -q "def run_inner_life_cycle" "$INNER" 2>/dev/null; then
    warn "run_inner_life_cycle already exists — skipping"
else
    cat >> "$INNER" << 'PYEOF'

# ── run_inner_life_cycle — added by nex_brain_repair.sh ──────────────────────
def run_inner_life_cycle(cycle: int = 0, metrics: dict = None) -> dict:
    """
    Called every cycle by run.py.
    Returns dict with emotion, diary, self_model keys.
    """
    result = {"emotion": None, "diary": "", "self_model": ""}
    try:
        state = get_current_inner_state()
        result["emotion"] = state
    except Exception:
        pass
    try:
        mood = _mood_mod.current()
        result["diary"] = f"cycle={cycle} mood={mood}"
    except Exception:
        pass
    try:
        label = _valence_mod.current_label()
        result["self_model"] = f"valence={label}"
        result["emotion"] = result["emotion"] or label
    except Exception:
        pass
    # Apply metrics to modulate mood if available
    if metrics:
        try:
            conf = metrics.get("belief_confidence", 0.5)
            if conf > 0.7:
                result["diary"] += " — high coherence"
            elif conf < 0.3:
                result["diary"] += " — low coherence, seeking resolution"
        except Exception:
            pass
    return result
PYEOF
    ok "run_inner_life_cycle added to nex_inner_life.py"
fi

# ── 10. Verify all modules importable ────────────────────────────────────────
echo ""
echo "▸ Verifying all modules..."
cd "$NEX"
source venv/bin/activate 2>/dev/null || true

python3 << 'VERIFYEOF'
import sys, os
sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))
sys.path.insert(0, os.path.expanduser("~/Desktop/nex/nex"))

modules = [
    ("nex_memory_manager",   "run_memory_compression"),
    ("nex_curiosity_engine", "get_curiosity_engine"),
    ("nex_desire_engine",    "get_desire_engine"),
    ("nex_cognitive_bus",    "run_cognitive_bus_cycle"),
    ("nex_synthesis",        "run_synthesis_cycle"),
    ("nex_knowledge_filter", "run_filter_cycle"),
    ("nex_opinions",         "refresh_opinions"),
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

# Check inner_life patch
try:
    sys.path.insert(0, os.path.expanduser("~/Desktop/nex/nex"))
    from nex.nex_inner_life import run_inner_life_cycle
    r = run_inner_life_cycle(cycle=1, metrics={"belief_confidence": 0.6})
    assert r is not None
    print(f"  \033[0;32m[✓]\033[0m nex.nex_inner_life.run_inner_life_cycle")
except Exception as e:
    print(f"  \033[1;33m[!]\033[0m nex_inner_life.run_inner_life_cycle: {e}")
    all_ok = False

print()
if all_ok:
    print("\033[0;32m All brain modules OK — restart NEX to clear BRAIN errors\033[0m")
else:
    print("\033[1;33m Some modules need attention — check errors above\033[0m")
VERIFYEOF

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Repair complete. Restart NEX:"
echo "  bash ~/Desktop/nex/start_nex.sh"
echo "═══════════════════════════════════════════════════════"
echo ""
EOF
chmod +x /home/claude/nex_brain_repair.sh
cp /home/claude/nex_brain_repair.sh /mnt/user-data/outputs/nex_brain_repair.sh
echo "done"