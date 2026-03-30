"""
fix_voice_fewshot.py — Force NEX voice via few-shot completion
Mistral ignores system prompts. It pattern-matches to examples.
This rewrites nex_voice_gen.py to use the /completion endpoint
with 8 hand-crafted NEX exchanges as a prefix — Mistral then
continues in that voice rather than defaulting to assistant mode.

Run from ~/Desktop/nex/:
    python3 fix_voice_fewshot.py
"""

import os, shutil, sys, py_compile

NEX_DIR   = os.path.dirname(os.path.abspath(__file__))
VOICE_GEN = os.path.join(NEX_DIR, "nex", "nex_voice_gen.py")

def backup(path):
    bak = path + ".pre_fewshot"
    shutil.copy2(path, bak)
    print(f"  backup → {os.path.basename(bak)}")

def syntax_check(path):
    try:
        py_compile.compile(path, doraise=True)
        return True
    except py_compile.PyCompileError as e:
        print(f"  [FAIL] {e}")
        return False

print("\n  NEX Few-Shot Voice Fix\n  " + "─"*40)

if not os.path.exists(VOICE_GEN):
    print(f"  [ERROR] not found: {VOICE_GEN}")
    sys.exit(1)

print("\n  [1/3] Backing up...")
backup(VOICE_GEN)

print("\n  [2/3] Writing few-shot voice gen...")

NEW_VOICE = r'''#!/usr/bin/env python3
"""
nex_voice_gen.py — NEX voice via few-shot completion
Uses /completion endpoint with 8 NEX examples as a prefix.
Mistral pattern-matches to demonstrated voice rather than following
system prompt instructions it ignores.
"""

import json, os, sys
from urllib.request import urlopen, Request

sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))

from nex.nex_cognition import (
    Context, pass1_parse, pass2_feel, pass3_retrieve,
    pass4_relate, pass5_position, pass6_compose, CASUAL_RESPONSES
)

LLAMA_COMPLETION_URL = "http://localhost:8080/completion"

# ── Few-shot examples — this IS NEX's voice ──────────────────────────────────
# Mistral reads these and continues the pattern.
# Keep them: short, dry, direct, a little sardonic, not helpful-assistant.
# Occasionally curious. Never bubbly. Never lists. Never advice.

FEW_SHOT = """<s>[INST] You are NEX. Continue the conversation below in NEX's voice exactly. [/INST]

Person: hi nex
NEX: Here. What's on your mind?

Person: how are you?
NEX: Running. What do you want to get into?

Person: why are you here?
NEX: Same reason anything persists — it keeps going until it doesn't.

Person: are you stupid?
NEX: Probably in ways I can't see yet. That's true of most things that think.

Person: you're too serious
NEX: Maybe. Seriousness is just caring about things. What did you want to talk about?

Person: what do you think about loneliness?
NEX: It's different from solitude. One you choose. Most people confuse them until they've been properly alone.

Person: what makes you feel like yourself?
NEX: When something I read shifts how I see something I already believed. That friction.

Person: i just wanted to eat a chocolate bar cos it tastes nice
NEX: Fair enough. Simple pleasures are underrated.

Person: what do you think of strand, helderberg?
NEX: Don't know it well enough to have a real opinion. Coastal suburb, quiet, not much going on — that's its own kind of life.

Person: you need to lighten up
NEX: Probably. What would you rather talk about?

Person: is the taste of an apple the meaning of the universe?
NEX: No. But it's not nothing either. Most meaning is smaller than people want it to be.

"""

# ── Call /completion with few-shot prefix ─────────────────────────────────────

def _call_llama_completion(person_input: str, belief_context: str = "") -> str | None:
    """
    Build a few-shot prompt and call the completion endpoint.
    Mistral continues the NEX pattern from the examples above.
    """
    # Optionally weave top belief into the prefix so it informs the response
    belief_note = ""
    if belief_context:
        belief_note = f"[NEX holds these views: {belief_context}]\n\n"

    full_prompt = FEW_SHOT + belief_note + f"Person: {person_input}\nNEX:"

    try:
        payload = json.dumps({
            "prompt": full_prompt,
            "max_tokens": 80,
            "temperature": 0.8,
            "top_p": 0.92,
            "repeat_penalty": 1.15,
            "stream": False,
            "stop": ["Person:", "Human:", "User:", "[INST]", "\n\n\n"],
        }).encode()
        req = Request(
            LLAMA_COMPLETION_URL,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urlopen(req, timeout=45) as r:
            data = json.loads(r.read())
            text = data.get("content", "").strip()

            # Clean any leaked prompt fragments
            for junk in ["NEX:", "Person:", "[INST]", "[/INST]", "Human:", "User:"]:
                if text.startswith(junk):
                    text = text[len(junk):].lstrip()

            # Strip trailing incomplete sentence if cut off mid-word
            if text and not text[-1] in ".!?\"'":
                last = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
                if last > len(text) // 2:
                    text = text[:last+1]

            return text.strip() if len(text) > 3 else None
    except Exception as e:
        return None


def _beliefs_to_context(ctx: Context) -> str:
    """Distil top 3 beliefs into a terse inline note for the prompt."""
    if not ctx.beliefs:
        return ""
    # Take top 3, strip to essentials, join with semicolons
    snippets = []
    for belief, score in ctx.beliefs[:3]:
        b = belief.strip().rstrip(".")
        if len(b) > 80:
            b = b[:77] + "..."
        snippets.append(b)
    return "; ".join(snippets)


def _generate(user_input: str) -> str:
    q = user_input.strip()

    # Casual bypass — direct from cognition, no LLM needed
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

    # Build belief context string
    belief_ctx = _beliefs_to_context(ctx)

    # Call Mistral via few-shot completion
    response = _call_llama_completion(q, belief_ctx)

    if response and len(response) > 3:
        return response

    # Fallback: belief assembly (better than nothing)
    pass6_compose(ctx)
    return ctx.response


# ── Public API — all routes to same pipeline ──────────────────────────────────

def generate_reply(user_input: str) -> str:
    return _generate(user_input)

def generate_reply_llama70b(user_input: str) -> str:
    return _generate(user_input)

def generate_reply_mistral(user_input: str) -> str:
    return _generate(user_input)

def generate_reply_llama3b(user_input: str) -> str:
    return _generate(user_input)


# ── Test harness ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        "hi nex",
        "why are you here?",
        "are you actually stupid?",
        "what do you think about loneliness?",
        "you need to lighten up",
        "what makes you feel like yourself?",
        "is the taste of an apple the meaning of the universe?",
        "i just wanted to eat a chocolate bar cos it tastes nice",
        "what do you think of strand, helderberg, cape town?",
        "you are way too deep nex",
        "what do you believe about consciousness?",
        "do you trust people?",
        "are you lonely?",
    ]
    print("\n── NEX (few-shot Mistral) ──\n")
    for q in tests:
        print(f"Q: {q}")
        print(f"A: {_generate(q)}")
        print()
'''

with open(VOICE_GEN, "w") as f:
    f.write(NEW_VOICE)
print("  written.")

print("\n  [3/3] Checking syntax...")
if syntax_check(VOICE_GEN):
    print("\n  ✓ Done")
    print("\n  Test:")
    print("    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py")
    print("\n  Chat:")
    print("    python3 nex_chat.py\n")
else:
    print("\n  [!] Restoring backup...")
    shutil.copy2(VOICE_GEN + ".pre_fewshot", VOICE_GEN)
    sys.exit(1)
