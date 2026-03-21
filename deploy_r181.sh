#!/bin/bash
# ════════════════════════════════════════════════════════════════
# deploy_r181.sh — NEX R161–R181 Expression Hardening
# Usage:
#   mv ~/Downloads/nex_r181.py    ~/Desktop/nex/nex_upgrades/
#   mv ~/Downloads/deploy_r181.sh ~/Desktop/nex/
#   chmod +x ~/Desktop/nex/deploy_r181.sh
#   cd ~/Desktop/nex && source venv/bin/activate && ./deploy_r181.sh
# ════════════════════════════════════════════════════════════════
set -euo pipefail

NEX_DIR="$HOME/Desktop/nex"
RUN_PY="$NEX_DIR/run.py"
TG_CMD="$NEX_DIR/nex_telegram_commands.py"
TS=$(date +%s)

echo "══════════════════════════════════════"
echo " NEX R161–R181 — Expression Hardening"
echo "══════════════════════════════════════"

[[ -f "$RUN_PY" ]]                             || { echo "ERROR: run.py not found";  exit 1; }
[[ -f "$NEX_DIR/nex_upgrades/nex_r181.py" ]]  || { echo "ERROR: nex_r181.py missing"; exit 1; }

cp "$RUN_PY" "$RUN_PY.bak_r181_$TS"
echo "[✓] Backed up run.py"

# ── Patch run.py ─────────────────────────────────────────────
python3 - << 'PYEOF'
import re, ast
from pathlib import Path

RUN = Path.home() / "Desktop/nex/run.py"
src = RUN.read_text()

if "nex_r181" in src:
    print("[r181] Already patched — skipping"); exit(0)

R181_IMPORT = (
    "\n# ── R161–R181 expression hardening stack ───────────────\n"
    "try:\n"
    "    from nex_upgrades.nex_r181 import get_r181 as _get_r181\n"
    "    _r181 = _get_r181()\n"
    "except Exception as _r181_ex:\n"
    "    print(f'[r181] Load failed: {_r181_ex}')\n"
    "    _r181 = None\n"
)

for anchor in ["    _x160 = None\n", "_x160 = None\n",
               "    _e140 = None\n", "_e140 = None\n",
               "    _r115 = None\n", "_r115 = None\n"]:
    idx = src.find(anchor)
    if idx != -1:
        src = src[:idx + len(anchor)] + R181_IMPORT + src[idx + len(anchor):]
        print(f"[r181] Import injected after: {anchor.strip()!r}")
        break
else:
    m = re.search(r'import signal\n', src)
    assert m, "No import anchor"
    src = src[:m.end()] + R181_IMPORT + src[m.end():]
    print("[r181] Import injected after 'import signal'")

lines     = src.splitlines(keepends=True)
insert_at = None
pad       = "                    "

for i, ln in enumerate(lines):
    if "nex_x160_err.txt" in ln:
        pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
        insert_at = i + 1
        break

if insert_at is None:
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

assert insert_at is not None, "No tick anchor found"

TICK = [
    "\n",
    f"{pad}# ── R161–R181 tick ─────────────────────────────────\n",
    f"{pad}if _r181 is not None:\n",
    f"{pad}    try:\n",
    f"{pad}        _ph_r181 = str(getattr(getattr(_v80,'gss',None),'phase',type('x',(),{{'value':'stable'}})()).value) if '_v80' in dir() and _v80 else 'stable'\n",
    f"{pad}        _ar181   = _v2ac if '_v2ac' in dir() else 0.50\n",
    f"{pad}        _tr181   = float(getattr(_s7,'tension_score',0.0)) if '_s7' in dir() and _s7 else 0.0\n",
    f"{pad}        _r181.tick(phase=_ph_r181, avg_conf=_ar181, tension=_tr181)\n",
    f"{pad}    except Exception as _er181:\n",
    f"{pad}        open('/tmp/nex_r181_err.txt','a').write(str(_er181)+'\\n')\n",
]

for k, bl in enumerate(TICK):
    lines.insert(insert_at + k, bl)

src = "".join(lines)
ast.parse(src)
RUN.write_text(src)
print(f"[r181] run.py written — tick at line {insert_at}")
PYEOF

echo "[✓] run.py patched"

# ── Register /r181status ─────────────────────────────────────
python3 - << 'PYEOF'
from pathlib import Path
tc  = Path.home() / "Desktop/nex/nex_telegram_commands.py"
src = tc.read_text()
if "r181_status" in src:
    print("[r181] Already registered"); exit(0)
CMD = '''
async def r181_status_command(update, context):
    """NEX R161–R181 — expression hardening status."""
    try:
        from nex_upgrades.nex_r181 import get_r181
        msg = get_r181().format_status()
    except Exception as e:
        msg = f"r181 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")

'''
HANDLER = '    application.add_handler(CommandHandler("r181status", r181_status_command))\n'
idx = src.find("def register_handlers")
if idx == -1: idx = src.rfind("application.add_handler(CommandHandler")
if idx == -1: src = src + "\n" + CMD
else: src = src[:idx] + CMD + src[idx:]
last = src.rfind("application.add_handler(CommandHandler")
if last != -1:
    eol = src.find("\n", last) + 1
    src = src[:eol] + HANDLER + src[eol:]
tc.write_text(src)
print("[r181] /r181status registered")
PYEOF

echo "[✓] /r181status registered"

python3 -m py_compile "$NEX_DIR/nex_upgrades/nex_r181.py" && echo "[✓] nex_r181.py OK"
python3 -m py_compile "$RUN_PY"                            && echo "[✓] run.py OK"
python3 -m py_compile "$TG_CMD"                            && echo "[✓] telegram_commands OK"

cd "$NEX_DIR"
git add nex_upgrades/nex_r181.py run.py nex_telegram_commands.py
git commit -m "R161-R181: 21-module expression hardening — BasePromptOverride (CRITICAL), AssertivenessHard, StyleDominanceRebalance, ResponseStartRandomizerV2, PhraseBlacklist, ClaimFirstEnforcer, MaxWordPressure, PunchlineCompressor, DensityScoring, HedgingEliminationV2, StrategyUsageEnforcer, StrategyVisibility, ExperienceTriggerLowering, FailureSurfaceOutput, PolicyDriftMonitor, VoiceConsistencyLock, StyleSwitchSmoothing, SignaturePattern, ExplorationFloorLock, SuppressionBackpressure, NoiseVsNoveltySeparator | /r181status"
git push

echo ""
echo "══════════════════════════════════════"
echo " R161–R181 deployed. Restart:"
echo "   pkill -f run.py; sleep 2; nex"
echo " Verify:"
echo "   sleep 20 && tail -5 /tmp/nex_r181.log"
echo " Telegram: /r181status"
echo "══════════════════════════════════════"
