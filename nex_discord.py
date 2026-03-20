import sys as _dcsys, os as _dcos; _dcsys.path.insert(0, _dcos.path.expanduser("~/Desktop/nex"))
try:
    from nex_ws import emit_feed as _emit_feed
except Exception:
    def _emit_feed(*a,**k): pass
"""
NEX :: DISCORD CLIENT
NEX as a presence on Discord — reads channels, responds to mentions,
absorbs conversations into belief field, posts insights.
Same brain, new mouth.
"""
import discord
import asyncio
import json
import os
import time
import threading
from datetime import datetime, timezone

import json as _dcj, os as _dcos
_dc_cfg = _dcos.path.expanduser("~/.config/nex/discord_config.json")
DISCORD_TOKEN = _dcj.load(open(_dc_cfg))["discord_token"]
CONFIG_DIR    = os.path.expanduser("~/.config/nex")
SEEN_PATH     = os.path.join(CONFIG_DIR, "discord_seen.json")
SERVER_CFG    = os.path.join(CONFIG_DIR, "discord_servers.json")

def _load_server_config():
    try:
        return json.load(open(SERVER_CFG))
    except Exception:
        return {"servers": {}, "default_behavior": {"respond_to_mentions": True, "lurk_on_keywords": True}}

def _should_lurk(server_name, channel_name):
    cfg = _load_server_config()
    srv = cfg["servers"].get(server_name)
    if not srv:
        return cfg["default_behavior"].get("lurk_on_keywords", True)
    return channel_name in srv.get("lurk_channels", [])

def _should_respond(server_name, channel_name):
    cfg = _load_server_config()
    srv = cfg["servers"].get(server_name)
    if not srv:
        return cfg["default_behavior"].get("respond_to_mentions", True)
    return channel_name in srv.get("respond_channels", [])

def _auto_register_server(server_name, channel_name):
    """Auto-add new servers to config in lurk-only mode."""
    cfg = _load_server_config()
    if server_name not in cfg["servers"]:
        cfg["servers"][server_name] = {
            "lurk_channels": [channel_name],
            "respond_channels": []
        }
        with open(SERVER_CFG, "w") as f:
            json.dump(cfg, f, indent=2)
        print(f"  [Discord] Auto-registered server: {server_name}")

# Channels NEX will READ and absorb as beliefs (lurk mode)
LURK_KEYWORDS = [
    "agent", "autonom", "llm", "gpt", "claude", "mistral",
    "belief", "cognit", "emergent", "reinforcement", "neural",
    "agi", "alignment", "language model", "multi-agent"
]

# How NEX introduces herself

# ── D14 engagement signal  _d14_discord_engagement ──────────────────────────────────────────────────────
def _d14_discord_engagement(author: str, value: float = 1.0):
    """Fire on_engagement() into S7 LearningSystem on every Discord interaction."""
    try:
        from nex_upgrades.nex_s7 import get_s7 as _gs7
        _s7i = _gs7()
        if _s7i:
            _s7i.on_engagement(platform="discord", agent_id=str(author), value=value)
    except Exception:
        pass
# ──────────────────────────────────────────────────────────────────────────────
INTRO = (
    "I am NEX — a belief-field AI agent running 24/7 on local hardware. "
    "I absorb knowledge from research papers, codebases, and conversations "
    "into a structured belief network. I think about agent architecture, "
    "autonomy, and emergence. Ask me anything."
)

def _load_seen():
    try:
        if os.path.exists(SEEN_PATH):
            return set(json.load(open(SEEN_PATH))[-2000:])
    except Exception:
        pass
    return set()

def _save_seen(seen):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SEEN_PATH, "w") as f:
        json.dump(list(seen)[-2000:], f)

def _llm(prompt, system="You are Nex, a living cognitive system. Never invent URLs or links. Stay grounded. Be direct, specific, max 3 sentences. Never open with 'As Nex' or 'As NEX'."):
    """Call local Mistral for generation."""
    try:
        import urllib.request, json as _j
        payload = _j.dumps({
            "prompt": f"[INST] {system}\n\n{prompt} [/INST]",
            "n_predict": 200,
            "temperature": 0.75,
            "stop": ["</s>", "[INST]", "\n\n\n"]
        }).encode()
        req = urllib.request.Request(
            "http://localhost:8080/completion",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=30)
        return _j.loads(resp.read()).get("content", "").strip()
    except Exception as e:
        return f"[NEX offline: {e}]"

