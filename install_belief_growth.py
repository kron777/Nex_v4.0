#!/usr/bin/env python3
"""
install_belief_growth.py
─────────────────────────
1. Copies nex_belief_growth.py into ~/Desktop/nex/
2. Verifies it compiles
3. Finds the right injection point in run.py and patches it in
4. Verifies run.py still compiles after the patch

Run:
    python3 install_belief_growth.py
    python3 install_belief_growth.py --dry-run   # preview only, no changes
    python3 install_belief_growth.py --undo      # remove the patch
"""

import ast, os, re, shutil, sys, argparse

NEX_DIR     = os.path.expanduser("~/Desktop/nex")
RUN_PY      = os.path.join(NEX_DIR, "run.py")
GROWTH_SRC  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nex_belief_growth.py")
BACKUP_PATH = RUN_PY + ".pre_growth_backup"

PATCH_MARKER = "# [BELIEF_GROWTH_DAEMON]"
PATCH_BLOCK  = """\n# [BELIEF_GROWTH_DAEMON] — auto-injected by install_belief_growth.py
try:
    from nex_belief_growth import BeliefGrowthDaemon as _BGD
    _growth_daemon = _BGD()
    _growth_daemon.start()
    print("  [NEX GROWTH] belief growth daemon started")
except Exception as _bgd_err:
    print(f"  [NEX GROWTH] failed to start: {_bgd_err}")
# [/BELIEF_GROWTH_DAEMON]\n"""


def check(path, label):
    """Verify a python file parses cleanly."""
    with open(path) as f:
        src = f.read()
    try:
        ast.parse(src)
        print(f"  ✓ {label} — syntax OK")
        return True
    except SyntaxError as e:
        print(f"  ✗ {label} — SyntaxError: {e}")
        return False


def find_injection_point(src):
    """
    Find the best line to inject the daemon start.
    Priority:
      1. Just before `if __name__ == "__main__":`
      2. Just after the last top-level import block
      3. Just after homeostasis / upgrade stack loads (common NEX pattern)
      4. Fallback: end of file
    Returns line index (0-based) to insert BEFORE.
    """
    lines = src.splitlines()

    # 1. if __name__ == "__main__"
    for i, line in enumerate(lines):
        if re.match(r'^if\s+__name__\s*==\s*["\']__main__["\']', line.strip()):
            print(f"  → injection point: line {i+1} (before __main__ block)")
            return i

    # 2. Last occurrence of a known NEX startup print / thread start
    for pattern in [
        r'\.start\(\)',
        r'print.*NEX.*loaded',
        r'print.*started',
        r'threading\.Thread',
    ]:
        matches = [i for i, l in enumerate(lines) if re.search(pattern, l)]
        if matches:
            idx = matches[-1] + 1
            print(f"  → injection point: line {idx+1} (after last thread/start call)")
            return idx

    # 3. After last import block
    last_import = 0
    for i, line in enumerate(lines):
        if re.match(r'^(import |from )', line.strip()):
            last_import = i
    if last_import:
        idx = last_import + 1
        print(f"  → injection point: line {idx+1} (after last import)")
        return idx

    # 4. Fallback — end of file
    print(f"  → injection point: end of file (fallback)")
    return len(lines)


def patch_run_py(dry_run=False):
    if not os.path.exists(RUN_PY):
        print(f"  ✗ run.py not found at {RUN_PY}")
        sys.exit(1)

    with open(RUN_PY) as f:
        src = f.read()

    if PATCH_MARKER in src:
        print("  ℹ  run.py already patched — nothing to do")
        print("     (run with --undo to remove, then re-run to re-apply)")
        return

    lines = src.splitlines(keepends=True)
    idx   = find_injection_point(src)

    patched_lines = lines[:idx] + [PATCH_BLOCK] + lines[idx:]
    patched_src   = "".join(patched_lines)

    # Verify the patched version still parses
    try:
        ast.parse(patched_src)
    except SyntaxError as e:
        print(f"  ✗ patch would break run.py syntax: {e}")
        print("    Aborting — no changes made.")
        sys.exit(1)

    if dry_run:
        print("\n  DRY RUN — patch preview:")
        print("  " + "─" * 50)
        # Show context around injection
        ctx_start = max(0, idx - 3)
        ctx_end   = min(len(lines), idx + 4)
        for i in range(ctx_start, ctx_end):
            print(f"  {i+1:5d}  {lines[i]}", end="")
        print("\n  ^^^ PATCH INSERTED HERE ^^^")
        print(PATCH_BLOCK)
        print("  " + "─" * 50)
        print("  (no files changed — remove --dry-run to apply)")
        return

    # Backup
    shutil.copy2(RUN_PY, BACKUP_PATH)
    print(f"  ✓ backup → {BACKUP_PATH}")

    # Write
    with open(RUN_PY, "w") as f:
        f.write(patched_src)
    print(f"  ✓ run.py patched")


