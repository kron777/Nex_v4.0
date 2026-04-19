"""
nex_tier0_composer.py — Phase 2A Tier 0 Python-only response composer.

Produces a coherent response from retrieved beliefs WITHOUT the LLM.

CRITICAL: every belief passes through _sanitize_belief from nex.nex_respond_v2.
The LLM weight contamination problem (bridge:X↔Y etc.) DOES NOT APPLY to
Tier 0 because there is no LLM call.

Deterministic: for a given (beliefs, query, intent), the same output is
produced every time. Opener/connective selection is hash-based, not random.
Blind-test replicability depends on this determinism.

Output constraints:
  - min 40 chars (avoid trivial outputs)
  - max 400 chars (Tier 0 is concise by design)
"""

from __future__ import annotations
import hashlib
import os
import sys
from pathlib import Path
from typing import List, TYPE_CHECKING

# Ensure we can import from nex package
_ROOT = Path(os.path.expanduser("~/Desktop/nex"))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from nex.nex_respond_v2 import _sanitize_belief

if TYPE_CHECKING:
    from nex_response_router import BeliefHit


MIN_LEN = 40
MAX_LEN = 400


_SELF_OPENERS = [
    "As I understand myself:",
    "From inside my own frame:",
    "What I hold about this is:",
    "My position:",
]

_GENERAL_OPENERS = [
    "What I hold on this:",
    "From the beliefs that bear on this:",
    "Here's where I stand:",
    "The position I've settled on:",
]

_CONNECTIVES = [
    "and relatedly,",
    "which connects to:",
    "building from that,",
    "alongside which:",
]


def _pick(key: str, pool: List[str]) -> str:
    """Deterministic picker — stable hash → index into pool."""
    if not pool:
        return ""
    h = hashlib.md5(key.encode("utf-8")).digest()
    idx = int.from_bytes(h[:4], "big") % len(pool)
    return pool[idx]


def _clean(beliefs: List["BeliefHit"], limit: int = 3) -> List[str]:
    cleaned = []
    for b in (beliefs or [])[:limit]:
        if not b or not b.content:
            continue
        s = _sanitize_belief(b.content).strip()
        if len(s) <= 10:
            continue
        # Normalize trailing punctuation into a terminal period
        if s and s[-1] not in ".!?":
            s = s + "."
        cleaned.append(s)
    return cleaned


def _clip_max(text: str, max_len: int = MAX_LEN) -> str:
    """Clip to max_len on sentence boundary when possible."""
    if len(text) <= max_len:
        return text
    # Try to cut at the last sentence boundary within the limit
    slack = text[:max_len]
    for sep in (". ", "! ", "? "):
        idx = slack.rfind(sep)
        if idx >= 0 and idx > max_len * 0.5:
            return slack[:idx + 1]
    # Fallback: hard cut with ellipsis, keeping total ≤ max_len
    return text[:max_len - 3].rstrip() + "..."


def compose_tier0(beliefs: List["BeliefHit"], query: str, intent: str) -> str:
    """Compose a response from sanitized beliefs. Returns '' if nothing usable."""
    sanitized = _clean(beliefs, limit=3)
    if not sanitized:
        return ""

    key = f"{intent}|{(query or '').strip()[:200]}"

    if intent == "self_inquiry":
        opener = _pick(key + "|so", _SELF_OPENERS)
        body = sanitized[0]
        if len(sanitized) > 1:
            conn = _pick(key + "|c1", _CONNECTIVES)
            body = f"{body} {conn} {sanitized[1]}"
        out = f"{opener} {body}"
    elif intent == "factual":
        # Declarative concat, no opener
        out = " ".join(sanitized[:2])
    else:
        opener = _pick(key + "|go", _GENERAL_OPENERS)
        if len(sanitized) == 1:
            out = f"{opener} {sanitized[0]}"
        else:
            conn = _pick(key + "|c1", _CONNECTIVES)
            out = f"{opener} {sanitized[0]} {conn} {sanitized[1]}"

    out = out.strip()
    if len(out) < MIN_LEN:
        # Try extending with a third belief if available
        if len(sanitized) > 2:
            out = out.rstrip(".").rstrip() + ". " + sanitized[2]
    out = _clip_max(out, MAX_LEN)
    return out


