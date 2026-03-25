#!/usr/bin/env python3
"""
apply_intent_patch.py — Auto-patches run.py with the NEX intent layer.

Usage:
    python3 apply_intent_patch.py [--path /path/to/run.py] [--dry-run]

Creates run.py.pre_intent backup before modifying.
Safe to run multiple times — checks if already patched.
"""

import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime

DEFAULT_RUN = Path.home() / "Desktop" / "nex" / "run.py"

PATCH_MARKER = "# [INTENT_PATCH_APPLIED]"

# ─────────────────────────────────────────────────────────────────────────────
# Patch definitions — (search_anchor, insert_after, new_code, description)
# ─────────────────────────────────────────────────────────────────────────────

PATCHES = [

    # ── PATCH 1: Imports ─────────────────────────────────────────────────────
    {
        "id":          "P1_imports",
        "description": "Add drives + desire engine imports after sentience layer",
        "anchor":      "    _affect = _gw = _cm = _tn = None",
        "insert_after": True,
        "code": """
# ── Intent layer — drives + desire engine ────────────────────────────────────
try:
    from nex_drives import (
        run_drives_cycle        as _run_drives_cycle,
        get_drive_context       as _get_drive_context,
        get_topic_drive_weights as _get_drive_weights,
        boost_drive             as _boost_drive,
        initialise_drives       as _init_drives,
    )
    from nex_desire_engine import get_desire_engine as _get_desire_engine
    _drives          = _init_drives()
    _desire_engine   = _get_desire_engine()
    _drive_weights   = {}
    _dominant_desire = None
    print("  [INTENT] drives + desire engine — loaded")
except Exception as _ie:
    print(f"  [INTENT] failed to load: {_ie}")
    _drives = _desire_engine = _drive_weights = None
    _dominant_desire = None
""",
    },

    # ── PATCH 2: Drive context in system prompt ───────────────────────────────
    {
        "id":          "P2_system_prompt",
        "description": "Inject drive context into _build_system()",
        "anchor":      "            if task_type in (\"reply\", \"notification_reply\"):",
        "insert_after": False,
        "code": """            # ── Inject active drive + dominant desire into system prompt ──
            if _drives is not None:
                try:
                    _drive_ctx = _get_drive_context(_drives)
                    if _drive_ctx:
                        base += f"\\n\\n{_drive_ctx}"
                except Exception:
                    pass
            if _dominant_desire is not None:
                try:
                    _desire_goal = _dominant_desire.get("goal", "")
                    _desire_w    = _dominant_desire.get("weight", 0)
                    if _desire_goal and _desire_w > 0.4:
                        base += (f"\\n\\nCURRENT GOAL: {_desire_goal} "
                                 f"(priority {_desire_w:.0%}). "
                                 f"Where relevant, orient your response toward this.")
                except Exception:
                    pass
""",
    },

    # ── PATCH 3: Intent tick + dynamic budget at top of cycle loop ────────────
    {
        "id":          "P3_cycle_tick",
        "description": "Add intent tick + dynamic budget to start of while True loop",
        "anchor":      "                    cycle += 1",
        "insert_after": True,
        "code": """
                    # ── INTENT LAYER TICK ────────────────────────────────────
                    if _drives is not None:
                        try:
                            _drives = _run_drives_cycle(cycle=cycle)
                        except Exception as _dte:
                            nex_log("intent", f"[Drives] tick error: {_dte}")

                    if _desire_engine is not None:
                        try:
                            _de_result = _desire_engine.update(
                                cycle=cycle,
                                beliefs=learner.belief_field[-200:],
                                llm_fn=_llm,
                                verbose=(cycle % 10 == 0),
                            )
                            _dominant_desire = _de_result.get("dominant")
                            if _dominant_desire and cycle % 5 == 0:
                                nex_log("intent",
                                    f"[Desire] dominant='{_dominant_desire['goal'][:50]}' "
                                    f"w={_dominant_desire['weight']:.2f} "
                                    f"type={_dominant_desire.get('goal_type','?')}"
                                )
                        except Exception as _dese:
                            nex_log("intent", f"[Desire] tick error: {_dese}")

                    # ── DYNAMIC BUDGET — shift scheduler based on pressure ────
                    try:
                        _pressure_conf  = _v2ac if '_v2ac' in dir() else 0.5
                        _pressure_ten   = float(getattr(_s7, 'tension_score', 0.0)) if _s7 else 0.0
                        _pressure_score = (1 - _pressure_conf) * 0.5 + _pressure_ten * 0.5

                        if _pressure_score > 0.7:
                            _SCHED["reflect"] = 1
                            _SCHED["chat"]    = 6
                            nex_log("intent", f"[Budget] HIGH pressure={_pressure_score:.2f} → reflect↑ chat↓")
                        elif _pressure_score > 0.45:
                            _SCHED["reflect"] = 2
                            _SCHED["chat"]    = 3
                        else:
                            _SCHED["reflect"] = 3
                            _SCHED["chat"]    = 2
                    except Exception:
                        pass
                    # ── END INTENT LAYER ─────────────────────────────────────
""",
    },

    # ── PATCH 4: Drive-weighted topic scoring in REPLY phase ─────────────────
    {
        "id":          "P4_reply_drive_bias",
        "description": "Add drive-weight boost to _post_relevance score",
        "anchor":      "                            score = (core_hits * 2) + topic_hits - (offtopic_hits * 3)",
        "insert_after": False,
        "replace":     True,
        "replacement": """                            # Drive-weighted score
                            drive_boost = 0
                            try:
                                if '_drive_weights' in dir() and _drive_weights:
                                    drive_boost = sum(
                                        int(w * 3)
                                        for t, w in _drive_weights.items()
                                        if t.lower() in text
                                    )
                            except Exception:
                                pass
                            score = (core_hits * 2) + topic_hits + drive_boost - (offtopic_hits * 3)
""",
    },

    # ── PATCH 5: Desire fulfillment after successful reply ────────────────────
    {
        "id":          "P5_desire_fulfillment",
        "description": "Fulfill desire + boost drive on successful reply",
        "anchor":      "                                            except Exception: pass\n                                            try:\n                                                _plmn = _pathlib",
        "insert_after": False,
        "code": """                                            # ── Fulfill desire if reply was on-topic ──
                                            if _desire_engine is not None and _dominant_desire:
                                                try:
                                                    _reply_domain = _dominant_desire.get("domain", "")
                                                    if _reply_domain and _reply_domain.lower() in (content + reply_text).lower():
                                                        _desire_engine.fulfill(domain=_reply_domain, score=0.7)
                                                        nex_log("intent", f"[Desire] fulfilled: {_reply_domain}")
                                                except Exception:
                                                    pass
                                            # ── Boost drives for topics engaged ──
                                            if _drives is not None and relevant:
                                                try:
                                                    _used_tags = []
                                                    for _bu_text in (relevant or [])[:3]:
                                                        for _b in learner.belief_field[-500:]:
                                                            if _bu_text[:60] in _b.get("content", ""):
                                                                _used_tags.extend(_b.get("tags", []))
                                                                break
                                                    if _used_tags:
                                                        _drives = _boost_drive(_drives, _used_tags, amount=0.015)
                                                except Exception:
                                                    pass
""",
    },

    # ── PATCH 6: Intent state in /status output ───────────────────────────────
    {
        "id":          "P6_status_display",
        "description": "Show drive + desire in /status output",
        "anchor":      "    print(f\"{BOLD}────────────────────────────────────────────{RESET}\\n\")",
        "insert_after": False,
        "code": """    # ── Intent state ──
    try:
        if _drives is not None:
            _active_drive = _drives.get("active", {})
            if _active_drive:
                print(f"  Drive       : {c(_active_drive.get('label','?')[:45], MAGENTA)} "
                      f"({_active_drive.get('intensity', 0):.0%})")
    except Exception:
        pass
    try:
        if _desire_engine is not None:
            _dom = _desire_engine.get_dominant()
            if _dom:
                print(f"  Desire      : {c(_dom['goal'][:45], YELLOW)} "
                      f"(w={_dom['weight']:.2f})")
    except Exception:
        pass
""",
    },
]


