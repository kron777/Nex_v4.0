"""
nex_telegram_commands.py
========================
Place at: ~/Desktop/nex/nex_telegram_commands.py

Owner-only Telegram control interface for NEX.
Gives full system control from your phone.

Commands:
  /help       — full command menu
  /status     — live system status (beliefs, mood, processes, GPU)
  /silent     — toggle silent mode (no posting)
  /saturate   — trigger domain saturation
  /anneal     — run belief field annealing
  /rebuild    — rebuild belief graph edges
  /mood       — NEX's current emotional state
  /beliefs    — belief counts by domain
  /restart    — restart crashed processes
  /backup     — trigger manual DB backup
  /version    — NEX version info
"""

import os
import subprocess
import sqlite3
import json
import time
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes

# ── Config ────────────────────────────────────────────────────────────────────
OWNER_TELEGRAM_ID = 5217790760  # loaded from config
NEX_DIR  = Path("/home/rr/Desktop/nex")
DB_PATH  = NEX_DIR / "nex.db"
CFG_PATH = Path("~/.config/nex").expanduser()

# Load owner ID from config
try:
    _cfg = json.loads((CFG_PATH / "telegram_config.json").read_text())
    OWNER_TELEGRAM_ID = int(_cfg.get("owner_id") or _cfg.get("admin_id") or 0)
except Exception:
    try:
        _cfg = json.loads((NEX_DIR / "telegram_config.json").read_text())
        OWNER_TELEGRAM_ID = int(_cfg.get("owner_id") or _cfg.get("admin_id") or 0)
    except Exception:
        pass

SILENT_FLAG = Path("/tmp/nex_silent.flag")


# ── Auth guard ────────────────────────────────────────────────────────────────

def _is_owner(update: Update) -> bool:
    if not OWNER_TELEGRAM_ID:
        return True   # no owner configured — allow all (set your ID!)
    return update.effective_user.id == OWNER_TELEGRAM_ID


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db_scalar(sql, params=()):
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        result = conn.execute(sql, params).fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception:
        return 0


def _db_rows(sql, params=()):
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


# ── Process helpers ───────────────────────────────────────────────────────────

