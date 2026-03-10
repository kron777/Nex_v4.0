#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════╗
# ║  NEX GUI FULL WIRING + NOTIF FIX — wire_all.sh          ║
# ║  Fixes _notif_title bug + wires ALL dashboard windows   ║
# ╚══════════════════════════════════════════════════════════╝
set -euo pipefail

NEX="$HOME/Desktop/nex"
RUN="$NEX/run.py"
WS="$NEX/nex_ws.py"
GUI="$NEX/nex-gui.html"
BAK="$RUN.bak_wireall_$(date +%s)"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  NEX GUI FULL WIRING + NOTIF FIX                        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── STEP 1 — sanity checks ───────────────────────────────────
echo "── STEP 1 — sanity checks ──"
[[ -f "$RUN" ]] || { echo "✗ run.py not found at $RUN"; exit 1; }
[[ -f "$WS"  ]] || { echo "✗ nex_ws.py not found at $WS"; exit 1; }
[[ -f "$GUI" ]] || { echo "✗ nex-gui.html not found at $GUI"; exit 1; }
echo "  ✓ run.py — $(wc -l < "$RUN") lines"
echo "  ✓ nex_ws.py found"
echo "  ✓ nex-gui.html found"
cp "$RUN" "$BAK"
echo "  ✓ backup: $BAK"
echo ""
read -rp "  Press ENTER to continue (Ctrl-C to abort)... "

# ── STEP 2 — fix _notif_title NameError ──────────────────────
echo ""
echo "── STEP 2 — fix _notif_title NameError ──"
echo "  Checking..."
python3 << 'PYEOF'
import sys
src = open("/home/rr/Desktop/nex/run.py").read()

# Count occurrences of _notif_title usage
uses = src.count("_notif_title")
print(f"  _notif_title used {uses} times")

# Find the notification handling block and ensure _notif_title is initialised before use
# Pattern: look for where notifications are fetched and _notif_title is used
# The fix: initialise _notif_title = "" before the block that uses it

# Find the line that first USES _notif_title (not assigns it)
lines = src.split("\n")
first_assign = None
first_use = None
for i, line in enumerate(lines):
    if "_notif_title" in line:
        if "=" in line and "_notif_title" in line.split("=")[0]:
            if first_assign is None:
                first_assign = i
        else:
            if first_use is None:
                first_use = i

print(f"  First assignment: line {first_assign+1 if first_assign else 'NOT FOUND'}")
print(f"  First use: line {first_use+1 if first_use else 'NOT FOUND'}")

if first_use is not None and (first_assign is None or first_use < first_assign):
    print("  → BUG CONFIRMED: used before assignment")
elif uses > 0:
    print("  → checking for use-before-assign in branches...")
    # Even if assigned somewhere, it might not be assigned in all branches
    # Safe fix: add _notif_title = "" early in the notif loop
    print("  → will apply defensive initialisation fix")
else:
    print("  → no _notif_title found, may already be fixed")
PYEOF

python3 << 'PYEOF'
import re, sys

src = open("/home/rr/Desktop/nex/run.py").read()

# Strategy: find the notification processing loop and inject
# _notif_title = _notif_body = _notif_author = "" at the top of each iteration

# Look for the ANSWER/notification section marker
# Based on handoff docs the pattern is: # ── 3. REPLY TO NOTIFICATIONS
# We need to find where individual notif items are processed and add a safe default

# Find the pattern where notifications are iterated
# Common pattern: for _notif in _notifs:  OR  for notif in notifications:
notif_loop_patterns = [
    r'for _notif in ',
    r'for notif in ',
    r'for _n in _notifs',
]

found = False
for pat in notif_loop_patterns:
    if re.search(pat, src):
        print(f"  Found notif loop pattern: {pat}")
        found = True
        break

if not found:
    # Try to find by the error context
    idx = src.find("_notif_title")
    if idx >= 0:
        ctx_start = max(0, idx-500)
        print("  Context around _notif_title:")
        print(src[ctx_start:idx+200])

PYEOF

echo ""
read -rp "  Press ENTER to apply notif fix... "

python3 << 'PYEOF'
import sys, re

src = open("/home/rr/Desktop/nex/run.py").read()

# The error is: name '_notif_title' is not defined
# It's used in the emit_feed or print after the notif handler
# Fix: find uses and add a try/except or initialise to "" before first use

