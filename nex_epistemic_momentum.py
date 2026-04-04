#!/usr/bin/env python3
"""
nex_epistemic_momentum.py
Epistemic Momentum Engine.

Tracks the direction and velocity of belief confidence over time.
A belief has positive momentum if it is:
  - Frequently used (high use_count)
  - Recently active (last_used recent)
  - High strength relative to confidence (earning trust)
  - From a reliable source (nex_core, depth_engine > web crawl)

A belief has negative momentum if it is:
  - Never used (use_count = 0)
  - Stale (last_used long ago)
  - Low strength despite high confidence (inflated)

Momentum score: -1.0 (decaying) to +1.0 (accelerating)

Effect on generation:
  HIGH momentum (>= 0.5):  speak assertively, no hedging
  NEUTRAL (0.0 to 0.5):    speak with measured confidence
  LOW (< 0.0):             speak provisionally, acknowledge uncertainty

Runs nightly to update momentum scores.
Feeds into nex_traversal_compiler.py for expression style.
"""
import sqlite3, math, time, logging
from pathlib import Path
from datetime import datetime, timedelta

log     = logging.getLogger("nex.momentum")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

# Source trust weights
SOURCE_TRUST = {
    "nex_core":          1.0,
    "depth_engine":      0.9,
    "warmth_tension":    0.85,
    "nex_synthesis":     0.80,
    "depth_belief":      0.80,
    "nex_insight":       0.75,
    "self_directed":     0.70,
    "web":               0.40,
    "unknown":           0.50,
}

NOW = time.time()
DAY = 86400


def _source_trust(source: str) -> float:
    if not source:
        return SOURCE_TRUST["unknown"]
    for key, val in SOURCE_TRUST.items():
        if key in source.lower():
            return val
    return SOURCE_TRUST["unknown"]


def _recency_weight(last_used) -> float:
    """1.0 if used today, decays to 0.1 over 30 days."""
    if not last_used:
        return 0.1
    try:
        if isinstance(last_used, str):
            dt = datetime.fromisoformat(last_used)
            ts = dt.timestamp()
        else:
            ts = float(last_used)
        days_ago = (NOW - ts) / DAY
        return max(0.1, math.exp(-days_ago / 15))
    except Exception:
        return 0.1


def _use_weight(use_count) -> float:
    """Logarithmic use count weight. 0 uses = 0.0, 10 uses = 0.7, 50+ = 1.0"""
    if not use_count:
        return 0.0
    return min(1.0, math.log1p(use_count) / math.log1p(50))


def _age_weight(created_at) -> float:
    """Older beliefs with sustained use have earned their confidence."""
    if not created_at:
        return 0.5
    try:
        if isinstance(created_at, str):
            dt = datetime.fromisoformat(created_at)
            ts = dt.timestamp()
        else:
            ts = float(created_at)
        days_old = (NOW - ts) / DAY
        # Sweet spot: 7-90 days old. Too new = unproven. Too old = stale.
        if days_old < 1:
            return 0.3
        elif days_old < 7:
            return 0.6
        elif days_old < 90:
            return 1.0
        else:
            return max(0.4, 1.0 - (days_old - 90) / 365)
    except Exception:
        return 0.5


def compute_momentum(row: dict) -> float:
    """
    Compute momentum score for a single belief.
    Returns -1.0 (decaying) to +1.0 (accelerating).
    """
    conf      = row.get("confidence", 0.5) or 0.5
    use_count = row.get("use_count", 0) or 0
    last_used = row.get("last_used")
    created   = row.get("created_at")
    source    = row.get("source", "")
    strength  = row.get("strength", conf) or conf

    trust    = _source_trust(source)
    recency  = _recency_weight(last_used)
    use_w    = _use_weight(use_count)
    age_w    = _age_weight(created)

    # Strength vs confidence alignment
    # If strength > confidence: belief is earning trust = positive signal
    # If strength < confidence: belief may be inflated = negative signal
    strength_delta = (strength - conf) * 2  # -1 to +1

    # Combine signals
    positive = (
        trust    * 0.25 +
        recency  * 0.25 +
        use_w    * 0.30 +
        age_w    * 0.10 +
        max(0, strength_delta) * 0.10
    )

    negative = (
        (1.0 - recency) * 0.20 +
        (1.0 - use_w)   * 0.20 +
        max(0, -strength_delta) * 0.10
    )

    momentum = (positive - negative * 0.5)
    return round(max(-1.0, min(1.0, momentum)), 3)


def ensure_schema(db):
    """Add momentum column to beliefs if missing."""
    cols = [r[1] for r in db.execute(
        "PRAGMA table_info(beliefs)").fetchall()]
    if "momentum" not in cols:
        db.execute(
            "ALTER TABLE beliefs ADD COLUMN momentum REAL DEFAULT 0.0")
        db.commit()
        log.info("Added momentum column to beliefs")


def run_momentum_update(dry_run=False) -> dict:
    """Update momentum scores for all beliefs."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    ensure_schema(db)

    rows = db.execute("""SELECT id, confidence, source, use_count,
        last_used, created_at, strength
        FROM beliefs WHERE confidence >= 0.3""").fetchall()

    updated   = 0
    high_mom  = 0
    low_mom   = 0
    total_mom = 0.0

    for row in rows:
        m = compute_momentum(dict(row))
        total_mom += m
        if m >= 0.5: high_mom += 1
        if m < 0.0:  low_mom  += 1
        if not dry_run:
            db.execute(
                "UPDATE beliefs SET momentum=? WHERE id=?",
                (m, row["id"]))
        updated += 1

    if not dry_run:
        db.commit()
    db.close()

    avg_m = total_mom / max(updated, 1)
    result = {
        "updated":   updated,
        "high_momentum": high_mom,
        "low_momentum":  low_mom,
        "avg_momentum":  round(avg_m, 3),
        "dry_run":   dry_run,
    }
    print(f"Momentum update: {updated} beliefs")
    print(f"  High (>=0.5): {high_mom}  Low (<0.0): {low_mom}")
    print(f"  Average momentum: {avg_m:.3f}")
    return result


def get_momentum_label(momentum: float) -> str:
    """Return expression style label for compiler."""
    if momentum >= 0.6:   return "assertive"
    elif momentum >= 0.3: return "confident"
    elif momentum >= 0.0: return "measured"
    elif momentum >= -0.3: return "provisional"
    else:                  return "uncertain"


def get_belief_momentum(belief_id: int, db) -> float:
    """Get stored momentum for a belief ID."""
    try:
        row = db.execute(
            "SELECT momentum FROM beliefs WHERE id=?",
            (belief_id,)).fetchone()
        return row[0] if row and row[0] is not None else 0.0
    except Exception:
        return 0.0


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--top", type=int, default=10,
                        help="Show top N high-momentum beliefs")
    args = parser.parse_args()

    run_momentum_update(dry_run=args.dry_run)

    if not args.dry_run:
        db = sqlite3.connect(str(DB_PATH))
        print(f"\nTop {args.top} high-momentum beliefs:")
        rows = db.execute("""SELECT content, topic, momentum, confidence, use_count
            FROM beliefs WHERE momentum IS NOT NULL
            ORDER BY momentum DESC LIMIT ?""",
            (args.top,)).fetchall()
        for r in rows:
            label = get_momentum_label(r[2])
            print(f"  [{label}] m={r[2]:.3f} conf={r[3]:.2f} "
                  f"uses={r[4] or 0} [{r[1]}]")
            print(f"    {r[0][:80]}")
        db.close()
