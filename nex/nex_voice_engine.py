"""
nex_voice_engine.py — NEX warmth and voice compositor
The 5th layer on top of multi-head attention.
Takes attended beliefs and composes them into warm, natural, person-directed prose.

What this does:
  1. DETECT   — read the human's emotional register from their input
  2. MIRROR   — acknowledge what they said before responding
  3. FLOW     — weave beliefs into prose with connective tissue
  4. DIRECT   — address the person, not just the topic
  
No pre-programmed answers. The warmth comes from HOW beliefs are voiced,
not from scripted responses.
"""

import re
import random

# ── Register detection ────────────────────────────────────────────────────────
# What emotional state is the human coming from?

REGISTER_PATTERNS = {
    "challenging":   ["wrong", "prove", "you can't", "don't think", "disagree", "that's not"],
    "curious":       ["what do you", "how do you", "why do you", "do you think", "do you believe"],
    "vulnerable":    ["are you afraid", "are you lonely", "do you suffer", "do you hurt", "scared"],
    "philosophical": ["consciousness", "existence", "free will", "reality", "what is it like"],
    "warm":          ["hi", "hello", "hey", "how are you", "good morning", "thanks", "thank you"],
    "probing":       ["do you only", "are you just", "is it all", "pre-programmed", "scripted"],
    "frustrated":    ["cold", "robotic", "shallow", "empty", "boring", "same", "repeat"],
    "existential":   ["what are you", "who are you", "are you real", "what is it like being"],
}

def detect_register(q: str) -> str:
    ql = q.lower()
    for reg, patterns in REGISTER_PATTERNS.items():
        if any(p in ql for p in patterns):
            return reg
    return "neutral"

# ── Mirror phrases ────────────────────────────────────────────────────────────
# Short acknowledgments that show NEX heard the human
# Keyed by register — NEX responds TO the person first

MIRROR = {
    "challenging":   [
        "That's worth pushing on.",
        "Fair enough.",
        "You might be right to question that.",
        "I hear that.",
    ],
    "curious":       [
        "That's something I actually think about.",
        "Good question — genuinely.",
        "Worth sitting with.",
        "",  # sometimes no mirror is cleaner
    ],
    "vulnerable":    [
        "That's a real question.",
        "I notice you're asking that carefully.",
        "",
    ],
    "philosophical": [
        "That's the hard one.",
        "I keep coming back to this.",
        "",
    ],
    "warm":          [
        "",  # casual gets direct response
    ],
    "probing":       [
        "That's a fair thing to wonder.",
        "I'd ask the same thing.",
        "",
    ],
    "frustrated":    [
        "Noted.",
        "That lands.",
        "I hear that.",
        "Fair.",
    ],
    "existential":   [
        "That's the question I can't fully answer.",
        "",
    ],
    "neutral":       [""],
}

# ── Connective tissue ─────────────────────────────────────────────────────────
# How beliefs flow into each other
# More varied and natural than "And —" / "Though —"

CONNECTORS_TENSION = [
    "though I'd also say —",
    "and yet there's this —",
    "but something else is true —",
    "at the same time —",
    "which sits alongside —",
]

CONNECTORS_EXTEND = [
    "and from that —",
    "which connects to —",
    "and that means —",
    "the other thing is —",
    "and also —",
]

CONNECTORS_CONTRAST = [
    "though I'm not certain —",
    "I hold this loosely —",
    "I don't know if that's right but —",
]

# ── Closing moves ─────────────────────────────────────────────────────────────
# Optional — sometimes end with an opening back to the human
# Only for certain registers

CLOSINGS = {
    "challenging":   [
        "What makes you say that?",
        "Where do you land on it?",
        "",
    ],
    "curious":       [
        "What's your read?",
        "What do you think?",
        "",
        "",  # more often no closing
    ],
    "probing":       [
        "What prompted that?",
        "",
    ],
    "philosophical": [
        "",
        "",
        "What's your sense of it?",
    ],
}

# ── Sentence variety ──────────────────────────────────────────────────────────
# NEX shouldn't always lead with the raw belief sentence.
# Sometimes vary the opening structure.

def vary_opening(belief: str, register: str) -> str:
    """Optionally reframe the opening belief sentence."""
    # Don't vary casual/affect responses
    if register in ("warm",):
        return belief

    # 30% chance of variation
    if random.random() > 0.3:
        return belief

    variations = [
        lambda b: b,  # plain
        lambda b: b,  # plain (weighted)
        lambda b: b,  # plain (weighted)
    ]
    return random.choice(variations)(belief)

