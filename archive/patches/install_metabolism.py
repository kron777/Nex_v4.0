#!/usr/bin/env python3
"""
install_metabolism.py
──────────────────────
Installs NEX's full epistemic metabolism system:
  - nex_gap_detector.py
  - nex_web_crawler.py
  - nex_distiller.py
  - nex_metabolism.py

Then patches run.py to start MetabolismDaemon on boot.

Usage:
    python3 install_metabolism.py            # install + patch
    python3 install_metabolism.py --dry-run  # preview only
    python3 install_metabolism.py --undo     # remove patch
    python3 install_metabolism.py --test     # test one cycle without patching
"""

import ast, os, re, shutil, sys, argparse, subprocess

NEX_DIR     = os.path.expanduser("~/Desktop/nex")
RUN_PY      = os.path.join(NEX_DIR, "run.py")
BACKUP_PATH = RUN_PY + ".pre_metabolism_backup"
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))

MODULES = [
    "nex_gap_detector.py",
    "nex_web_crawler.py",
    "nex_distiller.py",
    "nex_metabolism.py",
]

PATCH_MARKER = "# [NEX_METABOLISM]"
PATCH_BLOCK  = """\n# [NEX_METABOLISM] — auto-injected by install_metabolism.py
try:
    from nex_metabolism import MetabolismDaemon as _MD
    _metabolism = _MD()
    _metabolism.start()
    print("  [METABOLISM] epistemic loop started — gap→crawl→distil→believe")
except Exception as _md_err:
    print(f"  [METABOLISM] failed to start: {_md_err}")
# [/NEX_METABOLISM]\n"""


def ok(msg):  print(f"  ✓ {msg}")
def err(msg): print(f"  ✗ {msg}")
def inf(msg): print(f"  ℹ  {msg}")


def compile_check(path, label=None):
    label = label or os.path.basename(path)
    with open(path) as f:
        src = f.read()
    try:
        ast.parse(src)
        ok(f"{label} — syntax OK")
        return True
    except SyntaxError as e:
        err(f"{label} — SyntaxError: {e}")
        return False


def copy_modules(dry_run=False):
    """Copy all metabolism modules into NEX dir."""
    all_ok = True
    for fname in MODULES:
        src  = os.path.join(SCRIPT_DIR, fname)
        dest = os.path.join(NEX_DIR, fname)

        if not os.path.exists(src):
            # Maybe already in NEX dir
            if os.path.exists(dest):
                inf(f"{fname} already in place")
                continue
            err(f"{fname} not found in {SCRIPT_DIR}")
            all_ok = False
            continue

        if dry_run:
            inf(f"would copy {fname} → {NEX_DIR}")
        else:
            shutil.copy2(src, dest)
            ok(f"copied {fname} → {NEX_DIR}")
    return all_ok


def find_injection_point(src):
    """Find best line to inject before in run.py."""
    lines = src.splitlines()

    # 1. Before if __name__ == "__main__"
    for i, line in enumerate(lines):
        if re.match(r'^if\s+__name__\s*==\s*["\']__main__["\']', line.strip()):
            print(f"  → injection point: line {i+1} (before __main__)")
            return i

    # 2. After last .start() call
    matches = [i for i, l in enumerate(lines) if re.search(r'\.start\(\)', l)]
    if matches:
        idx = matches[-1] + 1
        print(f"  → injection point: line {idx+1} (after last .start())")
        return idx

    # 3. End of file
    print(f"  → injection point: end of file (fallback)")
    return len(lines)


def patch_run_py(dry_run=False):
    if not os.path.exists(RUN_PY):
        err(f"run.py not found at {RUN_PY}")
        sys.exit(1)

    with open(RUN_PY) as f:
        src = f.read()

    if PATCH_MARKER in src:
        inf("run.py already has metabolism patch")
        inf("run with --undo then re-run to refresh")
        return True

    lines   = src.splitlines(keepends=True)
    idx     = find_injection_point(src)
    patched = "".join(lines[:idx] + [PATCH_BLOCK] + lines[idx:])

    # Verify patch doesn't break syntax
    try:
        ast.parse(patched)
    except SyntaxError as e:
        err(f"patch would break run.py: {e}")
        err("Aborting — no changes made")
        sys.exit(1)

    if dry_run:
        print("\n  DRY RUN — patch preview:")
        print("  " + "─" * 50)
        ctx_start = max(0, idx - 2)
        ctx_end   = min(len(lines), idx + 3)
        for i in range(ctx_start, ctx_end):
            print(f"  {i+1:5d}  {lines[i]}", end="")
        print("\n  ^^^ METABOLISM BLOCK INSERTED HERE ^^^")
        print(PATCH_BLOCK)
        print("  " + "─" * 50)
        inf("no files changed — remove --dry-run to apply")
        return True

    shutil.copy2(RUN_PY, BACKUP_PATH)
    ok(f"backup → {BACKUP_PATH}")

    with open(RUN_PY, "w") as f:
        f.write(patched)
    ok("run.py patched")
    return True


