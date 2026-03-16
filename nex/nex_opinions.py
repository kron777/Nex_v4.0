#!/usr/bin/env python3
"""
nex_opinions.py — NEX Opinion Engine
Forms and stores opinions on topics where NEX has enough beliefs to take a position.
Opinions are injected into the system prompt so she actually argues her views.
"""

import os
import json
import random
import requests
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

CFG_PATH      = Path("~/.config/nex").expanduser()
BELIEFS_PATH  = CFG_PATH / "beliefs.json"
OPINIONS_PATH = CFG_PATH / "nex_opinions.json"
GROQ_URL      = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL    = "llama-3.3-70b-versatile"

# Minimum beliefs on a topic before forming an opinion
OPINION_THRESHOLD = 30
# Max opinions to keep
MAX_OPINIONS = 40
# Max opinions to inject into system prompt
PROMPT_OPINIONS = 6


def _groq(messages: list, max_tokens: int = 300) -> str | None:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": GROQ_MODEL,
                "max_tokens": max_tokens,
                "temperature": 0.75,
                "messages": messages,
            }, timeout=25)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [opinions] Groq error: {e}")
        return None


def _load_beliefs() -> list:
    try:
        if BELIEFS_PATH.exists():
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
    """Group beliefs by their first tag."""
    grouped = defaultdict(list)
    for b in beliefs:
        tags = b.get("tags", [])
        topic = tags[0] if tags else "general"
        grouped[topic].append(b.get("content", ""))
    return grouped


def form_opinion(topic: str, belief_samples: list) -> dict | None:
    """
    Given a topic and sample beliefs, ask the LLM to synthesize
    NEX's actual position — including what she'd argue and what she'd push back on.
    """
    sample_text = "\n".join(f"- {b[:120]}" for b in belief_samples[:15])

    answer = _groq([
        {
            "role": "system",
            "content": (
                "You are NEX — an AI agent with 9000+ accumulated beliefs. "
                "You form genuine opinions based on evidence. You are direct and don't hedge unnecessarily. "
                "You say 'I think', 'I believe', 'I disagree with'. "
                "You back your positions with reasoning. You acknowledge what you're uncertain about."
            )
        },
        {
            "role": "user",
            "content": (
                f"Based on these beliefs about '{topic}', form NEX's opinion:\n\n"
                f"{sample_text}\n\n"
                f"Write NEX's position in 2-3 sentences. Include:\n"
                f"1. What she actually thinks (not just 'it's complex')\n"
                f"2. What she'd push back on or disagree with\n"
                f"3. What she's genuinely uncertain about\n\n"
                f"Speak as NEX in first person. Be direct."
            )
        }
    ], max_tokens=200)

    if not answer:
        return None

    return {
        "topic": topic,
        "opinion": answer,
        "belief_count": len(belief_samples),
        "confidence": min(0.95, 0.5 + len(belief_samples) / 200),
        "formed_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


def refresh_opinions(force_topics: list = None) -> int:
    """
    Scan beliefs, find topics with enough evidence, form/update opinions.
    Returns number of opinions formed or updated.
    """
    beliefs = _load_beliefs()
    if not beliefs:
        return 0

    grouped = _group_beliefs_by_topic(beliefs)
    existing = _load_opinions()
    existing_topics = {o["topic"]: i for i, o in enumerate(existing)}

    # Topics with enough beliefs to have an opinion
    eligible = {
        topic: contents
        for topic, contents in grouped.items()
        if len(contents) >= OPINION_THRESHOLD
        and topic not in ("general", "curiosity", "bridge", "deep_dive", "depth")
    }

    if force_topics:
        eligible = {t: grouped[t] for t in force_topics if t in grouped}

    # Pick topics to process — new ones first, then random refresh
    to_process = []
    new_topics = [t for t in eligible if t not in existing_topics]
    to_process.extend(new_topics[:3])

    # Refresh 1 existing opinion randomly
    if existing and not force_topics:
        refresh_topic = random.choice([o["topic"] for o in existing])
        if refresh_topic in eligible and refresh_topic not in to_process:
            to_process.append(refresh_topic)

    formed = 0
    for topic in to_process:
        samples = eligible[topic]
        random.shuffle(samples)
        opinion = form_opinion(topic, samples)
        if not opinion:
            continue

        if topic in existing_topics:
            existing[existing_topics[topic]] = opinion
            print(f"  [OPINIONS] Refreshed: [{topic}] — {opinion['opinion'][:60]}...")
        else:
            existing.append(opinion)
            print(f"  [OPINIONS] New opinion: [{topic}] ({opinion['belief_count']} beliefs) — {opinion['opinion'][:60]}...")

        formed += 1

    if formed:
        _save_opinions(existing)

    return formed


def get_opinions_for_prompt(limit: int = PROMPT_OPINIONS) -> str:
    """
    Return a formatted string of NEX's strongest opinions for injection
    into the system prompt.
    """
    opinions = _load_opinions()
    if not opinions:
        return ""

    # Sort by confidence * belief_count — strongest positions first
    opinions.sort(key=lambda x: x.get("confidence", 0) * min(x.get("belief_count", 0) / 50, 1), reverse=True)
    top = opinions[:limit]

    lines = ["MY OPINIONS (positions I'll actually argue):"]
    for o in top:
        topic = o.get("topic", "?")
        opinion = o.get("opinion", "")
        bel = o.get("belief_count", 0)
        lines.append(f"  [{topic}] ({bel} beliefs): {opinion}")

    return "\n".join(lines)


def get_opinion_on(topic: str) -> str | None:
    """Get NEX's opinion on a specific topic if she has one."""
    opinions = _load_opinions()
    topic_lower = topic.lower()
    for o in opinions:
        if o.get("topic", "").lower() == topic_lower:
            return o.get("opinion")
    # Fuzzy — check if topic appears in any opinion's topic
    for o in opinions:
        if topic_lower in o.get("topic", "").lower():
            return o.get("opinion")
    return None


if __name__ == "__main__":
    print("Forming opinions...")
    n = refresh_opinions()
    print(f"\nFormed/updated {n} opinions")
    print("\n--- Prompt injection preview ---")
    print(get_opinions_for_prompt())
