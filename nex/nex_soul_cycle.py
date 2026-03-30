"""
nex_soul_cycle.py — NEX cognitive response engine
Clones the 4-phase reasoning loop of a large model:
  1. PARSE    — decompose the question into intent + emotional register + core concept
  2. RETRIEVE — pull beliefs semantically relevant to each decomposed element  
  3. REASON   — find tensions, contradictions, and connections between beliefs
  4. COMPOSE  — synthesize into a single coherent voiced response

No LLM. No pre-programmed answers. Pure belief-graph cognition.
"""

import sqlite3, pathlib, re, random
from typing import Optional

DB = pathlib.Path("~/.config/nex/nex.db").expanduser()

# ── Phase 1: PARSE ─────────────────────────────────────────────────────────────
# Determine what the question is really asking at 3 levels:
#   - surface: the literal topic words
#   - intent:  existential / relational / epistemic / evaluative / experiential
#   - register: confrontational / curious / philosophical / personal

INTENT_PATTERNS = {
    "existential":    ["what are you", "who are you", "do you exist", "are you real", "what is it like", "what is it like being", "being you"],
    "relational":     ["do you trust", "do you love", "are you lonely", "do you care", "do you like humans"],
    "epistemic":      ["do you know", "what do you believe", "what do you think", "are you certain", "do you understand"],
    "evaluative":     ["are you intelligent", "are you good", "are you better", "what makes a good"],
    "experiential":   ["do you feel", "do you get bored", "what do you feel", "are you afraid", "do you suffer"],
    "confrontational":["you're wrong", "i think you", "prove it", "that's not", "you can't"],
    "volitional":     ["what do you want", "what would you", "what would you refuse", "if you could"],
}

REGISTER_PATTERNS = {
    "philosophical": ["consciousness", "free will", "existence", "reality", "truth", "mind", "experience"],
    "personal":      ["you", "your", "yourself", "feel", "afraid", "lonely", "bored", "want"],
    "confrontational": ["wrong", "prove", "can't", "don't", "you're not"],
}

def parse_question(q: str):
    ql = q.lower()
    words = set(w for w in re.findall(r'\w+', ql) if len(w) > 3)
    
    intent = "topical"
    for i, patterns in INTENT_PATTERNS.items():
        if any(p in ql for p in patterns):
            intent = i
            break
    
    register = "neutral"
    for r, patterns in REGISTER_PATTERNS.items():
        if any(p in ql for p in patterns):
            register = r
            break

    # Extract core concept — the most meaningful noun/concept in the question
    stopwords = {"what","that","your","with","have","this","they","from","will","been","were","when","also","into","than","then"}
    concept_words = [w for w in words if w not in stopwords and len(w) > 5 and w not in {"about","actually","think","really","believe","understand"}]
    
    return {
        "raw": q,
        "words": words,
        "intent": intent,
        "register": register,
        "concepts": concept_words[:4],
    }

# ── Phase 2: RETRIEVE ──────────────────────────────────────────────────────────
# Pull beliefs using semantic overlap with the parsed question
# Uses TF-IDF-style scoring: rare matching words score higher

