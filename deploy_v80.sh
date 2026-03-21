#!/bin/bash
# ════════════════════════════════════════════════════════════════
# deploy_v80.sh — NEX v8.0 Unification Layer
# Files needed in ~/Downloads before running:
#   nex_v80.py
#
# Usage:
#   mv ~/Downloads/nex_v80.py    ~/Desktop/nex/nex_upgrades/
#   mv ~/Downloads/deploy_v80.sh ~/Desktop/nex/
#   chmod +x ~/Desktop/nex/deploy_v80.sh
#   cd ~/Desktop/nex && source venv/bin/activate && ./deploy_v80.sh
# ════════════════════════════════════════════════════════════════
set -euo pipefail

NEX_DIR="$HOME/Desktop/nex"
RUN_PY="$NEX_DIR/run.py"
TG_CMD="$NEX_DIR/nex_telegram_commands.py"
TS=$(date +%s)

echo "══════════════════════════════════════"
echo " NEX v8.0 — Unification Layer"
echo "══════════════════════════════════════"

[[ -f "$RUN_PY" ]]                           || { echo "ERROR: run.py not found";       exit 1; }
[[ -f "$NEX_DIR/nex_upgrades/nex_v80.py" ]] || { echo "ERROR: nex_v80.py not in nex_upgrades/"; exit 1; }

cp "$RUN_PY" "$RUN_PY.bak_v80_$TS"
echo "[✓] Backed up run.py"

# ── Patch run.py: import + tick ──────────────────────────────
python3 - << 'PYEOF'
import re, ast
from pathlib import Path

RUN = Path.home() / "Desktop/nex/run.py"
src = RUN.read_text()

if "nex_v80" in src:
    print("[v8.0] run.py already patched — skipping")
    exit(0)

# ── Import: after _v72=None line ─────────────────────────────
V80_IMPORT = (
    "\n# ── V8.0 unification layer ─────────────────────────────\n"
    "try:\n"
    "    from nex_upgrades.nex_v80 import get_v80 as _get_v80\n"
    "    _v80 = _get_v80()\n"
    "except Exception as _v80_ex:\n"
    "    print(f'[v8.0] Load failed: {_v80_ex}')\n"
    "    _v80 = None\n"
)

# Anchor priority: _v72=None → _v65=None → import signal
for anchor in ["    _v72 = None\n", "_v72 = None\n",
               "    _v65 = None\n", "_v65 = None\n"]:
    idx = src.find(anchor)
    if idx != -1:
        src = src[:idx + len(anchor)] + V80_IMPORT + src[idx + len(anchor):]
        print(f"[v8.0] Import injected after: {anchor.strip()!r}")
        break
else:
    m = re.search(r'import signal\n', src)
    assert m, "No import anchor found"
    src = src[:m.end()] + V80_IMPORT + src[m.end():]
    print("[v8.0] Import injected after 'import signal'")

# ── Tick: after v72 err log line ─────────────────────────────
lines = src.splitlines(keepends=True)
insert_at = None
pad = "                    "

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

# fallback: after last except _e7
if insert_at is None:
    for i in range(len(lines)-1, -1, -1):
        if re.search(r'except Exception as _e7', lines[i]):
            pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
            insert_at = i + 2
            break

assert insert_at is not None, "No tick anchor found"

# Pull tension from s7 or v72 if available
TICK = [
    "\n",
    f"{pad}# ── V8.0 tick ─────────────────────────────────────\n",
    f"{pad}if _v80 is not None:\n",
    f"{pad}    try:\n",
    f"{pad}        _a80 = _v2ac if '_v2ac' in dir() else 0.50\n",
    f"{pad}        _t80 = float(getattr(_s7,'tension_score',0.0)) if '_s7' in dir() and _s7 else 0.0\n",
    f"{pad}        _d80 = float(getattr(_s7,'drift_score',  0.0)) if '_s7' in dir() and _s7 else 0.0\n",
    f"{pad}        _v80.tick(avg_conf=_a80, tension=_t80, drift=_d80)\n",
    f"{pad}    except Exception as _e80:\n",
    f"{pad}        open('/tmp/nex_v80_err.txt','a').write(str(_e80)+'\\n')\n",
]

for k, bl in enumerate(TICK):
    lines.insert(insert_at + k, bl)

src = "".join(lines)
ast.parse(src)
RUN.write_text(src)
print(f"[v8.0] run.py written — tick at line {insert_at}")
PYEOF

echo "[✓] run.py patched"

# ── Register /v80status Telegram command ─────────────────────
python3 - << 'PYEOF'
from pathlib import Path

tc  = Path.home() / "Desktop/nex/nex_telegram_commands.py"
src = tc.read_text()

if "v80_status" in src:
    print("[v8.0] /v80status already registered — skipping")
    exit(0)

CMD = '''
async def v80_status_command(update, context):
    """NEX v8.0 — Unification layer status."""
    try:
        from nex_upgrades.nex_v80 import get_v80
        msg = get_v80().format_status()
    except Exception as e:
        msg = f"v8.0 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")

'''
HANDLER = '    application.add_handler(CommandHandler("v80status", v80_status_command))\n'

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
print("[v8.0] /v80status registered")
PYEOF

echo "[✓] /v80status registered"

# ── Syntax checks ─────────────────────────────────────────────
python3 -m py_compile "$NEX_DIR/nex_upgrades/nex_v80.py" && echo "[✓] nex_v80.py OK"
python3 -m py_compile "$RUN_PY"                           && echo "[✓] run.py OK"
python3 -m py_compile "$TG_CMD"                           && echo "[✓] telegram_commands OK"

# ── DB: ensure decision_quality table exists (v7.2 dependency) ─
python3 - << 'PYEOF'
import sqlite3
from pathlib import Path
db = Path.home() / ".config/nex/nex.db"
c  = sqlite3.connect(str(db))
c.execute("""
    CREATE TABLE IF NOT EXISTS decision_quality (
        cluster      TEXT PRIMARY KEY,
        success_rate REAL DEFAULT 0.5,
        total        INTEGER DEFAULT 0,
        last_updated TEXT
    )
""")
c.commit()
c.close()
print("[v8.0] decision_quality table confirmed")
PYEOF

# ── Git commit + push ─────────────────────────────────────────
cd "$NEX_DIR"
git add nex_upgrades/nex_v80.py run.py nex_telegram_commands.py
git commit -m "v8.0: 14-module unification layer — SystemWill, GlobalSystemState, AuthorityMap, CausalTraceLog, ReflectionQualityFilter, SignalNormalizer, DoNothingGate, PlatformContextLayer, IndecisionPenalty, DebateCostGate, AggressiveCompression, PhaseDeduplicator, NetworkResilience, NexRuntime orchestrator | /v80status"
git push

echo ""
echo "══════════════════════════════════════"
echo " v8.0 deployed. Restart:"
echo "   pkill -f run.py; sleep 2; nex"
echo " Then verify:"
echo "   sleep 20 && tail -5 /tmp/nex_v80.log"
echo " Telegram: /v80status"
echo "══════════════════════════════════════"
