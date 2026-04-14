#!/usr/bin/env python3
"""
nex_warmth_propagation.py
Warmth Propagation Engine.

Concepts inherit contextual warmth from connected words.
Reduces need to explicitly warm every token in the queue.

Formula:
  propagated_warmth = base_warmth + LAMBDA * sum(neighbor_warmth * edge_weight)

Where:
  - neighbors = words in association_vector + pull_toward
  - edge_weight = association weight (0.0-1.0)
  - LAMBDA = 0.15 (propagation strength — conservative)
  - propagated warmth capped at base_warmth + 0.25 (no runaway inflation)

Run after warming cron to propagate warmth through vocabulary graph.
"""
import sqlite3, json, logging, time, sys
from pathlib import Path

log     = logging.getLogger("nex.propagation")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"

LAMBDA       = 0.15   # propagation strength
MAX_BOOST    = 0.25   # max warmth gain from propagation
MIN_SOURCE_W = 0.45   # only propagate from warm+ words


def run_propagation(dry_run=False) -> dict:
    """
    Propagate warmth through vocabulary graph.
    Returns stats dict.
    """
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # Load all word tags
    rows = db.execute(
        "SELECT word, w, association_vector, pull_toward FROM word_tags"
    ).fetchall()

    word_warmth = {r["word"]: r["w"] for r in rows}

    updated = 0
    skipped = 0
    total_boost = 0.0

    for row in rows:
        word    = row["word"]
        base_w  = row["w"]

        # Parse neighbors from association_vector
        neighbors = []
        try:
            assoc = json.loads(row["association_vector"] or "[]")
            for item in assoc:
                if isinstance(item, dict):
                    w = item.get("word","")
                    weight = float(item.get("weight", 0.5))
                    if w:
                        neighbors.append((w, weight))
        except Exception:
            pass

        # Also include pull_toward words (full weight)
        try:
            pulls = json.loads(row["pull_toward"] or "[]")
            for p in pulls:
                if isinstance(p, str) and p:
                    neighbors.append((p, 0.8))
        except Exception:
            pass

        if not neighbors:
            skipped += 1
            continue

        # Compute propagated component
        prop = 0.0
        for nbr_word, edge_weight in neighbors:
            nbr_w = word_warmth.get(nbr_word, 0.0)
            if nbr_w >= MIN_SOURCE_W:
                prop += nbr_w * edge_weight

        if prop == 0.0:
            skipped += 1
            continue

        boost = min(MAX_BOOST, LAMBDA * prop)
        new_w = min(1.0, base_w + boost)

        if new_w <= base_w + 0.001:
            skipped += 1
            continue

        if not dry_run:
            db.execute(
                "UPDATE word_tags SET w=? WHERE word=?",
                (round(new_w, 4), word)
            )
        total_boost += (new_w - base_w)
        updated += 1
        log.debug(f"  {word}: {base_w:.3f} -> {new_w:.3f} (+{new_w-base_w:.3f})")

    if not dry_run:
        db.commit()
    db.close()

    avg_boost = total_boost / max(updated, 1)
    result = {
        "updated": updated,
        "skipped": skipped,
        "avg_boost": round(avg_boost, 4),
        "total_boost": round(total_boost, 3),
        "dry_run": dry_run
    }
    print(f"Propagation complete: {updated} words boosted, avg +{avg_boost:.4f}")
    return result


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if args.debug:
        logging.getLogger("nex.propagation").setLevel(logging.DEBUG)
    run_propagation(dry_run=args.dry_run)
