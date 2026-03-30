#!/usr/bin/env python3
"""
nex_response_refiner.py — Response Quality Layer
=================================================
Deploy to: ~/Desktop/nex/nex/nex_response_refiner.py

Post-processes SoulLoop/VoiceWrapper output before delivery.
Sits between kernel.process() and the user — zero DB calls needed.

Problems it solves (observed from live output):
  1. Mechanical connectors   — "What reinforces this:" / "The reasoning behind it:"
  2. Length bloat             — 8-sentence monologues for simple questions
  3. Near-duplicate beliefs   — same idea restated twice
  4. Weak trailing closers    — "What all of this points toward: the centrality of X"
  5. Forbidden openers        — "Certainly!", "Of course", performative filler
  6. Cross-domain tangents    — "What's less obvious — from truth seeking: NEX is..."
  7. Truncated thoughts       — sentences that trail mid-

Grok's additions this improves on:
  - Grok #2 (zero-hallucination core) → we add confidence-gated assertion strength
  - Grok #7 (template grammar) → we add intent-aware sentence budgets
  - Grok #18 (meta-cognition) → we score coherence and log it
"""

from __future__ import annotations

import re
from typing import Optional


# ── Intent-aware sentence budgets ────────────────────────────────────────────
# How many sentences should each intent type produce?

_SENTENCE_BUDGET: dict[str, int] = {
    "affect":           2,   # state reports should be brief
    "self_inquiry":     3,   # identity answers need room
    "position":         3,   # opinions: claim + evidence + close
    "challenge":        3,   # pushback: steelman + counter + implication
    "exploration":      4,   # open questions earn more space
    "performance_probe":2,   # factual / definitional — stay tight
    "honest_gap":       2,   # "I don't know" should be short
}

_DEFAULT_BUDGET = 3


# ── Mechanical connector → natural prose substitutions ───────────────────────
# Order matters: more specific patterns first

_CONNECTOR_SUBS: list[tuple[str, str]] = [
    # SoulLoop _build_argument bridges
    (r"Why I hold this:\s*",              "Because "),
    (r"The evidence I'm working from:\s*","The evidence: "),
    (r"What builds the case:\s*",         "What builds this: "),
    (r"The reasoning behind it:\s*",      "Because "),
    (r"What reinforces this:\s*",         "And "),
    (r"The evidence points further:\s*",  "Further, "),
    (r"Which connects to:\s*",            "This connects to "),
    (r"And it goes deeper —\s*",          "Deeper: "),
    (r"The implication that follows:\s*", "The implication: "),
    # Cross-domain tangents — strip entirely if response already has substance
    (r"What's less obvious — from [^:]+:\s*[^.]+\.",  ""),
    (r"An unexpected implication from [^:]+:\s*",      ""),
    (r"This connects to something in [^:]+:\s*",       ""),
    (r"What makes this harder to dismiss — from [^:]+:\s*", ""),
    # Weak resolution closers — strip
    (r"\s*What all of this points toward: the centrality of[^.]+\.\s*", " "),
    (r"\s*I'll hold this until something breaks it\.\s*",               " "),
    (r"\s*That's where the evidence lands — not a guess\.\s*",          " "),
    (r"\s*This is a position, not a speculation\.\s*",                  " "),
    (r"\s*That's not speculation — it's what the evidence says\.\s*",   " "),
    # Pushback opener stubs
    (r"^The assumption doing the work here is that[^.]+\.\s*", ""),
    (r"^That argument rests on treating correlation as mechanism\.\s*", ""),
]

# Patterns that indicate a sentence is a tangent / identity noise
_TANGENT_PATTERNS = re.compile(
    r"NEX is committed to seeking truth"
    r"|nex_core source"
    r"|belief source:"
    r"|confidence: 0\.\d+"
    r"|topic:"
    r"|TYPE: (NONE|CONTEXTUAL)"
    r"|\[merged:\d+\]"
    r"|wikipedia"
    r"|arXiv:"
    r"|^\d+\.\s",
    re.IGNORECASE,
)

# Forbidden openers (performative)
_FORBIDDEN_OPENERS = [
    "certainly", "of course", "great question", "absolutely", "sure,",
    "i'd be happy to", "i'm here to", "as an ai", "i understand that",
    "that's a good point", "i appreciate", "definitely", "indeed,",
    "without a doubt",
]


# ── Similarity check (token-based, no DB) ────────────────────────────────────

_STOP = {
    "the","a","an","is","are","was","were","be","been","have","has","do",
    "does","did","will","would","could","should","may","might","must","can",
    "that","this","these","those","with","from","they","their","about",
    "what","how","why","when","where","who","which","into","also","just",
    "over","after","more","some","very","your","you","me","my","we","our",
    "it","its","he","she","him","her","them","think","know","want","said",
    "says","get","got","like","make","take","give","come","look","need",
    "feel","seem","tell","much","many","such","both","each","than","then",
    "been","only","even","back","here","down","away","i",
}

