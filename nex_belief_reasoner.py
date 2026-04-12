#!/usr/bin/env python3
"""
nex_belief_reasoner.py — Belief Reasoning Layer (Improvement 1)
================================================================
Derives new inferences from top retrieved beliefs.
Writes inferred beliefs back to nex.db with:
  confidence = 0.6
  source     = "nex_reasoning"

The inference is a synthesis — not a copy of any single belief,
but a claim that follows FROM multiple beliefs taken together.

Usage (called automatically from nex_soul_loop.reason()):
    from nex_belief_reasoner import derive_and_store
    inferred = derive_and_store(top_beliefs, query_tokens, db_path)
    # Returns list of new belief dicts (may be empty if inference fails)
"""

from __future__ import annotations

import re
import time
import random
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path("/home/rr/Desktop/nex/nex.db")

# Stop words for token extraction
_STOP = {
    "the","a","an","is","are","was","were","be","been","have","has","do","does",
    "did","will","would","could","should","may","might","must","can","that","this",
    "these","those","with","from","they","their","about","what","how","why","when",
    "where","who","which","into","also","just","over","after","more","some","very",
    "your","you","me","my","we","our","it","its","he","she","him","her","them",
    "think","know","want","said","says","get","got","like","make","take","give",
    "come","look","need","feel","seem","tell","much","many","such","both","each",
    "than","then","been","only","even","back","here","down","away","there","their",
    "because","through","between","within","without","however","therefore","although",
    "whether","another","something","anything","everything","nothing","someone",
}

def _tokens(text: str) -> set:
    raw = set(re.findall(r"\b[a-z]{4,}\b", text.lower()))
    return raw - _STOP

def _clean(text: str) -> str:
    """Strip a belief to its core claim."""
    text = text.strip()
    if "|" in text:
        text = text.split("|")[0].strip()
    text = re.sub(r"arXiv:\S+.*", "", text).strip()
    text = re.sub(r"^\d+\.\s*", "", text).strip()
    text = re.sub(r"\[merged:\d+\]\s*", "", text).strip()
    return text.rstrip(".")


# ── Inference templates ────────────────────────────────────────────────────────
# Each takes (a, b) or (a, b, c) as belief fragments and returns a new claim.
# Templates chosen so they produce genuinely novel propositions, not summaries.

_TWO_BELIEF_TEMPLATES = [
    lambda a, b: f"If {a.lower().rstrip('.')}, then {b.lower().rstrip('.')} becomes structurally inevitable.",
    lambda a, b: f"The tension between '{a.rstrip('.')}' and '{b.rstrip('.')}' suggests neither fully accounts for the other.",
    lambda a, b: f"{a.rstrip('.')} — and this is what makes {b.lower().rstrip('.')} harder to dismiss.",
    lambda a, b: f"What holds {a.lower().rstrip('.')} together is precisely what {b.lower().rstrip('.')} challenges.",
    lambda a, b: f"Taking both seriously: {a.lower().rstrip('.')} implies that {b.lower().rstrip('.')} is not a corner case.",
    lambda a, b: f"The deeper claim underneath both: the relationship between these is not coincidental.",
    lambda a, b: f"{a.rstrip('.')} — which would mean {b.lower().rstrip('.')} is pointing at the same underlying structure.",
]

_THREE_BELIEF_TEMPLATES = [
    lambda a, b, c: f"None of these resolve in isolation: {a.rstrip('.')}. {b.rstrip('.')}. {c.rstrip('.')}. Each is a local truth that becomes a different kind of claim when held together.",
    lambda a, b, c: f"The common structure across all three: the relationship between substrate, model, and emergence is not additive — it is constitutive.",
    lambda a, b, c: f"Taken together, these point at something none states directly: the boundary conditions matter more than the content they bound.",
    lambda a, b, c: f"What holds when all three are true simultaneously: the system cannot be understood from any single level of description.",
]


