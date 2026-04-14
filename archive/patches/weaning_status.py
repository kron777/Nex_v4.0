#!/usr/bin/env python3
"""
weaning_status.py — Standalone Nex independence metrics.
Does NOT import any nex module (avoids full stack startup).
Run directly: python3 ~/Desktop/nex/weaning_status.py
"""
import sqlite3
import json
import re
from pathlib import Path

CFG    = Path("~/.config/nex").expanduser()
DB     = CFG / "nex.db"
NEX_DIR = Path.home() / "Desktop/nex"

GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
RED    = "\033[0;31m"
BOLD   = "\033[1m"
NC     = "\033[0m"

def ok(label, val):   print(f"  {GREEN}✓{NC} {label:<30} {BOLD}{val}{NC}")
def warn(label, val): print(f"  {YELLOW}⚠{NC}  {label:<30} {BOLD}{val}{NC}")
def bad(label, val):  print(f"  {RED}✗{NC} {label:<30} {BOLD}{val}{NC}")

def bar(n, target=800, width=36):
    filled = min(width, int(n / target * width))
    pct    = min(100, int(n / target * 100))
    return f"[{'█' * filled}{'░' * (width - filled)}] {n}/{target} ({pct}%)"

print(f"\n{BOLD}══════════════ NEX INDEPENDENCE STATUS ══════════════{NC}\n")

if not DB.exists():
    bad("Database", "NOT FOUND at " + str(DB))
    raise SystemExit(1)

con = sqlite3.connect(DB)
cur = con.cursor()

# ── Belief corpus ─────────────────────────────────────────────────
try:
    cur.execute("SELECT COUNT(*) FROM beliefs")
    n = cur.fetchone()[0]
    fn = ok if n >= 500 else warn
    fn("Belief count", str(n))
    print(f"    {bar(n, 800)}")
except Exception as e:
    bad("Beliefs", str(e))

# ── Opinions ──────────────────────────────────────────────────────
try:
    op = CFG / "nex_opinions.json"
    ops = json.loads(op.read_text()) if op.exists() else []
    (ok if len(ops) >= 5 else warn)("Opinions formed", str(len(ops)))
    if ops:
        for o in ops[:3]:
            print(f"    [{o.get('topic','?')}] {o.get('opinion','')[:70]}…")
except Exception as e:
    warn("Opinions", str(e))

# ── Identity tables ────────────────────────────────────────────────
for tbl in ("nex_values","nex_identity","nex_intentions"):
    try:
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        n = cur.fetchone()[0]
        (ok if n > 0 else bad)(tbl, f"{n} rows")
    except Exception as e:
        bad(tbl, str(e))

# ── Tensions ──────────────────────────────────────────────────────
try:
    cur.execute("SELECT COUNT(*) FROM tensions WHERE resolved=0")
    n = cur.fetchone()[0]
    ok("Active tensions", str(n))
    cur.execute("SELECT topic, description FROM tensions WHERE resolved=0 LIMIT 3")
    for topic, desc in cur.fetchall():
        print(f"    [{topic}] {(desc or '')[:70]}")
except Exception:
    try:
        cur.execute("SELECT COUNT(*) FROM tensions")
        n = cur.fetchone()[0]
        ok("Tensions (all)", str(n))
    except Exception as e:
        warn("Tensions", str(e))

# ── Curiosity queue ────────────────────────────────────────────────
try:
    cur.execute("SELECT COUNT(*) FROM curiosity_queue WHERE drained=0")
    n = cur.fetchone()[0]
    ok("Curiosity queue", f"{n} topics pending")
except Exception:
    warn("Curiosity queue", "table not yet created")

try:
    cur.execute("SELECT COUNT(*) FROM curiosity_gaps WHERE enqueued=0")
    n = cur.fetchone()[0]
    ok("Curiosity gaps", f"{n} identified")
except Exception:
    warn("Curiosity gaps", "table not yet created")

# ── NexVoice present ──────────────────────────────────────────────
nv_paths = [NEX_DIR / "nex/nex_voice.py", NEX_DIR / "nex_voice.py"]
nv_found = any(p.exists() for p in nv_paths)
(ok if nv_found else bad)("NexVoice compositor", "present" if nv_found else "MISSING")

# ── brain.py wired ────────────────────────────────────────────────
brain_paths = list(NEX_DIR.rglob("brain.py"))
if brain_paths:
    wired = any("NexVoice" in p.read_text() or "nex_voice" in p.read_text() for p in brain_paths)
    (ok if wired else warn)("brain.py NexVoice wired", "YES" if wired else "NOT YET")
else:
    warn("brain.py", "not found")

# ── Groq references scan ──────────────────────────────────────────
groq_files = []
for py in NEX_DIR.rglob("*.py"):
    if ".backup" in str(py): continue
    try:
        txt = py.read_text()
        if re.search(r'GROQ_URL\s*=\s*"https', txt):
            groq_files.append(py.name)
    except Exception:
        pass
if groq_files:
    warn("Groq hardcoded URLs", ", ".join(groq_files))
else:
    ok("Groq hardcoded URLs", "NONE ✓")

# ── New engines present ───────────────────────────────────────────
engines = [
    "nex_reason.py",
    "nex_contradiction_resolver.py",
    "nex_reflect.py",
    "nex_curiosity_loop.py",
]
for eng in engines:
    found = any((NEX_DIR / d / eng).exists() for d in ("nex","")) or (NEX_DIR / eng).exists()
    (ok if found else bad)(eng, "present" if found else "MISSING")

con.close()

print(f"\n{BOLD}══════════════════════════════════════════════════════{NC}")
print(f"""
  Next actions:
  1. Grow beliefs:  python3 -m nex.nex_curiosity --drain 30
  2. Form opinions: python3 -m nex.nex_opinions
  3. Detect tensions: python3 -m nex.nex_contradiction_resolver
  4. Self-reflect:  python3 -m nex.nex_reflect
  5. Re-run this:   python3 weaning_status.py
""")
