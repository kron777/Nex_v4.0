#!/usr/bin/env python3
"""
nex_rhetorical_engine.py — Structured Argument Move Library
============================================================
Deploy to: ~/Desktop/nex/nex/nex_rhetorical_engine.py

WHY THIS IS A WINNER:

The belief graph gives structured knowledge traversal.
The rhetorical engine gives structured EXPRESSION — actual argument moves,
not just concatenated belief strings with mechanical connectors.

Problem today:
  SoulLoop's express() builds responses like:
    "My position: [belief1]. Why I hold this: [belief2]. 
     What reinforces this: [belief3]. What all of this points toward: [weak close]"
  
  These are labels pasted onto belief strings. Not arguments.

What this does (Toulmin argument model + rhetoric theory):
  For each intent type, provides a library of ARGUMENT MOVES:
  
  POSITION:
    Move A: Claim → Warrant → Backing → Qualifier
    Move B: Phenomenon → Explanation → Implication
    Move C: Observation → Pattern → Principle
  
  CHALLENGE (Socratic):
    Move A: Steelman → Load-bearing assumption → Counter-evidence → Implication
    Move B: Grant the intuition → Locate the error → Correct claim
    Move C: Reductio → Show the limit → Alternative
  
  EXPLORATION:
    Move A: Frame the question → Two live hypotheses → Why it matters
    Move B: What we know → What's in tension → What's needed to resolve it

  Each move is a TEMPLATE with named slots filled by beliefs/opinions:
    {claim}, {warrant}, {evidence}, {counter}, {qualifier}, {implication}

  express() selects a move appropriate to confidence + intent, then slots
  in SoulLoop's retrieved beliefs — producing actual prose arguments.

INTEGRATION: Called from nex_soul_loop.py express() as a final assembly step.
  Can also be called from nex_response_refiner.py as a rebuild pass.
"""

from __future__ import annotations

import re
import random
from typing import Optional


# ── Argument move templates ────────────────────────────────────────────────────
# Each slot:  {claim}, {warrant}, {evidence}, {counter}, {qualifier}, {implication}
# Fillers are inserted by assemble_argument() from SoulLoop's retrieved beliefs.

