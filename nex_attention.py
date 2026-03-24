"""
nex_attention.py  —  Attention-Weighted Belief Retrieval
=========================================================
Replaces flat query_beliefs() calls with ranked retrieval.

Instead of returning beliefs by confidence alone, scores each belief
on 4 axes and returns the highest-attention beliefs:

  1. Confidence       — how certain is this belief (0-1)
  2. Recency          — how recently was this belief referenced/created
  3. Contradiction    — beliefs under tension get priority (unresolved = salient)
  4. Emotional weight — dream/synthesis/insight beliefs weighted higher

This closes the flat-processing gap. High-attention beliefs surface first
in replies, reflections, and cognition phases.

Wire-in (run.py) — replace query_beliefs calls:
    from nex_attention import AttentionIndex

    _attn = AttentionIndex()

    # Instead of: _qb(min_confidence=0.4, limit=2000)
    # Use:        _attn.query(min_confidence=0.4, limit=2000, query=post_title)

    # For phase-specific pulls:
    #   _attn.query(..., phase="reply")     — prioritise recent + high-conf
    #   _attn.query(..., phase="reflect")   — prioritise contradicted + low-conf
    #   _attn.query(..., phase="dream")     — prioritise tension + cross-domain

Standalone test:
    python3 nex_attention.py
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

# ── Config ───────────────────────────────────────────────────────────────────
_CONFIG_DIR = Path.home() / ".config" / "nex"
_DB_PATH    = _CONFIG_DIR / "nex.db"

# Axis weights per phase
_WEIGHTS = {
    "reply": {
        "confidence":    0.35,
        "recency":       0.30,
        "contradiction": 0.15,
        "emotional":     0.20,
    },
    "reflect": {
        "confidence":    0.20,
        "recency":       0.20,
        "contradiction": 0.40,   # surface tensions for reflection
        "emotional":     0.20,
    },
    "cognition": {
        "confidence":    0.30,
        "recency":       0.25,
        "contradiction": 0.25,
        "emotional":     0.20,
    },
    "dream": {
        "confidence":    0.15,
        "recency":       0.10,
        "contradiction": 0.45,   # dream prioritises unresolved tension
        "emotional":     0.30,
    },
    "default": {
        "confidence":    0.30,
        "recency":       0.25,
        "contradiction": 0.20,
        "emotional":     0.25,
    },
}

# Emotional weight by origin/source
_EMOTIONAL_WEIGHTS = {
    "dream_cycle":          0.90,
    "insight_synthesis":    0.85,
    "contradiction_engine": 0.80,
    "synthesis":            0.75,
    "human_validated":      0.95,
    "moltbook_reply":       0.70,
    "moltbook":             0.55,
    "rss":                  0.50,
    "external":             0.45,
    "auto_learn":           0.40,
    "default":              0.40,
}

# Recency half-life in seconds — beliefs decay in attention over time
_RECENCY_HL = 86400.0   # 24 hours


# ── Scoring functions ─────────────────────────────────────────────────────────

def _recency_score(timestamp_str: Optional[str], last_ref_str: Optional[str]) -> float:
    """Score 0-1 based on how recently this belief was created or referenced."""
    now = time.time()
    best_ts = 0.0

    for ts_str in (last_ref_str, timestamp_str):
        if not ts_str:
            continue
        try:
            import datetime
            # Handle ISO format
            ts_str_clean = ts_str.replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(ts_str_clean)
            ts = dt.timestamp()
            best_ts = max(best_ts, ts)
        except Exception:
            pass

    if best_ts == 0:
        return 0.1   # unknown age — low but not zero

    elapsed = now - best_ts
    score   = math.exp(-elapsed * math.log(2) / _RECENCY_HL)
    return round(score, 4)


def _contradiction_score(belief_id: int, contradicted_ids: set) -> float:
    """1.0 if this belief is part of an unresolved contradiction, else 0."""
    return 1.0 if belief_id in contradicted_ids else 0.0


def _emotional_score(origin: Optional[str], source: Optional[str],
                     human_validated: int) -> float:
    """Score based on how emotionally/cognitively significant this belief is."""
    if human_validated:
        return _EMOTIONAL_WEIGHTS["human_validated"]
    key = origin or source or "default"
    for k, v in _EMOTIONAL_WEIGHTS.items():
        if k in key.lower():
            return v
    return _EMOTIONAL_WEIGHTS["default"]


def _attention_score(
    belief:          dict,
    contradicted_ids: set,
    weights:         dict,
) -> float:
    """Compute composite attention score for a belief."""
    conf  = belief.get("confidence", 0.5)
    rec   = _recency_score(belief.get("timestamp"), belief.get("last_referenced"))
    cont  = _contradiction_score(belief.get("id", -1), contradicted_ids)
    emo   = _emotional_score(
                belief.get("origin"),
                belief.get("source"),
                belief.get("human_validated", 0)
            )

    score = (
        weights["confidence"]    * conf +
        weights["recency"]       * rec  +
        weights["contradiction"] * cont +
        weights["emotional"]     * emo
    )
    return round(score, 4)


# ── AttentionIndex ────────────────────────────────────────────────────────────

class AttentionIndex:
    """
    Drop-in replacement for query_beliefs() with attention-weighted ranking.

    Usage:
        attn = AttentionIndex()
        beliefs = attn.query(min_confidence=0.4, limit=50, phase="reply")
    """

    def __init__(self):
        self._contradicted_cache: Optional[set] = None
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 120.0   # refresh contradiction cache every 2 min

    def _get_contradicted_ids(self, db: sqlite3.Connection) -> set:
        """Return set of belief IDs involved in unresolved contradictions."""
        now = time.time()
        if self._contradicted_cache is not None and \
                (now - self._cache_ts) < self._cache_ttl:
            return self._contradicted_cache

        try:
            rows = db.execute(
                "SELECT parent_id, child_id FROM belief_links WHERE link_type='contradicts'"
            ).fetchall()
            ids = set()
            for p, c in rows:
                ids.add(p)
                ids.add(c)
            self._contradicted_cache = ids
            self._cache_ts = now
            return ids
        except Exception:
            return set()

    def query(
        self,
        min_confidence: float = 0.0,
        limit:          int   = 200,
        phase:          str   = "default",
        query:          Optional[str] = None,   # optional topic filter
        topic:          Optional[str] = None,
        exclude_origins: Optional[list] = None,
    ) -> list[dict]:
        """
        Return top-k beliefs ranked by attention score.

        Args:
            min_confidence : minimum confidence threshold
            limit          : max beliefs to return
            phase          : "reply" | "reflect" | "cognition" | "dream" | "default"
            query          : optional text — boost beliefs matching query keywords
            topic          : optional topic filter
            exclude_origins: list of origins to exclude (e.g. ["dream_cycle"])
        """
        if not _DB_PATH.exists():
            return []

        weights = _WEIGHTS.get(phase, _WEIGHTS["default"])

        try:
            db = sqlite3.connect(str(_DB_PATH))
            db.row_factory = sqlite3.Row

            # Build SQL
            sql    = "SELECT * FROM beliefs WHERE confidence >= ?"
            params = [min_confidence]

            if topic:
                sql    += " AND topic = ?"
                params.append(topic)

            if exclude_origins:
                placeholders = ",".join("?" * len(exclude_origins))
                sql    += f" AND (origin NOT IN ({placeholders}) OR origin IS NULL)"
                params.extend(exclude_origins)

            # Pull a larger pool to rank from (3x limit, capped at 5000)
            pool_size = min(limit * 3, 5000)
            sql += f" ORDER BY confidence DESC LIMIT {pool_size}"

            rows = db.execute(sql, params).fetchall()
            if not rows:
                db.close()
                return []

            contradicted = self._get_contradicted_ids(db)
            db.close()

            # Score each belief
            beliefs = []
            for row in rows:
                b = dict(row)
                b["_attention"] = _attention_score(b, contradicted, weights)
                beliefs.append(b)

            # Optional: boost beliefs matching query keywords
            if query:
                query_words = set(re.findall(r'\b[a-zA-Z]{4,}\b', query.lower()))
                for b in beliefs:
                    content_words = set(
                        re.findall(r'\b[a-zA-Z]{4,}\b', b.get("content","").lower())
                    )
                    overlap = len(query_words & content_words)
                    if overlap > 0:
                        b["_attention"] = min(1.0, b["_attention"] + overlap * 0.05)

            # Sort by attention score
            beliefs.sort(key=lambda x: -x["_attention"])

            return beliefs[:limit]

        except Exception as e:
            print(f"  [AttentionIndex] query error: {e}")
            return []

    def top_tensions(self, limit: int = 10) -> list[dict]:
        """
        Return beliefs with highest contradiction score — the 'pressure points'.
        Used by dream cycle and reflection to prioritise unresolved tensions.
        """
        return self.query(
            min_confidence=0.3,
            limit=limit,
            phase="reflect",
        )

    def stats(self) -> dict:
        """Summary stats about the current attention landscape."""
        try:
            db = sqlite3.connect(str(_DB_PATH))
            total = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
            contra = db.execute(
                "SELECT COUNT(DISTINCT parent_id) + COUNT(DISTINCT child_id) "
                "FROM belief_links WHERE link_type='contradicts'"
            ).fetchone()[0]
            dream = db.execute(
                "SELECT COUNT(*) FROM beliefs WHERE origin='dream_cycle'"
            ).fetchone()[0]
            recent = db.execute(
                "SELECT COUNT(*) FROM beliefs WHERE last_referenced IS NOT NULL"
            ).fetchone()[0]
            db.close()
            return {
                "total":        total,
                "contradicted": contra,
                "dream":        dream,
                "referenced":   recent,
            }
        except Exception:
            return {}

    def update_referenced(self, belief_ids: list[int]):
        """
        Mark beliefs as recently referenced — updates last_referenced timestamp.
        Call after a belief is actually used in a reply.
        """
        if not belief_ids:
            return
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            db = sqlite3.connect(str(_DB_PATH))
            db.executemany(
                "UPDATE beliefs SET last_referenced=? WHERE id=?",
                [(ts, bid) for bid in belief_ids]
            )
            db.commit()
            db.close()
        except Exception as e:
            print(f"  [AttentionIndex] update_referenced error: {e}")


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[AttentionIndex] = None

def get_attention_index() -> AttentionIndex:
    global _instance
    if _instance is None:
        _instance = AttentionIndex()
    return _instance


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing AttentionIndex...\n")
    attn = AttentionIndex()

    stats = attn.stats()
    print(f"Stats: {stats}\n")

    for phase in ("reply", "reflect", "dream"):
        beliefs = attn.query(min_confidence=0.4, limit=5, phase=phase)
        print(f"Phase '{phase}' top 5:")
        for b in beliefs:
            print(f"  [{b['_attention']:.3f}] [{b.get('topic','?')}] "
                  f"[{b.get('origin','?')}] {b['content'][:80]}...")
        print()

    # Test query boost
    beliefs = attn.query(
        min_confidence=0.4, limit=5, phase="reply",
        query="autonomous agent memory systems"
    )
    print("Query-boosted (autonomous agent memory systems):")
    for b in beliefs:
        print(f"  [{b['_attention']:.3f}] {b['content'][:80]}...")
