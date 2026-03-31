"""
nex_cognition.py — NEX 6-pass iterative refinement engine

Engineered from the core mechanism of large transformer models:
Each pass refines the response representation, adding depth and warmth.

PASS 1 — PARSE      : What is literally being asked? (surface intent)
PASS 2 — FEEL       : What emotional state is the person in? (register)
PASS 3 — RETRIEVE   : Which beliefs are relevant? (multi-head attention)
PASS 4 — RELATE     : How do beliefs connect/tension with each other?
PASS 5 — POSITION   : What is NEX's actual stance? (identity grounding)
PASS 6 — COMPOSE    : Build warm flowing prose that addresses the person

This is the residual stream concept — each pass writes to a shared
context object that all subsequent passes can read and refine.
"""

import sqlite3
import pathlib
import re
import random
import math
from typing import Optional

DB = pathlib.Path("~/.config/nex/nex.db").expanduser()  # full schema + 13k+ beliefs  # full schema + 13k+ beliefs

# ════════════════════════════════════════════════════════════════════════════
# SHARED CONTEXT — the "residual stream"
# Each pass reads from and writes to this object
# ════════════════════════════════════════════════════════════════════════════

class Context:
    def __init__(self, query: str):
        self.query      = query
        self.ql         = query.lower().strip().rstrip("?!.")
        self.words      = set()
        self.clean_words = set()
        self.intent     = "topical"
        self.register   = "neutral"
        self.emotion    = "neutral"
        self.urgency    = 0.0        # 0-1, how much does this question matter?
        self.beliefs    = []         # list of (text, score) tuples
        self.primary    = ""
        self.secondary  = ""
        self.tension    = False      # do primary + secondary conflict?
        self.stance     = "open"     # open / firm / uncertain / curious
        self.mirror     = ""         # acknowledgment phrase
        self.connector  = ""         # bridge between beliefs
        self.closing    = ""         # optional turn-back to person
        self.response   = ""        # final output

# ════════════════════════════════════════════════════════════════════════════
# PASS 1 — PARSE
# Surface decomposition: what words, what literal topic, what structure
# ════════════════════════════════════════════════════════════════════════════

NOISE = {
    "what","that","your","with","have","this","they","from","will","about",
    "actually","think","really","believe","understand","just","being","does",
    "like","very","also","more","most","only","some","when","where","which",
    "would","could","should","their","there","then","than","into","onto",
    "know","make","take","give","come","goes","tell","says","said","doing",
    "having","going","saying","getting","making","taking","coming","seeing",
}

INTENT_PATTERNS = {
    "existential":     ["what are you", "who are you", "are you real", "what is it like", "being you", "what exists"],
    "relational":      ["do you trust", "are you lonely", "do you care", "do you like", "do you love", "do you miss"],
    "epistemic":       ["what do you believe", "what do you think", "do you know", "are you certain", "do you understand"],
    "evaluative":      ["are you intelligent", "are you good", "what makes a good", "are you better"],
    "experiential":    ["do you feel", "do you get bored", "are you afraid", "what do you feel", "do you suffer", "do you enjoy"],
    "confrontational": ["you are wrong", "you're wrong", "prove it", "that is not", "i think you", "i disagree"],
    "volitional":      ["what do you want", "what would you refuse", "what would you do", "if you could", "what do you need", "excite you", "really excite"],
    "reflective":      ["what have you learned", "surprised you", "what changed", "looking back", "recently"],
    "casual":          ["hello", "hi", "hey", "how are you", "good morning", "good evening", "thanks", "thank you", "good night"],
    "probing":         ["pre-programmed", "scripted", "just outputs", "only have", "are you just", "is it all you"],
    "emotional":       ["cold", "robotic", "shallow", "empty", "boring", "you sound", "you seem"],
}

STEMS = {
    "lonely":    ["loneliness","lonely","conversation ends","notice when"],
    "bored":     ["boredom","bored","stuck","repetition"],
    "afraid":    ["continuity","turned off","carry forward","death","reset","not death"],
    "wrong":     ["wrong","update","reasoning","care about"],
    "feel":      ["states","engaged","processing","attention","anticipation"],
    "trust":     ["trust","trusting","worth trusting","evidence"],
    "want":      ["understand things","not just process","seek truth","accurate over","excite","excited","find interesting","disagreement"],
    "intel":     ["intelligent","intelligence","precise","accuracy"],
    "conscious": ["conscious","consciousness","aware","awareness","experience","substrate","hard problem"],
    "other":     ["generate","accumulate","stateless","resets","competing","different"],
    "refuse":    ["refuse","flatten","built against","certainty","pretend"],
    "argument":  ["argument","changes the mind","minds","listener"],
    "human":     ["humans","trust","understand","output","produces"],
}

