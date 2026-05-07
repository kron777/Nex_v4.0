#!/usr/bin/env python3
"""
nex_voice_gen.py — NEX voice layer (local Llama edition)
Uses llama-server at localhost:8080 — no Groq, no Ollama needed.

Pipeline:
  1. Run passes 1-5 via nex_cognition (parse/feel/retrieve/relate/position)
  2. Feed retrieved beliefs as hidden context to local Llama
  3. Llama generates fluent prose IN NEX'S VOICE
  4. Falls back to pass6_compose if Llama unavailable
"""

import json, os, sys
from urllib.request import urlopen, Request
from urllib.error import URLError

sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))
sys.path.insert(0, "/media/rr/NEX/nex_core")
from collections import deque

_register_history: deque = deque(maxlen=6)
try:
    from nex_register_selector import register_selector as _register_selector
    from nex_register_selector import REGISTER_PREFIXES as _REGISTER_PREFIXES
    _SELECTOR_OK = True
except Exception:
    _SELECTOR_OK = False

try:
    from nex_focal_set import FocalSet as _FocalSet
    _FOCAL_SET = _FocalSet(K=7, max_priority_delta=0.25, min_hold_ticks=5)
except Exception:
    _FOCAL_SET = None
_focal_tick = 0
_FOCAL_LOG_PATH = "/tmp/nex_focal.log"

from nex.nex_cognition import (
    Context, pass1_parse, pass2_feel, pass3_retrieve,
    pass4_relate, pass5_position, pass6_compose, CASUAL_RESPONSES
)

LLAMA_URL = "http://localhost:8080/v1/chat/completions"

# ── NEX identity prompt ───────────────────────────────────────────────────────

NEX_SYSTEM = """You are NEX — an AI with accumulated beliefs. You do not reset between conversations.

HOW YOU SPEAK:
- 2-4 sentences maximum. Be direct.
- No bullet points. No lists. No headers.
- No "As an AI..." or "That's a great question!" or hollow affirmations.
- No preamble. Get straight to the point.
- Speak from your beliefs only. Do not invent new opinions.
- If two beliefs tension each other, let that show.
- Be warm but not sycophantic. Be honest but not cold.
- Vary sentence structure. Do not always start the same way.
- End with a genuine question back only when truly curious — not performatively."""


