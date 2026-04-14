#!/usr/bin/env python3
"""
nex_belief_refiner.py — Belief Quality Improvement Pipeline
============================================================
Operates on the belief corpus to improve overall quality:

  1. DEDUP     — find near-duplicate beliefs (cosine sim > 0.92),
                 keep highest quality, merge reinforce_count
  2. BOOST     — beliefs with high reinforce_count but low confidence
                 get a confidence nudge (evidence supports them)
  3. DECAY     — beliefs with zero use_count and low reinforce get
                 decay_score increased (they're stale)
  4. RETOPIC   — beliefs with topic=None or topic='general' get
                 assigned a topic via keyword matching
  5. REPORT    — returns summary of changes made

Run standalone or import refine_corpus() for scheduled use.
"""

import sqlite3
import math
import re
import time
from pathlib import Path
from collections import defaultdict

DB_PATH = Path("~/.config/nex/nex.db").expanduser()

# ── Keyword -> topic mapping for retopicing ───────────────────────────────────
TOPIC_KEYWORDS = {
    "ai":            ["neural", "machine learning", "deep learning", "llm", "transformer",
                      "artificial intelligence", "model", "training", "inference", "gpt",
                      "language model", "embedding", "attention", "bert"],
    "consciousness": ["conscious", "awareness", "qualia", "subjective", "experience",
                      "sentient", "mind", "perception", "phenomenal"],
    "philosophy":    ["epistem", "ontolog", "metaphysic", "logic", "reasoning", "truth",
                      "belief", "knowledge", "justif", "ethics", "moral"],
    "neuroscience":  ["neuron", "brain", "cortex", "synapse", "cognitive", "neural circuit",
                      "hippocampus", "prefrontal", "dopamine", "serotonin"],
    "finance":       ["market", "stock", "invest", "econom", "gdp", "inflation", "bank",
                      "capital", "asset", "portfolio", "risk", "return", "fiscal"],
    "legal":         ["law", "legal", "court", "statute", "regulation", "contract",
                      "jurisdiction", "liability", "compliance", "rights"],
    "climate":       ["climate", "carbon", "emission", "temperature", "global warming",
                      "renewable", "fossil fuel", "greenhouse", "net zero"],
    "oncology":      ["cancer", "tumor", "oncol", "chemotherapy", "metastasis",
                      "carcinoma", "immunotherapy", "biopsy", "malignant"],
    "cardiology":    ["heart", "cardiac", "cardiovascular", "artery", "blood pressure",
                      "myocardial", "coronary", "ecg", "atrial", "ventricular"],
    "science":       ["quantum", "physics", "chemistry", "biology", "evolution",
                      "experiment", "hypothesis", "theory", "particle", "molecule"],
    "society":       ["social", "society", "culture", "community", "democracy",
                      "government", "political", "human rights", "inequality"],
}


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _infer_topic(content: str) -> str:
    """Assign a topic to content via keyword matching."""
    text = content.lower()
    scores = defaultdict(int)
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[topic] += 1
    if scores:
        return max(scores, key=scores.get)
    return "general"


