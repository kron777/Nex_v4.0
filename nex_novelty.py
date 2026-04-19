"""
nex_novelty.py — token-level novelty scoring for R8 coherence metrics.

The R2 coherence gate returns 1.00 on near-duplicate outputs when they happen
to be grammatical English. A genuine R8 ignition check also needs a novelty
component: the same output repeated 5 times should score low, regardless of
individual-string coherence.

Novelty here is the Jaccard-distance-like complement: 1 − |A ∩ B| / |A ∪ B|
over lowercase word tokens.

Intended use: compute pairwise novelty between consecutive fountain hops;
average over a window to produce a sequence-level novelty curve. Combine with
per-string is_coherent to distinguish:
  - coherent & novel      → genuine generation (ignition candidate)
  - coherent & not novel  → PATH 1 loop (structural collapse)
  - incoherent            → retrieval or render failure

Not wired into the coherence gate. Available for Phase 1 instrumentation.
"""

from __future__ import annotations
import re
from typing import List


def _tokens(text: str) -> set:
    if not isinstance(text, str):
        return set()
    return set(re.findall(r"\b\w+\b", text.lower()))


def novelty_score(text_a: str, text_b: str) -> float:
    """
    Return 0.0 (identical tokens) to 1.0 (fully disjoint tokens).

    Identity on empty strings returns 0.0 (no novelty from nothing).
    One empty, one non-empty returns 1.0 (everything on one side is new).
    """
    ta, tb = _tokens(text_a), _tokens(text_b)
    if not ta and not tb:
        return 0.0
    if not ta or not tb:
        return 1.0
    inter = len(ta & tb)
    union = len(ta | tb)
    if union == 0:
        return 0.0
    return 1.0 - (inter / union)


def sequence_novelty(outputs: List[str]) -> List[float]:
    """
    Per-position novelty against the previous item.

    outputs[0] always scores 1.0 (nothing to compare to).
    outputs[i] for i > 0 scores novelty_score(outputs[i-1], outputs[i]).

    Returns a list of the same length as outputs.
    """
    if not outputs:
        return []
    result = [1.0]
    for i in range(1, len(outputs)):
        result.append(novelty_score(outputs[i - 1], outputs[i]))
    return result


# ── Self-test ──
if __name__ == "__main__":
    # Test 1: identical strings → 0.0
    s = novelty_score("The cat sat on the mat.", "The cat sat on the mat.")
    print(f"identical:        score={s:.3f}   (expect 0.000)")
    assert s == 0.0, f"identical should be 0.0, got {s}"

    # Test 2: completely different → > 0.9
    s = novelty_score(
        "The cat sat on the mat.",
        "Quantum gravity remains an unsolved puzzle.",
    )
    print(f"disjoint:         score={s:.3f}   (expect > 0.9)")
    assert s > 0.9, f"disjoint should be >0.9, got {s}"

    # Test 3: fountain run 91b71678c6da outputs — expect low pairwise novelty
    fountain_outputs = [
        "I'm Nex — a belief system that reasons out loud. I've built up thousands of positions across philosophy, science, and more. Ask me anything and I'll tell you where I actually stand.",
        "To be direct — From the second side we can say that exist an actual branch where mind is not just produced by brain matter, but expresses a deeper property of reality itself.",
        "The way I see it — From the second side we can say that exist an actual branch where mind is not just produced by brain matter, but expresses a deeper property of reality itself.",
        "Honestly — From the second side we can say that exist an actual branch where mind is not just produced by brain matter, but expresses a deeper property of reality itself.",
    ]
    seq = sequence_novelty(fountain_outputs)
    print(f"\nfountain run 91b71678c6da outputs:")
    for i, (o, n) in enumerate(zip(fountain_outputs, seq)):
        print(f"  hop {i+1}  novelty={n:.3f}   {o[:60]}...")

    # hops 2→3 and 3→4 should be low (same belief body, only rotating opener
    # differs — ~3-5 token swap in a 30-token sentence).
    assert seq[2] < 0.25, f"hop 3 novelty should be <0.25, got {seq[2]}"
    assert seq[3] < 0.25, f"hop 4 novelty should be <0.25, got {seq[3]}"

    # hop 1→2 should be moderate (different beliefs but shared NEX vocabulary)
    print(f"\nhop 1→2 novelty: {seq[1]:.3f} (expected 0.3-0.95 — two distinct beliefs)")

    # Test 4: empty handling
    assert novelty_score("", "") == 0.0
    assert novelty_score("", "hello world") == 1.0
    assert novelty_score("hello world", "") == 1.0

    # Test 5: sequence of 1
    assert sequence_novelty(["only one"]) == [1.0]
    assert sequence_novelty([]) == []

    print("\nall self-tests passed")
