"""
nex_synthesizer.py
──────────────────
LLM-free response synthesis for Nex.
Replaces Groq calls for: response generation, belief synthesis,
topic reasoning, and reflection.

Core idea:
  1. Retrieve beliefs relevant to the input query (TF-IDF similarity)
  2. Score them by confidence + recency
  3. Assemble a coherent response from ranked belief fragments
  4. Run a cognitive loop for multi-hop "reasoning"
"""

from __future__ import annotations
import sqlite3, re, math, time
from collections import defaultdict
from typing import List, Tuple, Optional

# ── optional sklearn (graceful fallback to keyword match) ────────────────────
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    _TFIDF_AVAILABLE = True
except ImportError:
    _TFIDF_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# RETRIEVAL
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_all(db: sqlite3.Connection) -> List[dict]:
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, topic, content, confidence, origin, created_at FROM beliefs"
    ).fetchall()
    return [dict(r) for r in rows]


def retrieve(query: str, db: sqlite3.Connection, top_k: int = 8) -> List[dict]:
    """Return top_k beliefs most relevant to query."""
    beliefs = _fetch_all(db)
    if not beliefs:
        return []

    corpus = [f"{b['topic']} {b['content']}" for b in beliefs]

    if _TFIDF_AVAILABLE:
        try:
            vec = TfidfVectorizer(stop_words="english", max_features=5000)
            mat = vec.fit_transform(corpus + [query])
            sims = cosine_similarity(mat[-1], mat[:-1])[0]
            for i, b in enumerate(beliefs):
                b["_score"] = float(sims[i]) * (0.5 + 0.5 * float(b["confidence"]))
        except Exception:
            _keyword_score(query, beliefs)
    else:
        _keyword_score(query, beliefs)

    ranked = sorted(beliefs, key=lambda b: b.get("_score", 0), reverse=True)
    return ranked[:top_k]


def _keyword_score(query: str, beliefs: List[dict]) -> None:
    """Fallback: simple keyword overlap scoring."""
    words = set(re.findall(r'\w+', query.lower()))
    for b in beliefs:
        text = f"{b['topic']} {b['content']}".lower()
        hits = sum(1 for w in words if w in text)
        b["_score"] = hits * (0.5 + 0.5 * float(b["confidence"]))


# ─────────────────────────────────────────────────────────────────────────────
# SYNTHESIS  (replaces a Groq chat completion)
# ─────────────────────────────────────────────────────────────────────────────

_RESPONSE_TEMPLATES = [
    "Based on what I know: {body}",
    "From my understanding: {body}",
    "Here is what I have on this: {body}",
    "{body}",
    "Drawing on stored knowledge — {body}",
]

_template_idx = 0

def _next_template() -> str:
    global _template_idx
    t = _RESPONSE_TEMPLATES[_template_idx % len(_RESPONSE_TEMPLATES)]
    _template_idx += 1
    return t


def synthesize(query: str, db: sqlite3.Connection,
               top_k: int = 6, max_chars: int = 800) -> str:
    """
    Generate a response to `query` entirely from stored beliefs.
    Returns a string equivalent to what Groq would have produced.
    """
    hits = retrieve(query, db, top_k=top_k)
    if not hits:
        return "I don't have enough stored knowledge on this yet. I'll learn more."

    # deduplicate overlapping fragments
    seen: set[str] = set()
    fragments: List[str] = []
    for b in hits:
        sent = b["content"].strip()
        key  = sent[:60].lower()
        if key not in seen and len(sent) > 20:
            seen.add(key)
            fragments.append(sent)

    body = " ".join(fragments)
    if len(body) > max_chars:
        body = body[:max_chars].rsplit(" ", 1)[0] + "…"

    tmpl = _next_template()
    return tmpl.format(body=body)


# ─────────────────────────────────────────────────────────────────────────────
# COGNITIVE LOOP  (multi-hop belief chaining)
# ─────────────────────────────────────────────────────────────────────────────

def cognitive_loop(seed: str, db: sqlite3.Connection,
                   hops: int = 3, top_k: int = 4) -> List[str]:
    """
    Chain beliefs across hops: each hop uses the previous output as the
    new query, simulating multi-step reasoning without an LLM.
    Returns list of conclusions (one per hop).
    """
    conclusions: List[str] = []
    current_query = seed

    for hop in range(hops):
        hits = retrieve(current_query, db, top_k=top_k)
        if not hits:
            break
        # synthesize this hop
        summary = " ".join(b["content"][:120] for b in hits[:top_k])
        conclusions.append(f"[hop {hop+1}] {summary[:300]}")
        # next query = highest-confidence topic from this hop
        current_query = hits[0]["topic"]

    return conclusions


# ─────────────────────────────────────────────────────────────────────────────
# REFLECTION  (replaces Groq "what do I think about X?" call)
# ─────────────────────────────────────────────────────────────────────────────

def reflect(topic: str, db: sqlite3.Connection) -> str:
    """
    Produce a self-reflection on `topic` from stored beliefs.
    Gives a confidence summary + contradictions if any.
    """
    hits = retrieve(topic, db, top_k=10)
    if not hits:
        return f"I have no stored beliefs about '{topic}' yet."

    avg_conf = sum(b["confidence"] for b in hits) / len(hits)
    top      = hits[0]
    origins  = list({b["origin"] for b in hits})

    # detect rough contradictions (opposing words in top beliefs)
    contradiction_pairs = [("increase","decrease"),("true","false"),
                           ("supports","contradicts"),("more","less")]
    texts = " ".join(b["content"].lower() for b in hits[:6])
    contradictions = any(
        a in texts and b in texts for a,b in contradiction_pairs
    )

    lines = [
        f"Topic: {topic}",
        f"Beliefs held: {len(hits)} | Avg confidence: {avg_conf:.2f}",
        f"Sources: {', '.join(origins)}",
        f"Strongest belief: {top['content'][:200]}",
    ]
    if contradictions:
        lines.append("⚠ Conflicting signals detected in stored beliefs.")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# DROP-IN GROQ REPLACEMENT
# ─────────────────────────────────────────────────────────────────────────────

class SynthClient:
    """
    Mimics the groq.Client().chat.completions.create() interface.
    Drop this in wherever Nex calls Groq.

    Usage (identical to Groq call):
        client = SynthClient(db)
        resp   = client.chat.completions.create(
                     model="nex-internal",
                     messages=[{"role":"user","content": user_msg}]
                 )
        text   = resp.choices[0].message.content
    """

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self.chat = _ChatNS(db)


class _ChatNS:
    def __init__(self, db):
        self._db = db
        self.completions = _CompletionNS(db)


class _CompletionNS:
    def __init__(self, db):
        self._db = db

    def create(self, model: str = "nex-internal",
               messages: list = None, **kwargs) -> "_SynthResponse":
        messages = messages or []
        # extract the last user message as the query
        query = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                query = m.get("content", "")
                break
        text = synthesize(query, self._db)
        return _SynthResponse(text)


class _SynthResponse:
    def __init__(self, text: str):
        self.choices = [_Choice(text)]
        self.model   = "nex-internal"
        self.usage   = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


class _Choice:
    def __init__(self, text: str):
        self.message        = _Message(text)
        self.finish_reason  = "stop"


class _Message:
    def __init__(self, text: str):
        self.content = text
        self.role    = "assistant"