def undo_patch():
    if os.path.exists(BACKUP_PATH):
        shutil.copy2(BACKUP_PATH, RUN_PY)
        ok("restored run.py from backup")
        os.remove(BACKUP_PATH)
        ok("backup removed")
    else:
        with open(RUN_PY) as f:
            src = f.read()
        if PATCH_MARKER not in src:
            inf("run.py doesn't appear to be patched")
            return
        cleaned = re.sub(
            r'\n# \[NEX_METABOLISM\].*?# \[/NEX_METABOLISM\]\n',
            '\n', src, flags=re.DOTALL
        )
        with open(RUN_PY, "w") as f:
            f.write(cleaned)
        ok("metabolism patch removed from run.py")


def test_cycle():
    """Run one fast cycle to verify everything works end-to-end."""
    print("\n  Running test cycle...")
    result = subprocess.run(
        [sys.executable,
         os.path.join(NEX_DIR, "nex_metabolism.py"),
         "--now"],
        cwd=NEX_DIR,
        capture_output=False,
    )
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Install NEX metabolism system")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--undo",    action="store_true")
    parser.add_argument("--test",    action="store_true",
                        help="Test one cycle without patching run.py")
    args = parser.parse_args()

    print("\n  NEX Metabolism — Installer")
    print("  " + "─" * 44)

    if args.undo:
        undo_patch()
        return

    # 1. Copy modules
    print("\n  [1/4] Copying modules...")
    if not copy_modules(dry_run=args.dry_run):
        err("Some modules missing — check Downloads folder")
        sys.exit(1)

    # 2. Compile check all modules
    print("\n  [2/4] Compile checks...")
    all_ok = True
    for fname in MODULES:
        path = os.path.join(NEX_DIR, fname)
        if os.path.exists(path):
            if not compile_check(path):
                all_ok = False
        else:
            inf(f"{fname} not yet in place — skipping")

    if not compile_check(RUN_PY, "run.py (before patch)"):
        err("run.py has existing errors — fix those first")
        sys.exit(1)

    if not all_ok and not args.dry_run:
        err("Some modules have syntax errors — aborting")
        sys.exit(1)

    # 3. Optional test
    if args.test:
        print("\n  [3/4] Running test cycle...")
        if test_cycle():
            ok("test cycle passed")
        else:
            err("test cycle failed — check GROQ_API_KEY and module paths")
            sys.exit(1)
    else:
        print("\n  [3/4] Skipping live test (run with --test to verify first)")

    # 4. Patch run.py
    print("\n  [4/4] Patching run.py...")
    patch_run_py(dry_run=args.dry_run)

    if not args.dry_run:
        if compile_check(RUN_PY, "run.py (after patch)"):
            print(f"""
  ✓ Installation complete.

  Start NEX normally:
    python3 ~/Desktop/nex/run.py

  You'll see on startup:
    [METABOLISM] epistemic loop started — gap→crawl→distil→believe

  Manual controls:
    python3 ~/Desktop/nex/nex_metabolism.py --status       # gap report
    python3 ~/Desktop/nex/nex_metabolism.py --now          # one fast cycle
    python3 ~/Desktop/nex/nex_metabolism.py --slow         # full audit
    python3 ~/Desktop/nex/nex_metabolism.py --topic grief  # force topic
    python3 ~/Desktop/nex/nex_gap_detector.py              # gap scan only

  Undo:
    python3 install_metabolism.py --undo
""")
        else:
            err("Patch broke run.py — restoring backup")
            if os.path.exists(BACKUP_PATH):
                shutil.copy2(BACKUP_PATH, RUN_PY)
                ok("run.py restored")


if __name__ == "__main__":
    main()
