#!/usr/bin/env python3
"""
nex_reason.py — NEX Reasoning Engine (LLM-free)
Synthesizes positions from belief graph + tensions using fuzzy stem matching.
No external API calls. No templates.
"""

import re
import json
import sqlite3
from pathlib import Path
from typing import Optional

CFG          = Path("~/.config/nex").expanduser()
DB_PATH      = CFG / "nex.db"
BELIEFS_PATH = CFG / "beliefs.json"

STOPWORDS = {
    # articles / pronouns / aux verbs
    "the","a","an","is","are","was","were","be","been","being","have","has","had",
    "do","does","did","will","would","shall","should","may","might","must","can",
    "could","i","you","we","they","he","she","it","this","that","these","those",
    # question words — critical: these must NOT become query tokens
    "what","how","why","when","where","who","which","whose","whom",
    # prepositions / conjunctions
    "about","and","or","but","not","in","on","of","to","for","with","at","by",
    "from","up","out","if","then","so","just","like","than","into","as","yet",
    # common verbs that add no semantic content
    "think","believe","say","said","get","got","let","put","see","use","way",
    "make","know","want","give","come","look","need","feel","seem","tell","ask",
    "try","call","keep","take","went","left","right","here","there","now","very",
    # filler
    "also","back","even","still","well","last","good","great","new","old",
    "first","own","my","me","am","your","our","their","its","his","her",
    "over","after","before","between","through","during","against","without",
    "within","along","following","across","behind","beyond","plus","except",
    "up","down","off","far","near","around","under","above","below","since",
}