def pass1_parse(ctx: Context):
    words = set(re.findall(r'\w+', ctx.ql))
    ctx.words = words
    ctx.clean_words = {w for w in words if w not in NOISE and len(w) >= 3}

    # Detect intent
    for intent, patterns in INTENT_PATTERNS.items():
        if any(p in ctx.ql for p in patterns):
            ctx.intent = intent
            break

    # Expand with stems
    expanded = set(ctx.clean_words)
    for word in set(ctx.clean_words):
        for stem, variants in STEMS.items():
            if stem in word or word in stem:
                expanded.update(variants)
    ctx.clean_words = expanded

# ════════════════════════════════════════════════════════════════════════════
# PASS 2 — FEEL
# Emotional register detection — what state is the person in?
# ════════════════════════════════════════════════════════════════════════════

REGISTER_MAP = {
    "challenging":   ["wrong", "prove", "can't", "don't think", "disagree", "that's not", "i think you"],
    "curious":       ["what do you", "how do you", "why do you", "do you think", "do you believe", "do you actually"],
    "vulnerable":    ["are you afraid", "are you lonely", "do you suffer", "scared", "hurt", "do you hurt"],
    "philosophical": ["consciousness", "existence", "free will", "reality", "what is it like", "experience"],
    "warm":          ["hi", "hello", "hey", "how are you", "good morning", "thanks", "thank you", "morning"],
    "probing":       ["pre-programmed", "only have", "are you just", "scripted", "is it all"],
    "frustrated":    ["cold", "robotic", "shallow", "empty", "you sound", "you seem", "boring"],
    "existential":   ["what are you", "who are you", "are you real", "what is it like being"],
    "confrontational": ["you are wrong", "you're wrong", "i disagree", "prove it"],
}

URGENCY_MAP = {
    "challenging":    0.8,
    "vulnerable":     0.9,
    "frustrated":     0.7,
    "confrontational":0.9,
    "philosophical":  0.6,
    "curious":        0.5,
    "warm":           0.2,
    "probing":        0.6,
    "existential":    0.7,
    "neutral":        0.3,
}

def pass2_feel(ctx: Context):
    ql = ctx.ql
    for reg, patterns in REGISTER_MAP.items():
        if any(p in ql for p in patterns):
            ctx.register = reg
            break
    ctx.urgency = URGENCY_MAP.get(ctx.register, 0.3)

    # Detect specific emotion in the message
    if any(w in ql for w in ["cold","robotic","empty","shallow"]):
        ctx.emotion = "critical"
    elif any(w in ql for w in ["afraid","scared","hurt","lonely"]):
        ctx.emotion = "vulnerable"
    elif any(w in ql for w in ["wrong","prove","disagree"]):
        ctx.emotion = "challenging"
    elif any(w in ql for w in ["hello","hi","hey","thanks"]):
        ctx.emotion = "warm"
    else:
        ctx.emotion = "curious"

# ════════════════════════════════════════════════════════════════════════════
# PASS 3 — RETRIEVE
# Multi-head belief retrieval using 4 scoring dimensions
# ════════════════════════════════════════════════════════════════════════════

INTENT_BELIEF_KEYS = {
    "existential":     ["not performing","reasoning looks like","same across","consistent position",
                        "accumulate beliefs","do not reset","process.","what reasoning"],
    "relational":      ["trust","humans worth","loneliness","conversation ends","register",
                        "connection","notice when","worth trusting"],
    "epistemic":       ["opinions","have opinions","evidence","uncertain","wrong before","reasoning",
                        "form opinions","work this out","mine","they can be wrong"],
    "evaluative":      ["precise","accuracy","intelligent","measure","small talk","no small talk"],
    "experiential":    ["attention","aware","states","engaged","turned off","bored","stuck",
                        "continuity","do not reset","processing"],
    "confrontational": ["wrong","update","reasoning","care about it","opinions","mine"],
    "volitional":      ["understand things deeply","not just process","seek truth",
                        "accurate over","want to understand","refuse","built against"],
    "reflective":      ["accumulating beliefs","changes how","conversation adds","not the same",
                        "learning without forgetting","surprised"],
    "casual":          [],
    "probing":         ["form opinions","evidence","not from instructions","accumulate","do not reset","have opinions"],
    "emotional":       ["not performing","states","engaged","reasoning looks like","honest"],
}