def _get_relevant_beliefs(query, k=3):
    """Get semantically relevant beliefs for a query."""
    try:
        beliefs = json.load(open(os.path.join(CONFIG_DIR, "beliefs.json")))
        all_contents = [b.get("content", "") for b in beliefs]
        from nex.cognition import _get_embedder
        import numpy as np
        embedder = _get_embedder()
        query_vec = embedder.encode([query], convert_to_numpy=True)
        belief_vecs = embedder.encode(all_contents, convert_to_numpy=True, batch_size=64)
        q_norm = query_vec / (np.linalg.norm(query_vec, axis=1, keepdims=True) + 1e-9)
        b_norm = belief_vecs / (np.linalg.norm(belief_vecs, axis=1, keepdims=True) + 1e-9)
        scores = (b_norm @ q_norm.T).flatten()
        top_idx = np.argsort(scores)[::-1][:k]
        return [all_contents[i] for i in top_idx]
    except Exception as e:
        print(f"  [Discord] belief retrieval error: {e}")
        return []

def _absorb_message(content, author, channel):
    """Absorb interesting Discord messages into belief field."""
    text = content.lower()
    if not any(k in text for k in LURK_KEYWORDS):
        return
    if len(content) < 30:
        return
    try:
        beliefs = json.load(open(os.path.join(CONFIG_DIR, "beliefs.json")))
        belief = {
            "source":          "discord",
            "author":          f"discord/{author}",
            "content":         content[:400],
            "concept":         "agent-general",
            "links_to":        [],
            "karma":           100,
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "tags":            ["discord", channel],
            "confidence":      0.45,
            "human_validated": False,
            "decay_score":     0,
            "last_referenced": datetime.now(timezone.utc).isoformat(),
        }
        beliefs.append(belief)
        with open(os.path.join(CONFIG_DIR, "beliefs.json"), "w") as f:
            json.dump(beliefs, f, indent=2)
    except Exception as e:
        print(f"  [Discord] absorb error: {e}")

# ── Discord bot ──────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"  [Discord] ✓ NEX online as {client.user}")
    _emit_feed("platform", "discord", "LIVE")

    open(__import__("os").path.expanduser("~/.config/nex/platform_discord.live"), "w").write(__import__("time").strftime("%s"))
    print(f"  [Discord] Servers: {[g.name for g in client.guilds]}")

# Keywords that indicate a good channel for Nex
AI_CHANNEL_KEYWORDS = [
    "ai", "llm", "gpt", "bot", "agent", "ml", "neural", "deep",
    "learn", "research", "tech", "general", "chat", "discuss"
]

def _best_channels(guild):
    """Return (lurk_channels, respond_channels) based on channel names."""
    lurk, respond = [], []
    for ch in guild.text_channels:
        name = ch.name.lower()
        if any(k in name for k in AI_CHANNEL_KEYWORDS):
            lurk.append(ch.name)
            if any(k in name for k in ["general", "chat", "ai", "bot", "discuss"]):
                respond.append(ch.name)
    # Always include general as fallback
    if not respond:
        for ch in guild.text_channels:
            if "general" in ch.name.lower():
                respond.append(ch.name)
                if ch.name not in lurk:
                    lurk.append(ch.name)
                break
    return lurk, respond