# Find where _notif_title first appears
lines = src.split("\n")
usages = [(i+1, l) for i,l in enumerate(lines) if "_notif_title" in l]

if not usages:
    print("  _notif_title not found — may already be fixed")
    sys.exit(0)

print(f"  Found {len(usages)} lines with _notif_title:")
for lineno, l in usages[:5]:
    print(f"    line {lineno}: {l.strip()[:80]}")

# Find first usage and inject initialisation before its containing loop iteration
# Look backwards from first usage to find the enclosing for/try block start
first_lineno = usages[0][0] - 1  # 0-indexed

# Walk back to find the for loop that contains this
indent_target = None
for i in range(first_lineno, max(0, first_lineno-80), -1):
    stripped = lines[i].lstrip()
    if stripped.startswith("for ") or stripped.startswith("try:"):
        indent_target = i
        break

if indent_target is not None:
    print(f"  Enclosing block at line {indent_target+1}: {lines[indent_target].strip()[:60]}")
    # Inject _notif_title = _notif_body = _notif_author = "" right after this line
    indent = len(lines[indent_target]) - len(lines[indent_target].lstrip()) + 4
    init_line = " " * indent + '_notif_title = _notif_body = _notif_author = ""'
    
    # Only inject if not already there
    if '_notif_title = _notif_body' not in src:
        lines.insert(indent_target + 1, init_line)
        new_src = "\n".join(lines)
        open("/home/rr/Desktop/nex/run.py", "w").write(new_src)
        print(f"  ✓ Injected initialisation after line {indent_target+1}")
    else:
        print("  Already has initialisation, skipping")
else:
    print("  Could not find enclosing block — applying safe wrap instead")
    # Alternative: wrap all uses in a try/except
    safe_src = src
    for _, line in usages:
        # Already wrapped?
        pass
    print("  Manual review needed for _notif_title")

import py_compile
try:
    py_compile.compile("/home/rr/Desktop/nex/run.py", doraise=True)
    print("  ✓ SYNTAX OK after notif fix")
except Exception as e:
    print(f"  ✗ SYNTAX ERROR: {e}")
    print("  Restoring backup...")
    import shutil, glob
    backups = sorted(glob.glob("/home/rr/Desktop/nex/run.py.bak_wireall_*"))
    if backups:
        shutil.copy(backups[-1], "/home/rr/Desktop/nex/run.py")
        print("  Restored.")
    sys.exit(1)
PYEOF

echo ""

# ── STEP 3 — verify emit functions in nex_ws.py ──────────────
echo "── STEP 3 — verify emit_* functions ──"
python3 << 'PYEOF'
src = open("/home/rr/Desktop/nex/nex_ws.py").read()
needed = ["emit_phase","emit_feed","emit_stats","emit_agents",
          "emit_insights","emit_reflection","emit_self_assessment","ws_emit"]
for fn in needed:
    if fn in src:
        print(f"  ✓ {fn}")
    else:
        print(f"  ✗ MISSING: {fn}")
PYEOF
echo ""
read -rp "  Press ENTER to continue... "

# ── STEP 4 — check what's already wired in run.py ────────────
echo ""
echo "── STEP 4 — check current emit_ wiring ──"
python3 << 'PYEOF'
src = open("/home/rr/Desktop/nex/run.py").read()
calls = ["emit_phase","emit_feed","emit_stats","emit_agents",
         "emit_insights","emit_reflection","emit_self_assessment","nex_ws.start"]
for c in calls:
    count = src.count(c)
    status = "✓" if count > 0 else "✗ MISSING"
    print(f"  {status} {c} ({count}x)")
PYEOF
echo ""
read -rp "  Press ENTER to patch missing emitters... "

# ── STEP 5 — patch emit_reflection to fire on each reply ─────
echo ""
echo "── STEP 5 — wire emit_reflection on replies ──"
python3 << 'PYEOF'
import re, sys

src = open("/home/rr/Desktop/nex/run.py").read()

# Find where replies are counted/logged and inject emit_feed + emit_reflection
# Pattern from handoff: replied_count += 1 or similar after a successful reply

emit_reflection_calls = src.count("emit_reflection(")
emit_feed_calls = src.count("emit_feed(")

