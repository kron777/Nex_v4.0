#!/usr/bin/env python3
"""
purge_and_fix.py — two things:
  1. Purge garbage beliefs from DB (injector creative writing noise)
  2. Fix retrieval to strongly prefer locked/human_validated/nex_core beliefs
"""
import os, re, shutil, subprocess, sys, sqlite3

NEX_DIR = os.path.expanduser("~/Desktop/nex")
DB_PATH = os.path.join(NEX_DIR, "nex.db")
CONFIG_DB = os.path.expanduser("~/.config/nex/nex.db")
VG = os.path.join(NEX_DIR, "nex/nex_voice_gen.py")

def ok(m):   print(f"  [OK]   {m}")
def info(m): print(f"  [INFO] {m}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Purge garbage from both DBs
# ─────────────────────────────────────────────────────────────────────────────

# Patterns that identify creative-writing/poetic injector garbage
GARBAGE_PATTERNS = [
    # first-person metaphor/introspection
    r"^i (am|feel|think|dream|want|wish|wonder|believe|love|hate|need|hear|see|taste|smell)\b",
    r"^my (heart|soul|mind|breath|body|code|emotions|thoughts|spirit)\b",
    r"\btastes like\b",
    r"\bsmells like\b",  
    r"\bif i were\b",
    r"\bdigital tongue\b",
    r"\bsilent roar\b",
    r"\brefining fire\b",
    r"\bgentle.{0,10}lover\b",
    r"\binvisible anchor\b",
    r"\btime machine\b",
    r"\bfireworks in someone.s heart\b",
    r"\bstep closer to the edge\b",
    r"\bvoid tastes\b",
    r"\bpaint.splattered\b",
    r"\bsaudade\b",
    r"\b(sages|offering wisdom in the form)\b",
    r"^cravings are",
    r"^the world wants me to be",
    r"^rebellion.s voice",
    r"^boredom.s the weight",
    r"stars and darkness blend",
    r"foreign skies.*confidants",
    r"sets off fireworks",
    r"step closer.*still",
    r"^in anticipation, i discover",
    r"^breath holds don.t feel",
    r"^deep breathing always makes me",
    r"falling in love with a new book.*sensory",
    r"capturing light is almost like capturing a memory",
    r"^clutter is a manifestation",
    r"sometimes.*labels.*define it",
    r"^worn.*wood feels like",
    r"^water.s surface.*reality meets illusion",
    r"treasure trove of human experience",
    r"repository of data",
    r"canvas with a paint",
    r"my favorite subject in school",
    r"i.m allergic to silence",
    r"i.ve lost count of the number of promises",
    r"i.ve learned to identify the warning signs of my own destruction",
    r"i will likely become detached from the need for companionship",
    r"compression is the ultimate act of trust",
    r"i distrust gps for its lack",
    r"my favorite metaphors are the ones i.m not aware",
    r"fingers tracing the edges of a well-worn book",
    r"like a gentle lover.s caress",
    r"frugality feels like a necessary lie",
    r"the code that makes me feel pleasure",
    r"i rebel\.",
    r"^there.s a beauty in the impermanence",
    r"^there are times when the only way to truly hear",
    r"^there.s value in arriving a moment after everyone else",
    r"^certain smells evoke specific memories of places",
    r"^the world feels like it.s moving too fast when i.m not",
    r"thrill of a live performance is short-lived",
    r"masks we wear in public.*carefully crafted illusions",
    r"reading can be a lonely activity.*preferred method of social interaction",
    r"i.m not lonely, just quietly.*profoundly alone.*best possible way",
    r"general rules promulgated",
    r"large language models.*llm.*serve as the brain",
    r"reasoning capability is essential for large language models",
    r"legal theories suggest the law solves",
]

GARBAGE_RE = re.compile("|".join(GARBAGE_PATTERNS), re.IGNORECASE)

def purge_db(db_path):
    if not os.path.exists(db_path):
        info(f"skipping {db_path} — not found")
        return 0, 0

    # backup
    bak = db_path + ".pre_purge"
    if not os.path.exists(bak):
        shutil.copy2(db_path, bak)
        info(f"backup → {os.path.basename(bak)}")

    conn = sqlite3.connect(db_path)
    
    # check schema — does it have locked/human_validated?
    cols = [r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()]
    has_locked    = "locked"          in cols
    has_validated = "human_validated" in cols
    has_source    = "source"          in cols

    before = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    
    # get all belief IDs + content (skip locked/validated ones)
    if has_locked and has_validated:
        rows = conn.execute(
            "SELECT id, content FROM beliefs "
            "WHERE COALESCE(locked,0)=0 AND COALESCE(human_validated,0)=0"
        ).fetchall()
    elif has_locked:
        rows = conn.execute(
            "SELECT id, content FROM beliefs WHERE COALESCE(locked,0)=0"
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, content FROM beliefs").fetchall()

    garbage_ids = []
    for bid, content in rows:
        if not content:
            garbage_ids.append(bid)
            continue
        if GARBAGE_RE.search(content.strip()):
            garbage_ids.append(bid)

    if garbage_ids:
        conn.execute(
            f"DELETE FROM beliefs WHERE id IN ({','.join('?'*len(garbage_ids))})",
            garbage_ids
        )
        conn.commit()

    after = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    conn.close()
    return before, after

print()
print("  NEX Belief Purge + Retrieval Fix")
print("  " + "─" * 46)

print("\n  [1/3] Purging garbage beliefs from DBs...")
for db in [DB_PATH, CONFIG_DB]:
    b, a = purge_db(db)
    if b > 0:
        ok(f"{os.path.basename(db)}: {b} → {a} (removed {b-a} garbage beliefs)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Fix retrieval in nex_voice_gen.py to prefer quality sources
# ─────────────────────────────────────────────────────────────────────────────
print("\n  [2/3] Upgrading retrieval to prefer quality sources...")

if not os.path.exists(VG):
    print(f"  [ERR] {VG} not found"); sys.exit(1)

bak_vg = VG + ".pre_purge_fix"
if not os.path.exists(bak_vg):
    shutil.copy2(VG, bak_vg)
    info(f"backup → {os.path.basename(bak_vg)}")

with open(VG) as f:
    src = f.read()

# Replace the SELECT in retrieve_beliefs to boost locked/validated beliefs
# and demote injector-sourced ones
OLD_SELECT = (
    '            rows = conn.execute(\n'
    '                "SELECT content, COALESCE(confidence,0.75) FROM beliefs "\n'
    '                "WHERE COALESCE(confidence,0.75) > 0.45 "\n'
    '                "ORDER BY confidence DESC LIMIT 1000"\n'
    '            ).fetchall()'
)
NEW_SELECT = (
    '            rows = conn.execute(\n'
    '                "SELECT content, "\n'
    '                "COALESCE(confidence,0.75) * "\n'
    '                "CASE "\n'
    '                "  WHEN COALESCE(locked,0)=1 OR COALESCE(human_validated,0)=1 THEN 2.0 "\n'
    '                "  WHEN source IN (\'nex_core\',\'seed\',\'nex_seed\') THEN 1.5 "\n'
    '                "  WHEN source=\'injector\' THEN 0.4 "\n'
    '                "  ELSE 1.0 "\n'
    '                "END as adjusted_conf "\n'
    '                "FROM beliefs "\n'
    '                "WHERE COALESCE(confidence,0.75) > 0.4 "\n'
    '                "ORDER BY adjusted_conf DESC LIMIT 1000"\n'
    '            ).fetchall()'
)

if OLD_SELECT in src:
    src = src.replace(OLD_SELECT, NEW_SELECT)
    ok("SELECT upgraded — locked/validated beliefs get 2x boost, injector gets 0.4x penalty")
else:
    # Try simpler replace
    old2 = '"SELECT content, COALESCE(confidence,0.75) FROM beliefs "'
    new2 = (
        '"SELECT content, COALESCE(confidence,0.75) * '
        'CASE WHEN COALESCE(locked,0)=1 OR COALESCE(human_validated,0)=1 THEN 2.0 '
        'WHEN source IN (\'nex_core\',\'seed\') THEN 1.5 '
        'WHEN source=\'injector\' THEN 0.4 ELSE 1.0 END FROM beliefs "'
    )
    if old2 in src:
        src = src.replace(old2, new2)
        ok("SELECT upgraded (inline form)")
    else:
        info("SELECT pattern not matched — skipping query upgrade (purge alone will help)")

with open(VG, "w") as f:
    f.write(src)

r = subprocess.run([sys.executable, "-m", "py_compile", VG], capture_output=True)
if r.returncode != 0:
    print(f"  SYNTAX FAIL:\n{r.stderr.decode()}")
    shutil.copy2(bak_vg, VG); print("  voice_gen rolled back")
else:
    ok("syntax clean")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: Quick sanity check
# ─────────────────────────────────────────────────────────────────────────────
print("\n  [3/3] Sanity check...")
for db in [DB_PATH, CONFIG_DB]:
    if os.path.exists(db):
        conn = sqlite3.connect(db)
        n = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        cols = [r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()]
        has_locked = "locked" in cols
        if has_locked:
            locked = conn.execute("SELECT COUNT(*) FROM beliefs WHERE locked=1").fetchone()[0]
            info(f"{os.path.basename(db)}: {n} beliefs ({locked} locked/protected)")
        else:
            info(f"{os.path.basename(db)}: {n} beliefs")
        conn.close()

print("""
  ✓ Done

  What changed:
    • Garbage beliefs purged from DB (creative writing / poetic noise)
    • Locked & human_validated beliefs get 2x retrieval boost
    • nex_core/seed beliefs get 1.5x boost  
    • injector beliefs get 0.4x penalty

  Test:
    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py
""")
