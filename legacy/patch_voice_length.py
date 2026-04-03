#!/usr/bin/env python3
"""
patch_voice_length.py — targeted fix
  1. n_predict 160 → 220   (stops mid-sentence cuts)
  2. truncator drops incomplete final sentences
  3. max_s 5 → 5 (kept) but with cleaner guard
"""

import os, re, shutil, subprocess, sys

VG = os.path.expanduser("~/Desktop/nex/nex/nex_voice_gen.py")

if not os.path.exists(VG):
    print(f"Not found: {VG}"); sys.exit(1)

bak = VG + ".pre_length_patch"
if not os.path.exists(bak):
    shutil.copy2(VG, bak)
    print(f"  backup → {os.path.basename(bak)}")

with open(VG) as f:
    src = f.read()

# Fix 1: raise token cap
old1 = '"n_predict": 160,'
new1 = '"n_predict": 220,'
if old1 in src:
    src = src.replace(old1, new1)
    print("  [OK] n_predict → 220")
else:
    print("  [SKIP] n_predict pattern not found")

# Fix 2: replace truncator with one that drops incomplete sentences
OLD_TRUNC = '''\
def _truncate(text, max_s=5):
    sentences = re.split(r"(?<=[.!?])\\s+", text.strip())
    clean = [s.strip() for s in sentences
             if s.strip()
             and not s.startswith(("Person:", "NEX:", "[", "•", "*"))
             and len(s) > 8]
    return " ".join(clean[:max_s])'''

NEW_TRUNC = '''\
def _truncate(text, max_s=5):
    text = text.strip()
    sentences = re.split(r"(?<=[.!?])\\s+", text)
    clean = []
    for s in sentences:
        s = s.strip()
        if not s: continue
        if s.startswith(("Person:", "NEX:", "[", "•", "*")): continue
        if len(s) < 8: continue
        clean.append(s)
    # drop trailing incomplete sentence (no ending punctuation)
    if clean and not re.search(r"[.!?]$", clean[-1]):
        clean = clean[:-1]
    result = " ".join(clean[:max_s])
    # if we dropped everything, return original stripped
    return result if result else text'''

if OLD_TRUNC in src:
    src = src.replace(OLD_TRUNC, NEW_TRUNC)
    print("  [OK] truncator upgraded — drops incomplete sentences")
else:
    # fallback: patch just the n_predict change was enough for token fix
    print("  [SKIP] truncator pattern not matched exactly — patching inline")
    # inject a wrapper around the truncate call instead
    src = src.replace(
        "response = _truncate(response, max_s=5)",
        "response = _truncate(response, max_s=5)\n    # drop trailing incomplete sentence\n    if response and not re.search(r'[.!?]$', response.split()[-1] if response.split() else ''):\n        sentences = re.split(r'(?<=[.!?])\\s+', response)\n        complete = [s for s in sentences if re.search(r'[.!?]$', s.strip())]\n        if complete: response = ' '.join(complete)"
    )

with open(VG, "w") as f:
    f.write(src)

r = subprocess.run([sys.executable, "-m", "py_compile", VG], capture_output=True)
if r.returncode != 0:
    print(f"  SYNTAX FAIL:\n{r.stderr.decode()}")
    shutil.copy2(bak, VG)
    print("  rolled back")
    sys.exit(1)

print("  [OK] syntax clean")
print("\n  ✓ Done. Test:")
print("    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py")
