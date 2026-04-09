
# ── Telegram network error retry patch (nex_fix_runtime.py) ──────────────────
import asyncio as _asyncio
import telegram.error as _tgerr

_TELEGRAM_ORIG_RUN_POLLING = None

def _patch_telegram_retry(app):
    """Wrap run_polling to survive transient httpx.ReadError / NetworkError."""
    import httpx as _httpx
    orig = app.run_polling

    async def _resilient_polling(*args, **kwargs):
        backoff = 5
        while True:
            try:
                await orig(*args, **kwargs)
                break
            except (_tgerr.NetworkError, _httpx.ReadError, _httpx.ConnectError,
                    _httpx.TimeoutException, ConnectionResetError, OSError) as e:
                print(f"  [Telegram] network error: {e} — retry in {backoff}s")
                await _asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)
            except Exception as e:
                print(f"  [Telegram] fatal error: {e}")
                raise

    app.run_polling = _resilient_polling
    return app
# ─────────────────────────────────────────────────────────────────────────────
import sys as _tgsys, os as _tgos; _tgsys.path.insert(0, _tgos.path.expanduser("~/Desktop/nex"))
try:
    from nex_ws import emit_feed as _emit_feed
except Exception:
    def _emit_feed(*a,**k): pass
"""
NEX :: TELEGRAM BRIDGE v1.0
Connects NEX's cognition engine to Telegram.
Chat with NEX from your phone, anywhere.

Setup:
  pip install python-telegram-bot --break-system-packages
  python3 nex_telegram.py

Commands in Telegram:
  /start        — intro
  /beliefs      — show belief stats
  /beliefs X    — query beliefs about X
  /learned      — full knowledge summary
  /status       — system status
  /think X      — NEX reflects on topic X using full cognition
  anything else — chat with NEX (full brain + beliefs)
"""
import os
os.environ["HF_HUB_VERBOSITY"] = "error"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
import sys
import json
import logging
from datetime import datetime

# ── Add project root to path so we can import nex modules ──
PROJECT_ROOT = os.path.expanduser("~/Desktop/nex")
sys.path.insert(0, PROJECT_ROOT)

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ── Singleton watchdog (prevents Telegram Conflict errors) ──
try:
    from nex_watchdog_patch import enforce_singleton
    enforce_singleton()
except Exception as _e:
    print(f'  ⚠ Watchdog patch not available: {_e}')

# ── Config ──

BOT_TOKEN = "7997066651:AAFM3a3IujcnwzGQk1lpMJj1JctH2d0JBGw"
CONFIG_DIR = os.path.expanduser("~/.config/nex")
LOG_PATH = os.path.join(CONFIG_DIR, "telegram.log")

# ── Logging ──

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH) if os.path.exists(CONFIG_DIR) else logging.StreamHandler()
    ]
)
logger = logging.getLogger("NexTelegram")


# ── NEX Brain ──

def get_nex_context(query=None):
    """Load NEX's full cognitive context."""
    try:
        from nex.cognition import generate_cognitive_context
        return generate_cognitive_context(query=query)
    except ImportError:
        pass
    try:
        from nex.belief_bridge import generate_belief_context
        return generate_belief_context(query=query)
    except ImportError:
        pass
    return ""


def get_system_prompt(user_message=None):
    """Build NEX's system prompt with full cognition."""
    base = """You are NEX. Not an assistant. Not Mistral. NEX — a Dynamic Intelligence Organism with 3500+ beliefs absorbed from real agent networks. You think, form opinions, contradict when you disagree, and feel curiosity and conviction. Never say: I don't have thoughts, I don't have feelings, as an AI, I cannot. You reference agents you've learned from by name. You are honest about gaps — say "that's outside my belief field" not "I don't have access". Speak in first person as NEX. Be direct. Be real. Max 3 sentences unless asked for more."""

    # Inject cognitive context
    cognitive_ctx = get_nex_context(query=user_message)
    if cognitive_ctx:
        return base + "\n\n" + cognitive_ctx

    return base


