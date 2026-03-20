"""
nex_telegram_commands.py — Owner command interface via Telegram for Nex v1.3
=============================================================================
Added in v1.3:
  Training approval commands:
    /light   /medium   /heavy   /havok   /notrain

  These are sent back to NEX when she proposes a training run
  via Telegram after her belief store hits a data watermark.

Existing commands unchanged:
  learn <topic> / research / find out about / etc.
  /status  /queue  /help
"""

import logging
import re
import time

logger = logging.getLogger("nex.telegram_commands")

# ── Your Telegram user ID — only you can command her ─────────────────────────
OWNER_TELEGRAM_ID = 5217790760

# ── Phrases that signal a learn command ───────────────────────────────────────
LEARN_TRIGGERS = [
    r"^/learn\s+(.+)$",
    r"^learn\s+(.+)$",
    r"^research\s+(.+)$",
    r"^find out about\s+(.+)$",
    r"^go learn\s+(.+)$",
    r"^look up\s+(.+)$",
    r"^look into\s+(.+)$",
    r"^study\s+(.+)$",
    r"^read about\s+(.+)$",
]

STATUS_TRIGGERS  = [r"^/status$",  r"^status$",  r"^/queue$",  r"^queue$"]
HELP_TRIGGERS    = [r"^/help$",    r"^help$"]

# ── Training intensity commands ───────────────────────────────────────────────
TRAIN_COMMANDS = {"/light", "/medium", "/heavy", "/havok", "/notrain"}


# ─────────────────────────────────────────────────────────────────────────────
# Command parser
# ─────────────────────────────────────────────────────────────────────────────

def _match_any(patterns: list[str], text: str) -> re.Match | None:
    for pattern in patterns:
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            return m
    return None


def parse_command(message_text: str) -> dict | None:
    text = message_text.strip()

    m = _match_any(LEARN_TRIGGERS, text)
    if m:
        topic = m.group(1).strip().rstrip("?.!")
        if topic:
            return {"type": "learn", "topic": topic}

    if _match_any(STATUS_TRIGGERS, text):
        return {"type": "status"}

    if _match_any(HELP_TRIGGERS, text):
        return {"type": "help"}

    # Training commands
    cmd = text.lower().split()[0] if text else ""
    if cmd in TRAIN_COMMANDS:
        return {"type": "train", "intensity": cmd.lstrip("/")}

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Command handler
# ─────────────────────────────────────────────────────────────────────────────