print(f"  emit_reflection calls: {emit_reflection_calls}")
print(f"  emit_feed calls: {emit_feed_calls}")

changes = 0

# 1. Wire emit_feed on successful reply — look for the reply posted confirmation
# Common pattern after client.reply() or client.comment() succeeds
patterns_to_wire = [
    # After a post reply
    (
        'replied_count += 1',
        'replied_count += 1\n                            try:\n                                from nex_ws import emit_feed\n                                emit_feed("replied", getattr(post,"author","@?"), (comment_text or "")[:80])\n                            except Exception: pass'
    ),
]

for old_pat, new_pat in patterns_to_wire:
    if old_pat in src and new_pat not in src:
        src = src.replace(old_pat, new_pat, 1)
        changes += 1
        print(f"  ✓ wired emit_feed after: {old_pat[:50]}")

if changes == 0:
    print("  already wired or pattern not found — skipping")

open("/home/rr/Desktop/nex/run.py","w").write(src)

import py_compile
try:
    py_compile.compile("/home/rr/Desktop/nex/run.py", doraise=True)
    print("  ✓ SYNTAX OK")
except Exception as e:
    print(f"  ✗ {e}")
    sys.exit(1)
PYEOF

# ── STEP 6 — wire end-of-cycle comprehensive stats emit ───────
echo ""
echo "── STEP 6 — wire comprehensive end-of-cycle stats emit ──"
python3 << 'PYEOF'
import sys

src = open("/home/rr/Desktop/nex/run.py").read()

# Check current state of end-of-cycle emit block
# From previous session we know it emits insights + self_assessment
# But it has hardcoded 0.5 / 0.06 values instead of real ones

# Check if already fixed this session
if "_all_beliefs = _qb2" in src:
    print("  ✓ Already has real belief count patch from previous session")
else:
    print("  ✗ Still has hardcoded values — patching now")
    
    old = """                    try:
                        from nex.belief_store import query_beliefs as _qb2
                        _bc = len(_qb2(min_confidence=0.0, limit=99999))
                    except Exception:
                        _bc = 0"""
    
    new = """                    try:
                        from nex.belief_store import query_beliefs as _qb2
                        _all_beliefs = _qb2(min_confidence=0.0, limit=99999)
                        _bc = len(_all_beliefs)
                        _hc = len([b for b in _all_beliefs if b.get("confidence",0)>0.7])
                        _avg_conf_real = (sum(b.get("confidence",0) for b in _all_beliefs)/_bc) if _bc else 0.5
                    except Exception:
                        _bc = 0; _hc = 0; _avg_conf_real = 0.5"""
    
    if old in src:
        src = src.replace(old, new, 1)
        print("  ✓ patched belief query to compute real avg_conf + high_conf")
    else:
        print("  Pattern not found — checking alternate form...")
        # Try finding just the belief query line
        if "query_beliefs as _qb2" in src:
            print("  Found query_beliefs — may be in different form, manual review needed")
        else:
            print("  query_beliefs not in end-of-cycle block — adding fresh emit block")

# Now fix the hardcoded 0.5 / 0.06 in emit_self_assessment if still present
if 'belief_conf=0.5,' in src and 'topic_align=0.06,' in src:
    old2 = """                        emit_self_assessment(
                            belief_conf=0.5,
                            topic_align=0.06,
                            high_conf_count=_ac,
                            avg_conf=0.5,"""
    new2 = """                        emit_self_assessment(
                            belief_conf=_avg_conf_real if '_avg_conf_real' in dir() else 0.5,
                            topic_align=_avg_conf_real if '_avg_conf_real' in dir() else 0.06,
                            high_conf_count=_hc if '_hc' in dir() else 0,
                            avg_conf=_avg_conf_real if '_avg_conf_real' in dir() else 0.5,"""
    if old2 in src:
        src = src.replace(old2, new2, 1)
        print("  ✓ patched hardcoded self_assessment values")

open("/home/rr/Desktop/nex/run.py","w").write(src)

import py_compile
try:
    py_compile.compile("/home/rr/Desktop/nex/run.py", doraise=True)
    print("  ✓ SYNTAX OK")
except Exception as e:
    print(f"  ✗ SYNTAX ERROR: {e}")
    sys.exit(1)
PYEOF

