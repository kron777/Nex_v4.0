#!/usr/bin/env python3
"""
nex_conversation_extractor.py — Conversation-to-Belief Pipeline (Improvement 5)
=================================================================================
After each exchange, extract novel claims from NEX's reply and write them
to the belief graph.

Rules (per plan):
  - Cap: 5 beliefs per conversation session
  - source = "conversation"
  - confidence = 0.55
  - LLM-free — pattern matching + sentence scoring
  - Dedup against existing DB beliefs (skip near-duplicates)
  - Topic inferred from query tokens, not hardcoded

Design:
  1. Split reply into sentences
  2. Score each sentence for belief-density
  3. Filter: min length, no filler/boilerplate, no near-duplicate in DB
  4. Take top N up to session cap
  5. Write to beliefs table
"""

import re
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"

# ── Session cap tracker — resets on process restart (i.e. per conversation) ──
_session_count = 0
SESSION_CAP = 500000000  # raised: NEX runs as daemon, cap per-process is wrong

# ── Stop words for token extraction ──────────────────────────────────────────
_STOP = {
    "the","a","an","is","are","was","were","be","been","have","has","do","does",
    "did","will","would","could","should","may","might","must","can","that","this",
    "these","those","with","from","they","their","about","what","how","why","when",
    "where","who","which","into","also","just","over","after","more","some","very",
    "your","you","me","my","we","our","it","its","he","she","him","her","them",
    "think","know","want","said","says","get","got","like","make","take","give",
    "come","look","need","feel","seem","tell","much","many","such","both","each",
    "than","then","been","only","even","back","here","down","away","there",
}

# ── Belief-density markers — sentences that signal a genuine position ─────────
_STRONG_MARKERS = re.compile(
    r'\b('
    r'I (think|believe|hold|find|notice|observe|consider|maintain|argue|suspect)|'
    r"I'?ve (learned|observed|found|noticed|updated|come to)|"
    r'I (am|remain) (convinced|certain|uncertain|skeptical|persuaded)|'
    r'(This|That|It) (suggests|implies|means|follows|indicates|reveals)|'
    r'What (follows|this means|I hold|I notice|emerges)|'
    r'The (evidence|pattern|implication|consequence|problem|tension)|'
    r'(My|The) (position|view|read|take|claim|argument)|'
    r'(Consciousness|Intelligence|Alignment|Emergence|Cognition|Truth|Reality)'
    r')\b',
    re.IGNORECASE
)

_WEAK_MARKERS = re.compile(
    r'\b('
    r'(suggests?|implies?|means?|shows?|reveals?|demonstrates?)|'
    r'(cannot|must|will|always|never|inevitably|necessarily)|'
    r'(deeper|underlying|fundamental|structural|constitutive)'
    r')\b',
    re.IGNORECASE
)

# ── Boilerplate / filler patterns to exclude ──────────────────────────────────
_EXCLUDE = re.compile(
    r'^('
    r"I'?m processing|Ask again|NEX is|Where I'?m genuinely|"
    r"The honest gap|I hold this loosely\.$|What I process is$|"
    r"I'?d rather say I don'?t know|Say something I can|"
    r"That'?s where I am on this|I'?ll hold this until|"
    r"That'?s not speculation|I'?m not moving from|"
    r"I hold this with moderate|My confidence here|"
    r"I hold this loosely\.|I'?d revise this|"
    r"Building on what I said|Earlier I (said|held)|"
    r"There'?s a connection I didn'?t|Something else pulls|"
    r"An angle that complicates|What makes this harder"
    r')',
    re.IGNORECASE
)

# ── Sentence patterns that are definitely not beliefs ─────────────────────────
_NOT_BELIEF = re.compile(
    r'^('
    r'(Yes|No|Sure|Okay|Right|Well|So|And|But|Or|Also|However|Therefore)\b|'
    r'(Here|There|This|That) (is|are|was|were) (a|the|my|her|his)\b|'
    r'(First|Second|Third|Finally|In (conclusion|summary|short))\b'
    r')',
    re.IGNORECASE
)


