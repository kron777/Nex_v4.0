#!/usr/bin/env python3
"""
nex_belief_refiner.py — Belief Quality Improvement Pipeline v2
===============================================================
Upgrades over v1:
  - dedup_beliefs: raises limit to 6000 (covers full corpus)
  - decay_stale:   schema-safe (no locked/pinned dependency)
  - boost_reinforced: scaled boost — stronger reinforcement = larger nudge
  - retopic_orphans: unchanged (was solid)
  - Added: scheduler_hook() for cron/API trigger
  - Added: /refiner/run + /refiner/report Flask routes (imported by nex_api)

Run standalone:
    python3 nex_belief_refiner.py          # full run
    python3 nex_belief_refiner.py --dry    # dry run, no writes
    python3 nex_belief_refiner.py --report # quality report only
"""

import sqlite3
import math
import re
import time
import json
import sys
from pathlib import Path
from collections import defaultdict

DB_PATH = Path("~/.config/nex/nex.db").expanduser()

# ── Topic keyword mapping (unchanged from v1) ────────────────────────────────
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
    text   = content.lower()
    scores = defaultdict(int)
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[topic] += 1
    return max(scores, key=scores.get) if scores else "general"


def _schema_has_column(conn, table: str, column: str) -> bool:
    """Check if a column exists in a table without throwing."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == column for r in rows)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Deduplication
# ══════════════════════════════════════════════════════════════════════════════
def dedup_beliefs(dry_run: bool = False) -> dict:
    """
    Find near-duplicate beliefs (cosine sim >= 0.92).
    Merge reinforce_count into the higher-quality belief, delete the duplicate.
    Limit raised to 6000 to cover full corpus.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        use_tfidf = True
    except ImportError:
        use_tfidf = False

    conn = _db()
    rows = conn.execute("""
        SELECT id, content, confidence, reinforce_count, topic
        FROM beliefs
        WHERE content IS NOT NULL AND length(content) > 20
        ORDER BY confidence DESC
        LIMIT 6000
    """).fetchall()

    if len(rows) < 2:
        conn.close()
        return {"deduped": 0, "skipped": "too few beliefs"}

    ids      = [r["id"] for r in rows]
    contents = [r["content"] for r in rows]
    confs    = [float(r["confidence"] or 0.5) for r in rows]
    rcs      = [int(r["reinforce_count"] or 0) for r in rows]

    duplicates = []

    if use_tfidf:
        vec = TfidfVectorizer(max_features=6000, stop_words="english", ngram_range=(1, 2))
        try:
            matrix = vec.fit_transform(contents)
        except Exception as e:
            conn.close()
            return {"deduped": 0, "error": f"tfidf failed: {e}"}

        chunk_size = 200
        seen_drop  = set()
        for start in range(0, len(rows), chunk_size):
            end          = min(start + chunk_size, len(rows))
            chunk_matrix = matrix[start:end]
            sims         = cosine_similarity(chunk_matrix, matrix)
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
                        keep, drop = (global_i, j) if confs[global_i] >= confs[j] else (j, global_i)
                        merged_rc  = rcs[keep] + rcs[drop]
                        duplicates.append((ids[keep], ids[drop], merged_rc))
                        seen_drop.add(ids[drop])
    else:
        # Fallback: exact content match
        seen_content = {}
        for i, row in enumerate(rows):
            c = (row["content"] or "").strip()
            if c in seen_content:
                ki        = seen_content[c]
                merged_rc = rcs[ki] + rcs[i]
                duplicates.append((ids[ki], ids[i], merged_rc))
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


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Scaled confidence boost for well-reinforced beliefs
# ══════════════════════════════════════════════════════════════════════════════
def boost_reinforced(min_rc: int = 5, max_conf: float = 0.95,
                     dry_run: bool = False) -> dict:
    """
    Beliefs with reinforce_count >= min_rc but confidence < 0.7 get a
    confidence nudge scaled by reinforcement strength:
        rc 5-9   → +0.04
        rc 10-24 → +0.06
        rc 25+   → +0.08
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
        rc       = int(row["reinforce_count"] or 0)
        boost    = 0.04 if rc < 10 else (0.06 if rc < 25 else 0.08)
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
    return {"boosted": updated, "dry_run": dry_run}


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Decay stale beliefs (schema-safe)
# ══════════════════════════════════════════════════════════════════════════════
def decay_stale(max_use: int = 0, max_rc: int = 1,
                decay_increment: float = 0.1, dry_run: bool = False) -> dict:
    """
    Beliefs with zero/minimal use and reinforcement get decay_score increased.
    Schema-safe: does not depend on locked/pinned columns existing.
    """
    conn = _db()

    # Build WHERE clause defensively based on actual schema
    has_locked = _schema_has_column(conn, "beliefs", "locked")
    has_pinned = _schema_has_column(conn, "beliefs", "pinned")

    lock_clause = "AND locked = 0" if has_locked else ""
    pin_clause  = "AND pinned = 0" if has_pinned else ""

    try:
        rows = conn.execute(f"""
            SELECT id, decay_score
            FROM beliefs
            WHERE use_count <= ?
              AND reinforce_count <= ?
              AND confidence < 0.6
              {lock_clause}
              {pin_clause}
        """, (max_use, max_rc)).fetchall()
    except Exception:
        # use_count might not exist either — try without it
        try:
            rows = conn.execute(f"""
                SELECT id, decay_score
                FROM beliefs
                WHERE reinforce_count <= ?
                  AND confidence < 0.6
                  {lock_clause}
                  {pin_clause}
                LIMIT 1000
            """, (max_rc,)).fetchall()
        except Exception as e:
            conn.close()
            return {"decayed": 0, "error": str(e)}

    updated = 0
    for row in rows:
        new_decay = min(float(row["decay_score"] or 0.0) + decay_increment, 1.0)
        if not dry_run:
            try:
                conn.execute(
                    "UPDATE beliefs SET decay_score=? WHERE id=?",
                    (round(new_decay, 4), row["id"])
                )
                updated += 1
            except Exception:
                pass

    if not dry_run:
        conn.commit()
    conn.close()
    return {"decayed": updated, "increment": decay_increment, "dry_run": dry_run}


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Retopic orphaned beliefs
# ══════════════════════════════════════════════════════════════════════════════
def retopic_orphans(dry_run: bool = False) -> dict:
    """
    Beliefs with topic=NULL/empty/'general' get a topic assigned via
    keyword matching. Covers all orphans up to 5000.
    """
    conn = _db()
    rows = conn.execute("""
        SELECT id, content
        FROM beliefs
        WHERE (topic IS NULL OR topic = '' OR topic = 'general')
          AND content IS NOT NULL
          AND length(content) > 20
        LIMIT 5000
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


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Quality re-score (writes quality_score column if absent)
# ══════════════════════════════════════════════════════════════════════════════
def rescore_quality(dry_run: bool = False) -> dict:
    """
    Compute the nex_belief_quality score for every belief and write it
    to a quality_score column (created if absent). This lets fetch_stats()
    use real quality distribution instead of confidence-only thresholds.
    """
    try:
        from nex_belief_quality import score_belief
    except ImportError:
        return {"rescored": 0, "error": "nex_belief_quality not importable"}

    conn = _db()

    # Add quality_score column if it doesn't exist
    if not _schema_has_column(conn, "beliefs", "quality_score"):
        if not dry_run:
            try:
                conn.execute("ALTER TABLE beliefs ADD COLUMN quality_score REAL DEFAULT 0.0")
                conn.commit()
            except Exception as e:
                conn.close()
                return {"rescored": 0, "error": f"ALTER TABLE failed: {e}"}

    rows = conn.execute("""
        SELECT id, confidence, reinforce_count, decay_score, use_count, source
        FROM beliefs
        WHERE content IS NOT NULL AND length(content) > 10
        LIMIT 6000
    """).fetchall()

    updated = 0
    for row in rows:
        score = score_belief(row)
        if not dry_run:
            try:
                conn.execute(
                    "UPDATE beliefs SET quality_score=? WHERE id=?",
                    (score, row["id"])
                )
                updated += 1
            except Exception:
                pass

    if not dry_run:
        conn.commit()
    conn.close()
    return {"rescored": updated, "dry_run": dry_run}


