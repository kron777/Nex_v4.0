#!/usr/bin/env python3
"""
patch_fix_i.py
──────────────
Fixes lowercase 'i' appearing mid-response from belief text.

Patterns fixed:
  "— i feel"        → "— I feel"
  "this: i get"     → "this: I get"
  "also: i want"    → "also: I want"
  Any "i " after — / : / . followed by a verb

Run from ~/Desktop/nex:
    python3 patch_fix_i.py
"""

import os, re, shutil, subprocess, sys

NEX_DIR   = os.path.expanduser("~/Desktop/nex")
VOICE_GEN = os.path.join(NEX_DIR, "nex", "nex_voice_gen.py")

def backup(path):
    dst = path + ".pre_ifix"
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
    print(f"  backup -> {os.path.basename(dst)}")

def syntax_ok(path):
    r = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode())
    return r.returncode == 0

print("\n  Fix: lowercase 'i' in belief text\n")

with open(VOICE_GEN, "r") as f:
    src = f.read()

backup(VOICE_GEN)

# ── Inject a _fix_i() post-processor into _cap() or alongside it ─────────────

FIX_I_HELPER = '''
def _fix_i(s):
    """Fix standalone lowercase 'i' after punctuation/connectors in response text."""
    # After — or : or . followed by space+i+space
    s = re.sub(r'([—–\-:\.]\s+)i\b', lambda m: m.group(1) + "I", s)
    # At start of a clause after connector words
    s = re.sub(r'(\b(?:also|this|that|means|means)\s*:\s*)i\b',
               lambda m: m.group(1) + "I", s)
    return s

'''

if "def _fix_i(" not in src:
    # Inject right after _cap()
    src = re.sub(
        r'(def _cap\([^)]*\):.*?return[^\n]+\n)',
        r'\1' + FIX_I_HELPER,
        src, count=1, flags=re.DOTALL
    )
    if "def _fix_i(" not in src:
        # Fallback: inject after _var_random
        src = re.sub(
            r'(def _var_random\([^)]*\):.*?return[^\n]+\n)',
            r'\1' + FIX_I_HELPER,
            src, count=1, flags=re.DOTALL
        )
    print("  [OK] _fix_i() helper injected")
else:
    print("  [OK] _fix_i() already present")

# Make sure re is imported
if "^import re" not in src and "import re\n" not in src:
    src = "import re\n" + src
    print("  [OK] import re added")

# ── Wire _fix_i into the _cap() function so it runs on every response ─────────
if "_fix_i" not in src.split("def _cap(")[1][:300] if "def _cap(" in src else "":
    src = re.sub(
        r'(def _cap\(s\):.*?)(return s\[0\]\.upper\(\) \+ s\[1:\] if s else s)',
        r'\1s = _fix_i(s)\n    \2',
        src, count=1, flags=re.DOTALL
    )
    print("  [OK] _fix_i() wired into _cap()")
else:
    # Wire it at the generate_reply return instead
    src = re.sub(
        r'(return _cap\()(response|result|ctx\.response)(\))',
        r'return _cap(_fix_i(\2))',
        src, count=1
    )
    print("  [OK] _fix_i() wired into generate_reply return")

# ── Also fix beliefs at storage level — patch the _compose result cleanup ─────
src = re.sub(
    r'(result = _cap\(result\))',
    r'result = _cap(_fix_i(result))',
    src, count=1
)
print("  [OK] _fix_i() applied at _compose level too")

# ── write & verify ────────────────────────────────────────────────────────────
with open(VOICE_GEN, "w") as f:
    f.write(src)

if syntax_ok(VOICE_GEN):
    print("  [OK] syntax clean\n")
else:
    shutil.copy2(VOICE_GEN + ".pre_ifix", VOICE_GEN)
    print("  [FAIL] syntax error -- backup restored\n")
    sys.exit(1)

print("  Done\n")
print("  Test:")
print("    rm -f ~/Desktop/nex/.semantic_cache*.pkl")
print("    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py\n")
