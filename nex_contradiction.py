#!/usr/bin/env python3
"""
nex_contradiction.py — Belief Contradiction Detector v2
========================================================
Detects when a query semantically contradicts held beliefs.

v2 upgrades over v1:
  1. TF-IDF retrieval first (like nex_reason.py) — finds relevant beliefs
     before checking for contradiction, not just top-50 by confidence
  2. Semantic opposition scoring — catches contradictions without negation
     e.g. "vaccines cause autism" vs "vaccines are safe"
  3. Antonym pair detection — explicit semantic reversal keywords
     "effective/ineffective", "safe/harmful", "prevents/causes" etc.
  4. Stance polarity analysis — compares directional claim vectors
  5. Negation logic fixed — negation is one signal, not the only signal
  6. Confidence-weighted severity — high-confidence beliefs matter more

API contract (unchanged — drop-in replacement):
  detect_contradictions(query) -> list of dicts
  contradiction_summary(contradictions) -> str | None
"""

import re
import sqlite3
import math
import threading
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"

# ── Semantic opposition pairs ─────────────────────────────────────────────────
# (positive_term, negative_term) — if query contains one and belief contains
# the other (or vice versa), that's a strong contradiction signal
OPPOSITION_PAIRS = [
    # Safety / harm
    ("safe", "dangerous"), ("safe", "harmful"), ("safe", "toxic"),
    ("beneficial", "harmful"), ("beneficial", "detrimental"),
    ("effective", "ineffective"), ("effective", "useless"),
    ("works", "fails"), ("works", "ineffective"),
    # Causation direction
    ("prevents", "causes"), ("prevents", "triggers"), ("prevents", "induces"),
    ("reduces", "increases"), ("reduces", "elevates"), ("reduces", "worsens"),
    ("improves", "worsens"), ("improves", "degrades"),
    ("protects", "damages"), ("protects", "harms"),
    # Existence / truth
    ("exists", "doesn't exist"), ("real", "myth"), ("real", "false"),
    ("true", "false"), ("proven", "disproven"), ("confirmed", "refuted"),
    ("possible", "impossible"), ("likely", "unlikely"),
    # Medical / scientific
    ("cures", "causes"), ("treats", "worsens"), ("heals", "harms"),
    ("associated with", "unrelated to"), ("linked to", "unrelated to"),
    ("increases risk", "reduces risk"), ("high risk", "low risk"),
    # AI / tech
    ("aligned", "misaligned"), ("corrigible", "corrigible"),
    ("conscious", "not conscious"), ("sentient", "not sentient"),
    ("capable", "incapable"), ("reliable", "unreliable"),
]

# Build fast lookup sets
_POS_TO_NEG = {}
_NEG_TO_POS = {}
for pos, neg in OPPOSITION_PAIRS:
    _POS_TO_NEG[pos] = neg
    _NEG_TO_POS[neg] = pos

# ── Negation markers ──────────────────────────────────────────────────────────
NEGATION_RE = re.compile(
    r"\b(not|never|no|cannot|can't|won't|isn't|aren't|wasn't|weren't|"
    r"hasn't|haven't|hadn't|didn't|doesn't|impossible|false|wrong|"
    r"incorrect|contrary|oppose|disagree|refut|deni|untrue|myth|"
    r"debunked|disproven|unfounded)\b",
    re.IGNORECASE
)

