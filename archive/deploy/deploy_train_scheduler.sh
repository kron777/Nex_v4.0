#!/bin/bash
# ════════════════════════════════════════════════════════════════
# deploy_train_scheduler.sh — NEX Autonomous Training Scheduler
# Usage:
#   mv ~/Downloads/nex_train_scheduler.py ~/Desktop/nex/
#   mv ~/Downloads/deploy_train_scheduler.sh ~/Desktop/nex/
#   chmod +x ~/Desktop/nex/deploy_train_scheduler.sh
#   cd ~/Desktop/nex && source venv/bin/activate && ./deploy_train_scheduler.sh
# ════════════════════════════════════════════════════════════════
set -euo pipefail

NEX_DIR="$HOME/Desktop/nex"
RUN_PY="$NEX_DIR/run.py"
TG_CMD="$NEX_DIR/nex_telegram_commands.py"
TS=$(date +%s)

echo "══════════════════════════════════════"
echo " NEX Autonomous Training Scheduler"
echo "══════════════════════════════════════"

[[ -f "$RUN_PY" ]]                                  || { echo "ERROR: run.py not found"; exit 1; }
[[ -f "$NEX_DIR/nex_train_scheduler.py" ]]          || { echo "ERROR: nex_train_scheduler.py missing"; exit 1; }

cp "$RUN_PY" "$RUN_PY.bak_trainer_$TS"
echo "[✓] Backed up run.py"

# ── Patch run.py: import + tick ──────────────────────────────
python3 - << 'PYEOF'
import re, ast
from pathlib import Path

RUN = Path.home() / "Desktop/nex/run.py"
src = RUN.read_text()

if "nex_train_scheduler" in src:
    print("[trainer] Already patched — skipping"); exit(0)

IMPORT = (
    "\n# ── Autonomous training scheduler ──────────────────────\n"
    "try:\n"
    "    from nex_train_scheduler import get_scheduler as _get_scheduler\n"
    "    _trainer = _get_scheduler()\n"
    "except Exception as _trainer_ex:\n"
    "    print(f'[trainer] Load failed: {_trainer_ex}')\n"
    "    _trainer = None\n"
)

# Anchor: after last _rXXX = None or _eXXX = None
for anchor in ["    _r181 = None\n", "_r181 = None\n",
               "    _x160 = None\n", "_x160 = None\n",
               "    _e140 = None\n", "_e140 = None\n",
               "    _v80 = None\n",  "_v80 = None\n"]:
    idx = src.find(anchor)
    if idx != -1:
        src = src[:idx + len(anchor)] + IMPORT + src[idx + len(anchor):]
        print(f"[trainer] Import after: {anchor.strip()!r}")
        break
else:
    m = re.search(r'import signal\n', src)
    assert m
    src = src[:m.end()] + IMPORT + src[m.end():]
    print("[trainer] Import after 'import signal'")

# Tick: after last err log line
lines     = src.splitlines(keepends=True)
insert_at = None
pad       = "                    "

for err_tok in ["nex_r181_err.txt", "nex_x160_err.txt",
                "nex_e140_err.txt", "nex_r115_err.txt", "nex_v80_err.txt"]:
    for i, ln in enumerate(lines):
        if err_tok in ln:
            pad = " " * (len(lines[i]) - len(lines[i].lstrip()))
            insert_at = i + 1
            break
    if insert_at: break

assert insert_at, "No tick anchor"

TICK = [
    "\n",
    f"{pad}# ── Training scheduler tick ─────────────────────────\n",
    f"{pad}if _trainer is not None:\n",
    f"{pad}    try:\n",
    f"{pad}        _trainer.tick()\n",
    f"{pad}    except Exception as _etr:\n",
    f"{pad}        open('/tmp/nex_trainer_err.txt','a').write(str(_etr)+'\\n')\n",
]

for k, bl in enumerate(TICK):
    lines.insert(insert_at + k, bl)

src = "".join(lines)
ast.parse(src)
RUN.write_text(src)
print(f"[trainer] run.py written — tick at line {insert_at}")
PYEOF

echo "[✓] run.py patched"

# ── Register Telegram commands ────────────────────────────────
python3 - << 'PYEOF'
from pathlib import Path

