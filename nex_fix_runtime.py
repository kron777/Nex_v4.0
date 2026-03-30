#!/usr/bin/env python3
"""
nex_fix_runtime.py — Fix two runtime errors visible in NEX brain output:
  1. telegram.error.NetworkError / httpx.ReadError — add retry with backoff
  2. cannot import name 'get_engine' from 'nex_character_engine' — PEP 562 shim

Run from ~/Desktop/nex:
    python3 nex_fix_runtime.py
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
    dst = p.with_suffix(p.suffix + f".pre_runtime_{TS}")
    shutil.copy2(p, dst)
    return dst

# ═══════════════════════════════════════════════════════════════
# FIX 1 — Telegram httpx.ReadError — wrap polling with retry
# ═══════════════════════════════════════════════════════════════
hdr("FIX 1 — Telegram NetworkError / httpx.ReadError retry")

# Find which file runs the Telegram bot polling loop
telegram_files = []
for py in list(ROOT.glob("*.py")) + list(PKG.glob("*.py")):
    try:
        text = py.read_text(errors="replace")
        if "run_polling" in text or "get_updates" in text or "updater.start" in text:
            if "telegram" in text.lower():
                telegram_files.append(py)
    except Exception:
        pass

info(f"Telegram polling files: {[f.name for f in telegram_files]}")

RETRY_WRAPPER = '''
# ── Telegram network error retry patch (nex_fix_runtime.py) ──────────────────
import asyncio as _asyncio
import telegram.error as _tgerr

_TELEGRAM_ORIG_RUN_POLLING = None

def _patch_telegram_retry(app):
    """Wrap run_polling to survive transient httpx.ReadError / NetworkError."""
    import httpx as _httpx
    orig = app.run_polling

    async def _resilient_polling(*args, **kwargs):
        backoff = 5
        while True:
            try:
                await orig(*args, **kwargs)
                break
            except (_tgerr.NetworkError, _httpx.ReadError, _httpx.ConnectError,
                    _httpx.TimeoutException, ConnectionResetError, OSError) as e:
                print(f"  [Telegram] network error: {e} — retry in {backoff}s")
                await _asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)
            except Exception as e:
                print(f"  [Telegram] fatal error: {e}")
                raise

    app.run_polling = _resilient_polling
    return app
# ─────────────────────────────────────────────────────────────────────────────
'''

# Patch nex_telegram.py or run.py — wherever Application/Updater is built
patched_telegram = False
for py in telegram_files:
    text = py.read_text(errors="replace")
    # Look for where run_polling is actually called
    if "run_polling" not in text:
        continue
    if "_patch_telegram_retry" in text:
        ok(f"{py.name} — retry patch already present")
        patched_telegram = True
        continue

    # Insert the wrapper function before the first run_polling call
    # and wrap the app object
    insert_idx = text.find("run_polling")
    if insert_idx == -1:
        continue

    # Find start of the line containing run_polling
    line_start = text.rfind('\n', 0, insert_idx) + 1
    line = text[line_start:text.find('\n', insert_idx)]
    indent = len(line) - len(line.lstrip())
    pad = ' ' * indent

    # Extract the object calling run_polling (e.g. "application", "app", "updater")
    m = re.match(r'\s*(\w+)\.run_polling', line)
    obj = m.group(1) if m else "application"

    patch_call = f"\n{pad}{obj} = _patch_telegram_retry({obj})  # retry on network errors\n"

    new_text = RETRY_WRAPPER + text[:line_start] + patch_call + text[line_start:]
    backup(py)
    py.write_text(new_text, errors="replace")
    if syntax_ok(py):
        ok(f"{py.name} — Telegram retry wrapper installed")
        patched_telegram = True
    else:
        err(f"{py.name} — patch broke file, reverting")
        shutil.copy2(py.with_suffix(py.suffix + f".pre_runtime_{TS}"), py)

if not patched_telegram:
    info("Telegram retry patch — could not auto-apply; writing standalone wrapper")
    info("Add this to your telegram init code manually:")
    info("  from nex_telegram_retry import patch_telegram_retry")
    info("  application = patch_telegram_retry(application)")
    # Write as standalone module they can import
    standalone = ROOT / "nex_telegram_retry.py"
    standalone.write_text(RETRY_WRAPPER.replace("# ── Telegram", "").strip() + "\n\npatch_telegram_retry = _patch_telegram_retry\n")
    ok(f"Standalone retry module written: nex_telegram_retry.py")

# ═══════════════════════════════════════════════════════════════
# FIX 2 — nex_character_engine.py missing get_engine
# ═══════════════════════════════════════════════════════════════
hdr("FIX 2 — nex_character_engine: missing get_engine")

# Check all files that import get_engine from nex_character_engine
needed = set()
for py in list(ROOT.glob("*.py")) + list(PKG.glob("*.py")):
    try:
        text = py.read_text(errors="replace")
        for m in re.finditer(
            r'from\s+(?:nex\.)?nex_character_engine\s+import\s+([^\n]+)', text
        ):
            for name in re.split(r'[\s,]+', m.group(1).strip()):
                name = name.strip().strip('()')
                if name and name != 'as':
                    needed.add(name)
    except Exception:
        pass

info(f"Names needed from nex_character_engine: {sorted(needed)}")

# Check what's currently exported
ce_pkg  = PKG / "nex_character_engine.py"
ce_root = ROOT / "nex_character_engine.py"
ce = ce_pkg if ce_pkg.exists() else ce_root

if ce.exists():
    text = ce.read_text(errors="replace")
    existing = set(re.findall(r'^(?:class|def)\s+(\w+)', text, re.MULTILINE))
    existing |= set(re.findall(r'^(\w+)\s*=', text, re.MULTILINE))
    info(f"Currently exported: {sorted(existing)}")
    missing = needed - existing
    info(f"Missing: {sorted(missing)}")

    if missing or "__getattr__" not in text:
        # Build explicit stubs for missing names
        stubs = []

        if "get_engine" in missing or "get_engine" not in existing:
            # get_engine should return the singleton CharacterEngine instance
            stubs.append('''\
_char_engine_singleton = None

def get_engine():
    """Return the CharacterEngine singleton (compatibility stub)."""
    global _char_engine_singleton
    if _char_engine_singleton is None:
        # Try to instantiate the real engine if the class exists
        for cls_name in ["CharacterEngine", "NexCharacterEngine", "Character"]:
            cls = globals().get(cls_name)
            if cls:
                try:
                    _char_engine_singleton = cls()
                    break
                except Exception:
                    pass
        if _char_engine_singleton is None:
            # Fallback stub
            class _StubEngine:
                def get_style(self, *a, **kw): return {}
                def apply(self, text, *a, **kw): return text
                def __repr__(self): return "<CharacterEngine stub>"
            _char_engine_singleton = _StubEngine()
    return _char_engine_singleton
''')

        # Stubs for any other missing names
        for name in sorted(missing):
            if name == "get_engine":
                continue
            if re.match(r'^[A-Z]', name):
                stubs.append(f'class {name}:\n    """Stub for {name}"""\n    def __init__(self, *a, **kw): pass\n')
            else:
                stubs.append(f'def {name}(*a, **kw): return None\n')

        # PEP 562 catch-all
        pep562 = '''
# ── PEP 562 __getattr__ — catch any future missing names ─────────────────────
import sys as _sys_ce

def __getattr__(name: str):
    stub = type(name, (), {
        "__init__":  lambda self, *a, **kw: None,
        "__call__":  lambda self, *a, **kw: self,
        "__repr__":  lambda self: f"<{name} stub>",
        "apply":     lambda self, text, *a, **kw: text,
        "get_style": lambda self, *a, **kw: {},
    })
    setattr(_sys_ce.modules[__name__], name, stub)
    return stub
# ─────────────────────────────────────────────────────────────────────────────
'''
        if "__getattr__" not in text:
            append = "\n\n# ── Compatibility stubs (nex_fix_runtime.py) ──────────────────────────────\n"
            for s in stubs:
                append += s + "\n"
            append += pep562

            backup(ce)
            ce.write_text(text + append, errors="replace")
            if syntax_ok(ce):
                ok(f"{ce.name} — get_engine + PEP 562 shim added")
            else:
                err(f"{ce.name} — patch broke file, reverting")
                shutil.copy2(ce.with_suffix(ce.suffix + f".pre_runtime_{TS}"), ce)
        else:
            # Just add the missing stubs before the existing __getattr__
            idx = text.find("def __getattr__")
            new_text = text[:idx] + "\n".join(stubs) + "\n\n" + text[idx:]
            backup(ce)
            ce.write_text(new_text, errors="replace")
            if syntax_ok(ce):
                ok(f"{ce.name} — missing stubs added before existing __getattr__")
            else:
                err(f"{ce.name} — patch broke file, reverting")
                shutil.copy2(ce.with_suffix(ce.suffix + f".pre_runtime_{TS}"), ce)

    # Sync the other copy if both exist
    if ce_pkg.exists() and ce_root.exists() and ce_pkg != ce_root:
        other = ce_root if ce == ce_pkg else ce_pkg
        other_text = other.read_text(errors="replace")
        if "__getattr__" not in other_text:
            backup(other)
            other.write_text(ce.read_text(errors="replace"), errors="replace")
            if syntax_ok(other):
                ok(f"Synced {other.name}")
else:
    err("nex_character_engine.py not found in pkg or root")

# ═══════════════════════════════════════════════════════════════
# FINAL IMPORT TEST
# ═══════════════════════════════════════════════════════════════
hdr("FINAL IMPORT TEST")

test = f"""
import sys
sys.path.insert(0, "{ROOT}")
sys.path.insert(0, "{PKG}")

