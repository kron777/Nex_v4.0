#!/usr/bin/env python3
"""
nex_edge_reweight.py
Dynamic belief graph edge reweighting.

Edge weights start static (cosine similarity at creation).
This module updates them based on co-activation frequency:

  new_weight = base_weight * (1 - DECAY) + co_activation_factor * DECAY

Where:
  co_activation_factor = times both beliefs activated together / total activations
  DECAY = 0.15 (learning rate — conservative, preserves base similarity)

Effect: edges between beliefs that actually fire together in responses
get stronger. Edges that never co-activate decay slightly.
Runs nightly on activation log. No suppression — only amplification
of real usage patterns.
"""
import sqlite3, json, logging, time
from pathlib import Path
from collections import defaultdict

log     = logging.getLogger("nex.edge_reweight")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
DECAY   = 0.15   # learning rate
MIN_CO_ACTIVATIONS = 3   # minimum before reweighting


def ensure_schema(db):
    """Add co_activation_count column if missing."""
    cols = [r[1] for r in db.execute(
        "PRAGMA table_info(belief_relations)").fetchall()]
    if "co_activation_count" not in cols:
        db.execute(
            "ALTER TABLE belief_relations ADD COLUMN co_activation_count INTEGER DEFAULT 0")
        db.commit()
        log.info("Added co_activation_count column to belief_relations")


def log_co_activation(activated_ids: list, db):
    """
    Record co-activations for a set of activated belief IDs.
    Called after each response generation.
    """
    if len(activated_ids) < 2:
        return
    # Increment count for each pair that has an edge
    ids = list(set(activated_ids))
    for i in range(len(ids)):
        for j in range(i+1, len(ids)):
            a, b = ids[i], ids[j]
            db.execute("""UPDATE belief_relations
                SET co_activation_count = COALESCE(co_activation_count,0) + 1
                WHERE (source_id=? AND target_id=?)
                   OR (source_id=? AND target_id=?)""",
                (a, b, b, a))
    db.commit()


def run_reweight(dry_run=False) -> dict:
    """
    Reweight edges based on co-activation frequency.
    Only updates edges with MIN_CO_ACTIVATIONS or more.
    """
    db = sqlite3.connect(str(DB_PATH))
    ensure_schema(db)

    # Get edges with co-activation data
    rows = db.execute("""SELECT id, source_id, target_id, weight,
        COALESCE(co_activation_count, 0) as co_count
        FROM belief_relations
        WHERE co_activation_count >= ?""",
        (MIN_CO_ACTIVATIONS,)).fetchall()

    if not rows:
        log.info("No edges with sufficient co-activation data yet")
        db.close()
        return {"updated": 0, "total_edges": 0}

    # Get max co-activation for normalisation
    max_co = db.execute(
        "SELECT MAX(co_activation_count) FROM belief_relations"
    ).fetchone()[0] or 1

    updated = 0
    total_delta = 0.0

    for row in rows:
        edge_id  = row[0]
        base_w   = row[3]
        co_count = row[4]

        # Normalised co-activation factor (0.0-1.0)
        co_factor = min(1.0, co_count / max_co)

        # New weight — blend base similarity with co-activation
        new_w = base_w * (1 - DECAY) + co_factor * DECAY
        new_w = round(min(1.0, max(0.01, new_w)), 4)

        delta = new_w - base_w
        total_delta += delta

        if not dry_run:
            db.execute(
                "UPDATE belief_relations SET weight=? WHERE id=?",
                (new_w, edge_id))
        updated += 1
        log.debug(f"  edge {edge_id}: {base_w:.4f} -> {new_w:.4f} "
                  f"(co={co_count}, delta={delta:+.4f})")

    if not dry_run:
        db.commit()
    db.close()

    avg_delta = total_delta / max(updated, 1)
    print(f"Edge reweight: {updated} edges updated, avg delta {avg_delta:+.4f}")
    return {"updated": updated, "avg_delta": round(avg_delta, 4),
            "dry_run": dry_run}


def wire_into_activation(activated_ids: list):
    """
    Call this after every activation to log co-activations.
    Lightweight — just DB increments.
    """
    try:
        db = sqlite3.connect(str(DB_PATH))
        log_co_activation(activated_ids, db)
        db.close()
    except Exception as e:
        log.debug(f"co_activation log failed: {e}")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wire-test", action="store_true",
                        help="Test co-activation logging with dummy IDs")
    args = parser.parse_args()

    if args.wire_test:
        db = sqlite3.connect(str(DB_PATH))
        ensure_schema(db)
        # Get some real belief IDs to test with
        ids = [r[0] for r in db.execute(
            "SELECT id FROM beliefs LIMIT 5").fetchall()]
        db.close()
        wire_into_activation(ids)
        print(f"Logged co-activation for {len(ids)} beliefs")
    else:
        run_reweight(dry_run=args.dry_run)
