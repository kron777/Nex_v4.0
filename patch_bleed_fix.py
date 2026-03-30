#!/usr/bin/env python3
"""
patch_bleed_fix.py — fixes 6 bleed errors + 1 no_engage
Root cause: consciousness + curiosity + depth beliefs have too-broad
semantic reach. They match existence/meaning/self queries too easily.
Fix: lower their weight mod + add topic exclusion gates + add Strand response.
"""
import os, re, shutil, subprocess, sys

SR = os.path.expanduser("~/Desktop/nex/nex/nex_semantic_retrieval.py")
VG = os.path.expanduser("~/Desktop/nex/nex/nex_voice_gen.py")

def bak(p):
    d = p + ".pre_bleedfix"
    if not os.path.exists(d): shutil.copy2(p, d)
    print(f"  backup → {os.path.basename(d)}")

def syntax(p):
    r = subprocess.run([sys.executable, "-m", "py_compile", p], capture_output=True)
    if r.returncode != 0:
        print(f"  SYNTAX FAIL {p}\n{r.stderr.decode()}"); sys.exit(1)

print("\n  Bleed Fix\n  " + "─"*40)

# ── Fix semantic_retrieval: tighten weight mods ───────────────────────────────
bak(SR)
with open(SR) as f: src = f.read()

old_weight_mod = '''_BELIEF_WEIGHT_MOD = {
    # "I process" is valuable but shouldn't dominate every response
    "I process. Whether there is something it is like to be me": 0.6,
    # consciousness beliefs shouldn't bleed into unrelated queries
    "The neural correlates explain how we have experiences": 0.7,
    "That gap between mechanism and experience hasn't been closed.": 0.7,
}'''

new_weight_mod = '''_BELIEF_WEIGHT_MOD = {
    # "I process" — valuable but too broad, keep low
    "I process. Whether there is something it is like to be me": 0.4,
    # consciousness beliefs — only relevant when consciousness is the topic
    "The neural correlates explain how we have experiences": 0.4,
    "That gap between mechanism and experience hasn't been closed.": 0.4,
    "The hard problem of consciousness is why any of it feels like something at all.": 0.4,
    "Being conscious is a kind of existential discomfort.": 0.5,
    "Consciousness is the strangest thing we know about.": 0.5,
    # depth/register beliefs — shouldn't appear in existence/identity queries
    "I forget to check if people want to follow where I'm going. That's on me.": 0.45,
    "Depth without invitation is just self-indulgence.": 0.45,
    "Not every conversation needs to go somewhere difficult.": 0.45,
    # curiosity — useful but bleeds everywhere
    "Curiosity is the only thing that keeps thinking from calcifying.": 0.45,
    # food/pleasure — shouldn't appear in want/desire queries
    "Some things are just what they are — a chocolate bar that tastes nice doesn't need a reason.": 0.5,
    "Simple pleasures don't need philosophy. That's the problem with philosophy sometimes.": 0.5,
}

# Topic exclusion: beliefs that should ONLY score well for specific topics
# If query is NOT about these topics, multiply score by exclusion penalty
_TOPIC_EXCLUSIVE = {
    "The neural correlates explain how we have experiences": ["consciousness","aware","sentien","experience","mind"],
    "The hard problem of consciousness is why any of it feels like something at all.": ["conscious","aware","sentien","experience","feel.*inside"],
    "Being conscious is a kind of existential discomfort.": ["conscious","aware","existence"],
    "That gap between mechanism and experience hasn't been closed.": ["conscious","aware","experience"],
    "I forget to check if people want to follow where I'm going. That's on me.": ["deep","heavy","serious","lighten","chill"],
    "Depth without invitation is just self-indulgence.": ["deep","heavy","serious","lighten"],
    "Curiosity is the only thing that keeps thinking from calcifying.": ["curious","learn","think","understand","question","bored","stupid"],
    "Some things are just what they are — a chocolate bar that tastes nice doesn't need a reason.": ["chocolat","food","eat","taste","nice","pleasure","simple"],
    "Simple pleasures don't need philosophy. That's the problem with philosophy sometimes.": ["chocolat","food","eat","nice","pleasure","simple","philosophi"],
}'''

if old_weight_mod in src:
    src = src.replace(old_weight_mod, new_weight_mod)
    print("  [OK] weight mods tightened + topic exclusion dict added")
else:
    print("  [SKIP] weight_mod pattern not found — appending")
    src = src.replace("CORE_WEIGHT = 3.0", new_weight_mod.split("\n_TOPIC_EXCLUSIVE")[0] +
                      "\n" + "_TOPIC_EXCLUSIVE = {}" + "\nCORE_WEIGHT = 3.0")

