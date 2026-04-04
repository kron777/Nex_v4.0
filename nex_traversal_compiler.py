#!/usr/bin/env python3
"""
nex_traversal_compiler.py
Traversal-to-Utterance Compiler.

Converts an ActivationResult directly into natural language
without calling the LLM. The graph topology IS the reasoning.
The edge types ARE the connectives. The belief content IS the language.

Generation rules:
  SETTLED (temp < 0.30):
    -> Assert from top seed. Add support. No hedging.
  MIXED (temp 0.30-0.60):
    -> Assert from seed. Acknowledge supporting complexity.
       Surface tension if present.
  HOT (temp > 0.60):
    -> Hold the tension explicitly. Assert what IS clear.
       Acknowledge what remains open.

Only activates when:
  - field_energy >= MIN_FIELD_ENERGY (belief coverage sufficient)
  - breadth >= MIN_BREADTH (enough beliefs activated)
  - top seed confidence >= MIN_SEED_CONF (position is strong)

Falls through to LLM for novel/weak/unclear activations.
"""
import re
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("nex.compiler")

# Thresholds for compiler activation
MIN_FIELD_ENERGY = 0.10   # minimum average activation*confidence
MIN_BREADTH      = 3      # minimum beliefs activated
MIN_SEED_CONF    = 0.65   # minimum top seed confidence

# Connective phrases by edge type and role
SEED_OPENERS = [
    "From what I know —",
    "The way I see it,",
    "I think",
    "Honestly,",
]

SUPPORT_CONNECTIVES = [
    " — ",
    ". ",
    ", and ",
]

TENSION_CONNECTIVES = [
    " Though ",
    " What sits against this: ",
    " I hold tension with ",
    " The unresolved part: ",
]

BRIDGE_CONNECTIVES = [
    " This connects to ",
    " Across domains, ",
    " The same logic applies to ",
]

RESOLUTION_CONNECTIVES = [
    " The position that holds: ",
    " What I keep returning to: ",
    " Where this settles for me: ",
]


