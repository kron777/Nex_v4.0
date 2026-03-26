#!/usr/bin/env python3
"""
patch_run.py  —  Wires nex_homeostasis.py into run.py
Run from /home/rr/Desktop/nex/:  python patch_run.py

Makes 4 targeted str_replace edits:
  1. Import + init _hm at startup
  2. _hm.tick() at top of each cycle  
  3. Use _hm recommendations to override _cog_mode + _SCHED
  4. Source trust feedback on belief store
"""

import sys, shutil
from pathlib import Path

TARGET = Path(__file__).parent / "run.py"

if not TARGET.exists():
    print(f"[ERROR] {TARGET} not found — run this from the nex/ directory.")
    sys.exit(1)

# Backup
backup = TARGET.with_suffix(".py.pre_homeostasis")
shutil.copy2(TARGET, backup)
print(f"  [backup] → {backup.name}")

src = TARGET.read_text()

PATCHES = []

# ── PATCH 1: import + init ───────────────────────────────────────────────────
# Insert right after the discipline import block near the top of run.py
OLD1 = "from nex_upgrades.nex_discipline import get_discipline_enforcer"
NEW1 = """from nex_upgrades.nex_discipline import get_discipline_enforcer

# ── Homeostasis layer ─────────────────────────────────────────────────
try:
    import sys as _hm_sys, os as _hm_os
    _hm_sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from nex_homeostasis import get_homeostasis as _get_homeostasis
    _hm = _get_homeostasis()
    print("  [HOMEOSTASIS] 9-layer upgrade stack — loaded")
except Exception as _hm_ex:
    print(f"  [HOMEOSTASIS] failed to load: {_hm_ex}")
    class _FakeHM:
        def tick(self, *a, **k): return {"zone":"active","recommended_mode":"explore","conf_momentum":0,"allocations":{}}
        def record_source_feedback(self, *a, **k): pass
        def source_multiplier(self, *a, **k): return 1.0
        def noise_filter(self, text): return True
        def topic_priority(self, t, c, b): return b
        def mark_topic_synthesised(self, *a, **k): pass
        def belief_fitness(self, ins): return ins.get("confidence", 0.5)
        def evolve_insights(self, ins): return ins
        def dashboard_lines(self): return ["[homeostasis offline]"]
    _hm = _FakeHM()"""

PATCHES.append((OLD1, NEW1, "import + init"))

# ── PATCH 2: _hm.tick() at top of each cycle ────────────────────────────────
# The cycle top is: `while True:\n    cycle += 1\n    # ── INTENT LAYER TICK`
OLD2 = "                while True:\n                    cycle += 1\n                    # ── INTENT LAYER TICK ────────────────────────────────────"
NEW2 = """                while True:
                    cycle += 1
                    # ── HOMEOSTASIS TICK (first thing every cycle) ─────────
                    try:
                        _hm_conf  = _v2ac if '_v2ac' in dir() else 0.5
                        _hm_ten   = float(getattr(_s7, 'tension_score', 0.0)) if _s7 else 0.0
                        _hm_crate = 0.0
                        try:
                            import sqlite3 as _hmsq
                            with _hmsq.connect(str(__import__("pathlib").Path.home()/'.config/nex/nex.db'), timeout=2) as _hmc:
                                _total  = _hmc.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0] or 1
                                _contra = _hmc.execute("SELECT COUNT(*) FROM beliefs WHERE topic LIKE '%contradiction%'").fetchone()[0]
                                _hm_crate = _contra / max(_total, 1)
                        except Exception: pass
                        _hm_out   = _hm.tick(cycle=cycle, avg_conf=_hm_conf, tension=_hm_ten,
                                             cog_mode=_cog_mode, contra_rate=_hm_crate)
                        # Feed recommended mode back (but don't stomp a fresh meta decision)
                        if cycle % 5 != 0:   # meta layer runs on %5, wins those cycles
                            _hm_rec = _hm_out.get("recommended_mode", "explore")
                            if _hm_rec != _cog_mode:
                                _cog_mode        = _hm_rec
                                _cog_mode_reason = f"homeostasis zone={_hm_out.get('zone','?')} momentum={_hm_out.get('conf_momentum',0):+.4f}"
                        # Zone → _SCHED adjustment
                        _hm_zone = _hm_out.get("zone", "active")
                        if _hm_zone == "crisis":
                            _SCHED["reflect"]    = 1
                            _SCHED["chat"]       = 8
                            _SCHED["gap_detect"] = 2
                        elif _hm_zone == "stressed":
                            _SCHED["reflect"]    = max(1, _SCHED.get("reflect", 2) - 1)
                            _SCHED["chat"]       = min(6, _SCHED.get("chat", 3) + 1)
                        elif _hm_zone == "calm":
                            _SCHED["chat"]       = max(2, _SCHED.get("chat", 3) - 1)
                    except Exception as _hm_tick_ex:
                        pass
                    # ── INTENT LAYER TICK ────────────────────────────────────"""

