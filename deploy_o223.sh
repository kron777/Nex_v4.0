#!/bin/bash
# ════════════════════════════════════════════════════════════════
# deploy_o223.sh — NEX O201–O223 Guided Evolution Stack
# IMPORTANT: Injects tick at cycle += 1 level (shallow), NOT inside
# any try/except block. Fixes the nesting issue permanently.
# Usage:
#   mv ~/Downloads/nex_o223.py    ~/Desktop/nex/nex_upgrades/
#   mv ~/Downloads/deploy_o223.sh ~/Desktop/nex/
#   chmod +x ~/Desktop/nex/deploy_o223.sh
#   cd ~/Desktop/nex && source venv/bin/activate && ./deploy_o223.sh
# ════════════════════════════════════════════════════════════════
set -euo pipefail

NEX_DIR="$HOME/Desktop/nex"
RUN_PY="$NEX_DIR/run.py"
TG_CMD="$NEX_DIR/nex_telegram_commands.py"
TS=$(date +%s)

echo "══════════════════════════════════════"
echo " NEX O201–O223 Guided Evolution"
echo "══════════════════════════════════════"

[[ -f "$RUN_PY" ]]                             || { echo "ERROR: run.py missing"; exit 1; }
[[ -f "$NEX_DIR/nex_upgrades/nex_o223.py" ]]  || { echo "ERROR: nex_o223.py missing"; exit 1; }

# ── First: verify run.py is currently valid ───────────────────
if ! python3 -m py_compile "$RUN_PY" 2>/dev/null; then
    echo "run.py has syntax errors — running fix_nesting first..."
    if [ -f "$NEX_DIR/fix_nesting.py" ]; then
        python3 "$NEX_DIR/fix_nesting.py"
        python3 -m py_compile "$RUN_PY" || { echo "FATAL: still broken after fix"; exit 1; }
    else
        echo "ERROR: fix_nesting.py not found and run.py is broken"
        exit 1
    fi
fi

cp "$RUN_PY" "$RUN_PY.bak_o223_$TS"
echo "[✓] Backed up run.py"

# ── Patch run.py ─────────────────────────────────────────────
python3 - << 'PYEOF'
import re, ast
from pathlib import Path

RUN = Path.home() / "Desktop/nex/run.py"
src = RUN.read_text()

if "nex_o223" in src:
    print("[o223] Already patched — skipping"); exit(0)

O223_IMPORT = (
    "\n# ── O201–O223 guided evolution stack ───────────────────\n"
    "try:\n"
    "    from nex_upgrades.nex_o223 import get_o223 as _get_o223\n"
    "    _o223 = _get_o223()\n"
    "except Exception as _o223_ex:\n"
    "    print(f'[o223] Load failed: {_o223_ex}')\n"
    "    _o223 = None\n"
)

# Import anchor: after last _rXXX/_eXXX/_xXXX = None
for anchor in ["    _r181 = None\n", "_r181 = None\n",
               "    _x160 = None\n", "_x160 = None\n",
               "    _e140 = None\n", "_e140 = None\n",
               "    _trainer = None\n", "_trainer = None\n"]:
    idx = src.find(anchor)
    if idx != -1:
        src = src[:idx + len(anchor)] + O223_IMPORT + src[idx + len(anchor):]
        print(f"[o223] Import after: {anchor.strip()!r}")
        break
else:
    m = re.search(r'import signal\n', src)
    assert m
    src = src[:m.end()] + O223_IMPORT + src[m.end():]
    print("[o223] Import after 'import signal'")

# ── Tick: inject at cycle += 1 level (SHALLOW — not inside try/except) ──
lines = src.splitlines(keepends=True)

# Find cycle += 1 — get its indent level
cycle_line = None
cycle_indent = 20
for i, ln in enumerate(lines):
    if re.match(r'\s*cycle\s*\+=\s*1\s*$', ln):
        cycle_indent = len(ln) - len(ln.lstrip())
        cycle_line   = i

assert cycle_line is not None, "cycle += 1 not found"
pad = " " * cycle_indent

# Insert right after cycle += 1 (simple, shallow)
TICK = [
    f"\n",
    f"{pad}# ── O201–O223 observation tick ──────────────────────\n",
    f"{pad}if '_o223' in dir() and _o223 is not None:\n",
    f"{pad}    _o223.tick(avg_conf=_v2ac if '_v2ac' in dir() else 0.50)\n",
]

insert_at = cycle_line + 1
for k, bl in enumerate(TICK):
    lines.insert(insert_at + k, bl)

src = "".join(lines)
ast.parse(src)
RUN.write_text(src)
print(f"[o223] Tick at line {insert_at} indent={cycle_indent} — AST OK")
PYEOF

echo "[✓] run.py patched"

# ── Register /o223status ─────────────────────────────────────
python3 - << 'PYEOF'
from pathlib import Path
tc  = Path.home() / "Desktop/nex/nex_telegram_commands.py"
src = tc.read_text()
if "o223_status" in src:
    print("[o223] Already registered"); exit(0)
CMD = '''
async def o223_status_command(update, context):
    """NEX O201–O223 — guided evolution + observation status."""
    try:
        from nex_upgrades.nex_o223 import get_o223
        msg = get_o223().format_status()
    except Exception as e:
        msg = f"o223 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")

'''
HANDLER = '    application.add_handler(CommandHandler("o223status", o223_status_command))\n'
idx = src.find("def register_handlers")
if idx == -1: idx = src.rfind("application.add_handler(CommandHandler")
if idx == -1: src = src + "\n" + CMD
else: src = src[:idx] + CMD + src[idx:]
last = src.rfind("application.add_handler(CommandHandler")
if last != -1:
    eol = src.find("\n", last) + 1
    src = src[:eol] + HANDLER + src[eol:]
tc.write_text(src)
print("[o223] /o223status registered")
PYEOF

echo "[✓] /o223status registered"

python3 -m py_compile "$NEX_DIR/nex_upgrades/nex_o223.py" && echo "[✓] nex_o223.py OK"
python3 -m py_compile "$RUN_PY"                            && echo "[✓] run.py OK"
python3 -m py_compile "$TG_CMD"                            && echo "[✓] telegram_commands OK"

cd "$NEX_DIR"
git add nex_upgrades/nex_o223.py run.py nex_telegram_commands.py
git commit -m "O201-O223: 23-module guided evolution stack — PassiveObservation, BehaviorMetrics, StyleDiversity, AssertivenessScore, RepetitionV2, MicroPrompt, SoftCorrection, DelayedReinforcement, SuppressionBalancer, CreativityBand, OutputRate, StrategyFormation, StrategyUsage, ExperienceCheck, PolicyDrift, IdentitySignature, VoiceConsistency, ExpressionVariance, MinimalIntervention, SingleVariable, Cooldown, TrainingHold, TrainingTrigger | /o223status"
git push

echo ""
echo "══════════════════════════════════════"
echo " O201–O223 deployed."
echo "   pkill -f run.py; sleep 2; nex"
echo "   sleep 20 && tail -5 /tmp/nex_o223.log"
echo "   /o223status in Telegram"
echo "══════════════════════════════════════"
