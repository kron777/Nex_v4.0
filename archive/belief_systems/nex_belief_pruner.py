#!/usr/bin/env python3
"""
nex_belief_pruner.py — Safe Belief Pruning
===========================================
Removes beliefs the decay system has already marked as stale AND
that score below the quality floor. Two-gate system — both gates
must pass before a belief is deleted. Locked/pinned beliefs are
never touched regardless of score.

Gates:
  Gate 1 — decay_score >= DECAY_THRESHOLD (default 0.5)
  Gate 2 — quality_score < QUALITY_CEILING (default 0.38)

Optional third gate:
  Gate 3 — use_count = 0 (never queried)  [on by default]

Protections:
  - Never deletes locked or pinned beliefs (schema-safe check)
  - Never deletes beliefs with source in PROTECTED_SOURCES
  - Never deletes more than MAX_PRUNE_PCT of the corpus in one run
  - Dry-run by default — pass --run to actually delete
  - Writes a prune log to ~/.config/nex/prune_log.json

Run:
  python3 nex_belief_pruner.py           # dry run, shows what would be pruned
  python3 nex_belief_pruner.py --run     # actually prune
  python3 nex_belief_pruner.py --run --decay 0.8  # only near-dead beliefs
"""

import sqlite3, json, sys, time
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"
LOG_PATH  = Path("~/.config/nex/prune_log.json").expanduser()

# ── Tunables ──────────────────────────────────────────────────────────────────
DECAY_THRESHOLD  = 0.5    # decay_score >= this to be a candidate
QUALITY_CEILING  = 0.38   # quality_score < this to be a candidate
REQUIRE_ZERO_USE = True   # also require use_count = 0
MAX_PRUNE_PCT    = 0.45   # never delete more than 45% of corpus in one run

# Sources that are never pruned regardless of score
PROTECTED_SOURCES = {
    "human", "synthesis", "nex_self", "manual",
    "self_research",          # NEX's own research — academic quality content
    "arxiv", "pubmed",        # high-authority external sources
    # scheduler_saturation is NOT protected — fresh beliefs with rc=0, use=0
    # score 0.37 and drag the corpus average down. Pruner removes the weakest.
}

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

def _schema_has_column(conn, table, column):
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == column for r in rows)
    except Exception:
        return False

def _parse_args():
    args  = sys.argv[1:]
    dry   = "--run" not in args
    decay = DECAY_THRESHOLD
    qual  = QUALITY_CEILING
    for i, a in enumerate(args):
        if a == "--decay" and i+1 < len(args):
            decay = float(args[i+1])
        if a == "--quality" and i+1 < len(args):
            qual = float(args[i+1])
    return dry, decay, qual


def prune(dry_run=True, decay_threshold=DECAY_THRESHOLD,
          quality_ceiling=QUALITY_CEILING) -> dict:
    conn  = _db()
    total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    max_delete = int(total * MAX_PRUNE_PCT)

    has_locked  = _schema_has_column(conn, "beliefs", "locked")
    has_pinned  = _schema_has_column(conn, "beliefs", "pinned")
    has_use     = _schema_has_column(conn, "beliefs", "use_count")
    has_quality = _schema_has_column(conn, "beliefs", "quality_score")

    if not has_quality:
        conn.close()
        return {"pruned": 0, "error": "quality_score column missing — run nex_belief_refiner.py first"}

    # Build candidate query
    lock_clause = "AND (locked IS NULL OR locked = 0)" if has_locked else ""
    pin_clause  = "AND (pinned IS NULL OR pinned = 0)" if has_pinned else ""
    use_clause  = "AND (use_count IS NULL OR use_count = 0)" if (has_use and REQUIRE_ZERO_USE) else ""

    candidates = conn.execute(f"""
        SELECT id, content, topic, source, confidence,
               decay_score, quality_score
        FROM beliefs
        WHERE decay_score >= ?
          AND quality_score < ?
          {lock_clause}
          {pin_clause}
          {use_clause}
        ORDER BY quality_score ASC, decay_score DESC
        LIMIT ?
    """, (decay_threshold, quality_ceiling, max_delete * 2)).fetchall()

    # Apply source protection
    to_prune = []
    protected = []
    for row in candidates:
        src = (row["source"] or "").lower()
        is_protected = any(p in src for p in PROTECTED_SOURCES)
        if is_protected:
            protected.append(dict(row))
        else:
            to_prune.append(dict(row))

    # Enforce max prune cap
    if len(to_prune) > max_delete:
        print(f"  [pruner] Cap enforced: {len(to_prune)} candidates → {max_delete} max")
        to_prune = to_prune[:max_delete]

    # Summary by source
    by_source = defaultdict(list)
    for b in to_prune:
        by_source[b["source"] or "unknown"].append(b["quality_score"])

    print(f"\n{'DRY RUN — ' if dry_run else ''}Belief Pruner")
    print(f"{'='*50}")
    print(f"Total corpus:       {total}")
    print(f"Candidates found:   {len(candidates)}")
    print(f"Protected (kept):   {len(protected)}")
    print(f"To prune:           {len(to_prune)} ({len(to_prune)/total*100:.1f}%)")
    print(f"Max allowed:        {max_delete} ({MAX_PRUNE_PCT*100:.0f}%)")
    print(f"\nBy source (top 15):")
    for src, scores in sorted(by_source.items(), key=lambda x: -len(x[1]))[:15]:
        avg = sum(scores)/len(scores)
        print(f"  {len(scores):5d}  avg={avg:.3f}  {src[:60]}")

    # Simulate post-prune average
    remaining = total - len(to_prune)
    pruned_score_sum = sum(b["quality_score"] for b in to_prune)
    total_score_sum  = conn.execute(
        "SELECT SUM(quality_score) FROM beliefs WHERE quality_score IS NOT NULL"
    ).fetchone()[0] or 0
    projected_avg = (total_score_sum - pruned_score_sum) / max(remaining, 1)
    print(f"\nProjected corpus after prune:")
    print(f"  Beliefs remaining: {remaining}")
    print(f"  Projected avg quality: {projected_avg:.3f}")

    if not dry_run:
        ids = [b["id"] for b in to_prune]
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM beliefs WHERE id IN ({placeholders})", ids)
        conn.commit()
        print(f"\n  ✓ Pruned {len(to_prune)} beliefs from corpus.")

        # Write prune log
        log_entry = {
            "timestamp":       _now_iso(),
            "pruned":          len(to_prune),
            "remaining":       remaining,
            "projected_avg":   round(projected_avg, 3),
            "decay_threshold": decay_threshold,
            "quality_ceiling": quality_ceiling,
            "by_source":       {k: len(v) for k, v in by_source.items()},
        }
        log = []
        if LOG_PATH.exists():
            try:
                log = json.loads(LOG_PATH.read_text())
            except Exception:
                pass
        log.append(log_entry)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text(json.dumps(log, indent=2))
    else:
        print(f"\n  Run with --run to execute.")

    conn.close()
    return {
        "dry_run":         dry_run,
        "pruned":          len(to_prune) if not dry_run else 0,
        "would_prune":     len(to_prune) if dry_run else 0,
        "remaining":       remaining,
        "projected_avg":   round(projected_avg, 3),
        "protected_kept":  len(protected),
    }


if __name__ == "__main__":
    dry_run, decay, quality = _parse_args()
    result = prune(dry_run=dry_run, decay_threshold=decay, quality_ceiling=quality)
    print(f"\nResult: {json.dumps(result, indent=2)}")
