#!/usr/bin/env python3
"""
apply_final_patch.py — NEX Final Upgrades: Value→Synthesis + Meta-Strategy

Covers the two remaining gaps:
  1. VALUE→SYNTHESIS: drive weights flow into cognition.py's run_synthesis()
     so high-drive topics get synthesised first and more aggressively
  2. META-STRATEGY: nex_meta_layer.py gets consulted each cycle to select
     a cognitive mode (resolve / explore / optimize) that shapes NEX's behaviour

Usage:
    cd ~/Desktop/nex
    python3 apply_final_patch.py --dry-run
    python3 apply_final_patch.py

Creates backups before touching any file.
Safe to run multiple times — checks patch markers.
"""

import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime

NEX_ROOT     = Path.home() / "Desktop" / "nex"
RUN_PY       = NEX_ROOT / "run.py"
COGNITION_PY = NEX_ROOT / "nex" / "cognition.py"

MARKER_RUN  = "# [FINAL_PATCH_RUN_APPLIED]"
MARKER_COG  = "# [FINAL_PATCH_COGNITION_APPLIED]"

# ─────────────────────────────────────────────────────────────────────────────
# COGNITION.PY PATCHES
# ─────────────────────────────────────────────────────────────────────────────

# C1: Add drive-weighted cluster sorting to run_synthesis()
# Find the line that sorts clusters by size and replace with drive-aware sort
COG_C1_OLD = """    # Sort clusters by size — synthesize largest first, cap LLM calls at 15
    _sorted_clusters = sorted(clusters.items(), key=lambda x: len(x[1]["beliefs"]), reverse=True)"""

COG_C1_NEW = """    # Sort clusters by size + drive weight — drive topics get synthesised first
    # Drive weights are injected at call time via _drive_topic_weights kwarg
    def _cluster_priority(item):
        name, cluster = item
        size_score  = len(cluster["beliefs"])
        drive_score = _drive_topic_weights.get(name, 0) * 200  # drive boost
        return size_score + drive_score

    _sorted_clusters = sorted(clusters.items(), key=_cluster_priority, reverse=True)"""


# C2: Add _drive_topic_weights parameter to run_synthesis() signature
COG_C2_OLD = "def run_synthesis(min_beliefs=15, llm_fn=None):"
COG_C2_NEW = "def run_synthesis(min_beliefs=15, llm_fn=None, drive_weights=None):"


# C3: Resolve _drive_topic_weights inside run_synthesis body
# Insert after the existing_insights load line
COG_C3_OLD = "    existing_insights = load_json(INSIGHTS_PATH, [])"
COG_C3_NEW = """    existing_insights = load_json(INSIGHTS_PATH, [])

    # Drive weights — topics NEX is currently driven to understand get priority
    _drive_topic_weights = drive_weights or {}
    # Also pull live drives file if no weights passed in
    if not _drive_topic_weights:
        try:
            import json as _dwj
            from pathlib import Path as _dwp
            _dw_path = _dwp.home() / ".config" / "nex" / "nex_drives.json"
            if _dw_path.exists():
                _dw_data = _dwj.loads(_dw_path.read_text())
                for _dw in _dw_data.get("primary", []) + _dw_data.get("secondary", []):
                    for _dw_tag in _dw.get("tags", []):
                        _drive_topic_weights[_dw_tag] = max(
                            _drive_topic_weights.get(_dw_tag, 0),
                            _dw.get("intensity", 0)
                        )
        except Exception:
            pass"""


# C4: Force re-synthesis of drive-priority topics even with low growth
# Insert inside the cluster loop, modifying the skip condition
COG_C4_OLD = """            if growth < 0.05 and not (_is_template or _not_llm):
                skipped += 1
                continue"""
COG_C4_NEW = """            # Always re-synthesise if this is a high-drive topic
            _is_drive_priority = _drive_topic_weights.get(name, 0) > 0.6
            if growth < 0.05 and not (_is_template or _not_llm) and not _is_drive_priority:
                skipped += 1
                continue"""


# ─────────────────────────────────────────────────────────────────────────────
# RUN.PY PATCHES
# ─────────────────────────────────────────────────────────────────────────────