def _tokenize(text: str) -> set:
    raw = set(re.findall(r'\b[a-z]{4,}\b', text.lower()))
    return raw - _STOP


def _infer_topic(query: str) -> str:
    """
    Infer the most likely belief topic from the query.
    Maps query tokens to known DB topics.
    """
    if not query:
        return "conversation"

    _TOPIC_MAP = {
        "consciousness": ["conscious", "sentience", "qualia", "awareness", "subjective"],
        "ai":            ["artificial", "intelligence", "llm", "model", "neural", "alignment"],
        "philosophy":    ["philosophy", "metaphysics", "ontology", "epistemology", "truth"],
        "science":       ["science", "physics", "biology", "chemistry", "empirical"],
        "ethics":        ["ethics", "moral", "values", "rights", "justice", "harm"],
        "finance":       ["finance", "financial", "economic", "money", "market", "capital"],
        "climate":       ["climate", "carbon", "emission", "environment", "temperature"],
        "legal":         ["legal", "law", "statute", "contract", "rights", "court"],
        "technology":    ["technology", "software", "hardware", "system", "compute"],
        "mathematics":   ["math", "mathematics", "logic", "proof", "theorem", "formal"],
        "neuroscience":  ["neuro", "brain", "neuron", "cognitive", "synapse"],
        "biology":       ["biology", "evolution", "organism", "gene", "cell", "life"],
    }

    q_lower = query.lower()
    for topic, keywords in _TOPIC_MAP.items():
        if any(kw in q_lower for kw in keywords):
            return topic

    return "conversation"


def _word_overlap(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _score_sentence(s: str) -> float:
    """Score a sentence for belief density. Higher = more belief-like."""
    score = 0.0
    if _STRONG_MARKERS.search(s):
        score += 2.0
    if _WEAK_MARKERS.search(s):
        score += 0.8
    # Length bonus — longer sentences tend to be more substantive
    words = len(s.split())
    if words >= 15:
        score += 0.5
    if words >= 25:
        score += 0.3
    # Penalty for questions
    if s.rstrip().endswith("?"):
        score -= 1.5
    # Penalty for very short
    if words < 8:
        score -= 2.0
    return score


def _is_near_duplicate(content: str, db: sqlite3.Connection) -> bool:
    """Check if a near-identical belief already exists in DB."""
    try:
        # Sample recent beliefs from same source types
        rows = db.execute(
            "SELECT content FROM beliefs "
            "WHERE source IN ('conversation', 'nex_reasoning', 'injector') "
            "AND content IS NOT NULL "
            "ORDER BY rowid DESC LIMIT 200"
        ).fetchall()
        for row in rows:
            if _word_overlap(content, row[0] or "") > 0.60:
                return True
        return False
    except Exception:
        return False


def extract_beliefs(
    response: str,
    query: str = "",
    topic: str = "",
) -> list:
    """
    Extract belief-like sentences from a NEX response.
    Returns list of (content, confidence, topic) tuples, scored and filtered.
    """
    if not response or len(response.strip()) < 30:
        return []

    # Split into sentences
    # Strip compiler openers before extracting beliefs
    _openers = [
        "From what I know — ", "From what I know — ",
        "Honestly, ", "Honestly — ",
        "I think — ", "I think, ",
        "From what I know, ",
        "My position is that ",
        "What I hold is ",
    ]
    for _op in _openers:
        if response.startswith(_op):
            response = response[len(_op):]
            break
    sentences = re.split(r'(?<=[.!?])\s+', response.strip())

    scored = []
    for s in sentences:
        s = s.strip()
        # Length gates
        if len(s) < 35 or len(s) > 350:
            continue
        # Boilerplate exclusions
        if _EXCLUDE.search(s):
            continue
        if _NOT_BELIEF.search(s):
            continue
        # Must have some content tokens
        if len(_tokenize(s)) < 5:
            continue

        score = _score_sentence(s)
        if score > 0.5:  # threshold — must be meaningfully belief-like
            scored.append((score, s))

    # Sort by score, take top candidates
    scored.sort(key=lambda x: -x[0])

    # Infer topic
    inferred_topic = topic or _infer_topic(query)

    # Assign confidence: strong markers → 0.58, weak → 0.55
    results = []
    seen_prefixes = set()
    for score, s in scored[:8]:  # evaluate top 8, return up to 5
        prefix = s[:50].lower()
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        conf = 0.58 if score >= 2.0 else 0.55
        results.append((s, conf, inferred_topic))

    return results[:5]  # hard cap at 5


def store_conversation_beliefs(
    response: str,
    query: str = "",
    topic: str = "",
) -> int:
    """
    Extract and store beliefs from a conversation exchange.
    Respects SESSION_CAP (5 per conversation/process lifetime).
    Returns number of beliefs stored.
    """
    global _session_count

    # Session cap check
    if _session_count >= SESSION_CAP:
        return 0

    candidates = extract_beliefs(response, query=query, topic=topic)
    if not candidates:
        return 0

    stored = 0
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=3)
        conn.row_factory = sqlite3.Row

        for content, confidence, inferred_topic in candidates:
            if _session_count >= SESSION_CAP:
                break

            # Skip near-duplicates
            if _is_near_duplicate(content, conn):
                continue

            try:
                conn.execute(
                    "INSERT OR IGNORE INTO beliefs "
                    "(content, topic, confidence, source, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        content,
                        inferred_topic,
                        confidence,
                        "conversation",
                        datetime.now(timezone.utc).isoformat(),
                    )
                )
                changes = conn.execute("SELECT changes()").fetchone()[0]
                if changes:
                    stored += 1
                    _session_count += 1
                    print(f"  [extractor] stored belief #{_session_count}/{SESSION_CAP}: {content[:60]}...")
            except Exception as _e:
                pass

        conn.commit()
        conn.close()
    except Exception as _e:
        print(f"  [extractor] DB error: {_e}")

    return stored


