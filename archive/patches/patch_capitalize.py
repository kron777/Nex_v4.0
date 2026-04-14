#!/usr/bin/env python3
"""
patch_capitalize.py
───────────────────
Fixes responses that start with lowercase after opener phrases were stripped.
Capitalizes the first character of every response before returning it.

Run from ~/Desktop/nex:
    python3 patch_capitalize.py
"""

import os, re, shutil, subprocess, sys

NEX_DIR   = os.path.expanduser("~/Desktop/nex")
VOICE_GEN = os.path.join(NEX_DIR, "nex", "nex_voice_gen.py")

def backup(path):
    dst = path + ".pre_capitalize"
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
    print(f"  backup -> {os.path.basename(dst)}")

def syntax_ok(path):
    r = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode())
    return r.returncode == 0

print("\n  Fix: capitalize first char of response\n")

with open(VOICE_GEN, "r") as f:
    src = f.read()

backup(VOICE_GEN)

# ── Inject a _cap() helper near the top of the file ──────────────────────────
CAP_HELPER = '''
def _cap(s):
    """Capitalize first character without lowercasing the rest."""
    s = s.strip()
    return s[0].upper() + s[1:] if s else s

'''

if "def _cap(" not in src:
    # Insert after the first function definition or after imports
    src = re.sub(
        r'(def _var_random\([^)]*\):)',
        CAP_HELPER + r'\1',
        src, count=1
    )
    if "def _cap(" not in src:
        # Fallback: insert after import block
        src = re.sub(
            r'(^import [^\n]+\n)',
            r'\1' + CAP_HELPER,
            src, count=1, flags=re.MULTILINE
        )
    print("  [OK] _cap() helper injected")
else:
    print("  [OK] _cap() already present")

# ── Wrap the final return in generate_reply with _cap() ──────────────────────
patched = False

# Pattern 1: return response  (at end of generate_reply)
new_src = re.sub(
    r'(\n    return )(_cap\()?response\)?(\s*\n)',
    r'\n    return _cap(response)\3',
    src, count=1
)
if new_src != src:
    src = new_src
    patched = True
    print("  [OK] generate_reply return wrapped with _cap()")

# Pattern 2: ctx.response is returned directly
if not patched:
    new_src = re.sub(
        r'(\n    return )(_cap\()?ctx\.response\)?(\s*\n)',
        r'\n    return _cap(ctx.response)\3',
        src, count=1
    )
    if new_src != src:
        src = new_src
        patched = True
        print("  [OK] ctx.response return wrapped with _cap()")

# Pattern 3: wrap the result variable just before it's returned in _compose
if not patched:
    new_src = re.sub(
        r'(\n    return )(_cap\()?result\)?(\s*\n)',
        r'\n    return _cap(result)\3',
        src, count=1
    )
    if new_src != src:
        src = new_src
        patched = True
        print("  [OK] _compose result wrapped with _cap()")

if not patched:
    # Last resort: find the final return in the file's last function
    # and wrap whatever variable is returned
    src = re.sub(
        r'(    return )([a-z_]+)(\s*\n(?!\s*def|\s*#))',
        r'\1_cap(\2)\3',
        src, count=1
    )
    print("  [OK] last return in file wrapped with _cap() (fallback)")

# ── Also capitalize at the _compose level as a belt-and-braces fix ───────────
# Find where result is assembled and capitalize it there too
if "result = _cap(" not in src:
    src = re.sub(
        r'(\n    result = result\.replace\([^)]+\)\.strip\(\))',
        r'\1\n    result = _cap(result)',
        src, count=1
    )
    if "result = _cap(" not in src:
        src = re.sub(
            r'(\n    result = (?!_cap).*?\.strip\(\))',
            r'\1\n    result = _cap(result)',
            src, count=1
        )
    print("  [OK] result capitalized in _compose")

# ── write & verify ────────────────────────────────────────────────────────────
with open(VOICE_GEN, "w") as f:
    f.write(src)

if syntax_ok(VOICE_GEN):
    print("  [OK] syntax clean\n")
else:
    shutil.copy2(VOICE_GEN + ".pre_capitalize", VOICE_GEN)
    print("  [FAIL] syntax error -- backup restored\n")
    sys.exit(1)

print("  Done\n")
print("  Test:")
print("    rm -f ~/Desktop/nex/.semantic_cache*.pkl")
print("    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py\n")