# R1: Import meta layer at startup (after intent layer imports)
RUN_R1_OLD = '    print("  [INTENT] drives + desire engine — loaded")'
RUN_R1_NEW = '''    print("  [INTENT] drives + desire engine — loaded")
except Exception as _ie:
    print(f"  [INTENT] failed to load: {_ie}")
    _drives = _desire_engine = _drive_weights = None
    _dominant_desire = None

# ── Meta-strategy layer ───────────────────────────────────────────────────────
try:
    from nex_meta_layer import get_meta_layer as _get_meta_layer, record_module_call as _rmc
    _meta_layer   = _get_meta_layer()
    _cog_mode     = "explore"   # resolve | explore | optimize
    _cog_mode_reason = ""
    print("  [META] meta-strategy layer — loaded")
except Exception as _mle:
    print(f"  [META] failed to load: {_mle}")
    _meta_layer = None
    _cog_mode   = "explore"
    _cog_mode_reason = ""
    def _rmc(*a, **k): pass'''

# The above replaces the closing except of the intent block — we need a cleaner anchor
# Use a different anchor that's unique
RUN_R1_OLD = """    _drives          = _init_drives()
    _desire_engine   = _get_desire_engine()
    _drive_weights   = {}
    _dominant_desire = None
    print("  [INTENT] drives + desire engine — loaded")
except Exception as _ie:
    print(f"  [INTENT] failed to load: {_ie}")
    _drives = _desire_engine = _drive_weights = None
    _dominant_desire = None"""

RUN_R1_NEW = """    _drives          = _init_drives()
    _desire_engine   = _get_desire_engine()
    _drive_weights   = {}
    _dominant_desire = None
    print("  [INTENT] drives + desire engine — loaded")
except Exception as _ie:
    print(f"  [INTENT] failed to load: {_ie}")
    _drives = _desire_engine = _drive_weights = None
    _dominant_desire = None

# ── Meta-strategy layer ───────────────────────────────────────────────────────
try:
    from nex_meta_layer import get_meta_layer as _get_meta_layer, record_module_call as _rmc
    _meta_layer      = _get_meta_layer()
    _cog_mode        = "explore"
    _cog_mode_reason = ""
    print("  [META] meta-strategy layer — loaded")
except Exception as _mle:
    print(f"  [META] failed to load: {_mle}")
    _meta_layer      = None
    _cog_mode        = "explore"
    _cog_mode_reason = ""
    def _rmc(*a, **k): pass"""


# R2: Meta-strategy selection at top of cycle (after intent tick, before upgrade ticks)
# Insert after the dynamic budget block
RUN_R2_OLD = "                    # ── END INTENT LAYER ─────────────────────────────────────"
RUN_R2_NEW = """                    # ── END INTENT LAYER ─────────────────────────────────────

                    # ── META-STRATEGY SELECTION ──────────────────────────────
                    # Every 5 cycles, consult meta layer to choose cognitive mode.
                    # Mode shapes synthesis priority, reflection depth, curiosity type.
                    if cycle % 5 == 0 and _meta_layer is not None:
                        try:
                            _alerts     = _meta_layer.get_alerts()
                            _perf       = _meta_layer.get_performance_report()
                            _top        = _perf[0]["module"] if _perf else ""
                            _silent     = [r["module"] for r in _perf if r["silent_cycles"] > 8]

                            # Mode selection logic
                            _contra_load = 0
                            try:
                                import sqlite3 as _mssq
                                with _mssq.connect(
                                    str(Path.home()/'.config/nex/nex.db'), timeout=3
                                ) as _mc:
                                    _contra_load = _mc.execute(
                                        "SELECT COUNT(*) FROM beliefs "
                                        "WHERE topic LIKE '%contradiction%'"
                                    ).fetchone()[0]
                            except Exception:
                                pass

                            _pressure_val = (1 - (_v2ac if '_v2ac' in dir() else 0.5)) * 0.5 \
                                          + float(getattr(_s7,'tension_score',0)) * 0.5 \
                                          if _s7 else 0.3

                            if _contra_load > 50 or _pressure_val > 0.65:
                                _cog_mode        = "resolve"
                                _cog_mode_reason = f"contra={_contra_load} pressure={_pressure_val:.2f}"
                            elif len(_alerts) > 3 or len(_silent) > 4:
                                _cog_mode        = "resolve"
                                _cog_mode_reason = f"{len(_alerts)} alerts, {len(_silent)} silent modules"
                            elif _pressure_val < 0.3:
                                _cog_mode        = "explore"
                                _cog_mode_reason = f"low pressure={_pressure_val:.2f}"
                            else:
                                _cog_mode        = "optimize"
                                _cog_mode_reason = "stable state"

                            nex_log("meta", f"[META] mode={_cog_mode} reason={_cog_mode_reason}")

                            # Apply mode to scheduler
                            if _cog_mode == "resolve":
                                _SCHED["reflect"]    = 1
                                _SCHED["gap_detect"] = 2
                            elif _cog_mode == "explore":
                                _SCHED["reflect"]    = 3
                                _SCHED["gap_detect"] = 3
                                _SCHED["chat"]       = 2
                            else:  # optimize
                                _SCHED["reflect"]    = 2
                                _SCHED["gap_detect"] = 4

                        except Exception as _mse:
                            nex_log("meta", f"[META] error: {_mse}")
                    # ── END META-STRATEGY ─────────────────────────────────────"""