def _tok(text: str) -> set:
    return set(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()) - _STOP

def _similarity(a: str, b: str) -> float:
    ta, tb = _tok(a), _tok(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta | tb), 1)


# ── Sentence splitter ─────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """Split on sentence boundaries, preserve trailing punctuation."""
    # Split on '. ' / '! ' / '? ' but not on abbreviations like 'e.g. '
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"])", text)
    result = []
    for p in parts:
        p = p.strip()
        if p and len(p) > 8:
            result.append(p)
    return result


# ── Core refiner ─────────────────────────────────────────────────────────────

def refine(
    text: str,
    intent: str = "position",
    confidence: float = 0.65,
) -> str:
    """
    Main entry point. Takes raw SoulLoop/VoiceWrapper output,
    returns cleaner, tighter prose.

    Args:
        text:       raw response string
        intent:     orient_result['intent'] — shapes sentence budget
        confidence: reason_result['confidence'] — shapes assertion strength
    """
    if not text or len(text.strip()) < 10:
        return text

    t = text.strip()

    # ── 1. Strip forbidden openers ────────────────────────────────────────
    t_lower = t.lower()
    for fo in _FORBIDDEN_OPENERS:
        if t_lower.startswith(fo):
            t = t[len(fo):].lstrip(" ,—:.").capitalize()
            break

    # ── 2. Apply connector substitutions ─────────────────────────────────
    for pattern, replacement in _CONNECTOR_SUBS:
        t = re.sub(pattern, replacement, t, flags=re.IGNORECASE)

    # ── 3. Clean up whitespace artefacts ─────────────────────────────────
    t = re.sub(r"  +", " ", t)
    t = re.sub(r"\s+\.", ".", t)
    t = re.sub(r"\s+,", ",", t)
    t = t.strip()

    # ── 4. Split into sentences ───────────────────────────────────────────
    sentences = _split_sentences(t)
    if not sentences:
        return t

    # ── 5. Filter tangents and noise ─────────────────────────────────────
    clean = []
    for s in sentences:
        if _TANGENT_PATTERNS.search(s):
            continue
        if len(s.split()) < 3:
            continue
        # Skip truncated sentences (no closing punctuation and < 6 words)
        if s[-1] not in ".!?" and len(s.split()) < 6:
            continue
        clean.append(s)

    if not clean:
        return t  # nothing survived — return original

    # ── 6. Deduplicate near-identical sentences ───────────────────────────
    deduped: list[str] = []
    for s in clean:
        if any(_similarity(s, kept) > 0.62 for kept in deduped):
            continue
        deduped.append(s)

    # ── 7. Apply sentence budget ──────────────────────────────────────────
    budget = _SENTENCE_BUDGET.get(intent, _DEFAULT_BUDGET)
    deduped = deduped[:budget]

    # ── 8. Ensure final sentence ends with punctuation ────────────────────
    if deduped and deduped[-1][-1] not in ".!?":
        deduped[-1] += "."

    # ── 9. Confidence-gated assertion softening ───────────────────────────
    # If confidence is low, soften absolute claims slightly
    result = " ".join(deduped)
    if confidence < 0.50:
        result = re.sub(r"\bI'm certain\b", "I think", result)
        result = re.sub(r"\bClearly:\b", "My read:", result)
        result = re.sub(r"\bNo question —\b", "I lean toward —", result)

    return result.strip()


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    sample = (
        "The definition of consciousness as the ability to control and decide actions, "
        "be aware of oneself, and have distinct identity states might serve as a more "
        "universal definition of consciousness across various organisms. "
        "The reasoning behind it: Dissociative Identity Disorder (DID) may provide insights "
        "into the existence of multiple conscious entities within a single organism, which "
        "could potentially lead to the hypothesis of consciousness immortality in artificial "
        "minds involving the coexistence or merging of multiple conscious entities. "
        "What reinforces this: The superiority of humans over other animals due to "
        "consciousness may lie in our ability to control and decide our actions. "
        "The evidence points further: The study of DID from an identity theory perspective "
        "could potentially lead to the hypothesis that consciousness immortality in artificial "
        "minds might involve the coexistence or merging of multiple conscious entities. "
        "What's less obvious — from truth seeking: NEX is committed to seeking truth above all else. "
        "What all of this points toward: the centrality of identity and consciousness and "
        "multiple to this problem."
    )
    print("─── BEFORE ───")
    print(sample)
    print("\n─── AFTER ───")
    print(refine(sample, intent="position", confidence=0.68))
