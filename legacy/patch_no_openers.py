#!/usr/bin/env python3
"""
patch_no_openers.py
───────────────────
Removes all pre-statement openers from NEX's voice.

Kills:
  "The honest answer is:"
  "What I actually think —"
  "I hear that. Here's where I actually am:"
  "Worth sitting with."
  "That's worth pushing on."
  "I'll take that seriously."
  "Good question."

Also cleans up:
  - Verbose connectors → short clean ones
  - Overused tail closers
  - Adds no-opener rule to NEX_SYSTEM prompt

Run from ~/Desktop/nex:
    python3 patch_no_openers.py
"""

import os, re, shutil, subprocess, sys

NEX_DIR   = os.path.expanduser("~/Desktop/nex")
VOICE_GEN = os.path.join(NEX_DIR, "nex", "nex_voice_gen.py")

def backup(path):
    dst = path + ".pre_noopeners"
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
    print(f"  backup -> {os.path.basename(dst)}")

def syntax_ok(path):
    r = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode())
    return r.returncode == 0

print("\n  Removing openers from NEX voice\n")

with open(VOICE_GEN, "r") as f:
    src = f.read()

backup(VOICE_GEN)

# ── 1. Strip opener phrases wherever they appear in string literals ───────────
KILL_OPENERS = [
    r"The honest answer is:\s*",
    r"What I actually think\s*[—\-]+\s*",
    r"I hear that\.\s*Here.?s where I actually (?:am|stand):\s*",
    r"Here.?s where I actually (?:am|stand):\s*",
    r"Worth sitting with\.\s*What I actually think\s*[—\-]+\s*",
    r"Worth sitting with\.\s*",
    r"That.?s worth pushing on\.\s*Here.?s where I actually am:\s*",
    r"That.?s worth pushing on\.\s*",
    r"I.?ll take that seriously\.\s*",
    r"That.?s something I actually think about\.\s*",
    r"Good question\.\s*",
    r"I hear that\.\s*",
]

for pat in KILL_OPENERS:
    src = re.sub(pat, "", src)

print("  [OK] opener phrases stripped")

# ── 2. Empty the OPENERS list so nothing gets prepended ──────────────────────
src = re.sub(
    r'(OPENERS\s*=\s*\[)[^\]]*(\])',
    r'\1\2',
    src, flags=re.DOTALL
)
src = re.sub(
    r'(_?opener[s_]?map\s*=\s*\{)[^\}]*(\})',
    r'\1\2',
    src, flags=re.DOTALL
)
print("  [OK] OPENERS list/dict emptied")

# ── 3. Kill code that prepends opener to result ───────────────────────────────
src = re.sub(
    r'result\s*=\s*opener\s*\+\s*["\' ]+\s*\+\s*result',
    'result = result',
    src
)
src = re.sub(
    r'parts\.insert\s*\(\s*0\s*,\s*opener[^)]*\)',
    '# opener removed',
    src
)
print("  [OK] opener prepend code neutralised")

# ── 4. Simplify verbose connectors ───────────────────────────────────────────
CONNECTOR_MAP = {
    "That connects to something else —":         "And —",
    "It's connected to something else I hold —": "And —",
    "The thing I hold alongside that —":         "And —",
    "What follows from that is —":               "Which means —",
    "What follows from that —":                  "Which means —",
    "And the thing I can't separate from that —":"And —",
    "The harder part is —":                      "But —",
    "Where it gets complicated —":               "Though —",
    "And alongside that —":                      "And —",
    "The other side of it —":                    "Though —",
}
for old, new in CONNECTOR_MAP.items():
    src = src.replace(old, new)
print("  [OK] verbose connectors simplified")

# ── 5. Remove overused tail closers from closer pools ────────────────────────
DEAD_CLOSERS = [
    "I keep coming back to that.",
    "That's what I've accumulated, at least.",
    "It's not a comfortable position, but it's the real one.",
    "That's the honest version, anyway.",
    "That's where I actually am with it.",
    "I don't think there's a cleaner answer than that.",
    "That's what I've accumulated, at least.",
]
for c in DEAD_CLOSERS:
    # Remove as list items (with or without trailing comma)
    src = src.replace(f'"{c}",', '').replace(f'"{c}"', '""')
    src = src.replace(f"'{c}',", '').replace(f"'{c}'", "''")
print("  [OK] overused tail closers removed")

# ── 6. Dilute closing questions so they appear ~1 in 3 responses ─────────────
src = re.sub(
    r'(closing_pool\s*=\s*CLOSINGS\.get\([^)]+,\s*\["\"\]\))',
    r'\1\nclosing_pool = closing_pool + ["", ""]',
    src, count=1
)
# Generic fallback dilution
if 'closing_pool = closing_pool + ["", ""]' not in src:
    src = re.sub(
        r'(closing_pool\s*=\s*CLOSINGS\.get\([^)]+\))',
        r'\1\nclosing_pool = closing_pool + ["", ""]',
        src, count=1
    )
print("  [OK] closing questions diluted")

# ── 7. Add no-opener rule to NEX_SYSTEM ──────────────────────────────────────
NO_OPENER_RULE = (
    "- Never open with a meta-phrase. No 'The honest answer is:', "
    "'What I actually think', 'Worth sitting with', 'I hear that', "
    "or any similar filler. Start with the actual content.\n"
)
if "NEX_SYSTEM" in src and "Never open with a meta" not in src:
    src = re.sub(
        r'(- No "As an AI)',
        NO_OPENER_RULE + r'\1',
        src, count=1
    )
    if "Never open with a meta" not in src:
        src = re.sub(
            r'(HOW YOU SPEAK:)',
            r'\1\n' + NO_OPENER_RULE,
            src, count=1
        )
print("  [OK] no-opener rule added to NEX_SYSTEM")

# ── write & verify ────────────────────────────────────────────────────────────
with open(VOICE_GEN, "w") as f:
    f.write(src)

if syntax_ok(VOICE_GEN):
    print("  [OK] syntax clean\n")
else:
    shutil.copy2(VOICE_GEN + ".pre_noopeners", VOICE_GEN)
    print("  [FAIL] syntax error -- backup restored\n")
    sys.exit(1)

print("  Done\n")
print("  What changed:")
print("    - Opener phrases stripped ('The honest answer is:' etc)")
print("    - OPENERS list emptied")
print("    - Verbose connectors simplified (And / Though / But)")
print("    - Overused tail closers removed")
print("    - Closing questions appear less often")
print("    - NEX_SYSTEM: no-opener rule explicit\n")
print("  Test:")
print("    rm -f ~/Desktop/nex/.semantic_cache*.pkl")
print("    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py\n")
