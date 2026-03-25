#!/usr/bin/env python3
"""
apply_fix_patch.py — Fixes 4 real issues found in audit

Issues:
  1. CRITICAL: run.py line ~2511 — indentation bug, _synth_drive_weights block
     is outside the `if _run_cognition_cycle:` guard → SyntaxError/logic bug
  2. CRITICAL: run_cognition_cycle() doesn't accept drive_weights/cog_mode
     but run.py calls it with those kwargs → TypeError every cognition cycle
  3. MISSING: nex_signal_filter not wired — ImportanceGate/SourceScorer
     never called. Beliefs absorbed with no importance gate.
  4. MISSING: boost_belief_energy() never called when beliefs are used in
     replies — nex_belief_survival runs but beliefs never get energy boosts
     so everything decays equally regardless of use.

Usage:
    cd ~/Desktop/nex
    python3 apply_fix_patch.py --dry-run
    python3 apply_fix_patch.py
"""

import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime

NEX_ROOT     = Path.home() / "Desktop" / "nex"
RUN_PY       = NEX_ROOT / "run.py"
COGNITION_PY = NEX_ROOT / "nex" / "cognition.py"

MARKER_RUN = "# [FIX_PATCH_APPLIED]"
MARKER_COG = "# [FIX_PATCH_COG_APPLIED]"

# ─────────────────────────────────────────────────────────────────────────────
# FIX 1 + 2: run.py — fix indentation bug + remove unsupported kwargs
# ─────────────────────────────────────────────────────────────────────────────

FIX_RUN_1_OLD = """                        try:
                            if _run_cognition_cycle:
                                # Pass drive weights so synthesis prioritises driven topics
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

FIX_RUN_1_NEW = """                        try:
                            if _run_cognition_cycle:
                                # Build drive weights to pass into synthesis
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
                                # Inject drive weights via module-level hint
                                # (run_cognition_cycle doesn't accept kwargs — use hint attr)
                                try:
                                    import nex.cognition as _cog_mod
                                    _cog_mod.run_synthesis._drive_weights_hint = _synth_drive_weights
                                    _cog_mod.run_synthesis._cog_mode_hint = _cog_mode
                                except Exception:
                                    pass
                                _run_cognition_cycle(
                                    client, learner, conversations, cycle,
                                    llm_fn=_llm,
                                )"""

# ─────────────────────────────────────────────────────────────────────────────
# FIX 3: run.py — wire ImportanceGate into ABSORB phase
# Insert signal filter import + gate check into belief absorption
# ─────────────────────────────────────────────────────────────────────────────

# After sentience layer, add signal filter singleton
FIX_RUN_2_OLD = """# ── Intent layer — drives + desire engine ────────────────────────────────────"""

FIX_RUN_2_NEW = """# ── Signal filter — importance gate + source scorer ─────────────────────────
try:
    from nex_signal_filter import get_scorer as _get_scorer, get_gate as _get_gate
    _signal_scorer = _get_scorer()
    _signal_gate   = _get_gate()
    print("  [SIGNAL] importance gate + source scorer — loaded")
except Exception as _sfe:
    print(f"  [SIGNAL] failed to load: {_sfe}")
    _signal_scorer = None
    _signal_gate   = None

# ── Intent layer — drives + desire engine ────────────────────────────────────"""

# Wire gate into the spam-check block in ABSORB — after spam filter, before append
FIX_RUN_3_OLD = """                            if not _is_spam:
                                learner.belief_field.append(belief); nex_log("belief", f"Stored belief from @{belief.get("author","?")} [{int(belief.get("confidence",0)*100)}%]: {belief.get("content","")[:80]}")"""

FIX_RUN_3_NEW = """                            if not _is_spam:
                                # ── Importance gate ──────────────────────────
                                _item_important = True
                                if _signal_gate is not None:
                                    try:
                                        _src_mult = _signal_scorer.get_multiplier(
                                            belief.get("source", "moltbook")
                                        ) if _signal_scorer else 1.0
                                        _item_score = _signal_gate.score(
                                            p.get("title", ""),
                                            belief.get("content", ""),
                                            belief.get("source", "moltbook"),
                                            _src_mult,
                                        )
                                        _item_important = _item_score >= _signal_gate.MIN_IMPORTANCE
                                        if not _item_important:
                                            nex_log("signal", f"[SignalFilter] SUPPRESSED: score={_item_score:.2f} @{belief.get('author','?')}")
                                    except Exception:
                                        pass
                                if not _item_important:
                                    learner.known_posts.add(pid)
                                    continue
                                # ─────────────────────────────────────────────
                                learner.belief_field.append(belief); nex_log("belief", f"Stored belief from @{belief.get('author','?')} [{int(belief.get('confidence',0)*100)}%]: {belief.get('content','')[:80]}")"""

# ─────────────────────────────────────────────────────────────────────────────
# FIX 4: run.py — wire boost_belief_energy when beliefs are used in replies
# Insert after existing reinforce_belief calls
# ─────────────────────────────────────────────────────────────────────────────

# After notification reply reinforce_belief block
FIX_RUN_4_OLD = """                                            # ── Fulfill desire if reply was on-topic ──"""

