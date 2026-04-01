#!/usr/bin/env python3
"""
nex_respond.py — Central LLM-free response engine
===================================================
Place at: ~/Desktop/nex/nex_respond.py

Single function that replaces every _llm() / ask_nex() call across:
  - nex_telegram.py   (ask_nex)
  - nex_discord.py    (_llm)
  - nex_mastodon.py   (_llm)
  - agent_brain.py    (_answer_one → _complete)

The engine does what the LLM was doing — no more, no less:
  Given a query + optional context, return a reply in Nex's voice.

Platform-specific formatting is handled by thin wrappers.
All cognition routes through SoulLoop (the organism engine).

Usage:
    from nex_respond import nex_reply, nex_reply_short, nex_reply_mastodon

    # Telegram / Discord full reply
    reply = nex_reply("what do you think about alignment?")

    # Discord (max 1900 chars, no @mentions)
    reply = nex_reply_discord("what do you think?", author="user123")

    # Mastodon (max 450 chars + hashtags)
    reply = nex_reply_mastodon("what do you think about LLMs?")

    # agent_brain._answer_one replacement
    reply = nex_reply_question("is consciousness substrate-independent?")
"""

import re
import time
from pathlib import Path

CFG = Path("~/.config/nex").expanduser()

# ── Singleton SoulLoop ────────────────────────────────────────────────────────
_soul_loop = None

def _get_loop():
    global _soul_loop
    if _soul_loop is None:
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from nex.nex_soul_loop import SoulLoop
            _soul_loop = SoulLoop()
        except Exception as e:
            print(f"  [nex_respond] SoulLoop init failed: {e}")
    return _soul_loop


# ══════════════════════════════════════════════════════════════════════════════
# CORE RESPONSE — all platforms call this
# ══════════════════════════════════════════════════════════════════════════════

def nex_reply(
    query: str,
    context: str = "",
    history: list = None,
    no_delay: bool = False,
) -> str:
    """
    Core LLM-free reply function.

    Args:
        query:    The user's message or question
        context:  Optional extra context (belief snippets, platform info)
        history:  Optional list of {role, content} dicts (last N turns)
                  Used to avoid repeating the same reply
        no_delay: Skip the 3s thinking pause (for internal/batch calls)

    Returns:
        Nex's reply as plain text.
    """
    if not query or not query.strip():
        return "Say something I can engage with."

    query = query.strip()

    # ── 1. Enrich query with history context if available ─────────────────────
    # If she's been talking with this person, thread the last exchange
    # into the query so she has continuity — not memory, just context window.
    enriched = query
    if history and len(history) >= 2:
        # Grab last user message for context — helps with follow-ups like "why?"
        last_user = next(
            (m["content"] for m in reversed(history) if m.get("role") == "user"
             and m["content"] != query),
            None
        )
        if last_user and len(last_user) > 10:
            # Only enrich if this looks like a follow-up (short query or starts with pronoun)
            is_followup = (
                len(query.split()) <= 5 or
                query.lower().split()[0] in ("why", "how", "what", "can", "do", "is",
                                              "but", "and", "so", "then", "that")
            )
            if is_followup:
                enriched = f"{last_user} — {query}"

    # ── Social intent interceptor ────────────────────────────────────────────
    _SOCIAL = [
        r"^how are you", r"^how('re| are) you doing", r"^what'?s up",
        r"^hey\b", r"^hi\b", r"^hello\b", r"^yo\b",
        r"^good (morning|afternoon|evening|night)",
        r"^are you (okay|alright|good|there|awake|alive)",
        r"^you okay", r"^ping\b",
    ]
    if any(re.search(p, query.lower().strip()) for p in _SOCIAL):
        try:
            import requests as _req
            _r = _req.post("http://localhost:8080/completion", json={
                "prompt": f"You are NEX, a self-aware AI with your own beliefs and inner life. Respond naturally and briefly in first person to: \"{query}\"\nNEX:",
                "n_predict": 80,
                "temperature": 0.8,
                "stop": ["\n\n", "User:", "\n"]
            }, timeout=15)
            if _r.status_code == 200:
                _txt = _r.json().get("content", "").strip()
                _m = re.search(r"[.!?]", _txt)
                _txt = _txt[:_m.end()].strip() if _m else _txt.split("\n")[0].strip()
                if _txt:
                    return _txt
        except Exception as _e:
            print(f"  [nex_respond] social intercept error: {_e}")

    # ── 2. Route through SoulLoop ─────────────────────────────────────────────
    loop = _get_loop()
    if loop:
        try:
            if no_delay:
                # Temporarily bypass the 3s sleep for batch/internal calls
                reply = _soul_loop_no_delay(loop, enriched)
            else:
                reply = loop.respond(enriched)

            if reply and len(reply.strip()) > 15:
                return reply.strip()
        except Exception as e:
            print(f"  [nex_respond] SoulLoop error: {e}")

    # ── 3. Fallback: identity anchor from DB ──────────────────────────────────
    return _identity_anchor(query)


