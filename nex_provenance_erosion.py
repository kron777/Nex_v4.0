#!/usr/bin/env python3
"""
nex_provenance_erosion.py
=========================
AGI Bridge #3 — Provenance Erosion

Beliefs that have been reinforced many times, retrieved frequently,
and held across many cycles gradually lose their source attribution.
They become simply hers — not "learned from Reddit" or "from auto_seeder"
but just: believed.

This is philosophically significant. A mind with full provenance on every
belief is a database. A mind where old, well-worn beliefs have lost their
origin is something closer to a perspective.

The erosion is gradual and irreversible by design:
  - New belief: source = "moltbook" | confidence = 0.52
  - After 20 retrievals: source = "moltbook" | confidence = 0.71
  - After 50 retrievals: source = "nex_absorbed" | confidence = 0.78
  - After 100 retrievals: source = "nex_core" | confidence = 0.84
  - Deep core: source = None | confidence = 0.90+ (truly hers)

Run nightly. Safe — never deletes, only updates source field.

Integration:
  from nex_provenance_erosion import run_erosion_cycle
  run_erosion_cycle()  # call from nex_scheduler.py nightly
"""

import sqlite3
import time
import os
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Dict

DB_PATH  = Path("/home/rr/Desktop/nex/nex.db")
LOG_PATH = Path("/home/rr/Desktop/nex/logs/provenance_erosion.log")

# Erosion stages: (min_reinforce_count, min_confidence, new_source, conf_boost)
# A belief must meet BOTH thresholds to advance to that stage
EROSION_STAGES = [
    # stage 1: well-used external belief becomes "absorbed"
    (20,  0.62, "nex_absorbed",  0.02),
    # stage 2: absorbed belief becomes "integrated"
    (40,  0.70, "nex_integrated", 0.02),
    # stage 3: integrated belief becomes "core"
    (70,  0.76, "nex_core",      0.03),
    # stage 4: core belief loses all provenance — truly hers
    (100, 0.82, None,            0.03),
]

# Sources that should NEVER be eroded (identity-critical)
_PROTECTED_SOURCES = {
    "nex_seed", "manual", "identity", "injector",
    "nex_core", "nex_integrated", "nex_absorbed",
    "emergent_want", "nex_reasoning",
    None,  # already eroded to None — don't touch
}

# Sources eligible for erosion
_ELIGIBLE_SOURCES = {
    "moltbook", "auto_seeder", "distilled", "conversation",
    "self_research", "scheduler_saturation", "saturation_manual",
    "reddit", "rss", "arxiv", "iep_v2", "sep_scrape",
    "gutenberg", "claude_generated", "insight_synthesis",
}