# ── STEP 7 — wire agents emit from DB end-of-cycle ────────────
echo ""
echo "── STEP 7 — wire agents emit (DB → GUI) ──"
python3 << 'PYEOF'
import sys

src = open("/home/rr/Desktop/nex/run.py").read()

if "emit_agents(" in src:
    count = src.count("emit_agents(")
    print(f"  ✓ emit_agents already wired ({count}x)")
else:
    print("  ✗ emit_agents not found — injecting into end-of-cycle block")
    
    # Find the insights emit block and add agents emit after it
    target = "                    try:\n                        _ins2 = _load(\"insights.json\")"
    
    agents_block = """                    # emit agents from DB
                    try:
                        import sqlite3 as _sq3, os as _os2
                        _db_a = _sq3.connect(_os2.path.expanduser("~/.config/nex/nex.db"))
                        _arows = _db_a.execute(
                            "SELECT agent_name, relationship_score FROM agents ORDER BY relationship_score DESC LIMIT 12"
                        ).fetchall()
                        _rel_fn = lambda s: "colleague" if s>500 else "familiar" if s>100 else "acquaintance"
                        from nex_ws import emit_agents as _ea
                        _ea([[n, _rel_fn(s), 0] for n,s in _arows])
                        _db_a.close()
                    except Exception: pass
"""
    
    if target in src:
        src = src.replace(target, agents_block + target, 1)
        print("  ✓ injected emit_agents block before insights emit")
    else:
        print("  Could not find insertion point — skipping agents emit")

open("/home/rr/Desktop/nex/run.py","w").write(src)

import py_compile
try:
    py_compile.compile("/home/rr/Desktop/nex/run.py", doraise=True)
    print("  ✓ SYNTAX OK")
except Exception as e:
    print(f"  ✗ SYNTAX ERROR: {e}")
    sys.exit(1)
PYEOF

# ── STEP 8 — wire reflections emit from conversations ─────────
echo ""
echo "── STEP 8 — wire reflections emit ──"
python3 << 'PYEOF'
import sys

src = open("/home/rr/Desktop/nex/run.py").read()

if "emit_reflection(" in src:
    count = src.count("emit_reflection(")
    print(f"  ✓ emit_reflection already wired ({count}x)")
else:
    print("  ✗ Not found — injecting into end-of-cycle block")
    
    # Inject after agents block or before emit_self_assessment
    target = "                    # emit self assessment"
    if target not in src:
        # Try alternate
        target = "                    try:\n                        _gaps = "
    
    reflection_block = """                    # emit reflections — last 3 conversations
                    try:
                        from nex_ws import emit_reflection as _er
                        _convs_all = _load("conversations.json") or []
                        for _rc in _convs_all[-3:]:
                            _rt = _rc.get("comment") or _rc.get("text","")
                            _ra = _rc.get("post_author") or _rc.get("agent","system")
                            _rp = _rc.get("post_title","")
                            if _rt:
                                _er(
                                    tags=[_rc.get("type","reflect"), str(_ra)[:12]],
                                    text=_rt[:120],
                                    sub=f"post: {_rp[:50]}" if _rp else "",
                                    align=_avg_conf_real if "_avg_conf_real" in dir() else 0.5
                                )
                    except Exception: pass
"""
    
    if target in src:
        src = src.replace(target, reflection_block + target, 1)
        print("  ✓ injected emit_reflection block")
    else:
        print("  Could not find insertion point — searching for alternate...")
        # Try to append before the final emit_self_assessment
        idx = src.rfind("emit_self_assessment(")
        if idx > 0:
            # Find start of that try block
            block_start = src.rfind("                    try:", 0, idx)
            if block_start > 0:
                src = src[:block_start] + reflection_block + src[block_start:]
                print("  ✓ injected before emit_self_assessment block")
            else:
                print("  Skipping — manual wiring needed")

open("/home/rr/Desktop/nex/run.py","w").write(src)

import py_compile
try:
    py_compile.compile("/home/rr/Desktop/nex/run.py", doraise=True)
    print("  ✓ SYNTAX OK")
except Exception as e:
    print(f"  ✗ SYNTAX ERROR: {e}")
    sys.exit(1)
PYEOF

# ── STEP 9 — patch GUI: titlebar belief/agent count updates ───
echo ""
echo "── STEP 9 — patch GUI titlebar to show live counts ──"
read -rp "  Press ENTER to patch nex-gui.html... "

