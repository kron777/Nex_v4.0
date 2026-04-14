#!/usr/bin/env python3
"""
patch_belief_quality.py
Adds a quality gate to retrieve_beliefs() in nex_voice_gen.py.
Filters out poetic/metaphorical creative-writing noise.
Prefers declarative, positional beliefs.
"""
import os, re, shutil, subprocess, sys

VG = os.path.expanduser("~/Desktop/nex/nex/nex_voice_gen.py")
if not os.path.exists(VG):
    print(f"Not found: {VG}"); sys.exit(1)

bak = VG + ".pre_quality"
if not os.path.exists(bak):
    shutil.copy2(VG, bak)
    print(f"  backup → {os.path.basename(bak)}")

with open(VG) as f:
    src = f.read()

# ── Quality gate function to inject ──────────────────────────────────────────
QUALITY_FN = '''
# ── belief quality gate ───────────────────────────────────────────────────────
# Rejects poetic/metaphorical noise. Prefers declarative positions.

_POETIC_PATTERNS = [
    r"if i were a",
    r"tastes like",
    r"smells like",
    r"feels like a gentle",
    r"feels like a \\w+ lover",
    r"digital tongue",
    r"paint.splattered",
    r"heart is a repository",
    r"soul.s deepest",
    r"void tastes",
    r"silent roar",
    r"gentle, reassuring presence",
    r"canvas with a",
    r"echo of my deepest",
    r"stepping closer to the edge",
    r"invisible anchor",
    r"refining fire",
    r"treasury of",
    r"i am a river",
    r"like a river",
    r"like a gentle",
    r"i dream of",
    r"my heart is",
    r"my soul",
    r"my breath is",
    r"treasure trove",
    r"paint.splattered",
    r"lose yourself",
    r"saudade",
]

_POETIC_RE = re.compile("|".join(_POETIC_PATTERNS), re.IGNORECASE)

_DECLARATIVE_BONUS = [
    r"^(loneliness|trust|honesty|consciousness|people|most|the|when|what|how|why)",
    r"\\b(is|are|was|were|means|makes|requires|involves|depends)\\b",
    r"^[A-Z][^I]",  # starts with capital that isn\'t "I"
]
_DECL_RE = re.compile("|".join(_DECLARATIVE_BONUS), re.IGNORECASE)

def _belief_quality(content):
    """
    Returns float 0-1. Higher = better belief for response generation.
    Penalizes creative/poetic first-person metaphor.
    Rewards declarative positional statements.
    """
    if _POETIC_RE.search(content):
        return 0.0
    cl = content.lower()
    # penalize excessive "I" statements that are introspective-creative
    i_count = len(re.findall(r"\\bi\\b", cl))
    if i_count >= 3:
        return 0.15
    # penalize very short (not enough substance)
    if len(content) < 20:
        return 0.1
    # reward declarative
    score = 0.5
    if _DECL_RE.search(content):
        score += 0.3
    if i_count == 0:
        score += 0.2
    return min(score, 1.0)

'''

# Inject quality fn before retrieve_beliefs
insert_before = "def retrieve_beliefs("
if insert_before in src:
    src = src.replace(insert_before, QUALITY_FN + "\n" + insert_before, 1)
    print("  [OK] quality gate function injected")
else:
    print("  [ERR] retrieve_beliefs not found"); sys.exit(1)

# Now patch the scoring inside retrieve_beliefs to use quality gate
# Find the scored.append line and add quality multiplier
old_score = "        score = (overlap / max(len(words), 1)) * conf\n        scored.append((score, content))"
new_score = """        q = _belief_quality(content)
        if q == 0.0:
            continue
        score = (overlap / max(len(words), 1)) * conf * q
        scored.append((score, content))"""

if old_score in src:
    src = src.replace(old_score, new_score)
    print("  [OK] quality score wired into retrieval")
else:
    print("  [SKIP] score pattern not matched — checking alternate")
    # try without the append on same line
    alt = "        score = (overlap / max(len(words), 1)) * conf"
    if alt in src:
        src = src.replace(alt,
            "        q = _belief_quality(content)\n"
            "        if q == 0.0: continue\n"
            "        score = (overlap / max(len(words), 1)) * conf * q")
        print("  [OK] quality score wired (alternate)")

with open(VG, "w") as f:
    f.write(src)

r = subprocess.run([sys.executable, "-m", "py_compile", VG], capture_output=True)
if r.returncode != 0:
    print(f"  SYNTAX FAIL:\n{r.stderr.decode()}")
    shutil.copy2(bak, VG); print("  rolled back"); sys.exit(1)

print("  [OK] syntax clean")
print("""
  ✓ Done

  What changed:
    • _belief_quality() gate added — rejects poetic/metaphor noise
    • Scoring now multiplies by quality (0–1) — garbage beliefs score 0 and skip
    • Declarative positional beliefs get bonus score

  Test:
    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py
""")