# ══════════════════════════════════════════════════════════════════════════════
# Full pipeline
# ══════════════════════════════════════════════════════════════════════════════
def refine_corpus(dry_run: bool = False, verbose: bool = True) -> dict:
    """
    Run the full refinement pipeline. Safe to call repeatedly.
    Steps: dedup → boost → decay → retopic → rescore
    """
    start   = time.time()
    results = {}

    if verbose:
        print("[refiner] Starting belief corpus refinement...")

    if verbose: print("[refiner] Step 1/5: Deduplication...")
    results["dedup"] = dedup_beliefs(dry_run=dry_run)
    if verbose: print(f"  -> {results['dedup']['deduped']} duplicates removed")

    if verbose: print("[refiner] Step 2/5: Boosting reinforced beliefs...")
    results["boost"] = boost_reinforced(dry_run=dry_run)
    if verbose: print(f"  -> {results['boost']['boosted']} beliefs confidence-boosted")

    if verbose: print("[refiner] Step 3/5: Decaying stale beliefs...")
    results["decay"] = decay_stale(dry_run=dry_run)
    if verbose: print(f"  -> {results['decay']['decayed']} stale beliefs decayed")

    if verbose: print("[refiner] Step 4/5: Retopicing orphans...")
    results["retopic"] = retopic_orphans(dry_run=dry_run)
    if verbose: print(f"  -> {results['retopic']['retopiced']} beliefs retopiced")

    if verbose: print("[refiner] Step 5/5: Rescoring quality...")
    results["rescore"] = rescore_quality(dry_run=dry_run)
    if verbose: print(f"  -> {results['rescore']['rescored']} beliefs quality-scored")

    results["duration_s"] = round(time.time() - start, 2)
    results["dry_run"]    = dry_run

    if verbose:
        print(f"[refiner] Complete in {results['duration_s']}s")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# Scheduler hook — call this from nex_scheduler or cron
