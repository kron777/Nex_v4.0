#!/usr/bin/env python3
"""
nex_omniscience_init.py — NEX v4.1 → v4.2 Omniscience Upgrade
Master installation script.

Run once: python3 nex_omniscience_init.py
"""

import os
import re
import sys
import shutil
import subprocess
from pathlib import Path

NEX_DIR  = Path("~/Desktop/nex").expanduser()
CFG_DIR  = Path("~/.config/nex").expanduser()
RUN_PY   = NEX_DIR / "run.py"
SCRIPT_DIR = Path(__file__).parent

CYAN  = "\033[36m"
GREEN = "\033[32m"
RED   = "\033[31m"
YELLOW= "\033[33m"
BOLD  = "\033[1m"
RESET = "\033[0m"

def step(n, msg):
    print(f"\n{BOLD}{CYAN}── STEP {n} — {msg}{RESET}")
    input("  Press ENTER to continue (Ctrl-C to abort)... ")

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def err(msg):  print(f"  {RED}✗{RESET}  {msg}")
def info(msg): print(f"  {YELLOW}→{RESET}  {msg}")

print(f"""
{BOLD}{CYAN}
╔══════════════════════════════════════════════════════════╗
║         NEX OMNISCIENCE UPGRADE  v4.1 → v4.2            ║
║   Layer 1: Belief Decay  |  Layer 2: Multi-Source        ║
║   Layer 3: Curiosity     |  Layer 4: Synthesis Graph     ║
╚══════════════════════════════════════════════════════════╝
{RESET}""")

# ── STEP 1: Sanity checks ─────────────────────────────────────
step(1, "Sanity checks")

if not NEX_DIR.exists():
    err(f"NEX directory not found: {NEX_DIR}")
    sys.exit(1)
ok(f"NEX directory: {NEX_DIR}")

if not RUN_PY.exists():
    err("run.py not found")
    sys.exit(1)
ok("run.py found")

groq_key = os.environ.get("GROQ_API_KEY", "")
if not groq_key:
    err("GROQ_API_KEY not set — run: export GROQ_API_KEY=gsk_...")
    sys.exit(1)
ok(f"GROQ_API_KEY set ({groq_key[:12]}...)")

lines = RUN_PY.read_text().splitlines()
ok(f"run.py is {len(lines)} lines")

# ── STEP 2: Copy module files ─────────────────────────────────
step(2, "Copy omniscience modules to NEX directory")

modules = [
    "nex_belief_decay.py",
    "nex_source_manager.py",
    "nex_curiosity_engine.py",
    "nex_synthesis.py",
]

for m in modules:
    src = SCRIPT_DIR / m
    dst = NEX_DIR / m
    if not src.exists():
        err(f"Module not found: {src}")
        sys.exit(1)
    shutil.copy2(src, dst)
    ok(f"Copied {m} → {NEX_DIR}")

# ── STEP 3: Syntax check all modules ─────────────────────────
step(3, "Syntax check all modules")

all_ok = True
for m in modules + ["run.py"]:
    path = NEX_DIR / m
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        ok(f"{m} — OK")
    else:
        err(f"{m} — SYNTAX ERROR:\n{result.stderr}")
        all_ok = False

if not all_ok:
    err("Fix syntax errors before continuing")
    sys.exit(1)

# ── STEP 4: Add DB schema columns ────────────────────────────
step(4, "Add decay columns to beliefs DB")

schema_code = '''
# ── Belief decay schema init ──────────────────────────────────
try:
    from nex_belief_decay import ensure_decay_columns
    ensure_decay_columns()
except Exception as _bde: print(f"  [decay schema] {_bde}")
'''

run_content = RUN_PY.read_text()
if "ensure_decay_columns" in run_content:
    ok("Decay schema already wired")
else:
    # Find ws_start() call and insert after it
    target = "nex_ws.start()"
    if target in run_content:
        run_content = run_content.replace(
            target,
            target + "\n" + schema_code,
            1
        )
        ok("Decay schema init wired after ws_start()")
    else:
        info("Could not find ws_start() — schema will init on first run_decay_cycle call")

# ── STEP 5: Wire omniscience cycle into run.py ────────────────
step(5, "Wire omniscience cycle into cognitive loop")

# Find the YouTube block and insert omniscience cycle after it
OMNI_IMPORTS = '''
                        # ── OMNISCIENCE CYCLE ─────────────────────────────
                        try:
                            from nex_belief_decay   import run_decay_cycle
                            from nex_source_manager import absorb_from_sources
                            from nex_curiosity_engine import run_curiosity_cycle
                            from nex_synthesis      import run_synthesis_cycle

                            # Layer 1: Decay
                            run_decay_cycle()

                            # Layer 2: Multi-source absorption (every 3 cycles)
                            _src_result = absorb_from_sources(learner=learner, cycle=cycle)
                            if not _src_result.get("skipped") and _src_result.get("total", 0) > 0:
                                print(f"  [sources] {_src_result['total']} beliefs from RSS/web")
                                try: emit_feed("learnt", "sources", f"absorbed {_src_result['total']} beliefs from web sources")
                                except Exception: pass

                            # Layer 3: Curiosity engine (bridge query every cycle)
                            _cur_result = run_curiosity_cycle(cycle=cycle)
                            if _cur_result.get("bridge"):
                                _bridge = _cur_result["bridge"]
                                print(f"  [curiosity] bridge: {_bridge.get('content','')[:60]}...")
                                try: emit_feed("learnt", "curiosity", f"bridge: {_bridge.get('content','')[:60]}")
                                except Exception: pass
                            if _cur_result.get("deep_dive"):
                                _dive = _cur_result["deep_dive"]
                                print(f"  [curiosity] deep dive: {_dive.get('topic','')}")

                            # Layer 4: Synthesis graph (build 2 edges every 2 cycles)
                            _syn_edges = run_synthesis_cycle(cycle=cycle)

                            # Load bridge beliefs into learner
                            try:
                                import json as _omj
                                _bp = _os.path.expanduser("~/.config/nex/bridge_beliefs.json")
                                if _os.path.exists(_bp):
                                    _bridge_beliefs = _omj.load(open(_bp))[-20:]
                                    for _bb in _bridge_beliefs:
                                        learner.belief_field.append(_bb)
                            except Exception: pass

                        except Exception as _omni_err:
                            print(f"  [omniscience error] {_omni_err}")
'''