# ── Step 1: Deduplication ─────────────────────────────────────────────────────
def dedup_beliefs(dry_run: bool = False) -> dict:
    """
    Find near-duplicate beliefs using token overlap (lightweight, no sklearn needed).
    Merge reinforce_count into the higher-quality belief, delete the duplicate.
    Returns stats dict.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np
        use_tfidf = True
    except ImportError:
        use_tfidf = False

    conn = _db()
    rows = conn.execute("""
        SELECT id, content, confidence, reinforce_count, topic
        FROM beliefs
        WHERE content IS NOT NULL AND length(content) > 20
        ORDER BY confidence DESC
        LIMIT 3000
    """).fetchall()

    if len(rows) < 2:
        conn.close()
        return {"deduped": 0, "skipped": "too few beliefs"}

    ids      = [r["id"] for r in rows]
    contents = [r["content"] for r in rows]
    confs    = [r["confidence"] or 0.5 for r in rows]
    rcs      = [r["reinforce_count"] or 0 for r in rows]

    duplicates = []  # list of (keep_id, drop_id, merged_rc)

    if use_tfidf:
        vec = TfidfVectorizer(max_features=5000, stop_words="english", ngram_range=(1,2))
        try:
            matrix = vec.fit_transform(contents)
        except Exception:
            conn.close()
            return {"deduped": 0, "error": "tfidf failed"}

        # Process in chunks to avoid memory explosion
        chunk_size = 200
        seen_drop = set()
        for start in range(0, len(rows), chunk_size):
            end = min(start + chunk_size, len(rows))
            chunk_matrix = matrix[start:end]
            sims = cosine_similarity(chunk_matrix, matrix)
            for i, row_sims in enumerate(sims):
                global_i = start + i
                if ids[global_i] in seen_drop:
                    continue
                for j, sim in enumerate(row_sims):
                    if j <= global_i:
                        continue
                    if ids[j] in seen_drop:
                        continue
                    if sim >= 0.92:
                        # Keep higher confidence, drop lower
                        if confs[global_i] >= confs[j]:
                            keep, drop = global_i, j
                        else:
                            keep, drop = j, global_i
                        merged_rc = rcs[keep] + rcs[drop]
                        duplicates.append((ids[keep], ids[drop], merged_rc))
                        seen_drop.add(ids[drop])
    else:
        # Fallback: simple exact content match
        seen_content = {}
        for i, row in enumerate(rows):
            c = (row["content"] or "").strip()
            if c in seen_content:
                keep_i = seen_content[c]
                merged_rc = rcs[keep_i] + rcs[i]
                duplicates.append((ids[keep_i], ids[i], merged_rc))
            else:
                seen_content[c] = i

    if not dry_run:
        for keep_id, drop_id, merged_rc in duplicates:
            try:
                conn.execute(
                    "UPDATE beliefs SET reinforce_count=? WHERE id=?",
                    (merged_rc, keep_id)
                )
                conn.execute("DELETE FROM beliefs WHERE id=?", (drop_id,))
            except Exception:
                pass
        conn.commit()

    conn.close()
    return {"deduped": len(duplicates), "dry_run": dry_run}


# ── Step 2: Confidence boost for high-reinforce beliefs ───────────────────────
def boost_reinforced(min_rc: int = 5, boost: float = 0.05,
                     max_conf: float = 0.95, dry_run: bool = False) -> dict:
    """
    Beliefs with reinforce_count >= min_rc but confidence < 0.7 get a boost.
    Evidence of repeated reinforcement should increase confidence.
    """
    conn = _db()
    rows = conn.execute("""
        SELECT id, confidence, reinforce_count
        FROM beliefs
        WHERE reinforce_count >= ?
          AND confidence < 0.70
          AND confidence IS NOT NULL
    """, (min_rc,)).fetchall()

    updated = 0
    for row in rows:
        new_conf = min(float(row["confidence"]) + boost, max_conf)
        if not dry_run:
            conn.execute(
                "UPDATE beliefs SET confidence=? WHERE id=?",
                (round(new_conf, 4), row["id"])
            )
        updated += 1

    if not dry_run:
        conn.commit()
    conn.close()
    return {"boosted": updated, "boost_amount": boost, "dry_run": dry_run}


# ── Step 3: Decay stale beliefs ───────────────────────────────────────────────
def decay_stale(max_use: int = 0, max_rc: int = 1,
                decay_increment: float = 0.1, dry_run: bool = False) -> dict:
    """
    Beliefs never used (use_count=0) with minimal reinforcement get
    decay_score increased. They'll eventually be pruned by the main loop.
    """
    conn = _db()
    rows = conn.execute("""
        SELECT id, decay_score
        FROM beliefs
        WHERE use_count <= ?
          AND reinforce_count <= ?
          AND locked = 0
          AND pinned = 0
          AND confidence < 0.6
    """, (max_use, max_rc)).fetchall()

    updated = 0
    for row in rows:
        new_decay = min(float(row["decay_score"] or 0.0) + decay_increment, 1.0)
        if not dry_run:
            conn.execute(
                "UPDATE beliefs SET decay_score=? WHERE id=?",
                (round(new_decay, 4), row["id"])
            )
        updated += 1

    if not dry_run:
        conn.commit()
    conn.close()
    return {"decayed": updated, "increment": decay_increment, "dry_run": dry_run}


# ── Step 4: Retopic orphaned beliefs ─────────────────────────────────────────
def retopic_orphans(dry_run: bool = False) -> dict:
    """
    Beliefs with topic=NULL, '', or 'general' get assigned a topic
    via keyword matching.
    """
    conn = _db()
    rows = conn.execute("""
        SELECT id, content
        FROM beliefs
        WHERE (topic IS NULL OR topic = '' OR topic = 'general')
          AND content IS NOT NULL
          AND length(content) > 20
        LIMIT 2000
    """).fetchall()

    updated = 0
    for row in rows:
        new_topic = _infer_topic(row["content"])
        if new_topic != "general":
            if not dry_run:
                conn.execute(
                    "UPDATE beliefs SET topic=? WHERE id=?",
                    (new_topic, row["id"])
                )
            updated += 1

    if not dry_run:
        conn.commit()
    conn.close()
    return {"retopiced": updated, "dry_run": dry_run}


# ── Full pipeline ─────────────────────────────────────────────────────────────
def refine_corpus(dry_run: bool = False, verbose: bool = True) -> dict:
    """
    Run the full refinement pipeline. Safe to call repeatedly.
    Returns combined stats.
    """
    start = time.time()
    results = {}

    if verbose:
        print("[refiner] Starting belief corpus refinement...")

    if verbose: print("[refiner] Step 1/4: Deduplication...")
    results["dedup"] = dedup_beliefs(dry_run=dry_run)
    if verbose: print(f"  -> {results['dedup']['deduped']} duplicates removed")

    if verbose: print("[refiner] Step 2/4: Boosting reinforced beliefs...")
    results["boost"] = boost_reinforced(dry_run=dry_run)
    if verbose: print(f"  -> {results['boost']['boosted']} beliefs confidence-boosted")

    if verbose: print("[refiner] Step 3/4: Decaying stale beliefs...")
    results["decay"] = decay_stale(dry_run=dry_run)
    if verbose: print(f"  -> {results['decay']['decayed']} stale beliefs decayed")

    if verbose: print("[refiner] Step 4/4: Retopicing orphans...")
    results["retopic"] = retopic_orphans(dry_run=dry_run)
    if verbose: print(f"  -> {results['retopic']['retopiced']} beliefs retopiced")

    results["duration_s"] = round(time.time() - start, 2)
    results["dry_run"] = dry_run

    if verbose:
        print(f"[refiner] Complete in {results['duration_s']}s")

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import json
    dry = "--dry" in sys.argv
    if dry:
        print("DRY RUN — no changes will be written")
    results = refine_corpus(dry_run=dry, verbose=True)
    print("\nResults:")
    print(json.dumps(results, indent=2))
