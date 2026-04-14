#!/bin/bash
# ════════════════════════════════════════════════════════════════
# deploy_e140.sh — NEX E116–E140 Execution Intelligence Stack
# Usage:
#   mv ~/Downloads/nex_e140.py    ~/Desktop/nex/nex_upgrades/
#   mv ~/Downloads/deploy_e140.sh ~/Desktop/nex/
#   chmod +x ~/Desktop/nex/deploy_e140.sh
#   cd ~/Desktop/nex && source venv/bin/activate && ./deploy_e140.sh
# ════════════════════════════════════════════════════════════════
set -euo pipefail

NEX_DIR="$HOME/Desktop/nex"
RUN_PY="$NEX_DIR/run.py"
TG_CMD="$NEX_DIR/nex_telegram_commands.py"
TS=$(date +%s)

echo "══════════════════════════════════════"
echo " NEX E116–E140 — deployment starting"
echo "══════════════════════════════════════"

[[ -f "$RUN_PY" ]]                             || { echo "ERROR: run.py not found";        exit 1; }
[[ -f "$NEX_DIR/nex_upgrades/nex_e140.py" ]]  || { echo "ERROR: nex_e140.py not in nex_upgrades/"; exit 1; }

cp "$RUN_PY" "$RUN_PY.bak_e140_$TS"
echo "[✓] Backed up run.py"

# ── Patch run.py ─────────────────────────────────────────────
python3 - << 'PYEOF'
import re, ast
from pathlib import Path

RUN = Path.home() / "Desktop/nex/run.py"
src = RUN.read_text()

if "nex_e140" in src:
    print("[e140] run.py already patched — skipping")
    exit(0)

E140_IMPORT = (
    "\n# ── E116–E140 execution intelligence stack ─────────────\n"
    "try:\n"
    "    from nex_upgrades.nex_e140 import get_e140 as _get_e140\n"
    "    _e140 = _get_e140()\n"
    "except Exception as _e140_ex:\n"
    "    print(f'[e140] Load failed: {_e140_ex}')\n"
    "    _e140 = None\n"
)

for anchor in ["    _r115 = None\n", "_r115 = None\n",
               "    _u100 = None\n", "_u100 = None\n",
               "    _v80 = None\n",  "_v80 = None\n"]:
    idx = src.find(anchor)
    if idx != -1:
        src = src[:idx + len(anchor)] + E140_IMPORT + src[idx + len(anchor):]
        print(f"[e140] Import injected after: {anchor.strip()!r}")
        break
else:
    m = re.search(r'import signal\n', src)
    assert m, "No import anchor"
    src = src[:m.end()] + E140_IMPORT + src[m.end():]
    print("[e140] Import injected after 'import signal'")

lines     = src.splitlines(keepends=True)
insert_at = None
pad       = "                    "

for i, ln in enumerate(lines):
    if "nex_r115_err.txt" in ln:
        pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
        insert_at = i + 1
        break

if insert_at is None:
    for i, ln in enumerate(lines):
        if "nex_u100_err.txt" in ln:
            pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
            insert_at = i + 1
            break

if insert_at is None:
    for i, ln in enumerate(lines):
        if "nex_v80_err.txt" in ln:
            pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
            insert_at = i + 1
            break

assert insert_at is not None, "No tick anchor found"

TICK = [
    "\n",
    f"{pad}# ── E116–E140 tick ─────────────────────────────────\n",
    f"{pad}if _e140 is not None:\n",
    f"{pad}    try:\n",
    f"{pad}        _ae140 = _v2ac if '_v2ac' in dir() else 0.50\n",
    f"{pad}        _te140 = float(getattr(_s7,'tension_score',0.0)) if '_s7' in dir() and _s7 else 0.0\n",
    f"{pad}        _ph_e  = str(getattr(getattr(_v80,'gss',None),'phase',type('x',(),{{'value':'stable'}})()).value) if '_v80' in dir() and _v80 else 'stable'\n",
    f"{pad}        try:\n",
    f"{pad}            with __import__('sqlite3').connect(str(__import__('pathlib').Path.home()/'.config/nex/nex.db'),timeout=3) as _cE:\n",
    f"{pad}                _cE.row_factory = __import__('sqlite3').Row\n",
    f"{pad}                _bcE  = _cE.execute('SELECT COUNT(*) FROM beliefs').fetchone()[0]\n",
    f"{pad}                _ctE  = _cE.execute(\"SELECT COUNT(*) FROM beliefs WHERE topic LIKE '%contradiction%'\").fetchone()[0]\n",
    f"{pad}        except Exception: _bcE=1000; _ctE=0\n",
    f"{pad}        _e140.tick(avg_conf=_ae140, tension=_te140, phase=_ph_e,\n",
    f"{pad}                   belief_count=_bcE, contradiction_count=_ctE, cycle=cycle)\n",
    f"{pad}    except Exception as _ee140:\n",
    f"{pad}        open('/tmp/nex_e140_err.txt','a').write(str(_ee140)+'\\n')\n",
]

