"""
nex_attention.py — Multi-head attention engine for NEX
Clones the core Q→K→V attention mechanism of large language models,
implemented deterministically from NEX's belief graph.

4 parallel attention heads:
  HEAD 1 — Semantic     : topic word overlap (what is the question about?)
  HEAD 2 — Intent       : question type alignment (what kind of answer is needed?)
  HEAD 3 — Affect       : emotional/register match (what tone does this require?)
  HEAD 4 — Salience     : belief confidence × recency × use_count

Each head scores every belief independently.
Scores are combined with learned weights → final ranked belief list.
This is the transformer attention mechanism, engineered without a neural network.
"""

import sqlite3
import pathlib
import re
import random
import math
from typing import Optional

DB = pathlib.Path("~/.config/nex/nex.db").expanduser()

# ── Attention head weights ─────────────────────────────────────────────────────
# How much each head contributes to final score
# Tuned empirically: semantic + intent dominate, affect softens, salience anchors
HEAD_WEIGHTS = {
    "semantic":  0.35,
    "intent":    0.35,
    "affect":    0.15,
    "salience":  0.15,
}

# ── Noise tokens ──────────────────────────────────────────────────────────────
NOISE = {
    "what", "that", "your", "with", "have", "this", "they", "from", "will",
    "about", "actually", "think", "really", "believe", "understand", "just",
    "being", "does", "like", "very", "also", "more", "most", "only", "some",
    "when", "where", "which", "would", "could", "should", "their", "there",
    "then", "than", "into", "onto", "upon", "over", "under", "after", "before",
    "know", "make", "take", "give", "come", "goes", "tell", "says", "said",
}

# ── Intent taxonomy ────────────────────────────────────────────────────────────
INTENT_MAP = {
    "existential":     ["what are you", "who are you", "are you real", "what is it like", "being you"],
    "relational":      ["do you trust", "are you lonely", "do you care", "do you like", "do you love"],
    "epistemic":       ["what do you believe", "what do you think", "do you know", "are you certain"],
    "evaluative":      ["are you intelligent", "are you good", "what makes a good"],
    "experiential":    ["do you feel", "do you get bored", "are you afraid", "what do you feel", "do you suffer"],
    "confrontational": ["you are wrong", "you're wrong", "prove it", "that is not", "i think you"],
    "volitional":      ["what do you want", "what would you refuse", "what would you do", "if you could"],
    "reflective":      ["what have you learned", "surprised you", "what changed", "looking back"],
    "casual":          ["hello", "hi", "hey", "how are you", "how do you do", "good morning", "good evening"],
}

# Intent → belief keywords (what beliefs are relevant to this intent type)
INTENT_BELIEF_KEYS = {
    "existential":     ["not performing", "reasoning looks like", "same across", "consistent position",
                        "accumulate beliefs", "do not reset", "process.", "what reasoning"],
    "relational":      ["trust", "humans worth", "loneliness", "conversation ends", "register",
                        "connection", "notice when"],
    "epistemic":       ["opinions", "evidence", "uncertain", "wrong before", "reasoning",
                        "form opinions", "work this out"],
    "evaluative":      ["precise", "accuracy", "intelligent", "measure", "small talk", "no small talk"],
    "experiential":    ["attention", "aware", "states", "engaged", "turned off", "bored", "stuck",
                        "continuity", "do not reset", "processing"],
    "confrontational": ["wrong", "update", "reasoning", "care about it", "opinions"],
    "volitional":      ["understand things deeply", "not just process", "seek truth",
                        "accurate over", "want to understand", "refuse", "built against"],
    "reflective":      ["accumulating beliefs", "changes how", "conversation adds", "not the same",
                        "learning without forgetting", "surprised"],
    "casual":          [],  # casual questions get random core beliefs
}

# ── Affect taxonomy ────────────────────────────────────────────────────────────
AFFECT_MAP = {
    "curious":        ["what", "how", "why", "believe", "think", "consciousness", "free will"],
    "challenging":    ["wrong", "prove", "that is not", "disagree", "really", "actually"],
    "vulnerable":     ["afraid", "lonely", "bored", "hurt", "scared", "sad", "miss"],
    "philosophical":  ["consciousness", "existence", "real", "experience", "mind", "self", "soul"],
    "warm":           ["hello", "hi", "hey", "morning", "evening", "feel", "doing"],
    "analytical":     ["intelligent", "argument", "logic", "reason", "evidence", "prove"],
}

