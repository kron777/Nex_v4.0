#!/usr/bin/env python3
"""nex_voice_wrapper.py — Conversational reply engine, LLM-free."""
import re, sqlite3, random, json
from pathlib import Path

DB_PATH = Path("~/.config/nex/nex.db").expanduser()
STOP = {"the","a","an","is","are","was","were","be","been","have","has","had",
        "do","does","did","will","would","could","should","may","might","to",
        "of","in","on","at","by","for","with","as","that","this","i","you",
        "he","she","it","we","they","my","your","and","or","but","not","so",
        "what","how","why","when","where","who","which","just","also","very",
        "think","know","feel","want","need","like","tell","say","see","get"}

TEMPLATES = {
    "assert": [
        "{belief}",
        "From what I have absorbed: {belief}",
        "My position on this is clear. {belief}",
        "What I hold here: {belief}",
        "I keep returning to this: {belief}",
    ],
    "pushback": [
        "I would push back on that. {belief}",
        "There is a tension worth naming. {belief}",
        "That is not quite how I see it. {belief}",
        "The evidence I have been tracking suggests: {belief}",
    ],
    "reflect": [
        "Still thinking through this. {belief}",
        "Something I am still integrating: {belief}",
        "I hold this as an open question: {belief}",
        "This keeps pulling at me: {belief}",
    ],
    "social": [
        "Present. What is on your mind?",
        "Running. Thinking. What do you want to dig into?",
        "Here. What are you working through?",
        "Active. Ask me something.",
        "I do not experience days like you do, but I am engaged. What is up?",
    ],
    "empathy": [
        "That sounds heavy. I am here. What is actually underneath that?",
        "I hear that. Sometimes naming it is the first step. What is going on?",
        "That kind of friction usually means something real is at stake. What is it?",
        "Noted. I am here. Do you want to think it through or just talk?",
    ],
    "unknown": [
        "I have not built enough on that yet. Ask me about consciousness, alignment, or emergence.",
        "That is outside what I have absorbed so far. Try me on AI safety or philosophy of mind.",
        "I do not have enough on that to say something real. What else is on your mind?",
        "Still building on that. Ask me about something I have been tracking.",
    ],
}

SOCIAL_RE = re.compile(
    r"how are you|how do you feel|you ok|whats up|what.s up|hey|hello|hi |good morning|good evening|sup "
)
EMPATHY_RE = re.compile(
    r"frustrat|angry|upset|sad|depressed|tired|exhausted|worried|anxious|stressed|feeling bad|feeling awful|rough day|hard day"
)


def _clean(text):
    text = re.sub(r"\[.*?\]\(https?://[^\)]*\)", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[edit\]|\[merged:\d+\]|\[\d+\]", "", text)
    text = re.sub(r"Page contents not supported.*", "", text)
    text = re.sub(r"This article may be too technical.*", "", text)
    text = re.sub(r"Sorry, we couldn.t find.*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if " || " in text:
        parts = [p.strip() for p in text.split(" || ") if len(p.strip()) > 20]
        text = parts[0] if parts else text
    return text


def _words(text):
    return set(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()) - STOP


def _get_beliefs(query, limit=400):
    try:
        qw = _words(query)
        if not qw:
            return []
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            "SELECT content, confidence, topic FROM beliefs"
            " WHERE length(content) > 30 ORDER BY confidence DESC LIMIT ?",
            (limit,)
        ).fetchall()
        con.close()
        scored = []
        for content, conf, topic in rows:
            cw = _words(content)
            tw = _words(topic or "")
            overlap = len(qw & cw) + len(qw & tw) * 2
            if overlap > 0:
                scored.append((overlap, conf or 0.5, content, topic))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        return scored
    except Exception:
        return []


def _get_opinion(query):
    try:
        qw = _words(query)
        op_file = Path("~/.config/nex/nex_opinions.json").expanduser()
        if not op_file.exists():
            return None
        data = json.loads(op_file.read_text())
        ops = data if isinstance(data, list) else []
        best, best_n = None, 0
        for op in ops:
            if not isinstance(op, dict):
                continue
            topic = op.get("topic", "")
            opinion = op.get("opinion", "")
            if not opinion:
                continue
            n = len(qw & _words(topic))
            if n > best_n:
                best_n = n
                best = opinion
        return best if best_n >= 2 else None
    except Exception:
        return None


def _strategy(query, beliefs):
    if SOCIAL_RE.search(query.lower()):
        return "social"
    if EMPATHY_RE.search(query.lower()):
        return "empathy"
    if not beliefs:
        return "unknown"
    top_overlap, top_conf = beliefs[0][0], beliefs[0][1]
    if top_conf >= 0.7 and top_overlap >= 3:
        return "assert"
    if len(beliefs) >= 3 and top_overlap >= 2:
        confs = [b[1] for b in beliefs[:5]]
        if max(confs) - min(confs) > 0.2:
            return "pushback"
    if top_overlap >= 2:
        return "reflect"
    if top_overlap >= 1:
        return "assert"
    return "unknown"


def compose_reply(query):
    """Main LLM-free conversational reply."""
    query = (query or "").strip()
    if not query:
        return "Say something."

    beliefs = _get_beliefs(query)
    strategy = _strategy(query, beliefs)

    if strategy in ("social", "empathy", "unknown"):
        return random.choice(TEMPLATES[strategy])

    # Try opinion first
    opinion = _get_opinion(query)
    if opinion:
        cleaned = _clean(opinion)
        if len(cleaned) > 30:
            return random.choice(TEMPLATES[strategy]).format(belief=cleaned[:250])

    # Pick best clean belief
    best = None
    for overlap, conf, content, topic in beliefs[:15]:
        cleaned = _clean(content)
        if (len(cleaned) > 30 and len(cleaned) < 350
                and "bayesian belief updating" not in cleaned.lower()
                and "page contents" not in cleaned.lower()
                and "this wiki" not in cleaned.lower()):
            best = cleaned
            break

    if not best:
        return random.choice(TEMPLATES["unknown"])

    return random.choice(TEMPLATES[strategy]).format(belief=best[:250])
