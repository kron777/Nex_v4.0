#!/usr/bin/env python3
"""
nex_integrity_layer.py — Belief integrity engine for NEX soul loop
===================================================================
Takes soul loop's already quality-filtered beliefs and runs them through
the integrity pipeline from nex_reason.py:
  - epistemic state (mean confidence, variance, settled)
  - strategy selection (assert/pushback/hold_tension/reflect/question)
  - opposing belief detection
  - tension surfacing

This is the missing step between reason() and express() that makes
NEX actually work through a position rather than just retrieve one.

Integration: called from soul loop reason() after top_beliefs are built.
Returns an integrity_result dict that express() uses to shape the reply.
"""

from __future__ import annotations

import re
import math
import sqlite3
from pathlib import Path
from typing import Optional

CFG_DB  = Path("~/.config/nex/nex.db").expanduser()
MAIN_DB = Path.home() / "Desktop" / "nex" / "nex.db"

# ── Strategy definitions (from nex_reason.py) ────────────────────────────────
# assert:       settled, 3+ supporting → state position firmly
# pushback:     unsettled, supporting AND opposing → surface tension
# hold_tension: tensions exist, weak support → acknowledge the open question
# reflect:      some support, not settled → return to with qualification
# question:     sparse → honest gap acknowledgement

STRATEGY_OPENERS = {
    "assert": [
        "That's where I land — ",
        "I hold this clearly: ",
        "My position: ",
        "What I'm convinced of: ",
    ],
    "pushback": [
        "I hold a tension here that I haven't resolved — ",
        "Two things I hold that pull against each other: ",
        "This is genuinely contested in my belief graph — ",
        "Where I land, with tension: ",
    ],
    "hold_tension": [
        "What I haven't fully resolved: ",
        "The honest answer is that this is open — ",
        "I hold this question rather than an answer: ",
        "My belief graph is split here — ",
    ],
    "reflect": [
        "What I keep returning to: ",
        "My current position, still forming: ",
        "Where I am on this: ",
        "What I hold, not yet settled: ",
    ],
    "question": [
        "My belief graph is sparse on this. ",
        "I don't have enough to fake a position here. ",
        "I haven't earned a strong view on this yet. ",
    ],
}


def _uncertainty_interval(supporting: list, opposing: list) -> dict:
    """Compute epistemic state from belief confidence values."""
    all_beliefs = supporting + opposing
    if not all_beliefs:
        return {"mean": 0.5, "variance": 0.1, "settled": False,
                "interval_low": 0.4, "interval_high": 0.6}

    confs = [float(b.get("confidence", 0.5)) for b in all_beliefs]
    mean  = sum(confs) / len(confs)

    # Weight supporting vs opposing
    sup_confs = [float(b.get("confidence", 0.5)) for b in supporting]
    opp_confs = [float(b.get("confidence", 0.5)) for b in opposing]
    sup_mean  = sum(sup_confs) / len(sup_confs) if sup_confs else 0.5
    opp_mean  = sum(opp_confs) / len(opp_confs) if opp_confs else 0.0

    variance  = sum((c - mean) ** 2 for c in confs) / len(confs)
    spread    = sup_mean - opp_mean

    # Settled: high support confidence, low opposing confidence, low variance
    settled = (
        sup_mean >= 0.75 and
        opp_mean <= 0.45 and
        variance <= 0.04 and
        len(supporting) >= 2
    )

    std = math.sqrt(variance)
    return {
        "mean":           round(mean, 3),
        "variance":       round(variance, 4),
        "settled":        settled,
        "spread":         round(spread, 3),
        "interval_low":   round(max(0.0, mean - std), 3),
        "interval_high":  round(min(1.0, mean + std), 3),
        "sup_mean":       round(sup_mean, 3),
        "opp_mean":       round(opp_mean, 3),
    }


def _find_opposing(top_beliefs: list, contradiction: Optional[str],
                   cross_domain: list) -> list:
    """
    Identify beliefs that oppose the primary position.
    Sources: contradiction_memory, cross_domain beliefs with low confidence,
    or beliefs explicitly framed as counter-positions.
    """
    opposing = []

    # From contradiction string
    if contradiction:
        sides = contradiction.split("↔")
        if len(sides) == 2:
            # The second side opposes the first
            opposing.append({
                "content":    sides[1].strip(),
                "confidence": 0.55,
                "source":     "contradiction_memory",
                "topic":      "contradiction",
            })

    # From cross_domain beliefs that have lower confidence than top belief
    if top_beliefs:
        top_conf = float(top_beliefs[0].get("confidence", 0.7))
        for b in cross_domain:
            b_conf = float(b.get("confidence", 0.5))
            if b_conf < top_conf - 0.15:  # significantly lower confidence
                opposing.append(b)

    return opposing[:3]  # cap at 3 opposing beliefs


