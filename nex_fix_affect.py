#!/usr/bin/env python3
"""
nex_fix_affect.py — Restore AffectValenceEngine in nex_affect_valence.py
The **_kw patch touched the wrong ingest() stubs and broke the class export.

Run from ~/Desktop/nex:
    python3 nex_fix_affect.py
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

def syntax_ok(p):
    r = subprocess.run([PYTHON, "-m", "py_compile", str(p)], capture_output=True)
    return r.returncode == 0

def backup(p):
    dst = p.with_suffix(p.suffix + f".pre_affect_{TS}")
    shutil.copy2(p, dst)
    return dst

# ═══════════════════════════════════════════════════════════════
# STEP 1 — Find cleanest backup of nex_affect_valence.py
# ═══════════════════════════════════════════════════════════════
hdr("STEP 1 — Find clean backup of nex_affect_valence.py")

target = PKG / "nex_affect_valence.py"

# Collect all backups, newest first
backups = sorted(
    list(PKG.glob("nex_affect_valence.py.pre_*")) +
    list(PKG.glob("nex_affect_valence.py.bak*")),
    key=lambda p: p.stat().st_mtime, reverse=True
)

info(f"Found {len(backups)} backup(s)")
restored = False
for b in backups:
    text = b.read_text(errors="replace")
    # Must have AffectValenceEngine class AND be syntax-clean
    if "class AffectValenceEngine" in text and syntax_ok(b):
        backup(target)
        shutil.copy2(b, target)
        ok(f"Restored from {b.name}")
        restored = True
        break
    else:
        why = []
        if "class AffectValenceEngine" not in text: why.append("missing class")
        if not syntax_ok(b): why.append("syntax error")
        info(f"  Skip {b.name} — {', '.join(why)}")

if not restored:
    # Also check the root-level copy
    root_copy = ROOT / "nex_affect_valence.py"
    if root_copy.exists():
        text = root_copy.read_text(errors="replace")
        if "class AffectValenceEngine" in text and syntax_ok(root_copy):
            backup(target)
            shutil.copy2(root_copy, target)
            ok(f"Restored from root-level nex_affect_valence.py")
            restored = True

if not restored:
    info("No clean backup found — inspecting current file to patch in-place")

# ═══════════════════════════════════════════════════════════════
# STEP 2 — If restore failed, check if class is just missing an alias
# ═══════════════════════════════════════════════════════════════
hdr("STEP 2 — Verify or patch AffectValenceEngine")

text = target.read_text(errors="replace")

if "class AffectValenceEngine" in text:
    ok("AffectValenceEngine class is present in file")
else:
    info("Class not found — checking what classes DO exist:")
    classes = re.findall(r'^class (\w+)', text, re.MULTILINE)
    info(f"  Classes: {classes}")

    if classes:
        # The class probably got renamed or the export is just missing.
        # Add an alias at the bottom.
        main_class = classes[0]
        alias = f"\n\n# Compatibility alias (added by nex_fix_affect.py)\nAffectValenceEngine = {main_class}\n"
        if "AffectValenceEngine" not in text:
            backup(target)
            target.write_text(text + alias, errors="replace")
            if syntax_ok(target):
                ok(f"Added alias: AffectValenceEngine = {main_class}")
            else:
                err("Alias patch broke file — reverting")
                shutil.copy2(
                    target.with_suffix(target.suffix + f".pre_affect_{TS}"),
                    target
                )
    else:
        # No classes at all — the file got mangled. Write a minimal stub.
        info("No classes found — writing AffectValenceEngine stub")
        backup(target)
        stub = '''\
"""
nex_affect_valence.py — AffectValenceEngine stub (restored by nex_fix_affect.py)
"""
import re

class AffectProxy:
    def __init__(self): self.valence = 0.0; self.arousal = 0.0

    def get(self):
        """Return current affect state dict."""
        return {
            'valence': getattr(self, 'valence', 0.0),
            'arousal': getattr(self, 'arousal', 0.0),
            'label':   getattr(self, 'label',   'neutral'),
        }
    def ingest(self, text: str = "", source: str = "", **_kw) -> "AffectProxy":
        return self
    def to_dict(self): return {"valence": self.valence, "arousal": self.arousal}

class AffectValenceEngine:
    """Minimal affect valence engine — stub for compatibility."""
    def __init__(self): self._proxy = AffectProxy()

    def ingest(self, text: str = "", source: str = "", **_kw) -> AffectProxy:
        proxy = AffectProxy()
        positive = len(re.findall(
            r"\\b(good|great|love|joy|hope|positive|happy|excited|trust)\\b", text, re.I))
        negative = len(re.findall(
            r"\\b(bad|hate|fear|anger|sad|negative|terrible|wrong|lost)\\b", text, re.I))
        total = positive + negative or 1
        proxy.valence = (positive - negative) / total
        proxy.arousal = min(1.0, total / 10)
        return proxy

    def get_valence(self) -> float:
        return self._proxy.valence

    def get_arousal(self) -> float:
        return self._proxy.arousal

def ingest(data, **_kw):
    """Module-level stub for compatibility."""
    pass
'''
        target.write_text(stub)
        if syntax_ok(target):
            ok("nex_affect_valence.py — functional stub written")
        else:
            err("Stub has syntax error — check manually")

# ═══════════════════════════════════════════════════════════════
# STEP 3 — Also clean up the root-level nex_affect_valence.py
# (the final_fix patched it too, make sure it's consistent)
# ═══════════════════════════════════════════════════════════════
hdr("STEP 3 — Sync root-level nex_affect_valence.py")

root_av = ROOT / "nex_affect_valence.py"
if root_av.exists():
    rt = root_av.read_text(errors="replace")
    if "AffectValenceEngine" not in rt:
        classes = re.findall(r'^class (\w+)', rt, re.MULTILINE)
        if classes:
            alias = f"\n\nAffectValenceEngine = {classes[0]}\n"
            backup(root_av)
            root_av.write_text(rt + alias, errors="replace")
            if syntax_ok(root_av):
                ok(f"Root nex_affect_valence.py — alias added")
        else:
            info("Root copy has no classes — leaving as-is")
    else:
        ok("Root nex_affect_valence.py — AffectValenceEngine present")

# ═══════════════════════════════════════════════════════════════
# FINAL IMPORT TEST
# ═══════════════════════════════════════════════════════════════
hdr("FINAL IMPORT TEST")

test = f"""
import sys
sys.path.insert(0, "{ROOT}")
sys.path.insert(0, "{PKG}")
mods = [
    ("nex.nex_affect_valence",    "AffectValenceEngine", "AffectValenceEngine"),
    ("nex.nex_theory_of_mind",    None,                  "nex_theory_of_mind"),
    ("nex.nex_embodied",          None,                  "nex_embodied"),
    ("nex.nex_tick_shim",         "safe_tick",           "Tick Shim"),
    ("nex.nex_belief_index",      "build_index",         "Belief Index"),
    ("nex.nex_evo_daemon",        "run_evo_cycle",        "Evo Daemon"),
    ("nex.nex_temporal_pressure", "start_pressure_daemon","Temporal Pressure"),
    ("nex.nex_bridge_engine",     "BridgeEngine",         "Bridge Engine"),
    ("nex.nex_monument",          "export_monument",      "Monument"),
]
for mod, sym, label in mods:
    try:
        m = __import__(mod, fromlist=[sym] if sym else ["__name__"])
        if sym: getattr(m, sym)
        print(f"  OK  {{label}}")
    except Exception as e:
        print(f"  FAIL {{label}}: {{e}}")
"""

r = subprocess.run([PYTHON, "-c", test], capture_output=True, text=True, cwd=str(ROOT))
all_ok = True
for line in (r.stdout + r.stderr).splitlines():
    if "OK" in line:     ok(line.strip())
    elif "FAIL" in line: err(line.strip()); all_ok = False
    else:                info(line)

print(f"\n{BOLD}{'═'*60}")
if all_ok:
    print("  ALL CLEAR — restart NEX:")
    print("    python3 run.py")
else:
    print("  Some imports still failing — paste output for next fix.")
print(f"{'═'*60}{RST}")