for k, bl in enumerate(TICK):
    lines.insert(insert_at + k, bl)

src = "".join(lines)
ast.parse(src)
RUN.write_text(src)
print(f"[e140] run.py written — tick at line {insert_at}")
PYEOF

echo "[✓] run.py patched"

# ── Register /e140status ─────────────────────────────────────
python3 - << 'PYEOF'
from pathlib import Path
tc  = Path.home() / "Desktop/nex/nex_telegram_commands.py"
src = tc.read_text()
if "e140_status" in src:
    print("[e140] /e140status already registered"); exit(0)
CMD = '''
async def e140_status_command(update, context):
    """NEX E116–E140 — execution intelligence stack status."""
    try:
        from nex_upgrades.nex_e140 import get_e140
        msg = get_e140().format_status()
    except Exception as e:
        msg = f"e140 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")

'''
HANDLER = '    application.add_handler(CommandHandler("e140status", e140_status_command))\n'
idx = src.find("def register_handlers")
if idx == -1: idx = src.rfind("application.add_handler(CommandHandler")
if idx == -1: src = src + "\n" + CMD
else: src = src[:idx] + CMD + src[idx:]
last = src.rfind("application.add_handler(CommandHandler")
if last != -1:
    eol = src.find("\n", last) + 1
    src = src[:eol] + HANDLER + src[eol:]
tc.write_text(src)
print("[e140] /e140status registered")
PYEOF

echo "[✓] /e140status registered"

# ── Init persistent files ────────────────────────────────────
python3 - << 'PYEOF'
import json
from pathlib import Path
cfg = Path.home() / ".config/nex"

for fname, default in [
    ("benchmarks.json",    []),
    ("action_impact.json", {}),
]:
    f = cfg / fname
    if not f.exists():
        f.write_text(json.dumps(default))
        print(f"[e140] {fname} created")
    else:
        print(f"[e140] {fname} exists ✓")
PYEOF

echo "[✓] Persistent files initialised"

# ── Syntax checks ─────────────────────────────────────────────
python3 -m py_compile "$NEX_DIR/nex_upgrades/nex_e140.py" && echo "[✓] nex_e140.py OK"
python3 -m py_compile "$RUN_PY"                            && echo "[✓] run.py OK"
python3 -m py_compile "$TG_CMD"                            && echo "[✓] telegram_commands OK"

# ── Git commit + push ─────────────────────────────────────────
cd "$NEX_DIR"
git add nex_upgrades/nex_e140.py run.py nex_telegram_commands.py
git commit -m "E116-E140: 25-module execution intelligence stack — StrategyExtractionV2, StrategyExecutionPriority, PolicyGradientUpdate, OutputHardFormat, BeliefKillSystem, ContradictionResolutionV2, DecisionTraceEnforcement, ThoughtCompression, ResponseValueScoring, DynamicPhaseOverride, StrategyDecay, ExperienceFailurePriority, InternalBenchmark, StyleElimination, GlobalCoherence, ActionImpactTracker, MultiHorizonPlanning, SelfInterrupt, SignalPriorityQueueV2, IdentityHardConstraint, LearningRateAdaptation, MemoryAccessOptimizer, AgentSilenceMode, StrategyCompetition, TrueSelfConsistency | /e140status"
git push

echo ""
echo "══════════════════════════════════════"
echo " E116–E140 deployed. Restart:"
echo "   pkill -f run.py; sleep 2; nex"
echo " Verify:"
echo "   sleep 20 && tail -5 /tmp/nex_e140.log"
echo " Telegram: /e140status"
echo "══════════════════════════════════════"
