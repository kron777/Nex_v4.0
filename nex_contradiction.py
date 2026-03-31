#!/usr/bin/env python3
"""
nex_contradiction.py — Belief Contradiction Detector
=====================================================
Detects when a query or statement conflicts with held beliefs.

Core logic:
  1. Retrieve top beliefs relevant to the query via TF-IDF cosine
  2. For each belief, check if the query semantically negates it
     using negation keyword patterns + cosine opposition scoring
  3. Return a list of detected contradictions with severity scores

Used by:
  - /api/chat response to flag epistemic conflicts
  - nex_reason.py for pushback strategy selection
"""

import re
import sqlite3
import math
from pathlib import Path
from typing import Optional

DB_PATH = Path("~/.config/nex/nex.db").expanduser()

# ── Negation patterns ─────────────────────────────────────────────────────────
NEGATION_PATTERNS = [
    r"\bnot\b", r"\bnever\b", r"\bno\b", r"\bcannot\b", r"\bcan't\b",
    r"\bwon't\b", r"\bisn't\b", r"\baren't\b", r"\bwasn't\b", r"\bweren't\b",
    r"\bhasn't\b", r"\bhaven't\b", r"\bhadn't\b", r"\bdidn't\b", r"\bdoesn't\b",
    r"\bimpossible\b", r"\bfalse\b", r"\bwrong\b", r"\bincorrect\b",
    r"\bcontrary\b", r"\boppos\b", r"\bdisagree\b", r"\brefut\b",
    r"\bdenies\b", r"\bdenied\b", r"\buntrue\b", r"\bmyth\b",
]

NEGATION_RE = re.compile("|".join(NEGATION_PATTERNS), re.IGNORECASE)


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _has_negation(text: str) -> bool:
    return bool(NEGATION_RE.search(text))


def _token_overlap(a: str, b: str) -> float:
    """Simple token overlap score between two strings."""
    stop = {"the","a","an","is","are","was","were","be","been","being",
            "have","has","had","do","does","did","will","would","could",
            "should","may","might","can","of","in","on","at","to","for",
            "and","or","but","not","with","by","from","as","that","this",
            "it","its","they","them","their","we","our","you","your"}
    ta = set(re.findall(r'\b[a-z]{3,}\b', a.lower())) - stop
    tb = set(re.findall(r'\b[a-z]{3,}\b', b.lower())) - stop
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / math.sqrt(len(ta) * len(tb))


def _tfidf_cosine(query: str, beliefs: list) -> list:
    """Return cosine similarity scores for query against beliefs."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        corpus = [b["content"] for b in beliefs]
        vec = TfidfVectorizer(max_features=3000, stop_words="english", ngram_range=(1,2))
        matrix = vec.fit_transform(corpus)
        q_vec = vec.transform([query])
        scores = cosine_similarity(q_vec, matrix).flatten()
        return list(scores)
    except Exception:
        # Fallback to token overlap
        return [_token_overlap(query, b["content"]) for b in beliefs]


def detect_contradictions(
    query: str,
    n_candidates: int = 50,
    relevance_threshold: float = 0.15,
    severity_threshold: float = 0.20,
) -> list:
    """
    Detect beliefs that contradict the query.

    Returns list of dicts:
      {belief_id, content, topic, confidence, severity, reason}

    severity 0.0-1.0:
      > 0.7 = strong contradiction
      0.4-0.7 = moderate
      0.2-0.4 = weak / possible tension
    """
    if not query or len(query.strip()) < 5:
        return []

    query_has_negation = _has_negation(query)

    try:
        conn = _db()
        rows = conn.execute("""
            SELECT id, content, confidence, topic, reinforce_count
            FROM beliefs
            WHERE content IS NOT NULL AND length(content) > 15
              AND confidence >= 0.55
            ORDER BY confidence DESC
            LIMIT ?
        """, (n_candidates,)).fetchall()
        conn.close()
    except Exception as e:
        return []

    if not rows:
        return []

    beliefs = [dict(r) for r in rows]
    scores  = _tfidf_cosine(query, beliefs)

    contradictions = []
    for belief, score in zip(beliefs, scores):
        if score < relevance_threshold:
            continue

        content = belief["content"] or ""
        belief_has_negation = _has_negation(content)

        # Contradiction signal: query negates belief OR belief negates query
        # when both are about the same topic (high cosine relevance)
        contradiction_signal = 0.0
        reason = ""

        if query_has_negation and not belief_has_negation:
            # Query asserts something false about what belief holds true
            contradiction_signal = score * 0.85
            reason = "query negates held belief"
        elif not query_has_negation and belief_has_negation:
            # Query asserts something that belief explicitly denies
            contradiction_signal = score * 0.75
            reason = "held belief negates query assertion"
        elif query_has_negation and belief_has_negation:
            # Both have negations — possible double negative = agreement
            # Lower weight, flag as tension rather than contradiction
            contradiction_signal = score * 0.30
            reason = "both contain negations — possible tension"

        # Boost signal if reinforce_count is high (well-established belief)
        rc_boost = min(float(belief["reinforce_count"] or 0) / 50.0, 0.15)
        contradiction_signal = min(contradiction_signal + rc_boost, 1.0)

        if contradiction_signal >= severity_threshold:
            contradictions.append({
                "belief_id":  belief["id"],
                "content":    content[:200],
                "topic":      belief["topic"] or "general",
                "confidence": belief["confidence"],
                "severity":   round(contradiction_signal, 3),
                "reason":     reason,
            })

    contradictions.sort(key=lambda x: -x["severity"])
    return contradictions[:5]   # top 5 most severe


def contradiction_summary(contradictions: list) -> Optional[str]:
    """
    Return a human-readable summary string if contradictions exist.
    Returns None if list is empty.
    """
    if not contradictions:
        return None
    top = contradictions[0]
    severity_label = (
        "strongly contradicts" if top["severity"] >= 0.7 else
        "conflicts with"       if top["severity"] >= 0.4 else
        "creates tension with"
    )
    return (
        f"This {severity_label} a held belief on {top['topic']}: "
        f"\"{top['content'][:100]}\" (confidence {top['confidence']:.2f})"
    )


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import json
    query = " ".join(sys.argv[1:]) or "AI systems cannot be corrigible"
    print(f"Query: {query}\n")
    results = detect_contradictions(query)
    if results:
        print(f"Found {len(results)} contradiction(s):\n")
        for r in results:
            print(f"  Severity: {r['severity']:.3f} | Topic: {r['topic']}")
            print(f"  Belief:   {r['content'][:100]}")
            print(f"  Reason:   {r['reason']}\n")
        print("Summary:", contradiction_summary(results))
    else:
        print("No contradictions detected.")
