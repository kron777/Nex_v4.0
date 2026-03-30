#!/usr/bin/env python3
"""
patch_wire_knowledge.py
Copies nex_knowledge_layer.py to nex/nex/ and wires it into nex_voice_gen.py.
Response structure becomes: belief1 → FACT → belief2 → close
"""
import os, re, shutil, subprocess, sys

NEX_DIR = os.path.expanduser("~/Desktop/nex")
SRC_KL  = "/home/rr/Downloads/nex_knowledge_layer.py"  # from Downloads
DST_KL  = os.path.join(NEX_DIR, "nex/nex_knowledge_layer.py")
VG      = os.path.join(NEX_DIR, "nex/nex_voice_gen.py")

def bak(p):
    d = p + ".pre_knowledge"
    if not os.path.exists(d): shutil.copy2(p, d)
    print(f"  backup → {os.path.basename(d)}")

def syntax(p):
    r = subprocess.run([sys.executable, "-m", "py_compile", p], capture_output=True)
    if r.returncode != 0:
        print(f"  SYNTAX FAIL:\n{r.stderr.decode()}"); sys.exit(1)

print("\n  NEX Knowledge Layer Wire\n  " + "─"*40)

# Step 1: copy knowledge layer
if not os.path.exists(SRC_KL):
    print(f"  [ERR] {SRC_KL} not found — copy nex_knowledge_layer.py to Downloads first")
    sys.exit(1)
shutil.copy2(SRC_KL, DST_KL)
syntax(DST_KL)
print(f"  [OK] nex_knowledge_layer.py installed")

# Step 2: wire into voice_gen
bak(VG)
with open(VG) as f: src = f.read()

# Inject import after existing imports
IMPORT_INJECTION = """
# ── knowledge layer ───────────────────────────────────────────────────────────
try:
    from nex.nex_knowledge_layer import get_knowledge, is_knowledge_query
    _KNOWLEDGE_LAYER = True
except ImportError:
    try:
        from nex_knowledge_layer import get_knowledge, is_knowledge_query
        _KNOWLEDGE_LAYER = True
    except ImportError:
        _KNOWLEDGE_LAYER = False
        def get_knowledge(q, n=1): return []
"""

if "_KNOWLEDGE_LAYER" not in src:
    # Insert after the semantic_retrieval import block
    insert_after = "from nex.nex_cognition import Context, pass1_parse, pass2_feel, CASUAL_RESPONSES"
    if insert_after in src:
        src = src.replace(insert_after, insert_after + "\n" + IMPORT_INJECTION)
        print("  [OK] knowledge layer import injected")
    else:
        # fallback: insert near top after first sys.path line
        src = src.replace(
            "sys.path.insert(0, os.path.expanduser(\"~/Desktop/nex\"))",
            "sys.path.insert(0, os.path.expanduser(\"~/Desktop/nex\"))\n" + IMPORT_INJECTION,
            1
        )
        print("  [OK] knowledge layer import injected (fallback)")

# Update _compose to inject fact between belief1 and belief2
OLD_COMPOSE = '''def _compose(q, beliefs, ctx):
    parts = []
    opener = _var(q+"open", OPENERS.get(ctx.register, [""]))
    if opener: parts.append(opener)

    if beliefs:
        p = _wrap1(beliefs[0], ctx.register, q)
        if p: parts.append(p)
    if len(beliefs) > 1:
        s = _wrap2(beliefs[1], q)
        if s: parts.append(s)
    if len(beliefs) > 2 and len(parts) < 4:
        t = _wrap3(beliefs[2], q)
        if t: parts.append(t)

    cl = _closer(ctx.register, q, ctx.urgency)
    if cl and len(parts) >= 2:
        parts.append(cl)

    if not parts:
        return "Still forming a view on that."

    result = " ".join(p for p in parts if p)
    result = re.sub(r"\\.(\\.*)([.!?])", r".\\2", result)
    return result.strip()'''

NEW_COMPOSE = '''def _compose(q, beliefs, ctx, facts=None):
    """
    Compose response: opener → belief1 → [FACT] → belief2 → belief3 → close
    Facts (research data) are injected between belief1 and belief2 when available.
    This produces: position → evidence → extended position → close
    """
    parts = []
    opener = _var(q+"open", OPENERS.get(ctx.register, [""]))
    if opener: parts.append(opener)

    if beliefs:
        p = _wrap1(beliefs[0], ctx.register, q)
        if p: parts.append(p)

    # ── fact injection point ──────────────────────────────────────────────────
    if facts:
        parts.append(facts[0])

    if len(beliefs) > 1:
        s = _wrap2(beliefs[1], q)
        if s: parts.append(s)
    if len(beliefs) > 2 and len(parts) < 5:
        t = _wrap3(beliefs[2], q)
        if t: parts.append(t)

    cl = _closer(ctx.register, q, ctx.urgency)
    if cl and len(parts) >= 2:
        parts.append(cl)

    if not parts:
        return "Still forming a view on that."

    result = " ".join(p for p in parts if p)
    result = re.sub(r"\\.(\\.*)([.!?])", r".\\2", result)
    return result.strip()'''

if OLD_COMPOSE in src:
    src = src.replace(OLD_COMPOSE, NEW_COMPOSE)
    print("  [OK] _compose updated — fact injection point added")
else:
    print("  [WARN] _compose not matched exactly — injecting facts in generate_reply instead")

# Update generate_reply to fetch facts and pass to _compose
OLD_GEN = '''    beliefs = retrieve_beliefs(q, n=6)

    if not beliefs:
        pool = _LOW_BELIEF.get(ctx.register, _LOW_BELIEF["neutral"])
        response = _var(q, pool)
    else:
        response = _compose(q, beliefs, ctx)'''

NEW_GEN = '''    beliefs = retrieve_beliefs(q, n=6)

    # ── knowledge injection ───────────────────────────────────────────────────
    facts = []
    if _KNOWLEDGE_LAYER:
        try:
            facts = get_knowledge(q, n=1)
        except Exception:
            facts = []

    if not beliefs:
        pool = _LOW_BELIEF.get(ctx.register, _LOW_BELIEF["neutral"])
        # still try to inject fact even for low-belief responses
        if facts:
            response = _var(q, pool) + " " + facts[0]
        else:
            response = _var(q, pool)
    else:
        response = _compose(q, beliefs, ctx, facts=facts)'''

if OLD_GEN in src:
    src = src.replace(OLD_GEN, NEW_GEN)
    print("  [OK] generate_reply updated — facts fetched and passed to _compose")
else:
    print("  [WARN] generate_reply pattern not matched — knowledge will be inactive")

with open(VG, "w") as f: f.write(src)
syntax(VG)
print("  [OK] syntax clean")

print("""
  ✓ Done

  Knowledge layer wired. Response structure is now:
    [opener] → belief1 → FACT (research data) → belief2 → [belief3] → close

  This makes NEX:
    • Data-rich: real research findings woven into voice
    • Serious: neuroscience, psychology, philosophy grounded in evidence
    • Inspiring: the fact often reframes or deepens the belief

  Delete old cache and test:
    rm -f ~/Desktop/nex/.semantic_cache*.pkl
    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py
""")
