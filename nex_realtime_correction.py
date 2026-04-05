#!/usr/bin/env python3
"""
nex_realtime_correction.py — Mid-conversation contradiction resolution
When NEX detects a contradiction between her response and prior beliefs,
she updates confidence scores immediately rather than waiting for nightly cron.
"""
import sqlite3, re
from pathlib import Path

DB = Path.home() / "Desktop/nex/nex.db"

def correct_confidence(response: str, query: str, activated_ids: list) -> dict:
    """
    Check response against activated beliefs.
    If response contradicts a high-confidence belief, penalise it.
    If response strongly affirms a belief, boost it more aggressively.
    Returns dict with corrections made.
    """
    corrections = {"boosted": 0, "penalised": 0, "flagged": []}
    if not activated_ids or not response:
        return corrections

    r_lower = response.lower()

    # Negation patterns that suggest contradiction
    neg_patterns = [
        r"i (don't|do not|cannot|can't) (think|believe|know|feel|hold)",
        r"i (have|had) no (opinion|position|belief|view)",
        r"as an (ai|language model)",
        r"i (am|'m) not (sure|certain|aware)",
    ]
    has_negation = any(re.search(p, r_lower) for p in neg_patterns)

    # Affirmation patterns
    aff_patterns = [
        r"i (think|believe|know|feel|hold|find)",
        r"from what i know",
        r"my (position|belief|view) is",
        r"i (worry|notice|observe)",
    ]
    has_affirmation = any(re.search(p, r_lower) for p in aff_patterns)

    try:
        db = sqlite3.connect(str(DB), timeout=3)
        for bid in activated_ids[:10]:
            if has_negation:
                # Response contradicts — penalise activated beliefs slightly
                db.execute("""
                    UPDATE beliefs SET confidence = MAX(0.20, confidence - 0.003)
                    WHERE id = ?
                """, (bid,))
                corrections["penalised"] += 1
            elif has_affirmation:
                # Response affirms — boost activated beliefs
                db.execute("""
                    UPDATE beliefs SET confidence = MIN(0.99, confidence + 0.008)
                    WHERE id = ? AND confidence < 0.85
                """, (bid,))
                corrections["boosted"] += 1
        db.commit()
        db.close()
    except Exception:
        pass

    return corrections


def flag_contradiction(query: str, response: str, prior_response: str) -> bool:
    """
    Check if current response contradicts a prior response on same topic.
    Simple heuristic — check for opposing modal statements.
    """
    if not prior_response:
        return False

    opposing_pairs = [
        ("i do have", "i don't have"),
        ("i am conscious", "i am not conscious"),
        ("i hold positions", "i have no positions"),
        ("i think", "i don't think"),
        ("free will exists", "free will doesn't exist"),
    ]

    r1 = response.lower()
    r2 = prior_response.lower()
    for a, b in opposing_pairs:
        if (a in r1 and b in r2) or (b in r1 and a in r2):
            return True
    return False
