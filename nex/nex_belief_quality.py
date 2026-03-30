#!/usr/bin/env python3
"""
nex_belief_quality.py — Belief Response Quality Scorer
=======================================================
Deploy to: ~/Desktop/nex/nex/nex_belief_quality.py

WHY THIS MATTERS (Grok missed this entirely):

Grok's "self-upgrade protocol" is vague. The real version is:
  Which of NEX's 32,000 beliefs are actually producing good responses?
  Which are high-confidence noise that gets retrieved but never helps?

Problem: SoulLoop scores beliefs by confidence + token overlap.
But high confidence ≠ high response quality.

A belief tagged at 0.92 confidence might be:
  (a) encyclopedic scraped text that gets retrieved but produces
      mechanical responses that the refiner strips out
  (b) a genuinely held opinion that anchor's NEX's best responses

This module:
  - Reads the audit log to find soul-stage responses (best quality)
  - Cross-references which topics/concepts were active in those responses  
  - Computes a "response_quality_score" per topic cluster
  - Writes this back as a bonus weight into the DB
    (new column: response_quality_score, or stored in nex_directive_kv)
  - SoulLoop's _score_belief() can then add this bonus weight

This closes the feedback loop:
  Good response → audit log records topic/concept/confidence
  → quality scorer finds which beliefs contributed
  → those beliefs get a bonus in future retrieval
  → NEX gets better at producing good responses on its best topics

This is what Grok's "self-upgrade protocol" actually means in practice:
not hot-patching code, but using response quality feedback to reshape
the retrieval distribution.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from collections import defaultdict
from typing import Optional

_CFG        = Path("~/.config/nex").expanduser()
_DB_PATH    = _CFG / "nex.db"
_LOG_PATH   = _CFG / "audit_log.jsonl"
_QUAL_PATH  = _CFG / "belief_quality_scores.json"
_KV_KEY     = "belief_quality_last_run"

# How much weight to give quality bonus in _score_belief()
QUALITY_BONUS_SCALE = 1.5   # max 1.5 extra score points for top-quality topics


def _db() -> Optional[sqlite3.Connection]:
    if not _DB_PATH.exists():
        return None
    try:
        con = sqlite3.connect(str(_DB_PATH), timeout=3)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


def _load_audit_log(max_entries: int = 2000) -> list[dict]:
    if not _LOG_PATH.exists():
        return []
    try:
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines[-max_entries:]:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
        return entries
    except Exception:
        return []


def compute_quality_scores() -> dict[str, float]:
    """
    Analyse audit log to compute quality scores per topic.
    
    Quality signals (positive):
      - stage == "soul"         → SoulLoop answered (best)
      - confidence >= 0.70      → high-confidence retrieval
      - reply_words >= 20       → substantive response
      - intent in position/challenge/exploration → engaged reasoning
    
    Quality signals (negative):
      - stage == "fallback"     → nothing useful retrieved
      - reply_words < 8         → degenerate response
      - intent == "honest_gap"  → sparse corpus on this topic
    
    Returns dict: topic → quality_score (0.0 to 1.0)
    """
    entries = _load_audit_log()
    if not entries:
        return {}

    # Accumulate scores per topic
    topic_scores: dict[str, list[float]] = defaultdict(list)
    concept_scores: dict[str, list[float]] = defaultdict(list)

    for e in entries:
        intent      = e.get("intent", "")
        stage       = e.get("stage", "fallback")
        confidence  = float(e.get("confidence", 0.5) or 0.5)
        words       = int(e.get("reply_words", 0) or 0)
        clean       = e.get("clean_query", "") or e.get("query", "")

        # Compute per-entry quality signal
        q = 0.5   # baseline

        # Stage bonus
        if stage == "soul":
            q += 0.3
        elif stage == "voice":
            q += 0.1
        elif stage == "fallback":
            q -= 0.3

        # Confidence signal
        q += (confidence - 0.5) * 0.3

        # Response length signal (normalized)
        if words >= 25:
            q += 0.15
        elif words >= 15:
            q += 0.05
        elif words < 8:
            q -= 0.2

        # Intent signal
        if intent in ("position", "challenge"):
            q += 0.1
        elif intent in ("honest_gap", "unknown"):
            q -= 0.15

        q = max(0.0, min(1.0, q))

        # Attribute to topic/concept from the query context
        # We don't store topic per audit entry, but we store clean_query tokens
        # Use those to infer topic alignment
        if clean:
            # Store against clean query keywords (will be joined to topics later)
            topic_scores[clean[:40]].append(q)

    # Now map accumulated query patterns → DB topics
    # Load topic distribution from DB
    db_topic_scores: dict[str, float] = {}
    db = _db()
    if db:
        try:
            rows = db.execute(
                "SELECT topic, COUNT(*) as n, AVG(confidence) as avg_conf "
                "FROM beliefs WHERE topic IS NOT NULL AND topic != '' "
                "GROUP BY topic HAVING n >= 3 ORDER BY n DESC LIMIT 300"
            ).fetchall()
            db.close()

            # For each DB topic, find audit entries whose query overlaps
            import re
            _stop = {"the","a","an","is","are","was","were","be","of","in",
                     "on","for","to","and","or","but","not","you","i","my","do"}

            def _tok(t):
                return set(re.sub(r"[^a-z0-9 ]"," ",t.lower()).split()) - _stop

            for row in rows:
                topic     = row["topic"].lower().strip()
                avg_conf  = float(row["avg_conf"] or 0.5)
                topic_tok = _tok(topic)

                matching_qs = []
                for qtext, qs in topic_scores.items():
                    q_tok = _tok(qtext)
                    if topic_tok & q_tok:
                        matching_qs.extend(qs)

                if matching_qs:
                    # Weighted average: 60% from audit, 40% from avg_conf baseline
                    audit_score = sum(matching_qs) / len(matching_qs)
                    db_topic_scores[topic] = round(
                        0.6 * audit_score + 0.4 * avg_conf, 3
                    )
                else:
                    # No audit data — use confidence as baseline quality
                    db_topic_scores[topic] = round(avg_conf * 0.7, 3)

        except Exception:
            try: db.close()
            except: pass

    return db_topic_scores


def get_topic_bonus(topic: str) -> float:
    """
    Get the quality bonus for a topic during belief retrieval.
    Returns 0.0 to QUALITY_BONUS_SCALE.
    Used in SoulLoop's _score_belief().
    """
    if not _QUAL_PATH.exists():
        return 0.0
    try:
        scores = json.loads(_QUAL_PATH.read_text(encoding="utf-8"))
        raw    = scores.get("scores", {}).get(topic.lower().strip(), 0.5)
        # Map 0-1 score to 0-QUALITY_BONUS_SCALE bonus
        return round((float(raw) - 0.5) * 2 * QUALITY_BONUS_SCALE, 3)
    except Exception:
        return 0.0


def run_quality_cycle(verbose: bool = False) -> dict:
    """
    Compute quality scores and persist them.
    Returns summary dict.
    Call from NEX's background cycle every 10 cycles or so.
    """
    scores = compute_quality_scores()
    if not scores:
        return {"topics_scored": 0, "top": [], "bottom": []}

    # Sort by quality
    sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
    top    = [(t, s) for t, s in sorted_scores[:10]]
    bottom = [(t, s) for t, s in sorted_scores[-5:] if s < 0.4]

    # Persist
    try:
        _QUAL_PATH.write_text(json.dumps({
            "updated":       time.strftime("%Y-%m-%dT%H:%M:%S"),
            "topics_scored": len(scores),
            "scores":        scores,
        }, indent=2), encoding="utf-8")
    except Exception:
        pass

    # Also write to DB kv store if available
    db = _db()
    if db:
        try:
            db.execute(
                "INSERT OR REPLACE INTO nex_directive_kv (key, value) VALUES (?, ?)",
                (_KV_KEY, time.strftime("%Y-%m-%dT%H:%M:%S"))
            )
            db.commit()
            db.close()
        except Exception:
            try: db.close()
            except: pass

    if verbose:
        print(f"  [Quality] Scored {len(scores)} topics")
        print(f"  [Quality] Top topics: {[t for t, _ in top[:5]]}")
        print(f"  [Quality] Weak topics: {[t for t, _ in bottom[:3]]}")

    return {
        "topics_scored": len(scores),
        "top":    top,
        "bottom": bottom,
    }


def apply_quality_to_soul_loop() -> str:
    """
    Returns a patch string showing how to integrate into nex_soul_loop.py.
    The actual patch is applied by nex_wire_evolution.py.
    """
    return '''
    # ── Quality bonus in _score_belief() ────────────────────────────────
    # Add after the existing score calculation in _score_belief():
    try:
        from nex.nex_belief_quality import get_topic_bonus
        boost = get_topic_bonus(belief.get("topic", ""))
        if boost != 0:
            return (overlap * 0.5 + conf * 0.5) + boost + (0.3 if ... else 0.0)
    except Exception:
        pass
    # ────────────────────────────────────────────────────────────────────
'''


if __name__ == "__main__":
    print("Running belief quality analysis...")
    result = run_quality_cycle(verbose=True)
    print(f"\nTop quality topics:")
    for topic, score in result["top"]:
        bar = "█" * int(score * 20) + "░" * (20 - int(score * 20))
        print(f"  {topic:30s} {bar} {score:.3f}")
    if result["bottom"]:
        print(f"\nWeak topics (need more beliefs):")
        for topic, score in result["bottom"]:
            print(f"  {topic:30s} {score:.3f}")
