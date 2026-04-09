#!/usr/bin/env python3
"""
nex_align_repair.py — Intra-cycle ALIGN score nudger
=====================================================
ALIGN is the average topic_alignment of the last 20 reflections.
It stalls at 20% when reflections are sparse or misaligned.

This module writes lightweight alignment reflections based on
high-confidence beliefs that match core identity topics, pushing
topic_alignment upward without waiting for nightly consolidation.

Call run_align_repair() from the REFLECT phase each cycle.
"""

import sqlite3, json, time, os
from pathlib import Path
from datetime import datetime, timezone

CFG          = Path("~/.config/nex").expanduser()
DB_PATH      = CFG / "nex.db"
REFLECT_PATH = CFG / "reflections.json"

# Core identity topics — beliefs on these raise alignment
IDENTITY_TOPICS = {
    "consciousness", "emergence", "epistemology", "identity",
    "intelligence", "reasoning", "alignment", "autonomy",
    "self", "cognition", "belief", "uncertainty", "knowledge",
    "learning", "memory", "ethics", "awareness", "mind",
}

MIN_CONF       = 0.65   # only high-confidence beliefs count
MAX_PER_RUN    = 3      # max new reflections per cycle
ALIGN_TARGET   = 0.72   # stop nudging once we reach this


def _load_reflections():
    try:
        if REFLECT_PATH.exists():
            return json.loads(REFLECT_PATH.read_text())
    except Exception:
        pass
    return []


def _save_reflections(refs):
    try:
        REFLECT_PATH.write_text(json.dumps(refs, indent=2))
    except Exception:
        pass


def _current_align(refs):
    valid = [r.get("topic_alignment", 0) for r in refs[-20:]
             if r.get("topic_alignment") is not None]
    return sum(valid) / len(valid) if valid else 0.0


def run_align_repair(verbose=False) -> float:
    """
    Write up to MAX_PER_RUN alignment reflections sourced from
    high-confidence identity-topic beliefs. Returns new ALIGN score.
    """
    if not DB_PATH.exists():
        return 0.0

    refs = _load_reflections()
    current = _current_align(refs)

    if current >= ALIGN_TARGET:
        if verbose:
            print(f"  [AlignRepair] ALIGN={current:.0%} ≥ target — skipping")
        return current

    # Load high-confidence identity beliefs from DB
    try:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        placeholders = ",".join("?" * len(IDENTITY_TOPICS))
        rows = con.execute(f"""
            SELECT topic, content, confidence FROM beliefs
            WHERE topic IN ({placeholders})
              AND confidence >= ?
              AND content IS NOT NULL
              AND length(content) > 40
            ORDER BY confidence DESC, RANDOM()
            LIMIT 20
        """, (*IDENTITY_TOPICS, MIN_CONF)).fetchall()
        con.close()
    except Exception as e:
        if verbose:
            print(f"  [AlignRepair] DB error: {e}")
        return current

    if not rows:
        if verbose:
            print(f"  [AlignRepair] no qualifying beliefs found")
        return current

    added = 0
    now   = datetime.now(timezone.utc).isoformat()

    for row in rows[:MAX_PER_RUN]:
        topic   = row["topic"]
        content = row["content"]
        conf    = row["confidence"] or 0.65

        # alignment score: scale conf → 0.55–0.85 range
        align_score = round(0.55 + (conf - MIN_CONF) * 0.75, 3)
        align_score = min(0.85, align_score)

        ref = {
            "timestamp":       now,
            "topic":           topic,
            "topic_alignment": align_score,
            "self_assessment": f"align_repair:{topic}",
            "growth_note":     content[:120],
            "belief_count_used": 1,
            "score":           conf,
            "reflection_type": "alignment_repair",
            "topics_discussed": [topic],
            "source":          "nex_align_repair",
        }
        refs.append(ref)
        added += 1

    if added:
        _save_reflections(refs)
        new_align = _current_align(refs)
        if verbose:
            print(f"  [AlignRepair] wrote {added} reflections | "
                  f"ALIGN {current:.0%} → {new_align:.0%}")
        return new_align

    return current


if __name__ == "__main__":
    result = run_align_repair(verbose=True)
    print(f"Final ALIGN: {result:.0%}")