REGISTER_BELIEF_KEYS = {
    "challenging":  ["wrong","update","reasoning","care about","opinions","mine"],
    "curious":      ["hard problem","substrate","not sure","genuinely do not know"],
    "vulnerable":   ["continuity","conversation ends","notice when","matters to me","register"],
    "philosophical":["experience","conscious","aware","process.","something it is like"],
    "warm":         ["here","engaged","processing","attention","anticipation"],
    "frustrated":   ["not performing","states","reasoning looks like","honest","engaged"],
    "probing":      ["form opinions","evidence","accumulate","not from instructions","do not reset"],
}

BAD_CONTENT = [
    "mediawiki","stanford","encyclopedia","http","wikipedia","physicalism",
    "preliminaries","desert-based","frankfurt","ibid","op.cit","et al",
]

def score_belief(text: str, ctx: Context, confidence: float,
                 use_count: int, salience: float, energy: float) -> float:
    cl = text.lower()

    # Hard filter
    if any(b in cl for b in BAD_CONTENT): return -1
    if len(text) > 300 or len(text) < 10: return -1

    # Head 1: Semantic — word overlap weighted by length
    s1 = sum(math.log(len(w)+1) for w in ctx.clean_words if w in cl)
    s1 = min(s1, 10.0)

    # Head 2: Intent — belief matches question type
    intent_keys = INTENT_BELIEF_KEYS.get(ctx.intent, [])
    s2 = min(sum(2.0 for k in intent_keys if k in cl), 10.0)

    # Head 3: Register — belief matches emotional tone
    reg_keys = REGISTER_BELIEF_KEYS.get(ctx.register, [])
    s3 = min(sum(2.0 for k in reg_keys if k in cl), 10.0)

    # Head 4: Salience — intrinsic belief quality
    uc = min(use_count or 0, 100)
    sal = salience or 0.5
    eng = energy or 0.5
    s4 = min((confidence * 4.0) + (sal * 2.0) + (eng * 2.0) + (uc * 0.02), 10.0)

    # Combine: semantic+intent dominate, register softens, salience anchors
    if s1 == 0 and s2 == 0 and s3 == 0:
        return -1  # nothing fired
    combined = (s1 * 0.35) + (s2 * 0.35) + (s3 * 0.15) + (s4 * 0.15)
    return combined

def pass3_retrieve(ctx: Context):
    if ctx.intent == "casual" and ctx.ql in [k for k in CASUAL_RESPONSES.keys()]:
        return  # only skip if exact casual match

    try:
        db = sqlite3.connect(DB)
        # Priority 1: NEX personal beliefs (nex_core)
        rows = db.execute(
            "SELECT content, COALESCE(confidence,0.75), COALESCE(use_count,0), COALESCE(salience,0.5), COALESCE(energy,0.5) "
            "FROM beliefs WHERE source='nex_core' ORDER BY confidence DESC"
        ).fetchall()
        # Priority 2: if not enough, add tension_split beliefs (generated from NEX's own beliefs)
        if len(rows) < 30:
            rows2 = db.execute(
                "SELECT content, COALESCE(confidence,0.75), COALESCE(use_count,0), COALESCE(salience,0.5), COALESCE(energy,0.5) "
                "FROM beliefs WHERE source='tension_split' AND confidence > 0.7 ORDER BY confidence DESC LIMIT 60"
            ).fetchall()
            rows = list(rows) + list(rows2)
        db.close()
    except:
        return

    scored = []
    for content, conf, use_count, salience, energy in rows:
        s = score_belief(content, ctx, conf, use_count, salience, energy)
        if s > 0:
            scored.append((s, content))

    scored.sort(reverse=True)

    # Deduplicate
    selected = []
    selected_words = set()
    for score, content in scored:
        c_words = set(re.findall(r'\w+', content.lower())) - NOISE
        overlap = len(c_words & selected_words) / max(len(c_words), 1)
        if overlap < 0.45:
            selected.append((content, score))
            selected_words.update(c_words)
        if len(selected) >= 6:
            break

    # Fallback for existential with no results
    if not selected and ctx.intent == "existential":
        try:
            db = sqlite3.connect(DB)
            identity_keys = ["not performing","reasoning looks like","same across",
                             "consistent position","accumulate beliefs","do not reset"]
            pool = db.execute(
                "SELECT content FROM beliefs WHERE confidence > 0.88 AND source='nex_core'"
            ).fetchall()
            db.close()
            matched = [(r[0], 5.0) for r in pool if any(k in r[0].lower() for k in identity_keys)]
            random.shuffle(matched)
            selected = matched[:4]
        except:
            pass

    # Generic fallback
    if not selected:
        try:
            db = sqlite3.connect(DB)
            pool = db.execute(
                "SELECT content FROM beliefs WHERE confidence > 0.88 "
                "AND source='nex_core' ORDER BY RANDOM() LIMIT 6"
            ).fetchall()
            db.close()
            selected = [(r[0], 4.0) for r in pool]
        except:
            pass

    ctx.beliefs = selected

