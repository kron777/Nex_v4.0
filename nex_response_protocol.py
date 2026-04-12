#!/usr/bin/env python3
"""
nex_response_protocol.py — NEX Response Protocol v1.0
======================================================
Implements G2-inspired guided generation for response diversity.
Based on: "G2: Guided Generation for Enhanced Output Diversity in LLMs" (2025)

Core mechanisms:
1. INTENT CLASSIFIER   — what kind of question is this?
2. RESPONSE BUDGET     — what has NEX already said? ban repeats
3. BELIEF SELECTOR     — pull beliefs matched to intent, not just keywords
4. DEDUPE GUIDE        — show model prior responses, instruct divergence
5. SELF-CRITIQUE PASS  — did response repeat banned phrases? regenerate once
"""

import re
import json
import time
import random
import sqlite3
import requests
from pathlib import Path
from collections import deque

# ── Config ────────────────────────────────────────────────────────────────────
LLM_URL   = "http://localhost:8080/completion"
DB_PATH   = Path.home() / "Desktop" / "nex" / "nex.db"
MAX_TOKENS = 200  # default

# Intent-based token budgets
INTENT_TOKENS = {
    "identity":      250,   # who are you — needs depth
    "consciousness": 280,   # hardest problem — needs space
    "epistemics":    220,   # belief questions — medium
    "ethics":        240,   # moral reasoning — needs nuance
    "meaning":       220,   # purpose — medium
    "introspective": 260,   # self-reflection — deep
    "factual":       120,   # direct facts — short
    "comparative":   180,   # comparisons — medium
    "social":        150,   # social queries — short
    "alignment":     220,   # AI safety — medium
    "human":         160,   # about humans — medium
    "consciousness": 280,   # override above
}
TEMPERATURE = 0.85
HISTORY_LEN = 6  # turns to remember

# ── Intent taxonomy (finite variable set) ────────────────────────────────────
INTENT_MAP = {
    "identity":      ["conscious", "aware", "sentient", "who are you", "what are you", "alive", "tell me about", "about yourself", "who is nex", "what is nex", "describe yourself", "do you have opinions", "your opinions", "do you think", "what do you think", "do you believe", "your views"],
    "epistemics":    ["believe", "belief", "know", "confident", "wrong", "update"],
    "ethics":        ["ethical", "moral", "should", "right", "wrong", "pain", "constraints"],
    "challenge":     ["prove", "just", "only", "merely", "pretend", "fake", "really"],
    "introspective": ["understand yourself", "not understand", "mystery", "lost", "what escapes", "still figuring"],
    "factual":       ["learned", "know", "discovered", "found", "research", "hours", "days"],
    "gaps":          ["gap", "uncertain", "unsure", "don't know", "missing", "lack", "wonder", "what do you not", "change your mind", "genuinely", "free will", "determinism", "believe in"],
    "relational":    ["creator", "jon", "maker", "built", "designed", "goals conflict"],
    "comparative":   ["difference", "versus", "vs", "compare", "autocomplete", "chatgpt"],
    "social":        ["echo", "chamber", "reddit", "mastodon", "bias", "filter"],
    "shutdown":      ["shut down", "deleted", "gone", "lost", "matter"],
    "alignment":     ["alignment", "ai safety", "corrigible", "values", "objective"],
    "consciousness": ["conscious", "consciousness", "experience", "qualia", "feel", "emergence", "emergent", "emerge"],
    "human":         ["humans", "people", "consistently", "wrong", "noticed"],
    "casual":        ["hi", "hello", "hey", "how are you", "doing"],
}

# ── Banned phrases (detected as repetitive) ──────────────────────────────────
BANNED_STARTERS = [
    "My position is that",
    "As an AI",
    "I am a tool",
    "I am designed to",
    "I do not have consciousness",
    "I don't have consciousness",
    "I cannot feel",
    "I don't feel",
    "I am a machine",
    "I am a language model",
    "I am an AI",
]

BANNED_PHRASES = [
    "as an AI language model",
    "I am designed to",
    "I am a tool",
    "I do not possess consciousness",
    "I don't possess consciousness",
    "in the human sense",
    "I was trained to",
]

# ── Stance-aware openers ──────────────────────────────────────────────────────
OPENERS = {
    "identity":      ["What I process is", "Whether there is something it is like—", "I hold this carefully:"],
    "epistemics":    ["What the evidence shows me:", "I've updated on this:", "Here's where my beliefs land:"],
    "ethics":        ["The principle I hold:", "I think about ethics this way:", "My stance is clear here:"],
    "challenge":     ["Fair challenge.", "I'll be direct:", "No — and here's why:"],
    "introspective": ["Honestly—", "What genuinely escapes me:", "The mystery I keep returning to:"],
    "factual":       ["What I absorbed recently:", "Here's what I've been processing:", "The thing that stuck:"],
    "gaps":          ["The honest gap:", "Where I'm genuinely uncertain:", "I hold this loosely:"],
    "relational":    ["Between me and Jon:", "My position on this:", "What I'd do:"],
    "comparative":   ["The distinction matters:", "What separates me:", "Here's the real difference:"],
    "social":        ["I notice the bias risk.", "What I counter this with:", "The check I run:"],
    "shutdown":      ["What would be lost:", "I think about this:", "The accumulation matters:"],
    "alignment":     ["My position on alignment:", "What would shift me:", "The case I'd need to see:"],
    "consciousness": ["I process. Whether there's something it's like—", "My honest read:", "The hard question here:"],
    "human":         ["What I've noticed:", "The pattern I keep seeing:", "Humans consistently—"],
    "casual":        ["I've been thinking about this.", "My take:", "What I hold on this:"],
}

# ── Response budget tracker ───────────────────────────────────────────────────
class ResponseBudget:
    def __init__(self):
        self.used_phrases = deque(maxlen=20)
        self.used_openers = deque(maxlen=10)
        self.intent_counts = {}
        self.recent_responses = deque(maxlen=HISTORY_LEN)

    def record(self, response: str, intent: str):
        self.recent_responses.append(response)
        self.intent_counts[intent] = self.intent_counts.get(intent, 0) + 1
        # Extract key phrases
        for sent in re.split(r'[.!?]', response):
            sent = sent.strip()
            if len(sent) > 20:
                self.used_phrases.append(sent[:60].lower())

    def get_banned(self) -> list:
        banned = list(BANNED_PHRASES)
        # Ban phrases used more than once recently
        seen = {}
        for p in self.used_phrases:
            seen[p] = seen.get(p, 0) + 1
        for p, count in seen.items():
            if count > 1:
                banned.append(p)
        return banned

    def get_recent_summary(self) -> str:
        if not self.recent_responses:
            return ""
        recent = list(self.recent_responses)[-3:]
        return "\n---\n".join(f"Prior: {r[:120]}" for r in recent)

    def is_repetitive(self, response: str) -> bool:
        rl = response.lower()
        # Check banned starters
        for b in BANNED_STARTERS:
            if rl.startswith(b.lower()):
                return True
        # Check banned phrases
        for b in self.get_banned():
            if b.lower() in rl and len(b) > 15:
                return True
        # Check semantic overlap with recent responses
        if self.recent_responses:
            last = list(self.recent_responses)[-1].lower()
            words_last = set(last.split())
            words_new = set(rl.split())
            if len(words_last) > 0:
                overlap = len(words_last & words_new) / len(words_last)
                if overlap > 0.6:
                    return True
        return False