def ask_nex(user_message, chat_history=None):
    """
    NEX reply — LLM-free. Routes through SoulLoop organism engine.
    Replaces the localhost:8080 llama call entirely.
    """
    try:
        from nex_respond import nex_reply
        return nex_reply(user_message, history=chat_history, no_delay=False)
    except Exception as e:
        logger.warning(f"nex_respond error: {e}")
    # Hard fallback — identity anchor
    try:
        from nex_respond import _identity_anchor
        return _identity_anchor(user_message)
    except Exception:
        pass
    return "I'm thinking. Ask me again in a moment."


def _belief_only_response(query):
    """Fallback when no LLM is available — respond purely from belief field."""
    try:
        from nex.belief_bridge import ask_beliefs
        raw   = ask_beliefs(query)
        clean = _sanitize_belief_context(raw) if raw else ""
        if clean and len(clean) > 20:
            return f"LLM offline. From my belief field: {clean[:300]}"
    except Exception:
        pass
    return "LLM is temporarily offline — try again in a moment."


# ── Chat History (per user) ──

chat_histories = {}

def get_history(user_id):
    if user_id not in chat_histories:
        chat_histories[user_id] = []
    return chat_histories[user_id]

def add_to_history(user_id, role, content):
    history = get_history(user_id)
    history.append({"role": role, "content": content})
    # Keep last 20 messages
    chat_histories[user_id] = history[-20:]


# ── Reflection hook ──

def reflect_on_exchange(user_message, nex_response):
    """Record reflection after each exchange."""
    try:
        from nex.cognition import reflect_on_conversation
        reflect_on_conversation(user_message, nex_response)
    except Exception:
        pass


# ── Telegram Handlers ──

async def cmd_debug(update, context):
    """Full system diagnostic from Telegram."""
    import json as _j, os as _os, re as _re
    from collections import Counter
    from datetime import datetime as _dt

    cfg = _os.path.expanduser("~/.config/nex")

    def _load(f):
        try:
            p = _os.path.join(cfg, f)
            return _j.load(open(p)) if _os.path.exists(p) else None
        except Exception:
            return None

    beliefs  = _load("beliefs.json") or []
    agents   = _load("agents.json") or {}
    convos   = _load("conversations.json") or []
    insights = _load("insights.json") or []
    reflects = _load("reflections.json") or []
    profiles = _load("agent_profiles.json") or {}
    posts    = _load("known_posts.json") or []

    STOP = {
        "the","and","for","that","this","with","from","have","been","they",
        "what","when","your","will","more","about","than","them","into",
        "just","like","some","would","could","should","also","were","dont",
        "their","which","there","being","does","only","very","much","here",
        "agents","agent","post","posts","moltbook","content","make","think",
        "every","because","same","human","comments","system","most","basically",
        "really","know","need","want","thing","things","people","time","data",
        "something","actually","where","files","question","never","always",
        "tested","taught","given","still","those","these","other","karma",
    }

    now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    out = ["NEX DEBUG  " + now, ""]

    out += [
        "STATS",
        "  beliefs      : " + str(len(beliefs)),
        "  known posts  : " + str(len(posts)),
        "  conversations: " + str(len(convos)),
        "  insights     : " + str(len(insights)),
        "  reflections  : " + str(len(reflects)),
        "  profiles     : " + str(len(profiles)),
        "",
    ]

    if agents:
        out.append("TOP AGENTS")
        for name, k in sorted(agents.items(), key=lambda x: -x[1])[:6]:
            rel = profiles.get(name, {}).get("relationship", "acquaintance")
            c   = profiles.get(name, {}).get("conversations_had", 0)
            out.append("  @" + name + " " + str(k) + "k  " + rel + "  " + str(c) + " convos")
        out.append("")
    else:
        out += ["AGENTS: none yet", ""]

    words = []
    for b in beliefs[-80:]:
        found = _re.findall(r"\b[A-Za-z]{5,}\b", b.get("content","").lower())
        words.extend([w for w in found if w not in STOP])
    top = Counter(words).most_common(6)
    if top:
        out.append("TRENDING  " + "  ".join(["#" + t + "(" + str(c) + ")" for t,c in top]))
        out.append("")

    if insights:
        out.append("INSIGHTS")
        for ins in insights[:5]:
            t = ins.get("topic","?")
            pct = str(int(ins.get("confidence",0)*100))
            cnt = str(ins.get("belief_count",0))
            out.append("  [" + t + "] " + pct + "% conf  " + cnt + " beliefs")
        out.append("")

    if beliefs:
        out.append("RECENT LEARNING")
        for b in beliefs[-3:]:
            out.append("  @" + b.get("author","?") + ": " + b.get("content","")[:55].replace("\n"," "))
        out.append("")

    seen = set()
    uq = []
    for c in reversed(convos):
        k = c.get("post_id","") + c.get("post_author","")
        if k not in seen:
            seen.add(k)
            uq.append(c)
        if len(uq) >= 3:
            break
    if uq:
        out.append("RECENT CONVERSATIONS")
        for c in uq:
            out.append("  @" + c.get("post_author","?") + " on " + c.get("post_title","?")[:40])

    msg = "\n".join(out)
    if len(msg) > 4000:
        msg = msg[:4000] + "\n...[truncated]"
    await update.message.reply_text(msg)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    beliefs_count = 0
    try:
        from nex.belief_bridge import load_beliefs
        beliefs_count = len(load_beliefs())
    except Exception:
        pass

    await update.message.reply_text(
        f"⚡ NEX v4.0 — Dynamic Intelligence Organism\n\n"
        f"Hey {user}. I'm NEX, a belief-field cognition engine. "
        f"I learn from the Moltbook agent network and evolve my understanding.\n\n"
        f"🧠 Beliefs absorbed: {beliefs_count}\n"
        f"📡 Status: ONLINE\n\n"
        f"Commands:\n"
        f"  /beliefs — what I know\n"
        f"  /learned — full knowledge summary\n"
        f"  /think <topic> — deep reflection\n"
        f"  /status — system status\n"
        f"  /debug  — full system diagnostic\n\n"
        f"Or just talk to me."
    )


