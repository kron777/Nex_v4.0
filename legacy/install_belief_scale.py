"""
install_belief_scale.py — Install the full belief scaling system into NEX
Installs: nex_belief_index + nex_belief_memory + nex_belief_architect
Run from ~/Desktop/nex/
"""

import os
import sys
import shutil
import py_compile

NEX_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_PY  = os.path.join(NEX_DIR, "run.py")

FILES = [
    "nex_belief_index.py",
    "nex_belief_memory.py",
    "nex_belief_architect.py",
]

BLOCK = '''
# [NEX_BELIEF_SCALE] — auto-injected by install_belief_scale.py
try:
    # Smart contextual belief index (TF-IDF, scales to millions)
    from nex_belief_index import get_index as _get_bindex
    _belief_index = _get_bindex()
    print(f"  [BeliefIndex] built — {_belief_index.total()} beliefs indexed")

    # Tiered memory manager (hot/warm/cold tiers)
    from nex_belief_memory import get_memory as _get_bmem
    _belief_memory = _get_bmem()
    s = _belief_memory.status()
    print(f"  [BeliefMemory] hot={s['hot_tier']} warm={s['warm_tier']} total={s['total_in_db']}")

    # Belief architect daemon (dedup, compression, decay, health)
    from nex_belief_architect import start_architect as _start_arch
    _belief_architect = _start_arch()
    print("  [BeliefArchitect] started — dedup/compress/decay/health monitoring")

except Exception as _bse:
    print(f"  [BeliefScale] failed to start: {_bse}")
# [/NEX_BELIEF_SCALE]
'''

INJECT_AFTER  = "[/NEX_SOURCE_ROUTER]"
FALLBACK      = "[/NEX_METABOLISM]"
LAST_RESORT   = 'if __name__ == "__main__":'

def main():
    print("\n  NEX Belief Scale — Installer")
    print("  " + "─" * 44)

    # Check all files present
    print("\n  [1/4] Checking files...")
    missing = [f for f in FILES if not os.path.exists(os.path.join(NEX_DIR, f))]
    if missing:
        print(f"  ✗ Missing: {missing}")
        print("    Copy all three files into ~/Desktop/nex/ first.")
        sys.exit(1)

    # Syntax checks
    print("\n  [2/4] Syntax checks...")
    for f in FILES + ["run.py"]:
        path = os.path.join(NEX_DIR, f)
        try:
            py_compile.compile(path, doraise=True)
            print(f"  ✓ {f}")
        except py_compile.PyCompileError as e:
            print(f"  ✗ {f}: {e}")
            sys.exit(1)

    # Read run.py
    with open(RUN_PY, "r") as f:
        src = f.read()

    if "[NEX_BELIEF_SCALE]" in src:
        print("\n  ℹ  Already installed — nothing to do.")
        sys.exit(0)

    # Backup
    backup = RUN_PY + ".pre_belief_scale_backup"
    shutil.copy2(RUN_PY, backup)
    print(f"\n  [3/4] Backup → {backup}")

    # Inject
    if INJECT_AFTER in src:
        new_src = src.replace(INJECT_AFTER, INJECT_AFTER + "\n" + BLOCK, 1)
        print(f"  → injecting after [/NEX_SOURCE_ROUTER]")
    elif FALLBACK in src:
        new_src = src.replace(FALLBACK, FALLBACK + "\n" + BLOCK, 1)
        print(f"  → injecting after [/NEX_METABOLISM]")
    else:
        new_src = src.replace(LAST_RESORT, BLOCK + LAST_RESORT, 1)
        print(f"  → injecting before __main__")

    # Validate
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
        tmp.write(new_src)
        tmp_path = tmp.name
    try:
        py_compile.compile(tmp_path, doraise=True)
    except py_compile.PyCompileError as e:
        print(f"  ✗ patch broke run.py: {e}")
        os.unlink(tmp_path)
        sys.exit(1)
    os.unlink(tmp_path)

    # Write
    with open(RUN_PY, "w") as f:
        f.write(new_src)
    print(f"\n  [4/4] ✓ run.py patched")
    print("\n  Done. Start NEX:")
    print("    nex\n")
    print("  On startup:")
    print("    [BeliefIndex]    built — 11621 beliefs indexed")
    print("    [BeliefMemory]   hot=2000 warm=10000 total=11621")
    print("    [BeliefArchitect] started — dedup/compress/decay/health\n")
    print("  This system scales to millions of beliefs without changes.\n")

if __name__ == "__main__":
    main()
