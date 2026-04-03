#!/usr/bin/env python3
"""
patch_fix_i_v2.py
─────────────────
Fixes standalone lowercase 'i' in NEX responses.
Direct string replacement approach — no regex injection into other files.

Run from ~/Desktop/nex:
    python3 patch_fix_i_v2.py
"""

import os, re, shutil, subprocess, sys

NEX_DIR   = os.path.expanduser("~/Desktop/nex")
VOICE_GEN = os.path.join(NEX_DIR, "nex", "nex_voice_gen.py")

def backup(path):
    dst = path + ".pre_ifix2"
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
    print("  backup -> " + os.path.basename(dst))

def syntax_ok(path):
    r = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode())
    return r.returncode == 0

print("\n  Fix: lowercase i in responses\n")

with open(VOICE_GEN, "r") as f:
    src = f.read()

backup(VOICE_GEN)

# ── The _fix_i function we want to inject (as a plain string, no escapes) ─────

fix_i_code = (
    "\n\n"
    "def _fix_i(s):\n"
    "    \"\"\"Fix standalone lowercase i after connectors and punctuation.\"\"\"\n"
    "    import re as _re\n"
    "    # i after em-dash or colon+space\n"
    "    s = _re.sub(r'([\\u2014\\u2013\\-]{1,2}\\s+)i\\b', lambda m: m.group(1) + 'I', s)\n"
    "    s = _re.sub(r'(:\\s+)i\\b', lambda m: m.group(1) + 'I', s)\n"
    "    # i after period+space mid-sentence\n"
    "    s = _re.sub(r'(\\.\\s+)i\\b', lambda m: m.group(1) + 'I', s)\n"
    "    return s\n"
    "\n"
)

# Inject after the _cap function definition
if "_fix_i" not in src:
    # Find end of _cap function — look for its return statement
    cap_match = re.search(r"def _cap\(s\):.*?return[^\n]+\n", src, re.DOTALL)
    if cap_match:
        insert_pos = cap_match.end()
        src = src[:insert_pos] + fix_i_code + src[insert_pos:]
        print("  [OK] _fix_i() injected after _cap()")
    else:
        # Fallback: inject before generate_reply
        src = re.sub(
            r"(\ndef generate_reply\()",
            fix_i_code + r"\1",
            src, count=1
        )
        print("  [OK] _fix_i() injected before generate_reply()")
else:
    print("  [OK] _fix_i() already present")

# ── Wire _fix_i into _cap so it runs on every response ───────────────────────
if "_fix_i" in src:
    # Update _cap to call _fix_i first
    src = re.sub(
        r"def _cap\(s\):\n([^\n]*\n)*?    return s\[0\]\.upper\(\)",
        lambda m: m.group(0).replace(
            "    return s[0].upper()",
            "    s = _fix_i(s)\n    return s[0].upper()"
        ),
        src, count=1
    )
    # Check if it worked
    if "_fix_i(s)" in src:
        print("  [OK] _fix_i() wired into _cap()")
    else:
        # Direct approach: replace the return line in _cap
        src = src.replace(
            "    return s[0].upper() + s[1:] if s else s",
            "    s = _fix_i(s)\n    return s[0].upper() + s[1:] if s else s"
        )
        if "_fix_i(s)" in src:
            print("  [OK] _fix_i() wired into _cap() (direct replace)")
        else:
            print("  [WARN] could not wire _fix_i into _cap — wiring into generate_reply instead")
            src = src.replace(
                "return _cap(response)",
                "return _cap(_fix_i(response))"
            )
            src = src.replace(
                "return _cap(result)",
                "return _cap(_fix_i(result))"
            )

# ── write & verify ────────────────────────────────────────────────────────────
with open(VOICE_GEN, "w") as f:
    f.write(src)

if syntax_ok(VOICE_GEN):
    print("  [OK] syntax clean\n")
else:
    shutil.copy2(VOICE_GEN + ".pre_ifix2", VOICE_GEN)
    print("  [FAIL] syntax error -- backup restored\n")
    sys.exit(1)

print("  Done\n")
print("  Test:")
print("    rm -f ~/Desktop/nex/.semantic_cache*.pkl")
print("    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py\n")
