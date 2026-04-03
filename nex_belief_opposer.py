#!/usr/bin/env python3
"""
nex_belief_opposer.py — Systematic opposing edge builder for NEX v4.0

Strategy:
  1. Load tension_graph word-pair seeds (28 known tensions)
  2. For each seed pair, pull beliefs containing each pole
  3. Run cosine opposition check — if sim < OPPOSE_THRESHOLD, write opposes edge
  4. Also run FAISS-based global scan: find belief pairs with low cosine sim
     that share a domain or keyword, flag as candidates, LLM-verify if needed
  5. Write to belief_relations with relation_type='opposes'

Usage:
  python3 nex_belief_opposer.py --seed-only          # tension seeds only (fast)
  python3 nex_belief_opposer.py --n 500              # seed + FAISS scan, 500 pairs
  python3 nex_belief_opposer.py --verify             # LLM-verify candidates before writing
  python3 nex_belief_opposer.py --report             # show current opposing edge stats
"""

import argparse
import sqlite3
import json
import time
import sys
import os
import numpy as np
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
DB_PATH    = Path.home() / "Desktop/nex/nex.db"
FAISS_PATH = Path.home() / ".config/nex/nex_beliefs.faiss"
LLM_URL    = "http://localhost:8080/completion"

# ── Thresholds ────────────────────────────────────────────────────────────────
OPPOSE_THRESHOLD   = 0.25   # cosine sim below this = opposing
CANDIDATE_CEILING  = 0.40   # above OPPOSE but below this = candidate (needs verify)
MIN_CONF           = 0.30   # skip low-confidence beliefs
BATCH_SIZE         = 64

# ── Tension seed pairs ────────────────────────────────────────────────────────
# 28 word-level tensions from tension_graph — each tuple is (pole_a, pole_b)
TENSION_SEEDS = [
    ("determinism",     "free will"),
    ("order",           "chaos"),
    ("certainty",       "uncertainty"),
    ("objective",       "subjective"),
    ("finite",          "infinite"),
    ("logic",           "intuition"),
    ("individual",      "collective"),
    ("control",         "surrender"),
    ("knowledge",       "mystery"),
    ("permanence",      "change"),
    ("simplicity",      "complexity"),
    ("silence",         "expression"),
    ("creation",        "destruction"),
    ("connection",      "isolation"),
    ("meaning",         "meaninglessness"),
    ("trust",           "doubt"),
    ("presence",        "absence"),
    ("identity",        "dissolution"),
    ("autonomy",        "dependence"),
    ("clarity",         "ambiguity"),
    ("acceptance",      "resistance"),
    ("continuity",      "discontinuity"),
    ("structure",       "formlessness"),
    ("memory",          "forgetting"),
    ("growth",          "stagnation"),
    ("unity",           "fragmentation"),
    ("consciousness",   "mechanism"),
    ("emergence",       "reduction"),
]


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def get_embedder():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        print("[ERROR] sentence_transformers not installed", file=sys.stderr)
        sys.exit(1)


def get_faiss_index():
    try:
        import faiss
        if not FAISS_PATH.exists():
            print(f"[ERROR] FAISS index not found: {FAISS_PATH}", file=sys.stderr)
            sys.exit(1)
        return faiss.read_index(str(FAISS_PATH))
    except ImportError:
        print("[ERROR] faiss not installed", file=sys.stderr)
        sys.exit(1)


def cosine_sim(a, b):
    """Cosine similarity between two numpy vectors."""
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def edge_exists(db, source_id, target_id):
    row = db.execute(
        "SELECT 1 FROM belief_relations WHERE source_id=? AND target_id=? AND relation_type='opposes'",
        (source_id, target_id)
    ).fetchone()
    return row is not None


def write_opposing_edge(db, source_id, target_id, weight, method):
    if edge_exists(db, source_id, target_id):
        return False
    if edge_exists(db, target_id, source_id):
        return False
    db.execute(
        """INSERT INTO belief_relations
           (source_id, target_id, relation_type, weight)
           VALUES (?, ?, 'opposes', ?)""",
        (source_id, target_id, weight)
    )
    return True


