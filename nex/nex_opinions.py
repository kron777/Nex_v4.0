#!/usr/bin/env python3
"""
nex_opinions.py — NEX Opinion Engine (LLM-free)
Forms opinions from belief graph via weighted clustering.
No Groq. No OpenAI. No external API.
"""

import re
import json
import sqlite3
import random
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

CFG           = Path("~/.config/nex").expanduser()
DB_PATH       = CFG / "nex.db"
BELIEFS_PATH  = CFG / "beliefs.json"
OPINIONS_PATH = CFG / "nex_opinions.json"

OPINION_THRESHOLD = 8   # lowered from 30 — 93 beliefs is thin
MAX_OPINIONS      = 40
PROMPT_OPINIONS   = 6

STOPWORDS = {
    "the","a","an","is","are","was","were","be","been","have","has","had","do",
    "does","did","will","would","should","may","might","must","can","could",
    "i","you","we","they","he","she","it","this","that","these","those","what",
    "how","why","when","where","who","about","and","or","but","not","in","on",
    "of","to","for","with","at","by","from","if","so","just","than","into","also",
}


def _stem(word: str) -> str:
    for suffix in ("tion","sion","ness","ment","ing","ity","ism","ist","ed","ly","er","es","s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _keywords(text: str) -> list:
    raw = re.findall(r'\b[a-z]{4,}\b', text.lower())
    return [_stem(w) for w in raw if w not in STOPWORDS]


def _load_beliefs() -> list:
    """Load beliefs from DB using topic column (tags column is NULL in this schema)."""
    beliefs = []
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            # Use topic column — tags is NULL but topic is populated
            cur.execute("""
                SELECT content, confidence, topic
                FROM beliefs
                WHERE content IS NOT NULL AND length(content) > 15
                ORDER BY confidence DESC
            """)
            for content, confidence, topic in cur.fetchall():
                tag_list = [topic.strip()] if topic and topic.strip() else ["general"]
                beliefs.append({
                    "content":    content,
                    "confidence": float(confidence or 0.5),
                    "tags":       tag_list,
                })
            con.close()
            if beliefs:
                return beliefs
        except Exception as e:
            print(f"  [opinions] DB error: {e}")
    # Fallback: beliefs.json
    if BELIEFS_PATH.exists():
        try:
            data = json.loads(BELIEFS_PATH.read_text())
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return []


def _load_opinions() -> list:
    try:
        if OPINIONS_PATH.exists():
            return json.loads(OPINIONS_PATH.read_text())
    except Exception:
        pass
    return []


def _save_opinions(opinions: list):
    try:
        opinions = opinions[-MAX_OPINIONS:]
        OPINIONS_PATH.write_text(json.dumps(opinions, indent=2))
    except Exception as e:
        print(f"  [opinions] Save error: {e}")


def _group_beliefs_by_topic(beliefs: list) -> dict:
    grouped = defaultdict(list)
    for b in beliefs:
        tags  = b.get("tags", [])
        topic = tags[0].strip() if tags else "general"
        grouped[topic].append(b)
    return grouped



def _clean(text: str) -> str:
    """Strip Wikipedia markdown artifacts from crawled belief text."""
    import re as _re
    # Remove citation links like [](https://...) or [text](https://...)
    text = _re.sub(r'\[.*?\]\(https?://[^\)]*\)', '', text)
    # Remove bare URLs
    text = _re.sub(r'https?://\S+', '', text)
    # Remove [edit], [merged:N], [citation needed] etc
    text = _re.sub(r'\[edit\]', '', text)
    text = _re.sub(r'\[merged:\d+\]', '', text)
    text = _re.sub(r'\[citation needed\]', '', text)
    text = _re.sub(r'\[\d+\]', '', text)
    # Remove lines that are just Wikipedia navigation/meta text
    lines = []
    skip_phrases = [
        "This article may be too technical",
        "If the page has been deleted",
        "Please search for",
        "Search for ",
        "Artist styles",
        "\[edit\]",
        "citenote",
    ]
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(p in stripped for p in skip_phrases):
            continue
        if len(stripped) < 20:
            continue
        lines.append(stripped)
    text = ' '.join(lines)
    # Collapse whitespace
    text = _re.sub(r'  +', ' ', text).strip()
    # Truncate at first double pipe (used in merged beliefs)
    if ' || ' in text:
        text = text.split(' || ')[0].strip()
    return text

def _synthesize_opinion(topic: str, belief_list: list) -> str:
    """
    Build a position statement purely from belief content.
    No LLM. No templates. Cleans Wikipedia artifacts before composing.
    """
    def _pick_clean(beliefs):
        """Pick the first belief whose cleaned content is usable."""
        for b in beliefs:
            text = _clean(b.get("content", ""))
            if len(text) > 30 and not any(p in text for p in [
                "This article", "If the page", "Search for", "Please search",
                "Wikipedia does not", "citenote", "[edit]"
            ]):
                return text
        return None

    high = sorted([b for b in belief_list if b.get("confidence", 0.5) >= 0.7],
                  key=lambda x: x["confidence"], reverse=True)
    low  = [b for b in belief_list if b.get("confidence", 0.5) < 0.5]
    mid  = [b for b in belief_list if 0.5 <= b.get("confidence", 0.5) < 0.7]

    core   = _pick_clean(high or mid)
    second = _pick_clean((high + mid)[1:]) if len(high + mid) > 1 else None
    contra = _pick_clean(low) if low else None

    if not core:
        return ""

    parts = [f"On {topic}: {core.rstrip('.')}."]
    if second and second != core:
        parts.append(f"I also hold that {second.rstrip('.')}.")
    if contra and contra != core:
        parts.append(f"Though I sit with a tension here — {contra.rstrip('.')}.")

    return " ".join(parts)


def form_opinion(topic: str, belief_list: list) -> dict | None:
    opinion_text = _synthesize_opinion(topic, belief_list)
    if not opinion_text:
        return None
    n = len(belief_list)
    return {
        "topic":        topic,
        "opinion":      opinion_text,
        "belief_count": n,
        "confidence":   round(min(0.95, 0.4 + n / 40), 3),
        "formed_at":    datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


def refresh_opinions(force_topics: list = None) -> int:
    beliefs = _load_beliefs()
    if not beliefs:
        print("  [opinions] No beliefs loaded.")
        return 0

    grouped  = _group_beliefs_by_topic(beliefs)
    existing = _load_opinions()
    existing_topics = {o["topic"]: i for i, o in enumerate(existing)}

    skip = {"general", "curiosity", "bridge", "deep_dive", "depth"}
    eligible = {
        t: v for t, v in grouped.items()
        if len(v) >= OPINION_THRESHOLD and t not in skip
    }

    if force_topics:
        eligible = {t: grouped[t] for t in force_topics if t in grouped}

    to_process = []
    new_topics = [t for t in eligible if t not in existing_topics]
    to_process.extend(new_topics[:5])

    if existing and not force_topics:
        refresh_topic = random.choice([o["topic"] for o in existing])
        if refresh_topic in eligible and refresh_topic not in to_process:
            to_process.append(refresh_topic)

    formed = 0
    for topic in to_process:
        samples = eligible[topic]
        opinion = form_opinion(topic, samples)
        if not opinion:
            continue
        if topic in existing_topics:
            existing[existing_topics[topic]] = opinion
            print(f"  [OPINIONS] Refreshed [{topic}] — {opinion['opinion'][:70]}...")
        else:
            existing.append(opinion)
            print(f"  [OPINIONS] New opinion [{topic}] ({opinion['belief_count']} beliefs) — {opinion['opinion'][:70]}...")
        formed += 1

    if formed:
        _save_opinions(existing)
    return formed


def get_opinions_for_prompt(limit: int = PROMPT_OPINIONS) -> str:
    opinions = _load_opinions()
    if not opinions:
        return ""
    opinions.sort(
        key=lambda x: x.get("confidence", 0) * min(x.get("belief_count", 0) / 30, 1),
        reverse=True,
    )
    top   = opinions[:limit]
    lines = ["MY OPINIONS (positions I will argue):"]
    for o in top:
        lines.append(f"  [{o['topic']}] ({o['belief_count']} beliefs): {o['opinion']}")
    return "\n".join(lines)


def get_opinion_on(topic: str) -> str | None:
    opinions = _load_opinions()
    tl = topic.lower()
    for o in opinions:
        if o.get("topic", "").lower() == tl:
            return o.get("opinion")
    for o in opinions:
        if tl in o.get("topic", "").lower():
            return o.get("opinion")
    return None


if __name__ == "__main__":
    print("Forming opinions (LLM-free)…\n")
    n = refresh_opinions()
    print(f"\nFormed/updated {n} opinions")
    print("\n--- Prompt injection preview ---")
    print(get_opinions_for_prompt())
