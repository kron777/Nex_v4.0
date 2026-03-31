#!/usr/bin/env python3
"""
nex_belief_quality.py — Belief Quality Scoring Engine
======================================================
Scores beliefs across multiple dimensions:
  - confidence weight
  - reinforcement momentum
  - decay penalty
  - use frequency
  - source authority
  - topic density (how well-covered is this topic)

Provides:
  score_belief(row)          -> float 0.0-1.0
  score_all()                -> list of (id, score) sorted desc
  flag_weak(threshold=0.3)   -> list of belief ids below threshold
  quality_report()           -> dict summary
"""

import sqlite3
import math
from pathlib import Path
from typing import Optional

DB_PATH = Path("~/.config/nex/nex.db").expanduser()

# ── Source authority weights ──────────────────────────────────────────────────
SOURCE_WEIGHTS = {
    "arxiv":               1.0,
    "pubmed":              1.0,
    "wikipedia":           0.85,
    "scheduler_saturation": 0.82,  # domain saturation — structured prompts
    "self_research":       0.88,   # NEX's own research — academic quality
    "synthesis":           0.80,
    "auto_seeder":         0.70,
    "human":               0.95,
    "groq":                0.65,
    "web":                 0.60,
    "unknown":             0.50,
}

def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _source_weight(source: str) -> float:
    if not source:
        return SOURCE_WEIGHTS["unknown"]
    src = source.lower()
    for key, weight in SOURCE_WEIGHTS.items():
        if key in src:
            return weight
    return SOURCE_WEIGHTS["unknown"]


def score_belief(row) -> float:
    """
    Compute quality score 0.0–1.0 for a single belief row.

    Formula:
      base      = confidence * 0.40
      reinforce = log1p(reinforce_count) / log1p(50) * 0.20
      decay_pen = (1 - decay_score) * 0.15   (lower decay = better)
      use_freq  = log1p(use_count) / log1p(100) * 0.15
      source    = source_weight * 0.10
    """
    conf    = float(row["confidence"] or 0.5)
    rc      = int(row["reinforce_count"] or 0)
    decay   = float(row["decay_score"] or 0.0)
    use     = int(row["use_count"] or 0)
    source  = str(row["source"] or "")

    base        = conf * 0.40
    reinforce   = (math.log1p(rc) / math.log1p(50)) * 0.20
    decay_pen   = (1.0 - min(decay, 1.0)) * 0.15
    use_freq    = (math.log1p(use) / math.log1p(100)) * 0.15
    src_weight  = _source_weight(source) * 0.10

    score = base + reinforce + decay_pen + use_freq + src_weight
    return round(min(score, 1.0), 4)


def score_all(limit: int = 5000) -> list:
    """
    Score all beliefs. Returns list of dicts sorted by score descending.
    """
    try:
        conn = _db()
        rows = conn.execute("""
            SELECT id, content, confidence, reinforce_count,
                   decay_score, use_count, source, topic
            FROM beliefs
            WHERE content IS NOT NULL AND length(content) > 10
            ORDER BY confidence DESC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
    except Exception as e:
        print(f"[belief_quality] DB error: {e}")
        return []

    scored = []
    for row in rows:
        s = score_belief(row)
        scored.append({
            "id":         row["id"],
            "topic":      row["topic"] or "general",
            "score":      s,
            "confidence": row["confidence"],
            "content":    (row["content"] or "")[:120],
            "source":     row["source"] or "",
        })

    scored.sort(key=lambda x: -x["score"])
    return scored


def flag_weak(threshold: float = 0.3) -> list:
    """
    Return belief IDs scoring below threshold.
    These are candidates for refinement or pruning.
    """
    scored = score_all()
    return [b["id"] for b in scored if b["score"] < threshold]


def quality_report() -> dict:
    """
    Return a summary of the belief corpus quality distribution.
    """
    scored = score_all()
    if not scored:
        return {"error": "no beliefs scored"}

    scores = [b["score"] for b in scored]
    avg    = round(sum(scores) / len(scores), 3)

    elite    = sum(1 for s in scores if s >= 0.70)
    high     = sum(1 for s in scores if 0.50 <= s < 0.70)
    medium   = sum(1 for s in scores if 0.30 <= s < 0.50)
    low      = sum(1 for s in scores if s < 0.30)

    # Top topics by average quality score
    topic_scores: dict = {}
    for b in scored:
        t = b["topic"]
        if t not in topic_scores:
            topic_scores[t] = []
        topic_scores[t].append(b["score"])

    topic_avg = {
        t: round(sum(v)/len(v), 3)
        for t, v in topic_scores.items()
        if len(v) >= 3
    }
    top_topics = sorted(topic_avg.items(), key=lambda x: -x[1])[:10]

    return {
        "total_scored":  len(scored),
        "avg_score":     avg,
        "distribution": {
            "elite":  elite,
            "high":   high,
            "medium": medium,
            "low":    low,
        },
        "top_quality_topics": [{"topic": t, "avg_score": s} for t, s in top_topics],
        "weak_belief_count":  low + medium,
        "qlora_ready":        elite >= 500 and avg >= 0.50,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    print("Running belief quality report...")
    report = quality_report()
    print(json.dumps(report, indent=2))
    weak = flag_weak(0.3)
    print(f"\nWeak beliefs (score < 0.30): {len(weak)}")
    print(f"QLoRA ready: {report['qlora_ready']}")
