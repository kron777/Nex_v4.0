#!/usr/bin/env python3
"""
nex_saga_resonance.py
Saga Resonance Engine.

Open questions (DEEP + SOUL depth) are living entities.
Each day, new beliefs are generated. Some resonate with open sagas.
This engine scores that resonance and surfaces the most active sagas
for the depth engine to prioritise.

Resonance = how much today's belief activity touches a saga's themes.

Scoring:
  keyword_overlap: saga question words found in recent beliefs
  belief_density:  count of recent beliefs touching saga themes
  warmth_alignment: warmth scores of saga keywords
  momentum_signal: avg momentum of resonant beliefs

Output: ranked saga list with resonance scores.
Stored in saga_resonance table. Read by nex_depth_engine.py.

Run nightly after belief generation.
"""
import sqlite3, json, re, math, logging, time
from pathlib import Path
from datetime import datetime, timedelta
from enum import Enum

log     = logging.getLogger("nex.saga_resonance")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"

LOOKBACK_DAYS = 3   # how many days of belief activity to score against


class Depth(Enum):
    SHALLOW   = 1
    SEMI_MID  = 2
    MID       = 3
    SEMI_DEEP = 4
    DEEP      = 5
    SOUL      = 6


def _load_sagas() -> list:
    """Load DEEP and SOUL sagas from nex_question_sagas."""
    import sys
    sys.path.insert(0, str(NEX_DIR))
    try:
        from nex_question_sagas import SAGAS, Depth as SagaDepth
        deep_soul = []
        for depth in [SagaDepth.DEEP, SagaDepth.SOUL]:
            for q in SAGAS.get(depth, []):
                deep_soul.append({
                    "question": q,
                    "depth": depth.name,
                    "depth_val": depth.value,
                })
        return deep_soul
    except Exception as e:
        log.debug(f"Could not load sagas: {e}")
        return []


def _extract_keywords(text: str) -> set:
    """Extract meaningful keywords from text."""
    stops = {
        "the","a","an","is","are","was","were","be","been","do","does",
        "did","will","would","could","should","have","has","had","what",
        "how","why","when","where","which","who","that","this","these",
        "those","and","or","but","if","then","than","so","as","at","by",
        "for","in","of","on","to","with","from","into","about","can",
        "not","no","any","all","its","our","your","their","there","here",
    }
    words = set(re.findall(r"\b[a-z]{4,}\b", text.lower()))
    return words - stops