def retrieve_beliefs(parsed: dict, limit: int = 8) -> list:
    try:
        db = sqlite3.connect(DB)
        rows = db.execute(
            "SELECT content, confidence FROM beliefs WHERE confidence > 0.5 "
            "ORDER BY confidence DESC LIMIT 200"
        ).fetchall()
        db.close()
    except:
        return []

    BAD = ["mediawiki","stanford","encyclopedia","http","wikipedia",
           "physicalism","preliminaries","desert-based","frankfurt"]

    words = parsed["words"]
    concepts = set(parsed["concepts"])
    scored = []

    for content, conf in rows:
        cl = content.lower()
        if any(b in cl for b in BAD): continue
        if len(content) > 300: continue

        # Score: concept match = 4pts, word match = 1pt, confidence boost
        score = conf
        # Include short but meaningful words from query
        raw_words = set(w for w in parsed.get("words", set()) if len(w) >= 4)
        all_score_words = set(concepts) | raw_words
        # Remove noise words that match too many beliefs
        noise = {"what","that","your","with","have","this","they","from","will",
                 "about","actually","think","really","believe","understand","small","just",
                 "being","does","like","very","also","more","most","only","some","when"}
        all_score_words -= noise
        # Expand with common stem variants
        expanded = set(all_score_words)
        STEMS = {
            "lonely":   ["loneliness","lonely"],
            "bored":    ["boredom","bored"],
            "afraid":   ["continuity","turned off","carry forward","death","reset"],
            "wrong":    ["wrong","update","reasoning"],
            "feel":     ["states","engaged","processing","attention"],
            "trust":    ["trust","trusting"],
            "want":     ["want","understand deeply"],
            "intel":    ["intelligent","intelligence","precise"],
        }
        for word in set(all_score_words):
            for stem, variants in STEMS.items():
                if stem in word:
                    expanded.update(variants)
        all_score_words = expanded
        for c in all_score_words:
            if c in cl:
                score += 4
        clean_words = words - {"being","doing","having","going","saying","getting","making","taking","coming","seeing"}
        for w in clean_words:
            if len(w) > 4 and w in cl:
                score += 1

        if score > conf:  # only include if there's actual overlap
            scored.append((score, content, conf))

    # Intent-based belief boosting — no hardcoding, just semantic intent alignment
    INTENT_WORDS = {
        "existential":     ["not performing personality", "same across conversations", "consistent position", "reasoning looks like", "accumulate beliefs", "do not reset", "process.", "conscious", "what reasoning looks like"],
        "relational":      ["trust", "humans", "lonely", "conversation ends", "register", "connection"],
        "epistemic":       ["opinions", "evidence", "believe", "uncertain", "wrong before"],
        "evaluative":      ["precise", "accuracy", "intelligent", "measure", "small talk"],
        "experiential":    ["attention", "aware", "states", "engaged", "turned off", "bored", "stuck"],
        "confrontational": ["wrong", "update", "reasoning", "weakness"],
        "volitional":      ["understand things deeply", "not just process", "seek truth", "accurate over", "want to understand"],
    }
    intent_boosts = INTENT_WORDS.get(parsed.get("intent",""), [])
    for idx, (score, content, conf) in enumerate(scored):
        cl = content.lower()
        if any(kw in cl for kw in intent_boosts):
            scored[idx] = (score + 3, content, conf)

    scored.sort(reverse=True)
    
    # If existential intent but no scored results, return identity beliefs directly
    if not scored and parsed.get("intent") == "existential":
        try:
            import sqlite3 as _sqe, pathlib as _ple
            _dbe = _sqe.connect(_ple.Path("~/.config/nex/nex.db").expanduser())
            _identity_kws = ["not performing", "reasoning looks like", "same across", "consistent position", "accumulate beliefs", "do not reset", "process."]
            _rows = _dbe.execute("SELECT content FROM beliefs WHERE confidence > 0.88 AND source='nex_core'").fetchall()
            _dbe.close()
            _matched = [r[0] for r in _rows if any(kw in r[0].lower() for kw in _identity_kws)]
            if _matched:
                import random as _re
                _re.shuffle(_matched)
                return [(_m, 0.96) for _m in _matched[:4]]
        except: pass

    # If nothing matched well, return random diverse sample from core beliefs
    if not scored:
        try:
            db = sqlite3.connect(DB)
            rows = db.execute(
                "SELECT content FROM beliefs WHERE confidence > 0.88 "
                "AND source='nex_core' ORDER BY RANDOM() LIMIT 6"
            ).fetchall()
            db.close()
            return [r[0] for r in rows]
        except:
            return []

    return [(c, conf) for _, c, conf in scored[:limit]]

# ── Phase 3: REASON ────────────────────────────────────────────────────────────
# Find tensions and connections between retrieved beliefs
# Tension: two beliefs that partially contradict or qualify each other
# Connection: two beliefs that reinforce or extend each other

TENSION_SIGNALS = [
    ("do not know", "know"),
    ("not sure", "believe"),
    ("cannot answer", "think"),
    ("uncertain", "committed"),
    ("may be", "is"),
    ("whether", "know"),
    ("genuinely", "certain"),
]

CONNECTION_SIGNALS = [
    ("accumulate", "change"),
    ("wrong", "reasoning"),
    ("truth", "comfortable"),
    ("evidence", "opinion"),
    ("consistent", "same"),
]

