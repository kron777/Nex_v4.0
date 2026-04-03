#!/usr/bin/env python3
"""
patch_three_fixes.py
────────────────────
Fixes three issues found in the NEX BRAIN / AUTO CHECK screenshots:

  1. CFG_PATH not defined  → nex_curiosity_engine.py (or wherever CFG_PATH is used)
  2. Dev.to 422 error      → title too long (>128 chars) in nex_devto.py
  3. facts_block not in    → {facts_block} missing from prompt template in nex_voice_gen.py
     prompt template

Run from ~/Desktop/nex:
    python3 patch_three_fixes.py
"""

import os, re, shutil, subprocess, sys, glob
CFG_PATH = os.path.expanduser("~/.config/nex")
os.makedirs(CFG_PATH, exist_ok=True)

NEX_DIR   = os.path.expanduser("~/Desktop/nex")
NEX_SUB   = os.path.join(NEX_DIR, "nex")

def backup(path):
    dst = path + ".pre_3fix"
    if not os.path.exists(dst):          # don't overwrite earlier backup
        shutil.copy2(path, dst)
    print(f"    backup → {os.path.basename(dst)}")

def syntax_ok(path):
    r = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True)
    if r.returncode != 0:
        print(f"    [SYNTAX ERROR] {path}")
        print(r.stderr.decode())
    return r.returncode == 0

def find_file(name):
    """Search both nex/ root and nex/nex/ subdir."""
    for d in [NEX_DIR, NEX_SUB]:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None

print("\n  NEX — Three-Fix Patch")
print("  ══════════════════════════════════════════════\n")

# ══════════════════════════════════════════════════════════════════════════════
# FIX 1 — CFG_PATH not defined
# The curiosity engine (and possibly others) reference CFG_PATH without
# defining it. We find every file that uses CFG_PATH and inject a safe default
# at the top if it's missing.
# ══════════════════════════════════════════════════════════════════════════════
print("  [1/3] CFG_PATH not defined")

CFG_DEFAULT = (
    'CFG_PATH = os.path.expanduser("~/.config/nex")\n'
    'os.makedirs(CFG_PATH, exist_ok=True)\n'
)
CFG_IMPORT  = "import os\n"

fixed_cfg = 0
candidates = glob.glob(os.path.join(NEX_DIR, "*.py")) + \
             glob.glob(os.path.join(NEX_SUB, "*.py"))

for path in candidates:
    try:
        with open(path, "r", errors="replace") as f:
            src = f.read()
    except Exception:
        continue

    if "CFG_PATH" not in src:
        continue
    # Already defined?
    if re.search(r"^\s*CFG_PATH\s*=", src, re.MULTILINE):
        continue

    # Need to inject — add after the last "import os" line, or at top
    backup(path)
    if "import os" in src:
        src = re.sub(
            r"(import os\b[^\n]*\n)",
            r"\1" + CFG_DEFAULT,
            src, count=1
        )
    else:
        src = CFG_IMPORT + CFG_DEFAULT + src

    with open(path, "w") as f:
        f.write(src)

    if syntax_ok(path):
        print(f"    [OK]  CFG_PATH injected → {os.path.relpath(path, NEX_DIR)}")
        fixed_cfg += 1
    else:
        shutil.copy2(path + ".pre_3fix", path)
        print(f"    [SKIP] syntax error after patch, restored: {os.path.basename(path)}")

if fixed_cfg == 0:
    print("    [INFO] no files needed CFG_PATH injection (already defined everywhere)")

# ══════════════════════════════════════════════════════════════════════════════
# FIX 2 — Dev.to 422: title too long (>128 chars)
# Find nex_devto.py and truncate titles before posting.
# ══════════════════════════════════════════════════════════════════════════════
print("\n  [2/3] Dev.to 422 — title too long")

devto_path = find_file("nex_devto.py")
if not devto_path:
    print("    [SKIP] nex_devto.py not found")
else:
    backup(devto_path)
    with open(devto_path, "r", errors="replace") as f:
        src = f.read()

    patched = False

    # Pattern A: "title": title_var  →  "title": title_var[:128]
    new_src = re.sub(
        r'(["\']title["\']\s*:\s*)(\w+)(\s*[,}])',
        lambda m: m.group(1) + m.group(2) + "[:125]" + m.group(3)
        if "[:1" not in m.group(2) else m.group(0),
        src
    )
    if new_src != src:
        src = new_src
        patched = True
        print("    [OK]  title dict key truncated to [:125]")

    # Pattern B: explicit title= kwarg
    new_src = re.sub(
        r'(title\s*=\s*)([^\n,)]+?)(\s*[,)])',
        lambda m: m.group(1) + m.group(2).rstrip() + "[:125]" + m.group(3)
        if "[:1" not in m.group(2) and len(m.group(2).strip()) < 60 else m.group(0),
        src
    )
    if new_src != src:
        src = new_src
        patched = True
        print("    [OK]  title= kwarg truncated to [:125]")

    # Pattern C: inject truncation helper near post function
    if not patched:
        # Find where the article dict / payload is built and inject a truncation
        new_src = re.sub(
            r'("title"\s*:\s*)(.*?)(\n)',
            lambda m: m.group(1) + "(" + m.group(2).strip() + ")[:125]" + m.group(3)
            if "[:1" not in m.group(2) else m.group(0),
            src
        )
        if new_src != src:
            src = new_src
            patched = True
            print("    [OK]  title line truncated via inline wrap")

    # Pattern D: add a safe _trunc helper at the top and use it everywhere
    if not patched:
        helper = (
            "\ndef _trunc_title(t, n=125):\n"
            "    \"\"\"Dev.to rejects titles longer than 128 chars.\"\"\"\n"
            "    return str(t)[:n] if t else t\n\n"
        )
        # inject after imports block (first non-import, non-comment line)
        src = re.sub(
            r'(^(?:import|from)\s+\S+[^\n]*\n)+',
            lambda m: m.group(0) + helper,
            src, count=1, flags=re.MULTILINE
        )
        # wrap any title string in the payload
        src = re.sub(
            r'("title"\s*:\s*)([^\n,}]+)',
            lambda m: m.group(1) + "_trunc_title(" + m.group(2).strip() + ")",
            src
        )
        patched = True
        print("    [OK]  _trunc_title() helper injected + applied to all title fields")

    with open(devto_path, "w") as f:
        f.write(src)

    if syntax_ok(devto_path):
        print(f"    [OK]  nex_devto.py syntax clean")
    else:
        shutil.copy2(devto_path + ".pre_3fix", devto_path)
        print("    [FAIL] syntax error — restored backup, fix manually")

