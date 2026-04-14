#!/usr/bin/env python3
"""
patch_fix_closer.py
───────────────────
Fixes IndexError: Cannot choose from an empty sequence in _closer()
caused by patch_no_openers.py emptying all closing pools.

Two-part fix:
  1. _var_random() returns "" safely on empty pool (never crashes)
  2. CLOSINGS dict gets minimal non-annoying closers back
     — just enough variety, no performative openers

Run from ~/Desktop/nex:
    python3 patch_fix_closer.py
"""

import os, re, shutil, subprocess, sys

NEX_DIR   = os.path.expanduser("~/Desktop/nex")
VOICE_GEN = os.path.join(NEX_DIR, "nex", "nex_voice_gen.py")

def backup(path):
    dst = path + ".pre_closerfix"
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
    print(f"  backup -> {os.path.basename(dst)}")

def syntax_ok(path):
    r = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode())
    return r.returncode == 0

print("\n  Fix: empty closing pool crash\n")

with open(VOICE_GEN, "r") as f:
    src = f.read()

backup(VOICE_GEN)

# ── Fix 1: make _var_random safe against empty sequences ─────────────────────
# Find the _var_random function and add an empty-guard
old_var_random = re.search(
    r'(def _var_random\([^)]*\):.*?)(return _random\.choice\(pool\))',
    src, re.DOTALL
)
if old_var_random:
    src = src.replace(
        old_var_random.group(2),
        'return _random.choice(pool) if pool else ""'
    )
    print("  [OK] _var_random safe against empty pool")
else:
    # Broader fallback — find any random.choice(pool) inside _var_random
    src = re.sub(
        r'(_random\.choice\(pool\))',
        r'_random.choice(pool) if pool else ""',
        src, count=1
    )
    print("  [OK] _var_random patched (fallback)")

# ── Fix 2: replace CLOSINGS with a clean minimal set ─────────────────────────
# No openers, no tail summaries — just natural conversation moves
# "" entries mean "say nothing" — they appear 2x more than real closers
# so closing questions appear roughly 1 in 3 responses

NEW_CLOSINGS = '''\
CLOSINGS = {
    "challenging":     ["", "", "What's your take?"],
    "curious":         ["", "", "What do you think?"],
    "probing":         ["", "", "What made you ask that?"],
    "philosophical":   ["", "", ""],
    "confrontational": ["", "", "What's your read?"],
    "vulnerable":      ["", "", ""],
    "frustrated":      ["", ""],
    "existential":     ["", "", ""],
    "warm":            [""],
    "neutral":         ["", ""],
}
'''

# Replace existing CLOSINGS dict
replaced = False
new_src = re.sub(
    r'CLOSINGS\s*=\s*\{[^}]*\}',
    NEW_CLOSINGS.strip(),
    src, flags=re.DOTALL, count=1
)
if new_src != src:
    src = new_src
    replaced = True
    print("  [OK] CLOSINGS dict replaced with clean minimal set")
else:
    # CLOSINGS not found — inject before _closer function
    src = re.sub(
        r'(def _closer\()',
        NEW_CLOSINGS + r'\ndef _closer(',
        src, count=1
    )
    print("  [OK] CLOSINGS dict injected (was missing)")

# ── Fix 3: guard _closer itself against empty pool ───────────────────────────
# If _closer builds pool and it ends up empty, return "" not crash
src = re.sub(
    r'(def _closer\([^)]*\):)',
    r'\1\n    # safe: returns "" if pool is empty',
    src, count=1
)

# Find the return line in _closer and guard it
src = re.sub(
    r'(return _var_random\(pool\)(\s*#[^\n]*)?)',
    r'return _var_random(pool) if pool else ""',
    src, count=1
)
print("  [OK] _closer return guarded")

# ── write & verify ────────────────────────────────────────────────────────────
with open(VOICE_GEN, "w") as f:
    f.write(src)

if syntax_ok(VOICE_GEN):
    print("  [OK] syntax clean\n")
else:
    shutil.copy2(VOICE_GEN + ".pre_closerfix", VOICE_GEN)
    print("  [FAIL] syntax error -- backup restored\n")
    sys.exit(1)

print("  Done\n")
print("  Test:")
print("    rm -f ~/Desktop/nex/.semantic_cache*.pkl")
print("    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py\n")