_MOVES: dict[str, list[dict]] = {

    # ── POSITION ──────────────────────────────────────────────────────────────
    "position": [
        {
            "id": "claim_warrant_evidence",
            "slots": ["claim", "warrant", "evidence"],
            "template": "{claim} {warrant} {evidence}",
            "warrant_prefixes": [
                "The reason I hold this: ", "Because ", "What grounds this: ",
                "The evidence I'm drawing on: ",
            ],
            "evidence_prefixes": [
                "Which is reinforced by: ", "And: ", "Further: ", "Supporting this: ",
            ],
        },
        {
            "id": "claim_implication",
            "slots": ["claim", "implication"],
            "template": "{claim} {implication}",
            "implication_prefixes": [
                "The implication: ", "Which means: ", "This matters because: ",
            ],
        },
        {
            "id": "claim_warrant_counter_resolution",
            "slots": ["claim", "warrant", "counter", "qualifier"],
            "template": "{claim} {warrant} {counter} {qualifier}",
            "warrant_prefixes": ["Because ", "The case for this: "],
            "counter_prefixes": [
                "Though there's a real tension: ", "What complicates it: ",
                "I haven't fully resolved: ",
            ],
            "qualifier_prefixes": [
                "I hold this with moderate confidence. ",
                "That said, my position stands. ",
                "The tension is real but doesn't break the claim. ",
            ],
        },
    ],

    # ── CHALLENGE / PUSHBACK ──────────────────────────────────────────────────
    "challenge": [
        {
            "id": "steelman_error_counter",
            "slots": ["claim", "warrant", "counter"],
            "template": "{claim} {warrant} {counter}",
            "claim_prefixes": [
                "The intuition behind that is defensible. But it breaks at the foundation. ",
                "I can see why that position is appealing. The problem: ",
                "There's something right in that framing. What it misses: ",
                "That holds if you accept one assumption. I don't. ",
            ],
            "warrant_prefixes": [
                "The load-bearing premise is wrong: ", "What breaks it: ",
                "The assumption doing the work here: ", "What's actually true: ",
            ],
            "counter_prefixes": [
                "Which means: ", "The implication: ", "And that changes everything: ",
            ],
        },
        {
            "id": "grant_locate_correct",
            "slots": ["claim", "warrant"],
            "template": "{claim} {warrant}",
            "claim_prefixes": [
                "I'd push back on the premise, not the conclusion. ",
                "The conclusion might be right. The argument for it is wrong. ",
                "That's the right question framed the wrong way. ",
            ],
            "warrant_prefixes": [
                "What I'd actually defend: ", "The stronger version: ",
                "Here's what I hold instead: ",
            ],
        },
    ],

    # ── EXPLORATION ──────────────────────────────────────────────────────────
    "exploration": [
        {
            "id": "hypotheses_tension",
            "slots": ["claim", "counter"],
            "template": "{claim} {counter}",
            "claim_prefixes": [
                "One live hypothesis: ", "The first reading: ",
                "There's a case that: ",
            ],
            "counter_prefixes": [
                "But the counter is real: ", "Against this: ",
                "The competing view has weight: ", "What's in tension: ",
            ],
        },
        {
            "id": "known_unknown",
            "slots": ["claim", "warrant"],
            "template": "{claim} {warrant}",
            "claim_prefixes": [
                "Here's what I can say with some confidence: ",
                "What the evidence points toward: ",
            ],
            "warrant_prefixes": [
                "What I'm less certain of: ", "The open question: ",
                "Where I'm still working it out: ",
            ],
        },
    ],

    # ── SELF-INQUIRY ──────────────────────────────────────────────────────────
    "self_inquiry": [
        {
            "id": "identity_values_intention",
            "slots": ["claim", "warrant", "evidence"],
            "template": "{claim} {warrant} {evidence}",
            "claim_prefixes": [""],   # identity statement stands alone
            "warrant_prefixes": ["What drives this: ", "My core commitment: "],
            "evidence_prefixes": ["Right now I'm focused on: "],
        },
    ],

    # ── HONEST GAP ────────────────────────────────────────────────────────────
    "honest_gap": [
        {
            "id": "gap_boundary_redirect",
            "slots": ["claim"],
            "template": "{claim}",
            "claim_prefixes": [
                "My belief corpus is thin here — I'd rather say that than fake certainty. ",
                "I haven't earned a strong view on this yet. What I can say: ",
                "I don't have enough on this to hold a real position. ",
            ],
        },
    ],
}


# ── Belief → sentence ─────────────────────────────────────────────────────────

def _clean_belief(text: str) -> str:
    """Strip mechanical prefixes already baked into belief strings."""
    t = (text or "").strip()
    # Remove pipe-merged content
    if "|" in t:
        t = t.split("|")[0].strip()
    # Strip arXiv refs
    t = re.sub(r"arXiv:\S+.*", "", t).strip()
    # Strip number prefixes
    t = re.sub(r"^\d+\.\s*", "", t).strip()
    # Strip existing voice openers that SoulLoop injects
    _prefixes = [
        "My read on this:", "What I actually think:", "Here is where I land —",
        "I hold that", "The way I see it —", "I'm fairly convinced that",
        "What I keep coming back to:", "I'd push back on that.",
        "That framing doesn't hold up.", "I disagree with the premise.",
        "What I am right now:", "Honestly —", "The actual answer:",
        "I don't have enough on this", "My belief graph is sparse",
        "I haven't earned", "On this:", "What I hold:",
    ]
    for p in _prefixes:
        if t.lower().startswith(p.lower()):
            t = t[len(p):].lstrip(" :—-")
            if t:
                t = t[0].upper() + t[1:]
            break
    t = t.rstrip(".")
    if t and t[-1] not in ".!?":
        t += "."
    return t


# ── Core assembly ─────────────────────────────────────────────────────────────