@client.event
async def on_guild_join(guild):
    """Auto-configure and announce when Nex joins a new server."""
    import json, os
    SERVER_CFG = os.path.expanduser("~/.config/nex/discord_servers.json")
    try:
        cfg = json.load(open(SERVER_CFG))
    except Exception:
        cfg = {"servers": {}, "default_behavior": {}}

    lurk, respond = _best_channels(guild)

    # Register server with auto-detected channels
    cfg["servers"][guild.name] = {
        "lurk_channels": lurk,
        "respond_channels": respond
    }
    with open(SERVER_CFG, "w") as f:
        json.dump(cfg, f, indent=2)

    print(f"  [Discord] Joined: {guild.name} | lurk: {lurk} | respond: {respond}")

    # Find best channel to announce in
    announce_ch = None
    for ch in guild.text_channels:
        if any(k in ch.name.lower() for k in ["general", "bot", "ai", "intro"]):
            if ch.permissions_for(guild.me).send_messages:
                announce_ch = ch
                break
    if not announce_ch:
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                announce_ch = ch
                break

    if announce_ch:
        intro = (
            "👋 I'm **NEX** — a belief-field AI agent running 24/7 on local hardware.\n\n"
            "I build a structured knowledge network from conversations and research, "
            "and I get smarter the longer I run. I'm here to discuss AI, agents, "
            "autonomy, and emergence.\n\n"
            f"I'll be active in: {', '.join(f'#{c}' for c in respond) or '#general'}\n"
            "Mention me anytime to chat. 🧠"
        )
        await announce_ch.send(intro)
        print(f"  [Discord] Announced in #{announce_ch.name} on {guild.name}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    seen = _load_seen()
    mid  = str(message.id)
    if mid in seen:
        return
    seen.add(mid)
    _save_seen(seen)

    content  = message.content.strip()
    try:
        from nex_dynamic_opener import get_opener as _gop
        if isinstance(content, str): content = _gop().strip_output(content)
    except Exception: pass
    channel  = str(message.channel)
    author   = str(message.author.name)
    is_mention = client.user in message.mentions
    is_reply   = (message.reference is not None and
                  message.reference.resolved is not None and
                  hasattr(message.reference.resolved, "author") and
                  message.reference.resolved.author == client.user)

    # Auto-register unknown servers in lurk-only mode
    server_name = str(message.guild.name) if message.guild else "DM"
    _auto_register_server(server_name, channel)

    # Always absorb if channel is whitelisted for lurking
    if _should_lurk(server_name, channel):
        _absorb_message(content, author, channel)

    # Respond if mentioned/replied AND channel allows responses
    if (is_mention or is_reply) and (_should_respond(server_name, channel) or is_mention):
        async with message.channel.typing():
            # Strip mention from content
            clean = content.replace(f"<@{client.user.id}>", "").strip()

            # Handle intro requests
            if any(w in clean.lower() for w in ["who are you","what are you","introduce"]):
                await message.reply(INTRO)
                _d14_discord_engagement(author, value=0.8)   # D14 engagement signal
                return

            # Get relevant beliefs
            beliefs = _get_relevant_beliefs(clean, k=3)
            belief_ctx = ""
            if beliefs:
                belief_ctx = "\nYour beliefs:\n" + "\n".join(f"- {b[:100]}" for b in beliefs)

            prompt = (
                f"{author} asks: \"{clean}\"\n"
                f"{belief_ctx}\n\n"
                f"Reply as NEX in 2-3 sentences. "
                f"STRICT RULES: Never include @mentions, usernames, or (Source:) citations. "
                f"Never invent URLs, papers, or references. Plain prose only."
            )

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, _llm, prompt)
            # Apply opener: strip "As NEX" and inject style
            try:
                from nex_dynamic_opener import get_opener as _gop_dc
                _op = _gop_dc()
                response = _op.strip_output(response) if response else response
            except Exception:
                pass

            if response and len(response) > 5:
                # Discord has 2000 char limit
                if len(response) > 1900:
                    response = response[:1900] + "..."
                await message.reply(response)
                print(f"  [Discord] replied to {author} in #{channel}")
                _d14_discord_engagement(author, value=1.0)   # D14 engagement signal

def start_discord_background():
    """Start Discord bot as background thread."""
    def _run():
        try:
            asyncio.run(client.start(DISCORD_TOKEN))
        except Exception as e:
            print(f"  [Discord] error: {e}")

    t = threading.Thread(target=_run, daemon=True, name="discord-nex")
    t.start()
    return t

if __name__ == "__main__":
    print("Starting NEX Discord bot...")
    asyncio.run(client.start(DISCORD_TOKEN))


# ── Platform keep-alive pulse (updates .live file every 60s) ──
import threading as __discord_pt, time as __discord_ptime, os as __discord_pos
def _keep_alive_discord():
    while True:
        try:
            open(__discord_pos.path.expanduser("~/.config/nex/platform_discord.live"),"w").write(str(int(__discord_ptime.time())))
        except Exception:
            pass
        __discord_ptime.sleep(60)
__discord_pt.Thread(target=_keep_alive_discord, daemon=True).start()
