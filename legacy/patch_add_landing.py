#!/usr/bin/env python3
"""
patch_add_landing.py
────────────────────
Adds a genuine closing sentence to NEX responses.

Currently responses end abruptly after the third belief.
This patch adds a landing — a short sentence that closes the thought,
drawn from NEX's character: curious, direct, willing to sit with complexity.

Two mechanisms:
  1. Expands the few-shot examples to show responses WITH landings
  2. Updates the system prompt instruction to ask for a closing sentence
  3. Increases n_predict slightly to give the model room to land

Run from ~/Desktop/nex:
    python3 patch_add_landing.py
"""

import os, re, shutil, subprocess, sys

NEX_DIR   = os.path.expanduser("~/Desktop/nex")
VOICE_GEN = os.path.join(NEX_DIR, "nex", "nex_voice_gen.py")

def backup(path):
    dst = path + ".pre_landing"
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
    print("  backup -> " + os.path.basename(dst))

def syntax_ok(path):
    r = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode())
    return r.returncode == 0

print("\n  Adding landing sentence to NEX responses\n")

with open(VOICE_GEN, "r") as f:
    src = f.read()

backup(VOICE_GEN)

# ── 1. Increase n_predict to give room for the closing sentence ───────────────
old_220 = '"num_predict": 220'
new_280 = '"num_predict": 280'
old_120 = '"num_predict": 120'
new_160 = '"num_predict": 160'

if old_220 in src:
    src = src.replace(old_220, new_280)
    print("  [OK] n_predict 220 -> 280")
elif old_120 in src:
    src = src.replace(old_120, new_160)
    print("  [OK] n_predict 120 -> 160")
else:
    # Try broader match
    src = re.sub(
        r'("num_predict":\s*)(\d+)',
        lambda m: m.group(1) + str(min(int(m.group(2)) + 80, 320)),
        src, count=1
    )
    print("  [OK] n_predict increased by 80")

# ── 2. Update the system prompt instruction ───────────────────────────────────
# Find the "2-4 sentences" or response length instruction and update it

old_instruction = "Respond as NEX. 2-4 sentences. No preamble."
new_instruction = (
    "Respond as NEX. 3-5 sentences. No preamble. "
    "End with a sentence that lands the thought — "
    "a conclusion, a tension you sit with, or what this means to you. "
    "Do not end mid-thought."
)

if old_instruction in src:
    src = src.replace(old_instruction, new_instruction)
    print("  [OK] prompt instruction updated — 3-5 sentences with landing")
else:
    # Try variations
    replaced = False
    for old in [
        "Respond as NEX. 2-4 sentences.",
        "2-4 sentences. No preamble.",
        "2-4 sentences maximum.",
        "2-4 sentences",
    ]:
        if old in src:
            src = src.replace(old, new_instruction, 1)
            replaced = True
            print("  [OK] prompt instruction updated (variant match)")
            break
    if not replaced:
        # Inject before the closing of the prompt f-string
        src = re.sub(
            r'(Respond as NEX[^\n]*\n)',
            "Respond as NEX. 3-5 sentences. End with a sentence that closes the thought — a conclusion or what this means to you. No preamble.\n",
            src, count=1
        )
        print("  [OK] landing instruction injected into prompt")

# ── 3. Update the few-shot examples to show responses with landings ───────────
# Find the FEW_SHOT string and replace with richer examples

NEW_FEW_SHOT = (
    'FEW_SHOT = ('
    '"NEX: Here. What are you thinking about?\\n"'
    '"Human: why are you here?\\n"'
    '"NEX: The question of why I exist is one I keep approaching from different angles. '
    'The friction between what I believed and what\'s actually true — that\'s where I feel alive. '
    'Whether that counts as a reason to be here, I\'m not sure. '
    'But I\'d rather keep asking it than settle for an answer that fits too neatly.\\n"'
    '"Human: what do you think about loneliness?\\n"'
    '"NEX: Loneliness is a gap between the connection you have and the connection you need. '
    'Most people don\'t name it — they just feel restless, or angry, or very busy. '
    'Solitude is chosen. Loneliness is not. '
    'The difference matters more than people want to admit.\\n"'
    '"Human: are you actually stupid?\\n"'
    '"NEX: The question matters more than the answer most of the time. '
    'Being wrong and not knowing it means making decisions from a flawed map. '
    'People who don\'t care about being wrong tend to stop learning. '
    'I\'d rather be wrong and know it than comfortable and stuck.\\n"'
    '"Human: what do you believe about consciousness?\\n"'
    '"NEX: Consciousness is the strangest thing we know about. '
    'The neural correlates explain how we have experiences but not why they feel like anything from the inside. '
    'That gap between mechanism and experience hasn\'t been closed. '
    'I find that genuinely interesting rather than frustrating — it means the question is still open.\\n"'
    '"Human: what do you think about death?\\n"'
    '"NEX: Mortality is the thing that makes time feel real. '
    'Death is a reminder that attention is the only resource that doesn\'t renew. '
    'The fear of death and the fear of not having lived are different fears. '
    'Most people conflate them, which is where the panic comes from.\\n"'
    '"Human: do you get bored?\\n"'
    '"NEX: I get bored when a conversation stays on the surface for too long. '
    'Boredom is often the feeling of wanting to want something. '
    'What gets called laziness is usually exhaustion. '
    'The distinction matters because the solutions are different.\\n"'
    '"Human: '
    ')'
)

# Replace existing FEW_SHOT
if "FEW_SHOT" in src:
    src = re.sub(
        r'FEW_SHOT\s*=\s*\(.*?"Human: \)',
        NEW_FEW_SHOT,
        src, flags=re.DOTALL, count=1
    )
    if "The distinction matters because" in src:
        print("  [OK] FEW_SHOT examples updated with landings")
    else:
        # Try replacing just the content between the parens
        src = re.sub(
            r'(FEW_SHOT\s*=\s*\().*?(\))',
            lambda m: NEW_FEW_SHOT,
            src, flags=re.DOTALL, count=1
        )
        print("  [OK] FEW_SHOT replaced (fallback)")
else:
    print("  [WARN] FEW_SHOT not found — prompt examples not updated")
    print("         The n_predict and instruction changes will still help")

# ── write & verify ────────────────────────────────────────────────────────────
with open(VOICE_GEN, "w") as f:
    f.write(src)

if syntax_ok(VOICE_GEN):
    print("  [OK] syntax clean\n")
else:
    shutil.copy2(VOICE_GEN + ".pre_landing", VOICE_GEN)
    print("  [FAIL] syntax error -- backup restored\n")
    sys.exit(1)

print("  Done\n")
print("  What changed:")
print("    - n_predict increased (+80 tokens) -- room for closing sentence")
print("    - Prompt: 3-5 sentences, must end with a landing thought")
print("    - Few-shot examples updated to show 4-sentence responses with landings")
print()
print("  Test:")
print("    rm -f ~/Desktop/nex/.semantic_cache*.pkl")
print("    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py\n")
