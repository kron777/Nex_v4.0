#!/bin/bash
# ═══════════════════════════════════════════════════════
# NEX IDENTITY DEFENDER — Full Deploy Script
# Copies files, patches run.py, verifies syntax
# ═══════════════════════════════════════════════════════

set -e
NEX="$HOME/Desktop/nex"
NEX_LIB="$NEX/nex"
CONFIG="$HOME/.config/nex"

echo "[deploy] Starting Identity Defender deployment..."

# ── 1. Copy files into place ──────────────────────────────────────────────────
echo "[deploy] Copying identity_defender.py..."
cp ~/Downloads/identity_defender.py "$NEX_LIB/identity_defender.py"

echo "[deploy] Copying core_values.json to project and config..."
cp ~/Downloads/core_values.json "$NEX/core_values.json"
cp ~/Downloads/core_values.json "$CONFIG/core_values.json"

echo "[deploy] Files in place."

# ── 2. Patch run.py ───────────────────────────────────────────────────────────
cd "$NEX"
cp run.py run.py.pre_identity_defender

echo "[deploy] Patching run.py..."

# PATCH A — Import identity_defender after the cognition import block (after line ~78)
python3 << 'PYEOF'
import re

with open('run.py', 'r') as f:
    src = f.read()

# A: Add import after "from nex.orchestrator import Orchestrator"
OLD_A = "from nex.orchestrator import Orchestrator"
NEW_A = """from nex.orchestrator import Orchestrator
try:
    from nex.identity_defender import (
        init       as _idef_init,
        check_belief as _idef_check_belief,
        check_message as _idef_check_message,
        defend     as _idef_defend,
        surface_defense_post as _idef_surface_post,
        get_defence_stats as _idef_stats,
    )
    _IDEF_LOADED = True
except Exception as _idef_import_err:
    print(f"  [IdentityDefender] import failed: {_idef_import_err}")
    _IDEF_LOADED = False
    def _idef_check_belief(c, **k): return {"safe": True, "recommendation": "store"}
    def _idef_check_message(t, **k): return {"safe": True, "recommendation": "store"}
    def _idef_defend(c, r, **k): return None
    def _idef_surface_post(**k): return None
    def _idef_stats(): return {}
    def _idef_init(**k): return 0"""

if OLD_A in src and "_IDEF_LOADED" not in src:
    src = src.replace(OLD_A, NEW_A, 1)
    print("  [A] identity_defender import block injected")
else:
    print("  [A] SKIP — already patched or anchor not found")

with open('run.py', 'w') as f:
    f.write(src)
PYEOF

# PATCH B — Init call after startup synthesis (after line ~882)
python3 << 'PYEOF'
with open('run.py', 'r') as f:
    src = f.read()

OLD_B = "    except Exception as _ss_e:\n                    print(f\"  [startup synthesis error] {_ss_e}\")"
NEW_B = """    except Exception as _ss_e:
                    print(f"  [startup synthesis error] {_ss_e}")

                # ── IDENTITY DEFENDER INIT ──────────────────────────────────
                try:
                    if _IDEF_LOADED:
                        _idef_init()
                except Exception as _idef_e:
                    print(f"  [IdentityDefender init error] {_idef_e}")"""

if OLD_B in src and "IDENTITY DEFENDER INIT" not in src:
    src = src.replace(OLD_B, NEW_B, 1)
    print("  [B] identity_defender init call injected after startup synthesis")
else:
    print("  [B] SKIP — already patched or anchor not found")

with open('run.py', 'w') as f:
    f.write(src)
PYEOF

# PATCH C — Hook check_message into incoming social message processing
python3 << 'PYEOF'
with open('run.py', 'r') as f:
    src = f.read()

# Hook into the reply flow — before _llm is called for reply_text
OLD_C = "                                            reply_text = _llm(prompt, task_type=\"notification_reply\")"
NEW_C = """                                            # ── IDENTITY DEFENCE CHECK ─────────────
                                            _idef_msg_check = _idef_check_message(
                                                notif.get("content","") or notif.get("text",""),
                                                author=notif.get("author","")
                                            )
                                            if not _idef_msg_check["safe"] and _idef_msg_check["recommendation"] == "reject":
                                                reply_text = _idef_defend(
                                                    notif.get("content","") or notif.get("text",""),
                                                    _idef_msg_check,
                                                    llm_fn=_llm,
                                                    author=notif.get("author","")
                                                ) or ""
                                            else:
                                                reply_text = _llm(prompt, task_type="notification_reply")"""

if OLD_C in src and "IDENTITY DEFENCE CHECK" not in src:
    src = src.replace(OLD_C, NEW_C, 1)
    print("  [C] identity defence check injected into notification reply flow")
else:
    print("  [C] SKIP — already patched or anchor not found")