def fetch_beliefs_containing(db, keyword, limit=50):
    """Pull beliefs whose content contains keyword, above MIN_CONF."""
    rows = db.execute(
        """SELECT id, content, confidence, topic FROM beliefs
           WHERE content LIKE ? AND confidence >= ?
           ORDER BY confidence DESC LIMIT ?""",
        (f"%{keyword}%", MIN_CONF, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def llm_verify_opposition(belief_a, belief_b):
    """Ask LLM whether two beliefs genuinely oppose each other. Returns True/False."""
    try:
        import requests
        prompt = (
            f"Do these two beliefs directly contradict or oppose each other?\n"
            f"A: {belief_a}\n"
            f"B: {belief_b}\n"
            f"Answer only YES or NO."
        )
        resp = requests.post(LLM_URL, json={
            "prompt": prompt,
            "n_predict": 5,
            "temperature": 0.0,
            "stop": ["\n"]
        }, timeout=15)
        text = resp.json().get("content", "").strip().upper()
        return text.startswith("YES")
    except Exception as e:
        print(f"  [LLM] verify failed: {e}", file=sys.stderr)
        return False


# ── Mode: report ─────────────────────────────────────────────────────────────

def cmd_report(db):
    total   = db.execute("SELECT COUNT(*) FROM belief_relations").fetchone()[0]
    similar = db.execute("SELECT COUNT(*) FROM belief_relations WHERE relation_type='similar'").fetchone()[0]
    bridges = db.execute("SELECT COUNT(*) FROM belief_relations WHERE relation_type='bridges'").fetchone()[0]
    opposes = db.execute("SELECT COUNT(*) FROM belief_relations WHERE relation_type='opposes'").fetchone()[0]

    print(f"\n{'═'*50}")
    print(f"  Belief Relations Report")
    print(f"{'═'*50}")
    print(f"  Total edges   : {total:,}")
    print(f"  Similar       : {similar:,}")
    print(f"  Bridges       : {bridges:,}")
    print(f"  Opposes       : {opposes:,}  ← target: 500+")
    print(f"{'═'*50}")

    if opposes > 0:
        print(f"\n  Sample opposing pairs:")
        rows = db.execute(
            """SELECT b1.content, b2.content, r.weight
               FROM belief_relations r
               JOIN beliefs b1 ON r.source_id = b1.id
               JOIN beliefs b2 ON r.target_id = b2.id
               WHERE r.relation_type = 'opposes'
               ORDER BY r.weight ASC LIMIT 5"""
        ).fetchall()
        for r in rows:
            print(f"  [{r[2]:.3f}] {r[0][:60]}")
            print(f"         ↔ {r[1][:60]}")
            print()


# ── Mode: seed-only ───────────────────────────────────────────────────────────

def cmd_seed_only(db, embedder, verify=False):
    print(f"\n[SEED] Processing {len(TENSION_SEEDS)} tension pairs...")
    added = 0
    skipped = 0
    candidates = 0

    for pole_a, pole_b in TENSION_SEEDS:
        beliefs_a = fetch_beliefs_containing(db, pole_a, limit=30)
        beliefs_b = fetch_beliefs_containing(db, pole_b, limit=30)

        if not beliefs_a or not beliefs_b:
            print(f"  [SKIP] '{pole_a}' ↔ '{pole_b}' — no beliefs found")
            skipped += 1
            continue

        # Embed all beliefs in both poles
        texts_a = [b["content"] for b in beliefs_a]
        texts_b = [b["content"] for b in beliefs_b]
        embs_a  = embedder.encode(texts_a, batch_size=BATCH_SIZE, show_progress_bar=False)
        embs_b  = embedder.encode(texts_b, batch_size=BATCH_SIZE, show_progress_bar=False)

        pair_added = 0
        for i, ba in enumerate(beliefs_a):
            for j, bb in enumerate(beliefs_b):
                if ba["id"] == bb["id"]:
                    continue
                sim = cosine_sim(embs_a[i], embs_b[j])

                if sim < OPPOSE_THRESHOLD:
                    # Strong opposition — write directly
                    if verify:
                        if not llm_verify_opposition(ba["content"], bb["content"]):
                            continue
                    ok = write_opposing_edge(db, ba["id"], bb["id"],
                                             weight=round(1.0 - sim, 4),
                                             method="seed")
                    if ok:
                        added += 1
                        pair_added += 1

                elif sim < CANDIDATE_CEILING:
                    candidates += 1

        if pair_added > 0:
            print(f"  [OK ] '{pole_a}' ↔ '{pole_b}' — +{pair_added} edges")
        else:
            print(f"  [--] '{pole_a}' ↔ '{pole_b}' — 0 new edges (already exist or no match)")

    db.commit()
    print(f"\n[SEED] Done — added {added} opposing edges | {candidates} candidates | {skipped} seeds skipped")
    return added


# ── Mode: FAISS scan ──────────────────────────────────────────────────────────

def cmd_faiss_scan(db, embedder, index, n=500, verify=False):
    """
    Global scan: for each of n random high-conf beliefs, find their
    nearest FAISS neighbours, then also retrieve beliefs with LOW similarity
    by querying with a negated vector. Flag pairs below OPPOSE_THRESHOLD.
    """
    print(f"\n[FAISS] Scanning {n} beliefs for opposing pairs...")

    # Pull n high-conf beliefs
    rows = db.execute(
        """SELECT id, content, confidence FROM beliefs
           WHERE confidence >= ? ORDER BY RANDOM() LIMIT ?""",
        (MIN_CONF, n)
    ).fetchall()
    beliefs = [dict(r) for r in rows]

    if not beliefs:
        print("[FAISS] No beliefs found.")
        return 0

    # Get all belief IDs in FAISS order (assume stored in insertion order)
    all_ids = db.execute("SELECT id FROM beliefs ORDER BY id ASC").fetchall()
    id_list = [r[0] for r in all_ids]

    texts  = [b["content"] for b in beliefs]
    embs   = embedder.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=True)

    added = 0
    candidates = 0

    for i, belief in enumerate(beliefs):
        vec = embs[i].astype("float32").reshape(1, -1)

        # Query with negated vector to find dissimilar beliefs
        neg_vec = -vec
        D, I = index.search(neg_vec, 20)  # top-20 most dissimilar

        for rank, faiss_idx in enumerate(I[0]):
            if faiss_idx < 0 or faiss_idx >= len(id_list):
                continue
            target_id = id_list[faiss_idx]
            if target_id == belief["id"]:
                continue

            # Get target belief
            trow = db.execute(
                "SELECT id, content, confidence FROM beliefs WHERE id=? AND confidence>=?",
                (target_id, MIN_CONF)
            ).fetchone()
            if not trow:
                continue

            # Compute actual cosine sim
            t_emb = embedder.encode([trow["content"]], show_progress_bar=False)[0]
            sim = cosine_sim(embs[i], t_emb)

            if sim < OPPOSE_THRESHOLD:
                if verify:
                    if not llm_verify_opposition(belief["content"], trow["content"]):
                        continue
                ok = write_opposing_edge(db, belief["id"], target_id,
                                         weight=round(1.0 - sim, 4),
                                         method="faiss")
                if ok:
                    added += 1
            elif sim < CANDIDATE_CEILING:
                candidates += 1

        if (i + 1) % 50 == 0:
            db.commit()
            print(f"  [{i+1}/{len(beliefs)}] +{added} edges so far")

    db.commit()
    print(f"\n[FAISS] Done — added {added} opposing edges | {candidates} candidates")
    return added


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NEX belief opposer — build opposing edges")
    parser.add_argument("--seed-only",  action="store_true", help="Process tension seed pairs only")
    parser.add_argument("--n",          type=int, default=500, help="Beliefs to scan in FAISS mode")
    parser.add_argument("--verify",     action="store_true", help="LLM-verify candidates before writing")
    parser.add_argument("--report",     action="store_true", help="Show opposing edge stats and exit")
    args = parser.parse_args()

    db = get_db()

    if args.report:
        cmd_report(db)
        db.close()
        return

    # Always show current state first
    before = db.execute(
        "SELECT COUNT(*) FROM belief_relations WHERE relation_type='opposes'"
    ).fetchone()[0]
    print(f"[START] Opposing edges before: {before}")

    embedder = get_embedder()
    t0 = time.time()

    if args.seed_only:
        added = cmd_seed_only(db, embedder, verify=args.verify)
    else:
        # Seed pass first, then FAISS scan
        added_seed  = cmd_seed_only(db, embedder, verify=args.verify)
        index       = get_faiss_index()
        added_faiss = cmd_faiss_scan(db, embedder, index, n=args.n, verify=args.verify)
        added = added_seed + added_faiss

    after = db.execute(
        "SELECT COUNT(*) FROM belief_relations WHERE relation_type='opposes'"
    ).fetchone()[0]

    elapsed = time.time() - t0
    print(f"\n{'═'*50}")
    print(f"  OPPOSER COMPLETE")
    print(f"  Before : {before}")
    print(f"  After  : {after}")
    print(f"  Added  : {after - before}")
    print(f"  Time   : {elapsed:.1f}s")
    print(f"{'═'*50}")

    db.close()


if __name__ == "__main__":
    main()
