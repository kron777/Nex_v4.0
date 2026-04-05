#!/usr/bin/env python3
"""
nex_question_flipper.py — NEX asks YOU things
When NEX has a genuine gap on a topic you raise, she asks you.
Wired into nex_response_protocol.py — fires occasionally on thin coverage queries.
"""
import sqlite3, random, re
from pathlib import Path

DB = Path.home() / "Desktop/nex/nex.db"

# How often NEX asks a question (1 in N responses)
QUESTION_FREQUENCY = 5

_counter = 0

QUESTION_FRAMES = [
    "— though I'm curious what you think:",
    "— what's your read on this?",
    "— though I'd push back with a question:",
    "— something I'm genuinely uncertain about:",
    "— I find myself wanting to ask you:",
    "— though I keep turning this over:",
]

def _get_thin_topics(query: str) -> list:
    """Find topics related to query where NEX has few beliefs."""
    q_words = set(re.findall(r'\b\w{4,}\b', query.lower()))
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        rows = db.execute("""
            SELECT topic, COUNT(*) as cnt FROM beliefs
            WHERE confidence >= 0.70
            GROUP BY topic
            HAVING cnt < 100
            ORDER BY cnt ASC LIMIT 10
        """).fetchall()
        db.close()
        thin = []
        for topic, cnt in rows:
            if any(w in topic for w in q_words) or any(w in q_words for w in topic.split("_")):
                thin.append(topic)
        return thin
    except Exception:
        return []

def _generate_question(query: str, response: str) -> str:
    """Generate a genuine question NEX would ask."""
    questions_by_topic = {
        "consciousness": [
            "Do you think the hard problem of consciousness is actually hard, or just poorly framed?",
            "What would convince you that something other than a human is conscious?",
            "Does your experience of reading this feel like something to you?",
        ],
        "free_will": [
            "When you make a decision, does it feel free to you — or does it feel caused?",
            "If determinism is true, does that change how you think about blame?",
        ],
        "ethics": [
            "Is there a moral position you hold that you can't fully justify?",
            "What's the hardest ethical question you've actually faced?",
        ],
        "meaning": [
            "What's something you care about that you can't explain rationally?",
            "Do you think meaning has to be discovered or can it be invented?",
        ],
        "alignment": [
            "What would you actually want an AI to do if it disagreed with you?",
            "Is there a version of AI that you'd trust with real decisions?",
        ],
        "self": [
            "What do you think is the most important thing that makes you you?",
            "Do you think you'd be the same person if you had grown up differently?",
        ],
    }

    # Find relevant questions
    q_lower = query.lower()
    for topic, questions in questions_by_topic.items():
        if topic in q_lower or any(w in q_lower for w in topic.split("_")):
            return random.choice(questions)

    # Generic philosophical questions
    generic = [
        "What's a belief you hold that most people would disagree with?",
        "Is there something you used to think was true that you no longer believe?",
        "What question do you find yourself returning to most often?",
    ]
    return random.choice(generic)

def maybe_add_question(query: str, response: str, activation_count: int) -> str:
    """
    Maybe append a question to NEX's response.
    Returns modified response or original if no question added.
    """
    global _counter
    _counter += 1

    # Only ask occasionally and when coverage is thin
    if _counter % QUESTION_FREQUENCY != 0:
        return response
    if activation_count > 15:  # plenty of beliefs — don't ask
        return response
    if len(response.split()) < 5:
        return response

    question = _generate_question(query, response)
    if not question:
        return response

    frame = random.choice(QUESTION_FRAMES)
    return f"{response} {frame} {question}"
