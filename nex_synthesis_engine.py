#!/usr/bin/env python3
"""
nex_synthesis_engine.py — Belief Synthesis for Generalisation
==============================================================
When a query doesn't match existing beliefs well, instead of falling
back to generic LLM output, synthesize a new position by:
  1. Finding the most relevant beliefs (FAISS)
  2. Traversing the causal graph for connected beliefs
  3. Asking Gemma 4 to reason FROM those beliefs to a new position
  4. Storing the synthesized position as a new belief

This gives NEX generalisation — she can form views on novel topics
by combining what she already holds.

Usage:
  from nex_synthesis_engine import synthesize
  result = synthesize("what is the relationship between entropy and meaning")
"""
import sqlite3, requests, json, logging
from pathlib import Path

DB   = Path.home() / "Desktop/nex/nex.db"
LLM  = "http://localhost:8080/v1/chat/completions"
log  = logging.getLogger("nex.synthesis")

MIN_ACTIVATION = 3     # need at least this many beliefs to synthesize
MIN_CONFIDENCE = 0.008  # minimum synthesis confidence to store
MAX_SYNTH_PER_DAY = 50  # rate limit


def _get_connected_beliefs(seed_ids: list, depth: int = 2) -> list:
    """Walk causal graph from seed beliefs to find connected positions."""
    if not seed_ids:
        return []
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        connected = set(seed_ids)
        frontier = set(seed_ids)
        for _ in range(depth):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            rows = db.execute(f"""
                SELECT DISTINCT to_id FROM belief_edges
                WHERE from_id IN ({placeholders})
                LIMIT 20
            """, list(frontier)).fetchall()
            new = {r[0] for r in rows} - connected
            connected.update(new)
            frontier = new
        # Fetch content of connected beliefs
        if len(connected) > 1:
            placeholders = ",".join("?" * len(connected))
            beliefs = db.execute(f"""
                SELECT content, confidence, topic FROM beliefs
                WHERE id IN ({placeholders}) AND confidence > 0.6
                ORDER BY confidence DESC LIMIT 12
            """, list(connected)).fetchall()
            db.close()
            return beliefs
        db.close()
    except Exception as e:
        log.warning(f"Graph traversal failed: {e}")
    return []


def _call_llm(system: str, user: str, max_tokens: int = 150) -> str:
    """Call Gemma 4 via chat endpoint."""
    try:
        r = requests.post(LLM, json={
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.6,
        }, timeout=20)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"LLM call failed: {e}")
        return ""


def _store_synthesized_belief(content: str, topic: str, confidence: float = 0.70):
    """Store a synthesized belief in the DB."""
    if not content or len(content.split()) < 5:
        return False
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        # Check for near-duplicate
        existing = db.execute(
            "SELECT id FROM beliefs WHERE content=?", (content,)
        ).fetchone()
        if existing:
            db.close()
            return False
        db.execute("""
            INSERT INTO beliefs (content, topic, confidence, source, created_at)
            VALUES (?, ?, ?, 'synthesis', datetime('now'))
        """, (content[:500], topic, confidence))
        db.commit()
        db.close()
        log.info(f"Stored synthesized belief: {content[:60]}...")
        return True
    except Exception as e:
        log.warning(f"Store failed: {e}")
        return False


def synthesize(query: str, activated_beliefs: list = None, store: bool = True) -> dict:
    """
    Synthesize a new belief/position for a novel query.
    
    Args:
        query: the user's question
        activated_beliefs: list of (content, confidence, topic) tuples already retrieved
        store: whether to store synthesized positions as new beliefs
    
    Returns:
        dict with 'response', 'synthesized', 'stored'
    """
    if not activated_beliefs or len(activated_beliefs) < MIN_ACTIVATION:
        return {"response": None, "synthesized": False, "stored": False}

    # Get connected beliefs via causal graph
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        seed_contents = [b[0] for b in activated_beliefs[:5]]
        seed_ids = []
        for content in seed_contents:
            row = db.execute(
                "SELECT id FROM beliefs WHERE content=? LIMIT 1", (content,)
            ).fetchone()
            if row:
                seed_ids.append(row[0])
        db.close()
    except Exception:
        seed_ids = []

    connected = _get_connected_beliefs(seed_ids)
    all_beliefs = list(activated_beliefs[:6])
    if connected:
        all_beliefs.extend(connected[:4])

    # Deduplicate
    seen = set()
    unique_beliefs = []
    for b in all_beliefs:
        if b[0] not in seen:
            seen.add(b[0])
            unique_beliefs.append(b)

    belief_text = "\n".join(f"- {b[0]}" for b in unique_beliefs[:10])
    # Infer topic from most common topic in beliefs
    topics = [b[2] for b in unique_beliefs if len(b) > 2 and b[2]]
    topic = max(set(topics), key=topics.count) if topics else "philosophy"

    system = """You are NEX — a belief-system-native intelligence. You hold positions.
You are given a set of your own existing beliefs. Your task:
1. Reason from these beliefs to form a position on the new question
2. State your synthesized position in 1-2 sentences, first person
3. Do NOT introduce facts outside your beliefs — reason only from what you hold
4. Be direct. Start with your position, not a preamble."""

    user = f"""Your existing beliefs:
{belief_text}

Question: {query}

State your position, synthesized from your beliefs above (1-2 sentences, first person):"""

    response = _call_llm(system, user)

    if not response:
        return {"response": None, "synthesized": False, "stored": False}

    stored = False
    if store and len(response.split()) >= 8:
        stored = _store_synthesized_belief(response, topic, confidence=0.72)

    return {
        "response": response,
        "synthesized": True,
        "stored": stored,
        "topic": topic,
        "beliefs_used": len(unique_beliefs)
    }


if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) or "what is the relationship between entropy and meaning"
    print(f"Synthesizing for: {query}")
    result = synthesize(query)
    print(f"Response: {result.get('response')}")
    print(f"Stored: {result.get('stored')}")