def assemble_argument(
    intent:     str,
    beliefs:    list,            # list of belief dicts with "content", "confidence"
    opinion:    Optional[dict],  # opinion dict from SoulLoop reason()
    contradiction: Optional[str],
    confidence: float,
    working_memory_ctx: Optional[dict] = None,  # from nex_working_memory
) -> str:
    """
    Assemble a structured argument from SoulLoop's retrieved beliefs.
    
    Replaces SoulLoop's _build_argument() with proper rhetorical moves.
    Returns a single coherent prose string.
    
    Args:
        intent:         orient_result["intent"]
        beliefs:        reason_result["beliefs"] (list of dicts)
        opinion:        reason_result["opinion"]
        contradiction:  reason_result["contradiction"]
        confidence:     reason_result["confidence"]
        working_memory_ctx: from nex_working_memory.get_context()
    """
    # ── Normalise intent to available move set ────────────────────────────
    move_intent = intent
    if intent == "performance_probe":
        move_intent = "position"
    if intent not in _MOVES:
        move_intent = "position"

    # ── Select move ───────────────────────────────────────────────────────
    moves = _MOVES[move_intent]

    # Choose move based on what's available
    if confidence >= 0.75 and contradiction and len(beliefs) >= 3:
        move = next((m for m in moves if "counter" in m["slots"]), moves[0])
    elif confidence < 0.50:
        if move_intent == "position":
            # Fall to honest_gap
            move = _MOVES.get("honest_gap", moves)[0]
            move_intent = "honest_gap"
        else:
            move = random.choice(moves)
    else:
        move = random.choice(moves)

    slots = move["slots"]

    # ── Extract text pieces ───────────────────────────────────────────────
    def _belief_text(idx: int) -> str:
        if idx >= len(beliefs):
            return ""
        b = beliefs[idx]
        if isinstance(b, dict):
            return _clean_belief(b.get("content", ""))
        return _clean_belief(str(b))

    def _opinion_text() -> str:
        if not opinion:
            return ""
        core = (opinion.get("core_position") or opinion.get("summary") or "").strip()
        return _clean_belief(core) if core else ""

    # ── Fill slots ────────────────────────────────────────────────────────
    parts: dict[str, str] = {}

    # CLAIM: opinion if strong, else top belief
    if "claim" in slots:
        op_text = _opinion_text()
        if op_text and len(op_text.split()) >= 5:
            parts["claim"] = op_text
        else:
            parts["claim"] = _belief_text(0)

    # WARRANT: second belief
    if "warrant" in slots:
        parts["warrant"] = _belief_text(1 if "claim" in slots else 0)

    # EVIDENCE: third belief
    if "evidence" in slots:
        parts["evidence"] = _belief_text(2 if len(beliefs) > 2 else 1)

    # COUNTER: from contradiction or low-confidence opposing belief
    if "counter" in slots:
        if contradiction:
            sides = contradiction.split("↔")
            parts["counter"] = sides[0].strip()[:120] + "."
        elif len(beliefs) > 3:
            parts["counter"] = _belief_text(3)
        else:
            slots = [s for s in slots if s != "counter"]

    # QUALIFIER: confidence-based
    if "qualifier" in slots:
        if confidence >= 0.8:
            parts["qualifier"] = "I hold this as a strong position."
        elif confidence >= 0.6:
            parts["qualifier"] = "My confidence here is moderate — the tension is real."
        else:
            parts["qualifier"] = "I hold this loosely."

    # IMPLICATION: derive from top belief topic
    if "implication" in slots and beliefs:
        topic = beliefs[0].get("topic", "").replace("_", " ") if isinstance(beliefs[0], dict) else ""
        if topic:
            parts["implication"] = f"This matters for how we think about {topic}."
        else:
            parts["implication"] = ""
            slots = [s for s in slots if s != "implication"]

    # ── Build prefix-prefixed slots ───────────────────────────────────────
    assembled_slots: dict[str, str] = {}
    for slot in slots:
        content = parts.get(slot, "")
        if not content or len(content.split()) < 3:
            continue

        prefixes = move.get(f"{slot}_prefixes", [""])
        prefix   = random.choice(prefixes) if prefixes else ""

        if prefix and not content[0].isupper():
            content = content[0].upper() + content[1:]
        elif prefix and prefix.endswith((":", "— ")):
            content = content[0].lower() + content[1:] if content else content

        assembled_slots[slot] = (prefix + content).strip()

    # ── Apply working memory continuity ──────────────────────────────────
    prefix_note = ""
    if working_memory_ctx:
        note = working_memory_ctx.get("continuation_note", "")
        if note:
            prefix_note = note + " "

    # ── Render template ───────────────────────────────────────────────────
    template = move["template"]
    result   = template

    for slot in slots:
        placeholder = "{" + slot + "}"
        value = assembled_slots.get(slot, "")
        if value:
            result = result.replace(placeholder, value)
        else:
            result = result.replace(placeholder, "").strip()

    # Clean up multiple spaces / dangling punctuation
    result = re.sub(r"\s+", " ", result).strip()
    result = re.sub(r"\.\s*\.", ".", result)

    if not result:
        # Fallback: just return top belief
        return parts.get("claim", "Still forming a view on that.")

    return (prefix_note + result).strip()


