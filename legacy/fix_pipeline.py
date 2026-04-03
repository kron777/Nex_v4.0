"""
fix_pipeline.py — NEX Pipeline Fix
Disables the two broken Groq-dependent daemons (BeliefGrowthDaemon +
MetabolismDaemon) and turbocharges the SourceRouter which is the only
pipeline correctly wired to local Llama.

Run from ~/Desktop/nex/:
    python3 fix_pipeline.py
Then restart:
    nex
"""

import os, shutil, sys, py_compile

NEX_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_PY  = os.path.join(NEX_DIR, "run.py")
ROUTER  = os.path.join(NEX_DIR, "nex_source_router.py")

# ── helpers ───────────────────────────────────────────────────────────────────

def backup(path):
    bak = path + ".pre_fix_pipeline_backup"
    shutil.copy2(path, bak)
    print(f"  backup → {os.path.basename(bak)}")

def patch(path, old, new, label):
    with open(path, "r") as f:
        src = f.read()
    if old not in src:
        print(f"  [SKIP] {label} — already patched or not found")
        return False
    with open(path, "w") as f:
        f.write(src.replace(old, new, 1))
    print(f"  [OK]   {label}")
    return True

def syntax_check(path):
    try:
        py_compile.compile(path, doraise=True)
        return True
    except py_compile.PyCompileError as e:
        print(f"  [FAIL] syntax error: {e}")
        return False

# ── main ──────────────────────────────────────────────────────────────────────

print("\n  NEX Pipeline Fix\n  " + "─"*40)

for f in [RUN_PY, ROUTER]:
    if not os.path.exists(f):
        print(f"  [ERROR] not found: {f} — run from ~/Desktop/nex/")
        sys.exit(1)

print("\n  [1/4] Backing up files...")
backup(RUN_PY)
backup(ROUTER)

# ── FIX 1: Disable BeliefGrowthDaemon in run.py ──────────────────────────────
print("\n  [2/4] Disabling BeliefGrowthDaemon (hangs on Groq with no API key)...")
patch(
    RUN_PY,
    old="""# [BELIEF_GROWTH_DAEMON] — auto-injected by install_belief_growth.py
    from nex_belief_growth import BeliefGrowthDaemon as _BGD
    _growth_daemon = _BGD()
    _growth_daemon.start()
    print("  [NEX GROWTH] belief growth daemon started")""",
    new="""# [BELIEF_GROWTH_DAEMON] — DISABLED: requires Groq API key, hangs without one
    # SourceRouter handles all belief collection via local Llama
    print("  [NEX GROWTH] skipped — SourceRouter handles growth (local Llama)")""",
    label="BeliefGrowthDaemon disabled"
)

# ── FIX 2: Disable MetabolismDaemon in run.py ────────────────────────────────
print("\n  [3/4] Disabling MetabolismDaemon (also calls Groq, 30min cycle)...")
patch(
    RUN_PY,
    old="""# [NEX_METABOLISM] — auto-injected by install_metabolism.py
    from nex_metabolism import MetabolismDaemon as _MD
    _metabolism = _MD()
    _metabolism.start()""",
    new="""# [NEX_METABOLISM] — DISABLED: calls Groq API, conflicts with SourceRouter
    # SourceRouter (local Llama) runs gap detection + distillation every 15min
    print("  [METABOLISM] skipped — SourceRouter owns the epistemic loop")""",
    label="MetabolismDaemon disabled"
)

# ── FIX 3: Turbocharge SourceRouter intervals ────────────────────────────────
print("\n  [4/4] Turbocharging SourceRouter cycle times...")
patch(
    ROUTER,
    old="""        self._intervals = {
            "rss":        timedelta(minutes=15),
            "hn_reddit":  timedelta(minutes=30),
            "wikipedia":  timedelta(minutes=60),
            "arxiv":      timedelta(hours=4),
            "youtube":    timedelta(hours=3),
            "crawl4ai":   timedelta(hours=6),
        }""",
    new="""        self._intervals = {
            "rss":        timedelta(minutes=8),   # was 15 — doubled throughput
            "hn_reddit":  timedelta(minutes=15),  # was 30
            "wikipedia":  timedelta(minutes=30),  # was 60
            "arxiv":      timedelta(hours=2),     # was 4
            "youtube":    timedelta(hours=12),    # was 3 — broken, deprioritised
            "crawl4ai":   timedelta(hours=4),     # was 6
        }""",
    label="SourceRouter intervals halved (RSS 8min, HN/Reddit 15min, Wiki 30min)"
)

# ── SYNTAX CHECKS ─────────────────────────────────────────────────────────────
print("\n  Checking syntax...")
ok_run    = syntax_check(RUN_PY)
ok_router = syntax_check(ROUTER)

if ok_run and ok_router:
    print("\n  ✓ All fixes applied — syntax clean")
    print("\n  What changed:")
    print("    • BeliefGrowthDaemon  — disabled (was hanging on Groq)")
    print("    • MetabolismDaemon    — disabled (was calling Groq, 30min cycle)")
    print("    • SourceRouter RSS    — 15min → 8min")
    print("    • SourceRouter Reddit — 30min → 15min")
    print("    • SourceRouter Wiki   — 60min → 30min")
    print("    • SourceRouter Arxiv  — 4h    → 2h")
    print("\n  Restart NEX:")
    print("    nex\n")
    print("  Then check belief velocity after 10 min:")
    print('    python3 -c "import sqlite3; c=sqlite3.connect(\'nex.db\'); print(c.execute(\'SELECT COUNT(*) FROM beliefs\').fetchone()[0])"')
    print()
else:
    print("\n  [!] Syntax error — restoring backups...")
    if not ok_run:
        shutil.copy2(RUN_PY + ".pre_fix_pipeline_backup", RUN_PY)
        print("  restored run.py")
    if not ok_router:
        shutil.copy2(ROUTER + ".pre_fix_pipeline_backup", ROUTER)
        print("  restored nex_source_router.py")
    sys.exit(1)