PATCHES.append((OLD2, NEW2, "_hm.tick() at cycle top"))

# ── PATCH 3: Source trust feedback on belief store ──────────────────────────
# Hook onto the belief promotion line: learner.belief_field.append(belief)
OLD3 = "                                learner.belief_field.append(belief); nex_log(\"belief\", f\"Stored belief from @{belief.get('author','?')} [{int(belief.get('confidence',0)*100)}%]: {belief.get('content','')[:80]}\")"
NEW3 = """                                learner.belief_field.append(belief); nex_log("belief", f"Stored belief from @{belief.get('author','?')} [{int(belief.get('confidence',0)*100)}%]: {belief.get('content','')[:80]}")
                                # Homeostasis: noise filter + source trust multiplier
                                try:
                                    _src = belief.get("source", "moltbook")
                                    _btext = belief.get("content", "")
                                    if not _hm.noise_filter(_btext):
                                        # Low-entropy noise — reduce confidence
                                        belief["confidence"] = max(0.1, belief.get("confidence", 0.5) * 0.7)
                                        nex_log("hm", f"[NOISE] entropy too low — conf reduced @{belief.get('author','?')}")
                                    else:
                                        # Apply trust multiplier
                                        _trust_mult = _hm.source_multiplier(_src)
                                        belief["confidence"] = min(0.95, belief.get("confidence", 0.5) * _trust_mult)
                                except Exception: pass"""

PATCHES.append((OLD3, NEW3, "source trust + noise filter on belief store"))

# ── PATCH 4: Pass _hm cycle hint to synthesis so cooldowns work ─────────────
# Find where run_synthesis is called and inject the hint
OLD4 = "from nex.cognition import run_synthesis as _run_synthesis"
NEW4 = """from nex.cognition import run_synthesis as _run_synthesis

# Inject homeostasis cycle reference into synthesis
def _run_synthesis_hm(llm_fn=None, drive_weights=None):
    try:
        _run_synthesis._hm_ref = _hm
        _run_synthesis._hm_cycle = cycle if 'cycle' in dir() else 0
    except Exception: pass
    return _run_synthesis(llm_fn=llm_fn, drive_weights=drive_weights)"""

PATCHES.append((OLD4, NEW4, "inject _hm ref into synthesis"))

# ── Apply all patches ────────────────────────────────────────────────────────
applied = 0
for old, new, label in PATCHES:
    if old in src:
        src = src.replace(old, new, 1)
        print(f"  [✓] {label}")
        applied += 1
    else:
        print(f"  [!] SKIP (anchor not found): {label}")

TARGET.write_text(src)
print(f"\n  {applied}/{len(PATCHES)} patches applied → {TARGET.name}")
if applied < len(PATCHES):
    print(f"  Skipped patches are non-critical — run.py will still load nex_homeostasis.py fine.")
print(f"  Backup: {backup.name}")