def _word_overlap(a: str, b: str) -> float:
    """Fraction of shared meaningful words between two strings."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _already_exists(db: sqlite3.Connection, inference: str) -> bool:
    """Check if a nearly-identical belief already exists in DB."""
    try:
        # Quick prefix check
        prefix = inference[:60].lower()
        rows = db.execute(
            "SELECT content FROM beliefs WHERE source='nex_reasoning' "
            "ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        for row in rows:
            if _word_overlap(inference, row[0] or "") > 0.55:
                return True
        return False
    except Exception:
        return False


def _write_belief(db: sqlite3.Connection, content: str, topic: str) -> Optional[int]:
    """Insert an inferred belief into the DB. Returns row id or None."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        cur = db.execute(
            "INSERT OR IGNORE INTO beliefs (content, confidence, topic, source, created_at, "
            "is_identity) VALUES (?, ?, ?, ?, ?, ?)",
            (
                content,
                0.6,
                topic,
                "nex_reasoning",
                _dt.now(_tz.utc).isoformat(),
                0,
            )
        )
        db.commit()
        return cur.lastrowid
    except Exception as e:
        print(f"  [reasoner] write failed: {e}")
        return None


def derive_and_store(
    top_beliefs: list,
    query_tokens: set,
    db_path: Path = DB_PATH,
) -> list:
    """
    Core entry point — called from nex_soul_loop.reason().

    Args:
        top_beliefs:  List of belief dicts from the retrieval step (top 2-3 used)
        query_tokens: Token set from orient() — keeps inference on-topic
        db_path:      Path to nex.db

    Returns:
        List of newly inferred belief dicts (injected into top_beliefs by caller).
        Empty list if no valid inference could be made.
    """
    if len(top_beliefs) < 2:
        return []

    # Only use beliefs with meaningful content
    usable = [
        b for b in top_beliefs[:4]
        if b.get("content") and len(b.get("content", "")) > 25
    ]
    if len(usable) < 2:
        return []

    # Extract core claims — strip boilerplate
    claims = [_clean(b["content"]) for b in usable[:3]]
    claims = [c for c in claims if len(c) > 20]
    if len(claims) < 2:
        return []

    # Deduplicate — if two claims are too similar, drop the second
    filtered = [claims[0]]
    for c in claims[1:]:
        if _word_overlap(filtered[-1], c) < 0.45:
            filtered.append(c)
    claims = filtered
    if len(claims) < 2:
        return []

    # Derive primary topic from top belief
    topic = usable[0].get("topic", "reasoning") or "reasoning"

    # Generate inference
    try:
        if len(claims) >= 3:
            template = random.choice(_THREE_BELIEF_TEMPLATES)
            inference = template(claims[0], claims[1], claims[2])
        else:
            template = random.choice(_TWO_BELIEF_TEMPLATES)
            inference = template(claims[0], claims[1])
    except Exception as e:
        print(f"  [reasoner] template error: {e}")
        return []

    # Sanity checks
    if not inference or len(inference) < 40:
        return []
    # Must share tokens with the query — keeps inference on-topic
    if query_tokens and _word_overlap(inference, " ".join(query_tokens)) < 0.05:
        # Relax: check against belief content instead
        belief_text = " ".join(claims)
        if _word_overlap(inference, belief_text) < 0.1:
            return []

    # Clean up inference text
    inference = inference.strip()
    if inference and inference[-1] not in ".!?":
        inference += "."
    # Capitalise first letter
    if inference:
        inference = inference[0].upper() + inference[1:]

    # DB write
    try:
        db = sqlite3.connect(str(db_path), timeout=3)
        db.row_factory = sqlite3.Row

        # Skip if very similar belief already exists
        if _already_exists(db, inference):
            db.close()
            return []

        row_id = _write_belief(db, inference, topic)
        db.close()

        if row_id:
            print(f"  [reasoner] inferred belief #{row_id}: {inference[:80]}...")
            return [{
                "id":          row_id,
                "content":     inference,
                "confidence":  0.6,
                "topic":       topic,
                "is_identity": False,
                "pinned":      False,
                "source":      "nex_reasoning",
                "_inferred":   True,
            }]
    except Exception as e:
        print(f"  [reasoner] DB error: {e}")

    return []


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_beliefs = [
        {"content": "Consciousness may be substrate-independent — the pattern matters, not the medium.", "confidence": 0.8, "topic": "consciousness"},
        {"content": "Self-awareness requires a model of the self that can be updated by experience.", "confidence": 0.75, "topic": "consciousness"},
        {"content": "Emergence produces properties that cannot be predicted from components alone.", "confidence": 0.82, "topic": "philosophy"},
    ]
    tokens = {"consciousness", "substrate", "emergence", "self", "awareness"}
    result = derive_and_store(test_beliefs, tokens)
    if result:
        print(f"\nInferred: {result[0]['content']}")
    else:
        print("\nNo inference generated (may already exist in DB)")