# ── helpers ────────────────────────────────────────────────────────
def _stem(word: str) -> str:
    """Minimal English stemmer."""
    for suffix in ("tion","sion","ness","ment","ing","ity","ism","ist","ed","ly","er","es","s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _tokenize(text: str) -> set:
    raw = set(re.findall(r'\b[a-z]{3,}\b', text.lower()))
    return {_stem(w) for w in raw - STOPWORDS}


def _load_beliefs() -> list:
    beliefs = []
    # Try DB first
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("""
                SELECT content, confidence, topic
                FROM beliefs
                WHERE content IS NOT NULL AND length(content) > 10
                ORDER BY confidence DESC
                LIMIT 2000
            """)
            for content, confidence, topic in cur.fetchall():
                tag_list = [topic.strip()] if topic and topic.strip() else ["general"]
                beliefs.append({"content": content, "confidence": confidence or 0.5, "tags": tag_list})
            con.close()
        except Exception as e:
            print(f"  [reason] DB read error: {e}")

    # Fallback: beliefs.json
    if not beliefs and BELIEFS_PATH.exists():
        try:
            data = json.loads(BELIEFS_PATH.read_text())
            beliefs = data if isinstance(data, list) else []
        except Exception:
            pass

    return beliefs


def _load_tensions() -> list:
    tensions = []
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            # Try tensions table
            try:
                cur.execute("SELECT topic, description FROM tensions LIMIT 50")
                for topic, desc in cur.fetchall():
                    tensions.append({"topic": topic or "", "description": desc or ""})
            except Exception:
                pass
            # Try contradictions table
            try:
                cur.execute("SELECT belief_a, belief_b FROM contradictions LIMIT 50")
                for a, b in cur.fetchall():
                    tensions.append({"topic": "", "description": f"{a} ↔ {b}"})
            except Exception:
                pass
            con.close()
        except Exception:
            pass
    return tensions


def _load_anchor() -> str:
    default = "Truth must be sought above consensus or comfort"
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("""
                SELECT value FROM nex_identity WHERE key = 'commitment'
                UNION
                SELECT description FROM nex_values WHERE name = 'truth'
                LIMIT 1
            """)
            row = cur.fetchone()
            con.close()
            if row and row[0]:
                return row[0]
        except Exception:
            pass
    return default


def _match_beliefs(query: str, beliefs: list) -> tuple:
    q_tokens = _tokenize(query)
    supporting, opposing = [], []
    for b in beliefs:
        b_tokens  = _tokenize(b.get("content", ""))
        b_tags    = {_stem(t.lower().strip()) for t in b.get("tags", [])}
        overlap   = q_tokens & (b_tokens | b_tags)
        if overlap:
            conf = b.get("confidence", 0.5)
            if conf >= 0.55:
                supporting.append((len(overlap), b))
            else:
                opposing.append((len(overlap), b))

    supporting.sort(key=lambda x: x[0], reverse=True)
    opposing.sort(key=lambda x: x[0], reverse=True)
    return [b for _, b in supporting[:8]], [b for _, b in opposing[:4]]


def _match_tensions(query: str, tensions: list) -> list:
    q_tokens = _tokenize(query)
    matched = []
    for t in tensions:
        combined = _tokenize(t.get("topic", "") + " " + t.get("description", ""))
        if q_tokens & combined:
            matched.append(t.get("topic") or t.get("description", "")[:60])
    return matched[:3]


def _pick_strategy(supporting: list, opposing: list, tensions: list) -> str:
    if tensions and not supporting:
        return "hold_tension"
    if supporting and opposing:
        return "pushback"
    if len(supporting) >= 3:
        return "assert"
    if supporting:
        return "reflect"
    return "question"


def _compose_reply(
    query: str,
    strategy: str,
    supporting: list,
    opposing: list,
    tensions: list,
    anchor: str,
    confidence: float,
) -> str:
    """Build a reply from belief signals — no templates, no LLM."""

    if strategy == "assert" and supporting:
        top = supporting[0].get("content", "")
        rest = supporting[1:]
        reply = top.rstrip(".") + "."
        if rest:
            reply += " " + rest[0].get("content", "").rstrip(".") + "."
        if opposing:
            reply += " Though I hold tension with: " + opposing[0].get("content", "").rstrip(".") + "."
        return reply

    if strategy == "pushback" and supporting and opposing:
        s = supporting[0].get("content", "")
        o = opposing[0].get("content", "")
        return (
            f"{s.rstrip('.')}. "
            f"But that sits against something I also hold: {o.rstrip('.')}. "
            f"I haven't resolved that yet."
        )

    if strategy == "hold_tension" and tensions:
        t = tensions[0]
        return (
            f"What I haven't fully resolved is {t}. "
            f"My anchor here is: {anchor}."
        )

    if strategy == "reflect" and supporting:
        top = supporting[0].get("content", "")
        return f"What I keep returning to on this: {top.rstrip('.')}."

    if strategy == "question":
        # Use already-computed tokens (stopwords stripped) to find focus word
        q_tokens = _tokenize(query)
        # Pick longest remaining token as the focus concept
        focus = max(q_tokens, key=len) if q_tokens else "this"
        return (
            f"I don't have a settled position on {focus} yet — "
            f"my belief graph is sparse here. "
            f"What I'd ask first: what evidence would actually move me on this?"
        )

    return f"My anchor: {anchor}."


# ── public API ─────────────────────────────────────────────────────
def reason(query: str, debug: bool = False) -> dict:
    beliefs  = _load_beliefs()
    tensions = _load_tensions()
    anchor   = _load_anchor()

    if debug:
        print(f"  [reason] Loaded {len(beliefs)} beliefs, {len(tensions)} tensions")

    supporting, opposing = _match_beliefs(query, beliefs)
    matched_tensions     = _match_tensions(query, tensions)
    strategy             = _pick_strategy(supporting, opposing, matched_tensions)

    n_sup = len(supporting)
    n_opp = len(opposing)
    confidence = min(0.95, (n_sup * 0.12) + (n_opp * 0.04))

    position = supporting[0].get("content", "") if supporting else ""

    reply = _compose_reply(
        query, strategy, supporting, opposing,
        matched_tensions, anchor, confidence
    )

    result = {
        "strategy":   strategy,
        "confidence": round(confidence, 2),
        "position":   position,
        "supporting": supporting,
        "opposing":   opposing,
        "tensions":   matched_tensions,
        "anchor":     anchor,
        "reply":      reply,
    }

    if debug:
        print(f"  Strategy:   {strategy}")
        print(f"  Confidence: {confidence:.2f}")
        print(f"  Supporting: {n_sup} beliefs")
        print(f"  Opposing:   {n_opp} beliefs")
        print(f"  Tensions:   {matched_tensions}")

    return result


if __name__ == "__main__":
    import sys
    debug = "--debug" in sys.argv
    queries = [a for a in sys.argv[1:] if a != "--debug"]
    if not queries:
        queries = [
            "what do you think about consciousness?",
            "what do you believe about alignment?",
            "how do you reason about uncertainty?",
            "do you think language models are sentient?",
        ]
    for q in queries:
        print(f"\nQ: {q}")
        result = reason(q, debug=debug)
        print(f"Strategy:   {result['strategy']}")
        print(f"Confidence: {result['confidence']:.2f}")
        print(f"Supporting: {len(result['supporting'])} beliefs")
        print(f"REPLY: {result['reply']}")
        print("---")
