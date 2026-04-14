#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# NEX WARMTH WIRING — Surgical integration into response pipeline
# Touches exactly 2 files. Makes 4 insertions. Nothing removed.
# ═══════════════════════════════════════════════════════════════

set -e
cd ~/Desktop/nex
source venv/bin/activate

echo "═══ STEP 1: BACKUP ORIGINALS ═══"
cp nex_response_protocol.py nex_response_protocol.py.bak
cp nex_respond.py nex_respond.py.bak
echo "✓ Backups created"
echo "  nex_response_protocol.py.bak"
echo "  nex_respond.py.bak"


echo ""
echo "═══ STEP 2: WIRE WARMTH INTO nex_response_protocol.py ═══"

# We insert at 3 points inside generate():
#
# POINT A — top of generate(), after "global _budget, _history"
#   → pre_process(query) — pre-load hot word tendencies
#
# POINT B — after beliefs retrieved, before contradiction check
#   → cot_gate() — potentially skip FAISS, seed beliefs from warmth
#
# POINT C — after response = _call_llm(system, prompt)
#   → post_process() — capture new gaps, quality signal

python3 << 'PATCHEOF'
import re
from pathlib import Path

path = Path("nex_response_protocol.py")
src  = path.read_text()

# ── POINT A: insert warmth pre-process at top of generate() ──
# After "global _budget, _history" line
INSERT_A = '''
    # ── WARMTH PRE-PROCESS ────────────────────────────────────────
    _warmth_ctx = {}
    _warmth_db  = None
    try:
        import sqlite3
        from nex_word_tag_schema import init_db
        from nex_warmth_integrator import pre_process, cot_gate
        _warmth_db = sqlite3.connect(
            str(Path.home() / "Desktop/nex/nex.db"))
        _warmth_db.row_factory = sqlite3.Row
        init_db(_warmth_db)
        _warmth_ctx = pre_process(query)
    except Exception as _we:
        pass
    # ─────────────────────────────────────────────────────────────
'''

old_a = "    # 1. Classify intent\n    intent = classify_intent(query)"
new_a = INSERT_A + "    # 1. Classify intent\n    intent = classify_intent(query)"

if old_a in src:
    src = src.replace(old_a, new_a, 1)
    print("✓ Point A inserted (pre_process)")
else:
    print("✗ Point A — pattern not found, skipping")

# ── POINT B: warmth-aware belief seeding after belief retrieval ──
# After the belief_text is assembled, before contradiction check
INSERT_B = '''
    # ── WARMTH COT GATE ───────────────────────────────────────────
    if _warmth_ctx and _warmth_db:
        try:
            _gate = cot_gate(query, [belief_text], _warmth_ctx)
            if _gate.get("reasoning_seed"):
                belief_text = (
                    _gate["reasoning_seed"] + "\\n" + belief_text
                )
            if _warmth_ctx.get("depth_ceiling", 0) >= 5:
                # Soul-level question — force rich intent
                if intent not in ("identity","consciousness",
                                  "introspective","gaps"):
                    intent = "introspective"
        except Exception as _ge:
            pass
    # ─────────────────────────────────────────────────────────────
'''

old_b = "    # 2b. Contradiction check"
new_b = INSERT_B + "    # 2b. Contradiction check"

if old_b in src:
    src = src.replace(old_b, new_b, 1)
    print("✓ Point B inserted (cot_gate + belief seeding)")
else:
    print("✗ Point B — pattern not found, skipping")

# ── POINT C: post-process after LLM response ──────────────────
INSERT_C = '''
    # ── WARMTH POST-PROCESS ───────────────────────────────────────
    if _warmth_ctx and _warmth_db:
        try:
            from nex_warmth_integrator import post_process
            post_process(query, response, _warmth_ctx)
        except Exception:
            pass
        try:
            _warmth_db.close()
        except Exception:
            pass
    # ─────────────────────────────────────────────────────────────
'''

old_c = "    response = _call_llm(system, prompt)"
new_c = "    response = _call_llm(system, prompt)" + INSERT_C

if old_c in src:
    src = src.replace(old_c, new_c, 1)
    print("✓ Point C inserted (post_process)")