tc  = Path.home() / "Desktop/nex/nex_telegram_commands.py"
src = tc.read_text()

if "trainstatus_command" in src:
    print("[trainer] Telegram commands already registered"); exit(0)

CMDS = '''
async def trainstatus_command(update, context):
    """NEX training scheduler status + readiness."""
    try:
        from nex_train_scheduler import get_scheduler
        msg = get_scheduler().format_status()
    except Exception as e:
        msg = f"trainer status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def traindata_command(update, context):
    """Force generate training data now. Args: light|hectic"""
    try:
        from nex_train_scheduler import get_scheduler
        args = context.args if context.args else []
        mode = args[0].lower() if args else "light"
        if mode not in ("light", "hectic"):
            mode = "light"
        await update.message.reply_text(
            f"Generating {mode} training data... (notifying when done)")
        import threading
        def _gen():
            try:
                get_scheduler().force_generate(mode)
            except Exception as e:
                import asyncio
                pass
        threading.Thread(target=_gen, daemon=True).start()
    except Exception as e:
        await update.message.reply_text(f"traindata error: {e}")

async def trainnow_command(update, context):
    """Evaluate training readiness and generate if ready."""
    try:
        from nex_train_scheduler import get_scheduler
        sched = get_scheduler()
        ev    = sched.get_readiness()
        mode  = ev.get("mode")
        if mode:
            await update.message.reply_text(
                f"Ready for {mode} training. Generating data + notifying...")
            import threading
            threading.Thread(target=sched.force_generate, args=(mode,), daemon=True).start()
        else:
            ls = ev.get("light_score","?")
            hs = ev.get("hectic_score","?")
            await update.message.reply_text(
                f"Not ready yet.\\nLight: {ls}/4 | Hectic: {hs}/4\\n"
                f"Beliefs: {ev.get('belief_count','?')} | "
                f"conf: {ev.get('avg_conf','?')}\\n"
                f"New since last: {ev.get('new_beliefs','?')}")
    except Exception as e:
        await update.message.reply_text(f"trainnow error: {e}")

'''

HANDLERS = """    application.add_handler(CommandHandler("trainstatus", trainstatus_command))
    application.add_handler(CommandHandler("traindata", traindata_command))
    application.add_handler(CommandHandler("trainnow", trainnow_command))
"""

idx = src.find("def register_handlers")
if idx == -1: idx = src.rfind("application.add_handler(CommandHandler")
if idx == -1: src = src + "\n" + CMDS
else: src = src[:idx] + CMDS + src[idx:]

last = src.rfind("application.add_handler(CommandHandler")
if last != -1:
    eol = src.find("\n", last) + 1
    src = src[:eol] + HANDLERS + src[eol:]

tc.write_text(src)
print("[trainer] /trainstatus /traindata /trainnow registered")
PYEOF

echo "[✓] Telegram commands registered"

# ── Create training dir + state file ─────────────────────────
mkdir -p "$HOME/.config/nex/training"
echo "[✓] ~/.config/nex/training/ created"

# ── Syntax checks ─────────────────────────────────────────────
python3 -m py_compile "$NEX_DIR/nex_train_scheduler.py" && echo "[✓] nex_train_scheduler.py OK"
python3 -m py_compile "$RUN_PY"                          && echo "[✓] run.py OK"
python3 -m py_compile "$TG_CMD"                          && echo "[✓] telegram_commands OK"

# ── Git ───────────────────────────────────────────────────────
cd "$NEX_DIR"
git add nex_train_scheduler.py run.py nex_telegram_commands.py
git commit -m "autonomous training scheduler: auto-generates training data from live DB, evaluates light/hectic readiness every 30min, notifies Telegram with download instructions | /trainstatus /traindata /trainnow"
git push

echo ""
echo "══════════════════════════════════════"
echo " Training scheduler deployed. Restart:"
echo "   pkill -f run.py; sleep 2; nex"
echo ""
echo " Telegram commands:"
echo "   /trainstatus  — readiness + last gen"
echo "   /traindata light|hectic  — force generate now"
echo "   /trainnow  — evaluate + generate if ready"
echo ""
echo " Training data saved to:"
echo "   ~/.config/nex/training/"
echo "══════════════════════════════════════"