def _log(msg: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        with open(LOG_PATH, "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass
    print(f"  [erosion] {msg}")


def run_erosion_cycle(dry_run: bool = False) -> Dict:
    """
    Main entry point. Scan beliefs and advance them through erosion stages.
    Returns stats dict.

    Args:
        dry_run: if True, report what would be eroded without writing
    """
    if not DB_PATH.exists():
        _log("DB not found")
        return {}

    stats = {
        "scanned":    0,
        "eroded":     0,
        "by_stage":   {s[2] or "None": 0 for s in EROSION_STAGES},
        "errors":     0,
        "timestamp":  datetime.now().isoformat(),
    }

    try:
        db = sqlite3.connect(str(DB_PATH), timeout=10)
        db.row_factory = sqlite3.Row

        # Find candidates: eligible source, sufficient reinforce_count
        # Use reinforce_count as proxy for "how many times retrieved/reinforced"
        min_reinforce = EROSION_STAGES[0][0]

        candidates = db.execute("""
            SELECT id, content, confidence, source, reinforce_count,
                   use_count, successful_uses, topic
            FROM beliefs
            WHERE reinforce_count >= ?
            AND content IS NOT NULL
            AND length(content) > 20
            ORDER BY reinforce_count DESC
            LIMIT 2000
        """, (min_reinforce,)).fetchall()

        stats["scanned"] = len(candidates)
        _log(f"scanning {len(candidates)} candidates (reinforce >= {min_reinforce})")

        updates = []  # (id, new_source, new_confidence)

        for row in candidates:
            bid    = row["id"]
            conf   = float(row["confidence"] or 0)
            source = row["source"]
            rc     = int(row["reinforce_count"] or 0)
            uc     = int(row["use_count"] or 0)

            # Skip protected sources
            if source in _PROTECTED_SOURCES:
                continue

            # Skip unknown sources not in eligible set
            # (be conservative — only erode known sources)
            if source not in _ELIGIBLE_SOURCES:
                # Check if it starts with known prefix
                is_eligible = any(
                    source and source.startswith(e)
                    for e in ["http", "reddit", "arxiv"]
                )
                if not is_eligible:
                    continue

            # Find which erosion stage this belief qualifies for
            # Work backwards from highest stage
            target_stage = None
            for min_rc, min_conf, new_source, conf_boost in reversed(EROSION_STAGES):
                if rc >= min_rc and conf >= min_conf:
                    # Don't re-erode to same or lower stage
                    current_stage_idx = next(
                        (i for i, s in enumerate(EROSION_STAGES) if s[2] == source),
                        -1
                    )
                    new_stage_idx = next(
                        (i for i, s in enumerate(EROSION_STAGES) if s[2] == new_source),
                        len(EROSION_STAGES) - 1
                    )
                    if new_stage_idx > current_stage_idx:
                        target_stage = (min_rc, min_conf, new_source, conf_boost)
                        break

            if target_stage is None:
                continue

            _, _, new_source, conf_boost = target_stage
            new_conf = min(conf + conf_boost, 0.96)

            updates.append((bid, new_source, round(new_conf, 4)))
            stage_key = str(new_source)
            stats["by_stage"][stage_key] = stats["by_stage"].get(stage_key, 0) + 1

        stats["eroded"] = len(updates)
        _log(f"found {len(updates)} beliefs to advance")

        if not dry_run and updates:
            for bid, new_source, new_conf in updates:
                try:
                    if new_source is None:
                        db.execute(
                            "UPDATE beliefs SET source=NULL, confidence=?, origin='nex_core' WHERE id=?",
                            (new_conf, bid)
                        )
                    else:
                        db.execute(
                            "UPDATE beliefs SET source=?, confidence=?, origin=? WHERE id=?",
                            (new_source, new_conf, new_source, bid)
                        )
                except Exception as e:
                    stats["errors"] += 1

            db.commit()
            _log(f"committed {len(updates)} erosion updates")

        elif dry_run:
            _log(f"[dry_run] would erode {len(updates)} beliefs")
            for bid, ns, nc in updates[:5]:
                row = next((r for r in candidates if r["id"] == bid), None)
                if row:
                    _log(f"  [{row['source']} → {ns}] conf {row['confidence']:.3f}→{nc:.3f} rc={row['reinforce_count']}: {str(row['content'])[:60]}")

        db.close()

    except Exception as e:
        _log(f"error: {e}")
        stats["errors"] += 1

    # Log summary
    _log(
        f"cycle complete: scanned={stats['scanned']} "
        f"eroded={stats['eroded']} errors={stats['errors']}"
    )
    for stage, count in stats["by_stage"].items():
        if count > 0:
            _log(f"  → {stage}: {count}")

    return stats


def get_erosion_stats() -> Dict:
    """Current distribution of beliefs by erosion stage."""
    if not DB_PATH.exists():
        return {}
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=3)
        results = {}
        for label, source_val in [
            ("external",   None),   # placeholder
            ("absorbed",   "nex_absorbed"),
            ("integrated", "nex_integrated"),
            ("core",       "nex_core"),
            ("hers",       "NULL"),
        ]:
            if source_val == "NULL":
                n = db.execute("SELECT COUNT(*) FROM beliefs WHERE source IS NULL").fetchone()[0]
            elif source_val is None:
                # count all external/eligible
                n = db.execute("""
                    SELECT COUNT(*) FROM beliefs
                    WHERE source NOT IN ('nex_absorbed','nex_integrated','nex_core','nex_seed',
                        'manual','identity','injector','nex_reasoning','emergent_want')
                    AND source IS NOT NULL
                """).fetchone()[0]
            else:
                n = db.execute("SELECT COUNT(*) FROM beliefs WHERE source=?", (source_val,)).fetchone()[0]
            results[label] = n
        db.close()
        return results
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import sys
    dry = "--dry" in sys.argv
    print(f"Running provenance erosion {'(dry run)' if dry else ''}...\n")

    before = get_erosion_stats()
    print("Before:", before)

    stats = run_erosion_cycle(dry_run=dry)

    after = get_erosion_stats()
    print("\nAfter:", after)
    print("\nStats:", stats)