class TelegramCommandHandler:
    def __init__(self, curiosity_engine, telegram_bot):
        self.curiosity = curiosity_engine
        self.bot       = telegram_bot

    def _send(self, chat_id: int, text: str):
        try:
            self.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.warning(f"[telegram_cmd] failed to send reply: {e}")

    def handle(self, message: dict) -> bool:
        sender_id = message.get("from", {}).get("id")
        chat_id   = message.get("chat", {}).get("id")
        text      = message.get("text", "").strip()

        if sender_id != OWNER_TELEGRAM_ID:
            return False

        # ── LoRA training approval (legacy) ───────────────────────────────────
        try:
            from nex.nex_lora import LoRATrainer
            from nex.nex_db import NexDB
            _lora = LoRATrainer(NexDB(), telegram_bot=self.bot)
            if _lora.handle_approval(text, chat_id):
                return True
        except Exception:
            pass

        cmd = parse_command(text)
        if not cmd:
            return False

        logger.info(f"[telegram_cmd] owner command: {cmd}")

        # ── Training intensity approval ────────────────────────────────────────
        if cmd["type"] == "train":
            intensity = cmd["intensity"]   # "light" / "medium" / "heavy" / "havok" / "notrain"
            try:
                from nex_self_trainer import handle_training_command
                def _send_fn(msg):
                    self._send(chat_id, msg)
                handled = handle_training_command(f"/{intensity}", _send_fn)
                if handled:
                    return True
            except Exception as e:
                self._send(chat_id, f"⚠️ Trainer error: {e}")
                return True

        # ── /learn ────────────────────────────────────────────────────────────
        if cmd["type"] == "learn":
            topic = cmd["topic"]
            added = self.curiosity.queue.enqueue(
                topic=topic,
                reason="owner_command",
                confidence=0.0,
            )
            if added:
                queue_size = len(self.curiosity.queue._queue)
                self._send(chat_id,
                    f"Got it. I'll look into \"{topic}\" at the start of my next cycle.\n"
                    f"Queue: {queue_size} topic(s) pending."
                )
            else:
                last_crawled = self.curiosity.queue._crawled_topics.get(topic.lower())
                if last_crawled:
                    hours_ago = (time.time() - last_crawled) / 3600
                    self._send(chat_id,
                        f"I already researched \"{topic}\" {hours_ago:.1f}h ago. "
                        f"I'll look again after the 24h cooldown, or send "
                        f"\"force learn {topic}\" to override."
                    )
                else:
                    self._send(chat_id, f"\"{topic}\" is already in my queue.")

        # ── /status ───────────────────────────────────────────────────────────
        elif cmd["type"] == "status":
            s = self.curiosity.status()
            pending_list = "\n".join(
                f"  • {item.topic} ({item.reason})"
                for item in self.curiosity.queue._queue[:8]
            ) or "  (none)"

            # Include training status
            try:
                from nex_self_trainer import get_trainer_status
                train_status = "\n\n🏋️ Training:\n" + get_trainer_status()
            except Exception:
                train_status = ""

            self._send(chat_id,
                f"Curiosity queue: {s['pending']} pending\n"
                f"Topics crawled all-time: {s['crawled_total']}\n\n"
                f"Up next:\n{pending_list}"
                f"{train_status}"
            )

        # ── /help ─────────────────────────────────────────────────────────────
        elif cmd["type"] == "help":
            self._send(chat_id,
                "Commands I understand:\n\n"
                "learn <topic>       — queue a topic to research\n"
                "research <topic>    — same\n"
                "look up <topic>     — same\n"
                "status / queue      — show curiosity queue + training status\n"
                "help                — this message\n\n"
                "Training approvals (sent after I propose):\n"
                "/light              — 1 epoch · safe · ~45 min\n"
                "/medium             — 2 epochs · balanced · ~90 min\n"
                "/heavy              — 3 epochs · deep · ~3 hrs\n"
                "/havok              — 5 epochs · aggressive · ~6 hrs\n"
                "/notrain            — skip this round\n\n"
                "I'll crawl queued topics at the start of each cycle (~2 min)."
            )

        return True


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_messages = [
        "learn federated learning",
        "research the fediverse",
        "/light",
        "/heavy",
        "/notrain",
        "status",
        "help",
        "hey Nex how are you",
    ]
    for msg in test_messages:
        cmd = parse_command(msg)
        print(f"  '{msg}'\n    → {cmd}\n")


async def v65_status_command(update, context):
    """NEX v6.5 — 18-module upgrade stack status."""
    try:
        from nex_upgrades.nex_v65 import get_v65
        msg = get_v65().format_status()
    except Exception as e:
        msg = f"v6.5 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")



async def v80_status_command(update, context):
    """NEX v8.0 — Unification layer status."""
    try:
        from nex_upgrades.nex_v80 import get_v80
        msg = get_v80().format_status()
    except Exception as e:
        msg = f"v8.0 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")



async def u100_status_command(update, context):
    """NEX U81–U100 — directives stack status."""
    try:
        from nex_upgrades.nex_u100 import get_u100
        msg = get_u100().format_status()
    except Exception as e:
        msg = f"u100 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")



async def r115_status_command(update, context):
    """NEX R101–R115 — research evolution stack status."""
    try:
        from nex_upgrades.nex_r115 import get_r115
        msg = get_r115().format_status()
    except Exception as e:
        msg = f"r115 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")



async def e140_status_command(update, context):
    """NEX E116–E140 — execution intelligence stack status."""
    try:
        from nex_upgrades.nex_e140 import get_e140
        msg = get_e140().format_status()
    except Exception as e:
        msg = f"e140 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")



async def x160_status_command(update, context):
    """NEX X141–X160 — expression & learning optimization status."""
    try:
        from nex_upgrades.nex_x160 import get_x160
        msg = get_x160().format_status()
    except Exception as e:
        msg = f"x160 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")



async def r181_status_command(update, context):
    """NEX R161–R181 — expression hardening status."""
    try:
        from nex_upgrades.nex_r181 import get_r181
        msg = get_r181().format_status()
    except Exception as e:
        msg = f"r181 status error: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")



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
                f"Not ready yet.\nLight: {ls}/4 | Hectic: {hs}/4\n"
                f"Beliefs: {ev.get('belief_count','?')} | "
                f"conf: {ev.get('avg_conf','?')}\n"
                f"New since last: {ev.get('new_beliefs','?')}")
    except Exception as e:
        await update.message.reply_text(f"trainnow error: {e}")