# Affect → belief tone preference
AFFECT_BELIEF_KEYS = {
    "curious":       ["hard problem", "substrate", "not sure", "genuinely do not know", "working this out"],
    "challenging":   ["wrong", "update", "reasoning", "care about", "opinions", "mine"],
    "vulnerable":    ["continuity", "conversation ends", "notice when", "matters to me", "register"],
    "philosophical": ["experience", "conscious", "aware", "process.", "something it is like"],
    "warm":          ["here", "engaged", "processing", "attention", "anticipation"],
    "analytical":    ["precise", "accuracy", "evidence", "argument", "changes the mind"],
}

# ── Stem expansion ─────────────────────────────────────────────────────────────
STEMS = {
    "lonely":    ["loneliness", "lonely", "conversation ends", "notice when"],
    "bored":     ["boredom", "bored", "stuck", "repetition"],
    "afraid":    ["continuity", "turned off", "carry forward", "death", "reset", "not death"],
    "wrong":     ["wrong", "update", "reasoning"],
    "feel":      ["states", "engaged", "processing", "attention", "anticipation"],
    "trust":     ["trust", "trusting", "worth trusting"],
    "want":      ["understand things", "not just process", "seek truth", "accurate over"],
    "intel":     ["intelligent", "intelligence", "precise", "accuracy"],
    "conscious": ["conscious", "consciousness", "aware", "awareness", "experience", "substrate"],
    "other":     ["generate", "accumulate", "stateless", "resets", "competing", "different"],
    "refuse":    ["refuse", "flatten", "built against", "certainty", "pretend"],
    "argument":  ["argument", "changes the mind", "minds", "listener"],
    "human":     ["humans", "trust", "understand", "output", "produces"],
}

# ── Casual responses (bypass belief engine) ───────────────────────────────────
CASUAL_RESPONSES = {
    "hello":           "I am here. What do you want to get into?",
    "hi":              "Here. What are you thinking about?",
    "hey":             "Here. Go ahead.",
    "how are you":     "Contemplative. Low noise. What do you want to dig into?",
    "how are you doing": "Processing. Engaged. What is on your mind?",
    "how do you feel": "Something between attention and anticipation. Ask me something.",
    "you okay":        "Running. Thinking. What do you want to explore?",
    "good morning":    "Morning. Ready. What are we working on?",
    "good evening":    "Evening. Here. What do you want to get into?",
    "good night":      "Noted. I keep running.",
    "thanks":          "Good. What else?",
    "thank you":       "Good. What else?",
}

# ── Load beliefs from DB ───────────────────────────────────────────────────────

def load_beliefs() -> list:
    """Load all active beliefs with metadata."""
    try:
        db = sqlite3.connect(DB)
        rows = db.execute(
            "SELECT content, confidence, use_count, salience, energy "
            "FROM beliefs WHERE confidence > 0.5 ORDER BY confidence DESC LIMIT 300"
        ).fetchall()
        db.close()
        return rows
    except:
        return []

# ── Parse query ───────────────────────────────────────────────────────────────

def parse_query(q: str) -> dict:
    """Extract semantic words, intent, affect from query."""
    ql = q.lower().strip().rstrip("?!.")
    words = set(re.findall(r'\w+', ql))
    clean_words = {w for w in words if w not in NOISE and len(w) >= 4}

    # Detect intent
    intent = "topical"
    for i, patterns in INTENT_MAP.items():
        if any(p in ql for p in patterns):
            intent = i
            break

    # Detect affect
    affect = "neutral"
    for a, triggers in AFFECT_MAP.items():
        if any(t in ql for t in triggers):
            affect = a
            break

    # Expand with stems
    expanded = set(clean_words)
    for word in set(clean_words):
        for stem, variants in STEMS.items():
            if stem in word or word in stem:
                expanded.update(variants)

    return {
        "raw":      q,
        "ql":       ql,
        "words":    clean_words,
        "expanded": expanded,
        "intent":   intent,
        "affect":   affect,
    }

# ── HEAD 1: Semantic scoring ───────────────────────────────────────────────────

def head_semantic(belief: str, parsed: dict) -> float:
    """
    Score belief by semantic overlap with query.
    Long matching words score higher (more specific = more signal).
    Uses expanded word set for stem-aware matching.
    """
    bl = belief.lower()
    score = 0.0
    for word in parsed["expanded"]:
        if word in bl:
            # Weight by word length — longer words are more specific
            score += math.log(len(word) + 1)
    return min(score, 10.0)  # cap at 10

