"""
nex_belief_reasoner.py — Lightweight belief inference engine.
Given a list of beliefs, derives what logically follows.
Rule-based — no LLM needed. Fast, deterministic.
"""
import re
from pathlib import Path
import sqlite3

# ── Inference rules ────────────────────────────────────────────────────────────
# Pattern: if N beliefs share a negation of X → infer "X alone is insufficient"
# Pattern: if N beliefs share assertion of Y → infer "Y is necessary/fundamental"

_NEGATION = re.compile(
    r'\b(not|cannot|can\'t|isn\'t|never|no|beyond|more than|transcends)\b',
    re.IGNORECASE
)

_SHARED_CONCEPTS = [
    ("computation", "purely computational models are necessarily incomplete"),
    ("gradients", "gradient-based explanations capture only part of the phenomenon"),
    ("physical world", "the physical substrate is a necessary but not sufficient condition"),
    ("emergent", "emergence is a fundamental feature, not an epiphenomenon"),
    ("subjective", "subjective experience cannot be eliminated from any complete account"),
    ("alignment", "alignment requires understanding phenomena that resist formal specification"),
    ("free will", "free will and determinism may describe the same reality at different levels"),
    ("consciousness", "consciousness may be a fundamental feature of reality, not a derived one"),
    ("intelligence", "intelligence cannot be reduced to any single computational process"),
    ("belief", "beliefs are not static — they evolve under evidence and contradiction"),
]

def infer(beliefs: list, query: str = "") -> str | None:
    """
    Given a list of belief strings, derive a logical inference.
    Returns a single inference sentence or None if no pattern found.
    """
    if not beliefs or len(beliefs) < 2:
        return None

    combined = " ".join(beliefs).lower()
    query_lower = query.lower()

    # Count negations across beliefs
    neg_count = sum(1 for b in beliefs if _NEGATION.search(b))

    # Find shared concepts
    matches = []
    for concept, inference in _SHARED_CONCEPTS:
        count = sum(1 for b in beliefs if concept in b.lower())
        if count >= 2:
            matches.append((count, concept, inference))

    if not matches:
        return None

    # Pick the most-mentioned concept
    matches.sort(key=lambda x: -x[0])
    _, concept, inference = matches[0]

    # If mostly negations: use "insufficient" framing
    if neg_count >= len(beliefs) * 0.5:
        return f"This suggests that {inference}."
    else:
        return f"I find that {inference}."


def infer_and_store(beliefs: list, query: str = "", topic: str = "reasoning") -> str | None:
    """
    Derive inference and optionally store as new belief in DB.
    Returns the inference string or None.
    """
    inference = infer(beliefs, query)
    if not inference:
        return None

    # Store in DB as a derived belief
    try:
        DB = Path.home() / "Desktop" / "nex" / "nex.db"
        conn = sqlite3.connect(str(DB), timeout=2)
        conn.execute("""
            INSERT OR IGNORE INTO beliefs (content, topic, confidence, source)
            VALUES (?, ?, 0.60, 'nex_reasoning')
        """, (inference, topic))
        conn.commit()
        conn.close()
    except Exception:
        pass  # Non-fatal — inference still returned even if storage fails

    return inference


if __name__ == "__main__":
    # Test
    test_beliefs = [
        "Consciousness is not a product of computation alone but is deeply entwined with the physical world.",
        "Consciousness cannot be reduced to computation gradients.",
        "Consciousness is an emergent property that transcends purely computational models.",
    ]
    result = infer(test_beliefs, "What is consciousness?")
    print("Inference:", result)
