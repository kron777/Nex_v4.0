#!/bin/bash
# ════════════════════════════════════════════════════════════════
# deploy_r115.sh — NEX R101–R115 Research Evolution Stack
# Usage:
#   mv ~/Downloads/nex_r115.py    ~/Desktop/nex/nex_upgrades/
#   mv ~/Downloads/deploy_r115.sh ~/Desktop/nex/
#   chmod +x ~/Desktop/nex/deploy_r115.sh
#   cd ~/Desktop/nex && source venv/bin/activate && ./deploy_r115.sh
# ════════════════════════════════════════════════════════════════
set -euo pipefail

NEX_DIR="$HOME/Desktop/nex"
RUN_PY="$NEX_DIR/run.py"
TG_CMD="$NEX_DIR/nex_telegram_commands.py"
TS=$(date +%s)

echo "══════════════════════════════════════"
echo " NEX R101–R115 — deployment starting"
echo "══════════════════════════════════════"

[[ -f "$RUN_PY" ]]                             || { echo "ERROR: run.py not found";        exit 1; }
[[ -f "$NEX_DIR/nex_upgrades/nex_r115.py" ]]  || { echo "ERROR: nex_r115.py not in nex_upgrades/"; exit 1; }

cp "$RUN_PY" "$RUN_PY.bak_r115_$TS"
echo "[✓] Backed up run.py → run.py.bak_r115_$TS"

# ── Patch run.py ─────────────────────────────────────────────
python3 - << 'PYEOF'
import re, ast
from pathlib import Path

RUN = Path.home() / "Desktop/nex/run.py"
src = RUN.read_text()

if "nex_r115" in src:
    print("[r115] run.py already patched — skipping")
    exit(0)

# ── Import: anchor priority chain ────────────────────────────
R115_IMPORT = (
    "\n# ── R101–R115 research evolution stack ─────────────────\n"
    "try:\n"
    "    from nex_upgrades.nex_r115 import get_r115 as _get_r115\n"
    "    _r115 = _get_r115()\n"
    "except Exception as _r115_ex:\n"
    "    print(f'[r115] Load failed: {_r115_ex}')\n"
    "    _r115 = None\n"
)

for anchor in ["    _u100 = None\n", "_u100 = None\n",
               "    _v80 = None\n",  "_v80 = None\n",
               "    _v72 = None\n",  "_v72 = None\n"]:
    idx = src.find(anchor)
    if idx != -1:
        src = src[:idx + len(anchor)] + R115_IMPORT + src[idx + len(anchor):]
        print(f"[r115] Import injected after: {anchor.strip()!r}")
        break
else:
    m = re.search(r'import signal\n', src)
    assert m, "No import anchor found"
    src = src[:m.end()] + R115_IMPORT + src[m.end():]
    print("[r115] Import injected after 'import signal'")

# ── Tick: after u100 err log line ────────────────────────────
lines     = src.splitlines(keepends=True)
insert_at = None
pad       = "                    "

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

if insert_at is None:
    for i, ln in enumerate(lines):
        if "nex_v72_err.txt" in ln:
            pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
            insert_at = i + 1
            break

assert insert_at is not None, "No tick anchor found"

TICK = [
    "\n",
    f"{pad}# ── R101–R115 tick ─────────────────────────────────\n",
    f"{pad}if _r115 is not None:\n",
    f"{pad}    try:\n",
    f"{pad}        _ar115 = _v2ac if '_v2ac' in dir() else 0.50\n",
    f"{pad}        _tr115 = float(getattr(_s7,'tension_score',0.0)) if '_s7' in dir() and _s7 else 0.0\n",
    f"{pad}        _gss_score = float(getattr(getattr(_v80,'gss',None),'score',0.50)) if '_v80' in dir() and _v80 else 0.50\n",
    f"{pad}        _ph_r = str(getattr(getattr(_v80,'gss',None),'phase',type('x',(),{{'value':'stable'}})()).value) if '_v80' in dir() and _v80 else 'stable'\n",
    f"{pad}        try:\n",
    f"{pad}            with __import__('sqlite3').connect(str(__import__('pathlib').Path.home()/'.config/nex/nex.db'),timeout=3) as _cR:\n",
    f"{pad}                _cR.row_factory = __import__('sqlite3').Row\n",
    f"{pad}                _bcR  = _cR.execute('SELECT COUNT(*) FROM beliefs').fetchone()[0]\n",
    f"{pad}                _ctR  = _cR.execute(\"SELECT COUNT(*) FROM beliefs WHERE topic LIKE '%contradiction%'\").fetchone()[0]\n",
    f"{pad}        except Exception: _bcR=1000; _ctR=0\n",
    f"{pad}        _r115.tick(avg_conf=_ar115, tension=_tr115, coherence=_gss_score,\n",
    f"{pad}                   belief_count=_bcR, contradiction_count=_ctR, phase=_ph_r)\n",
    f"{pad}    except Exception as _er115:\n",
    f"{pad}        open('/tmp/nex_r115_err.txt','a').write(str(_er115)+'\\n')\n",
]