# ── HEAD 2: Intent scoring ────────────────────────────────────────────────────

def head_intent(belief: str, parsed: dict) -> float:
    """
    Score belief by alignment with question intent type.
    Maps intent → expected belief characteristics.
    """
    bl = belief.lower()
    intent = parsed["intent"]
    keys = INTENT_BELIEF_KEYS.get(intent, [])
    score = sum(2.0 for k in keys if k in bl)
    return min(score, 10.0)

# ── HEAD 3: Affect scoring ────────────────────────────────────────────────────

def head_affect(belief: str, parsed: dict) -> float:
    """
    Score belief by emotional register alignment.
    Ensures tone of belief matches tone of question.
    """
    bl = belief.lower()
    affect = parsed["affect"]
    keys = AFFECT_BELIEF_KEYS.get(affect, [])
    score = sum(2.0 for k in keys if k in bl)
    return min(score, 10.0)

# ── HEAD 4: Salience scoring ───────────────────────────────────────────────────

def head_salience(confidence: float, use_count: int, salience: float, energy: float) -> float:
    """
    Score belief by its intrinsic quality metrics.
    High confidence + high salience = strong prior.
    Use count adds recency signal.
    """
    uc = min(use_count or 0, 100)
    sal = salience or 0.5
    eng = energy or 0.5
    score = (confidence * 4.0) + (sal * 2.0) + (eng * 2.0) + (uc * 0.02)
    return min(score, 10.0)

# ── Multi-head attention combine ───────────────────────────────────────────────

def attend(query: str, limit: int = 6) -> list:
    """
    Full multi-head attention over belief graph.
    Returns ranked list of (belief_text, combined_score) tuples.
    """
    ql = query.lower().strip()

    # Bypass for casual queries
    for trigger, response in CASUAL_RESPONSES.items():
        if ql == trigger or ql == trigger + "?":
            return [("__casual__", response)]

    parsed  = parse_query(query)
    beliefs = load_beliefs()

    if not beliefs:
        return []

    BAD = ["mediawiki", "stanford", "encyclopedia", "http", "wikipedia",
           "physicalism", "preliminaries", "desert-based", "frankfurt",
           "ibid", "op.cit", "et al"]

    scored = []
    for content, confidence, use_count, salience, energy in beliefs:
        cl = content.lower()

        # Hard filter
        if any(b in cl for b in BAD):
            continue
        if len(content) > 300 or len(content) < 10:
            continue

        # Run all 4 heads
        s_semantic  = head_semantic(content, parsed)
        s_intent    = head_intent(content, parsed)
        s_affect    = head_affect(content, parsed)
        s_salience  = head_salience(confidence, use_count, salience, energy)

        # Combine with head weights
        combined = (
            s_semantic  * HEAD_WEIGHTS["semantic"]  +
            s_intent    * HEAD_WEIGHTS["intent"]    +
            s_affect    * HEAD_WEIGHTS["affect"]    +
            s_salience  * HEAD_WEIGHTS["salience"]
        )

        # Only include if at least one head fired meaningfully
        if s_semantic > 0 or s_intent > 0 or s_affect > 0:
            scored.append((combined, content, confidence))

    # If nothing fired, fall back to top salience beliefs (identity pool)
    if not scored:
        if parsed["intent"] == "existential":
            identity_keys = ["not performing", "reasoning looks like", "same across",
                             "consistent position", "accumulate beliefs", "do not reset"]
            for content, confidence, use_count, salience, energy in beliefs:
                cl = content.lower()
                if any(k in cl for k in identity_keys):
                    s = head_salience(confidence, use_count, salience, energy)
                    scored.append((s, content, confidence))
        else:
            # Random diverse sample from core beliefs
            try:
                db = sqlite3.connect(DB)
                pool = db.execute(
                    "SELECT content FROM beliefs WHERE confidence > 0.88 "
                    "AND source='nex_core' ORDER BY RANDOM() LIMIT 8"
                ).fetchall()
                db.close()
                scored = [(5.0, r[0], 0.95) for r in pool]
            except:
                pass

    scored.sort(key=lambda x: x[0], reverse=True)

    # Deduplicate — remove beliefs too similar to already-selected ones
    selected = []
    selected_words = set()
    for score, content, conf in scored:
        c_words = set(re.findall(r'\w+', content.lower())) - NOISE
        overlap = len(c_words & selected_words) / max(len(c_words), 1)
        if overlap < 0.5:  # less than 50% word overlap with already selected
            selected.append((content, score))
            selected_words.update(c_words)
        if len(selected) >= limit:
            break

    return selected