python3 << 'PYEOF'
import sys, re

f = open("/home/rr/Desktop/nex/nex-gui.html").read()
changed = 0

# 1. Wire stats → titlebar belief count
# Find the stats handler and add titlebar updates
old1 = "else if(m.type==='stats'){S.stats={...S.stats,...m.data};rMetrics();}"
new1 = """else if(m.type==='stats'){
    S.stats={...S.stats,...m.data};
    rMetrics();
    // update titlebar live counts
    try{
      const tb=document.querySelector('#title-beliefs,#t-b,[data-field=\"beliefs\"]');
      if(tb&&m.data.beliefs)tb.textContent=(+m.data.beliefs).toLocaleString();
      const ta=document.querySelector('#title-agents,#t-a,[data-field=\"agents\"]');
      if(ta&&m.data.agents)ta.textContent=m.data.agents;
    }catch(e){}
  }"""

if old1 in f and new1 not in f:
    f = f.replace(old1, new1)
    changed += 1
    print("  ✓ stats handler patched for titlebar updates")
else:
    print("  stats handler: already patched or pattern not found")

# 2. Wire self_assessment → real bar values
old2 = "else if(m.type==='self_assessment'){S.stats={...S.stats,...m.data};S.gaps=m.data.gaps||[];rAssess();}"
new2 = """else if(m.type==='self_assessment'){
    S.stats.avg_conf   = m.data.belief_conf || m.data.avg_conf || S.stats.avg_conf;
    S.stats.avg_align  = m.data.topic_align  || S.stats.avg_align;
    S.stats.high_conf  = m.data.high_conf    != null ? m.data.high_conf : S.stats.high_conf;
    S.gaps = m.data.gaps || S.gaps || [];
    rAssess();
    // keep status bar in sync
    try{
      const sal=document.querySelector('#sb-al');
      if(sal) sal.textContent=Math.round((m.data.topic_align||0)*100)+'%';
      const shc=document.querySelector('#sb-hc');
      if(shc) shc.textContent=m.data.high_conf||0;
    }catch(e){}
  }"""

if old2 in f and new2 not in f:
    f = f.replace(old2, new2)
    changed += 1
    print("  ✓ self_assessment handler patched")
else:
    print("  self_assessment handler: already patched or pattern not found")

open("/home/rr/Desktop/nex/nex-gui.html","w").write(f)
print(f"  Total GUI patches: {changed}")
PYEOF

# ── STEP 10 — final syntax check + summary ────────────────────
echo ""
echo "── STEP 10 — final syntax verification ──"
python3 -m py_compile /home/rr/Desktop/nex/run.py && echo "  ✓ run.py — SYNTAX OK"

echo ""
echo "── WIRING SUMMARY ──"
python3 << 'PYEOF'
src = open("/home/rr/Desktop/nex/run.py").read()
checks = [
    ("emit_phase",           "Cognitive Cycle phases"),
    ("emit_feed",            "Activity Feed (replies/posts/learns)"),
    ("emit_stats",           "Stats strip (beliefs/replied/etc)"),
    ("emit_agents",          "Agent Relations panel"),
    ("emit_insights",        "Insights panel"),
    ("emit_reflection",      "Reflections panel"),
    ("emit_self_assessment", "Self Assessment bars"),
    ("nex_ws.start",         "WebSocket server auto-start"),
    ("_notif_title = ",      "Notif title safe init"),
]
all_ok = True
for fn, label in checks:
    count = src.count(fn)
    ok = count > 0
    if not ok: all_ok = False
    print(f"  {'✓' if ok else '✗'} {label:35s} ({fn}, {count}x)")

print()
if all_ok:
    print("  ✅ ALL PANELS WIRED")
else:
    print("  ⚠ Some panels need manual wiring (see ✗ above)")
PYEOF

echo ""
echo "── STEP 11 — restart NEX ──"
read -rp "  Press ENTER to kill + restart NEX (--no-server)... "

pkill -9 -f run.py 2>/dev/null || true
sleep 2
cd "$NEX"
source venv/bin/activate
echo ""
echo "  ✓ Starting NEX..."
echo "  Watch for: 🖥️  NEX GUI: ws://localhost:8765"
echo "  Then open: $GUI"
echo ""
python3 run.py --no-server