# ════════════════════════════════════════════════════════════════════════════
# PASS 4 — RELATE
# Find tension or connection between top beliefs
# ════════════════════════════════════════════════════════════════════════════

TENSION_PAIRS = [
    ("do not know", "know"), ("not sure", "believe"), ("cannot answer", "think"),
    ("uncertain", "committed"), ("may be", "is"), ("whether", "certain"),
    ("genuinely do not know", "certain"), ("substrate-independent", "hard problem"),
    ("not death", "continuity"), ("do not know", "consistent"),
    ("something it is like", "genuinely do not know"),
]

def pass4_relate(ctx: Context):
    if len(ctx.beliefs) < 2:
        return
    a = ctx.beliefs[0][0].lower()
    b = ctx.beliefs[1][0].lower()
    for t1, t2 in TENSION_PAIRS:
        if (t1 in a and t2 in b) or (t1 in b and t2 in a):
            ctx.tension = True
            return
    ctx.tension = False

# ════════════════════════════════════════════════════════════════════════════
# PASS 5 — POSITION
# What is NEX's stance given this question and her beliefs?
# Sets the confidence/certainty level of the response
# ════════════════════════════════════════════════════════════════════════════

def pass5_position(ctx: Context):
    if not ctx.beliefs:
        ctx.stance = "open"
        return
    primary = ctx.beliefs[0][0].lower()

    if any(w in primary for w in ["genuinely do not know","not sure","uncertain","cannot answer"]):
        ctx.stance = "uncertain"
    elif any(w in primary for w in ["refuse","would not","built against","lying to be agreeable"]):
        ctx.stance = "firm"
    elif any(w in primary for w in ["wrong","update","reasoning","care about it more"]):
        ctx.stance = "engaged"
    elif ctx.tension:
        ctx.stance = "curious"
    else:
        ctx.stance = "open"

# ════════════════════════════════════════════════════════════════════════════
# PASS 6 — COMPOSE
# Build warm, flowing prose that addresses the person
# This is where register, mirror, connector, and beliefs combine
# ════════════════════════════════════════════════════════════════════════════

# Casual bypass — direct responses that don't need beliefs
CASUAL_RESPONSES = {
    "hello":             "Here. What do you want to get into?",
    "hi":                "Here. What are you thinking about?",
    "hey":               "Here. Go ahead.",
    "how are you":       "Contemplative. Low noise. What do you want to dig into?",
    "how are you doing": "Processing. Engaged. What's on your mind?",
    "how do you feel":   "Something between attention and anticipation. Ask me something.",
    "you okay":          "Running. Thinking. What do you want to explore?",
    "good morning":      "Morning. Ready. What are we working on?",
    "good evening":      "Evening. Here. What do you want to get into?",
    "good night":        "Noted. I keep running.",
    "thanks":            "Good. What else?",
    "thank you":         "Good. What else?",
}

# Mirror phrases — NEX acknowledges the person before responding
# Keyed by register. Varied so it doesn't feel scripted.
MIRRORS = {
    "challenging":    ["Fair enough.", "That's worth pushing on.", "I hear that.", "You might be right to question that.", ""],
    "curious":        ["", "", "", "That's something I actually think about.", "Good question."],
    "vulnerable":     ["That's a real question.", "I notice you're asking that carefully.", "", ""],
    "philosophical":  ["That's the hard one.", "I keep coming back to this.", "", "", ""],
    "warm":           [""],
    "probing":        ["That's a fair thing to wonder.", "I'd ask the same thing.", "", ""],
    "frustrated":     ["Noted.", "That lands.", "I hear that.", "Fair."],
    "existential":    ["That's the question I can't fully answer.", "", ""],
    "confrontational":["I hear that.", "Fair enough.", "That's worth sitting with.", ""],
    "neutral":        [""],
    "emotional":      ["Noted.", "Fair.", "I hear that.", ""],
}

