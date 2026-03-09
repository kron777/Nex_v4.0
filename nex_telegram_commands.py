"""
nex_telegram_commands.py — Owner command interface via Telegram for Nex v1.2
=============================================================================
Drop into ~/Desktop/nex/nex/

Lets you send Nex direct instructions via Telegram:
  "learn quantum computing"
  "research federated learning"
  "find out about the fediverse"
  "/learn prompt engineering"
  "/status"
  "/queue"

She'll acknowledge, queue the topic, and crawl it at next ABSORB.

Setup:
  1. Set OWNER_TELEGRAM_ID below to your Telegram user ID
     (get it by messaging @userinfobot on Telegram)
  2. Wire into your existing Telegram polling loop (see bottom of file)

Security:
  Only messages from OWNER_TELEGRAM_ID are treated as commands.
  Everyone else gets Nex's normal reply behaviour unchanged.
"""

import logging
import re
import time

logger = logging.getLogger("nex.telegram_commands")

# ── Your Telegram user ID — only you can command her ─────────────────────────
# Message @userinfobot on Telegram to get yours
OWNER_TELEGRAM_ID = 5217790760  # set

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

STATUS_TRIGGERS = [r"^/status$", r"^status$", r"^/queue$", r"^queue$"]
HELP_TRIGGERS   = [r"^/help$", r"^help$"]


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
    """
    Parse a Telegram message into a command dict.
    Returns None if not a recognized command.

    Returns:
        {"type": "learn", "topic": "quantum computing"}
        {"type": "status"}
        {"type": "help"}
    """
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

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Command handler
# ─────────────────────────────────────────────────────────────────────────────

class TelegramCommandHandler:
    """
    Handles owner commands received via Telegram.
    Inject into your existing Telegram message processing.
    """

    def __init__(self, curiosity_engine, telegram_bot):
        """
        curiosity_engine: your CuriosityEngine instance from nex_curiosity.py
        telegram_bot:     your existing Telegram bot object (python-telegram-bot
                          or whatever you're using) — needs a send_message method
        """
        self.curiosity = curiosity_engine
        self.bot = telegram_bot

    def _send(self, chat_id: int, text: str):
        """Send a reply back to Telegram. Wraps your bot's send method."""
        try:
            # Adjust this call to match your existing Telegram bot library:
            # python-telegram-bot v13: self.bot.send_message(chat_id=chat_id, text=text)
            # python-telegram-bot v20: await self.bot.send_message(...)
            # requests-based:          requests.post(url, json={...})
            self.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.warning(f"[telegram_cmd] failed to send reply: {e}")

    def handle(self, message: dict) -> bool:
        """
        Process an incoming Telegram message.
        Returns True if it was an owner command (suppress normal Nex reply).
        Returns False if not a command (let Nex reply normally).

        message dict expected fields:
            message["from"]["id"]   — sender Telegram ID
            message["chat"]["id"]   — chat ID to reply to
            message["text"]         — message text
        """
        sender_id = message.get("from", {}).get("id")
        chat_id   = message.get("chat", {}).get("id")
        text      = message.get("text", "").strip()

        # Not from owner — let Nex handle it normally
        if sender_id != OWNER_TELEGRAM_ID:
            return False

        # ── LoRA training approval ───────────────────────────────────────
        try:
            from nex.nex_lora import LoRATrainer
            from nex.nex_db import NexDB
            _lora = LoRATrainer(NexDB(), telegram_bot=self.bot)
            if _lora.handle_approval(text, chat_id):
                return True
        except Exception as _le:
            pass
        cmd = parse_command(text)
        if not cmd:
            return False   # Owner sent a normal message, not a command

        logger.info(f"[telegram_cmd] owner command: {cmd}")

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
                # Topic was on cooldown or already queued
                last_crawled = self.curiosity.queue._crawled_topics.get(topic.lower())
                if last_crawled:
                    hours_ago = (time.time() - last_crawled) / 3600
                    self._send(chat_id,
                        f"I already researched \"{topic}\" {hours_ago:.1f}h ago. "
                        f"I'll look again after the 24h cooldown, or send "
                        f"\"force learn {topic}\" to override."
                    )
                else:
                    self._send(chat_id,
                        f"\"{topic}\" is already in my queue."
                    )

        # ── /status ───────────────────────────────────────────────────────────
        elif cmd["type"] == "status":
            s = self.curiosity.status()
            pending_list = "\n".join(
                f"  • {item.topic} ({item.reason})"
                for item in self.curiosity.queue._queue[:8]
            ) or "  (none)"
            self._send(chat_id,
                f"Curiosity queue: {s['pending']} pending\n"
                f"Topics crawled all-time: {s['crawled_total']}\n\n"
                f"Up next:\n{pending_list}"
            )

        # ── /help ─────────────────────────────────────────────────────────────
        elif cmd["type"] == "help":
            self._send(chat_id,
                "Commands I understand:\n\n"
                "learn <topic>       — queue a topic to research\n"
                "research <topic>    — same\n"
                "look up <topic>     — same\n"
                "status / queue      — show what's in my curiosity queue\n"
                "help                — this message\n\n"
                "I'll crawl queued topics at the start of each cycle (~2 min)."
            )

        return True   # Was a command — suppress normal Nex reply


# ─────────────────────────────────────────────────────────────────────────────
# Wire into existing Telegram polling (run.py / your telegram handler)
# ─────────────────────────────────────────────────────────────────────────────
#
# Find where you process incoming Telegram messages and add:
#
#   from nex.nex_telegram_commands import TelegramCommandHandler
#
#   # After curiosity and bot are initialised:
#   cmd_handler = TelegramCommandHandler(curiosity, telegram_bot)
#
#   # In your message processing loop, BEFORE Nex generates a reply:
#   if cmd_handler.handle(message):
#       continue   # was a command, skip normal reply
#
#   # ... existing Nex reply logic unchanged below ...
#
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    test_messages = [
        "learn federated learning",
        "research the fediverse",
        "find out about prompt injection",
        "look into mixture of experts",
        "status",
        "help",
        "hey Nex how are you",         # should return False (not a command)
    ]

    for msg in test_messages:
        cmd = parse_command(msg)
        print(f"  '{msg}'\n    → {cmd}\n")
