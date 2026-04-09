#!/usr/bin/env python3
"""
nex_goal_belief_linker.py — Goal-Belief Relevance Linker
=========================================================
Finds which beliefs are most relevant to each active goal.
Runs each cycle and injects top-goal-relevant beliefs into
the NBRE context so NEX actively works toward her goals.

This is the missing link between goals and cognition:
goals currently sit in a table and inject into prompts as text.
This module makes beliefs actively serve goals.
"""
import sqlite3
import re
import json
import logging
from pathlib import Path

log     = logging.getLogger("nex.goal_belief_linker")
DB_PATH = Path("/home/rr/Desktop/nex/nex.db")
MIN_CONF     = 0.60
MAX_PER_GOAL = 5


def _tokenize(text: str) -> set:
    STOP = {"the","and","for","with","from","that","this","have","not",
            "are","was","were","been","will","would","could","should"}
    return set(re.findall(r'\b[a-z]{4,}\b', text.lower())) - STOP


def link_goals_to_beliefs() -> dict:
    """
    For each active goal, find the top MIN_CONF beliefs most relevant to it.
    Returns: {goal_id: [belief_content, ...]}
    """
    if not DB_PATH.exists():
        return {}

    try:
        con = sqlite3.connect(str(DB_PATH), timeout=5)
        con.row_factory = sqlite3.Row

        goals = con.execute("""
            SELECT id, description, priority FROM goals
            WHERE status = 'active'
            ORDER BY priority DESC
        """).fetchall()

        beliefs = con.execute("""
            SELECT id, content, topic, confidence FROM beliefs
            WHERE confidence >= ? AND content IS NOT NULL
              AND length(content) > 30
            AND content NOT LIKE '%different domain%'
            AND content NOT LIKE '%none of these resolve%'
            AND content NOT LIKE '%bridge:truth%'
            ORDER BY confidence DESC LIMIT 500
        """, (MIN_CONF,)).fetchall()

        con.close()
    except Exception as e:
        log.error(f"link error: {e}")
        return {}

    result = {}
    for goal in goals:
        g_tokens = _tokenize(goal["description"])
        scored   = []
        for b in beliefs:
            b_tokens = _tokenize(b["content"])
            overlap  = len(g_tokens & b_tokens)
            if overlap >= 2:
                score = overlap * float(b["confidence"] or 0.6)
                scored.append((score, b))
        scored.sort(key=lambda x: x[0], reverse=True)
        result[goal["id"]] = {
            "goal":    goal["description"][:80],
            "beliefs": [b["content"][:150] for _, b in scored[:MAX_PER_GOAL]],
            "topics":  list({b["topic"] for _, b in scored[:MAX_PER_GOAL] if b["topic"]}),
        }
        if scored:
            log.info(f"Goal {goal['id']}: {len(scored)} relevant beliefs found")

    return result


def get_top_goal_context(n_goals: int = 2) -> str:
    """
    Return a prompt block of top goals with their most relevant beliefs.
    Injected into NEX's context so cognition actively serves goals.
    """
    links = link_goals_to_beliefs()
    if not links:
        return ""

    lines = ["GOAL-RELEVANT BELIEFS (work toward these):"]
    for goal_id, data in list(links.items())[:n_goals]:
        if not data["beliefs"]:
            continue
        lines.append(f"\nGoal: {data['goal']}")
        for b in data["beliefs"][:3]:
            lines.append(f"  • {b}")

    return "\n".join(lines) if len(lines) > 1 else ""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ctx = get_top_goal_context()
    print(ctx if ctx else "No goal-belief links found")
