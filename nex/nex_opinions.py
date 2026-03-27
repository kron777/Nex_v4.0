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
    beliefs = []
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("""
                SELECT content, confidence, tags
                FROM beliefs
                WHERE content IS NOT NULL AND length(content) > 15
                ORDER BY confidence DESC
            """)
            for content, confidence, tags in cur.fetchall():
                tag_list = []
                if tags:
                    try:
                        tag_list = json.loads(tags) if tags.startswith("[") else [t.strip() for t in tags.split(",")]
                    except Exception:
                        tag_list = [tags]
                beliefs.append({"content": content, "confidence": float(confidence or 0.5), "tags": tag_list})
            con.close()
            if beliefs:
                return beliefs
        except Exception as e:
            print(f"  [opinions] DB error: {e}")
    if BELIEFS_PATH.exists():
        try:
            data = json.loads(BELIEFS_PATH.read_text())
            return data if isinstance(data, list) else []
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


def _synthesize_opinion(topic: str, belief_list: list) -> str:
    """
    Build a position statement purely from belief content.
    No LLM. No templates. Uses highest-confidence beliefs as the core claim,
    then weaves in any contradicting signals.
    """
    high  = sorted([b for b in belief_list if b.get("confidence", 0.5) >= 0.7],
                   key=lambda x: x["confidence"], reverse=True)
    low   = [b for b in belief_list if b.get("confidence", 0.5) < 0.5]
    mid   = [b for b in belief_list if 0.5 <= b.get("confidence", 0.5) < 0.7]

    if not high and not mid:
        if belief_list:
            return belief_list[0]["content"].rstrip(".") + "."
        return ""

    core   = (high or mid)[0]["content"].rstrip(".")
    second = ((high + mid)[1]["content"].rstrip(".")) if len(high + mid) > 1 else None
    contra = low[0]["content"].rstrip(".") if low else None

    parts = [f"On {topic}: {core}."]
    if second:
        parts.append(f"I also hold that {second}.")
    if contra:
        parts.append(f"Though I sit with a tension here — {contra}.")

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