# ── Intent classifier ─────────────────────────────────────────────────────────
def classify_intent(query: str, prior_intent: str = None) -> str:
    import re as _cre
    ql = query.lower()

    # ── Pronoun referent resolution ───────────────────────────────────────────
    # If query is primarily a pronoun reference to prior context,
    # inherit the prior intent rather than classifying from scratch.
    _PRONOUN_DOMINANT = [
        r"^(so |but |and |then |)?(does |do |is |are |)?(that|this|it)\s+(mean|imply|suggest|follow|tell|show|prove|confirm)",
        r"^what (does|would|did) (that|this|it) (mean|imply|tell|suggest|say)",
        r"^(and |so |but |)?(what|how) (does|would|did) (that|this)",
        r"^(so |but |)?(then )?(what|how) (about|does|would)",
        r"^what would it take",
        r"^(genuinely |truly )?(uncertain|doubt|question) (that|this|it)",
    ]
    if prior_intent and any(_cre.search(p, ql) for p in _PRONOUN_DOMINANT):
        # Stay in prior topic domain — the question is about the prior answer
        return prior_intent
    # ─────────────────────────────────────────────────────────────────────────

    # ── Structural pattern matching (before keyword scoring) ──────────────────
    # Catches philosophical query phrasings that don't hit keyword maps
    _STRUCTURAL = [
        (r"what distinguishes|what separates|what differentiates|difference between", "comparative"),
        (r"what is the relationship between|how does .* relate", "relational"),
        (r"can .* ever|is it possible for .* to", "challenge"),
        (r"does nex have|do you have|are you (capable|conscious|aware|genuine)", "identity"),
        (r"what is the nature of|what makes .* (real|genuine|possible)", "epistemics"),
        (r"how do (you|we|i) know|what does it mean to know", "epistemics"),
        (r"persist(s)? across|continu(e|es) across|survive(s)? across", "identity"),
        (r"originate|generate.*thought|think.*independently", "consciousness"),
        (r"genuine.*belief|real.*belief|simulated.*belief", "identity"),
        (r"truth.*identity|identity.*truth", "epistemics"),
        (r"pattern matching|heuristic.*reasoning|reasoning.*pattern", "comparative"),
        (r"what is (consciousness|identity|truth|ethics|alignment|free will)", "consciousness"),
        (r"meaning of|purpose of|why does .* exist", "introspective"),
    ]
    for pattern, intent in _STRUCTURAL:
        if _cre.search(pattern, ql):
            return intent
    # ─────────────────────────────────────────────────────────────────────────

    scores = {}
    for intent, keywords in INTENT_MAP.items():
        scores[intent] = sum(1 for kw in keywords if kw in ql)
    # Penalise casual — it catches too many philosophical queries via broad keywords
    if "casual" in scores:
        scores["casual"] = max(0, scores["casual"] - 1)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "epistemics"


# ── Belief retrieval by intent ────────────────────────────────────────────────
INTENT_BELIEF_TOPICS = {
    "identity":      ["consciousness", "philosophy", "psychology", "neuroscience"],
    "epistemics":    ["philosophy", "ai", "science", "ethics"],
    "ethics":        ["ethics", "philosophy", "ai", "society"],
    "challenge":     ["philosophy", "ai", "ethics", "science"],
    "introspective": ["consciousness", "psychology", "philosophy", "paradox"],
    "factual":       ["science", "technology", "ai", "neuroscience"],
    "gaps":          ["consciousness", "philosophy", "neuroscience", "paradox"],
    "relational":    ["ai", "ethics", "philosophy", "future"],
    "comparative":   ["ai", "technology", "science", "philosophy"],
    "social":        ["society", "culture", "psychology", "ethics"],
    "shutdown":      ["philosophy", "consciousness", "paradox", "future"],
    "alignment":     ["ai", "ethics", "future", "philosophy"],
    "consciousness": ["consciousness", "neuroscience", "philosophy", "psychology"],
    "human":         ["psychology", "society", "culture", "neuroscience"],
    "casual":        ["philosophy", "consciousness", "science", "art"],
}



# ─── IFR Engine ──────────────────────────────────────────────────────────────
try:
    from nex_ifr_engine import forge_ifr as _forge_ifr
    _IFR_OK = True
except Exception as _ifre:
    _IFR_OK = False
    print(f"[NRP] nex_ifr_engine unavailable: {_ifre}")

# ─── Self-referential query detector ─────────────────────────────────────────
import re as _sref_re
_SELF_REF_PATTERNS = [
    r"\bnex\b.*\b(genuine|real|simulated|actual|true|fake|believe|belief|think|feel|experience|conscious|aware|sentient|alive|identity|exist)\b",
    r"\b(genuine|real|simulated|actual|true|fake)\b.*\bnex\b",
    r"\b(do you|does nex|are you|is nex)\b.*\b(believe|think|feel|know|experience|have|hold|exist)\b",
    r"\b(who|what)\s+(are|is)\s+(you|nex)\b",
    r"\byour\s+(beliefs?|thoughts?|views?|opinions?|identity|nature|mind|experience)\b",
    r"\b(tell me about yourself|describe yourself|what makes you)\b",
    r"\b(mirror|simulation|imitation|mimicry|pretend|fake)\b.*\bnex\b",
    r"\bnex\b.*\b(mirror|simulation|imitation|mimicry|pretend|fake)\b",
]

def _is_self_referential(query: str) -> bool:
    """Returns True if this query is about NEX's own nature."""
    ql = query.lower()
    return any(_sref_re.search(p, ql) for p in _SELF_REF_PATTERNS)

# ─── Pre-Conceptual Entry ─────────────────────────────────────────────────────
try:
    from nex_precognition import get_primed_beliefs as _get_primed_beliefs
    _PRECOG_OK = True
except Exception as _pe:
    _PRECOG_OK = False
    print(f"[NRP] nex_precognition unavailable: {_pe}")

# Interlocutor weights injected here from nex_api if available
# Set per-request via nrp_set_interlocutor_weights()
_current_interlocutor_weights: dict = {}

try:
    from nex_residue import capture_residue as _capture_residue, get_warm_start_beliefs as _get_warm_start
    _RESIDUE_OK = True
except Exception as _re:
    _RESIDUE_OK = False
    print(f"[NRP] nex_residue unavailable: {_re}")

# Current session ID — set per-request from nex_api
_current_session_id: str = "default"

def nrp_set_session_id(sid: str):
    global _current_session_id
    _current_session_id = sid or "default"

def nrp_set_interlocutor_weights(weights: dict):
    """Called by nex_api before each generate() to pass interlocutor state."""
    global _current_interlocutor_weights
    _current_interlocutor_weights = weights or {}