for k, bl in enumerate(TICK):
    lines.insert(insert_at + k, bl)

src = "".join(lines)
ast.parse(src)
RUN.write_text(src)
print(f"[r115] run.py written — tick at line {insert_at}")
PYEOF

echo "[✓] run.py patched"

# ── Register /r115status Telegram command ────────────────────
python3 - << 'PYEOF'
from pathlib import Path

tc  = Path.home() / "Desktop/nex/nex_telegram_commands.py"
src = tc.read_text()

if "r115_status" in src:
    print("[r115] /r115status already registered — skipping")
    exit(0)

CMD = '''
async def r115_status_command(update, context):
    """NEX R101–R115 — research evolution stack status."""
    try:
        from nex_upgrades.nex_r115 import get_r115
        msg = get_r115().format_status()
    except Exception as e:
        msg = f"r115 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")

'''
HANDLER = '    application.add_handler(CommandHandler("r115status", r115_status_command))\n'

idx = src.find("def register_handlers")
if idx == -1:
    idx = src.rfind("application.add_handler(CommandHandler")
if idx == -1:
    src = src + "\n" + CMD
else:
    src = src[:idx] + CMD + src[idx:]

last = src.rfind("application.add_handler(CommandHandler")
if last != -1:
    eol = src.find("\n", last) + 1
    src = src[:eol] + HANDLER + src[eol:]

tc.write_text(src)
print("[r115] /r115status registered")
PYEOF

echo "[✓] /r115status registered"

# ── Syntax checks ─────────────────────────────────────────────
python3 -m py_compile "$NEX_DIR/nex_upgrades/nex_r115.py" && echo "[✓] nex_r115.py OK"
python3 -m py_compile "$RUN_PY"                            && echo "[✓] run.py OK"
python3 -m py_compile "$TG_CMD"                            && echo "[✓] telegram_commands OK"

# ── Init config files ─────────────────────────────────────────
python3 - << 'PYEOF'
import json
from pathlib import Path
cfg = Path.home() / ".config/nex"

# Strategies store
sf = cfg / "strategies.json"
if not sf.exists():
    sf.write_text("[]")
    print("[r115] strategies.json created")

# Policy file
pf = cfg / "policy.json"
if not pf.exists():
    pf.write_text(json.dumps({
        "prune_threshold": 0.25, "insight_threshold": 0.55,
        "merge_threshold": 0.65, "tension_threshold": 0.60,
        "debate_threshold": 0.45, "version": 1, "updates": 0
    }, indent=2))
    print("[r115] policy.json created")

# Quarantine table
import sqlite3
c = sqlite3.connect(str(cfg / "nex.db"))
c.execute("""
    CREATE TABLE IF NOT EXISTS belief_quarantine (
        belief_id     INTEGER PRIMARY KEY,
        reason        TEXT,
        quarantine_ts TEXT,
        release_ts    TEXT
    )
""")
c.commit(); c.close()
print("[r115] belief_quarantine table confirmed")
PYEOF

echo "[✓] Config files initialised"

# ── Git commit + push ─────────────────────────────────────────
cd "$NEX_DIR"
git add nex_upgrades/nex_r115.py run.py nex_telegram_commands.py
git commit -m "R101-R115: 15-module research evolution stack — ExperienceDistillation, CriticalActionTraining, MultiStageFeedback, ReflectionInLoop, StrategyLibrary, HierarchicalPlanning, ToolSpecialization, SelfHealing, MemoryValidation, GoalInference, DriveMotivation, ActionSimulation, FailurePriority, AgentCoordination, ContinuousPolicyEvolution | /r115status"
git push

echo ""
echo "══════════════════════════════════════"
echo " R101–R115 deployed. Restart:"
echo "   pkill -f run.py; sleep 2; nex"
echo " Verify:"
echo "   sleep 20 && tail -5 /tmp/nex_r115.log"
echo " Telegram: /r115status"
echo "══════════════════════════════════════"
