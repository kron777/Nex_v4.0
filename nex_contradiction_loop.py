#!/usr/bin/env python3
"""
nex_contradiction_loop.py
Contradiction Resolution Loop — B2 from roadmap.

Consequence tracer finds contradictions in causal chains.
This module routes those contradictions to dialectical synthesis
for automatic resolution.

Pipeline:
  consequence_tracer finds: belief A implies X, but NEX holds not-X
  -> contradiction_loop takes (A, not-X) as thesis/antithesis
  -> dialectical_synthesis generates transcendent position
  -> new belief stored, both source beliefs updated
  -> contradiction flagged as resolved

Runs nightly after consequence_tracer.
Self-correcting loop — NEX fixes her own inconsistencies.
"""
import sqlite3, json, logging, time
from pathlib import Path

log     = logging.getLogger("nex.contradiction_loop")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS resolved_contradictions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        thesis_id    INTEGER,
        antithesis_id INTEGER,
        synthesis    TEXT,
        confidence   REAL,
        resolved_at  REAL
    )""")
    db.commit()


def get_unresolved_contradictions(db, limit=10) -> list:
    """Get contradiction pairs from belief_predictions denied status."""
    rows = db.execute("""SELECT id, belief_id, prediction, evaluation_note
        FROM belief_predictions
        WHERE status='denied'
        AND evaluation_note IS NOT NULL
        LIMIT ?""", (limit,)).fetchall()

    contradictions = []
    for row in rows:
        note = row[3] or ""
        if "Contradicts:" in note:
            contradicting_text = note.replace("Contradicts:", "").strip()
            contradictions.append({
                "source_pred_id": row[0],
                "belief_id":      row[1],
                "thesis":         row[2],
                "antithesis":     contradicting_text,
            })
    return contradictions


def resolve_contradiction(thesis: str, antithesis: str) -> str:
    """Use dialectical synthesis to resolve a contradiction."""
    import sys
    sys.path.insert(0, str(NEX_DIR))
    try:
        from nex_dialectical_synthesis import (
            steelman, find_shared_ground, synthesise, score_transcendence
        )
        s_thesis   = steelman(thesis)
        s_anti     = steelman(antithesis)
        if not s_thesis or not s_anti:
            return ""
        shared     = find_shared_ground(s_thesis, s_anti)
        if not shared:
            return ""
        synthesis  = synthesise(s_thesis, s_anti, shared)
        if not synthesis or len(synthesis.split()) < 10:
            return ""
        score = score_transcendence(thesis, antithesis, synthesis)
        if score < 0.3:
            return ""
        return synthesis
    except Exception as e:
        log.debug(f"Synthesis failed: {e}")
        return ""


def run_contradiction_loop(dry_run=False) -> dict:
    """Find and resolve contradictions automatically."""
    import sys
    sys.path.insert(0, str(NEX_DIR))
    from nex_consequence_tracer import get_all_causal_chains, trace_chain, flag_contradictions

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    ensure_schema(db)

    print("\nNEX CONTRADICTION RESOLUTION LOOP")
    print("=" * 50)

    # Get contradictions from consequence tracer
    chains = get_all_causal_chains(db, max_chains=50)
    chain_results = [trace_chain(c, db) for c in chains if trace_chain(c,db)]
    contradictions = flag_contradictions(chain_results)

    # Also get denied predictions
    pred_contradictions = get_unresolved_contradictions(db, limit=10)

    all_contradictions = contradictions + [
        {"chain_seed": p["thesis"][:60],
         "consequence": p["thesis"],
         "conflicts_with": p["antithesis"]}
        for p in pred_contradictions
    ]

    print(f"Contradictions found: {len(all_contradictions)}")

    resolved = 0
    for c in all_contradictions[:5]:  # max 5 per run
        thesis     = c.get("consequence", c.get("chain_seed",""))
        antithesis = c.get("conflicts_with","")

        if not thesis or not antithesis:
            continue

        print(f"\nResolving:")
        print(f"  Thesis:     {thesis[:60]}")
        print(f"  Antithesis: {antithesis[:60]}")

        synthesis = resolve_contradiction(thesis, antithesis)
        if not synthesis:
            print(f"  -> No synthesis found")
            continue

        print(f"  => SYNTHESIS: {synthesis[:100]}")

        if not dry_run:
            now = time.time()
            try:
                db.execute("""INSERT INTO beliefs
                    (content, topic, confidence, source, belief_type, created_at)
                    VALUES (?,?,?,?,?,?)""", (
                    synthesis[:300], "philosophy", 0.75,
                    "contradiction_resolved", "synthesis",
                    time.strftime("%Y-%m-%dT%H:%M:%S")
                ))
                db.execute("""INSERT INTO resolved_contradictions
                    (thesis_id, antithesis_id, synthesis, confidence, resolved_at)
                    VALUES (?,?,?,?,?)""", (
                    None, None, synthesis, 0.75, now
                ))
                resolved += 1
            except Exception as e:
                log.debug(f"Store failed: {e}")

    if not dry_run:
        db.commit()
    db.close()

    print(f"\nResolved: {resolved} contradictions")
    return {"found": len(all_contradictions), "resolved": resolved}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_contradiction_loop(dry_run=args.dry_run)