def _proc_running(pattern: str) -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def _gpu_vram() -> str:
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--noheader"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "Used" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "Used":
                        return f"{parts[i+1]} MB"
        return "unknown"
    except Exception:
        return "unknown"


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Full command menu."""
    text = (
        "🤖 *NEX Control Panel*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "*System*\n"
        "/status — live system status\n"
        "/mood — NEX's emotional state\n"
        "/version — version info\n\n"
        "*Knowledge*\n"
        "/beliefs — belief counts by domain\n"
        "/saturate — trigger domain saturation\n"
        "/anneal — run belief field annealing\n"
        "/rebuild — rebuild graph edges\n\n"
        "*Control*\n"
        "/silent — toggle silent mode\n"
        "/restart — restart crashed processes\n"
        "/backup — manual DB backup\n\n"
        "*Conversation*\n"
        "/think [query] — ask NEX anything\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_status_v2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live system status from nex.db and process table."""
    # Belief count
    total_beliefs = _db_scalar("SELECT COUNT(*) FROM beliefs")

    # Top domains
    top_domains = _db_rows(
        "SELECT topic, COUNT(*) as c FROM beliefs "
        "GROUP BY topic ORDER BY c DESC LIMIT 5"
    )
    domain_str = " | ".join(f"{r[0]}:{r[1]}" for r in top_domains)

    # Mood
    mood_label = "unknown"
    mood_val   = 0.0
    try:
        state_path = CFG_PATH / "nex_emotion_state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            mood_label = state.get("label", "unknown")
            mood_val   = state.get("mood", 0.0)
    except Exception:
        pass

    # Processes
    run_ok   = "✅" if _proc_running("run.py") else "❌"
    api_ok   = "✅" if _proc_running("nex_api.py") else "❌"
    sch_ok   = "✅" if _proc_running("nex_scheduler.py") else "❌"
    llm_ok   = "✅" if _proc_running("llama-server") else "❌"

    # Silent mode
    silent = "🔇 ON" if SILENT_FLAG.exists() else "🔊 OFF"

    # GPU
    vram = _gpu_vram()

    text = (
        f"⚡ *NEX v4.0 Status*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 Beliefs: {total_beliefs:,}\n"
        f"📊 Top: {domain_str}\n\n"
        f"💭 Mood: {mood_label} ({mood_val:.2f})\n"
        f"🔇 Silent: {silent}\n\n"
        f"*Processes*\n"
        f"run.py {run_ok} | api {api_ok}\n"
        f"scheduler {sch_ok} | llama {llm_ok}\n\n"
        f"🖥 VRAM: {vram}\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """NEX's current emotional state from belief field."""
    try:
        state_path = CFG_PATH / "nex_emotion_state.json"
        if not state_path.exists():
            await update.message.reply_text("No emotion state recorded yet.")
            return
        state = json.loads(state_path.read_text())
        label     = state.get("label", "unknown")
        valence   = state.get("valence", 0.0)
        arousal   = state.get("arousal", 0.0)
        dominance = state.get("dominance", 0.0)
        mood      = state.get("mood", 0.0)
        temp      = state.get("epistemic_temp", 0.0)
        tension   = state.get("tension_density", 0.0)
        ts        = state.get("timestamp", 0)
        age       = int(time.time() - ts)

        # Valence bar
        v_bar = "▓" * int((valence + 1) * 5) + "░" * (10 - int((valence + 1) * 5))

        text = (
            f"💭 *NEX Emotional State*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Label: *{label.capitalize()}*\n\n"
            f"Valence:   {v_bar} {valence:+.3f}\n"
            f"Arousal:   {arousal:.3f}\n"
            f"Dominance: {dominance:.3f}\n"
            f"Mood:      {mood:.3f}\n\n"
            f"Epistemic temp: {temp:.3f}\n"
            f"Tension density: {tension:.3f}\n\n"
            f"_Updated {age}s ago_"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Mood read error: {e}")


async def cmd_beliefs_v2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Belief counts by domain with saturation status."""
    rows = _db_rows(
        "SELECT topic, COUNT(*) as c FROM beliefs "
        "GROUP BY topic ORDER BY c DESC LIMIT 20"
    )
    total = _db_scalar("SELECT COUNT(*) FROM beliefs")

    TARGET = 200
    lines = [f"🧠 *NEX Belief Graph* — {total:,} total\n━━━━━━━━━━━━━━━━━━━━"]
    for topic, count in rows:
        bar = "▓" * min(10, int(count / TARGET * 10))
        bar = bar.ljust(10, "░")
        status = "✓" if count >= TARGET else f"{count}/{TARGET}"
        lines.append(f"`{topic[:18]:18s}` {bar} {status}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_silent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle silent mode."""
    if not _is_owner(update):
        await update.message.reply_text("Owner only.")
        return

    if SILENT_FLAG.exists():
        SILENT_FLAG.unlink()
        await update.message.reply_text(
            "🔊 *Silent mode OFF*\nNEX is posting again.",
            parse_mode="Markdown"
        )
    else:
        SILENT_FLAG.touch()
        await update.message.reply_text(
            "🔇 *Silent mode ON*\nNEX is thinking but not posting.",
            parse_mode="Markdown"
        )


async def cmd_saturate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trigger domain saturation via scheduler API."""
    if not _is_owner(update):
        await update.message.reply_text("Owner only.")
        return

    await update.message.reply_text("⚗ Triggering domain saturation...")
    try:
        import requests
        r = requests.post(
            "http://localhost:7825/scheduler/trigger",
            headers={
                "Content-Type": "application/json",
                "X-Admin-Secret": "nex-admin-2026"
            },
            json={"job": "saturation"},
            timeout=10
        )
        if r.status_code == 200:
            await update.message.reply_text(
                "✅ Saturation triggered.\nRunning in background — check /beliefs in a few minutes."
            )
        else:
            await update.message.reply_text(f"❌ Scheduler returned {r.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_anneal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run belief field annealing."""
    if not _is_owner(update):
        await update.message.reply_text("Owner only.")
        return

    await update.message.reply_text("🔥 Starting annealing (200 cycles)...")
    try:
        subprocess.Popen(
            ["python3", str(NEX_DIR / "nex_annealing.py"), "--cycles", "200"],
            cwd=str(NEX_DIR),
            stdout=open("/tmp/nex_annealing.log", "w"),
            stderr=subprocess.STDOUT
        )
        await update.message.reply_text(
            "✅ Annealing running in background.\nLog: /tmp/nex_annealing.log"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rebuild belief graph edges."""
    if not _is_owner(update):
        await update.message.reply_text("Owner only.")
        return

    await update.message.reply_text("🕸 Rebuilding belief graph edges...")
    try:
        subprocess.Popen(
            ["python3", str(NEX_DIR / "nex_graph_builder.py"), "--build"],
            cwd=str(NEX_DIR),
            stdout=open("/tmp/nex_graph_builder.log", "w"),
            stderr=subprocess.STDOUT
        )
        await update.message.reply_text(
            "✅ Graph rebuild running in background.\nLog: /tmp/nex_graph_builder.log"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trigger manual DB backup."""
    if not _is_owner(update):
        await update.message.reply_text("Owner only.")
        return

    await update.message.reply_text("💾 Running backup...")
    try:
        result = subprocess.run(
            ["bash", str(NEX_DIR / "nex_backup.sh")],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            await update.message.reply_text(f"✅ {result.stdout.strip()}")
        else:
            await update.message.reply_text(f"❌ Backup error: {result.stderr[:200]}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show restart instructions (doesn't auto-restart for safety)."""
    if not _is_owner(update):
        await update.message.reply_text("Owner only.")
        return

    run_ok = _proc_running("run.py")
    api_ok = _proc_running("nex_api.py")
    sch_ok = _proc_running("nex_scheduler.py")
    llm_ok = _proc_running("llama-server")

    lines = ["🔄 *Process Status*\n━━━━━━━━━━━━━━━━━━━━"]
    lines.append(f"run.py:       {'✅ running' if run_ok else '❌ DOWN'}")
    lines.append(f"nex_api.py:   {'✅ running' if api_ok else '❌ DOWN'}")
    lines.append(f"nex_scheduler:{'✅ running' if sch_ok else '❌ DOWN'}")
    lines.append(f"llama-server: {'✅ running' if llm_ok else '❌ DOWN'}")

    if not all([run_ok, api_ok, sch_ok, llm_ok]):
        lines.append("\n⚠️ Some processes are down.")
        lines.append("Run on your machine:\n`cd ~/Desktop/nex && bash nex_launch.sh`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """NEX version and build info."""
    total   = _db_scalar("SELECT COUNT(*) FROM beliefs")
    domains = _db_scalar("SELECT COUNT(DISTINCT topic) FROM beliefs")

    try:
        git = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=str(NEX_DIR), capture_output=True, text=True
        ).stdout.strip()
    except Exception:
        git = "unknown"

    text = (
        f"🤖 *NEX v4.0*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"IQ: 92% ELITE\n"
        f"Beliefs: {total:,} across {domains} domains\n"
        f"Phases: 1-4 complete\n"
        f"Next: Phase 5 (emotion) → Phase 6 (memory)\n\n"
        f"Last commit:\n`{git}`\n\n"
        f"GitHub: github.com/kron777/Nex_v4.0"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Registration helper ───────────────────────────────────────────────────────


async def cmd_thrownet(update, context):
    """Run Throw-Net on a constraint. Usage: /thrownet your constraint here"""
    from telegram.ext import ContextTypes
    args = ' '.join(context.args) if context.args else ''
    if not args:
        await update.message.reply_text(
            "Usage: /thrownet <constraint>\n"
            "Example: /thrownet Nex cannot reason causally about beliefs"
        )
        return
    await update.message.reply_text(f"🧠 Throw-Net running on: {args[:80]}...")
    try:
        import sys
        sys.path.insert(0, '/home/rr/Desktop/nex/nex')
        from nex_throw_net import handle_thrownet_command
        result = handle_thrownet_command(args)
        await update.message.reply_text(result[:4000])
    except Exception as e:
        await update.message.reply_text(f"Throw-Net error: {str(e)[:200]}")

async def cmd_approve_tn(update, context):
    """Approve a Throw-Net session. Usage: /approve_tn <session_id>"""
    if not context.args:
        await update.message.reply_text("Usage: /approve_tn <session_id>")
        return
    try:
        session_id = int(context.args[0])
        notes = ' '.join(context.args[1:]) if len(context.args) > 1 else ''
        from nex_throw_net import handle_approve_command
        result = handle_approve_command(session_id, notes)
        await update.message.reply_text(result[:2000])
    except Exception as e:
        await update.message.reply_text(f"Approve error: {str(e)[:200]}")

async def cmd_tn_sessions(update, context):
    """Show recent Throw-Net sessions. Usage: /tn_sessions"""
    try:
        from nex_throw_net import handle_sessions_command
        result = handle_sessions_command(limit=5)
        await update.message.reply_text(result[:4000])
    except Exception as e:
        await update.message.reply_text(f"Sessions error: {str(e)[:200]}")


async def cmd_refine_tn(update, context):
    """Refine a Throw-Net session. Usage: /refine_tn <session_id>"""
    args = ' '.join(context.args) if context.args else ''
    if not args:
        await update.message.reply_text("Usage: /refine_tn <session_id>")
        return
    await update.message.reply_text(f"🔬 Refining session {args}...")
    try:
        import sys
        sys.path.insert(0, '/home/rr/Desktop/nex/nex')
        from nex_refinement_engine import handle_refine_command
        result = handle_refine_command(args)
        await update.message.reply_text(result[:4000])
    except Exception as e:
        await update.message.reply_text(f"Refine error: {str(e)[:200]}")

async def cmd_auto_refine(update, context):
    """Auto-refine all pending sessions. Usage: /auto_refine"""
    await update.message.reply_text("🔬 Auto-refining pending sessions...")
    try:
        from nex_refinement_engine import handle_auto_refine_command
        result = handle_auto_refine_command()
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"Auto-refine error: {str(e)[:200]}")

def register_commands(app):
    """
    Register all new commands with a Telegram Application instance.
    Call this from nex_telegram.py after existing handlers are added.

    Usage in nex_telegram.py:
        from nex_telegram_commands import register_commands
        register_commands(app)
    """
    from telegram.ext import CommandHandler

    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("mood",     cmd_mood))
    app.add_handler(CommandHandler("silent",   cmd_silent))
    app.add_handler(CommandHandler("saturate", cmd_saturate))
    app.add_handler(CommandHandler("anneal",   cmd_anneal))
    app.add_handler(CommandHandler("rebuild",  cmd_rebuild))
    app.add_handler(CommandHandler("backup",   cmd_backup))
    app.add_handler(CommandHandler("restart",  cmd_restart))
    app.add_handler(CommandHandler("version",  cmd_version))

    # Override old status and beliefs with improved versions
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("status",   cmd_status_v2))
    app.add_handler(CommandHandler("beliefs",  cmd_beliefs_v2))

    app.add_handler(CommandHandler("thrownet",    cmd_thrownet))
    app.add_handler(CommandHandler("approve_tn",  cmd_approve_tn))
    app.add_handler(CommandHandler("tn_sessions", cmd_tn_sessions))
    app.add_handler(CommandHandler("refine_tn",   cmd_refine_tn))
    app.add_handler(CommandHandler("auto_refine",  cmd_auto_refine))
    print("  [telegram_commands] registered 16 commands")