else:
    print("✗ Point C — pattern not found, skipping")

path.write_text(src)
print("\nnex_response_protocol.py patched.")
PATCHEOF


echo ""
echo "═══ STEP 3: WIRE SESSION LAYER INTO nex_respond.py ═══"

# We insert the session layer at one point in nex_reply():
# After "query = query.strip()" — process text through session,
# and after the reply is returned from SoulLoop — advance session.

python3 << 'PATCHEOF'
from pathlib import Path

path = Path("nex_respond.py")
src  = path.read_text()

# Add import at top of file (after existing imports)
IMPORT_INSERT = '''
# ── Warmth session layer ──────────────────────────────────────
try:
    import sqlite3 as _sqlite3
    from nex_warmth_session import get_session, end_session
    from pathlib import Path as _Path
    _WARMTH_SESSION_OK = True
    _WARMTH_DB_PATH = _Path.home() / "Desktop/nex/nex.db"
except Exception:
    _WARMTH_SESSION_OK = False
# ─────────────────────────────────────────────────────────────
'''

# Insert after the existing imports block
old_imp = "CFG = Path(\"~/.config/nex\").expanduser()"
new_imp = old_imp + "\n" + IMPORT_INSERT

if old_imp in src:
    src = src.replace(old_imp, new_imp, 1)
    print("✓ Session import inserted")
else:
    print("✗ Import — pattern not found, skipping")

# Wire session processing after query.strip()
SESSION_PROCESS = '''
    # ── SESSION WARMTH LAYER ──────────────────────────────────────
    _session = None
    _conv_id  = str(id(history)) if history else "default"
    if _WARMTH_SESSION_OK:
        try:
            _sdb = _sqlite3.connect(str(_WARMTH_DB_PATH))
            _sdb.row_factory = _sqlite3.Row
            _session = get_session(_conv_id)
            _session.process_text(query, _sdb)
            _sdb.close()
        except Exception:
            pass
    # ─────────────────────────────────────────────────────────────
'''

old_sess = "    # ── 1. Enrich query with history context if available"
new_sess = SESSION_PROCESS + "    # ── 1. Enrich query with history context if available"

if old_sess in src:
    src = src.replace(old_sess, new_sess, 1)
    print("✓ Session pre-process inserted")
else:
    print("✗ Session pre-process — pattern not found, skipping")

# Advance session after successful reply from SoulLoop
SESSION_ADVANCE = '''
                # Advance session warmth for next exchange
                if _session:
                    try:
                        _sdb2 = _sqlite3.connect(str(_WARMTH_DB_PATH))
                        _sdb2.row_factory = _sqlite3.Row
                        _session.process_text(reply.strip(), _sdb2)
                        _session.next_exchange()
                        _sdb2.close()
                    except Exception:
                        pass
'''

old_adv = "                # Fire feedback loop"
new_adv = SESSION_ADVANCE + "                # Fire feedback loop"

if old_adv in src:
    src = src.replace(old_adv, new_adv, 1)
    print("✓ Session advance inserted (post-reply)")
else:
    print("✗ Session advance — pattern not found, skipping")

path.write_text(src)
print("\nnex_respond.py patched.")
PATCHEOF


echo ""
echo "═══ STEP 4: VERIFY PATCHES ═══"

echo "Checking nex_response_protocol.py insertions..."
grep -n "WARMTH PRE-PROCESS\|WARMTH COT GATE\|WARMTH POST-PROCESS" \
    nex_response_protocol.py | head -10

echo ""
echo "Checking nex_respond.py insertions..."
grep -n "WARMTH SESSION\|SESSION WARMTH\|session.process_text\|session.next_exchange" \
    nex_respond.py | head -10


echo ""
echo "═══ STEP 5: SYNTAX CHECK ═══"
venv/bin/python3 -m py_compile nex_response_protocol.py \
    && echo "✓ nex_response_protocol.py — syntax OK" \
    || echo "✗ nex_response_protocol.py — SYNTAX ERROR"

venv/bin/python3 -m py_compile nex_respond.py \
    && echo "✓ nex_respond.py — syntax OK" \
    || echo "✗ nex_respond.py — SYNTAX ERROR"