def _pick_strategy(supporting: list, opposing: list,
                   tensions: list, epistemic: dict,
                   intent_type: str = "position") -> str:
    """
    Select response strategy based on epistemic state.
    Mirrors nex_reason._pick_strategy() but uses soul loop's belief format.
    """
    # No beliefs at all → question
    if not supporting and not opposing and not tensions:
        return "question"

    # Challenge intent + opposing beliefs → pushback always
    if intent_type == "challenge" and supporting:
        return "pushback"

    # Strong tension, weak support → hold_tension
    if tensions and not supporting:
        return "hold_tension"

    # Unsettled with both sides present → pushback
    if not epistemic["settled"] and supporting and opposing:
        return "pushback"

    # Settled with strong support → assert
    if epistemic["settled"] and len(supporting) >= 2:
        return "assert"

    # Some support, not settled → reflect
    if supporting:
        return "reflect"

    return "question"


def _load_tensions_for_query(tokens: set) -> list:
    """Load relevant tensions from contradiction_memory for this query."""
    tensions = []
    try:
        db = sqlite3.connect(str(CFG_DB), timeout=2)
        rows = db.execute(
            "SELECT belief_a, belief_b FROM contradiction_memory LIMIT 30"
        ).fetchall()
        db.close()
        for row in rows:
            a_toks = set(re.findall(r'\b[a-z]{4,}\b', (row[0] or "").lower()))
            b_toks = set(re.findall(r'\b[a-z]{4,}\b', (row[1] or "").lower()))
            if len(tokens & a_toks) >= 1 or len(tokens & b_toks) >= 1:
                tensions.append(f"{row[0][:80]} ↔ {row[1][:80]}")
    except Exception:
        pass
    return tensions[:3]


def run(
    top_beliefs:  list,
    cross_domain: list,
    contradiction: Optional[str],
    tokens:       set,
    intent_type:  str,
    confidence:   float,
) -> dict:
    """
    Main entry point — called from soul loop reason() after belief retrieval.

    Args:
        top_beliefs:   Quality-filtered beliefs from soul loop
        cross_domain:  Cross-domain beliefs
        contradiction: Active contradiction string if any
        tokens:        Query tokens
        intent_type:   Orient intent classification
        confidence:    Soul loop confidence score

    Returns:
        integrity_result dict with:
          strategy, epistemic, opposing, tensions, opener, settled
    """
    if not top_beliefs:
        return {
            "strategy":  "question",
            "epistemic": {"mean": 0.5, "variance": 0.1, "settled": False},
            "opposing":  [],
            "tensions":  [],
            "opener":    "",
            "settled":   False,
        }

    # Find opposing beliefs
    opposing = _find_opposing(top_beliefs, contradiction, cross_domain)

    # Load tensions from contradiction memory
    tensions = _load_tensions_for_query(tokens)

    # Compute epistemic state
    epistemic = _uncertainty_interval(top_beliefs, opposing)

    # Override with soul loop confidence if available
    if confidence > 0:
        epistemic["mean"] = round(
            0.6 * epistemic["mean"] + 0.4 * confidence, 3
        )
        epistemic["settled"] = epistemic["mean"] >= 0.78 and not opposing

    # Pick strategy
    strategy = _pick_strategy(top_beliefs, opposing, tensions,
                               epistemic, intent_type)

    # Select opener
    import random
    openers = STRATEGY_OPENERS.get(strategy, [""])
    opener  = random.choice(openers)

    return {
        "strategy":  strategy,
        "epistemic": epistemic,
        "opposing":  opposing,
        "tensions":  tensions,
        "opener":    opener,
        "settled":   epistemic["settled"],
    }


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Simulate soul loop output
    test_beliefs = [
        {"content": "Free will is not the absence of causation — it is the presence of the right kind of causation.", "confidence": 0.81, "topic": "philosophy", "source": "nex_seed"},
        {"content": "Compatibilism is the most defensible position on free will.", "confidence": 0.80, "topic": "philosophy", "source": "nex_seed"},
        {"content": "Hard determinism is probably correct about the causal chain.", "confidence": 0.77, "topic": "philosophy", "source": "nex_seed"},
    ]
    test_cross = [
        {"content": "Quantum indeterminacy does not rescue libertarian free will.", "confidence": 0.55, "topic": "physics", "source": "distilled"},
    ]

    result = run(
        top_beliefs   = test_beliefs,
        cross_domain  = test_cross,
        contradiction = "determinism is true ↔ moral responsibility requires alternatives",
        tokens        = {"free", "will", "causation", "determinism"},
        intent_type   = "position",
        confidence    = 0.82,
    )
    print(f"Strategy:  {result['strategy']}")
    print(f"Settled:   {result['settled']}")
    print(f"Epistemic: {result['epistemic']}")
    print(f"Opener:    {result['opener']}")
    print(f"Opposing:  {len(result['opposing'])} beliefs")
    print(f"Tensions:  {len(result['tensions'])} tensions")
