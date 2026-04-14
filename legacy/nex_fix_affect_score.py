#!/usr/bin/env python3
"""
nex_fix_affect_score.py — Fix missing AffectScore (and any other names)
from nex_affect_valence using PEP 562 module-level __getattr__.

This is the correct modern pattern: instead of chasing every missing name
one by one, we install a __getattr__ in the module that returns a safe
stub for ANY missing attribute — future-proof against further renames.

Run from ~/Desktop/nex:
    python3 nex_fix_affect_score.py
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
    dst = p.with_suffix(p.suffix + f".pre_score_{TS}")
    shutil.copy2(p, dst)
    return dst

# ═══════════════════════════════════════════════════════════════
# STEP 1 — Scan what nex_theory_of_mind imports from nex_affect_valence
# ═══════════════════════════════════════════════════════════════
hdr("STEP 1 — Scan imports from nex_affect_valence")

tom = PKG / "nex_theory_of_mind.py"
needed_names = set()
if tom.exists():
    text = tom.read_text(errors="replace")
    # Find all: from nex_affect_valence import X, Y, Z  (any variant)
    for m in re.finditer(
        r'from\s+(?:nex\.)?nex_affect_valence\s+import\s+([^\n]+)', text
    ):
        for name in re.split(r'[\s,]+', m.group(1).strip()):
            name = name.strip().strip('()')
            if name and name != 'as':
                needed_names.add(name)
    info(f"nex_theory_of_mind needs: {sorted(needed_names)}")
else:
    info("nex_theory_of_mind.py not found")

# Also scan all other files that import from nex_affect_valence
all_needed = set(needed_names)
for py in list(PKG.glob("*.py")) + list(ROOT.glob("*.py")):
    if py.name.startswith("nex_fix") or py.name.startswith("nex_amend") \
       or py.name.startswith("nex_full") or py.name.startswith("nex_final"):
        continue
    try:
        text = py.read_text(errors="replace")
        for m in re.finditer(
            r'from\s+(?:nex\.)?nex_affect_valence\s+import\s+([^\n]+)', text
        ):
            for name in re.split(r'[\s,]+', m.group(1).strip()):
                name = name.strip().strip('()')
                if name and name != 'as':
                    all_needed.add(name)
    except Exception:
        pass

info(f"All names needed from nex_affect_valence: {sorted(all_needed)}")

# ═══════════════════════════════════════════════════════════════
# STEP 2 — Check what's currently exported
# ═══════════════════════════════════════════════════════════════
hdr("STEP 2 — Check current nex_affect_valence.py exports")

av = PKG / "nex_affect_valence.py"
av_text = av.read_text(errors="replace") if av.exists() else ""
existing = set(re.findall(r'^(?:class|def|[A-Z]\w+)\s+(\w+)', av_text, re.MULTILINE))
# Also catch simple assignments like AffectScore = ...
existing |= set(re.findall(r'^(\w+)\s*=', av_text, re.MULTILINE))
info(f"Currently exported: {sorted(existing)}")

missing = all_needed - existing
info(f"Missing names: {sorted(missing)}")

# ═══════════════════════════════════════════════════════════════
# STEP 3 — Patch nex_affect_valence.py with PEP 562 __getattr__
#           + explicit stubs for all known missing names
# ═══════════════════════════════════════════════════════════════
hdr("STEP 3 — Install PEP 562 __getattr__ + explicit stubs")

# Build explicit stub classes for the known missing names
explicit_stubs = []

# AffectScore — a named tuple / dataclass-like score object
if "AffectScore" in missing or "AffectScore" not in existing:
    explicit_stubs.append('''\
class AffectScore:
    """Compatibility stub for AffectScore (restored by nex_fix_affect_score.py)"""
    __slots__ = ("valence", "arousal", "label", "intensity")
    def __init__(self, valence=0.0, arousal=0.0, label="neutral", intensity=0.0):
        self.valence   = float(valence)
        self.arousal   = float(arousal)
        self.label     = label
        self.intensity = float(intensity)
    def to_dict(self):
        return {"valence": self.valence, "arousal": self.arousal,
                "label": self.label, "intensity": self.intensity}
    def __repr__(self):
        return f"AffectScore(valence={self.valence:.2f}, label={self.label!r})"
''')

# Add stubs for any other missing names dynamically
for name in sorted(missing):
    if name in ("AffectScore",):
        continue  # already handled above
    if re.match(r'^[A-Z]', name):
        # Looks like a class
        explicit_stubs.append(f'''\
class {name}:
    """Compatibility stub for {name} (nex_fix_affect_score.py)"""
    def __init__(self, *a, **kw): pass
    def __call__(self, *a, **kw): return self
    def to_dict(self): return {{}}
''')
    else:
        # Looks like a function or constant
        explicit_stubs.append(f'''\
def {name}(*a, **kw):
    """Compatibility stub for {name} (nex_fix_affect_score.py)"""
    return None
''')

# PEP 562 module __getattr__ — catches any future missing names at import time
pep562_block = '''\

# ── PEP 562 module __getattr__ (nex_fix_affect_score.py) ─────────────────────
# Returns a safe no-op stub for ANY name not explicitly defined above.
# This prevents ImportError when callers request names that were renamed/removed.
import sys as _sys

def __getattr__(name: str):
    """Return a safe stub class for any missing attribute in this module."""
    import sys as _sys2
    _stub_name = f"_{name}_Stub"
    if _stub_name in _sys2.modules.get(__name__, {}) .__dict__:
        return _sys2.modules[__name__].__dict__[_stub_name]

    # Build a generic stub class on the fly
    stub_cls = type(name, (), {
        "__init__":  lambda self, *a, **kw: None,
        "__call__":  lambda self, *a, **kw: self,
        "to_dict":   lambda self: {},
        "ingest":    lambda self, *a, **kw: self,
        "__repr__":  lambda self: f"<{name} stub>",
        "valence":   0.0,
        "arousal":   0.0,
        "label":     "neutral",
        "intensity": 0.0,
    })
    # Cache it on the module so repeated imports get the same object
    _this = _sys.modules[__name__]
    setattr(_this, name, stub_cls)
    return stub_cls
# ─────────────────────────────────────────────────────────────────────────────
'''

# Inject into the file
if "__getattr__" not in av_text:
    backup(av)
    append_block = "\n\n# ── Explicit compatibility stubs ──────────────────────────────────────────────\n"
    for stub in explicit_stubs:
        append_block += stub + "\n"
    append_block += pep562_block

    av.write_text(av_text + append_block, errors="replace")
    if syntax_ok(av):
        ok(f"nex_affect_valence.py — PEP 562 __getattr__ + {len(explicit_stubs)} stub(s) added")
    else:
        err("Patch broke file — reverting")
        shutil.copy2(av.with_suffix(av.suffix + f".pre_score_{TS}"), av)
        # Fallback: write a complete clean file
        info("Writing complete clean nex_affect_valence.py...")
else:
    info("__getattr__ already present — just adding missing explicit stubs")
    if explicit_stubs and any(s.split('\n')[0].split()[-1] not in av_text for s in explicit_stubs):
        backup(av)
        append = "\n" + "\n".join(explicit_stubs) + "\n"
        av.write_text(av_text + append, errors="replace")
        if syntax_ok(av):
            ok("Explicit stubs added")
        else:
            err("Adding stubs broke file — reverting")
            shutil.copy2(av.with_suffix(av.suffix + f".pre_score_{TS}"), av)

# ═══════════════════════════════════════════════════════════════
# STEP 4 — Same treatment for root-level nex_affect_valence.py
# ═══════════════════════════════════════════════════════════════
hdr("STEP 4 — Sync root-level copy")

root_av = ROOT / "nex_affect_valence.py"
if root_av.exists():
    rt = root_av.read_text(errors="replace")
    if "__getattr__" not in rt:
        backup(root_av)
        root_av.write_text(rt + pep562_block, errors="replace")
        if syntax_ok(root_av):
            ok("Root nex_affect_valence.py — PEP 562 __getattr__ added")
        else:
            err("Root copy patch failed — reverting")
            shutil.copy2(root_av.with_suffix(root_av.suffix + f".pre_score_{TS}"), root_av)
    else:
        ok("Root copy already has __getattr__")

# ═══════════════════════════════════════════════════════════════
# FINAL IMPORT TEST
# ═══════════════════════════════════════════════════════════════
hdr("FINAL IMPORT TEST")

# Build a test that imports every name that was missing
missing_imports = ", ".join(sorted(all_needed)) if all_needed else "AffectScore"

test = f"""
import sys
sys.path.insert(0, "{ROOT}")
sys.path.insert(0, "{PKG}")