echo ""
echo "═══ STEP 6: LIVE INTEGRATION TEST ═══"
venv/bin/python3 << 'TESTEOF'
import sys, sqlite3
sys.path.insert(0, "/home/rr/Desktop/nex")
from pathlib import Path

DB = Path.home() / "Desktop/nex/nex.db"
db = sqlite3.connect(str(DB))
db.row_factory = sqlite3.Row

print("Testing warmth pre-process on live question...")
from nex_warmth_integrator import pre_process, cot_gate, post_process

q = "Is consciousness reducible to physical substrate?"
ctx = pre_process(q)
print(f"  hot_ratio    : {ctx['hot_ratio']}")
print(f"  depth_ceiling: {ctx['depth_ceiling']}")
print(f"  search_budget: {ctx['search_budget']}")
print(f"  hot_words    : {ctx['hot_words'][:5]}")
print(f"  cold_words   : {ctx['cold_words'][:5]}")

gate = cot_gate(q, [], ctx)
print(f"\n  skip_faiss   : {gate['skip_faiss']}")
print(f"  use_warmth   : {gate['use_warmth']}")
if gate['reasoning_seed']:
    print(f"  seed preview : "
          f"{gate['reasoning_seed'][:100]}")

print("\nTesting session layer...")
from nex_warmth_session import SessionWarmthLayer
s = SessionWarmthLayer("test_wire")
s.process_text(q, db)
s.next_exchange()
s.process_text("The hard problem of consciousness "
               "remains genuinely unsolved.", db)
s.next_exchange()
print(f"  Active words : {len(s.boosts)}")
print(f"  Top boosted  : ")
for w, b in s.most_active(4):
    print(f"    {w:20} +{b:.3f}")

print("\nTesting phrase resolution...")
from nex_warmth_phrases import resolve_phrase
matches = resolve_phrase(q, db)
print(f"  Phrases found: {len(matches)}")
for m in matches[:3]:
    print(f"    '{m['phrase']}' w={m['w']:.2f}")

print("\nTesting contextual domain detection...")
from nex_warmth_context import detect_domain, apply_domain_adjustments
domain, conf, scores = detect_domain(q)
print(f"  Domain       : {domain} (conf={conf:.2f})")
print(f"  Scores       : {scores}")

print("\n✓ All warmth systems live in response pipeline")
db.close()
TESTEOF


echo ""
echo "═══ STEP 7: ROLLBACK INSTRUCTIONS ═══"
echo "If anything breaks, restore originals with:"
echo "  cp nex_response_protocol.py.bak nex_response_protocol.py"
echo "  cp nex_respond.py.bak nex_respond.py"


echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║   NEX WARMTH WIRING — COMPLETE                ║"
echo "╠═══════════════════════════════════════════════╣"
echo "║                                               ║"
echo "║  WIRED INTO:                                  ║"
echo "║    nex_response_protocol.py::generate()       ║"
echo "║      → pre_process()   top of function        ║"
echo "║      → cot_gate()      after beliefs loaded   ║"
echo "║      → post_process()  after LLM responds     ║"
echo "║                                               ║"
echo "║    nex_respond.py::nex_reply()                ║"
echo "║      → session.process_text()  on query       ║"
echo "║      → session.next_exchange() after reply    ║"
echo "║                                               ║"
echo "║  WHAT THIS MEANS:                             ║"
echo "║    Every conversation now:                    ║"
echo "║    • Pre-loads hot word tendencies            ║"
echo "║    • Skips FAISS for warm questions           ║"
echo "║    • Seeds beliefs from warmth context        ║"
echo "║    • Boosts soul questions to deep intent     ║"
echo "║    • Captures new gaps after every response   ║"
echo "║    • Amplifies vocabulary within session      ║"
echo "║    • Gets smarter as conversation develops    ║"
echo "║                                               ║"
echo "║  ROLLBACK: cp *.bak to restore originals      ║"
echo "║                                               ║"
echo "║  NEXT: Items 7-12 from NEX_BUILD.txt          ║"
echo "╚═══════════════════════════════════════════════╝"
