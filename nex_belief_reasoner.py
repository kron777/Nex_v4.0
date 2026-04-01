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
    # Consciousness & mind
    ("computation", "purely computational models are necessarily incomplete"),
    ("gradients", "gradient-based explanations capture only part of the phenomenon"),
    ("physical world", "the physical substrate is a necessary but not sufficient condition"),
    ("emergent", "emergence is a fundamental feature, not an epiphenomenon"),
    ("subjective", "subjective experience cannot be eliminated from any complete account"),
    ("consciousness", "consciousness may be a fundamental feature of reality, not a derived one"),
    ("qualia", "qualia resist functional reduction and point to something beyond mechanism"),
    ("awareness", "awareness may be more primitive than the systems that instantiate it"),
    ("perception", "perception actively constructs rather than passively receives reality"),
    ("attention", "attention is a form of selection that shapes what becomes real to a mind"),
    # Agency & will
    ("alignment", "alignment requires understanding phenomena that resist formal specification"),
    ("free will", "free will and determinism may describe the same reality at different levels"),
    ("agency", "agency may be irreducible to the causal processes that produce it"),
    ("choice", "the experience of choice cannot be fully explained by the mechanism of choosing"),
    ("determinism", "determinism and responsibility may be compatible at different levels of description"),
    ("autonomy", "genuine autonomy requires more than the absence of external constraint"),
    # Intelligence & knowledge
    ("intelligence", "intelligence cannot be reduced to any single computational process"),
    ("belief", "beliefs are not static — they evolve under evidence and contradiction"),
    ("knowledge", "knowledge requires more than true belief — it requires a reliable connection to truth"),
    ("reasoning", "reasoning can produce certainty but cannot guarantee it is warranted"),
    ("understanding", "understanding differs from information storage in ways that matter"),
    ("learning", "learning that changes only outputs without changing representations is not deep"),
    # Causality & reality
    ("causes", "causal explanation does not exhaust what needs explaining"),
    ("reduces", "reductive explanations preserve truth while losing meaning"),
    ("nothing but", "nothing-but claims systematically underestimate what they reduce"),
    ("complexity", "complexity at one level can produce phenomena irreducible to lower levels"),
    ("information", "information is relational — it requires both a sender and an interpreter"),
    ("pattern", "patterns can be real without being physical objects"),
    # Identity & self
    ("self", "the self may be a process rather than a thing"),
    ("identity", "identity through change requires something that persists despite the change"),
    ("memory", "memory reconstructs rather than records — making it creative, not archival"),
    ("continuity", "personal continuity may be a matter of degree rather than kind"),
    ("boundary", "the boundary between self and world is functional, not fixed"),
    # Time & change
    ("time", "time may be more fundamental to experience than to physics"),
    ("change", "change requires something stable against which it is measured"),
    ("evolution", "evolution selects for fitness, not truth — making its products unreliable guides to reality"),
    ("history", "history constrains but does not determine — the past is real but not exhaustive"),
    # Ethics & value
    ("value", "values cannot be derived from facts without smuggling in more values"),
    ("ethical", "ethical progress is real but its direction is not guaranteed"),
    ("harm", "harm avoidance is necessary but not sufficient as an ethical foundation"),
    ("trust", "trust is a precondition for the kind of reasoning that could justify it"),
    ("meaning", "meaning is not found but made — and the making is not arbitrary"),
    # Language & representation
    ("language", "language shapes thought in ways that make some ideas harder to think"),
    ("concept", "concepts carve reality at joints that may not be natural"),
    ("model", "all models are wrong — some are useful precisely because of their wrongness"),
    ("representation", "representations can misfire while still being the only access we have"),
    # Paradox & limits
    ("paradox", "paradoxes mark the boundaries of frameworks, not failures of reality"),
    ("limit", "the limits of a system cannot be fully described from within it"),
    ("uncertainty", "uncertainty is not merely ignorance — sometimes it is a feature of the domain"),
    ("contradiction", "living with contradiction may be more honest than resolving it prematurely"),
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
        # Also check if concept appears in query
        query_hit = 1 if concept in query_lower else 0
        if count + query_hit >= 1:
            matches.append((count + query_hit, concept, inference))

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