# ══════════════════════════════════════════════════════════════════════════════
def scheduler_hook() -> dict:
    """
    Drop-in for nex_scheduler.py trigger hooks.
    Runs full pipeline, returns results dict.
    """
    return refine_corpus(dry_run=False, verbose=False)


# ══════════════════════════════════════════════════════════════════════════════
# Flask routes — register these in nex_api.py if desired
# ══════════════════════════════════════════════════════════════════════════════
def register_refiner_routes(app, require_admin):
    """
    Call from nex_api.py after app is created:
        from nex_belief_refiner import register_refiner_routes
        register_refiner_routes(app, require_admin)

    Exposes:
        POST /admin/refiner/run      — run full pipeline
        GET  /admin/refiner/report   — quality report only
    """
    from flask import jsonify, request as freq

    @app.route("/admin/refiner/run", methods=["POST"])
    @require_admin
    def refiner_run():
        body    = freq.get_json(silent=True) or {}
        dry_run = bool(body.get("dry_run", False))
        results = refine_corpus(dry_run=dry_run, verbose=False)
        return jsonify(results)

    @app.route("/admin/refiner/report", methods=["GET"])
    @require_admin
    def refiner_report():
        try:
            from nex_belief_quality import quality_report
            report = quality_report()
        except ImportError:
            report = {"error": "nex_belief_quality not available"}
        return jsonify(report)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    dry    = "--dry"    in sys.argv
    report = "--report" in sys.argv

    if report:
        try:
            from nex_belief_quality import quality_report
            print(json.dumps(quality_report(), indent=2))
        except ImportError:
            print("nex_belief_quality not importable")
        sys.exit(0)

    if dry:
        print("DRY RUN — no changes will be written")

    results = refine_corpus(dry_run=dry, verbose=True)
    print("\nResults:")
    print(json.dumps(results, indent=2))