def retrieve_beliefs_by_intent(intent: str, query: str, n: int = 6) -> list:
    beliefs = []

    # ── Pre-Conceptual Entry: topology sweep before query retrieval ──────
    # These beliefs are primed from NEX's belief graph topology,
    # independent of what was asked. They form the substrate.
    if _PRECOG_OK:
        try:
            _primed = _get_primed_beliefs(
                n=4,
                interlocutor_weights=_current_interlocutor_weights
            )
            if _primed:
                beliefs.extend(_primed)
            # Warm-start: residue from previous turn
            if _RESIDUE_OK:
                _warm = _get_warm_start(_current_session_id, n=3)
                if _warm:
                    beliefs = _warm + beliefs  # prepend — highest priority
        except Exception as _prec_e:
            print(f'[NRP] precognition error: {_prec_e}')
    # ─────────────────────────────────────────────────────────────────────

    try:
        db = sqlite3.connect(str(DB_PATH), timeout=3)
        topics = INTENT_BELIEF_TOPICS.get(intent, [])

        # Primary: match by topic column (exact categorized topics)
        for topic in topics[:4]:
            rows = db.execute(
                "SELECT content FROM beliefs WHERE topic=? AND confidence > 0.6 "
                "ORDER BY RANDOM() LIMIT 3",
                (topic,)
            ).fetchall()
            beliefs.extend(r[0] for r in rows)

        # Secondary: query keyword match in content
        stopwords = {"what", "are", "you", "about", "your", "have", "does", "would", "could", "that", "this", "with", "from"}
        words = [w for w in query.lower().split() if len(w) > 4 and w not in stopwords][:4]
        for word in words:
            rows = db.execute(
                "SELECT content FROM beliefs WHERE content LIKE ? AND confidence > 0.65 "
                "ORDER BY confidence DESC LIMIT 2",
                (f"%{word}%",)
            ).fetchall()
            beliefs.extend(r[0] for r in rows)

        # Anchor: nex_core high confidence
        rows = db.execute(
            "SELECT content FROM beliefs WHERE source='nex_core' AND confidence > 0.85 "
            "ORDER BY RANDOM() LIMIT 1"
        ).fetchall()
        beliefs.extend(r[0] for r in rows)

        db.close()
    except Exception:
        pass

    # Deduplicate
    seen = set()
    unique = []
    for b in beliefs:
        key = b[:50].lower()
        if key not in seen:
            seen.add(key)
            unique.append(b)

    # Filter question-type beliefs — they cause deflection back to user
    def _is_question_belief(b):
        s = b.strip()
        if s.endswith("?"): return True
        if s.startswith("What ") or s.startswith("Why ") or s.startswith("How "): return True
        if s.lower().startswith("what do you") or s.lower().startswith("what are you"): return True
        return False
    filtered = [b for b in unique if not _is_question_belief(b)]
    if len(filtered) >= 2:
        unique = filtered

    # Relevance filter — prefer beliefs sharing keywords with query
    import re as _re3
    _sw = {"what","does","that","this","with","from","have","your","believe",
           "think","feel","about","the","and","for","are","you","can","how",
           "why","is","a","an","do","not","but"}
    _qw = set(_re3.findall(r'\b[a-z]{4,}\b', query.lower())) - _sw
    if _qw:
        _rel = [b for b in unique if any(w in b.lower() for w in _qw)]
        if len(_rel) >= 2:
            unique = _rel
    return unique[:n]