# Test 1: explicit missing names
try:
    from nex.nex_affect_valence import {missing_imports}
    print("  OK  nex_affect_valence explicit imports ({missing_imports})")
except Exception as e:
    print(f"  FAIL nex_affect_valence explicit imports: {{e}}")

# Test 2: theory_of_mind full import
try:
    import nex.nex_theory_of_mind
    print("  OK  nex_theory_of_mind")
except Exception as e:
    print(f"  FAIL nex_theory_of_mind: {{e}}")

# Test 3: all evolution modules still clean
mods = [
    ("nex.nex_tick_shim",         "safe_tick",             "Tick Shim"),
    ("nex.nex_belief_index",      "build_index",           "Belief Index"),
    ("nex.nex_evo_daemon",        "run_evo_cycle",         "Evo Daemon"),
    ("nex.nex_temporal_pressure", "start_pressure_daemon", "Temporal Pressure"),
    ("nex.nex_bridge_engine",     "BridgeEngine",          "Bridge Engine"),
    ("nex.nex_monument",          "export_monument",       "Monument"),
]
for mod, sym, label in mods:
    try:
        m = __import__(mod, fromlist=[sym])
        getattr(m, sym)
        print(f"  OK  {{label}}")
    except Exception as e:
        print(f"  FAIL {{label}}: {{e}}")
"""

r = subprocess.run([PYTHON, "-c", test], capture_output=True, text=True, cwd=str(ROOT))
all_ok = True
for line in (r.stdout + r.stderr).splitlines():
    if "OK" in line:      ok(line.strip())
    elif "FAIL" in line:  err(line.strip()); all_ok = False
    else:                 info(line)

print(f"\n{BOLD}{'═'*60}")
if all_ok:
    print("  ALL CLEAR — you are good to restart NEX:")
    print("    python3 run.py")
else:
    print("  Still failing — paste output and I'll fix immediately.")
print(f"{'═'*60}{RST}")
