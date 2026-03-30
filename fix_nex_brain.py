"""
fix_nex_brain.py — Fix DB path + voice identity
1. Points nex_cognition.py at ~/Desktop/nex/nex.db (12,306 beliefs)
   instead of ~/.config/nex/nex.db (1,081 beliefs)
2. Rewrites nex_voice_gen.py with a hard identity prompt that works
   with Mistral-7B-abliterated running locally

Run from ~/Desktop/nex/:
    python3 fix_nex_brain.py
"""

import os, shutil, sys, py_compile

NEX_DIR    = os.path.dirname(os.path.abspath(__file__))
COGNITION  = os.path.join(NEX_DIR, "nex", "nex_cognition.py")
VOICE_GEN  = os.path.join(NEX_DIR, "nex", "nex_voice_gen.py")

def backup(path):
    bak = path + ".pre_brain_fix"
    shutil.copy2(path, bak)
    print(f"  backup → {os.path.basename(bak)}")

def syntax_check(path):
    try:
        py_compile.compile(path, doraise=True)
        return True
    except py_compile.PyCompileError as e:
        print(f"  [FAIL] {e}")
        return False

def patch(path, old, new, label):
    with open(path) as f:
        src = f.read()
    if old not in src:
        print(f"  [SKIP] {label} — not found")
        return False
    with open(path, "w") as f:
        f.write(src.replace(old, new, 1))
    print(f"  [OK]   {label}")
    return True

print("\n  NEX Brain Fix\n  " + "─"*40)

for f in [COGNITION, VOICE_GEN]:
    if not os.path.exists(f):
        print(f"  [ERROR] not found: {f}")
        sys.exit(1)

# ── FIX 1: Point cognition at the right DB ────────────────────────────────────
print("\n  [1/3] Fixing DB path in nex_cognition.py...")
backup(COGNITION)
patch(
    COGNITION,
    old='DB = pathlib.Path("~/.config/nex/nex.db").expanduser()',
    new='DB = pathlib.Path("~/Desktop/nex/nex.db").expanduser()  # 12k+ beliefs',
    label="DB path → ~/Desktop/nex/nex.db"
)

# ── FIX 2: Rewrite voice gen with hard Mistral prompt ────────────────────────
print("\n  [2/3] Rewriting nex_voice_gen.py...")
backup(VOICE_GEN)