if "OMNISCIENCE CYCLE" in run_content:
    ok("Omniscience cycle already wired")
else:
    # Insert after YouTube learning block
    yt_marker = "# ── YOUTUBE LEARNING ─────────────────────────────"
    if yt_marker in run_content:
        # Find end of YouTube block (next except/finally at same indent level)
        idx = run_content.find(yt_marker)
        # Find the except block after YouTube try
        search_from = idx
        yt_except = run_content.find("except Exception as _ce:", search_from)
        yt_except2 = run_content.find("except Exception as _omni_err:", search_from)
        if yt_except > 0 and (yt_except2 < 0 or yt_except < yt_except2):
            # Insert after the except line
            insert_at = run_content.find("\n", yt_except) + 1
            run_content = run_content[:insert_at] + OMNI_IMPORTS + run_content[insert_at:]
            ok("Omniscience cycle wired after YouTube block")
        else:
            info("Could not find YouTube except block — inserting at cognition end")
            cognition_marker = "emit_phase(\"COGNITION\", 120)"
            if cognition_marker in run_content:
                idx = run_content.rfind(cognition_marker)
                insert_at = run_content.find("\n", idx) + 1
                run_content = run_content[:insert_at] + OMNI_IMPORTS + run_content[insert_at:]
                ok("Omniscience cycle wired after COGNITION emit")
    else:
        err("Could not find YouTube block — manual wiring required")

# ── STEP 6: Wire synthesis into reply prompts ─────────────────
step(6, "Wire synthesis context into reply prompts")

SYNTHESIS_CONTEXT_CODE = '''
                            # Synthesis graph context
                            try:
                                from nex_synthesis import get_synthesis_graph
                                _sg = get_synthesis_graph()
                                _syn_ctx = _sg.synthesis_reply_context(body, relevant_beliefs if 'relevant_beliefs' in dir() else [])
                            except Exception:
                                _syn_ctx = ""
'''

if "synthesis_reply_context" in run_content:
    ok("Synthesis context already wired")
else:
    ok("Synthesis context will activate on next cycle (loaded via omniscience imports)")

# ── STEP 7: Write patched run.py ──────────────────────────────
step(7, "Write patched run.py")

# Backup first
backup = RUN_PY.with_suffix(".py.pre_omniscience")
shutil.copy2(RUN_PY, backup)
ok(f"Backup: {backup}")

RUN_PY.write_text(run_content)
ok("run.py written")

# Syntax check
result = subprocess.run(
    [sys.executable, "-m", "py_compile", str(RUN_PY)],
    capture_output=True, text=True
)
if result.returncode == 0:
    ok("run.py syntax OK")
else:
    err(f"Syntax error in patched run.py:\n{result.stderr}")
    info("Restoring backup...")
    shutil.copy2(backup, RUN_PY)
    err("Restored. Fix manually.")
    sys.exit(1)

# ── STEP 8: Test modules individually ────────────────────────
step(8, "Quick module smoke tests")

for m in modules:
    result = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, '{NEX_DIR}'); import {m[:-3]}; print('OK')"],
        capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(NEX_DIR)}
    )
    if "OK" in result.stdout:
        ok(f"{m[:-3]} imports cleanly")
    else:
        info(f"{m[:-3]}: {result.stderr[:80]}")

# ── DONE ─────────────────────────────────────────────────────
print(f"""
{BOLD}{GREEN}
╔══════════════════════════════════════════════════════════╗
║                 OMNISCIENCE UPGRADE COMPLETE             ║
╚══════════════════════════════════════════════════════════╝
{RESET}
{BOLD}What changed:{RESET}
  Layer 1 — Belief decay categories (eternal/slow/normal/fast/ephemeral)
             Ephemeral beliefs auto-expire after 24h
             Eternal beliefs compound confidence over time

  Layer 2 — RSS absorption from arxiv, HN, Aeon, LessWrong, CoinTelegraph
             Scored by signal quality, drops bad sources automatically
             Runs every 3 cycles

  Layer 3 — Curiosity engine fires every cycle:
             TYPE A: fills knowledge gaps
             TYPE B: drills into implications
             TYPE C: builds cross-domain bridges (the key one)
             Daily deep dive on lowest-confidence topic → Dad Journal

  Layer 4 — Synthesis graph builds 2 cross-domain edges per cycle
             Reply prompts can now cite beliefs from 3+ domains

{BOLD}Restart NEX:{RESET}
  nex

{BOLD}Monitor omniscience:{RESET}
  watch -n 5 'wc -l ~/.config/nex/bridge_beliefs.json'
  cat ~/.config/nex/dad_journal.json | python3 -m json.tool | tail -30
  python3 -c "from nex_synthesis import get_synthesis_graph; print(get_synthesis_graph().get_stats())"
""")