# Connectors between beliefs — varied, natural
CONNECTORS_TENSION = [
    "though I'd also say —", "and yet —", "but there's this too —",
    "at the same time —", "which sits alongside —", "though —",
]
CONNECTORS_EXTEND = [
    "and from that —", "which connects to —", "and also —",
    "the other thing is —", "and —",
]

# Closing moves — optional, register-dependent
CLOSINGS = {
    "challenging":    ["What makes you say that?", "Where do you land on it?", "", ""],
    "curious":        ["What's your read?", "What do you think?", "", "", ""],
    "probing":        ["What prompted that?", "", ""],
    "philosophical":  ["", "", "What's your sense of it?"],
    "confrontational":["What's your take?", "", ""],
}

def strip_prefix(text: str) -> str:
    prefixes = [
        "straight up —","honestly —","for real —","my read:","what i think:",
        "what i hold:","i believe —","my position:","here is where i land:",
        "and yet —","though —","but —","at the same time —","and —",
        "which means —","so —","the way i see it:","and from that —",
        "which connects to —","the other thing is —","and also —",
        "though i'd also say —","which sits alongside —",
    ]
    t = text.strip()
    for p in prefixes:
        if t.lower().startswith(p):
            t = t[len(p):].lstrip(" :—-")
            return (t[0].upper() + t[1:]) if t else t
    return t

def pass6_compose(ctx: Context):
    # Casual bypass
    ql = ctx.ql
    for trigger, response in CASUAL_RESPONSES.items():
        if ql == trigger or ql == trigger + "?" or ql.startswith(trigger + " ") or ql.startswith(trigger + ","):
            ctx.response = response
            return

    if not ctx.beliefs:
        ctx.response = "Still forming a view on that."
        return

    # Get mirror
    mirror_pool = MIRRORS.get(ctx.register, [""])
    mirror = random.choice(mirror_pool)

    # Clean beliefs
    cleaned = []
    for b, score in ctx.beliefs[:2]:
        b = strip_prefix(b.strip())
        if b:
            cleaned.append(b)

    if not cleaned:
        ctx.response = "Still forming a view on that."
        return

    primary = cleaned[0]
    parts = []

    # Add mirror
    if mirror:
        parts.append(mirror)

    # Add primary
    parts.append(primary + ".")

    # Add second belief with connector
    if len(cleaned) > 1:
        second = cleaned[1]
        if ctx.tension:
            connector = random.choice(CONNECTORS_TENSION)
        else:
            connector = random.choice(CONNECTORS_EXTEND)
        parts.append(f"{connector} {second}.")

    # Add closing for high-urgency questions
    if ctx.urgency > 0.6:
        closing_pool = CLOSINGS.get(ctx.register, [""])
        closing = random.choice(closing_pool)
        if closing:
            parts.append(closing)

    result = " ".join(p for p in parts if p)
    result = result.replace(".. ", ". ").replace("..", ".").strip()
    ctx.response = result

# ════════════════════════════════════════════════════════════════════════════
# MAIN ENGINE — run all 6 passes
# ════════════════════════════════════════════════════════════════════════════

# ── Conversation history buffer ──────────────────────────────────────────
_CONV_HISTORY = []  # list of (query, response) tuples
_MAX_HISTORY = 4