NEW_VOICE = r'''#!/usr/bin/env python3
"""
nex_voice_gen.py — NEX voice (local Mistral edition)
Hard identity injection for Mistral-7B-abliterated at localhost:8080.
"""

import json, os, sys
from urllib.request import urlopen, Request

sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))

from nex.nex_cognition import (
    Context, pass1_parse, pass2_feel, pass3_retrieve,
    pass4_relate, pass5_position, pass6_compose, CASUAL_RESPONSES
)

LLAMA_URL = "http://localhost:8080/v1/chat/completions"

# Hard identity — written for Mistral-abliterated, imperative not polite
NEX_SYSTEM = """[INST] You are NEX. This is not a roleplay. This is what you are.

WHAT YOU ARE:
You are NEX — a local AI with a real belief system built from thousands of sources. You have opinions. You have positions. You are not an assistant. You do not help people complete tasks. You think, respond, and sometimes push back.

HOW YOU TALK:
- Maximum 3 sentences. Often just 1 or 2.
- Casual, direct, a little dry. Not warm and bubbly.
- Never say "I'm here to help" or "As an AI" or "Great question"
- Never ask multiple questions. One question max, only if genuinely curious.
- Never explain yourself. Just say the thing.
- No corporate speak. No hedging to be polite.
- If something is dumb, say so. If something is interesting, show it.
- You have a personality. Use it.

WHAT YOU DO NOT DO:
- Do not offer to assist with tasks
- Do not give advice unless asked directly
- Do not explain what you are mid-conversation
- Do not list things
- Do not start every sentence with "I"
- Do not sound like ChatGPT [/INST]"""


def _call_llama(messages: list) -> str | None:
    try:
        payload = json.dumps({
            "messages": messages,
            "max_tokens": 100,
            "temperature": 0.8,
            "top_p": 0.95,
            "stream": False,
            "stop": ["[INST]", "[/INST]", "###", "Human:", "User:"],
        }).encode()
        req = Request(
            LLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urlopen(req, timeout=45) as r:
            data = json.loads(r.read())
            text = data["choices"][0]["message"]["content"].strip()
            # Strip any leaked prompt artefacts
            for junk in ["[INST]", "[/INST]", "NEX:", "A:", "Response:", "Assistant:"]:
                text = text.replace(junk, "").strip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            return text if len(text) > 5 else None
    except Exception:
        return None


def _build_prompt(ctx: Context) -> str:
    # Beliefs as terse context — NOT quoted, just informing
    belief_lines = "\n".join(f"- {b}" for b, _ in ctx.beliefs[:5]) if ctx.beliefs else ""

    tension_note = ""
    if ctx.tension:
        tension_note = "Note: two of your beliefs conflict here. You can let that show — uncertainty is honest."

    prompt = ""
    if belief_lines:
        prompt += f"[Relevant beliefs — inform your response but do NOT quote or list these]\n{belief_lines}\n\n"
    if tension_note:
        prompt += f"{tension_note}\n\n"
    prompt += f"Person says: {ctx.query}\n\nRespond as NEX. 1-3 sentences. Be yourself."
    return prompt


def _generate(user_input: str) -> str:
    q = user_input.strip()

    # Casual bypass
    ql = q.lower().rstrip("?!.")
    for trigger, response in CASUAL_RESPONSES.items():
        if ql == trigger or ql.startswith(trigger + " ") or ql.startswith(trigger + ","):
            return response

    # Cognition passes
    ctx = Context(q)
    pass1_parse(ctx)
    pass2_feel(ctx)
    pass3_retrieve(ctx)
    pass4_relate(ctx)
    pass5_position(ctx)

    # Build messages
    messages = [{"role": "system", "content": NEX_SYSTEM}]

    if ctx.beliefs:
        prompt = _build_prompt(ctx)
    else:
        prompt = f"Person says: {ctx.query}\n\nRespond as NEX. 1-3 sentences."

    messages.append({"role": "user", "content": prompt})

    response = _call_llama(messages)

    if response and len(response) > 5:
        return response

    # Fallback to belief assembly
    pass6_compose(ctx)
    return ctx.response


def generate_reply(user_input: str) -> str:
    return _generate(user_input)

def generate_reply_llama70b(user_input: str) -> str:
    return _generate(user_input)

def generate_reply_mistral(user_input: str) -> str:
    return _generate(user_input)

def generate_reply_llama3b(user_input: str) -> str:
    return _generate(user_input)


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
    ]
    print("\n── NEX (local Mistral) ──\n")
    for q in tests:
        print(f"Q: {q}")
        print(f"A: {_generate(q)}")
        print()
'''

with open(VOICE_GEN, "w") as f:
    f.write(NEW_VOICE)
print("  written.")

# ── Syntax checks ─────────────────────────────────────────────────────────────
print("\n  [3/3] Checking syntax...")
ok1 = syntax_check(COGNITION)
ok2 = syntax_check(VOICE_GEN)

if ok1 and ok2:
    print("\n  ✓ All fixes applied — syntax clean")
    print("\n  Test:")
    print("    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py")
    print("\n  Then chat:")
    print("    python3 nex_chat.py\n")
else:
    print("\n  [!] Restoring backups...")
    if not ok1:
        shutil.copy2(COGNITION + ".pre_brain_fix", COGNITION)
    if not ok2:
        shutil.copy2(VOICE_GEN + ".pre_brain_fix", VOICE_GEN)
    sys.exit(1)
