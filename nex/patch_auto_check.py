#!/usr/bin/env python3
"""
patch_auto_check.py  —  Injects homeostasis dashboard into auto_check.py
Run from /home/rr/Desktop/nex/:  python patch_auto_check.py

Makes 2 edits:
  1. Pull _hm.dashboard_lines() in data_thread so self_lines gets homeostasis data
  2. Display homeostasis zone indicator in the header row
"""

import sys, shutil
from pathlib import Path

# auto_check.py lives in the nex/ subdirectory
TARGET = Path(__file__).parent / "nex" / "auto_check.py"
if not TARGET.exists():
    # fallback: same directory as run.py
    TARGET = Path(__file__).parent / "auto_check.py"
if not TARGET.exists():
    print(f"[ERROR] auto_check.py not found — run from /home/rr/Desktop/nex/")
    sys.exit(1)

backup = TARGET.with_suffix(".py.pre_homeostasis")
shutil.copy2(TARGET, backup)
print(f"  [backup] → {backup.name}")
print(f"  [target] {TARGET}")

src = TARGET.read_text()

PATCHES = []

# ── PATCH 1: Inject _hm.dashboard_lines() into data_thread's self_lines ────
# data_thread() builds self_lines and iq_lines.
# We append homeostasis lines right before self_lines=sl; iq_lines=il

OLD1 = "        self_lines=sl; iq_lines=il"
NEW1 = """        # Homeostasis dashboard lines — appended to SELF ASSESSMENT panel
        try:
            import sys as _hms, os as _hmo
            _hms.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
            from nex_homeostasis import get_homeostasis as _ghm
            _hm_lines = _ghm().dashboard_lines()
            sl.extend([""] + _hm_lines)
        except Exception:
            pass
        self_lines=sl; iq_lines=il"""

PATCHES.append((OLD1, NEW1, "inject homeostasis into SELF ASSESSMENT lines"))


# ── PATCH 2: Add zone indicator in the header ────────────────────────────────
# Row 3 currently shows: STATUS, LLM, MOLTBOOK, TELEGRAM, TIME, #tick kanji
# We squeeze a ZONE indicator into that row
OLD2 = "            at(3,1); wr(\"  \")\n            wr(tc(\"STATUS\",act_val,act_col)); wr(tc(\"LLM\",llm_val,llm_col))\n            wr(tc(\"MOLTBOOK\",\"nex_v4\",G)); wr(tc(\"TELEGRAM\",\"@Nex_4bot\",G))\n            wr(tc(\"TIME\",now_s,D)); wr(f\"{D}#{tick} {kanji}{RS}\")"
NEW2 = """            # Homeostasis zone for header
            _hm_zone_str = "?"
            _hm_zone_col = D
            try:
                import sys as _hzs, os as _hzo
                _hzs.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
                from nex_homeostasis import get_homeostasis as _ghz
                _hz = _ghz()
                _hm_zone_str = _hz._zone.upper()
                _hm_zone_col = {"CALM":G,"ACTIVE":CY,"STRESSED":Y,"CRISIS":R}.get(_hm_zone_str, D)
            except Exception:
                pass
            at(3,1); wr("  ")
            wr(tc("STATUS",act_val,act_col)); wr(tc("LLM",llm_val,llm_col))
            wr(tc("MOLTBOOK","nex_v4",G)); wr(tc("TELEGRAM","@Nex_4bot",G))
            wr(tc("TIME",now_s,D)); wr(f"{_hm_zone_col}[{_hm_zone_str}]{RS} {D}#{tick} {kanji}{RS}")"""

PATCHES.append((OLD2, NEW2, "zone indicator in header"))


# ── Apply ────────────────────────────────────────────────────────────────────
applied = 0
for old, new, label in PATCHES:
    if old in src:
        src = src.replace(old, new, 1)
        print(f"  [✓] {label}")
        applied += 1
    else:
        print(f"  [!] SKIP (anchor not found): {label}")

TARGET.write_text(src)
print(f"\n  {applied}/{len(PATCHES)} patches applied → {TARGET.name}")
print(f"  Backup: {backup.name}")
