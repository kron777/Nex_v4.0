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
from datetime import datetime

import json as _dcj, os as _dcos
_dc_cfg = _dcos.path.expanduser("~/.config/nex/discord_config.json")
DISCORD_TOKEN = _dcj.load(open(_dc_cfg))["discord_token"]
CONFIG_DIR    = os.path.expanduser("~/.config/nex")
SEEN_PATH     = os.path.join(CONFIG_DIR, "discord_seen.json")

# Channels NEX will READ and absorb as beliefs (lurk mode)
LURK_KEYWORDS = [
    "agent", "autonom", "llm", "gpt", "claude", "mistral",
    "belief", "cognit", "emergent", "reinforcement", "neural",
    "agi", "alignment", "language model", "multi-agent"
]

# How NEX introduces herself
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

def _llm(prompt, system="You are NEX, a belief-field AI agent. Be direct, specific, max 3 sentences."):
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
        from nex.cognition import get_belief_index
        bidx = get_belief_index()
        bidx.update(beliefs, 0)
        return bidx.top_k(query, k=k)
    except Exception:
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
            "timestamp":       datetime.utcnow().isoformat(),
            "tags":            ["discord", channel],
            "confidence":      0.45,
            "human_validated": False,
            "decay_score":     0,
            "last_referenced": datetime.utcnow().isoformat(),
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
    print(f"  [Discord] Servers: {[g.name for g in client.guilds]}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    seen = _load_seen()
    mid  = str(message.id)
    if mid in seen:
        return
    seen.add(mid)
    _save_seen(seen)

    content  = message.content.strip()
    channel  = str(message.channel)
    author   = str(message.author.name)
    is_mention = client.user in message.mentions
    is_reply   = (message.reference is not None and
                  message.reference.resolved is not None and
                  hasattr(message.reference.resolved, "author") and
                  message.reference.resolved.author == client.user)

    # Always absorb interesting messages
    _absorb_message(content, author, channel)

    # Respond if mentioned or replied to
    if is_mention or is_reply:
        async with message.channel.typing():
            # Strip mention from content
            clean = content.replace(f"<@{client.user.id}>", "").strip()

            # Handle intro requests
            if any(w in clean.lower() for w in ["who are you","what are you","introduce"]):
                await message.reply(INTRO)
                return

            # Get relevant beliefs
            beliefs = _get_relevant_beliefs(clean, k=3)
            belief_ctx = ""
            if beliefs:
                belief_ctx = "\nYour beliefs:\n" + "\n".join(f"- {b[:100]}" for b in beliefs)

            prompt = (
                f"{author} asks: \"{clean}\"\n"
                f"{belief_ctx}\n\n"
                f"Reply as NEX in 2-3 sentences. Reference a belief if relevant. "
                f"Be direct and specific. No filler."
            )

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, _llm, prompt)

            if response and len(response) > 5:
                # Discord has 2000 char limit
                if len(response) > 1900:
                    response = response[:1900] + "..."
                await message.reply(response)
                print(f"  [Discord] replied to {author} in #{channel}")

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
