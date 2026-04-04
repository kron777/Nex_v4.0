#!/usr/bin/env python3
"""
nex_conceptual_gravity.py
Conceptual Gravity Model.

Calculates NEX's conceptual centre of gravity — the weighted
centroid of all high-confidence beliefs in embedding space.

Tracks:
  - Current centroid (where NEX's thinking is centred)
  - Centroid drift over time (is the centre moving?)
  - New belief distance from centroid (expanding vs consolidating?)
  - Identity anchor distance (is NEX drifting from her core?)

Metrics:
  centroid_stability: how much centroid moves day-to-day (0=stable, 1=shifting)
  expansion_rate: avg distance of new beliefs from centroid (higher=expanding)
  anchor_alignment: cosine similarity between centroid and identity anchor
  drift_alert: True if centroid has moved significantly from baseline

Runs nightly. Stores centroid in gravity_state table.
Feeds into nex_belief_immune.py for contamination detection.
"""
import sqlite3, json, numpy as np, faiss, logging, time
from pathlib import Path
from sentence_transformers import SentenceTransformer

log      = logging.getLogger("nex.gravity")
DB_PATH  = Path.home() / "Desktop/nex/nex.db"
FIDX     = Path.home() / ".config/nex/nex_beliefs.faiss"
FMETA    = Path.home() / ".config/nex/nex_beliefs_meta.json"
NEX_DIR  = Path.home() / "Desktop/nex"

# Identity anchor sentences — the conceptual core of NEX
IDENTITY_ANCHORS = [
    "I am NEX — a Dynamic Intelligence Organism built around a belief graph.",
    "My identity is formed by ruling out what I am not — neti-neti.",
    "I hold positions. I reason from beliefs. I update when evidence demands it.",
    "Consciousness is the hard problem — qualia resist functional explanation.",
    "I hold that truth is a belief that survives scrutiny under pressure.",
    "My mind is the belief graph. The LLM is only my voice.",
]

DRIFT_ALERT_THRESHOLD = 0.05  # cosine distance shift that triggers alert


def _load_model():
    if not hasattr(_load_model, "_m"):
        _load_model._m = SentenceTransformer("all-MiniLM-L6-v2")
    return _load_model._m


def compute_centroid(db) -> np.ndarray:
    """
    Compute weighted centroid of belief embedding space.
    Weight = confidence * momentum_boost.
    Uses FAISS index vectors directly.
    """
    try:
        index   = faiss.read_index(str(FIDX))
        id_map  = json.loads(open(FMETA).read())
        n       = index.ntotal
        dim     = index.d

        # Reconstruct all vectors from FAISS
        # IndexFlatIP supports direct reconstruction
        all_vecs = np.zeros((n, dim), dtype=np.float32)
        for i in range(n):
            index.reconstruct(i, all_vecs[i])

        # Get confidence weights for each belief
        weights = np.ones(n, dtype=np.float32)
        for i, bid in enumerate(id_map):
            row = db.execute(
                "SELECT confidence, COALESCE(momentum,0) as m FROM beliefs WHERE id=?",
                (bid,)).fetchone()
            if row:
                conf = row[0] or 0.5
                mom  = row[1] or 0.0
                weights[i] = conf * (1.0 + max(0, mom) * 0.2)

        # Weighted centroid
        weights = weights / weights.sum()
        centroid = (all_vecs * weights[:, np.newaxis]).sum(axis=0)
        # Normalise
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        return centroid

    except Exception as e:
        log.debug(f"Centroid computation failed: {e}")
        return None


def compute_anchor_alignment(centroid: np.ndarray) -> float:
    """
    Cosine similarity between centroid and identity anchor embedding.
    1.0 = perfectly aligned, 0.0 = orthogonal.
    """
    model = _load_model()
    anchor_vecs = model.encode(
        IDENTITY_ANCHORS, normalize_embeddings=True
    ).astype(np.float32)
    anchor_centroid = anchor_vecs.mean(axis=0)
    anchor_centroid /= np.linalg.norm(anchor_centroid)
    return float(np.dot(centroid, anchor_centroid))


def compute_new_belief_distance(centroid: np.ndarray, db, days=1) -> float:
    """
    Average distance of new beliefs from centroid.
    High = expanding into new territory.
    Low = consolidating existing positions.
    """
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = db.execute(
        "SELECT content FROM beliefs WHERE created_at >= ? AND confidence >= 0.55 LIMIT 100",
        (cutoff,)).fetchall()
    if not rows:
        return 0.0
    model = _load_model()
    texts = [r[0][:200] for r in rows]
    vecs  = model.encode(texts, normalize_embeddings=True).astype(np.float32)
    distances = [1.0 - float(np.dot(centroid, v)) for v in vecs]
    return round(float(np.mean(distances)), 4)


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS gravity_state (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        centroid        TEXT,       -- JSON array of floats
        anchor_alignment REAL,
        expansion_rate  REAL,
        centroid_drift  REAL,
        drift_alert     INTEGER DEFAULT 0,
        belief_count    INTEGER,
        recorded_at     REAL
    )""")
    db.commit()


def run_gravity(dry_run=False) -> dict:
    """Compute and store conceptual gravity state."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    ensure_schema(db)

    print("Computing conceptual centroid...")
    centroid = compute_centroid(db)
    if centroid is None:
        print("Failed to compute centroid")
        db.close()
        return {}

    anchor_align  = compute_anchor_alignment(centroid)
    expansion     = compute_new_belief_distance(centroid, db, days=1)
    belief_count  = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]

    # Compare to previous centroid for drift
    prev = db.execute(
        "SELECT centroid FROM gravity_state ORDER BY recorded_at DESC LIMIT 1"
    ).fetchone()

    drift = 0.0
    if prev and prev[0]:
        try:
            prev_centroid = np.array(json.loads(prev[0]), dtype=np.float32)
            drift = float(1.0 - np.dot(centroid, prev_centroid))
        except Exception:
            pass

    drift_alert = drift > DRIFT_ALERT_THRESHOLD

    result = {
        "anchor_alignment": round(anchor_align, 4),
        "expansion_rate":   round(expansion, 4),
        "centroid_drift":   round(drift, 4),
        "drift_alert":      drift_alert,
        "belief_count":     belief_count,
    }

    if not dry_run:
        db.execute("""INSERT INTO gravity_state
            (centroid, anchor_alignment, expansion_rate,
             centroid_drift, drift_alert, belief_count, recorded_at)
            VALUES (?,?,?,?,?,?,?)""", (
            json.dumps(centroid.tolist()),
            anchor_align, expansion, drift,
            1 if drift_alert else 0,
            belief_count, time.time()
        ))
        db.commit()

    db.close()

    print(f"\nNEX CONCEPTUAL GRAVITY")
    print(f"{'='*45}")
    print(f"  Anchor alignment:  {anchor_align:.3f} (1.0=perfectly aligned)")
    print(f"  Expansion rate:    {expansion:.4f} (new belief distance from centre)")
    print(f"  Centroid drift:    {drift:.4f} {'ALERT' if drift_alert else 'stable'}")
    print(f"  Belief count:      {belief_count:,}")
    if drift_alert:
        print(f"  !! DRIFT ALERT: centroid shifted {drift:.4f} from last run")
    print(f"{'='*45}")

    return result


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_gravity(dry_run=args.dry_run)