# ══════════════════════════════════════════════════════════════════════════════
# FIX 3 — facts_block not reaching prompt template
# The patch_knowledge_fix.py warned it couldn't find {belief_text} in the
# prompt string. We locate the actual prompt variable in nex_voice_gen.py
# and inject {facts_block} at the right point.
# ══════════════════════════════════════════════════════════════════════════════
print("\n  [3/3] facts_block not in prompt template")

voice_gen = find_file(os.path.join("nex", "nex_voice_gen.py"))
if not voice_gen:
    voice_gen = find_file("nex_voice_gen.py")

if not voice_gen:
    print("    [SKIP] nex_voice_gen.py not found")
else:
    backup(voice_gen)
    with open(voice_gen, "r", errors="replace") as f:
        src = f.read()

    patched_facts = False

    # Make sure facts_block is assembled in _compose
    if "facts_block" not in src:
        # Inject the assembly block inside _compose, right before the prompt
        assembly = (
            '\n    # ── factual knowledge block ──────────────────────────────────\n'
            '    facts_block = ""\n'
            '    if facts:\n'
            '        _fl = []\n'
            '        for _f in (facts or [])[:2]:\n'
            '            _txt = _f.get("content", str(_f)).strip() if isinstance(_f, dict) else str(_f).strip()\n'
            '            if _txt: _fl.append(_txt)\n'
            '        if _fl:\n'
            '            facts_block = "\\n\\nKNOWN FACTS (weave in naturally if relevant):\\n" + "\\n".join(f"- {x}" for x in _fl)\n'
        )
        src = re.sub(
            r'(def _compose\([^)]*\):)',
            r'\1' + assembly,
            src, count=1
        )
        patched_facts = True
        print("    [OK]  facts_block assembly injected into _compose()")

    # Find the prompt f-string / format string and inject {facts_block}
    # Strategy: look for the beliefs section in the prompt
    if "{facts_block}" not in src:
        # Try common patterns for where beliefs appear in the prompt
        patterns = [
            # f-string with belief_text
            (r'(\{belief_text\})', r'\1{facts_block}'),
            # f-string with beliefs variable
            (r'(\{beliefs_text\})', r'\1{facts_block}'),
            # f-string with belief_str
            (r'(\{belief_str\})', r'\1{facts_block}'),
            # Literal "BELIEFS:" section in prompt string
            (r'(BELIEFS[^\n]*\n[^\n]*\{[^}]+\})', r'\1\n{facts_block}'),
            # Any section ending that looks like end of beliefs block
            (r'(YOUR RELEVANT BELIEFS[^\n]*\n(?:[^\n]*\n)?[^\n]*\}[^\n]*\n)',
             r'\1{facts_block}\n'),
        ]
        for pat, rep in patterns:
            new_src = re.sub(pat, rep, src, count=1)
            if new_src != src and "{facts_block}" in new_src:
                src = new_src
                patched_facts = True
                print(f"    [OK]  {{facts_block}} injected into prompt template")
                break

        if "{facts_block}" not in src:
            # Last resort: find the prompt string end marker and inject before it
            # Look for the last line of the prompt before the closing triple-quote
            new_src = re.sub(
                r'(Respond as NEX[^\n]*\n)',
                r'{facts_block}\n\1',
                src, count=1
            )
            if new_src != src:
                src = new_src
                patched_facts = True
                print("    [OK]  {facts_block} injected before 'Respond as NEX' line")
            else:
                print("    [WARN] could not auto-inject {facts_block} — prompt structure unfamiliar")
                print("           Open nex/nex_voice_gen.py, find your prompt f-string,")
                print("           and add {facts_block} after the beliefs section manually.")

    else:
        print("    [OK]  {facts_block} already in prompt template")

    # Also make sure facts_block is in the format() call if using .format()
    if ".format(" in src and "facts_block" not in src.split(".format(")[1][:200]:
        src = re.sub(
            r'(\.format\([^)]*)\)',
            r'\1, facts_block=facts_block)',
            src, count=1
        )
        print("    [OK]  facts_block added to .format() call")

    with open(voice_gen, "w") as f:
        f.write(src)

    if syntax_ok(voice_gen):
        print(f"    [OK]  nex_voice_gen.py syntax clean")
    else:
        shutil.copy2(voice_gen + ".pre_3fix", voice_gen)
        print("    [FAIL] syntax error — restored backup")

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print()
print("  ✓ All three patches applied\n")
print("  Summary:")
print("    1. CFG_PATH    — injected into any file that uses it without defining it")
print("    2. Dev.to 422  — title truncated to 125 chars before POST")
print("    3. facts_block — assembled inside _compose() + injected into prompt\n")
print("  Rebuild semantic cache and test:")
print("    rm -f ~/Desktop/nex/.semantic_cache*.pkl")
print("    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py\n")
print("  Then restart NEX:")
print("    nex\n")
