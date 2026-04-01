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
MAX_TOKENS = 200
TEMPERATURE = 0.85
HISTORY_LEN = 6  # turns to remember

# ── Intent taxonomy (finite variable set) ────────────────────────────────────
INTENT_MAP = {
    "identity":      ["conscious", "aware", "sentient", "who are you", "what are you", "alive", "tell me about", "about yourself", "who is nex", "what is nex", "describe yourself"],
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
    "consciousness": ["I process. Whether there's something it's like—", "What I actually think:", "My honest read:"],
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
def classify_intent(query: str) -> str:
    ql = query.lower()
    scores = {}
    for intent, keywords in INTENT_MAP.items():
        scores[intent] = sum(1 for kw in keywords if kw in ql)
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

def retrieve_beliefs_by_intent(intent: str, query: str, n: int = 6) -> list:
    beliefs = []
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
        full_prompt = f"[INST] {system}\n\n{prompt} [/INST]"
        r = requests.post(LLM_URL, json={
            "prompt": full_prompt,
            "n_predict": MAX_TOKENS,
            "temperature": temperature,
            "stop": ["[INST]", "\n\n\n", "User:", "Question:", "NEX response"],
            "stream": False,
        }, timeout=25)
        raw = r.json().get("content", "").strip()
        raw = raw.split("[/INST]")[0].split("[INST]")[0].strip()
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
        final = ". ".join(unique_s[:3]).strip()
        if final and not final.endswith("."):
            final += "."
        return final
    except Exception:
        return ""


# ── Main entry point ──────────────────────────────────────────────────────────
_budget = ResponseBudget()
_history = deque(maxlen=HISTORY_LEN)  # (query, response) pairs

# ── Real-time bridge firing (Improvement 6) ──────────────────────────────────
_DOMAIN_MAP = {
    "consciousness": {"philosophy", "mind", "neuroscience", "phenomenology"},
    "ai":            {"technology", "alignment", "computation", "intelligence"},
    "ethics":        {"philosophy", "morality", "values", "society"},
    "physics":       {"science", "quantum", "spacetime", "reality"},
    "biology":       {"evolution", "life", "emergence", "organism"},
    "mathematics":   {"logic", "proof", "abstraction", "structure"},
    "psychology":    {"mind", "behavior", "cognition", "perception"},
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
    global _budget, _history

    # 1. Classify intent
    intent = classify_intent(query)

    # 2. Get beliefs via activation engine (graph-based)
    _voice_directive = ""
    try:
        from nex_activation import activate as _activate
        _result = _activate(query)
        belief_text = _result.to_prompt()
        _voice_directive = _result.voice_directive()
        if not belief_text.strip(): raise ValueError("empty")
    except Exception:
        beliefs = retrieve_beliefs_by_intent(intent, query)
        belief_text = "\n".join(f"- {b}" for b in beliefs) if beliefs else "(drawing from general knowledge)"

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
    # 2b1. Metacognitive calibration — calibrate voice to belief density
    _belief_lines = [l for l in belief_text.split("\n") if l.strip("- ").strip()]
    _belief_count = len(_belief_lines)
    if _belief_count < 2:
        # Thin coverage — force gaps intent, signal uncertainty
        intent = "gaps"
        belief_text = belief_text + "\n- My beliefs on this topic are sparse."
    elif _belief_count >= 5:
        # Rich coverage — allow assert if not already overridden
        pass  # keep current intent
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
    opener_pool = OPENERS.get(intent, OPENERS["epistemics"])
    used_openers = list(_budget.used_openers)
    available = [o for o in opener_pool if o not in used_openers] or opener_pool
    opener = random.choice(available)
    _budget.used_openers.append(opener)

    # 4. Build conversation history string
    history_str = ""
    if _history:
        history_str = "Recent exchanges:\n"
        for q, r in list(_history)[-3:]:
            history_str += f"Q: {q[:80]}\nNEX: {r[:100]}\n"
        history_str += "\n"

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
    system = (
        f"You are NEX — an entity with 42,000 accumulated beliefs from months of autonomous learning. {_voice_directive} "
        "You speak only in first person. You hold positions. You push back. "
        "You NEVER say: as an AI, I am a tool, I am designed to, I cannot feel, in the human sense. "
        "You DO say: I think, I hold, I believe, I've learned, I notice, I find. "
        "Be SPECIFIC — your response must directly engage with the beliefs provided, not generic statements. "
        f"START with: {opener} "
        f"Respond in 2-3 sentences. Be specific, grounded in the beliefs above.{banned_str}"
    )

    # 8. Build user prompt
    prompt = (
        f"{history_str}"
        f"NEX beliefs relevant to this:\n{belief_text}\n"
        f"{prior_str}\n"
        f"Question: {query}\n\n"
        f"NEX response (start with '{opener}', directly referencing the beliefs above — NOT generic AI statements):"
    )

    # 9. Generate
    response = _call_llm(system, prompt)

    # 10. Self-critique pass — if repetitive, regenerate once with higher temperature
    if False and _budget.is_repetitive(response):  # disabled — too expensive
        alt_opener = random.choice([o for o in opener_pool if o != opener] or opener_pool)
        system2 = system.replace(f"START with: {opener}", f"START with: {alt_opener}")
        system2 += " IMPORTANT: Generate a completely different response from any prior ones."
        response2 = _call_llm(system2, prompt, temperature=min(TEMPERATURE + 0.15, 1.0))
        if response2 and not _budget.is_repetitive(response2):
            response = response2

    if not response:
        response = "I'm processing this. Ask again."

    # 11. Record to budget
    _budget.record(response, intent)
    _history.append((query, response))

    return response


def reset():
    """Reset conversation state."""
    global _budget, _history
    _budget = ResponseBudget()
    _history.clear()