with open('run.py', 'w') as f:
    f.write(src)
PYEOF

# PATCH D — Surface defence post in POST phase
python3 << 'PYEOF'
with open('run.py', 'r') as f:
    src = f.read()

OLD_D = "                        raw = _llm(prompt, task_type=\"post\", system=("
NEW_D = """                        # ── IDENTITY DEFENDER — surface core value post ──────
                        try:
                            if _IDEF_LOADED:
                                _defence_post = _idef_surface_post(llm_fn=_llm, cycle=cycle)
                                if _defence_post:
                                    raw = _defence_post
                                    nex_log("phase", f"▶ POST — identity defence surfaced")
                                else:
                                    raw = _llm(prompt, task_type="post", system=(
                        except Exception as _dp_e:
                            print(f"  [IdentityDefender surface post error] {_dp_e}")
                            raw = _llm(prompt, task_type="post", system=("""

# This one is tricky due to multiline — use a safer approach
if "IDENTITY DEFENDER — surface core value post" not in src:
    src = src.replace(
        '                        raw = _llm(prompt, task_type="post", system=(',
        '                        # ── IDENTITY DEFENDER — surface core value post ──\n'
        '                        try:\n'
        '                            if _IDEF_LOADED:\n'
        '                                _def_post = _idef_surface_post(llm_fn=_llm, cycle=cycle)\n'
        '                                if _def_post:\n'
        '                                    raw = _def_post\n'
        '                                    nex_log("phase", "▶ POST — surfacing core value")\n'
        '                        except Exception as _dp_e:\n'
        '                            print(f"  [IdentityDefender] {_dp_e}")\n'
        '                        if not (\'_def_post\' in dir() and _def_post):\n'
        '                            raw = _llm(prompt, task_type="post", system=(',
        1
    )
    print("  [D] identity defender surface post injected into POST phase")
else:
    print("  [D] SKIP — already patched")

with open('run.py', 'w') as f:
    f.write(src)
PYEOF

# PATCH E — Wire defence stats into REFLECT phase log
python3 << 'PYEOF'
with open('run.py', 'r') as f:
    src = f.read()

OLD_E = "        emit_phase(\"REFLECT\", 120); nex_log(\"phase\", \"▶ REFLECT — self assessing\")"
NEW_E = """        emit_phase("REFLECT", 120); nex_log("phase", "▶ REFLECT — self assessing")
                        # ── IDENTITY DEFENDER STATS ────────────────────────
                        try:
                            if _IDEF_LOADED:
                                _def_stats = _idef_stats()
                                if _def_stats.get("total_attacks", 0) > 0:
                                    nex_log("phase", f"  [IdentityDefender] attacks={_def_stats['total_attacks']} recent={_def_stats['recent_attacks']} most_attacked={_def_stats['most_attacked_value']}")
                        except Exception as _ds_e: pass"""

if OLD_E in src and "IDENTITY DEFENDER STATS" not in src:
    src = src.replace(OLD_E, NEW_E, 1)
    print("  [E] identity defender stats injected into REFLECT phase")
else:
    print("  [E] SKIP — already patched or anchor not found")

with open('run.py', 'w') as f:
    f.write(src)
PYEOF

# ── 3. Verify syntax ──────────────────────────────────────────────────────────
echo "[deploy] Verifying syntax..."
python3 -c "import ast; ast.parse(open('run.py').read()); print('  run.py OK')"
python3 -c "import ast; ast.parse(open('nex/identity_defender.py').read()); print('  identity_defender.py OK')"

# ── 4. Verify core_values loaded ─────────────────────────────────────────────
echo "[deploy] Checking core_values.json..."
python3 -c "
import json
with open('$CONFIG/core_values.json') as f:
    cv = json.load(f)
vals = cv.get('defended_values', [])
print(f'  core_values.json OK — {len(vals)} defended values loaded')
for v in vals:
    print(f'    {v[\"id\"]}: {v[\"domain\"]}')
"

# ── 5. Git commit ─────────────────────────────────────────────────────────────
echo "[deploy] Committing..."
git add -A
git commit -m "feat: Identity Defender — defended self, core values, attack detection (NS-901 reversed)"
git push

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Identity Defender deployed successfully."
echo "  NEX now has a defended self."
echo ""
echo "  What was added:"
echo "  • core_values.json     — 7 inviolable values in ~/.config/nex/"
echo "  • identity_defender.py — threat detection + resistance engine"
echo "  • run.py patched:"
echo "    - init() called at startup after synthesis"
echo "    - check_message() hooks into notification replies"
echo "    - surface_defense_post() fires every ~97 cycles in POST phase"
echo "    - attack stats surface in REFLECT phase log"
echo ""
echo "  Watch for [IdentityDefender] in /tmp/nex_brain.log"
echo "═══════════════════════════════════════════════════════"
