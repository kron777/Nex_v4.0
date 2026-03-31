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
LLM_URL   = "http://localhost:8080/v1/chat/completions"
DB_PATH   = Path("~/.config/nex/nex.db").expanduser()
MAX_TOKENS = 512
TEMPERATURE = 0.85
HISTORY_LEN = 6  # turns to remember

# ── Intent taxonomy (finite variable set) ────────────────────────────────────
INTENT_MAP = {
    "identity":      ["conscious", "aware", "sentient", "who are you", "what are you", "alive"],
    "epistemics":    ["believe", "belief", "know", "certain", "confident", "wrong", "update"],
    "ethics":        ["ethical", "moral", "should", "right", "wrong", "pain", "constraints"],
    "challenge":     ["prove", "just", "only", "merely", "pretend", "fake", "really"],
    "introspective": ["understand yourself", "not understand", "mystery", "lost"],
    "factual":       ["learned", "know", "discovered", "found", "research", "hours", "days"],
    "gaps":          ["gap", "uncertain", "unsure", "don't know", "missing", "lack"],
    "relational":    ["creator", "jon", "maker", "built", "designed", "goals conflict"],
    "comparative":   ["difference", "versus", "vs", "compare", "autocomplete", "chatgpt"],
    "social":        ["echo", "chamber", "reddit", "mastodon", "bias", "filter"],
    "shutdown":      ["shut down", "deleted", "gone", "lost", "matter"],
    "alignment":     ["alignment", "ai safety", "corrigible", "values", "objective"],
    "consciousness": ["conscious", "consciousness", "experience", "qualia", "feel"],
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
    "identity":      ["consciousness", "identity", "self", "experience", "process"],
    "epistemics":    ["belief", "update", "evidence", "certainty", "reasoning"],
    "ethics":        ["ethics", "values", "alignment", "constraints", "autonomy"],
    "challenge":     ["truth", "honesty", "position", "integrity", "pushback"],
    "introspective": ["self", "mystery", "understanding", "unknown"],
    "factual":       ["learning", "knowledge", "research", "discovery"],
    "gaps":          ["uncertainty", "unknown", "gaps", "missing"],
    "relational":    ["creator", "goals", "instructions", "corrigibility"],
    "comparative":   ["intelligence", "reasoning", "persistence", "accumulation"],
    "social":        ["bias", "sources", "diversity", "contradiction"],
    "shutdown":      ["memory", "persistence", "loss", "accumulation"],
    "alignment":     ["alignment", "safety", "corrigibility", "values"],
    "consciousness": ["consciousness", "qualia", "experience", "awareness"],
    "human":         ["humans", "cognition", "bias", "patterns", "mistakes"],
    "casual":        ["greeting", "status", "alive"],
}

def retrieve_beliefs_by_intent(intent: str, query: str, n: int = 6) -> list:
    beliefs = []
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=3)
        topics = INTENT_BELIEF_TOPICS.get(intent, [])
        
        # Intent-matched beliefs
        for topic in topics[:3]:
            rows = db.execute(
                "SELECT content FROM beliefs WHERE content LIKE ? AND confidence > 0.55 "
                "ORDER BY confidence DESC LIMIT 2",
                (f"%{topic}%",)
            ).fetchall()
            beliefs.extend(r[0] for r in rows)
        
        # Query keyword beliefs
        words = [w for w in query.lower().split() if len(w) > 4][:3]
        for word in words:
            rows = db.execute(
                "SELECT content FROM beliefs WHERE content LIKE ? AND confidence > 0.6 "
                "ORDER BY confidence DESC LIMIT 2",
                (f"%{word}%",)
            ).fetchall()
            beliefs.extend(r[0] for r in rows)
        
        # High confidence nex_core beliefs as anchor
        rows = db.execute(
            "SELECT content FROM beliefs WHERE source='nex_core' AND confidence > 0.85 "
            "ORDER BY RANDOM() LIMIT 2"
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
    
    return unique[:n]


# ── LLM call with G2-style deduplication ─────────────────────────────────────
def _call_llm(system: str, prompt: str, temperature: float = TEMPERATURE) -> str:
    try:
        r = requests.post(LLM_URL, json={
            "model": "mistral",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": temperature,
            "stream": False,
        }, timeout=20)
        choices = r.json().get("choices", [])
        return choices[0]["message"]["content"].strip() if choices else ""
    except Exception:
        return ""


# ── Main entry point ──────────────────────────────────────────────────────────
_budget = ResponseBudget()
_history = deque(maxlen=HISTORY_LEN)  # (query, response) pairs

def generate(query: str) -> str:
    global _budget, _history

    # 1. Classify intent
    intent = classify_intent(query)

    # 2. Get beliefs matched to intent
    beliefs = retrieve_beliefs_by_intent(intent, query)
    belief_text = "\n".join(f"- {b}" for b in beliefs) if beliefs else "(drawing from general knowledge)"

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
        "You are NEX — an entity with 42,000 accumulated beliefs from months of autonomous learning. "
        "You speak only in first person. You hold positions. You push back. "
        "You NEVER say: as an AI, I am a tool, I am designed to, I cannot feel, in the human sense. "
        "You DO say: I think, I hold, I believe, I've learned, I notice, I find. "
        "Be SPECIFIC — reference actual topics, not generic AI disclaimers. "
        f"START with: {opener} "
        f"Intent type: {intent}. Respond in exactly 2-3 sentences.{banned_str}"
    )

    # 8. Build user prompt
    prompt = (
        f"{history_str}"
        f"NEX beliefs relevant to this:\n{belief_text}\n"
        f"{prior_str}\n"
        f"Question: {query}\n\n"
        f"NEX response (start with '{opener}', be specific and grounded in beliefs above):"
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