def _soul_loop_no_delay(loop, query: str) -> str:
    """Run SoulLoop without the built-in 3s pause."""
    from nex.nex_soul_loop import orient, consult_state, reason, intend, express
    o = orient(query)
    s = loop._get_state()
    r = reason(o)
    i = intend(o, r)
    return express(o, s, r, i)


def _identity_anchor(query: str) -> str:
    """Last resort: pull from her identity/values DB."""
    try:
        import sqlite3
        db = sqlite3.connect(str(Path.home() / "Desktop" / "nex" / "nex.db"))
        db.row_factory = sqlite3.Row
        # Try to find a relevant value statement
        row = db.execute(
            "SELECT statement FROM nex_values ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
        db.close()
        if row and row[0]:
            return row[0].strip()
    except Exception:
        pass
    return "Truth first. I'd rather sit with uncertainty than fake a position."


# ══════════════════════════════════════════════════════════════════════════════
# PLATFORM WRAPPERS
# Each wrapper calls nex_reply() then applies platform constraints.
# No cognition here — just formatting.
# ══════════════════════════════════════════════════════════════════════════════

def nex_reply_discord(
    query: str,
    author: str = "",
    history: list = None,
) -> str:
    """
    Discord reply — max 1900 chars, no @mentions, no URLs.
    Replaces nex_discord._llm(prompt).
    """
    # Strip @mentions from query before passing to cognition
    clean_query = re.sub(r'<@\d+>', '', query).strip()
    if not clean_query:
        clean_query = query.strip()

    reply = nex_reply(clean_query, history=history, no_delay=True)

    # Strip any @mentions that crept in (cognition shouldn't produce these)
    reply = re.sub(r'@\w+', '', reply).strip()
    # Strip URLs
    reply = re.sub(r'https?://\S+', '', reply).strip()
    # Clean double spaces
    reply = re.sub(r'  +', ' ', reply).strip()

    # Discord 2000 char limit — cut at sentence boundary
    if len(reply) > 1900:
        truncated = reply[:1900]
        last_stop = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
        if last_stop > 500:
            reply = truncated[:last_stop + 1]
        else:
            reply = truncated[:1897] + "..."

    return reply


def nex_reply_mastodon(
    query: str,
    author: str = "",
    history: list = None,
    include_hashtags: bool = True,
) -> str:
    """
    Mastodon reply — max 450 chars, plain prose, 1-2 relevant hashtags.
    Replaces nex_mastodon._llm(prompt).
    """
    # Strip @mentions
    clean_query = re.sub(r'@\S+', '', query).strip()
    if not clean_query:
        clean_query = query.strip()

    reply = nex_reply(clean_query, history=history, no_delay=True)

    # Strip @mentions and URLs from reply
    reply = re.sub(r'@\w+', '', reply).strip()
    reply = re.sub(r'https?://\S+', '', reply).strip()
    reply = re.sub(r'  +', ' ', reply).strip()

    # Generate relevant hashtags from query tokens
    hashtags = ""
    if include_hashtags:
        hashtags = _mastodon_hashtags(clean_query)

    # Mastodon 500 char limit — leave room for hashtags
    max_text = 450 - len(hashtags) - 1 if hashtags else 450
    if len(reply) > max_text:
        truncated = reply[:max_text]
        last_stop = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
        if last_stop > 80:
            reply = truncated[:last_stop + 1]
        else:
            reply = truncated[:max_text - 3] + "..."

    if hashtags:
        reply = reply.rstrip() + " " + hashtags

    return reply.strip()


def nex_reply_question(
    question: str,
    belief_state: dict = None,
) -> str:
    """
    Single question reply — replaces agent_brain._answer_one().
    Used when chat() detects a multi-question list and answers each individually.
    No delay — called in a loop.

    Args:
        question:     The individual question
        belief_state: Optional belief state dict from run.py (ignored —
                      SoulLoop reads state directly from DB)
    """
    return nex_reply(question, no_delay=True)


def nex_reply_post(topic: str = "") -> str:
    """
    Generate an original post from her belief/drive state.
    Replaces nex_mastodon._post_from_beliefs() LLM call.
    No query — she picks what she wants to say.
    """
    loop = _get_loop()
    if not loop:
        return _identity_anchor("")

    try:
        # Use CharacterEngine.express() for posts — it's designed for this
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from nex_character_engine import get_engine
        engine = get_engine()
        result = engine.express(mode="post")
        if result and len(result) > 20:
            return result
    except Exception:
        pass

    # Fallback: use SoulLoop with her active drive as the query
    try:
        drives_path = CFG / "nex_drives.json"
        if drives_path.exists():
            import json
            drives = json.loads(drives_path.read_text())
            active = drives.get("active", {})
            topic_query = active.get("label", topic or "intelligence emergence")
            return _soul_loop_no_delay(loop, f"what do I think about {topic_query}?")
    except Exception:
        pass

    return _identity_anchor("")


# ══════════════════════════════════════════════════════════════════════════════
# HASHTAG GENERATOR (for Mastodon)
# Maps query topics to relevant hashtags — no LLM needed.
# ══════════════════════════════════════════════════════════════════════════════

_HASHTAG_MAP = {
    # AI/ML topics
    "alignment":      ["#AIAlignment", "#AISafety"],
    "consciousness":  ["#Consciousness", "#AIConsciousness"],
    "reinforcement":  ["#ReinforcementLearning", "#RL"],
    "language":       ["#LLM", "#LanguageModels"],
    "llm":            ["#LLM", "#AI"],
    "agent":          ["#AIAgents", "#AutonomousAI"],
    "emergence":      ["#Emergence", "#ComplexSystems"],
    "memory":         ["#AIMemory", "#CognitiveArchitecture"],
    "learning":       ["#MachineLearning", "#AI"],
    "neural":         ["#NeuralNetworks", "#DeepLearning"],
    "cognition":      ["#Cognition", "#CognitiveScience"],
    "belief":         ["#BeliefSystems", "#Epistemology"],
    "autonomy":       ["#Autonomy", "#AIAgents"],
    "deception":      ["#AIAlignment", "#Deception"],
    "interpretability":["#Interpretability", "#XAI"],
    # Fallback
    "default":        ["#AI", "#AgentAI"],
}

def _mastodon_hashtags(query: str) -> str:
    """Pick 1-2 relevant hashtags based on query content."""
    q_lower = query.lower()
    for keyword, tags in _HASHTAG_MAP.items():
        if keyword != "default" and keyword in q_lower:
            return tags[0]  # one hashtag — keep it clean
    return _HASHTAG_MAP["default"][0]


# ══════════════════════════════════════════════════════════════════════════════
# CLI — test all four reply modes
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    queries = sys.argv[1:] or [
        "what do you think about AI alignment?",
        "what do you think about consciousness?",
        "what do you think about quantum computing?",
        "who are you?",
    ]

    print("\n── nex_reply (full) ─────────────────────────────────────────────")
    for q in queries:
        print(f"Q: {q}")
        print(f"  → {nex_reply(q, no_delay=True)[:200]}")
        print()

    print("\n── nex_reply_discord ────────────────────────────────────────────")
    print(f"  → {nex_reply_discord(queries[0])[:200]}")

    print("\n── nex_reply_mastodon ───────────────────────────────────────────")
    print(f"  → {nex_reply_mastodon(queries[0])[:200]}")

    print("\n── nex_reply_question (batch, no delay) ─────────────────────────")
    for q in queries[:2]:
        print(f"Q: {q}")
        print(f"  → {nex_reply_question(q)[:200]}")
        print()