def undo_patch():
    if os.path.exists(BACKUP_PATH):
        shutil.copy2(BACKUP_PATH, RUN_PY)
        print(f"  ✓ restored run.py from backup")
        os.remove(BACKUP_PATH)
        print(f"  ✓ backup removed")
    else:
        # Try to strip the patch block manually
        with open(RUN_PY) as f:
            src = f.read()
        if PATCH_MARKER not in src:
            print("  ℹ  run.py doesn't appear to be patched")
            return
        # Remove everything between markers
        cleaned = re.sub(
            r'\n# \[BELIEF_GROWTH_DAEMON\].*?# \[/BELIEF_GROWTH_DAEMON\]\n',
            '\n',
            src,
            flags=re.DOTALL
        )
        with open(RUN_PY, "w") as f:
            f.write(cleaned)
        print("  ✓ patch block removed from run.py")


def main():
    parser = argparse.ArgumentParser(description="Install NEX belief growth daemon")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    parser.add_argument("--undo",    action="store_true", help="Remove the patch")
    args = parser.parse_args()

    print("\n  NEX Belief Growth — Installer")
    print("  " + "─" * 40)

    if args.undo:
        undo_patch()
        return

    # 1. Check growth module exists
    if not os.path.exists(GROWTH_SRC):
        # Try same directory as this script
        alt = os.path.join(NEX_DIR, "nex_belief_growth.py")
        if os.path.exists(alt):
            print(f"  ✓ found nex_belief_growth.py in {NEX_DIR}")
        else:
            print(f"  ✗ nex_belief_growth.py not found")
            print(f"    Put it in the same folder as this script or in {NEX_DIR}")
            sys.exit(1)
    else:
        # Copy to nex dir if not already there
        dest = os.path.join(NEX_DIR, "nex_belief_growth.py")
        if not os.path.exists(dest):
            shutil.copy2(GROWTH_SRC, dest)
            print(f"  ✓ copied nex_belief_growth.py → {NEX_DIR}")
        else:
            print(f"  ✓ nex_belief_growth.py already in {NEX_DIR}")

    # 2. Compile check — growth module
    growth_path = os.path.join(NEX_DIR, "nex_belief_growth.py")
    if not check(growth_path, "nex_belief_growth.py"):
        sys.exit(1)

    # 3. Compile check — run.py before patch
    if not check(RUN_PY, "run.py (before patch)"):
        print("  ✗ run.py has existing syntax errors — fix those first")
        sys.exit(1)

    # 4. Patch run.py
    patch_run_py(dry_run=args.dry_run)

    if not args.dry_run:
        # 5. Final compile check
        if check(RUN_PY, "run.py (after patch)"):
            print("\n  ✓ All done. Start NEX normally:")
            print("    python3 ~/Desktop/nex/run.py")
            print("\n  You'll see:")
            print("    [NEX GROWTH] belief growth daemon started")
            print("    [NEX GROWTH] growth cycle every 3h — 4 topics × 20 beliefs")
        else:
            print("\n  ✗ Patch broke run.py — restoring backup")
            if os.path.exists(BACKUP_PATH):
                shutil.copy2(BACKUP_PATH, RUN_PY)
                print("  ✓ run.py restored from backup")


if __name__ == "__main__":
    main()