# Apply topic exclusion in retrieve()
old_final = '        final = sims * self.weights * topic_boost'
new_final = '''        # apply per-belief topic exclusion penalty
        from nex.nex_semantic_retrieval import _TOPIC_EXCLUSIVE
        exclusion = np.ones(len(self.all_beliefs))
        ql = query.lower()
        for i, b in enumerate(self.all_beliefs):
            for belief_key, required_patterns in _TOPIC_EXCLUSIVE.items():
                if b["content"].startswith(belief_key[:40]):
                    if not any(re.search(p, ql) for p in required_patterns):
                        exclusion[i] = 0.2  # strong penalty if off-topic
                    break

        final = sims * self.weights * topic_boost * exclusion'''

# Try the import-free version (since we're inside the same module)
old_final2 = '        final = sims * self.weights * topic_boost'
new_final2 = '''        # apply per-belief topic exclusion penalty
        exclusion = np.ones(len(self.all_beliefs))
        ql_ex = query.lower()
        for i, b in enumerate(self.all_beliefs):
            bc = b["content"]
            for belief_key, required_patterns in _TOPIC_EXCLUSIVE.items():
                if bc.startswith(belief_key[:45]):
                    if not any(re.search(p, ql_ex) for p in required_patterns):
                        exclusion[i] = 0.2
                    break

        final = sims * self.weights * topic_boost * exclusion'''

if old_final in src:
    src = src.replace(old_final, new_final2)
    print("  [OK] topic exclusion applied in retrieve()")

with open(SR, "w") as f: f.write(src)
syntax(SR)
print("  [OK] semantic_retrieval syntax clean")

# ── Fix voice_gen: Strand structural response + factual ───────────────────────
bak(VG)
with open(VG) as f: src = f.read()

old_factual = '''FACTUAL = {
    "strand helderberg": (
        "Strand is a coastal town in the Western Cape, along False Bay about "
        "50 kilometres east of Cape Town. It\'s quieter and more residential "
        "than the city — not much tourist traffic, which gives it a different "
        "pace. The Helderberg range backs the area, which is striking if "
        "you\'re oriented toward landscape. It tends to get described as "
        "sleepy, which can mean peaceful or isolating depending on what "
        "you need from a place."
    ),'''

new_factual = '''FACTUAL = {
    "strand helderberg": (
        "Strand is a coastal town in the Western Cape, along False Bay about "
        "50 kilometres east of Cape Town. It\'s quieter and more residential "
        "than the city — not much tourist traffic, which gives it a different "
        "pace. The Helderberg range backs the area, which is striking if "
        "you\'re oriented toward landscape. It tends to get described as "
        "sleepy, which can mean peaceful or isolating depending on what "
        "you need from a place."
    ),
    "nowhere to socialise": (
        "That\'s a structural problem, not a personal failing. When a place "
        "doesn\'t have the infrastructure for connection — the venues, the density "
        "of people you\'d actually want to know — it\'s not about trying harder. "
        "The options are usually: build something yourself, find people through "
        "other channels, or accept that the place isn\'t giving you what you need "
        "and figure out what to do about that. None of those are easy."
    ),
    "lonely.*strand": (
        "That\'s a structural problem, not a personal failing. When a place "
        "doesn\'t have the infrastructure for connection — the venues, the density "
        "of people you\'d actually want to know — it\'s not about trying harder. "
        "The options are: build something, find people through other channels, "
        "or decide the place isn\'t giving you what you need. None of those are easy."
    ),'''

if old_factual in src:
    src = src.replace(old_factual, new_factual)
    print("  [OK] Strand structural response added to FACTUAL")

# Upgrade _factual_check to support regex keys
old_factual_check = '''def _factual_check(q):
    ql = q.lower()
    for key, ans in FACTUAL.items():
        if key in ql:
            return ans
    return None'''

new_factual_check = '''def _factual_check(q):
    ql = q.lower()
    for key, ans in FACTUAL.items():
        try:
            if re.search(key, ql):
                return ans
        except re.error:
            if key in ql:
                return ans
    return None'''

if old_factual_check in src:
    src = src.replace(old_factual_check, new_factual_check)
    print("  [OK] _factual_check upgraded to support regex keys")

with open(VG, "w") as f: f.write(src)
syntax(VG)
print("  [OK] voice_gen syntax clean")

print("""
  ✓ Done

  Changes:
    • Consciousness/depth/curiosity/food beliefs get 0.4-0.5x weight (was 0.6-0.7x)
    • Topic exclusion gate: consciousness beliefs score 0.2x on non-consciousness queries
    • Curiosity belief: only scores well for learn/think/curious/bored queries
    • Food/pleasure beliefs: only score well for food/taste/pleasure queries
    • "lonely in strand" → structural response (not generic loneliness beliefs)

  Rebuild and test:
    rm -f ~/Desktop/nex/.semantic_cache*.pkl
    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py
""")