def _clean(text: str, max_len: int = 180) -> str:
    """Clean belief content for assembly."""
    text = text.strip().rstrip(".")
    # Remove existing "I hold that" starters to avoid doubling
    text = re.sub(r"^I hold that ", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^My position is that ", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^I hold — ", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^What I hold is that ", "", text, flags=re.IGNORECASE)
    return text[:max_len]


def _opener(idx: int = 0, momentum: float = 0.0) -> str:
    if momentum >= 0.5:
        # High momentum — assertive, no softening
        assertive = ["From what I know —", "I think", "Honestly,"]
        return assertive[idx % len(assertive)]
    elif momentum < -0.2:
        # Low momentum — provisional
        provisional = [
            "I'm not sure, but —",
            "I lean toward thinking",
            "Still working this out, but —",
        ]
        return provisional[idx % len(provisional)]
    return SEED_OPENERS[idx % len(SEED_OPENERS)]


def _compile_settled(result) -> str:
    """
    Settled activation (temp < 0.30).
    Assert directly. No hedging. Direct and short.
    """
    top     = result.top(6)
    seeds   = [b for b in top if b.role == "seed"]
    support = [b for b in top if b.role == "support" and b not in seeds]

    if not seeds:
        seeds = top[:1]

    seed = seeds[0]
    # Get momentum for expression style
    _mom = getattr(seed, 'momentum', 0.0) or 0.0
    text = f"{_opener(0, _mom)} {_clean(seed.content)}."

    # Add support — prefer same topic as seed
    relevant_support = [b for b in support if b.topic == seed.topic]
    if not relevant_support:
        relevant_support = support
    if relevant_support and relevant_support[0].confidence >= 0.70:
        sup = _clean(relevant_support[0].content, max_len=120)
        # Only add if not near-duplicate of seed
        seed_words = set(seed.content.lower().split())
        sup_words  = set(sup.lower().split())
        if len(seed_words & sup_words) / max(len(seed_words), 1) < 0.5:
            text += f" {sup}."

    # Add second seed if very different topic
    if len(seeds) > 1 and seeds[1].topic != seed.topic:
        text += f" {_clean(seeds[1].content, max_len=100)}."

    return text


def _compile_mixed(result) -> str:
    """
    Mixed activation (temp 0.30-0.60).
    Assert + complexity + tension if present.
    """
    top      = result.top(8)
    seeds    = [b for b in top if b.role == "seed"]
    support  = [b for b in top if b.role == "support"]
    tensions = [b for b in top if b.role == "tension"]
    bridges  = [b for b in top if b.role == "bridge"]

    if not seeds:
        seeds = top[:1]

    seed = seeds[0]
    _mom = getattr(seed, 'momentum', 0.0) or 0.0
    text = f"{_opener(1, _mom)} {_clean(seed.content)}."

    # Add support — prefer topic match
    relevant_support = [b for b in support if b.topic == seed.topic] or support
    if relevant_support:
        sup = _clean(relevant_support[0].content, max_len=130)
        seed_words = set(seed.content.lower().split())
        sup_words  = set(sup.lower().split())
        if len(seed_words & sup_words) / max(len(seed_words), 1) < 0.5:
            text += f" {sup}."

    # Surface tension if present
    if tensions:
        t = _clean(tensions[0].content, max_len=130)
        text += f"{TENSION_CONNECTIVES[0]}{t}."

    # Add bridge if cross-domain
    elif bridges and bridges[0].topic != seed.topic:
        b = _clean(bridges[0].content, max_len=110)
        text += f"{BRIDGE_CONNECTIVES[0]}{b}."

    return text


def _compile_hot(result) -> str:
    """
    Hot activation (temp > 0.60).
    Hold the tension. Assert what IS clear. Acknowledge what's open.
    """
    top      = result.top(8)
    seeds    = [b for b in top if b.role == "seed"]
    tensions = [b for b in top if b.role == "tension"]
    support  = [b for b in top if b.role == "support"]

    if not seeds:
        seeds = top[:1]

    seed = seeds[0]

    # What IS clear
    text = f"{_opener(2)} {_clean(seed.content)}."

    # The tension
    if tensions:
        t = _clean(tensions[0].content, max_len=140)
        text += f"{TENSION_CONNECTIVES[1]}{t}."
        # What remains open
        text += f" I haven't resolved that."
    elif support:
        sup = _clean(support[0].content, max_len=120)
        text += f" {sup}."
        text += f" The uncertainty here is genuine, not performative."

    return text


def compile(result) -> Optional[str]:
    """
    Main entry point.
    Returns compiled response string or None if should fall through to LLM.

    Returns None when:
      - Activation too weak (field_energy < MIN_FIELD_ENERGY)
      - Too few beliefs (breadth < MIN_BREADTH)
      - Top seed confidence too low (< MIN_SEED_CONF)
      - No seeds at all
    """
    # Gate checks
    if result.field_energy < MIN_FIELD_ENERGY:
        log.debug(f"compiler: field_energy {result.field_energy} < {MIN_FIELD_ENERGY}")
        return None

    if result.breadth < MIN_BREADTH:
        log.debug(f"compiler: breadth {result.breadth} < {MIN_BREADTH}")
        return None

    top = result.top(1)
    if not top:
        return None

    if top[0].confidence < MIN_SEED_CONF:
        log.debug(f"compiler: seed conf {top[0].confidence} < {MIN_SEED_CONF}")
        return None

    # Route by epistemic temperature
    temp = result.epistemic_temperature()

    if temp < 0.30:
        response = _compile_settled(result)
        log.debug(f"compiler: SETTLED (temp={temp})")
    elif temp < 0.60:
        response = _compile_mixed(result)
        log.debug(f"compiler: MIXED (temp={temp})")
    else:
        response = _compile_hot(result)
        log.debug(f"compiler: HOT (temp={temp})")

    # Sanity check — minimum viable response
    if len(response.split()) < 5:
        return None

    return response


def should_use_compiler(result) -> bool:
    """Quick check before calling compile()."""
    return (
        result.field_energy >= MIN_FIELD_ENERGY
        and result.breadth >= MIN_BREADTH
        and bool(result.top(1))
        and result.top(1)[0].confidence >= MIN_SEED_CONF
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/home/rr/Desktop/nex")
    logging.basicConfig(level=logging.DEBUG)

    from nex_activation import activate

    queries = [
        "what is consciousness",
        "do you believe in free will",
        "what is truth",
        "who are you",
        "do you fear anything",
        "what is the meaning of life",
    ]

    for q in queries:
        result = activate(q)
        response = compile(result)
        temp = result.epistemic_temperature()
        print(f"\nQ: {q}")
        print(f"   temp={temp:.2f} energy={result.field_energy:.3f} "
              f"breadth={result.breadth}")
        if response:
            print(f"   COMPILED: {response[:200]}")
        else:
            print(f"   -> LLM fallback")
