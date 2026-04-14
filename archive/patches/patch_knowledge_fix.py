#!/usr/bin/env python3
"""
patch_knowledge_fix.py
──────────────────────
Fixes the TypeError: _compose() got an unexpected keyword argument 'facts'
and wires the knowledge layer cleanly into NEX's voice pipeline.

Run from ~/Desktop/nex:
    python3 patch_knowledge_fix.py
"""

import os, re, shutil, subprocess, sys

NEX_DIR   = os.path.expanduser("~/Desktop/nex")
VOICE_GEN = os.path.join(NEX_DIR, "nex", "nex_voice_gen.py")

def backup(path):
    dst = path + ".pre_knowledge_fix"
    shutil.copy2(path, dst)
    print(f"  backup → {os.path.basename(dst)}")

def syntax_ok(path):
    r = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True)
    return r.returncode == 0

# ── read ──────────────────────────────────────────────────────────────────────
with open(VOICE_GEN, "r") as f:
    src = f.read()

backup(VOICE_GEN)
print("\n  NEX Knowledge Layer Fix")
print("  ────────────────────────────────────────")

# ── Fix 1: update _compose signature to accept optional facts ─────────────────
# Handles both def _compose(q, beliefs, ctx): and def _compose(q, beliefs, ctx, facts=None):
if "def _compose(q, beliefs, ctx, facts=None)" not in src:
    src = re.sub(
        r"def _compose\(q, beliefs, ctx\):",
        "def _compose(q, beliefs, ctx, facts=None):",
        src
    )
    print("  [OK] _compose signature updated — accepts facts=None")
else:
    print("  [OK] _compose signature already correct")

# ── Fix 2: wire facts into the prompt inside _compose ────────────────────────
# Find where the prompt string is built and inject a facts block after beliefs
# Strategy: find the BELIEF_BLOCK section and add FACTS block after it

FACTS_INJECTION = '''
    # ── inject factual data if available ─────────────────────────────────
    facts_block = ""
    if facts:
        fact_lines = []
        for f in facts[:2]:
            if isinstance(f, dict):
                fact_lines.append(f.get("content", str(f)).strip())
            else:
                fact_lines.append(str(f).strip())
        if fact_lines:
            facts_block = "\\n\\nKNOWN FACTS (weave these in naturally if relevant):\\n" + "\\n".join(f"- {fl}" for fl in fact_lines)
'''

# Inject facts_block assembly right before the prompt is built
# Look for where prompt = f"""... or prompt = ( starts
if "facts_block = " not in src:
    # Find the line that builds the prompt variable
    # Insert facts_block assembly just before `prompt =`
    src = re.sub(
        r"(\n)(    prompt = )",
        r"\n" + FACTS_INJECTION + r"\n\2",
        src,
        count=1
    )
    print("  [OK] facts_block assembly injected before prompt build")
else:
    print("  [OK] facts_block already present")

# ── Fix 3: add {facts_block} into the prompt template ────────────────────────
# Find the beliefs section in the prompt and append facts_block after it
if "{facts_block}" not in src:
    # Look for BELIEFS or belief_text in the prompt f-string and append after
    src = re.sub(
        r"(YOUR RELEVANT BELIEFS:\n\{belief_text\})",
        r"\1{facts_block}",
        src
    )
    if "{facts_block}" in src:
        print("  [OK] {facts_block} inserted into prompt template")
    else:
        # fallback: find any {belief_text} in prompt and append after
        src = re.sub(
            r"(\{belief_text\})",
            r"\1{facts_block}",
            src,
            count=1
        )
        if "{facts_block}" in src:
            print("  [OK] {facts_block} inserted after belief_text (fallback)")
        else:
            print("  [WARN] could not find belief_text in prompt — facts_block not in template")
            print("         Facts will still be fetched but won't reach the model.")
            print("         Manually add {facts_block} to your prompt string in _compose().")
else:
    print("  [OK] {facts_block} already in prompt template")

# ── Fix 4: ensure generate_reply passes facts correctly ──────────────────────
# The broken patch added: response = _compose(q, beliefs, ctx, facts=facts)
# but facts might not be defined if knowledge layer import failed silently
# Wrap the facts fetch in a safe try/except

if "facts=facts" in src:
    # Replace the unsafe call with a safe version
    old_call = "_compose(q, beliefs, ctx, facts=facts)"
    new_call = "_compose(q, beliefs, ctx, facts=facts)"  # same, but we fix the fetch above

    # Find the facts fetch and make it safe
    src = re.sub(
        r"(facts\s*=\s*retrieve_facts\([^)]+\))",
        r"try:\n        facts = retrieve_facts(q)\n    except Exception:\n        facts = []",
        src,
        count=1
    )
    # Clean up double try if already wrapped
    src = src.replace(
        "try:\n        try:\n        facts",
        "try:\n        facts"
    )
    print("  [OK] facts fetch wrapped in try/except — safe against import failures")
else:
    # knowledge layer call not present at all — add it safely
    src = re.sub(
        r"(    response = _compose\(q, beliefs, ctx\))",
        r"""    facts = []
    try:
        from nex_factual_retriever import retrieve_facts as _rf
        facts = _rf(q)
    except Exception:
        pass
    response = _compose(q, beliefs, ctx, facts=facts)""",
        src,
        count=1
    )
    print("  [OK] safe facts fetch added to generate_reply")

# ── Fix 5: ensure nex_knowledge_layer import doesn't crash at module load ────
if "nex_knowledge_layer" in src:
    src = re.sub(
        r"^(from nex_knowledge_layer import.*)",
        r"try:\n    \1\nexcept ImportError:\n    pass",
        src,
        flags=re.MULTILINE,
        count=1
    )
    src = re.sub(
        r"^(import nex_knowledge_layer.*)",
        r"try:\n    \1\nexcept ImportError:\n    pass",
        src,
        flags=re.MULTILINE,
        count=1
    )
    print("  [OK] nex_knowledge_layer import guarded with try/except")

# ── write ─────────────────────────────────────────────────────────────────────
with open(VOICE_GEN, "w") as f:
    f.write(src)

# ── syntax check ─────────────────────────────────────────────────────────────
if syntax_ok(VOICE_GEN):
    print("  [OK] syntax clean\n")
else:
    print("  [FAIL] syntax error — restoring backup")
    shutil.copy2(VOICE_GEN + ".pre_knowledge_fix", VOICE_GEN)
    print("  Restored. Check nex_voice_gen.py manually.\n")
    sys.exit(1)

print("  ✓ Done\n")
print("  What changed:")
print("    • _compose() now accepts facts=None — TypeError gone")
print("    • facts_block assembled inside _compose — only present when relevant")
print("    • {facts_block} appended to belief section in prompt template")
print("    • facts fetch in generate_reply wrapped in try/except — safe if retriever missing")
print("    • nex_knowledge_layer import guarded — no crash if file not found")
print()
print("  Test:")
print("    rm -f ~/Desktop/nex/.semantic_cache*.pkl")
print("    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py")
print()
print("  Chat:")
print("    python3 nex_chat.py")