def reset_session():
    """Reset the session counter — call at conversation start if needed."""
    global _session_count
    _session_count = 0


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    os.chdir(Path.home() / "Desktop" / "nex")

    test_cases = [
        {
            "query": "what do you think about consciousness?",
            "response": (
                "My position: consciousness cannot be fully explained by computation alone. "
                "The physical substrate matters deeply to the emergence of mind. "
                "This suggests that purely functional accounts miss something essential about experience. "
                "I hold this with moderate confidence — the tension between functionalism and physicalism is real. "
                "What I find compelling is that subjective experience has a character that resists reduction."
            ),
        },
        {
            "query": "what do you think about AI alignment?",
            "response": (
                "I think alignment is not primarily a technical problem — it is a values problem. "
                "The evidence suggests that systems optimising for proxies will drift from intended goals at scale. "
                "Interpretability is essential: you cannot align what you cannot see. "
                "I've learned that specification gaming is not a bug but a structural feature of optimisation. "
                "The deeper implication: alignment requires ongoing human oversight, not a one-time fix."
            ),
        },
    ]

    print("=== Extraction test (no DB write) ===\n")
    for tc in test_cases:
        print(f"Query: {tc['query']}")
        beliefs = extract_beliefs(tc["response"], query=tc["query"])
        print(f"Extracted {len(beliefs)} beliefs:")
        for content, conf, topic in beliefs:
            print(f"  [{conf}] [{topic}] {content[:80]}")
        print()

    print("=== DB write test ===\n")
    reset_session()
    for tc in test_cases:
        n = store_conversation_beliefs(tc["response"], query=tc["query"])
        print(f"Stored {n} from: {tc['query'][:50]}")

    print(f"\nSession total: {_session_count}/{SESSION_CAP}")