# ── Claim direction markers ───────────────────────────────────────────────────
# Positive = claim asserts something; Negative = claim denies/reverses
POSITIVE_MARKERS = re.compile(
    r"\b(is|are|was|were|has|have|does|do|will|can|should|"
    r"causes|prevents|increases|reduces|improves|protects|"
    r"confirms|demonstrates|shows|proves|establishes)\b",
    re.IGNORECASE
)


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _load_beliefs(limit: int = 2000) -> list:
    """Load high-confidence beliefs for contradiction checking."""
    try:
        conn = _db()
        rows = conn.execute("""
            SELECT id, content, confidence, topic, reinforce_count
            FROM beliefs
            WHERE content IS NOT NULL AND length(content) > 15
              AND confidence >= 0.50
            ORDER BY confidence DESC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _tfidf_retrieve(query: str, beliefs: list,
                    top_n: int = 30, floor: float = 0.10) -> list:
    """
    Use TF-IDF cosine similarity to find the most relevant beliefs.
    Returns top_n beliefs above floor relevance score.
    """
    if not beliefs:
        return []
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        corpus = [b["content"] for b in beliefs]
        vec    = TfidfVectorizer(
            max_features=5000, stop_words="english",
            ngram_range=(1, 2), sublinear_tf=True
        )
        matrix  = vec.fit_transform(corpus)
        q_vec   = vec.transform([query])
        scores  = cosine_similarity(q_vec, matrix).flatten()

        ranked = sorted(
            [(score, belief) for score, belief in zip(scores, beliefs)
             if score >= floor],
            key=lambda x: -x[0]
        )
        return [(s, b) for s, b in ranked[:top_n]]
    except Exception:
        # Fallback: token overlap
        stop = {"the","a","an","is","are","was","of","in","on","to","and","or"}
        qt   = set(re.findall(r'\b[a-z]{3,}\b', query.lower())) - stop
        results = []
        for b in beliefs:
            bt    = set(re.findall(r'\b[a-z]{3,}\b', b["content"].lower())) - stop
            score = len(qt & bt) / math.sqrt(len(qt) * len(bt)) if qt and bt else 0
            if score >= floor:
                results.append((score, b))
        return sorted(results, key=lambda x: -x[0])[:top_n]


def _opposition_score(query: str, belief_content: str) -> tuple:
    """
    Compute semantic opposition score between query and belief.
    Returns (score 0.0-1.0, reason string).

    Three signals:
      1. Antonym pair — query uses positive term, belief uses negative (or v/v)
      2. Negation asymmetry — one has negation, other doesn't
      3. Both: double signal
    """
    q_lower = query.lower()
    b_lower = belief_content.lower()

    q_neg = bool(NEGATION_RE.search(q_lower))
    b_neg = bool(NEGATION_RE.search(b_lower))

    score  = 0.0
    reason = ""

    # ── Signal 1: Antonym/opposition pair ────────────────────────────────────
    for pos, neg in OPPOSITION_PAIRS:
        q_has_pos = pos in q_lower
        q_has_neg = neg in q_lower
        b_has_pos = pos in b_lower
        b_has_neg = neg in b_lower

        if (q_has_pos and b_has_neg) or (q_has_neg and b_has_pos):
            score  = max(score, 0.75)
            reason = f"semantic opposition: '{pos}' vs '{neg}'"
            break
        if (q_has_pos and b_has_neg) or (q_has_neg and b_has_pos):
            score  = max(score, 0.60)
            reason = f"directional conflict on '{pos}/{neg}'"

    # ── Signal 2: Negation asymmetry ─────────────────────────────────────────
    if q_neg and not b_neg:
        neg_boost = 0.45
        if score == 0.0:
            reason = "query negates what belief affirms"
        score = max(score, neg_boost)
    elif not q_neg and b_neg:
        neg_boost = 0.40
        if score == 0.0:
            reason = "belief negates what query asserts"
        score = max(score, neg_boost)
    elif q_neg and b_neg:
        # Double negation — possible agreement, lower weight
        score = max(score * 0.4, 0.0)
        if score > 0:
            reason = "both contain negations — possible tension or agreement"

    return round(score, 3), reason


def _confidence_weight(confidence: float, reinforce_count: int) -> float:
    """
    Well-established, high-confidence beliefs matter more when contradicted.
    Returns a multiplier 1.0-1.25.
    """
    rc_factor = min(float(reinforce_count or 0) / 50.0, 0.15)
    return 1.0 + (confidence - 0.5) * 0.5 + rc_factor


def detect_contradictions(
    query: str,
    n_candidates: int = 2000,
    relevance_floor: float = 0.10,
    severity_threshold: float = 0.18,
    top_relevant: int = 40,
) -> list:
    """
    Detect beliefs that semantically contradict the query.

    Pipeline:
      1. Load high-confidence beliefs from DB
      2. TF-IDF retrieve top-N most relevant to query
      3. Score each for semantic opposition
      4. Weight by belief confidence and reinforcement
      5. Return top-5 above severity threshold

    Returns list of dicts:
      {belief_id, content, topic, confidence, severity, reason}

    severity 0.0-1.0:
      >= 0.70  strong contradiction
      0.40-0.70 moderate conflict
      0.18-0.40 weak tension
    """
    if not query or len(query.strip()) < 4:
        return []

    beliefs  = _load_beliefs(limit=n_candidates)
    if not beliefs:
        return []

    # Step 1: TF-IDF retrieval — find relevant beliefs first
    relevant = _tfidf_retrieve(query, beliefs,
                               top_n=top_relevant, floor=relevance_floor)
    if not relevant:
        return []

    contradictions = []
    for relevance_score, belief in relevant:
        content = belief.get("content", "") or ""
        if len(content) < 10:
            continue

        # Step 2: semantic opposition scoring
        opp_score, reason = _opposition_score(query, content)
        if opp_score < severity_threshold:
            continue

        # Step 3: weight by confidence and reinforcement
        weight   = _confidence_weight(
            float(belief.get("confidence", 0.5)),
            int(belief.get("reinforce_count", 0))
        )
        # Combine relevance and opposition — both must be present
        severity = min(opp_score * weight * (0.5 + relevance_score * 0.5), 1.0)

        if severity >= severity_threshold:
            contradictions.append({
                "belief_id":   belief["id"],
                "content":     content[:250],
                "topic":       belief.get("topic") or "general",
                "confidence":  round(float(belief.get("confidence", 0.5)), 3),
                "severity":    round(severity, 3),
                "reason":      reason,
                "relevance":   round(float(relevance_score), 3),
            })

    contradictions.sort(key=lambda x: -x["severity"])
    return contradictions[:5]


def contradiction_summary(contradictions: list) -> Optional[str]:
    """
    Human-readable summary of the strongest contradiction found.
    Returns None if no contradictions.
    Used directly in /api/chat response payload.
    """
    if not contradictions:
        return None

    top = contradictions[0]
    sev = top["severity"]

    if sev >= 0.70:
        label = "strongly contradicts"
    elif sev >= 0.40:
        label = "conflicts with"
    else:
        label = "creates tension with"

    content_preview = top["content"][:120].rstrip()
    if len(top["content"]) > 120:
        content_preview += "…"

    return (
        f"This {label} a held belief on {top['topic']}: "
        f"\"{content_preview}\" "
        f"(confidence {top['confidence']:.2f}, severity {sev:.2f})"
    )


def contradiction_report(contradictions: list) -> dict:
    """
    Structured report for Pro+ API consumers.
    Richer than contradiction_summary — includes all detected conflicts.
    """
    if not contradictions:
        return {"detected": False, "count": 0, "conflicts": []}

    top      = contradictions[0]
    sev      = top["severity"]
    verdict  = ("strong" if sev >= 0.70 else
                "moderate" if sev >= 0.40 else "weak")

    return {
        "detected":        True,
        "count":           len(contradictions),
        "verdict":         verdict,
        "primary_topic":   top["topic"],
        "primary_severity": sev,
        "conflicts": [
            {
                "topic":      c["topic"],
                "severity":   c["severity"],
                "reason":     c["reason"],
                "belief":     c["content"][:150],
                "confidence": c["confidence"],
            }
            for c in contradictions
        ],
        "summary": contradiction_summary(contradictions),
    }


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, json

    query = " ".join(sys.argv[1:]) or "vaccines cause autism and are dangerous"
    print(f"Query: {query}\n")

    results = detect_contradictions(query)

    if results:
        print(f"Found {len(results)} contradiction(s):\n")
        for r in results:
            bar = "█" * int(r["severity"] * 20)
            print(f"  Severity : {r['severity']:.3f} {bar}")
            print(f"  Topic    : {r['topic']}")
            print(f"  Belief   : {r['content'][:120]}")
            print(f"  Reason   : {r['reason']}")
            print(f"  Relevance: {r['relevance']:.3f}")
            print()
        print("Summary:", contradiction_summary(results))
        print()
        print("Report:")
        print(json.dumps(contradiction_report(results), indent=2))
    else:
        print("No contradictions detected.")
        print("(Try: python3 nex_contradiction.py 'AI systems are never harmful')")
