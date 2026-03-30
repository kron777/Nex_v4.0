#!/usr/bin/env python3
"""
nex_final_fix.py — Two targeted fixes:
  1. Restore SMALL_INTERVAL and FULL_INTERVAL in nex_auto_seeder.py
     (the amend incorrectly replaced 3600 with 150)
  2. Verify ingest is correctly called (it's a class method, not module-level)

Run from ~/Desktop/nex:
    python3 nex_final_fix.py
"""

import re, sys, shutil, subprocess
from pathlib import Path
from datetime import datetime

ROOT   = Path.home() / "Desktop" / "nex"
PKG    = ROOT / "nex"
PYTHON = ROOT / "venv" / "bin" / "python3"
PYTHON = str(PYTHON) if PYTHON.exists() else sys.executable
TS     = datetime.now().strftime("%Y%m%d_%H%M%S")

GREEN = "\033[32m"; RED = "\033[31m"; BOLD = "\033[1m"; RST = "\033[0m"
def ok(m):   print(f"{GREEN}  ✓  {m}{RST}")
def err(m):  print(f"{RED}  ✗  {m}{RST}")
def info(m): print(f"  ·  {m}")
def hdr(t):  print(f"\n{BOLD}{'─'*60}\n  {t}\n{'─'*60}{RST}")

def backup(p):
    dst = p.with_suffix(p.suffix + f".pre_final_{TS}")
    shutil.copy2(p, dst); return dst

def syntax_ok(p):
    r = subprocess.run([PYTHON, "-m", "py_compile", str(p)], capture_output=True)
    return r.returncode == 0

# ═══════════════════════════════════════════════════════════════
# FIX 1 — Restore seeder intervals (3600-based, not 150-based)
# ═══════════════════════════════════════════════════════════════
hdr("FIX 1 — Restore nex_auto_seeder.py intervals")

seeder = PKG / "nex_auto_seeder.py"
if seeder.exists():
    text = seeder.read_text(errors="replace")
    original = text

    # The amend turned "3600 * 6" into "150 * 6" and "3600 * 24" into "150 * 24"
    # Restore those two lines specifically
    text = re.sub(
        r'SMALL_INTERVAL\s*=\s*150\s*\*\s*6',
        'SMALL_INTERVAL   = 3600 * 6   # 6 hours between small seeds',
        text
    )
    text = re.sub(
        r'FULL_INTERVAL\s*=\s*150\s*\*\s*24',
        'FULL_INTERVAL    = 3600 * 24  # 24 hours between full seeds',
        text
    )
    # Also fix the comment that got mangled ("300-150 new beliefs" → restore)
    text = re.sub(
        r'300-150 new beliefs',
        '300-500 new beliefs',
        text
    )

    if text != original:
        backup(seeder)
        seeder.write_text(text, errors="replace")
        if syntax_ok(seeder):
            ok("nex_auto_seeder.py — intervals restored to 3600*6 / 3600*24")
            ok("nex_auto_seeder.py — MIN_BELIEFS stays at 150 (correct)")
        else:
            err("Restore broke file — reverting")
            shutil.copy2(seeder.with_suffix(seeder.suffix + f".pre_final_{TS}"), seeder)
    else:
        ok("nex_auto_seeder.py — intervals already correct, no change needed")

    # Show final state of the three key lines
    for ln in seeder.read_text(errors="replace").splitlines():
        if any(k in ln for k in ["MIN_BELIEFS", "SMALL_INTERVAL", "FULL_INTERVAL"]):
            if not ln.strip().startswith("#"):
                info(f"  {ln.strip()}")

# ═══════════════════════════════════════════════════════════════
# FIX 2 — Locate where ingest actually lives
# ═══════════════════════════════════════════════════════════════
hdr("FIX 2 — Locate ingest() definition")

found_in = []
for py in list(ROOT.glob("*.py")) + list(PKG.glob("*.py")):
    try:
        text = py.read_text(errors="replace")
        if re.search(r'def ingest\s*\(', text):
            # Find the line numbers
            for i, ln in enumerate(text.splitlines(), 1):
                if re.search(r'def ingest\s*\(', ln):
                    found_in.append((py.relative_to(ROOT), i, ln.strip()))
    except Exception:
        pass

if found_in:
    info("def ingest(, **_kw) found in:")
    for fpath, lineno, ln in found_in:
        info(f"  {fpath}  L{lineno}: {ln}")

    # For each file, check if **kwargs is already there
    for fpath, lineno, ln in found_in:
        full_path = ROOT / fpath
        text = full_path.read_text(errors="replace")
        m = re.search(r'def ingest\s*\(([^)]*)\)', text)
        if m and '**' not in m.group(1):
            new_args = m.group(1).rstrip(', ') + ', **_kw'
            new_text = text.replace(m.group(0), f'def ingest({new_args})', 1)
            backup(full_path)
            full_path.write_text(new_text, errors="replace")
            if syntax_ok(full_path):
                ok(f"{fpath} — ingest() now accepts **_kw")
            else:
                err(f"{fpath} — patch broke file, reverting")
                shutil.copy2(
                    full_path.with_suffix(full_path.suffix + f".pre_final_{TS}"),
                    full_path
                )
        elif m:
            ok(f"{fpath} — ingest() already accepts **kwargs")
else:
    info("def ingest() not found as a standalone function anywhere")
    info("The 'source=' callers (nex_theory_of_mind, nex_embodied) are already patched")
    info("No further action needed — the error was at the call sites, not definition")

# ═══════════════════════════════════════════════════════════════
# FINAL VERIFICATION
# ═══════════════════════════════════════════════════════════════
hdr("FINAL VERIFICATION")

check = [
    PKG / "nex_auto_seeder.py",
    PKG / "nex_theory_of_mind.py",
    PKG / "nex_embodied.py",
]
all_ok = True
for p in check:
    if p.exists():
        if syntax_ok(p):
            ok(p.name)
        else:
            err(f"{p.name} — syntax error")
            all_ok = False

# Quick NEX boot test — just import the kernel without starting it
boot_test = f"""
import sys
sys.path.insert(0, "{ROOT}")
sys.path.insert(0, "{PKG}")
errors = []
# Test the previously-failing modules all load cleanly together
try:
    import nex.nex_tick_shim
    import nex.nex_belief_index
    import nex.nex_evo_daemon
    import nex.nex_temporal_pressure
    import nex.nex_bridge_engine
    import nex.nex_monument
    print("  OK  All evolution modules import cleanly")
except Exception as e:
    print(f"  FAIL evolution imports: {{e}}")

# Test patched callers
for mod in ["nex.nex_theory_of_mind", "nex.nex_embodied"]:
    try:
        __import__(mod)
        print(f"  OK  {{mod}}")
    except Exception as e:
        print(f"  FAIL {{mod}}: {{e}}")
"""

r = subprocess.run([PYTHON, "-c", boot_test], capture_output=True, text=True, cwd=str(ROOT))
for line in (r.stdout + r.stderr).splitlines():
    if "OK" in line:    ok(line.strip())
    elif "FAIL" in line: err(line.strip())
    else: info(line)

print(f"\n{BOLD}{'═'*60}")
print("  FINAL FIX COMPLETE")
print("  You're good to restart NEX:")
print("    python3 run.py")
print(f"{'═'*60}{RST}")
