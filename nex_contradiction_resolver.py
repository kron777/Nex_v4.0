#!/usr/bin/env python3
"""
nex_contradiction_resolver.py — Graph-Native Contradiction Resolution
======================================================================
Place at: ~/Desktop/nex/nex_contradiction_resolver.py

Contradictions in the belief graph are not errors.
They are epistemic tension — two things NEX believes that cannot both be true.

Resolution doctrine:
  - Do NOT delete beliefs — they represent real knowledge states
  - DO decay the lower-confidence belief toward uncertainty
  - DO store the tension as a CONTRADICTS edge (already done by graph builder)
  - DO update self_model if a core domain has high contradiction density

Resolution algorithm:
  1. Find belief pairs with CONTRADICTS edges in belief_relations
  2. For each pair: compare confidence scores
  3. Apply decay to the weaker belief:
     new_conf = weaker_conf * DECAY_RATE (default 0.85)
  4. If weaker_conf already < MIN_CONF: archive it (confidence → 0.1)
  5. Log resolution to contra_resolved table

This runs:
  - On scheduler (every 6h)
  - After each saturation run
  - Via CLI: python3 nex_contradiction_resolver.py

Usage:
  python3 nex_contradiction_resolver.py           # resolve all
  python3 nex_contradiction_resolver.py --dry-run # show without applying
  python3 nex_contradiction_resolver.py --topic consciousness
"""

import sqlite3
import time
import argparse
import sys
from pathlib import Path

CFG_PATH = Path("~/.config/nex").expanduser()
DB_PATH  = CFG_PATH / "nex.db"

DECAY_RATE   = 0.88   # weaker belief confidence * this on each resolution
MIN_CONF     = 0.25   # below this → archive (set to 0.1, stop surfacing)
ARCHIVE_CONF = 0.10   # archived belief confidence


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def resolve_contradictions(
    topic_filter: str = None,
    dry_run: bool = False,
    limit: int = 500,
    verbose: bool = True,
) -> dict:
    """
    Find all CONTRADICTS edges in belief_relations and resolve them
    by decaying the lower-confidence belief.

    Returns summary dict.
    """
    conn = _db()
    now  = time.time()

    # Get all CONTRADICTS edges
    query = """
        SELECT br.belief_a_id, br.belief_b_id, br.weight,
               ba.content as content_a, ba.confidence as conf_a,
               ba.topic as topic_a, ba.locked as locked_a,
               bb.content as content_b, bb.confidence as conf_b,
               bb.topic as topic_b, bb.locked as locked_b
        FROM belief_relations br
        JOIN beliefs ba ON ba.id = br.belief_a_id
        JOIN beliefs bb ON bb.id = br.belief_b_id
        WHERE br.relation_type = 'CONTRADICTS'
        AND ba.confidence IS NOT NULL
        AND bb.confidence IS NOT NULL
    """
    if topic_filter:
        query += f" AND (lower(ba.topic) = '{topic_filter.lower()}' OR lower(bb.topic) = '{topic_filter.lower()}')"

    query += f" ORDER BY br.weight DESC LIMIT {limit}"

    rows = conn.execute(query).fetchall()

    if verbose:
        print(f"\n  Contradiction Resolver")
        print(f"  {'─'*50}")
        print(f"  CONTRADICTS edges found: {len(rows)}")
        if dry_run:
            print(f"  Mode: DRY RUN — no changes applied")

    resolved   = 0
    archived   = 0
    skipped    = 0
    unchanged  = 0

    for row in rows:
        conf_a = float(row["conf_a"] or 0.5)
        conf_b = float(row["conf_b"] or 0.5)

        # Skip if one is locked (pinned)
        if row["locked_a"] or row["locked_b"]:
            skipped += 1
            continue

        # Skip if confidences are equal — genuine uncertainty, leave as-is
        if abs(conf_a - conf_b) < 0.05:
            unchanged += 1
            continue

        # Identify weaker and stronger
        if conf_a <= conf_b:
            weaker_id   = row["belief_a_id"]
            weaker_conf = conf_a
            weaker_content = (row["content_a"] or "")[:80]
            stronger_conf  = conf_b
        else:
            weaker_id   = row["belief_b_id"]
            weaker_conf = conf_b
            weaker_content = (row["content_b"] or "")[:80]
            stronger_conf  = conf_a

        # Compute new confidence
        if weaker_conf < MIN_CONF:
            new_conf = ARCHIVE_CONF
            action   = "archive"
            archived += 1
        else:
            new_conf = round(weaker_conf * DECAY_RATE, 4)
            action   = "decay"
            resolved += 1

        if verbose and resolved + archived <= 10:
            print(f"\n  [{action}] {weaker_content[:70]}")
            print(f"    conf: {weaker_conf:.3f} → {new_conf:.3f}  "
                  f"(stronger: {stronger_conf:.3f})")

        if not dry_run:
            conn.execute(
                "UPDATE beliefs SET confidence=? WHERE id=?",
                (new_conf, weaker_id)
            )

            # Log to contra_resolved
            try:
                conn.execute("""
                    INSERT INTO contra_resolved
                    (belief_a_id, belief_b_id, resolution, resolved_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    row["belief_a_id"],
                    row["belief_b_id"],
                    f"graph_resolver/{action}",
                    now,
                ))
            except Exception:
                pass

    if not dry_run:
        conn.commit()

    conn.close()

    summary = {
        "edges_found": len(rows),
        "resolved":    resolved,
        "archived":    archived,
        "skipped":     skipped,
        "unchanged":   unchanged,
    }

    if verbose:
        print(f"\n  Results:")
        print(f"    Decayed:   {resolved}")
        print(f"    Archived:  {archived}")
        print(f"    Unchanged (equal conf): {unchanged}")
        print(f"    Skipped (locked): {skipped}")

    return summary


def contradiction_density_report() -> list:
    """
    Show which topics have the most unresolved contradictions.
    Useful for identifying where the graph is most uncertain.
    """
    conn = _db()
    rows = conn.execute("""
        SELECT ba.topic, COUNT(*) as c,
               AVG(ABS(ba.confidence - bb.confidence)) as conf_spread
        FROM belief_relations br
        JOIN beliefs ba ON ba.id = br.belief_a_id
        JOIN beliefs bb ON bb.id = br.belief_b_id
        WHERE br.relation_type = 'CONTRADICTS'
        AND ba.topic IS NOT NULL
        GROUP BY ba.topic
        ORDER BY c DESC LIMIT 15
    """).fetchall()
    conn.close()

    report = []
    for row in rows:
        report.append({
            "topic":       row["topic"],
            "count":       row["c"],
            "conf_spread": round(float(row["conf_spread"] or 0), 4),
        })
    return report


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--topic",   type=str, default=None)
    parser.add_argument("--report",  action="store_true")
    parser.add_argument("--limit",   type=int, default=500)
    args = parser.parse_args()

    if args.report:
        report = contradiction_density_report()
        print(f"\n  Contradiction density by topic:")
        print(f"  {'─'*45}")
        for r in report:
            print(f"  {r['topic']:<30} {r['count']:4d} contradictions  "
                  f"spread={r['conf_spread']:.3f}")
        sys.exit(0)

    resolve_contradictions(
        topic_filter=args.topic,
        dry_run=args.dry_run,
        limit=args.limit,
        verbose=True,
    )