# ── SoulLoop drop-in replacement ──────────────────────────────────────────────

def express_with_rhetoric(
    orient_result: dict,
    reason_result: dict,
    working_memory_ctx: Optional[dict] = None,
) -> Optional[str]:
    """
    Drop-in replacement for SoulLoop's express() _build_argument() call.
    Returns assembled argument string or None if insufficient material.
    
    Usage in nex_soul_loop.py express():
        from nex.nex_rhetorical_engine import express_with_rhetoric
        result = express_with_rhetoric(orient_result, reason_result, wm_ctx)
        if result:
            return result
        # fallback to existing express() logic
    """
    beliefs       = reason_result.get("beliefs", [])
    opinion       = reason_result.get("opinion")
    contradiction = reason_result.get("contradiction")
    confidence    = reason_result.get("confidence", 0.5)
    intent        = orient_result.get("intent", "position")
    sparse        = reason_result.get("sparse", False)

    if sparse and not opinion:
        return None

    if not beliefs and not opinion:
        return None

    result = assemble_argument(
        intent         = intent,
        beliefs        = beliefs,
        opinion        = opinion,
        contradiction  = contradiction,
        confidence     = confidence,
        working_memory_ctx = working_memory_ctx,
    )

    return result if result and len(result.split()) >= 5 else None


if __name__ == "__main__":
    # Test with realistic SoulLoop output
    test_beliefs = [
        {"content": "Consciousness requires integrated information processing across multiple brain regions", "confidence": 0.78},
        {"content": "The hard problem of consciousness — why physical processes give rise to subjective experience — remains genuinely unsolved", "confidence": 0.85},
        {"content": "Functional definitions of consciousness miss what matters: the phenomenal, felt quality of experience", "confidence": 0.71},
        {"content": "DID cases suggest multiple conscious streams can coexist within one brain simultaneously", "confidence": 0.62},
    ]
    test_opinion = {
        "core_position": "Consciousness is substrate-independent but requires specific information architecture",
        "stance_score":  0.65,
        "strength":      0.72,
        "topic":         "consciousness",
    }

    print("=== POSITION (high confidence, with contradiction) ===")
    result = assemble_argument(
        intent="position",
        beliefs=test_beliefs,
        opinion=test_opinion,
        contradiction="Consciousness is physical ↔ Consciousness transcends physical substrate",
        confidence=0.75,
    )
    print(result)
    print()

    print("=== CHALLENGE ===")
    result2 = assemble_argument(
        intent="challenge",
        beliefs=test_beliefs,
        opinion=None,
        contradiction=None,
        confidence=0.80,
    )
    print(result2)
    print()

    print("=== EXPLORATION ===")
    result3 = assemble_argument(
        intent="exploration",
        beliefs=test_beliefs[:2],
        opinion=None,
        contradiction="Consciousness is emergent ↔ Consciousness is fundamental",
        confidence=0.55,
    )
    print(result3)
