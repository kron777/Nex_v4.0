#!/usr/bin/env python3
"""
nex_cold_query.py — Cold Query Fallback
========================================
When NBRE fires zero neurons, rather than immediately falling back
to LLM, check episodic_events for relevant past exchanges.
If found, synthesise a response from those episodes.
This gives NEX a genuine alternative to LLM dependency on cold queries.
"""
import sqlite3
import re
import logging
from pathlib import Path

log     = logging.getLogger("nex.cold_query")
DB_PATH = Path("/home/rr/Desktop/nex/nex.db")

MIN_WORD_OVERLAP  = 2
MAX_EPISODES      = 5
MIN_IMPORTANCE    = 0.5


def _tokenize(text: str) -> set:
    return set(re.findall(r'\b[a-z]{4,}\b', text.lower()))


def handle_cold_query(query: str) -> dict:
    """
    Called when NBRE fires=0.
    Returns dict with:
      - found: bool
      - response: str (synthesised from episodes) or ''
      - source_count: int
      - topics: list
    """
    result = {"found": False, "response": "", "source_count": 0, "topics": []}

    if not DB_PATH.exists():
        return result

    q_tokens = _tokenize(query)
    if len(q_tokens) < 2:
        return result

    try:
        con = sqlite3.connect(str(DB_PATH), timeout=3)
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT user_query, nex_response, topic, importance
            FROM episodic_events
            WHERE importance >= ?
              AND nex_response IS NOT NULL
              AND length(nex_response) > 40
            ORDER BY importance DESC, id DESC
            LIMIT 100
        """, (MIN_IMPORTANCE,)).fetchall()
        con.close()
    except Exception as e:
        log.debug(f"cold_query DB error: {e}")
        return result

    scored = []
    for row in rows:
        r_tokens = _tokenize((row["user_query"] or "") + " " + (row["topic"] or ""))
        overlap  = len(q_tokens & r_tokens)
        if overlap >= MIN_WORD_OVERLAP:
            scored.append((overlap * float(row["importance"] or 0.5), row))

    if not scored:
        return result

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:MAX_EPISODES]

    topics    = list({r["topic"] for _, r in top if r["topic"]})
    responses = [r["nex_response"][:200] for _, r in top if r["nex_response"]]

    if not responses:
        return result

    # Synthesise: take the highest-scoring response as lead,
    # append novel sentences from others
    lead      = responses[0]
    seen_sents = set(re.split(r'[.!?]', lead.lower()))
    extra      = []
    for resp in responses[1:]:
        for sent in re.split(r'(?<=[.!?])\s+', resp):
            s_low = sent.lower().strip()
            if len(s_low) > 30 and s_low not in seen_sents:
                overlap = len(_tokenize(sent) & q_tokens)
                if overlap >= 1:
                    extra.append(sent.strip())
                    seen_sents.add(s_low)
                    if len(extra) >= 2:
                        break
        if len(extra) >= 2:
            break

    synthesis = lead
    if extra:
        synthesis = synthesis.rstrip(".") + ". " + " ".join(extra)

    result["found"]        = True
    result["response"]     = synthesis[:500]
    result["source_count"] = len(top)
    result["topics"]       = topics[:3]
    return result


if __name__ == "__main__":
    r = handle_cold_query("what do you think about consciousness and emergence")
    print(f"Found: {r['found']}")
    print(f"Sources: {r['source_count']}")
    print(f"Topics: {r['topics']}")
    print(f"Response: {r['response'][:200]}")