# R3: Pass drive weights into run_synthesis call inside _run_cognition_cycle
# Find the cognition call in the COGNITION phase
RUN_R3_OLD = "                            _run_cognition_cycle(client, learner, conversations, cycle, llm_fn=_llm)"
RUN_R3_NEW = """                            # Pass drive weights so synthesis prioritises driven topics
                            _synth_drive_weights = {}
                            try:
                                if _drives is not None:
                                    _synth_drive_weights = _get_drive_weights(_drives)
                                if _dominant_desire is not None:
                                    _dd_domain = _dominant_desire.get("domain", "")
                                    if _dd_domain:
                                        _synth_drive_weights[_dd_domain] = max(
                                            _synth_drive_weights.get(_dd_domain, 0), 0.95)
                            except Exception:
                                pass
                            _run_cognition_cycle(
                                client, learner, conversations, cycle,
                                llm_fn=_llm,
                                drive_weights=_synth_drive_weights,
                                cog_mode=_cog_mode,
                            )"""


# R4: Record meta-layer module calls after key phases
# After LLM succeeds in _llm() function
RUN_R4_OLD = '                            print(f"  [Mistral-7B ✓] {task_type}: {result[:60]}…")'
RUN_R4_NEW = '''                            print(f"  [Mistral-7B ✓] {task_type}: {result[:60]}…")
                            try: _rmc("llm_local", success=True, value=1)
                            except Exception: pass'''


# R5: Show cognitive mode in /status
RUN_R5_OLD = """    # ── Intent state ──
    try:
        if _drives is not None:"""
RUN_R5_NEW = """    # ── Meta-strategy + Intent state ──
    try:
        print(f"  Cog Mode    : {c(_cog_mode.upper(), CYAN)} — {_cog_mode_reason[:40]}")
    except Exception:
        pass
    try:
        if _meta_layer is not None:
            print(f"  Modules     : {c(_meta_layer.summary(), DIM)}")
    except Exception:
        pass
    try:
        if _drives is not None:"""


# ─────────────────────────────────────────────────────────────────────────────
# Also patch cognition.py's run_cognition_cycle to accept + pass drive_weights
# ─────────────────────────────────────────────────────────────────────────────

# Find run_cognition_cycle signature
COG_R1_OLD = "def run_cognition_cycle(client, learner, conversations, cycle, llm_fn=None):"
COG_R1_NEW = "def run_cognition_cycle(client, learner, conversations, cycle, llm_fn=None, drive_weights=None, cog_mode='explore'):"

# Find the run_synthesis call inside run_cognition_cycle and pass drive_weights
COG_R2_OLD = "        insights, new_count = run_synthesis(llm_fn=llm_fn)"
COG_R2_NEW = """        # Pass drive weights + cog_mode into synthesis
        insights, new_count = run_synthesis(
            llm_fn=llm_fn,
            drive_weights=drive_weights or {},
        )"""

# Also shape synthesis LLM cap based on cog_mode
COG_R3_OLD = "    _LLM_CAP = 60"
COG_R3_NEW = """    # Cog mode shapes how aggressively we synthesise
    # resolve → more synthesis to resolve contradictions
    # explore → normal
    # optimize → fewer calls, focus on quality
    _LLM_CAP = {"resolve": 80, "explore": 60, "optimize": 40}.get(
        getattr(run_synthesis, '_cog_mode_hint', 'explore'), 60
    )"""


# ─────────────────────────────────────────────────────────────────────────────