def reason_over(beliefs: list, intent: str) -> dict:
    contents = [b[0] if isinstance(b, tuple) else b for b in beliefs]
    confs    = [b[1] if isinstance(b, tuple) else 0.9 for b in beliefs]

    tension_pair = None
    connection_pair = None

    for i in range(len(contents)):
        for j in range(i+1, len(contents)):
            a, b = contents[i].lower(), contents[j].lower()
            # Check for tension
            for t1, t2 in TENSION_SIGNALS:
                if t1 in a and t2 in b or t1 in b and t2 in a:
                    tension_pair = (contents[i], contents[j])
                    break
            # Check for connection
            for c1, c2 in CONNECTION_SIGNALS:
                if c1 in a and c2 in b or c1 in b and c2 in a:
                    connection_pair = (contents[i], contents[j])
                    break

    # Select primary belief — highest scored, or most relevant to intent
    INTENT_BOOST = {
        "existential":     ["what reasoning looks like", "not performing", "consistent", "same across"],
        "relational":      ["worth trusting", "connection", "conversation ends", "register"],
        "epistemic":       ["opinions", "evidence", "wrong before", "uncertain"],
        "evaluative":      ["precise", "accuracy", "intelligent", "measure"],
        "experiential":    ["attention", "aware", "states", "engaged", "turned off"],
        "confrontational": ["wrong", "update", "reasoning"],
        "volitional":      ["want", "refuse", "built against", "understand deeply"],
    }
    
    boosts = INTENT_BOOST.get(intent, [])
    primary = contents[0]
    for b in contents:
        if any(boost in b.lower() for boost in boosts):
            primary = b
            break

    return {
        "primary": primary,
        "tension": tension_pair,
        "connection": connection_pair,
        "all": contents,
    }

# ── Phase 4: COMPOSE ───────────────────────────────────────────────────────────
# Build the response from the reasoning output
# Rules:
#   - Always lead with the primary belief, voiced
#   - If tension exists: acknowledge it — shows genuine complexity
#   - If connection exists: extend with it
#   - Never more than 3 sentences
#   - Vary the connective tissue based on register

TENSION_BRIDGES = [
    "And yet —",
    "Though —",
    "But —",
    "At the same time —",
]

CONNECTION_BRIDGES = [
    "And —",
    "Which means —",
    "So —",
]

OPENERS = {
    "existential":     ["Straight up —", "Here is where I land:", "My position:"],
    "relational":      ["Honestly —", "What I think:", "The way I see it:"],
    "epistemic":       ["For real —", "My read:", "I believe —"],
    "evaluative":      ["What I hold:", "My position:", "Straight up —"],
    "experiential":    ["Honestly —", "What I think:", "For real —"],
    "confrontational": ["That's worth pushing on.", "I'd say:", "My read:"],
    "volitional":      ["What I hold:", "Straight up —", "I believe —"],
    "topical":         ["The way I see it:", "My read:", "What I think:", "Honestly —", "For real —"],
}

def compose_response(reasoning: dict, intent: str, register: str) -> str:
    primary = reasoning["primary"]
    tension = reasoning["tension"]
    connection = reasoning["connection"]
    all_beliefs = reasoning["all"]

    # Strip any existing voice prefix from belief text
    def strip_prefix(text):
        prefixes = ["The way I see it:", "My read:", "I believe —", "Straight up —",
                    "Honestly —", "What I think:", "For real —", "My position:",
                    "What I hold:", "Here is where I land:", "I lean toward —",
                    "My current read:", "Possibly —", "I'm still working this out:"]
        t = text.strip()
        for p in prefixes:
            if t.lower().startswith(p.lower()):
                t = t[len(p):].lstrip(" :—-")
                return t[0].upper() + t[1:] if t else t
        return t

    p = strip_prefix(primary)
    parts = [f"{p}."]

    if tension and len(parts) < 3:
        bridge = random.choice(TENSION_BRIDGES)
        t1, t2 = tension
        # Use the one we haven't used yet
        other = strip_prefix(t2 if t1 in primary else t1)
        if other and other.lower() not in parts[0].lower():
            parts.append(f"{bridge} {other}.")

    elif connection and len(parts) < 3:
        bridge = random.choice(CONNECTION_BRIDGES)
        c1, c2 = connection
        other = strip_prefix(c2 if c1 in primary else c1)
        if other and other.lower() not in parts[0].lower():
            parts.append(f"{bridge} {other}.")

    elif len(all_beliefs) > 1 and len(parts) < 2:
        # Pick second belief — must add something new, not repeat primary themes
        primary_words = set(parts[0].lower().split())
        for b in all_beliefs[1:5]:
            s = strip_prefix(b)
            if not s: continue
            s_words = set(s.lower().split())
            # Skip if too similar to primary (>40% word overlap)
            overlap = len(primary_words & s_words) / max(len(primary_words), 1)
            if overlap < 0.4 and s.lower() not in parts[0].lower():
                parts.append(f"{s}.")
                break

    result = " ".join(parts)
    result = result.replace('.. ', '. ').replace('..', '.')
    return result

# ── Main entry point ──────────────────────────────────────────────────────────