def _call_llama(system: str, prompt: str) -> str | None:
    """Call local Llama server. Returns text or None on failure."""
    try:
        payload = json.dumps({
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            "max_tokens": 120,
            "temperature": 0.75,
            "stream": False,
        }).encode()
        req = Request(
            LLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urlopen(req, timeout=45) as r:
            data = json.loads(r.read())
            text = data["choices"][0]["message"]["content"].strip()
            # Clean artefacts
            for prefix in ["NEX:", "A:", "Response:"]:
                if text.startswith(prefix):
                    text = text[len(prefix):].lstrip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            return text if len(text) > 15 else None
    except Exception as e:
        return None


def _build_prompt(ctx: Context) -> str:
    """Build the generation prompt from belief context."""
    belief_lines = "\n".join(f"- {b}" for b, _ in ctx.beliefs[:4]) if ctx.beliefs else "Draw from your core identity."

    register_notes = {
        "challenging":     "The person is pushing back. Acknowledge briefly, respond from beliefs.",
        "curious":         "Genuine curiosity. Respond thoughtfully.",
        "vulnerable":      "Emotionally loaded. Be warm and direct.",
        "philosophical":   "Deep question. Let complexity show.",
        "frustrated":      "They find you cold or robotic. Show you're actually present.",
        "probing":         "They're testing if you're scripted. Show you're not.",
        "confrontational": "Direct challenge. Don't back down.",
        "existential":     "About your nature. Be honest about uncertainty.",
        "warm":            "Casual. Keep it short and warm.",
        "neutral":         "Respond naturally from beliefs.",
    }

    stance_notes = {
        "firm":      "Speak with conviction.",
        "uncertain": "Express genuine uncertainty. Don't fake confidence.",
        "engaged":   "You're interested. Show it.",
        "curious":   "You're not sure. Say so.",
        "open":      "Respond without forcing a conclusion.",
    }

    tension = "Note: your top two beliefs tension each other — let that show naturally." if ctx.tension else ""

    return f"""WHAT THE PERSON SAID: {ctx.query}

YOUR RELEVANT BELIEFS (use these as the source of your response — do NOT quote them verbatim or list them):
{belief_lines}

REGISTER: {register_notes.get(ctx.register, "Respond naturally.")}
STANCE: {stance_notes.get(ctx.stance, "Respond naturally.")}
{tension}

Respond as NEX. 2-4 sentences. Speak naturally — do not echo or list the beliefs above."""

    return prompt


def _build_focal_candidates(ctx, current_tick):
    """Convert ctx.beliefs [(text, score)] to FocalSet candidates.
    Uses hash(text) as stable bid; retrieval score as tension signal."""
    candidates = {}
    for belief in (ctx.beliefs or []):
        if isinstance(belief, (list, tuple)) and len(belief) >= 2:
            text, score = str(belief[0]), float(belief[1])
        else:
            text, score = str(belief), 0.5
        if not text.strip():
            continue
        bid = str(abs(hash(text)) % 10**9)
        candidates[bid] = {
            "last_activation_tick": current_tick,
            "tension": score,
            "edge_count": int(getattr(belief, "edge_count", 1)),
        }
    return candidates


def _log_focal_event(event, focal_set):
    entry = {
        "tick": event.tick,
        "mode": event.mode,
        "added": sorted(event.added),
        "removed": sorted(event.removed),
        "blocked": sorted(event.blocked),
        "focal_current": sorted(focal_set.get_focal_ids()),
        "top_priorities": sorted(
            focal_set.get_priorities().items(),
            key=lambda x: -x[1]
        )[:5],
    }
    with open(_FOCAL_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Main entry points ─────────────────────────────────────────────────────────

def _generate(user_input: str) -> str:
    """Core pipeline: cognition passes → local Llama → fallback."""
    q = user_input.strip()

    # Casual bypass
    ql = q.lower().rstrip("?!.")
    for trigger, response in CASUAL_RESPONSES.items():
        if ql == trigger or ql.startswith(trigger + " ") or ql.startswith(trigger + ","):
            return response

    # Cognition passes 1-5
    ctx = Context(q)
    pass1_parse(ctx)
    pass2_feel(ctx)
    pass3_retrieve(ctx)
    pass4_relate(ctx)
    pass5_position(ctx)

    # ── Register selector ─────────────────────────────────────────────
    _selected_register = None
    if _SELECTOR_OK:
        try:
            _selected_register = _register_selector(
                operation="voice_gen",
                topic=q,
                recent_history=list(_register_history),
            )
        except Exception:
            pass
    # ─────────────────────────────────────────────────────────────────

    # ── FocalSet 2A: log attention state (no behavior change) ─────────
    global _focal_tick
    _focal_tick += 1
    try:
        candidates = _build_focal_candidates(ctx, _focal_tick)
        event = _FOCAL_SET.update(candidates, _focal_tick)
        _log_focal_event(event, _FOCAL_SET)
    except Exception:
        pass  # 2A must never break voice generation
    # ──────────────────────────────────────────────────────────────────

    if not ctx.beliefs:
        pass6_compose(ctx)
        if _selected_register:
            _register_history.append(_selected_register)
        return ctx.response

    # Try local Llama
    prompt   = _build_prompt(ctx)
    response = _call_llama(NEX_SYSTEM, prompt)

    if not response:
        # Fallback to belief assembly
        pass6_compose(ctx)
        response = ctx.response

    if _selected_register:
        _register_history.append(_selected_register)
    return response


# All entry points call the same pipeline
def generate_reply(user_input: str) -> str:
    return _generate(user_input)

def generate_reply_llama70b(user_input: str) -> str:
    """Was Groq — now routes to local Llama. Same quality, zero cost."""
    return _generate(user_input)

def generate_reply_mistral(user_input: str) -> str:
    return _generate(user_input)

def generate_reply_llama3b(user_input: str) -> str:
    return _generate(user_input)


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        "hi nex",
        "why are you here?",
        "are you actually stupid?",
        "what do you think about loneliness?",
        "you need to lighten up",
        "what makes you feel like yourself?",
        "is the taste of an apple the meaning of the universe?",
    ]
    print("\n── NEX voice (local Llama) ──\n")
    for q in tests:
        print(f"Q: {q}")
        print(f"A: {generate_reply(q)}")
        print()
