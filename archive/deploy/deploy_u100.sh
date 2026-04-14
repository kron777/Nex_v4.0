#!/bin/bash
# ════════════════════════════════════════════════════════════════
# deploy_u100.sh — NEX U81–U100 Directives Execution Stack
# Usage:
#   mv ~/Downloads/nex_u100.py   ~/Desktop/nex/nex_upgrades/
#   mv ~/Downloads/deploy_u100.sh ~/Desktop/nex/
#   chmod +x ~/Desktop/nex/deploy_u100.sh
#   cd ~/Desktop/nex && source venv/bin/activate && ./deploy_u100.sh
# ════════════════════════════════════════════════════════════════
set -euo pipefail

NEX_DIR="$HOME/Desktop/nex"
RUN_PY="$NEX_DIR/run.py"
TG_CMD="$NEX_DIR/nex_telegram_commands.py"
TS=$(date +%s)

echo "══════════════════════════════════════"
echo " NEX U81–U100 — deployment starting"
echo "══════════════════════════════════════"

[[ -f "$RUN_PY" ]]                            || { echo "ERROR: run.py not found";        exit 1; }
[[ -f "$NEX_DIR/nex_upgrades/nex_u100.py" ]] || { echo "ERROR: nex_u100.py not in nex_upgrades/"; exit 1; }

cp "$RUN_PY" "$RUN_PY.bak_u100_$TS"
echo "[✓] Backed up run.py → run.py.bak_u100_$TS"

# ── Patch run.py ─────────────────────────────────────────────
python3 - << 'PYEOF'
import re, ast
from pathlib import Path

RUN = Path.home() / "Desktop/nex/run.py"
src = RUN.read_text()

if "nex_u100" in src:
    print("[u100] run.py already patched — skipping")
    exit(0)

# ── Import block ──────────────────────────────────────────────
U100_IMPORT = (
    "\n# ── U81–U100 directives stack ──────────────────────────\n"
    "try:\n"
    "    from nex_upgrades.nex_u100 import get_u100 as _get_u100\n"
    "    _u100 = _get_u100()\n"
    "except Exception as _u100_ex:\n"
    "    print(f'[u100] Load failed: {_u100_ex}')\n"
    "    _u100 = None\n"
)

# Anchor priority: _v80=None → _v72=None → _v65=None → signal
for anchor in ["    _v80 = None\n", "_v80 = None\n",
               "    _v72 = None\n", "_v72 = None\n",
               "    _v65 = None\n", "_v65 = None\n"]:
    idx = src.find(anchor)
    if idx != -1:
        src = src[:idx + len(anchor)] + U100_IMPORT + src[idx + len(anchor):]
        print(f"[u100] Import injected after: {anchor.strip()!r}")
        break
else:
    m = re.search(r'import signal\n', src)
    assert m, "No import anchor found"
    src = src[:m.end()] + U100_IMPORT + src[m.end():]
    print("[u100] Import injected after 'import signal'")

# ── Tick block ────────────────────────────────────────────────
lines = src.splitlines(keepends=True)
insert_at = None
pad = "                    "

# Anchor: after v80 err log line
for i, ln in enumerate(lines):
    if "nex_v80_err.txt" in ln:
        pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
        insert_at = i + 1
        break

# fallback: after v72 err log
if insert_at is None:
    for i, ln in enumerate(lines):
        if "nex_v72_err.txt" in ln:
            pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
            insert_at = i + 1
            break

# fallback: after v65 err log
if insert_at is None:
    for i, ln in enumerate(lines):
        if "nex_v65_err.txt" in ln:
            pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
            insert_at = i + 1
            break

assert insert_at is not None, "No tick anchor found"

TICK = [
    "\n",
    f"{pad}# ── U81–U100 tick ─────────────────────────────────\n",
    f"{pad}if _u100 is not None:\n",
    f"{pad}    try:\n",
    f"{pad}        _a100  = _v2ac if '_v2ac' in dir() else 0.50\n",
    f"{pad}        _t100  = float(getattr(_s7,'tension_score',0.0)) if '_s7' in dir() and _s7 else 0.0\n",
    f"{pad}        _ph100 = str(getattr(getattr(_v80,'gss',None),'phase',type('x',(),{{'value':'stable'}})()).value) if '_v80' in dir() and _v80 else 'stable'\n",
    f"{pad}        _ct100 = 0\n",
    f"{pad}        _u100.tick(avg_conf=_a100, tension=_t100,\n",
    f"{pad}                   phase=_ph100, contradiction_count=_ct100)\n",
    f"{pad}    except Exception as _eu100:\n",
    f"{pad}        open('/tmp/nex_u100_err.txt','a').write(str(_eu100)+'\\n')\n",
]

for k, bl in enumerate(TICK):
    lines.insert(insert_at + k, bl)

src = "".join(lines)
ast.parse(src)
RUN.write_text(src)
print(f"[u100] run.py written — tick at line {insert_at}")
PYEOF

echo "[✓] run.py patched"

# ── Register /u100status Telegram command ────────────────────
python3 - << 'PYEOF'
from pathlib import Path

tc  = Path.home() / "Desktop/nex/nex_telegram_commands.py"
src = tc.read_text()

if "u100_status" in src:
    print("[u100] /u100status already registered — skipping")
    exit(0)

CMD = '''
async def u100_status_command(update, context):
    """NEX U81–U100 — directives stack status."""
    try:
        from nex_upgrades.nex_u100 import get_u100
        msg = get_u100().format_status()
    except Exception as e:
        msg = f"u100 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")

'''
HANDLER = '    application.add_handler(CommandHandler("u100status", u100_status_command))\n'

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
print("[u100] /u100status registered")
PYEOF

echo "[✓] /u100status registered"

# ── Syntax checks ─────────────────────────────────────────────
python3 -m py_compile "$NEX_DIR/nex_upgrades/nex_u100.py" && echo "[✓] nex_u100.py OK"
python3 -m py_compile "$RUN_PY"                            && echo "[✓] run.py OK"
python3 -m py_compile "$TG_CMD"                            && echo "[✓] telegram_commands OK"

# ── Git commit + push ─────────────────────────────────────────
cd "$NEX_DIR"
git add nex_upgrades/nex_u100.py run.py nex_telegram_commands.py
git commit -m "U81-U100: 20-module directives stack — OutputCompression, DecisiveBeliefUpdate, HardDoNothingGate, PhaseDrivenBehavior, SystemWillDynamics, ReflectionKillSwitch, SignalDeduplication, AggressiveBeliefMergeV2, OutputStyleBreaker, AuthorityEnforcementActive, CausalTraceUtilization, DebateCostHardLimit, TensionActionBinding, PlatformAdaptation, IndecisionPunishmentV2, GlobalStateScore, ActionValueFilter, MemoryPressureFeedback, IdentityDominanceEnforcer, RunPyFreezeMigration | /u100status"
git push

echo ""
echo "══════════════════════════════════════"
echo " U81–U100 deployed. Restart:"
echo "   pkill -f run.py; sleep 2; nex"
echo " Verify:"
echo "   sleep 20 && tail -5 /tmp/nex_u100.log"
echo " Telegram: /u100status"
echo "══════════════════════════════════════"