def _get_recent_beliefs(db, days: int) -> list:
    """Get beliefs created or updated in last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = db.execute("""
        SELECT content, topic, confidence, COALESCE(momentum, 0.0) as momentum
        FROM beliefs
        WHERE created_at >= ? AND confidence >= 0.55
        ORDER BY confidence DESC
        LIMIT 500
    """, (cutoff,)).fetchall()
    return [dict(zip(["content","topic","confidence","momentum"], r)) for r in rows]


def _get_warmth_scores(db, words: set) -> dict:
    """Get warmth scores for a set of words."""
    scores = {}
    for word in words:
        row = db.execute(
            "SELECT w FROM word_tags WHERE word=?", (word,)
        ).fetchone()
        if row:
            scores[word] = row[0]
    return scores


def score_resonance(saga: dict, recent_beliefs: list, db) -> dict:
    """
    Score how much recent belief activity resonates with a saga question.
    Returns resonance dict with score and supporting data.
    """
    question    = saga["question"]
    saga_words  = _extract_keywords(question)

    if not saga_words:
        return {"score": 0.0, "saga": question, "depth": saga["depth"]}

    # Warmth scores for saga keywords
    warmth      = _get_warmth_scores(db, saga_words)
    warmth_avg  = sum(warmth.values()) / max(len(warmth), 1)

    # Score each recent belief against saga
    resonant_beliefs  = []
    total_overlap     = 0
    total_momentum    = 0.0
    total_confidence  = 0.0

    for belief in recent_beliefs:
        belief_words = _extract_keywords(belief["content"])
        overlap = saga_words & belief_words
        if len(overlap) >= 2:  # at least 2 meaningful word matches
            overlap_score = len(overlap) / math.sqrt(len(saga_words))
            resonant_beliefs.append({
                "content": belief["content"][:100],
                "overlap": len(overlap),
                "score": overlap_score,
            })
            total_overlap    += overlap_score
            total_momentum   += belief.get("momentum", 0.0)
            total_confidence += belief.get("confidence", 0.5)

    n = max(len(resonant_beliefs), 1)

    # Component scores
    density_score   = min(1.0, len(resonant_beliefs) / 10)
    overlap_score   = min(1.0, total_overlap / max(n, 1) / 3)
    warmth_score    = min(1.0, warmth_avg)
    momentum_score  = max(0.0, total_momentum / n)
    confidence_score= total_confidence / n

    # Weighted resonance
    resonance = (
        density_score   * 0.30 +
        overlap_score   * 0.25 +
        warmth_score    * 0.20 +
        momentum_score  * 0.15 +
        confidence_score* 0.10
    )

    return {
        "question":        question,
        "depth":           saga["depth"],
        "depth_val":       saga["depth_val"],
        "score":           round(resonance, 4),
        "resonant_count":  len(resonant_beliefs),
        "warmth_avg":      round(warmth_avg, 3),
        "momentum_avg":    round(total_momentum / n, 3),
        "top_beliefs":     resonant_beliefs[:3],
    }


def ensure_schema(db):
    """Create saga_resonance table if missing."""
    db.execute("""CREATE TABLE IF NOT EXISTS saga_resonance (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        question    TEXT UNIQUE,
        depth       TEXT,
        score       REAL DEFAULT 0.0,
        resonant_count INTEGER DEFAULT 0,
        warmth_avg  REAL DEFAULT 0.0,
        momentum_avg REAL DEFAULT 0.0,
        top_beliefs TEXT,
        updated_at  REAL
    )""")
    db.commit()


def run_resonance(dry_run=False) -> list:
    """Score all DEEP+SOUL sagas against recent belief activity."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    ensure_schema(db)

    sagas          = _load_sagas()
    recent_beliefs = _get_recent_beliefs(db, LOOKBACK_DAYS)

    print(f"Scoring {len(sagas)} sagas against {len(recent_beliefs)} recent beliefs...")

    results = []
    for saga in sagas:
        result = score_resonance(saga, recent_beliefs, db)
        results.append(result)

        if not dry_run:
            db.execute("""INSERT OR REPLACE INTO saga_resonance
                (question, depth, score, resonant_count, warmth_avg,
                 momentum_avg, top_beliefs, updated_at)
                VALUES (?,?,?,?,?,?,?,?)""", (
                result["question"],
                result["depth"],
                result["score"],
                result["resonant_count"],
                result["warmth_avg"],
                result["momentum_avg"],
                json.dumps(result["top_beliefs"]),
                time.time(),
            ))

    if not dry_run:
        db.commit()

    db.close()

    # Sort by resonance score
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def get_top_sagas(n: int = 5, db=None) -> list:
    """Get top N resonant sagas for depth engine prioritisation."""
    close_db = False
    if db is None:
        db = sqlite3.connect(str(DB_PATH))
        close_db = True
    rows = db.execute("""SELECT question, depth, score, resonant_count
        FROM saga_resonance
        ORDER BY score DESC LIMIT ?""", (n,)).fetchall()
    if close_db:
        db.close()
    return [{"question": r[0], "depth": r[1],
             "score": r[2], "resonant_count": r[3]} for r in rows]


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    results = run_resonance(dry_run=args.dry_run)

    print(f"\nTop {args.top} resonant sagas:")
    print(f"{'='*60}")
    for r in results[:args.top]:
        print(f"[{r['depth']}] score={r['score']:.3f} "
              f"n={r['resonant_count']} warmth={r['warmth_avg']:.2f}")
        print(f"  {r['question']}")
        if r['top_beliefs']:
            print(f"  -> {r['top_beliefs'][0]['content'][:70]}")
    print(f"{'='*60}")
