#!/bin/bash
# ════════════════════════════════════════════════════════════════
# deploy_v72.sh — NEX v7.2 — 20-module evolution stack
# Usage:
#   mv ~/Downloads/nex_v72.py   ~/Desktop/nex/nex_upgrades/
#   mv ~/Downloads/deploy_v72.sh ~/Desktop/nex/
#   chmod +x ~/Desktop/nex/deploy_v72.sh
#   cd ~/Desktop/nex && source venv/bin/activate && ./deploy_v72.sh
# ════════════════════════════════════════════════════════════════
set -euo pipefail

NEX_DIR="$HOME/Desktop/nex"
RUN_PY="$NEX_DIR/run.py"
TG_CMD="$NEX_DIR/nex_telegram_commands.py"
TS=$(date +%s)

echo "══════════════════════════════════════"
echo " NEX v7.2 — deployment starting"
echo "══════════════════════════════════════"

[[ -f "$RUN_PY" ]]                           || { echo "ERROR: run.py not found";       exit 1; }
[[ -f "$NEX_DIR/nex_upgrades/nex_v72.py" ]] || { echo "ERROR: nex_v72.py not in nex_upgrades/"; exit 1; }

cp "$RUN_PY" "$RUN_PY.bak_v72_$TS"
echo "[✓] Backed up run.py → run.py.bak_v72_$TS"

# ── Patch run.py ─────────────────────────────────────────────
python3 - << 'PYEOF'
import re, ast
from pathlib import Path

RUN = Path.home() / "Desktop/nex/run.py"
src = RUN.read_text()

if "nex_v72" in src:
    print("[v7.2] run.py already patched — skipping")
    exit(0)

# ── Import block ──────────────────────────────────────────────
V72_IMPORT = (
    "\n# ── V7.2 upgrade layer ─────────────────────────────────\n"
    "try:\n"
    "    from nex_upgrades.nex_v72 import get_v72 as _get_v72\n"
    "    _v72 = _get_v72()\n"
    "except Exception as _v72_ex:\n"
    "    print(f'[v7.2] Load failed: {_v72_ex}')\n"
    "    _v72 = None\n"
)

# Inject after v6.5 import block if present, else after 'import signal'
if "nex_v65" in src:
    anchor = "_v65 = None\n"
    idx = src.find(anchor)
    if idx != -1:
        src = src[:idx + len(anchor)] + V72_IMPORT + src[idx + len(anchor):]
        print("[v7.2] Import injected after v6.5 block")
    else:
        m = re.search(r'import signal\n', src)
        src = src[:m.end()] + V72_IMPORT + src[m.end():]
        print("[v7.2] Import injected after 'import signal'")
else:
    m = re.search(r'import signal\n', src)
    src = src[:m.end()] + V72_IMPORT + src[m.end():]
    print("[v7.2] Import injected after 'import signal'")

# ── Tick block ────────────────────────────────────────────────
lines = src.splitlines(keepends=True)
insert_at = None
pad = "                    "

# Find v6.5 tick except/pass — insert after it
for i, ln in enumerate(lines):
    if "_e65" in ln and "pass" in ln.lstrip():
        pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
        insert_at = i + 1
        break

# Fallback: after _s7 except/pass
if insert_at is None:
    for i, ln in enumerate(lines):
        if "_s7te" in ln or ("_s7" in ln and "pass" in ln.lstrip()):
            pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
            insert_at = i + 1
            break

# Fallback: after cycle += 1
if insert_at is None:
    for i, ln in enumerate(reversed(lines)):
        if re.match(r'\s*cycle\s*\+=\s*1', ln):
            insert_at = len(lines) - i
            break

assert insert_at is not None, "No tick anchor found"

TICK = [
    "\n",
    f"{pad}# ── V7.2 tick ─────────────────────────────────────\n",
    f"{pad}if _v72 is not None:\n",
    f"{pad}    try:\n",
    f"{pad}        _a72 = _v2ac if '_v2ac' in dir() else 0.50\n",
    f"{pad}        _q72 = len(getattr(getattr(_v72,'qhl',None),'_q',[])) / 150\n",
    f"{pad}        _v72.tick(avg_conf=_a72, queue_pressure=_q72)\n",
    f"{pad}    except Exception as _e72:\n",
    f"{pad}        open('/tmp/nex_v72_err.txt','a').write(str(_e72)+'\\n')\n",
]

for k, bl in enumerate(TICK):
    lines.insert(insert_at + k, bl)

src = "".join(lines)
ast.parse(src)
RUN.write_text(src)
print(f"[v7.2] run.py patched — tick at line {insert_at}")
PYEOF

echo "[✓] run.py patched"

# ── Register /v72status Telegram command ─────────────────────
python3 - << 'PYEOF'
from pathlib import Path

tc  = Path.home() / "Desktop/nex/nex_telegram_commands.py"
src = tc.read_text()

if "v72_status" in src:
    print("[v7.2] /v72status already registered")
    exit(0)

CMD = '''
async def v72_status_command(update, context):
    """NEX v7.2 — 20-module evolution stack status."""
    try:
        from nex_upgrades.nex_v72 import get_v72
        msg = get_v72().format_status()
    except Exception as e:
        msg = f"v7.2 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")

'''
HANDLER = '    application.add_handler(CommandHandler("v72status", v72_status_command))\n'

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
print("[v7.2] /v72status registered")
PYEOF

echo "[✓] /v72status command registered"

# ── Syntax checks ─────────────────────────────────────────────
python3 -m py_compile "$NEX_DIR/nex_upgrades/nex_v72.py" && echo "[✓] nex_v72.py syntax OK"
python3 -m py_compile "$RUN_PY"                           && echo "[✓] run.py syntax OK"
python3 -m py_compile "$TG_CMD"                           && echo "[✓] nex_telegram_commands.py syntax OK"

# ── Git commit ────────────────────────────────────────────────
cd "$NEX_DIR"
git add nex_upgrades/nex_v72.py run.py nex_telegram_commands.py
git commit -m "v7.2: 20-module evolution stack — decision quality scoring, forced tension resolution, dynamic belief cap, cluster pruning, multi-pass validation, belief entropy reduction, belief market feedback, reflection-action binding, temporal intelligence v2, identity gravity, hierarchical belief graph, cross-cluster contradiction detection, memory compression v2, context resolution engine, queue hard limit, load-sensitive decision depth, failure memory penalty, prediction confidence calibration, simulation validation loop, adaptive insight generation | /v72status"

git push

echo ""
echo "══════════════════════════════════════"
echo " v7.2 deployed. Restart NEX:"
echo "   pkill -f run.py; sleep 2; nex"
echo " Then: /v72status in Telegram"
echo "══════════════════════════════════════"
