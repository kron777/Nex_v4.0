#!/bin/bash
# ════════════════════════════════════════════════════════════════
# deploy_x160.sh — NEX X141–X160 + C141–C143
# Expression & Learning Optimization Stack (23 modules)
# Usage:
#   mv ~/Downloads/nex_x160.py    ~/Desktop/nex/nex_upgrades/
#   mv ~/Downloads/deploy_x160.sh ~/Desktop/nex/
#   chmod +x ~/Desktop/nex/deploy_x160.sh
#   cd ~/Desktop/nex && source venv/bin/activate && ./deploy_x160.sh
# ════════════════════════════════════════════════════════════════
set -euo pipefail

NEX_DIR="$HOME/Desktop/nex"
RUN_PY="$NEX_DIR/run.py"
TG_CMD="$NEX_DIR/nex_telegram_commands.py"
TS=$(date +%s)

echo "══════════════════════════════════════"
echo " NEX X141–X160 + C141–C143"
echo " Expression & Learning Optimization"
echo "══════════════════════════════════════"

[[ -f "$RUN_PY" ]]                             || { echo "ERROR: run.py not found";        exit 1; }
[[ -f "$NEX_DIR/nex_upgrades/nex_x160.py" ]]  || { echo "ERROR: nex_x160.py not in nex_upgrades/"; exit 1; }

cp "$RUN_PY" "$RUN_PY.bak_x160_$TS"
echo "[✓] Backed up run.py"

# ── Patch run.py ─────────────────────────────────────────────
python3 - << 'PYEOF'
import re, ast
from pathlib import Path

RUN = Path.home() / "Desktop/nex/run.py"
src = RUN.read_text()

if "nex_x160" in src:
    print("[x160] run.py already patched — skipping")
    exit(0)

X160_IMPORT = (
    "\n# ── X141–X160 + C141–C143 expression stack ─────────────\n"
    "try:\n"
    "    from nex_upgrades.nex_x160 import get_x160 as _get_x160\n"
    "    _x160 = _get_x160()\n"
    "except Exception as _x160_ex:\n"
    "    print(f'[x160] Load failed: {_x160_ex}')\n"
    "    _x160 = None\n"
)

for anchor in ["    _e140 = None\n", "_e140 = None\n",
               "    _r115 = None\n", "_r115 = None\n",
               "    _u100 = None\n", "_u100 = None\n"]:
    idx = src.find(anchor)
    if idx != -1:
        src = src[:idx + len(anchor)] + X160_IMPORT + src[idx + len(anchor):]
        print(f"[x160] Import injected after: {anchor.strip()!r}")
        break
else:
    m = re.search(r'import signal\n', src)
    assert m, "No import anchor"
    src = src[:m.end()] + X160_IMPORT + src[m.end():]
    print("[x160] Import injected after 'import signal'")

lines     = src.splitlines(keepends=True)
insert_at = None
pad       = "                    "

for i, ln in enumerate(lines):
    if "nex_e140_err.txt" in ln:
        pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
        insert_at = i + 1
        break

if insert_at is None:
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

assert insert_at is not None, "No tick anchor found"

TICK = [
    "\n",
    f"{pad}# ── X141–X160 tick ─────────────────────────────────\n",
    f"{pad}if _x160 is not None:\n",
    f"{pad}    try:\n",
    f"{pad}        _ph_x = str(getattr(getattr(_v80,'gss',None),'phase',type('x',(),{{'value':'stable'}})()).value) if '_v80' in dir() and _v80 else 'stable'\n",
    f"{pad}        _wl_x = str(getattr(_v80,'will',type('w',(),{{'intent':'seek_truth'}})()).intent) if '_v80' in dir() and _v80 else 'seek_truth'\n",
    f"{pad}        _ax   = _v2ac if '_v2ac' in dir() else 0.50\n",
    f"{pad}        _x160.tick(phase=_ph_x, will=_wl_x, avg_conf=_ax)\n",
    f"{pad}    except Exception as _ex160:\n",
    f"{pad}        open('/tmp/nex_x160_err.txt','a').write(str(_ex160)+'\\n')\n",
]

for k, bl in enumerate(TICK):
    lines.insert(insert_at + k, bl)

src = "".join(lines)
ast.parse(src)
RUN.write_text(src)
print(f"[x160] run.py written — tick at line {insert_at}")
PYEOF

echo "[✓] run.py patched"

# ── Register /x160status ─────────────────────────────────────
python3 - << 'PYEOF'
from pathlib import Path
tc  = Path.home() / "Desktop/nex/nex_telegram_commands.py"
src = tc.read_text()
if "x160_status" in src:
    print("[x160] /x160status already registered"); exit(0)
CMD = '''
async def x160_status_command(update, context):
    """NEX X141–X160 — expression & learning optimization status."""
    try:
        from nex_upgrades.nex_x160 import get_x160
        msg = get_x160().format_status()
    except Exception as e:
        msg = f"x160 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")

'''
HANDLER = '    application.add_handler(CommandHandler("x160status", x160_status_command))\n'
idx = src.find("def register_handlers")
if idx == -1: idx = src.rfind("application.add_handler(CommandHandler")
if idx == -1: src = src + "\n" + CMD
else: src = src[:idx] + CMD + src[idx:]
last = src.rfind("application.add_handler(CommandHandler")
if last != -1:
    eol = src.find("\n", last) + 1
    src = src[:eol] + HANDLER + src[eol:]
tc.write_text(src)
print("[x160] /x160status registered")
PYEOF

echo "[✓] /x160status registered"

# ── Syntax checks ─────────────────────────────────────────────
python3 -m py_compile "$NEX_DIR/nex_upgrades/nex_x160.py" && echo "[✓] nex_x160.py OK"
python3 -m py_compile "$RUN_PY"                            && echo "[✓] run.py OK"
python3 -m py_compile "$TG_CMD"                            && echo "[✓] telegram_commands OK"

# ── Git commit + push ─────────────────────────────────────────
cd "$NEX_DIR"
git add nex_upgrades/nex_x160.py run.py nex_telegram_commands.py
git commit -m "X141-X160+C141-C143: 23-module expression & learning stack — ResponseStyleDiversifier, IdentityVoiceMapping, OutputCompressionHard, PhraseRepetitionPenalty, ExplorationBypassWindow, ReasoningStyleRotation, DynamicTemperatureControl, OutputRhythmVariation, MultiPerspectiveSynthesis, ResponseIntentAlignment, AssertivenessScaler, MicroInsightInjection, ContextualStyleAdaptation, LengthAutoOptimizer, ExpressiveMemoryLinking, IdentityConsistencyGuard, ControlledCreativeRisk, OutputQualityScoring, IdeaCompressionEngine, EndingVariationEngine, SuppressionRebalance, ExplorationProtection, CreativityFloor | /x160status"
git push

echo ""
echo "══════════════════════════════════════"
echo " X141–X160 deployed. Restart:"
echo "   pkill -f run.py; sleep 2; nex"
echo " Verify:"
echo "   sleep 20 && tail -5 /tmp/nex_x160.log"
echo " Telegram: /x160status"
echo "══════════════════════════════════════"