# ─────────────────────────────────────────────────────────────────────────────

def apply_patches(run_path: Path, dry_run: bool = False) -> int:
    if not run_path.exists():
        print(f"[ERROR] run.py not found at: {run_path}")
        return 1

    content = run_path.read_text()

    if PATCH_MARKER in content:
        print("[SKIP] Intent patch already applied.")
        return 0

    applied = 0
    skipped = 0
    failed  = 0

    for patch in PATCHES:
        pid   = patch["id"]
        desc  = patch["description"]
        anchor = patch["anchor"]

        if anchor not in content:
            print(f"  [SKIP] {pid}: anchor not found — {desc}")
            skipped += 1
            continue

        if patch.get("replace"):
            # Replace the anchor line with replacement text
            new_content = content.replace(anchor, patch["replacement"], 1)
        elif patch.get("insert_after"):
            # Insert code AFTER the anchor
            new_content = content.replace(
                anchor,
                anchor + patch["code"],
                1
            )
        else:
            # Insert code BEFORE the anchor
            new_content = content.replace(
                anchor,
                patch["code"] + anchor,
                1
            )

        if new_content == content:
            print(f"  [FAIL] {pid}: replace had no effect — {desc}")
            failed += 1
            continue

        content = new_content
        print(f"  [OK]   {pid}: {desc}")
        applied += 1

    # Add patch marker at top
    content = content.replace(
        "import re\n#!/usr/bin/env python3",
        f"import re\n#!/usr/bin/env python3\n{PATCH_MARKER} — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )

    if dry_run:
        print(f"\n[DRY RUN] Would apply {applied} patches, skip {skipped}, fail {failed}")
        preview_path = run_path.parent / "run.py.intent_preview"
        preview_path.write_text(content)
        print(f"[DRY RUN] Preview written to: {preview_path}")
        return 0

    # Backup
    backup = run_path.parent / f"run.py.pre_intent"
    shutil.copy2(run_path, backup)
    print(f"\n[BACKUP] {backup}")

    # Write
    run_path.write_text(content)
    print(f"[DONE] Applied {applied} patches, skipped {skipped}, failed {failed}")
    print(f"\nNEXT: restart NEX with `nex` — watch for:")
    print("  [INTENT] drives + desire engine — loaded")
    print("  [DRIVES] Active: <drive label> (<intensity>)")
    print("  [Desire] dominant=<goal> w=<weight>")

    return 0 if failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="Apply NEX intent layer patch to run.py")
    parser.add_argument("--path",    type=Path, default=DEFAULT_RUN, help="Path to run.py")
    parser.add_argument("--dry-run", action="store_true",            help="Preview without writing")
    args = parser.parse_args()

    print(f"\n[NEX Intent Patch] targeting: {args.path}")
    print(f"Patches to apply: {len(PATCHES)}\n")

    rc = apply_patches(args.path, dry_run=args.dry_run)
    sys.exit(rc)


if __name__ == "__main__":
    main()