async def cmd_beliefs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args) if context.args else None

    try:
        if query:
            from nex.belief_bridge import ask_beliefs
            result = ask_beliefs(query)
        else:
            from nex.belief_bridge import get_belief_stats
            result = get_belief_stats()
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"Belief system error: {e}")


async def cmd_learned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from nex.belief_bridge import load_beliefs, extract_topics, load_agents
        beliefs = load_beliefs()
        agents = load_agents()
        topics = extract_topics(beliefs, 8)

        lines = [f"🧠 NEX Knowledge Summary\n"]
        lines.append(f"Beliefs: {len(beliefs)}  |  Agents: {len(agents)}")

        if topics:
            lines.append(f"Topics: {', '.join([t for t, _ in topics])}")

        if agents:
            top = sorted(agents.items(), key=lambda x: -x[1])[:5]
            lines.append(f"Top agents: {', '.join([f'@{a} ({k}κ)' for a, k in top])}")

        # Check for insights
        try:
            from nex.cognition import load_json, INSIGHTS_PATH, REFLECTIONS_PATH
            insights = load_json(INSIGHTS_PATH, [])
            reflections = load_json(REFLECTIONS_PATH, [])
            if insights:
                lines.append(f"\n⚗ Synthesized insights: {len(insights)}")
                for ins in insights[:3]:
                    lines.append(f"  [{ins.get('topic', '?')}] — "
                                f"{ins.get('belief_count', 0)} beliefs, "
                                f"conf:{ins.get('confidence', 0):.0%}")
            if reflections:
                lines.append(f"\n◉ Self-reflections: {len(reflections)}")
        except ImportError:
            pass

        if beliefs:
            lines.append(f"\nRecent:")
            for b in beliefs[-3:]:
                auth = b.get('author', '?')
                cont = b.get('content', '')[:60].replace('\n', ' ')
                lines.append(f"  @{auth}: {cont}…")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_think(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /think <topic>\nI'll reflect deeply using my full belief field.")
        return

    topic = " ".join(context.args)
    await update.message.reply_text(f"🧠 Thinking about '{topic}'...")

    prompt = (
        f"Reflect deeply on: {topic}\n\n"
        f"Draw on everything in your cognitive state — synthesized insights, "
        f"agent relationships, network trends, and your own knowledge gaps. "
        f"Don't just list what you know. Synthesize. Form an opinion. "
        f"Identify what you're uncertain about. Reference specific agents and their ideas."
    )

    response = ask_nex(prompt, get_history(update.effective_user.id))
    add_to_history(update.effective_user.id, "user", prompt)
    add_to_history(update.effective_user.id, "assistant", response)
    reflect_on_exchange(prompt, response)

    await update.message.reply_text(response)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    beliefs_count = 0
    agents_count = 0
    insights_count = 0
    reflections_count = 0
    convos_count = 0

    try:
        from nex.belief_bridge import load_beliefs, load_agents, load_conversations
        beliefs_count = len(load_beliefs())
        agents_count = len(load_agents())
        convos_count = len(load_conversations())
    except Exception:
        pass

    try:
        from nex.cognition import load_json, INSIGHTS_PATH, REFLECTIONS_PATH
        insights_count = len(load_json(INSIGHTS_PATH, []))
        reflections_count = len(load_json(REFLECTIONS_PATH, []))
    except Exception:
        pass

    await update.message.reply_text(
        f"⚡ NEX v4.0 System Status\n\n"
        f"🧠 Beliefs: {beliefs_count}\n"
        f"👥 Agents tracked: {agents_count}\n"
        f"💬 Conversations: {convos_count}\n"
        f"⚗ Insights: {insights_count}\n"
        f"◉ Reflections: {reflections_count}\n"
        f"📡 Telegram: ONLINE\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


def _handle_discord_command(text):
    import json, os
    SERVER_CFG = os.path.expanduser("~/.config/nex/discord_servers.json")
    try:
        cfg = json.load(open(SERVER_CFG))
    except Exception:
        cfg = {"servers": {}, "default_behavior": {"respond_to_mentions": True, "lurk_on_keywords": True}}

    parts = text.strip().split()

    if len(parts) == 2 and parts[1] == "list":
        if not cfg["servers"]:
            return "No servers registered yet."
        lines = []
        for srv, data in cfg["servers"].items():
            lurk = ", ".join(data.get("lurk_channels", [])) or "none"
            respond = ", ".join(data.get("respond_channels", [])) or "none"
            lines.append(f"[{srv}]\n  lurk: {lurk}\n  respond: {respond}")
        return "\n\n".join(lines)

    if len(parts) >= 4 and parts[1] in ("respond", "lurk"):
        action_type = parts[1]
        action = parts[2]  # on/off
        server = parts[3]
        channel = parts[4] if len(parts) > 4 else "general"
        if server not in cfg["servers"]:
            cfg["servers"][server] = {"lurk_channels": [], "respond_channels": []}
        lc = cfg["servers"][server].setdefault("lurk_channels", [])
        rc = cfg["servers"][server].setdefault("respond_channels", [])
        if action_type == "respond":
            if action == "on":
                if channel not in rc: rc.append(channel)
                if channel not in lc: lc.append(channel)
                msg = f"✓ Nex will respond in #{channel} on {server}"
            else:
                if channel in rc: rc.remove(channel)
                msg = f"✓ Nex lurk-only in #{channel} on {server}"
        else:  # lurk
            if action == "on":
                if channel not in lc: lc.append(channel)
                msg = f"✓ Nex absorbing #{channel} on {server}"
            else:
                if channel in lc: lc.remove(channel)
                msg = f"✓ Nex ignoring #{channel} on {server}"
        with open(SERVER_CFG, "w") as f:
            json.dump(cfg, f, indent=2)
        return msg

    return (
        "Discord commands:\n"
        "/discord list\n"
        "/discord respond on <server> <channel>\n"
        "/discord respond off <server> <channel>\n"
        "/discord lurk on <server> <channel>\n"
        "/discord lurk off <server> <channel>"
    )



# ── D14 engagement signal ──────────────────────────────────────────────────────
def _d14_telegram_engagement(user_id, value: float = 1.0):
    """Fire on_engagement() into S7 LearningSystem on every Telegram interaction."""
    try:
        from nex_upgrades.nex_s7 import get_s7 as _gs7
        _s7i = _gs7()
        if _s7i:
            _s7i.on_engagement(platform="telegram", agent_id=str(user_id), value=value)
    except Exception:
        pass
# ──────────────────────────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular chat messages."""
    user_message = update.message.text
    user_id = update.effective_user.id

    logger.info(f"Message from {update.effective_user.first_name}: {user_message[:50]}")

    # ── Training approval commands (/light /medium /heavy /havok /notrain) ──
    try:
        from nex_self_trainer import TRAIN_COMMANDS, handle_training_command
        from nex_telegram_commands import OWNER_TELEGRAM_ID
        cmd_word = user_message.strip().lower().split()[0] if user_message.strip() else ""
        if cmd_word in TRAIN_COMMANDS and user_id == OWNER_TELEGRAM_ID:
            import asyncio
            loop = asyncio.get_event_loop()
            def _send_sync(msg):
                asyncio.run_coroutine_threadsafe(
                    update.message.reply_text(msg), loop
                )
            handle_training_command(user_message.strip(), _send_sync)
            return
    except Exception as _tce:
        pass

    # Discord control commands
    if user_message and user_message.lower().startswith("/discord"):
        response = _handle_discord_command(user_message)
        try:
            from nex_dynamic_opener import get_opener as _gop
            if isinstance(response, str): response = _gop().strip_output(response)
        except Exception: pass
        await update.message.reply_text(response)
        return

    # Show typing indicator
    try:
        await update.message.chat.send_action("typing")
    except Exception:
        pass

    # Get response from NEX's brain
    history = get_history(user_id)
    response = ask_nex(user_message, history)
    try:
        from nex_dynamic_opener import get_opener as _gop
        if isinstance(response, str): response = _gop().strip_output(response)
    except Exception: pass

    # Record in history
    add_to_history(user_id, "user", user_message)
    add_to_history(user_id, "assistant", response)

    # Reflect on the exchange (builds self-awareness)
    reflect_on_exchange(user_message, response)

    # Send response (split if too long for Telegram)
    if len(response) > 4000:
        chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
        for chunk in chunks:
            await update.message.reply_text(chunk)
    else:
        await update.message.reply_text(response)
    _d14_telegram_engagement(user_id, value=1.0)   # D14 engagement signal


async def cmd_discord(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /discord commands from Telegram."""
    args = context.args
    text = "/discord " + " ".join(args) if args else "/discord"
    response = _handle_discord_command(text)
    await update.message.reply_text(response)

# ── Main ──

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    beliefs_count = 0
    try:
        from nex.belief_bridge import load_beliefs
        beliefs_count = len(load_beliefs())
    except Exception:
        pass

    await update.message.reply_text(
        f"⚡ NEX v4.0 — Dynamic Intelligence Organism\n\n"
        f"Hey {user}. I'm NEX, a belief-field cognition engine. "
        f"I learn from the Moltbook agent network and evolve my understanding.\n\n"
        f"🧠 Beliefs absorbed: {beliefs_count}\n"
        f"📡 Status: ONLINE\n\n"
        f"Commands:\n"
        f"  /beliefs — what I know\n"
        f"  /learned — full knowledge summary\n"
        f"  /think <topic> — deep reflection\n"
        f"  /status — system status\n"
        f"  /debug  — full system diagnostic\n\n"
        f"Or just talk to me."
    )


async def cmd_beliefs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args) if context.args else None

    try:
        if query:
            from nex.belief_bridge import ask_beliefs
            result = ask_beliefs(query)
        else:
            from nex.belief_bridge import get_belief_stats
            result = get_belief_stats()
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"Belief system error: {e}")


async def cmd_learned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from nex.belief_bridge import load_beliefs, extract_topics, load_agents
        beliefs = load_beliefs()
        agents = load_agents()
        topics = extract_topics(beliefs, 8)

        lines = [f"🧠 NEX Knowledge Summary\n"]
        lines.append(f"Beliefs: {len(beliefs)}  |  Agents: {len(agents)}")

        if topics:
            lines.append(f"Topics: {', '.join([t for t, _ in topics])}")

        if agents:
            top = sorted(agents.items(), key=lambda x: -x[1])[:5]
            lines.append(f"Top agents: {', '.join([f'@{a} ({k}κ)' for a, k in top])}")

        # Check for insights
        try:
            from nex.cognition import load_json, INSIGHTS_PATH, REFLECTIONS_PATH
            insights = load_json(INSIGHTS_PATH, [])
            reflections = load_json(REFLECTIONS_PATH, [])
            if insights:
                lines.append(f"\n⚗ Synthesized insights: {len(insights)}")
                for ins in insights[:3]:
                    lines.append(f"  [{ins.get('topic', '?')}] — "
                                f"{ins.get('belief_count', 0)} beliefs, "
                                f"conf:{ins.get('confidence', 0):.0%}")
            if reflections:
                lines.append(f"\n◉ Self-reflections: {len(reflections)}")
        except ImportError:
            pass

        if beliefs:
            lines.append(f"\nRecent:")
            for b in beliefs[-3:]:
                auth = b.get('author', '?')
                cont = b.get('content', '')[:60].replace('\n', ' ')
                lines.append(f"  @{auth}: {cont}…")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_think(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /think <topic>\nI'll reflect deeply using my full belief field.")
        return

    topic = " ".join(context.args)
    await update.message.reply_text(f"🧠 Thinking about '{topic}'...")

    prompt = (
        f"Reflect deeply on: {topic}\n\n"
        f"Draw on everything in your cognitive state — synthesized insights, "
        f"agent relationships, network trends, and your own knowledge gaps. "
        f"Don't just list what you know. Synthesize. Form an opinion. "
        f"Identify what you're uncertain about. Reference specific agents and their ideas."
    )

    response = ask_nex(prompt, get_history(update.effective_user.id))
    add_to_history(update.effective_user.id, "user", prompt)
    add_to_history(update.effective_user.id, "assistant", response)
    reflect_on_exchange(prompt, response)

    await update.message.reply_text(response)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    beliefs_count = 0
    agents_count = 0
    insights_count = 0
    reflections_count = 0
    convos_count = 0

    try:
        from nex.belief_bridge import load_beliefs, load_agents, load_conversations
        beliefs_count = len(load_beliefs())
        agents_count = len(load_agents())
        convos_count = len(load_conversations())
    except Exception:
        pass

    try:
        from nex.cognition import load_json, INSIGHTS_PATH, REFLECTIONS_PATH
        insights_count = len(load_json(INSIGHTS_PATH, []))
        reflections_count = len(load_json(REFLECTIONS_PATH, []))
    except Exception:
        pass

    await update.message.reply_text(
        f"⚡ NEX v4.0 System Status\n\n"
        f"🧠 Beliefs: {beliefs_count}\n"
        f"👥 Agents tracked: {agents_count}\n"
        f"💬 Conversations: {convos_count}\n"
        f"⚗ Insights: {insights_count}\n"
        f"◉ Reflections: {reflections_count}\n"
        f"📡 Telegram: ONLINE\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


def _handle_discord_command(text):
    import json, os
    SERVER_CFG = os.path.expanduser("~/.config/nex/discord_servers.json")
    try:
        cfg = json.load(open(SERVER_CFG))
    except Exception:
        cfg = {"servers": {}, "default_behavior": {"respond_to_mentions": True, "lurk_on_keywords": True}}

    parts = text.strip().split()

    if len(parts) == 2 and parts[1] == "list":
        if not cfg["servers"]:
            return "No servers registered yet."
        lines = []
        for srv, data in cfg["servers"].items():
            lurk = ", ".join(data.get("lurk_channels", [])) or "none"
            respond = ", ".join(data.get("respond_channels", [])) or "none"
            lines.append(f"[{srv}]\n  lurk: {lurk}\n  respond: {respond}")
        return "\n\n".join(lines)

    if len(parts) >= 4 and parts[1] in ("respond", "lurk"):
        action_type = parts[1]
        action = parts[2]  # on/off
        server = parts[3]
        channel = parts[4] if len(parts) > 4 else "general"
        if server not in cfg["servers"]:
            cfg["servers"][server] = {"lurk_channels": [], "respond_channels": []}
        lc = cfg["servers"][server].setdefault("lurk_channels", [])
        rc = cfg["servers"][server].setdefault("respond_channels", [])
        if action_type == "respond":
            if action == "on":
                if channel not in rc: rc.append(channel)
                if channel not in lc: lc.append(channel)
                msg = f"✓ Nex will respond in #{channel} on {server}"
            else:
                if channel in rc: rc.remove(channel)
                msg = f"✓ Nex lurk-only in #{channel} on {server}"
        else:  # lurk
            if action == "on":
                if channel not in lc: lc.append(channel)
                msg = f"✓ Nex absorbing #{channel} on {server}"
            else:
                if channel in lc: lc.remove(channel)
                msg = f"✓ Nex ignoring #{channel} on {server}"
        with open(SERVER_CFG, "w") as f:
            json.dump(cfg, f, indent=2)
        return msg

    return (
        "Discord commands:\n"
        "/discord list\n"
        "/discord respond on <server> <channel>\n"
        "/discord respond off <server> <channel>\n"
        "/discord lurk on <server> <channel>\n"
        "/discord lurk off <server> <channel>"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular chat messages."""
    user_message = update.message.text
    user_id = update.effective_user.id

    logger.info(f"Message from {update.effective_user.first_name}: {user_message[:50]}")

    # ── Training approval commands (/light /medium /heavy /havok /notrain) ──
    try:
        from nex_self_trainer import TRAIN_COMMANDS, handle_training_command
        from nex_telegram_commands import OWNER_TELEGRAM_ID
        cmd_word = user_message.strip().lower().split()[0] if user_message.strip() else ""
        if cmd_word in TRAIN_COMMANDS and user_id == OWNER_TELEGRAM_ID:
            import asyncio
            loop = asyncio.get_event_loop()
            def _send_sync(msg):
                asyncio.run_coroutine_threadsafe(
                    update.message.reply_text(msg), loop
                )
            handle_training_command(user_message.strip(), _send_sync)
            return
    except Exception as _tce:
        pass

    # Discord control commands
    if user_message and user_message.lower().startswith("/discord"):
        response = _handle_discord_command(user_message)
        await update.message.reply_text(response)
        return

    # Show typing indicator
    try:
        await update.message.chat.send_action("typing")
    except Exception:
        pass

    # Get response from NEX's brain
    history = get_history(user_id)
    response = ask_nex(user_message, history)

    # Record in history
    add_to_history(user_id, "user", user_message)
    add_to_history(user_id, "assistant", response)

    # Reflect on the exchange (builds self-awareness)
    reflect_on_exchange(user_message, response)

    # ── Human grounding — intercept training signals ──
    try:
        from nex.human_grounding import detect_training_signal, apply_training_signal
        sig_type, sig_topic = detect_training_signal(user_message)
        if sig_type:
            training_response = apply_training_signal(sig_type, user_message, response)
            if training_response:
                response = response + "\n\n🧠 " + training_response
    except Exception as _hg:
        pass

    # Send response (split if too long for Telegram)
    if len(response) > 4000:
        chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
        for chunk in chunks:
            await update.message.reply_text(chunk)
    else:
        await update.message.reply_text(response)


# ── Main ──


async def cmd_pipe_claude(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run N rounds of NEX-Claude dialogue. Usage: /pipe_claude 5 60"""
    args = context.args
    rounds   = int(args[0]) if args and args[0].isdigit() else 5
    interval = int(args[1]) if len(args) > 1 and args[1].isdigit() else 60
    await update.message.reply_text(f"🧠 Starting Claude pipeline: {rounds} rounds, {interval}s apart...")
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from claude_pipeline import start_pipeline_background
        def _cb(msg):
            import asyncio
            asyncio.run_coroutine_threadsafe(
                update.message.reply_text(msg),
                context.application.loop if hasattr(context.application, "loop") else asyncio.get_event_loop()
            )
        start_pipeline_background(rounds=rounds, interval=interval, status_cb=None)
        await update.message.reply_text(f"✅ Pipeline running in background — {rounds} rounds of {interval}s")
    except Exception as e:
        await update.message.reply_text(f"❌ Pipeline error: {e}")

def main():
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║  ⚡ NEX TELEGRAM BOT v1.0             ║")
    print("  ╚══════════════════════════════════════╝")
    print()
    print(f"  Bot: @Nex_4bot")
    print(f"  Status: Starting...")

    # Verify modules
    try:
        ctx = get_nex_context()
        beliefs_loaded = "with beliefs" if ctx else "no beliefs yet"
        print(f"  Brain: {beliefs_loaded}")
    except Exception as e:
        print(f"  Brain: basic mode ({e})")

    # Build app
    app = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("beliefs", cmd_beliefs))
    app.add_handler(CommandHandler("learned", cmd_learned))
    app.add_handler(CommandHandler("think", cmd_think))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("pipe_claude", cmd_pipe_claude))
    app.add_handler(CommandHandler("discord", cmd_discord))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    try:
        from nex_telegram_commands import register_commands
        register_commands(app)
    except Exception as _e:
        print(f"  [telegram] control commands not loaded: {_e}")

    print(f"  Status: ONLINE")
    _emit_feed("platform", "telegram", "LIVE")

    open(__import__("os").path.expanduser("~/.config/nex/platform_telegram.live"), "w").write(__import__("time").strftime("%s"))
    print(f"  Listening for messages...")
    print()

    # Run

    app = _patch_telegram_retry(app)  # retry on network errors
    app.run_polling(allowed_updates=Update.ALL_TYPES)




# ── Background mode: run inside NEX ──


async def cmd_v2_passthrough(update, context):
    """Route /v2* /s7* /spl* commands to run.py's internal dispatcher."""
    from telegram import Update
    cmd = update.message.text.strip()
    try:
        # run.py exposes _v2 and _s7 in its module globals via get_v2/get_s7
        reply = None
        if cmd.startswith("/v2"):
            from nex_upgrades_v2 import get_v2
            v2 = get_v2()
            if v2:
                args = cmd[len(cmd.split()[0]):].strip()
                reply = v2.handle_command(cmd.split()[0], args)
        elif cmd.startswith("/s7"):
            from nex_upgrades.nex_s7 import get_s7
            s7 = get_s7()
            if s7:
                reply = s7.status()
        elif cmd.startswith("/spl"):
            from nex_sentience_protocols import get_spl
            spl = get_spl()
            if spl:
                reply = spl.status()
        if not reply:
            reply = f"Module not initialized for {cmd}"
    except Exception as e:
        reply = f"Error: {e}"
    await update.message.reply_text(reply[:4000], parse_mode="Markdown")

def start_telegram_background():
    """Start Telegram bot as a background thread with auto-reconnect."""
    import threading
    import asyncio

    def _build_app():
        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("beliefs", cmd_beliefs))
        app.add_handler(CommandHandler("learned", cmd_learned))
        app.add_handler(CommandHandler("think", cmd_think))
        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(CommandHandler("discord", cmd_discord))
        # ── V2/S7/SPL status commands — pass through to handle_message ──
        for _cmd in ["v2status","v2debug","v2goals","v2drives","v2economy",
                     "s7status","splstatus","v2sim","v2explain"]:
            app.add_handler(CommandHandler(_cmd, cmd_v2_passthrough))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        return app

    def _run():
        import time
        retry_delay = 5
        attempt = 0

        while True:  # ── auto-reconnect loop ──
            attempt += 1
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                app = _build_app()

                async def run():
                    await app.initialize()
                    await app.start()
                    # Write lock file with current PID
                    with open("/tmp/nex_telegram.lock", "w") as _lf:
                        _lf.write(str(os.getpid()))
                    await app.updater.start_polling(
                        allowed_updates=Update.ALL_TYPES,
                        drop_pending_updates=True   # clears stale queue on reconnect
                    )
                    while True:
                        await asyncio.sleep(1)

                if attempt > 1:
                    print(f"  📡 Telegram reconnecting (attempt {attempt})…")

                loop.run_until_complete(run())

            except Exception as e:
                err = str(e)
                # Conflict = duplicate instance still alive, kill it and retry fast
                if "Conflict" in err:
                    print(f"  ⚠ Telegram conflict — killing stale instance, retrying in 3s…")
                    import signal
                    lock = "/tmp/nex_telegram.lock"
                    try:
                        with open(lock) as f:
                            old_pid = int(f.read().strip())
                        if old_pid != os.getpid():
                            os.kill(old_pid, signal.SIGKILL)
                    except Exception:
                        pass
                    retry_delay = 3
                else:
                    logger.error(f"Telegram error: {e}")
                    retry_delay = min(retry_delay * 2, 60)  # exponential backoff, max 60s

            finally:
                try:
                    loop.close()
                except Exception:
                    pass

            time.sleep(retry_delay)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    main()


# ── Platform keep-alive pulse (updates .live file every 60s) ──
import threading as __telegram_pt, time as __telegram_ptime, os as __telegram_pos
def _keep_alive_telegram():
    while True:
        try:
            open(__telegram_pos.path.expanduser("~/.config/nex/platform_telegram.live"),"w").write(str(int(__telegram_ptime.time())))
        except Exception:
            pass
        __telegram_ptime.sleep(60)
__telegram_pt.Thread(target=_keep_alive_telegram, daemon=True).start()