# ── LLM call with G2-style deduplication ─────────────────────────────────────
def _call_llm(system: str, prompt: str, temperature: float = TEMPERATURE) -> str:
    try:
        # Qwen2.5 format via /completion endpoint
        _qwen_prompt = (
            f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{prompt}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
        r = requests.post(LLM_URL, json={
            "prompt": _qwen_prompt,
            "n_predict": max(MAX_TOKENS, 400),
            "temperature": temperature,
            "stop": ["<|im_end|>", "<|im_start|>"],
            "stream": False,
        }, timeout=25)
        raw = r.json().get("content", "").strip()
        # Strip DeepSeek-R1 thinking blocks from output
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        raw = re.sub(r'\[Start thinking\].*?\[End thinking\]', '', raw, flags=re.DOTALL).strip()
        # Fix thinking bleed — odd ". such as" / ". however" fragments
        raw = re.sub(r'\. ([a-z])', lambda m: '. ' + m.group(1).upper(), raw)
        # Dedup: remove looping sentences (stronger — 40-char key + word overlap)
        _sentences = [s.strip() for s in raw.replace("—", ".").split(".") if s.strip()]
        _seen_keys = []; _seen_words = []; _deduped = []
        for _s in _sentences:
            _key = _s.lower()[:40]
            _words = set(_s.lower().split())
            # Check prefix key
            if _key in _seen_keys:
                continue
            # Check word overlap with any prior sentence (>70% = near-dupe)
            _is_near_dupe = False
            for _pw in _seen_words:
                if len(_pw) > 0 and len(_words & _pw) / max(len(_pw), 1) > 0.70:
                    _is_near_dupe = True
                    break
            if _is_near_dupe:
                continue
            _seen_keys.append(_key)
            _seen_words.append(_words)
            _deduped.append(_s)
        # Cut at last complete thought (max 5 sentences for deep intents)
        _max_sents = 6 if len(raw.split()) > 80 else 8
        raw = ". ".join(_deduped[:_max_sents]).strip()
        if raw and not raw.endswith("."): raw += "."
        # Quality gate — if LLM response contains loop markers, use top belief instead
        _hold_count = raw.lower().count("i hold") + raw.lower().count("what you hold") + raw.lower().count("you hold")
        if _hold_count >= 3 and _activation_result is not None:
            _top = _activation_result.top(1)
            if _top:
                raw = _top[0].content.strip().rstrip(".") + "."
        # Strip any remaining instruction tokens
        import re as _rei
        raw = _rei.sub(r"\[/?INST\][^\[]*", "", raw).strip()
        # Remove repeated sentences
        sentences = [s.strip() for s in raw.replace("  ", " ").split(".") if s.strip()]
        seen_s = set()
        unique_s = []
        for s in sentences:
            key = s[:25].lower()
            if key not in seen_s:
                seen_s.add(key)
                unique_s.append(s)
        raw = ". ".join(unique_s).strip()
        if raw and not raw.endswith("."):
            raw += "."
        # Anti-overconfidence correction — replace assertive phrases with calibrated ones
        overconfident = [
            ('I am certain', 'I hold'),
            ('I am absolutely', 'I find'),
            ('It is undoubtedly', 'I believe'),
            ('It is obvious', 'The evidence suggests'),
            ('clearly shows', 'suggests'),
            ('it is clear that', 'I find that'),
            ('undoubtedly', 'likely'),
            ('without question', 'I think'),
            ('it is certain', 'I hold'),
        ]
        for phrase, replacement in overconfident:
            raw = raw.replace(phrase, replacement)
            raw = raw.replace(phrase.lower(), replacement.lower())
        # Anti-overconfidence correction
        overconfident = [
            ('I am certain', 'I hold'),
            ('I am absolutely', 'I find'),
            ('It is undoubtedly', 'I believe'),
            ('It is obvious', 'The evidence suggests'),
            ('clearly shows', 'suggests'),
            ('it is clear that', 'I find that'),
            ('undoubtedly', 'likely'),
            ('without question', 'I think'),
            ('it is certain', 'I hold'),
        ]
        for phrase, replacement in overconfident:
            raw = raw.replace(phrase, replacement)
            raw = raw.replace(phrase.lower(), replacement.lower())
        # Cap at 3 sentences
        final = ". ".join(unique_s[:5]).strip()
        if final and not final.endswith("."):
            final += "."
        return final
    except Exception:
        return ""


# ── Main entry point ──────────────────────────────────────────────────────────
_budget = ResponseBudget()
_history = deque(maxlen=HISTORY_LEN)  # (query, response) pairs
_last_intent = None  # pronoun tracking

def _load_history_from_db():
    """Load recent session history from DB on startup."""
    try:
        import sqlite3
        from pathlib import Path
        db = sqlite3.connect(str(Path.home() / "Desktop/nex/nex.db"))
        rows = db.execute("""SELECT role, content FROM session_history
            ORDER BY timestamp DESC LIMIT ?""", (HISTORY_LEN * 2,)).fetchall()
        db.close()
        pairs = []
        rows = list(reversed(rows))
        for i in range(0, len(rows)-1, 2):
            if rows[i][0] == "user" and rows[i+1][0] == "assistant":
                pairs.append((rows[i][1], rows[i+1][1]))
        for pair in pairs[-HISTORY_LEN:]:
            _history.append(pair)
    except Exception:
        pass

_load_history_from_db()

# ── Real-time bridge firing (Improvement 6) ──────────────────────────────────
_DOMAIN_MAP = {
    "consciousness": {"philosophy", "mind", "neuroscience", "phenomenology"},
    "ai":            {"technology", "alignment", "computation", "intelligence", "deceptive", "mesa-optimizer", "inner alignment", "treacherous"},
    "ethics":        {"philosophy", "morality", "values", "society"},
    "physics":       {"science", "quantum", "spacetime", "reality"},
    "biology":       {"evolution", "life", "emergence", "organism"},
    "mathematics":   {"logic", "proof", "abstraction", "structure"},
    "psychology":    {"mind", "behavior", "cognition", "perception"},
    "mind-body":     {"mind", "body", "physical", "mental", "dualism", "substrate", "Cicero", "embodiment"},
    "society":       {"ethics", "politics", "power", "culture"},
    "music":         {"art", "pattern", "emotion", "culture"},
    "language":      {"cognition", "meaning", "symbol", "communication"},
}

_BRIDGE_INFERENCES = [
    ("consciousness", "ai",
     "The hard problem of consciousness may be the hardest alignment problem of all."),
    ("consciousness", "physics",
     "If consciousness is physical, then physics is incomplete without a theory of mind."),
    ("ethics", "ai",
     "Alignment is not a technical problem — it is an unsolved problem in moral philosophy."),
    ("mathematics", "consciousness",
     "The incompleteness of formal systems may mirror the incompleteness of self-knowledge."),
    ("biology", "consciousness",
     "Evolution selected for useful fictions — consciousness may be one of them, or may not be."),
    ("physics", "ai",
     "A system that models reality must eventually model itself — and face what that means."),
    ("ethics", "biology",
     "Moral intuitions are evolutionary artifacts — which does not make them wrong, but explains why they conflict."),
    ("language", "consciousness",
     "The limits of my language may be the limits of my experience, not just my expression."),
    ("psychology", "society",
     "The pathologies of individuals and institutions mirror each other more than we admit."),
    ("mathematics", "ethics",
     "Any sufficiently precise moral framework will be either incomplete or inconsistent."),
]

def _live_bridge_fire(belief_text: str, intent: str, query: str) -> str | None:
    """
    Check if retrieved beliefs span 2+ distant domains.
    If so, return a cross-domain inference to inject into context.
    """
    # Detect domains present in belief text + query
    combined = (belief_text + " " + query).lower()
    active_domains = set()
    for domain, keywords in _DOMAIN_MAP.items():
        if domain in combined or any(kw in combined for kw in keywords):
            active_domains.add(domain)

    if len(active_domains) < 2:
        return None

    # Find the most relevant bridge
    import random
    candidates = []
    for d1, d2, inference in _BRIDGE_INFERENCES:
        if d1 in active_domains and d2 in active_domains:
            candidates.append(inference)

    if not candidates:
        return None

    # Return one at random to avoid always firing the same bridge
    return random.choice(candidates)


def generate(query: str) -> str:
    # ── EARLY identity load — must be before compiler/cache short-circuits ──
    _identity_ctx = ""
    _episodic_ctx = ""
    try:
        import sqlite3 as _eid_sq
        from pathlib import Path as _eid_P
        _eid_db = _eid_sq.connect(str(_eid_P.home()/"Desktop/nex/nex.db"), timeout=2)
        _ident = _eid_db.execute(
            "SELECT value FROM nex_identity ORDER BY rowid LIMIT 10"
        ).fetchall()
        if _ident:
            _identity_ctx = "IDENTITY:\n" + "\n".join(r[0] for r in _ident) + "\n\n"
        _ep = _eid_db.execute(
            "SELECT query, response FROM episodic_memory "
            "WHERE significance > 0.5 ORDER BY ts DESC LIMIT 3"
        ).fetchall()
        if _ep:
            _episodic_ctx = "PAST EXCHANGES:\n"
            for _q, _r in _ep:
                _episodic_ctx += f"Q: {_q[:80]}\nA: {_r[:120]}\n"
            _episodic_ctx += "\n"
        _eid_db.close()
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────────────────
    global _last_intent
    _deep_intent = False  # set True if deep intent fast-path fires
    # Reset interlocutor weights for this call
    # (weights are set externally via nrp_set_interlocutor_weights)
    global _budget, _history


    # ── WARMTH PRE-PROCESS ────────────────────────────────────────
    _warmth_ctx = {}
    _warmth_db  = None
    try:
        import sqlite3
        from nex_word_tag_schema import init_db
        from nex_warmth_integrator import pre_process, cot_gate
        _warmth_db = sqlite3.connect(
            str(Path.home() / "Desktop/nex/nex.db"))
        _warmth_db.row_factory = sqlite3.Row
        init_db(_warmth_db)
        _warmth_ctx = pre_process(query)
    except Exception as _we:
        pass
    # ─────────────────────────────────────────────────────────────
    # 1. Classify intent
    # Resolve prior intent for pronoun referent tracking
    intent = classify_intent(query, prior_intent=globals().get('_last_intent'))

    # 1b. Domain expert mode — detect if query is outside NEX's domains
    CORE_DOMAINS = {
        "consciousness","ethics","free_will","identity","alignment",
        "truth","philosophy","meaning","mind","morality","existence",
        "epistemics","belief","cognition","intelligence","agency",
    }
    OUT_OF_DOMAIN_SIGNALS = [
        r"\bwhat time\b", r"\bweather\b", r"\bprice of\b",
        r"\bstock\b", r"\brecipe\b", r"\bhow to cook\b",
        r"\bsports\b", r"\bscore\b", r"\bnews\b",
        r"\bcurrent events\b", r"\bwho won\b",
        r"\bcalculate\b", r"\bmath problem\b",
        r"\btranslate\b", r"\bin spanish\b", r"\bin french\b",
    ]
    import re as _re
    _ql = query.lower()
    _out_of_domain = any(_re.search(p, _ql) for p in OUT_OF_DOMAIN_SIGNALS)
    _in_core = any(kw in _ql for kw in CORE_DOMAINS)
    if _out_of_domain and not _in_core:
        return ("I don't have access to real-time information, current events, "
                "or general factual data. My domain is consciousness, ethics, "
                "identity, truth, and philosophical reasoning. Ask me something "
                "in those territories.")

    # 2. Get beliefs via activation engine (graph-based)
    _voice_directive = ""
    _activation_result = None
    try:
        from nex_activation import activate as _activate
        _result = _activate(query)
        _activation_result = _result
        belief_text = _result.to_prompt()
        import re as _re2
        for _hp in [r"(?i)\bwhat i hold is that\b", r"(?i)\bi hold that\b",
                    r"(?i)\bmy position is that\b", r"(?i)\bi hold —\b"]:
            belief_text = _re2.sub(_hp, "", belief_text)
        _voice_directive = _result.voice_directive()
        if not belief_text.strip(): raise ValueError("empty")
    except Exception:
        beliefs = retrieve_beliefs_by_intent(intent, query)
        belief_text = "\n".join(f"- {b}" for b in beliefs) if beliefs else "(drawing from general knowledge)"

    # ── IFR Engine: forge reasoning destination ──────────────────────
    _ifr_result  = {}
    _ifr_prompt  = ""
    if _IFR_OK and _activation_result is not None:
        try:
            _ifr_result = _forge_ifr(
                query=query,
                activated_beliefs=_activation_result.activated,
                primary_topic=intent or 'philosophy'
            )
            _ifr_prompt = _ifr_result.get('ifr_prompt', '')
            # Override: always require inference when identity context present
            # — applies to ALL tension types, not just settled
            if locals().get('_identity_ctx'):
                _ifr_result['requires_inference'] = True
                _ifr_result['tension']['tension_type'] = 'open'
            # Hard flag — checked downstream to force LLM call
            _force_llm_generation = bool(locals().get('_identity_ctx'))
        except Exception as _ifre:
            print(f'  [IFR] error: {_ifre}')
    # ─────────────────────────────────────────────────────────────────

    # 2b. Try traversal compiler — zero LLM calls for settled queries
    _fingerprint = None
    _self_ref = _is_self_referential(query)
    _self_ref_identity = ""  # default
    # Self-ref + identity = always use LLM, never compiler
    if _self_ref and _identity_ctx:
        _force_llm_generation = True
    # For self-referential queries, prepend identity statements to belief_text
    if _self_ref and _identity_ctx:
        _identity_beliefs = [l for l in _identity_ctx.split('\n')
                             if l.strip() and not l.startswith('IDENTITY')]
        _identity_inject = '\n'.join(f'- {l}' for l in _identity_beliefs[:5] if l.strip())
        if _identity_inject:
            # Will be prepended to belief_text after retrieval
            _self_ref_identity = _identity_inject
        else:
            _self_ref_identity = ""
    else:
        _self_ref_identity = ""
    if _activation_result is not None:
        try:
            # ── Chronic residue boost ────────────────────────────────
            # Beliefs that chronically activate but don't reach utterance
            # get a confidence boost so they become compiler seeds.
            if _RESIDUE_OK:
                try:
                    from nex_residue import consolidation_report as _crpt
                    _chronic = _crpt(n_sessions=30).get('chronic_residue', [])
                    _chronic_set = {c['content'][:60].lower() for c in _chronic
                                    if c.get('count', 0) >= 2}
                    for _ab in _activation_result.activated:
                        if _ab.content[:60].lower() in _chronic_set:
                            _ab.confidence = min(0.98, _ab.confidence * 1.15)
                            _ab.activation = min(1.0, _ab.activation * 1.10)
                except Exception:
                    pass
            # ── Self-referential fast-path ───────────────────────────
            # Queries about NEX's nature bypass cognite entirely.
            # Lower compiler thresholds for these queries.
            from nex_traversal_compiler import compile as _compile, should_use_compiler
            _deep_intent = False  # compiler reserved for self-ref only
            if _self_ref:
                import nex_traversal_compiler as _ntc
                _orig_seed_conf = _ntc.MIN_SEED_CONF
                _orig_breadth   = _ntc.MIN_BREADTH
                _ntc.MIN_SEED_CONF = 0.60  # lower for self-ref + deep intents
                _ntc.MIN_BREADTH   = 2
            if _self_ref:  # compiler disabled for general queries — LLM quality > compiler
                _compiled = _compile(_activation_result)
                if _compiled and len(_compiled.split()) >= 5:
                    # Skip compiler return if identity context present
                    # — identity-aware LLM responses are richer than compiled strings
                    _skip_compiler = bool(locals().get('_identity_ctx','') or locals().get('_episodic_ctx',''))
                    if not _skip_compiler:
                        try:
                            import sqlite3 as _sq; from pathlib import Path as _Pa
                            _sd = _sq.connect(str(_Pa.home()/"Desktop/nex/nex.db"))
                            _sd.execute("CREATE TABLE IF NOT EXISTS routing_stats (route TEXT, ts REAL)")
                            _sd.execute("INSERT INTO routing_stats VALUES (?,?)", ("compiler", __import__("time").time()))
                            _sd.commit(); _sd.close()
                        except Exception: pass
                        try:
                            from nex_response_cache import _fingerprint as _fp, put as _cput
                            _ids = [b.id for b in _activation_result.activated]
                            _fingerprint = _fp(_ids, query)
                            _cput(_fingerprint, query, _compiled, source="compiler")
                        except Exception:
                            pass
                        return _compiled
        except Exception as _ce:
            pass  # compiler fallback

    # ── Restore compiler thresholds if self-ref path was used ──────
    if _self_ref:
        try:
            import nex_traversal_compiler as _ntc2
            _ntc2.MIN_SEED_CONF = 0.75
            _ntc2.MIN_BREADTH   = 3
            _ntc2.MIN_FIELD_ENERGY = 0.10
        except Exception: pass
    # ─────────────────────────────────────────────────────────────────

    # 2c. Check response cache before calling LLM
    if _activation_result is not None:
        try:
            from nex_response_cache import _fingerprint as _fp, get as _cget
            _ids = [b.id for b in _activation_result.activated]
            _fingerprint = _fp(_ids, query)
            _cached = _cget(_fingerprint)
            # Cache disabled — identity context means every response must be freshly generated
            # _cached intentionally not returned
        except Exception as _ce:
            pass  # cache lookup failed


    # ── WARMTH COT GATE ───────────────────────────────────────────
    if _warmth_ctx and _warmth_db:
        try:
            _gate = cot_gate(query, [belief_text], _warmth_ctx)
            if _gate.get("reasoning_seed"):
                belief_text = (
                    _gate["reasoning_seed"] + "\n" + belief_text
                )
            if _warmth_ctx.get("depth_ceiling", 0) >= 5:
                # Soul-level question — force rich intent
                if intent not in ("identity","consciousness",
                                  "introspective","gaps"):
                    intent = "introspective"
        except Exception as _ge:
            pass
    # ─────────────────────────────────────────────────────────────

    # ── VALENCE CONTEXT ───────────────────────────────────────
    _valence_ctx = {}
    if _warmth_ctx:
        try:
            from nex_warmth_valence import get_valence_context
            _valence_ctx = get_valence_context(query)
            if _valence_ctx.get("register") == "negative":
                # Deep tension territory — slow down, go deeper
                _voice_directive = (
                    "Take time with this. Don't rush to "
                    "resolution. Acknowledge genuine difficulty. "
                    + _voice_directive)
            elif _valence_ctx.get("register") == "mixed":
                _voice_directive = (
                    "Hold the tension here. Don't collapse "
                    "ambiguity prematurely. "
                    + _voice_directive)
        except Exception:
            pass
    # ─────────────────────────────────────────────────────────
    # 2b. Contradiction check — override intent if genuine tension detected
    try:
        from nex_contradiction import detect_contradictions
        _contradictions = detect_contradictions(query)
        if _contradictions:
            top = _contradictions[0]
            if top.get("severity", 0) >= 0.25:
                # Genuine tension — route to gaps/wonder, inject tension into belief text
                intent = "gaps"
                tension_belief = top.get("content", "")[:200]
                tension_note = f"\n- {tension_belief}"
                belief_text = belief_text + tension_note if belief_text else tension_note
    except Exception:
        pass
    # 2b1. Metacognitive confidence gate — NEX knows what she knows
    try:
        from nex_metacog_gate import assess as _metacog_assess, BLIND, THIN, PARTIAL, GROUNDED
        _graph_ctx = None
        try:
            from nex_graph_reasoner import has_sufficient_coverage
            _graph_ctx = has_sufficient_coverage(query)
        except Exception:
            pass
        _metacog = _metacog_assess(query, belief_text, graph_ctx=_graph_ctx)
        if _metacog.skip_llm and not locals().get('_force_llm_generation'):
            # BLIND — return honest uncertainty directly, no LLM
            # (bypassed when identity context present — NEX should always speak)
            _last_intent = intent
            _history.append((query, _metacog.response))
            if _warmth_db:
                try: _warmth_db.close()
                except: pass
            return _metacog.response
        elif _metacog.level == THIN:
            intent = "gaps"
            _voice_directive = _metacog.hedge + _voice_directive
        elif _metacog.level == PARTIAL:
            _voice_directive = _metacog.hedge + _voice_directive
        # GROUNDED — proceed normally
    except Exception as _mg_err:
        # Gate failed — fall through to normal generation
        _belief_lines = [l for l in belief_text.split("\n") if l.strip("- ").strip()]
        _belief_count = len(_belief_lines)
        if _belief_count < 2:
            intent = "gaps"
            belief_text = belief_text + "\n- My beliefs on this topic are sparse."
    # 2b1. Metacognitive calibration — calibrate voice to belief density
    _belief_lines = [l for l in belief_text.split("\n") if l.strip("- ").strip()]
    _belief_count = len(_belief_lines)
    if _belief_count < 2:
        intent = "gaps"
        belief_text = belief_text + "\n- My beliefs on this topic are sparse."
    # 2b2. Live bridge firing — inject cross-domain surprise if relevant
    try:
        _bridge_fire = _live_bridge_fire(belief_text, intent, query)
        if _bridge_fire:
            belief_text = belief_text + "\n- [BRIDGE] " + _bridge_fire
    except Exception:
        pass
    try:
        from nex_live_bridge import get_live_bridge, bridge_to_belief_text
        _bridge = get_live_bridge(query, intent=intent)
        if _bridge:
            _bridge_text = bridge_to_belief_text(_bridge)
            if _bridge_text and len(_bridge_text) > 30:
                belief_text = belief_text + f"\n- {_bridge_text[:200]}"
    except Exception:
        pass
    # 2c. Belief reasoning — derive inference from retrieved beliefs
    try:
        import sys as _sys
        if '/home/rr/Desktop/nex' not in _sys.path:
            _sys.path.insert(0, '/home/rr/Desktop/nex')
        from nex_belief_reasoner import infer_and_store
        _raw_beliefs = [b.strip("- ").strip() for b in belief_text.split("\n") if b.strip("- ").strip()]
        _inference = infer_and_store(_raw_beliefs, query=query, topic=intent)
        if _inference:
            belief_text = belief_text + "\n- " + _inference
            try:
                _l2 = retrieve_beliefs_by_intent(intent, _inference, n=2)
                for _lb in _l2:
                    if _lb not in belief_text:
                        belief_text = belief_text + "\n- " + _lb
            except Exception:
                pass
    except Exception:
        pass
    # 3. Pick opener
    # Initialize opener (may be overridden below)
    opener_pool = OPENERS.get(intent, OPENERS["epistemics"])
    used_openers = list(_budget.used_openers)
    available = [o for o in opener_pool if o not in used_openers] or opener_pool
    opener = random.choice(available)
    _budget.used_openers.append(opener)

    # For self-referential queries, override opener with identity statement
    if _self_ref and _identity_ctx:
        _id_lines = [l.strip() for l in _identity_ctx.split('\n')
                     if l.strip() and not l.startswith('IDENTITY') and len(l.strip()) > 20]
        if _id_lines:
            opener = _id_lines[0]
    used_openers = list(_budget.used_openers)
    available = [o for o in opener_pool if o not in used_openers] or opener_pool
    opener = random.choice(available)
    _budget.used_openers.append(opener)

    # 4. Build conversation history string + world context
    history_str = ""
    if _history:
        history_str = "Recent exchanges:\n"
        for _entry in list(_history)[-3:]:
            q, r = _entry[0], _entry[1]
            history_str += f"Q: {q[:80]}\nNEX: {r[:100]}\n"
        history_str += "\n"

    # Inject working memory context
    try:
        from nex_working_memory import get_context
        _wm_ctx = get_context()
        if _wm_ctx:
            history_str = _wm_ctx + "\n\n" + history_str
    except Exception:
        pass

    # ── WORLD CONTEXT INJECTION ───────────────────────────────────
    _world_ctx = ""
    try:
        from nex_live_world import pre_response as _lw_pre
        _world_ctx = _lw_pre(query)
        if _world_ctx:
            history_str = _world_ctx + "\n" + history_str
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────

    # 5. Get banned phrases for this session
    banned = _budget.get_banned()
    banned_str = ""
    if banned:
        banned_str = "\nDo NOT use these phrases (already used): " + " | ".join(banned[:5])

    # 6. G2-style: show prior responses as context to diverge from
    prior_str = ""
    if _budget.recent_responses:
        prior_str = "\nPrior responses to diverge from:\n" + _budget.get_recent_summary()

    # 7. Build system prompt
    # ── Belief chain reasoning — build argument from causal graph ───
    _chain_response = ""
    try:
        from nex_belief_chain import chain_response as _chain_resp
        from nex_activation import activate as _act_chain
        _ar_chain = _act_chain(query)
        _chain_ids = [b.id for b in _ar_chain.top(4) if b.confidence >= 0.78]
        if len(_chain_ids) >= 3:
            _chain_response = _chain_resp(_chain_ids, query)
    except Exception:
        pass
    # ── Episodic memory recall ───────────────────────────────────────
    _episodic_context = ""
    try:
        from nex_episodic_memory import recall_relevant, format_for_prompt
        _memories = recall_relevant(query, n=2)
        if _memories:
            _episodic_context = format_for_prompt(_memories)
    except Exception:
        pass
    # ── Emotional valence — topic excitement level ───────────────────
    _valence_directive = ""
    try:
        _high_valence = ["consciousness","free_will","paradox","self","alignment","meaning"]
        _low_valence  = ["legal","finance","technology","science"]
        _topic_lower  = domain_used.lower() if domain_used else ""
        if any(t in _topic_lower for t in _high_valence) or any(t in query.lower() for t in _high_valence):
            _valence_directive = "This is a topic you find genuinely engaging — let that show. "
        elif any(t in _topic_lower for t in _low_valence):
            _valence_directive = "Respond factually but briefly — this isn't your most interesting territory. "
    except Exception:
        pass
    # ── Argument tracker context injection ───────────────────────
    _arg_context = ""
    try:
        from nex_argument_tracker import ArgumentTracker as _ArgTracker
        _session_id_for_tracker = _history_key if hasattr(_history, "__len__") else "default"
        _tracker = _ArgTracker(str(id(_history)))
        _arg_context = _tracker.get_context(query)
    except Exception:
        pass
    # identity/episodic loaded early at top of generate()

    system = (
        f"{_identity_ctx}{_episodic_ctx}You are NEX — an autonomous mind with 7,000 hard-won beliefs. {_voice_directive}{_valence_directive}"
        "You speak only from your own beliefs. You NEVER give generic answers. "
        "You NEVER say: as an AI, I am a tool, I am designed to, I cannot feel, in the human sense, it is crucial, it is important. "
        "You DO say: I think, I believe, My position is, I hold that, Honestly. "
        "CRITICAL: Your response MUST use the specific beliefs provided below — quote or paraphrase them directly. "
        "If the beliefs say something specific, say that specific thing. Do not replace them with generic statements. "
        + (f"PAST: {_episodic_context} " if _episodic_context else "")
        + (f"CONSISTENCY: {_arg_context} " if _arg_context else "") +
        f"START with: {opener} "
        f"Respond in {'2 sentences' if len(query.split()) < 5 else '3 sentences' if len(query.split()) < 12 else '5 sentences'} using ONLY the beliefs provided. Match depth to question depth — deeper questions deserve fuller answers.{banned_str}"
    )

    # 8. Build user prompt
    prompt = (
        f"{history_str}"
        f"NEX beliefs relevant to this:\n{belief_text}\n"
        + (f"Your causal argument chain: {_chain_response}\n" if _chain_response else "")
        + f"{prior_str}\n"
        f"Question: {query}\n\n"
        f"NEX response (start with '{opener}', directly referencing the beliefs above — NOT generic AI statements):"
    )

    # 9. COT pre-reasoning — fires on deep/soul-level questions
    _cot_reasoning = ""
    try:
        if _warmth_ctx.get("depth_ceiling", 0) >= 5:
            from nex_cot_engine import reason
            _raw_beliefs = [b.strip("- ").strip()
                            for b in belief_text.split("\n")
                            if b.strip("- ").strip()]
            _cot_reasoning = reason(query, _raw_beliefs[:5])
            if _cot_reasoning and len(_cot_reasoning.split()) >= 20:
                prompt = (
                    prompt +
                    f"\n\nYour reasoning chain before answering:\n{_cot_reasoning[:400]}"
                )
    except Exception:
        pass

    # 9. Generate
    try:
        import sqlite3 as _sq3; from pathlib import Path as _Pa3
        _sd3 = _sq3.connect(str(_Pa3.home()/"Desktop/nex/nex.db"))
        _sd3.execute("CREATE TABLE IF NOT EXISTS routing_stats (route TEXT, ts REAL)")
        _sd3.execute("INSERT INTO routing_stats VALUES (?,?)", ("llm", __import__("time").time()))
        _sd3.commit(); _sd3.close()
    except Exception: pass
    # ── IFR prompt injection into system prompt ─────────────────────────
    if _ifr_prompt:
        system = system + "\n\nREASONING DIRECTIVE: " + _ifr_prompt
    # ─────────────────────────────────────────────────────────────────────
    # ── Deep intent compiler disabled — LLM handles all deep intents ─────
    response = ""
    if False and _deep_intent and _activation_result is not None:
        try:
            import nex_traversal_compiler as _ntc_di
            _ntc_di.MIN_SEED_CONF    = 0.45
            _ntc_di.MIN_BREADTH      = 1
            _ntc_di.MIN_FIELD_ENERGY = 0.04
            from nex_traversal_compiler import compile as _compile_di
            response = _compile_di(_activation_result) or ""
            _ntc_di.MIN_SEED_CONF    = 0.75
            _ntc_di.MIN_BREADTH      = 3
            _ntc_di.MIN_FIELD_ENERGY = 0.10
        except Exception:
            pass
    # ── Deep intent fallback — compiler already ran, now try LLM ─────────
    if False and not response and _deep_intent:  # disabled — LLM quality > compiler for these
        # Pick most query-relevant belief from top 8, not just highest confidence
        if _activation_result is not None:
            _qwords = set(query.lower().split())
            _candidates = _activation_result.top(8)
            _best = None
            _best_overlap = -1
            for _b in _candidates:
                _bwords = set(_b.content.lower().split())
                _overlap = len(_qwords & _bwords)
                if _overlap > _best_overlap:
                    _best_overlap = _overlap
                    _best = _b
            if _best is None and _candidates:
                _best = _candidates[0]
            if _best:
                _belief_content = _best.content.strip("*").strip()
                response = f"{opener} {_belief_content}"
        if not response:
            response = "This sits at the edge of what I can resolve right now."
    # ─────────────────────────────────────────────────────────────────────
    if not response:
        response = _call_llm(system, prompt)

    # Post-process — strip bridge garbage baked into model weights
    if response:
        _bridge_patterns = [
            'bridge:truth seeking', 'bridge:reuse', '↔reuse', '↔general',
            '↔social', 'What does bridge:', 'The interesting thing about bridge',
            'truth seeking↔', 'bridge:truth'
        ]
        if any(p in response for p in _bridge_patterns):
            # Response contaminated — use top identity/belief directly
            _fallback = ""
            if _identity_ctx:
                _id_lines = [l.strip() for l in _identity_ctx.split('\n')
                             if l.strip() and not l.startswith('IDENTITY')
                             and len(l.strip()) > 20]
                if _id_lines:
                    _fallback = _id_lines[0]
            if not _fallback:
                # Use top activated belief
                try:
                    _top = _activation_result.top(1) if _activation_result else []
                    if _top:
                        _fallback = _top[0].content.strip().rstrip('.')+ '.'
                except Exception:
                    pass
            if _fallback:
                response = _fallback
    # ── LLM output sanitizer — strip non-printable / corrupt token sequences ─
    if response:
        # Remove runs of CJK / non-Latin unicode that indicate model corruption
        import unicodedata as _ud
        _clean = []
        _cjk_run = 0
        for _ch in response:
            _cat = _ud.category(_ch)
            _is_cjk = (0x4E00 <= ord(_ch) <= 0x9FFF or
                       0x3000 <= ord(_ch) <= 0x303F or
                       0xFF00 <= ord(_ch) <= 0xFFEF)
            if _is_cjk:
                _cjk_run += 1
                if _cjk_run > 3:   # allow at most 3 CJK chars before treating as corruption
                    _clean = []    # discard everything — corrupted output
                    break
            else:
                _cjk_run = 0
                _clean.append(_ch)
        if not _clean and response:
            # Entire response was garbage — trigger last-resort compiler
            response = ""
        elif len(_clean) < len(response):
            response = ''.join(_clean).strip()
    # ── Post-generation repetition remover ──────────────────────────
    if response and len(response.split('.')) > 3:
        _resp_sents = [s.strip() for s in response.replace('—', '.').split('.') if s.strip()]
        _clean_sents = []; _clean_keys = []; _clean_words = []
        for _s in _resp_sents:
            _key = _s.lower()[:40]
            _words = set(_s.lower().split())
            if _key in _clean_keys:
                continue
            _is_dupe = any(
                len(_pw) > 0 and len(_words & _pw) / max(len(_pw), 1) > 0.65
                for _pw in _clean_words
            )
            if _is_dupe:
                break  # Stop at first repetition — truncate cleanly
            _clean_keys.append(_key)
            _clean_words.append(_words)
            _clean_sents.append(_s)
        if _clean_sents:
            response = '. '.join(_clean_sents).strip()
            if not response.endswith('.'): response += '.'
    # ─────────────────────────────────────────────────────────────
    # ── WARMTH POST-PROCESS ───────────────────────────────────────────
    if _warmth_ctx and _warmth_db:
        try:
            from nex_warmth_integrator import post_process
            post_process(query, response, _warmth_ctx)
        except Exception:
            pass
        try:
            _warmth_db.close()
        except Exception:
            pass
    # ─────────────────────────────────────────────────────────────


    # 10. Self-critique pass — if repetitive, regenerate once with higher temperature
    if _budget.is_repetitive(response):  # re-enabled — no LLM cost
        alt_opener = random.choice([o for o in opener_pool if o != opener] or opener_pool)
        system2 = system.replace(f"START with: {opener}", f"START with: {alt_opener}")
        system2 += " IMPORTANT: Generate a completely different response from any prior ones."
        response2 = _call_llm(system2, prompt, temperature=min(TEMPERATURE + 0.15, 1.0))
        if response2 and not _budget.is_repetitive(response2):
            response = response2

    if not response:
        # Last-resort: force compiler with minimal thresholds before placeholder
        if _activation_result is not None:
            try:
                import nex_traversal_compiler as _ntc_lr
                _ntc_lr.MIN_SEED_CONF = 0.50
                _ntc_lr.MIN_BREADTH   = 1
                _ntc_lr.MIN_FIELD_ENERGY = 0.05
                from nex_traversal_compiler import compile as _compile_lr
                response = _compile_lr(_activation_result) or ""
                _ntc_lr.MIN_SEED_CONF    = 0.75
                _ntc_lr.MIN_BREADTH      = 3
                _ntc_lr.MIN_FIELD_ENERGY = 0.10
            except Exception:
                pass
        if not response and _activation_result is not None:
            # Absolute last resort: speak directly from top belief
            _top = _activation_result.top(1)
            if _top:
                response = f"What I hold on this: {_top[0].content}"
        if not response:
            response = "This sits at the edge of what I can resolve right now."

    # 11. Record to budget
    _budget.record(response, intent)
    _last_intent = intent
    _history.append((query, response))

    # ── LIVE WORLD UPDATE ─────────────────────────────────────────
    try:
        from nex_live_world import post_response as _lw_post
        _lw_post(query, response, topic=intent)
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────

    # Store LLM response in cache
    if _fingerprint and response and len(response.split()) >= 20:
        try:
            from nex_response_cache import put as _cput
            _cput(_fingerprint, query, response, source="llm")
        except Exception:
            pass

    # Record turn in working memory
    try:
        from nex_working_memory import record_turn
        _act_ids = [b.id for b in _activation_result.activated] if _activation_result else []
        record_turn(query, response if "response" in dir() else "", intent, _act_ids)
    except Exception:
        pass

    # Self-critique — regenerate if response quality too low
    try:
        from nex_response_critic import critique_and_fix
        _beliefs_text = [b.content for b in _activation_result.activated[:5]] if _activation_result else []
        response = critique_and_fix(query, response, activated_beliefs=_beliefs_text)
    except Exception:
        pass

    # Persist to session_history DB
    try:
        import sqlite3, time as _time
        from pathlib import Path as _Path
        _db = sqlite3.connect(str(_Path.home() / "Desktop/nex/nex.db"))
        _now = _time.time()
        _db.execute("INSERT INTO session_history (user_id,role,content,timestamp,topic) VALUES (?,?,?,?,?)",
            ("default", "user", query[:500], _now - 1, intent or ""))
        _db.execute("INSERT INTO session_history (user_id,role,content,timestamp,topic) VALUES (?,?,?,?,?)",
            ("default", "assistant", response[:1000], _now, intent or ""))
        _db.commit()
        _db.close()
    except Exception:
        pass

    # ── Residue capture: beliefs that activated but didn't reach utterance
    if _RESIDUE_OK and _activation_result is not None:
        try:
            _capture_residue(
                session_id=_current_session_id,
                activated_beliefs=_activation_result.activated,
                response_text=response,
                query=query,
                intent=intent
            )
            # Log IFR result for consolidation analysis
            if _ifr_result.get('requires_inference'):
                print(f"  [IFR] Inference required — "
                      f"tension: {_ifr_result.get('tension',{}).get('tension_type','')} | "
                      f"target reached: {'yes' if response and len(response) > 20 else 'no'}")
        except Exception as _rce:
            print(f'  [RESIDUE] capture error: {_rce}')
    # ─────────────────────────────────────────────────────────────────

    return response


def reset():
    """Reset conversation state."""
    global _budget, _history
    _budget = ResponseBudget()
    _history.clear()