FIX_RUN_4_NEW = """                                            # ── Boost energy for beliefs used in this reply ──
                                            try:
                                                from nex_belief_survival import boost_belief_energy as _bbe
                                                for _bu_e in (relevant or [])[:3]:
                                                    if isinstance(_bu_e, str) and len(_bu_e) > 10:
                                                        _bbe(_bu_e)
                                                if _signal_scorer is not None:
                                                    _signal_scorer.record_signal(
                                                        belief.get("source", "moltbook") if 'belief' in dir() else "moltbook"
                                                    )
                                            except Exception:
                                                pass
                                            # ── Fulfill desire if reply was on-topic ──"""

# ─────────────────────────────────────────────────────────────────────────────
# FIX 5: cognition.py — use _drive_weights_hint attr in run_synthesis
# Replace the static attr lookup with the hint injected from run.py
# ─────────────────────────────────────────────────────────────────────────────

FIX_COG_1_OLD = """    # Drive weights — topics NEX is currently driven to understand get priority
    _drive_topic_weights = drive_weights or {}
    # Also pull live drives file if no weights passed in
    if not _drive_topic_weights:"""

FIX_COG_1_NEW = """    # Drive weights — check hint attr first (injected from run.py), then param, then file
    _drive_topic_weights = (
        getattr(run_synthesis, '_drive_weights_hint', None)
        or drive_weights
        or {}
    )
    # Clear hint after consuming it
    try:
        run_synthesis._drive_weights_hint = {}
    except Exception:
        pass
    if not _drive_topic_weights:"""

# Also fix the cog_mode hint lookup
FIX_COG_2_OLD = """    _LLM_CAP = {"resolve": 80, "explore": 60, "optimize": 40}.get(
        getattr(run_synthesis, '_cog_mode_hint', 'explore'), 60
    )"""

FIX_COG_2_NEW = """    _active_cog_mode = getattr(run_synthesis, '_cog_mode_hint', 'explore')
    _LLM_CAP = {"resolve": 80, "explore": 60, "optimize": 40}.get(_active_cog_mode, 60)
    try:
        run_synthesis._cog_mode_hint = 'explore'  # reset after consuming
    except Exception:
        pass"""

# ─────────────────────────────────────────────────────────────────────────────

RUN_FIXES = [
    {
        "id":   "F1_cognition_indent",
        "desc": "Fix indentation bug in cognition cycle call + remove bad kwargs",
        "old":  FIX_RUN_1_OLD,
        "new":  FIX_RUN_1_NEW,
    },
    {
        "id":   "F2_signal_import",
        "desc": "Import signal filter gate + scorer at startup",
        "old":  FIX_RUN_2_OLD,
        "new":  FIX_RUN_2_NEW,
    },
    {
        "id":   "F3_importance_gate",
        "desc": "Wire ImportanceGate into ABSORB belief intake",
        "old":  FIX_RUN_3_OLD,
        "new":  FIX_RUN_3_NEW,
    },
    {
        "id":   "F4_energy_boost",
        "desc": "boost_belief_energy() on used beliefs + record_signal on source",
        "old":  FIX_RUN_4_OLD,
        "new":  FIX_RUN_4_NEW,
    },
]

COG_FIXES = [
    {
        "id":   "FC1_hint_attr",
        "desc": "Use _drive_weights_hint attr injected from run.py",
        "old":  FIX_COG_1_OLD,
        "new":  FIX_COG_1_NEW,
    },
    {
        "id":   "FC2_cog_mode_hint",
        "desc": "Use _cog_mode_hint attr and reset after consuming",
        "old":  FIX_COG_2_OLD,
        "new":  FIX_COG_2_NEW,
    },
]


def apply(path: Path, fixes: list, marker: str, dry_run: bool):
    content = path.read_text()

    if marker in content:
        print(f"  [SKIP] {path.name} already patched")
        return 0, 0

    applied = skipped = 0
    for f in fixes:
        if f["old"] not in content:
            print(f"  [SKIP] {f['id']}: anchor not found — {f['desc']}")
            skipped += 1
            continue
        content = content.replace(f["old"], f["new"], 1)
        print(f"  [OK]   {f['id']}: {f['desc']}")
        applied += 1

    content = content[:50] + f"\n{marker} — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n" + content[50:]

    if dry_run:
        preview = path.parent / (path.name + ".fix_preview")
        preview.write_text(content)
        print(f"  [DRY RUN] → {preview}")
    else:
        backup = path.parent / (path.name + ".pre_fix")
        shutil.copy2(path, backup)
        print(f"  [BACKUP] {backup}")
        path.write_text(content)

    return applied, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"\n[NEX Fix Patch] {'DRY RUN — ' if args.dry_run else ''}targeting {NEX_ROOT}\n")

    print(f"── run.py ({len(RUN_FIXES)} fixes) ──")
    ra, rs = apply(RUN_PY, RUN_FIXES, MARKER_RUN, args.dry_run)

    print(f"\n── cognition.py ({len(COG_FIXES)} fixes) ──")
    ca, cs = apply(COGNITION_PY, COG_FIXES, MARKER_COG, args.dry_run)

    total_a = ra + ca
    total_s = rs + cs

    print(f"\n[DONE] applied={total_a} skipped={total_s}")

    if not args.dry_run:
        print("\nNEXT:")
        print("  nex  — restart and watch for [SIGNAL] in startup")
        print("  After 5+ cycles: [SignalFilter] SUPPRESSED lines = gate working")
        print("  [BeliefSurvival] amplified=N = energy boosts working")

    return 0


if __name__ == "__main__":
    sys.exit(main())