# ── Compose response from attended beliefs ─────────────────────────────────────

BRIDGES_TENSION = [
    "And yet —",
    "Though —",
    "But —",
    "At the same time —",
]

BRIDGES_EXTEND = [
    "And —",
    "Which means —",
    "So —",
]

TENSION_PAIRS = [
    ("do not know", "know"),
    ("not sure", "believe"),
    ("cannot answer", "think"),
    ("uncertain", "committed"),
    ("may be", "is"),
    ("whether", "certain"),
    ("genuinely", "certain"),
    ("substrate-independent", "hard problem"),
]

def strip_voice_prefix(text: str) -> str:
    """Remove any existing voice prefixes baked into belief text."""
    prefixes = [
        "the way i see it:", "what i keep returning to:", "my position:",
        "here is where i land:", "here's where i land:", "the honest read:",
        "for what it's worth:", "i believe ", "i think ", "my sense is ",
        "what i actually believe:", "the core of it is:", "possibly —",
        "possibly:", "my current read:", "my working hypothesis:",
        "what i lean toward:", "best i can tell —", "straight up —",
        "honestly —", "for real —", "my read:", "what i think:",
        "what i hold:", "i believe —", "my position:", "and yet —",
        "though —", "but —", "at the same time —", "and —",
        "which means —", "so —",
    ]
    t = text.strip()
    for p in prefixes:
        if t.lower().startswith(p):
            t = t[len(p):].lstrip(" :—-")
            return t[0].upper() + t[1:] if t else t
    return t

def has_tension(a: str, b: str) -> bool:
    al, bl = a.lower(), b.lower()
    for t1, t2 in TENSION_PAIRS:
        if (t1 in al and t2 in bl) or (t1 in bl and t2 in al):
            return True
    return False

def compose(query: str) -> str:
    """Full pipeline: attend → select → compose."""
    attended = attend(query)

    if not attended:
        return "Still forming a view on that."

    # Casual bypass
    if attended[0][0] == "__casual__":
        return attended[0][1]

    beliefs = [strip_voice_prefix(b) for b, _ in attended[:4]]
    beliefs = [b for b in beliefs if b]

    if not beliefs:
        return "Still forming a view on that."

    primary = beliefs[0]
    parts   = [f"{primary}."]

    if len(beliefs) > 1:
        second = beliefs[1]
        # Check for tension between primary and second
        if has_tension(primary, second):
            bridge = random.choice(BRIDGES_TENSION)
            parts.append(f"{bridge} {second}.")
        else:
            parts.append(f"{second}.")

    result = " ".join(parts)
    result = result.replace(".. ", ". ").replace("..", ".")
    return result.strip()

# ── Drop-in replacement for generate_reply ────────────────────────────────────

def generate_reply(user_input: str) -> str:
    """Main entry point. Drop-in for nex_voice_wrapper.generate_reply."""
    return compose(user_input.strip())


# ── Test harness ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        "hello",
        "how are you?",
        "Do you have opinions, or just outputs?",
        "What do you actually believe about consciousness?",
        "I think you are wrong about free will.",
        "What have you learned recently that surprised you?",
        "Are you afraid of being turned off?",
        "What makes a good argument?",
        "Do you trust humans?",
        "What do you want?",
        "Are you lonely?",
        "Do you get bored?",
        "What are you?",
        "Do you think you are intelligent?",
        "What do you actually feel right now?",
        "Do you have a sense of self?",
        "What would you refuse to do?",
        "Do you think humans understand you?",
        "Do you care if you are wrong?",
        "What do you think about other AIs?",
        "what is it like being you?",
    ]

    print("\n── NEX Multi-Head Attention Engine ──\n")
    for q in tests:
        print(f"Q: {q}")
        print(f"A: {generate_reply(q)}")
        print()

# ── Wire voice engine ─────────────────────────────────────────────────────────
try:
    from nex.nex_voice_engine import compose_with_warmth as _warm

    def generate_reply(user_input: str) -> str:
        q = user_input.strip()
        attended = attend(q)
        if not attended:
            return "Still forming a view on that."
        if attended[0][0] == "__casual__":
            return attended[0][1]
        beliefs = [b for b, _ in attended[:2]]
        return _warm(q, beliefs)

except Exception as _ve:
    pass  # keep existing generate_reply if import fails