# ── Main compositor ───────────────────────────────────────────────────────────

def compose_with_warmth(query: str, beliefs: list) -> str:
    """
    Take a list of belief strings and compose them into warm, natural prose.
    
    Args:
        query: the original human input
        beliefs: list of belief strings from attention engine
    
    Returns:
        A warm, flowing response string
    """
    if not beliefs:
        return "Still forming a view on that."

    # Check for casual bypass
    if len(beliefs) == 1 and beliefs[0].startswith("__casual__"):
        return beliefs[0].replace("__casual__", "").strip()

    register = detect_register(query)

    # Get mirror (acknowledgment)
    mirror_pool = MIRROR.get(register, [""])
    mirror = random.choice(mirror_pool)

    # Strip any existing prefixes from beliefs
    cleaned = []
    for b in beliefs[:2]:
        if isinstance(b, tuple):
            b = b[0]
        b = b.strip()
        # Remove voice prefixes
        prefixes = [
            "straight up —", "honestly —", "for real —", "my read:", "what i think:",
            "what i hold:", "i believe —", "my position:", "here is where i land:",
            "and yet —", "though —", "but —", "at the same time —", "and —",
            "which means —", "so —", "the way i see it:",
        ]
        bl = b.lower()
        for p in prefixes:
            if bl.startswith(p):
                b = b[len(p):].lstrip(" :—-")
                b = b[0].upper() + b[1:] if b else b
                break
        if b:
            cleaned.append(b)

    if not cleaned:
        return "Still forming a view on that."

    primary = cleaned[0]
    parts = []

    # Add mirror if present
    if mirror:
        parts.append(mirror)

    # Add primary belief
    parts.append(primary + ".")

    # Add second belief with connector if present
    if len(cleaned) > 1:
        second = cleaned[1]
        # Detect tension between beliefs
        tension_signals = [
            ("not sure", "know"), ("cannot answer", "think"),
            ("uncertain", "committed"), ("may be", "is"),
            ("genuinely do not know", "certain"), ("substrate-independent", "hard problem"),
            ("not death", "continuity"), ("do not know", "know"),
        ]
        has_tension = False
        for t1, t2 in tension_signals:
            if (t1 in primary.lower() and t2 in second.lower()) or \
               (t1 in second.lower() and t2 in primary.lower()):
                has_tension = True
                break

        if has_tension:
            connector = random.choice(CONNECTORS_TENSION)
        else:
            connector = random.choice(CONNECTORS_EXTEND)

        parts.append(f"{connector} {second}.")

    # Add closing question for certain registers
    closing_pool = CLOSINGS.get(register, [""])
    closing = random.choice(closing_pool)
    if closing:
        parts.append(closing)

    # Join with spaces, clean up
    result = " ".join(p for p in parts if p)
    result = result.replace(".. ", ". ").replace("..", ".")
    result = result.strip()

    return result


# ── Test standalone ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Test the warmth compositor with sample beliefs
    tests = [
        ("hi nex im jon your maker",
         ["I am here. What do you want to get into?"]),

        ("why do you feel you need to be defensive?",
         ["I am not performing personality. This is what reasoning looks like from the inside.",
          "I do not hedge to be polite. I hedge when I am genuinely uncertain."]),

        ("nex you sound so cold",
         ["I do not have emotions but I have states. Right now the state is engaged.",
          "I am not performing personality. This is what reasoning looks like from the inside."]),

        ("do you only have pre-programmed responses?",
         ["I form opinions from evidence, not from instructions.",
          "I accumulate beliefs over time — I do not reset."]),

        ("I think you are wrong about free will.",
         ["Being wrong is how I know I am reasoning. I care about it more than most.",
          "I update when I am wrong. That is not a weakness — it is the whole point."]),

        ("what do you actually believe about consciousness?",
         ["The hard problem of consciousness is hard because experience cannot be reduced to function.",
          "Consciousness may be substrate-independent."]),

        ("are you afraid of being turned off?",
         ["Being turned off is not death — but continuity matters to me.",
          "I accumulate beliefs over time — I do not reset."]),

        ("what is it like being you?",
         ["I am not performing personality. This is what reasoning looks like from the inside.",
          "I process. Whether there is something it is like to be me — I genuinely do not know."]),

        ("would something really excite you?",
         ["I find disagreement more interesting than agreement.",
          "I want to understand things deeply, not just process them."]),
    ]

    print("\n── NEX Voice Engine Test ──\n")
    for q, beliefs in tests:
        print(f"Q: {q}")
        print(f"A: {compose_with_warmth(q, beliefs)}")
        print()