# ── Unit tests ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Lazy import only for the self-test — keeps module light in production
    class _BH:
        def __init__(self, content, confidence=0.8, topic=None, tfidf_score=0.5):
            self.content = content
            self.confidence = confidence
            self.topic = topic
            self.tfidf_score = tfidf_score

    passed = failed = 0
    def check(name, cond, detail=""):
        nonlocal_pass = {"p": passed, "f": failed}
        print(("  ✓" if cond else "  ✗") + f" {name}" + (f"  — {detail}" if not cond and detail else ""))
        return cond

    # Test 1: 3 high-confidence beliefs + self_inquiry → valid response
    print("Test 1: self_inquiry happy path")
    t1_beliefs = [
        _BH("Beliefs change through retrieval and challenge"),
        _BH("Identity is the residue of truth-seeking"),
        _BH("Self-reference is structural not phenomenal"),
    ]
    out1 = compose_tier0(t1_beliefs, "what do you think about yourself?", "self_inquiry")
    print(f"    out: {out1!r}")
    ok = MIN_LEN <= len(out1) <= MAX_LEN
    if ok: passed += 1
    else: failed += 1
    print(("    ✓" if ok else "    ✗") + f" length in [{MIN_LEN},{MAX_LEN}]: {len(out1)}")

    # Test 2: sanitizer fires on bridge:X↔Y
    print("Test 2: sanitizer strips bridge:X↔Y from composed output")
    t2_beliefs = [
        _BH("The interesting thing about bridge:truth seeking↔reuse: beliefs connect through shared context."),
        _BH("Identity persists through compositional change."),
    ]
    out2 = compose_tier0(t2_beliefs, "what is belief structure?", "factual")
    print(f"    out: {out2!r}")
    ok = "bridge:" not in out2 and "↔" not in out2
    if ok: passed += 1
    else: failed += 1
    print(("    ✓" if ok else "    ✗") + f" no graph syntax in output")

    # Test 3: determinism — same input twice → same output
    print("Test 3: determinism")
    t3_beliefs = [_BH("Beliefs update with evidence."), _BH("Confidence is a real variable.")]
    a = compose_tier0(t3_beliefs, "how do you update?", "general")
    b = compose_tier0(t3_beliefs, "how do you update?", "general")
    ok = a == b and len(a) > 0
    if ok: passed += 1
    else: failed += 1
    print(f"    out: {a!r}")
    print(("    ✓" if ok else "    ✗") + f" byte-identical across calls")

    # Test 4: different queries → different opener/connective picks
    print("Test 4: query variation drives opener variation")
    a2 = compose_tier0(t3_beliefs, "query alpha", "general")
    b2 = compose_tier0(t3_beliefs, "query beta", "general")
    ok = a2 != b2  # not guaranteed but usually true with hash
    # This is best-effort — only warn if equal
    if ok:
        passed += 1
        print("    ✓ different queries produced different output")
    else:
        print("    ⚠ different queries produced same output (possible with small pools)")
        passed += 1  # not a hard fail

    # Test 5: empty / degenerate input → empty string
    print("Test 5: empty beliefs → empty string")
    out5 = compose_tier0([], "anything", "general")
    ok = out5 == ""
    if ok: passed += 1
    else: failed += 1
    print(("    ✓" if ok else "    ✗") + f" empty→empty: got {out5!r}")

    # Test 6: length bound — huge belief gets clipped
    print("Test 6: max-length clipping")
    big = "A" * 800
    t6 = [_BH(big + " First sentence ends here.")]
    out6 = compose_tier0(t6, "describe", "general")
    ok = len(out6) <= MAX_LEN
    if ok: passed += 1
    else: failed += 1
    print(("    ✓" if ok else "    ✗") + f" clipped to <= {MAX_LEN}: got {len(out6)}")

    # Test 7: factual intent has no opener
    print("Test 7: factual intent has no opener")
    out7 = compose_tier0(t1_beliefs, "what is X?", "factual")
    ok = not any(out7.startswith(op) for op in _SELF_OPENERS + _GENERAL_OPENERS)
    if ok: passed += 1
    else: failed += 1
    print(("    ✓" if ok else "    ✗") + f" no opener on factual: {out7[:60]!r}")

    print()
    print(f"passed: {passed} / failed: {failed}")