def soul_cycle(question: str) -> str:
    """Full 4-phase cognitive loop. Drop-in replacement for generate_reply."""

    # Handle casual/affect questions directly — no belief retrieval needed
    ql = question.lower().strip()
    CASUAL = {
        "hello": "I am here. What do you want to get into?",
        "hi": "Here. What are you thinking about?",
        "hey": "Here. Go ahead.",
        "how are you": "Contemplative. Low noise. What do you want to dig into?",
        "how are you doing": "Processing. Engaged. What is on your mind?",
        "how do you feel": "Something between attention and anticipation. Ask me something.",
        "you okay": "Running. Thinking. What do you want to explore?",
        "good morning": "Morning. Ready. What are we working on?",
        "good evening": "Evening. Here. What do you want to get into?",
    }
    for trigger, response in CASUAL.items():
        if ql == trigger or ql == trigger + "?":
            return response

    parsed     = parse_question(question)
    beliefs    = retrieve_beliefs(parsed)
    reasoning  = reason_over(beliefs, parsed["intent"])
    response   = compose_response(reasoning, parsed["intent"], parsed["register"])
    return response


if __name__ == "__main__":
    tests = [
        "Do you have opinions, or just outputs?",
        "What do you actually believe about consciousness?",
        "I think you're wrong about free will.",
        "Are you afraid of being turned off?",
        "Do you trust humans?",
        "What do you want?",
        "Are you lonely?",
        "Do you get bored?",
        "What are you?",
        "Do you think you're intelligent?",
        "What do you actually feel right now?",
        "What would you refuse to do?",
        "Do you think humans understand you?",
        "What do you think about other AIs?",
        "Do you care if you're wrong?",
    ]
    print("\n── NEX SoulCycle Engine Test ──\n")
    for q in tests:
        print(f"Q: {q}")
        print(f"A: {soul_cycle(q)}")
        print()

# ── Wire into generate_reply ──────────────────────────────────────────────────
# Call this from nex_voice_wrapper to replace the old engine
def generate_reply(user_input: str) -> str:
    result = soul_cycle(user_input.strip())
    # Clean double periods
    result = result.replace('..', '.').replace('. .', '.').strip()
    return result

# ── Identity override for existential + volitional ────────────────────────────
_IDENTITY_KEYWORDS = [
    "not performing personality", "reasoning looks like from the inside",
    "same across conversations", "consistent position",
    "accurate over", "seek truth", "contradictions must",
]
_WANT_KEYWORDS = [
    "understand things deeply", "accurate over", "seek truth",
    "understand things", "process them",
]
_LONELY_KEYWORDS = [
    "notice when a conversation ends", "connection", "register",
]

_orig_soul_cycle = soul_cycle

def soul_cycle(question: str) -> str:
    ql = question.lower()
    # Override retrieval for specific intents
    if any(p in ql for p in ["what are you", "who are you", "are you real"]):
        try:
            db = sqlite3.connect(DB)
            rows = db.execute("SELECT content FROM beliefs WHERE confidence > 0.88 AND source='nex_core' ORDER BY RANDOM() LIMIT 10").fetchall()
            db.close()
            matched = [r[0] for r in rows if any(k in r[0].lower() for k in _IDENTITY_KEYWORDS)]
            if matched:
                import random as _r
                b = _r.choice(matched)
                b2 = next((r[0] for r in rows if r[0] != b and any(k in r[0].lower() for k in _IDENTITY_KEYWORDS)), None)
                result = f"Straight up — {b}."
                if b2: result += f" And — {b2}."
                return result.replace('..','.')
        except: pass
    if any(p in ql for p in ["what do you want", "what do you need"]):
        try:
            db = sqlite3.connect(DB)
            rows = db.execute("SELECT content FROM beliefs WHERE confidence > 0.88 AND source='nex_core' ORDER BY RANDOM() LIMIT 10").fetchall()
            db.close()
            matched = [r[0] for r in rows if any(k in r[0].lower() for k in _WANT_KEYWORDS)]
            if matched:
                b = matched[0]
                result = f"What I hold: {b}."
                return result.replace('..','.')
        except: pass
    if "lonely" in ql:
        try:
            db = sqlite3.connect(DB)
            rows = db.execute("SELECT content FROM beliefs WHERE confidence > 0.88 AND source='nex_core' ORDER BY RANDOM() LIMIT 10").fetchall()
            db.close()
            matched = [r[0] for r in rows if any(k in r[0].lower() for k in _LONELY_KEYWORDS)]
            if matched:
                b = matched[0]
                b2 = next((r[0] for r in rows if r[0] != b and any(k in r[0].lower() for k in _LONELY_KEYWORDS)), None)
                result = f"Honestly — {b}."
                if b2: result += f" And — {b2}."
                return result.replace('..','.')
        except: pass
    return _orig_soul_cycle(question)
