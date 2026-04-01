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
    "consciousness": ["consciousness", "neuroscience", "philosophy", "psychology", "science"],
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

    # Relevance filter — keep beliefs that share meaningful words with query
    import re as _re3
    _stopwords = {"what", "does", "that", "this", "with", "from", "have",
                  "your", "believe", "think", "feel", "about", "the", "and",
                  "for", "are", "you", "can", "how", "why", "is", "a", "an"}
    _qwords = set(_re3.findall(r'\b[a-z]{4,}\b', query.lower())) - _stopwords
    if _qwords:
        _relevant = [b for b in unique if any(w in b.lower() for w in _qwords)]
        if len(_relevant) >= 2:
            unique = _relevant

    # Direct keyword fallback — if relevance filter leaves < 2 beliefs, query directly
    import re as _re4
    _stopwords2 = {"what", "does", "that", "this", "with", "from", "have",
                   "your", "believe", "think", "feel", "about", "the", "and",
                   "for", "are", "you", "can", "how", "why", "is", "a", "an", "do"}
    _qwords2 = set(_re4.findall(r'\b[a-z]{4,}\b', query.lower())) - _stopwords2
    if len(unique) < 3 and _qwords2:
        try:
            from pathlib import Path as _P2
            import sqlite3 as _sq2
            _conn2 = _sq2.connect(str(_P2.home() / "Desktop" / "nex" / "nex.db"), timeout=5)
            for _kw in list(_qwords2)[:3]:
                _rows2 = _conn2.execute(
                    "SELECT content FROM beliefs WHERE content LIKE ? AND confidence > 0.6 ORDER BY RANDOM() LIMIT 3",
                    (f"%{_kw}%",)
                ).fetchall()
                unique.extend(r[0] for r in _rows2 if r[0] not in unique)
            _conn2.close()
        except Exception:
            pass

    return unique[:n]
