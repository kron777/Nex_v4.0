#!/usr/bin/env python3
"""
fix_nesting.py — Restores pre-r181 backup, re-injects r181 import only,
puts trainer tick at correct shallow indent outside all try/except chains.
"""
import ast, re, shutil, time, glob
from pathlib import Path

NEX = Path.home() / "Desktop/nex"
RUN = NEX / "run.py"

# ── 1. Find the pre-r181 backup ───────────────────────────────
backups = sorted(glob.glob(str(NEX / "run.py.bak_r181_*")))
if not backups:
    # Fall back to x160 backup
    backups = sorted(glob.glob(str(NEX / "run.py.bak_x160_*")))
if not backups:
    backups = sorted(glob.glob(str(NEX / "run.py.bak_e140_*")))

assert backups, "No suitable backup found"
backup = backups[-1]  # most recent
print(f"Restoring from: {Path(backup).name}")

# ── 2. Restore ────────────────────────────────────────────────
shutil.copy(RUN, str(RUN) + f".bak_before_nestfix_{int(time.time())}")
shutil.copy(backup, RUN)
src = RUN.read_text()
print(f"Restored — {len(src)} chars")

# ── 3. Verify r181 import exists (it's in the backup) ─────────
if "nex_r181" not in src:
    R181_IMPORT = (
        "\n# ── R161–R181 expression hardening stack ───────────────\n"
        "try:\n"
        "    from nex_upgrades.nex_r181 import get_r181 as _get_r181\n"
        "    _r181 = _get_r181()\n"
        "except Exception as _r181_ex:\n"
        "    print(f'[r181] Load failed: {_r181_ex}')\n"
        "    _r181 = None\n"
    )
    for anchor in ["    _x160 = None\n", "_x160 = None\n",
                   "    _e140 = None\n", "_e140 = None\n"]:
        idx = src.find(anchor)
        if idx != -1:
            src = src[:idx + len(anchor)] + R181_IMPORT + src[idx + len(anchor):]
            print(f"r181 import injected after {anchor.strip()!r}")
            break

# ── 4. Verify trainer import exists ───────────────────────────
if "nex_train_scheduler" not in src:
    TRAINER_IMPORT = (
        "\n# ── Autonomous training scheduler ──────────────────────\n"
        "try:\n"
        "    from nex_train_scheduler import get_scheduler as _get_scheduler\n"
        "    _trainer = _get_scheduler()\n"
        "except Exception as _trainer_ex:\n"
        "    print(f'[trainer] Load failed: {_trainer_ex}')\n"
        "    _trainer = None\n"
    )
    for anchor in ["    _r181 = None\n", "_r181 = None\n",
                   "    _x160 = None\n", "_x160 = None\n"]:
        idx = src.find(anchor)
        if idx != -1:
            src = src[:idx + len(anchor)] + TRAINER_IMPORT + src[idx + len(anchor):]
            print(f"trainer import injected after {anchor.strip()!r}")
            break

# ── 5. Find the while True loop body — inject trainer tick ─────
# Strategy: find `cycle += 1` and check its indent
# The while True body is at 20 spaces; cycle += 1 should be there
lines = src.splitlines(keepends=True)
insert_at = None
cycle_indent = 20

for i, ln in enumerate(lines):
    if re.search(r'\s*cycle\s*\+=\s*1\s*$', ln):
        indent = len(ln) - len(ln.lstrip())
        if indent <= 28:  # must be shallow (while True body)
            cycle_indent = indent
            insert_at = i + 1
            # Keep searching for the last occurrence
            
print(f"cycle += 1 found, inserting trainer tick after line {insert_at} "
      f"(indent={cycle_indent})")

pad = " " * cycle_indent

# Only add if not already present at this level
already_present = any(
    "_trainer.tick()" in lines[j] and
    abs((len(lines[j]) - len(lines[j].lstrip())) - cycle_indent) <= 4
    for j in range(max(0, insert_at-5), min(len(lines), insert_at+5))
    if insert_at
)

if not already_present and insert_at:
    TICK = [
        f"\n",
        f"{pad}# ── Training scheduler ─────────────────────────────\n",
        f"{pad}if '_trainer' in dir() and _trainer is not None:\n",
        f"{pad}    _trainer.tick()\n",
    ]
    for k, bl in enumerate(TICK):
        lines.insert(insert_at + k, bl)
    print(f"Trainer tick injected at line {insert_at} (indent={cycle_indent})")
else:
    print("Trainer tick already present or no anchor — skipping")

src = "".join(lines)

# ── 6. AST check ──────────────────────────────────────────────
try:
    ast.parse(src)
    print("AST OK ✓")
except SyntaxError as e:
    all_lines = src.splitlines()
    print(f"SyntaxError line {e.lineno}: {e.msg}")
    for j in range(max(0, e.lineno-4), min(len(all_lines), e.lineno+4)):
        print(f"  {j+1:4d}  {all_lines[j]}")
    raise SystemExit(1)

RUN.write_text(src)
print(f"run.py written ({len(src)} chars)")
print("Done — run: pkill -f run.py; sleep 2; nex")