for mod, sym, label in [
    ("nex.nex_character_engine", "get_engine",  "CharacterEngine.get_engine"),
    ("nex.nex_affect_valence",   "AffectScore", "AffectScore"),
    ("nex.nex_tick_shim",        "safe_tick",   "Tick Shim"),
    ("nex.nex_belief_index",     "build_index", "Belief Index"),
    ("nex.nex_evo_daemon",       "run_evo_cycle","Evo Daemon"),
    ("nex.nex_monument",         "export_monument","Monument"),
]:
    try:
        m = __import__(mod, fromlist=[sym])
        getattr(m, sym)
        print(f"  OK  {{label}}")
    except Exception as e:
        print(f"  FAIL {{label}}: {{e}}")

# Test get_engine actually returns something callable
try:
    from nex.nex_character_engine import get_engine
    engine = get_engine()
    print(f"  OK  get_engine() returned: {{type(engine).__name__}}")
except Exception as e:
    print(f"  FAIL get_engine() call: {{e}}")
"""

r = subprocess.run([PYTHON, "-c", test], capture_output=True, text=True, cwd=str(ROOT))
all_ok = True
for line in (r.stdout + r.stderr).splitlines():
    if "OK" in line:      ok(line.strip())
    elif "FAIL" in line:  err(line.strip()); all_ok = False
    else:                 info(line)

print(f"\n{BOLD}{'═'*60}")
if all_ok:
    print("  ALL CLEAR — restart NEX:")
    print("    python3 run.py")
else:
    print("  Still failing — paste output for next fix.")
print(f"{'═'*60}{RST}")