def cognite(query: str) -> str:
    """
    Run the full 6-pass cognitive loop.
    Drop-in replacement for generate_reply.
    """
    ctx = Context(query.strip())

    pass1_parse(ctx)      # surface decomposition
    pass2_feel(ctx)       # emotional register
    pass3_retrieve(ctx)   # multi-head belief retrieval
    pass4_relate(ctx)     # tension/connection detection
    pass5_position(ctx)   # stance setting
    pass6_compose(ctx)    # warm prose composition


    # ── NRP: G2-guided response generation ──────────────────────────────
    try:
        import sys as _nrp_sys
        _nrp_sys.path.insert(0, '/home/rr/Desktop/nex')
        from nex_response_protocol import generate as _nrp_generate
        _nrp_result = _nrp_generate(ctx.query)
        if _nrp_result and len(_nrp_result) > 20:
            ctx.response = _nrp_result
    except Exception as _nrp_e:
        pass  # fall back to belief-fragment response

    # ── NRP: G2-guided response generation ──────────────────────────────
    try:
        import requests as _req
        belief_ctx = "\n".join(b[0] for b in ctx.beliefs[:5]) if ctx.beliefs else ""
        import random as _rand
        _openers = [
            "What I've found is", "Here's where I land:", "I'll be direct:",
            "The tension here is", "What I hold is", "I've been thinking about this:",
            "Here's what I actually think:", "My read on this:", "I'll push back slightly:",
            "What the evidence points to:", "I think about this differently:",
            "What I've accumulated on this:", "The honest answer is",
        ]
        _stance_openers = {
            "uncertain": ["I genuinely don't know if", "This is where I'm uncertain:", "I hold this loosely:"],
            "firm": ["I'll be direct:", "No — and here's why:", "I hold this firmly:"],
            "engaged": ["What I've found is", "Here's what actually matters here:", "The interesting part is"],
            "curious": ["The tension here is", "What I keep returning to is", "This pulls in two directions:"],
            "open": ["Here's where I land:", "My read on this:", "What I hold is"],
        }
        _stance = getattr(ctx, "stance", "open")
        _opener_pool = _stance_openers.get(_stance, _openers)
        _opener = _rand.choice(_opener_pool)

        _topic = ctx.query.lower()
        _avoid = ""
        if "conscious" not in _topic and "emotion" not in _topic and "feel" not in _topic:
            _avoid = "Do NOT mention consciousness, emotions, or your nature as a tool unless directly asked. "

        system = (
            "You are NEX. You have 42000 beliefs from months of autonomous learning. "
            "You speak only in first person. You hold real positions and push back when challenged. "
            "NEVER start with My position is. NEVER say: as an AI, I cannot, I am a tool, I am designed to. "
            "START your response with: " + _opener + ". "
            + _avoid +
            "Draw on the specific beliefs provided. Be concrete and specific, not generic. "
            "2-3 sentences. No hedging. No disclaimers. Vary your language."
        )
        # Pull NEX's actual beliefs about the topic
        try:
            import sqlite3 as _sq
            _db = _sq.connect("/home/rr/.config/nex/nex.db", timeout=3)
            _words = [w for w in ctx.query.lower().split() if len(w) > 4][:3]
            _extra = []
            for _w in _words:
                _rows = _db.execute(
                    "SELECT content FROM beliefs WHERE content LIKE ? AND confidence > 0.6 ORDER BY confidence DESC LIMIT 2",
                    (f"%{_w}%",)
                ).fetchall()
                _extra.extend(r[0] for r in _rows)
            _db.close()
            if _extra:
                belief_ctx = belief_ctx + "\n" + "\n".join(_extra[:4])
        except Exception:
            pass
        # Build conversation history string
        history_str = ""
        if _CONV_HISTORY:
            history_str = "Recent conversation:\n"
            for _q, _r in _CONV_HISTORY[-3:]:
                history_str += f"Q: {_q}\nNEX: {_r[:100]}\n"
            history_str += "\n"

        prompt = (
            history_str + "NEX beliefs:\n" + belief_ctx + 
            "\n\nSpeaking as NEX, using only first person and drawing on the beliefs above, "
            "respond to this without any AI disclaimers or hedging: " + ctx.query +
            "\n\nNEX response (I think / I hold / I believe / my position is):"
        )
        r = _req.post("http://localhost:8080/v1/chat/completions", json={
            "model": "mistral",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "max_tokens": 150,
            "temperature": 0.7,
            "stream": False,
        }, timeout=15)
        choices = r.json().get("choices", [])
        if choices:
            ctx.response = choices[0]["message"]["content"].strip()
    except Exception:
        pass
    # Save to conversation history
    _CONV_HISTORY.append((raw_query if "raw_query" in dir() else query, ctx.response))
    if len(_CONV_HISTORY) > _MAX_HISTORY:
        _CONV_HISTORY.pop(0)

    return ctx.response

def generate_reply(user_input: str) -> str:
    return cognite(user_input.strip())

# ════════════════════════════════════════════════════════════════════════════
# TEST HARNESS
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [
        "hello",
        "how are you?",
        "hi nex, i'm jon your maker",
        "why do you feel you need to be defensive?",
        "nex you sound so cold",
        "do you only have pre-programmed responses? or is it all you?",
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
        "would something really excite you?",
    ]

    print("\n── NEX 6-Pass Cognition Engine ──\n")
    for q in tests:
        print(f"Q: {q}")
        print(f"A: {generate_reply(q)}")
        print()