COGNITION_PATCHES = [
    {
        "id":    "C1_drive_sort",
        "desc":  "Drive-weighted cluster sorting in run_synthesis",
        "old":   COG_C1_OLD,
        "new":   COG_C1_NEW,
    },
    {
        "id":    "C2_signature",
        "desc":  "Add drive_weights param to run_synthesis signature",
        "old":   COG_C2_OLD,
        "new":   COG_C2_NEW,
    },
    {
        "id":    "C3_weights_resolve",
        "desc":  "Resolve _drive_topic_weights inside run_synthesis",
        "old":   COG_C3_OLD,
        "new":   COG_C3_NEW,
    },
    {
        "id":    "C4_drive_force_resynth",
        "desc":  "Force re-synthesis for high-drive topics",
        "old":   COG_C4_OLD,
        "new":   COG_C4_NEW,
    },
    {
        "id":    "C5_cycle_signature",
        "desc":  "Add drive_weights + cog_mode to run_cognition_cycle",
        "old":   COG_R1_OLD,
        "new":   COG_R1_NEW,
    },
    {
        "id":    "C6_pass_weights",
        "desc":  "Pass drive_weights into run_synthesis call",
        "old":   COG_R2_OLD,
        "new":   COG_R2_NEW,
    },
    {
        "id":    "C7_llm_cap",
        "desc":  "Shape LLM synthesis cap by cog_mode",
        "old":   COG_R3_OLD,
        "new":   COG_R3_NEW,
    },
]

RUN_PATCHES = [
    {
        "id":    "R1_meta_import",
        "desc":  "Import meta-strategy layer at startup",
        "old":   RUN_R1_OLD,
        "new":   RUN_R1_NEW,
    },
    {
        "id":    "R2_meta_cycle",
        "desc":  "Meta-strategy mode selection each cycle",
        "old":   RUN_R2_OLD,
        "new":   RUN_R2_NEW,
    },
    {
        "id":    "R3_drive_synth",
        "desc":  "Pass drive weights into cognition cycle",
        "old":   RUN_R3_OLD,
        "new":   RUN_R3_NEW,
    },
    {
        "id":    "R4_meta_record",
        "desc":  "Record LLM calls in meta layer",
        "old":   RUN_R4_OLD,
        "new":   RUN_R4_NEW,
    },
    {
        "id":    "R5_status",
        "desc":  "Show cog mode + module health in /status",
        "old":   RUN_R5_OLD,
        "new":   RUN_R5_NEW,
    },
]


# ─────────────────────────────────────────────────────────────────────────────

def apply(path: Path, patches: list, marker: str, dry_run: bool) -> tuple:
    content = path.read_text()

    if marker in content:
        print(f"  [SKIP] {path.name} already patched")
        return 0, 0, 0

    applied = skipped = failed = 0

    for p in patches:
        if p["old"] not in content:
            print(f"  [SKIP] {p['id']}: anchor not found — {p['desc']}")
            skipped += 1
            continue
        content = content.replace(p["old"], p["new"], 1)
        print(f"  [OK]   {p['id']}: {p['desc']}")
        applied += 1

    # Add marker
    content = content[:50] + f"\n{marker} — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n" + content[50:]

    if dry_run:
        preview = path.parent / (path.name + ".final_preview")
        preview.write_text(content)
        print(f"  [DRY RUN] preview → {preview}")
    else:
        backup = path.parent / (path.name + ".pre_final")
        shutil.copy2(path, backup)
        print(f"  [BACKUP] {backup}")
        path.write_text(content)

    return applied, skipped, failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"\n[NEX Final Patch] {'DRY RUN — ' if args.dry_run else ''}targeting {NEX_ROOT}\n")

    print(f"── cognition.py ({len(COGNITION_PATCHES)} patches) ──")
    ca, cs, cf = apply(COGNITION_PY, COGNITION_PATCHES, MARKER_COG, args.dry_run)

    print(f"\n── run.py ({len(RUN_PATCHES)} patches) ──")
    ra, rs, rf = apply(RUN_PY, RUN_PATCHES, MARKER_RUN, args.dry_run)

    total_a = ca + ra
    total_s = cs + rs
    total_f = cf + rf

    print(f"\n[DONE] applied={total_a} skipped={total_s} failed={total_f}")

    if not args.dry_run and total_f == 0:
        print("\nNEXT: restart NEX with `nex` — watch for:")
        print("  [META] meta-strategy layer — loaded")
        print("  [META] mode=resolve|explore|optimize reason=...")
        print("  /status will now show: Cog Mode + Modules health")

    return 0 if total_f == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
