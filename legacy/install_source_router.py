"""
install_source_router.py — Wires SourceRouter into NEX run.py
Run from ~/Desktop/nex/
"""

import sys
import os
import shutil
import py_compile

NEX_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_PY  = os.path.join(NEX_DIR, "run.py")
ROUTER  = os.path.join(NEX_DIR, "nex_source_router.py")

INJECT_MARKER  = "[/NEX_METABOLISM]"  # inject right after metabolism block
FALLBACK_MARKER = 'if __name__ == "__main__":'

BLOCK = '''
# [NEX_SOURCE_ROUTER] — auto-injected by install_source_router.py
try:
    from nex_source_router import SourceRouter as _SR
    _source_router = _SR()
    _source_router.start()
    print("  [SOURCE_ROUTER] 6-tier belief extraction active — RSS/HN/Reddit/Wiki/Arxiv/YouTube/crawl4ai")
except Exception as _sr_err:
    print(f"  [SOURCE_ROUTER] failed to start: {_sr_err}")
# [/NEX_SOURCE_ROUTER]
'''

def check_syntax(path):
    try:
        py_compile.compile(path, doraise=True)
        return True
    except py_compile.PyCompileError as e:
        print(f"  ✗ syntax error in {os.path.basename(path)}: {e}")
        return False

def main():
    print("\n  NEX Source Router — Installer")
    print("  " + "─" * 44)

    # Check router file exists
    if not os.path.exists(ROUTER):
        print(f"  ✗ nex_source_router.py not found in {NEX_DIR}")
        print("    Copy it here first, then re-run.")
        sys.exit(1)

    # Syntax checks
    print("\n  [1/3] Syntax checks...")
    if not check_syntax(ROUTER):
        sys.exit(1)
    print(f"  ✓ nex_source_router.py — OK")
    if not check_syntax(RUN_PY):
        sys.exit(1)
    print(f"  ✓ run.py — OK")

    # Read run.py
    with open(RUN_PY, "r") as f:
        src = f.read()

    # Check not already patched
    if "[NEX_SOURCE_ROUTER]" in src:
        print("\n  ℹ  run.py already has SourceRouter — nothing to do.")
        sys.exit(0)

    # Backup
    backup = RUN_PY + ".pre_source_router_backup"
    shutil.copy2(RUN_PY, backup)
    print(f"\n  [2/3] Backup → {backup}")

    # Find injection point — after metabolism block if present, else before __main__
    if INJECT_MARKER in src:
        inject_after = INJECT_MARKER
        new_src = src.replace(inject_after, inject_after + "\n" + BLOCK, 1)
        print(f"  → injecting after [/NEX_METABOLISM] block")
    elif FALLBACK_MARKER in src:
        new_src = src.replace(FALLBACK_MARKER, BLOCK + FALLBACK_MARKER, 1)
        print(f"  → injecting before __main__")
    else:
        print("  ✗ could not find injection point in run.py")
        sys.exit(1)

    # Write
    with open(RUN_PY, "w") as f:
        f.write(new_src)

    # Final syntax check
    if not check_syntax(RUN_PY):
        print("  ✗ patch broke run.py — restoring backup")
        shutil.copy2(backup, RUN_PY)
        sys.exit(1)

    print(f"\n  [3/3] ✓ run.py patched")
    print("\n  Installation complete. Start NEX normally:")
    print("    nex\n")
    print("  On startup you'll see:")
    print("    [SOURCE_ROUTER] 6-tier belief extraction active\n")

    # Install optional deps quietly
    print("  Installing optional dependencies...")
    os.system("pip install feedparser youtube-transcript-api --break-system-packages -q")
    print("  ✓ feedparser + youtube-transcript-api installed\n")

if __name__ == "__main__":
    main()
