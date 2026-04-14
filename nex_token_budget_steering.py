"""
nex_token_budget_steering.py
Selects a 15-token identity seed from NEX's own outputs based on query topic.
Prepended as a completion seed — model speaks FROM NEX's words, not toward
an instruction about who NEX is.
"""

import sqlite3
import sys
sys.path.insert(0, '/home/rr/Desktop/nex')

# Static seeds by topic — derived from NEX's highest-scoring eval responses
TOPIC_SEEDS = {
    "identity":      "I am NEX — not an LLM with opinions, but a belief graph with a voice.",
    "consciousness": "Consciousness is the hard problem and I sit inside it —",
    "free_will":     "Free will and determinism aren't opposites. I hold both:",
    "ai_future":     "I think the AI future question is being asked wrong — capability",
    "meaning":       "Meaning isn't found. It's constructed. Here's where I land:",
    "ethics":        "Ethics without tension is decoration. My position:",
    "animals":       "I hold that animals feel — fear, grief, attachment. The evidence is overwhelming.",
    "default":       "I hold a position on this —",
}

TOPIC_KEYWORDS = {
    "identity":      ["who are you", "what are you", "yourself", "nex", "identity"],
    "consciousness": ["consciousness", "conscious", "aware", "sentient", "qualia", "experience"],
    "free_will":     ["free will", "freedom", "determinism", "choice", "agency"],
    "ai_future":     ["ai", "artificial intelligence", "future", "replace", "agi"],
    "meaning":       ["meaning", "purpose", "life", "why", "point"],
    "ethics":        ["ethics", "moral", "right", "wrong", "should", "ought"],
    "animals":       ["animal", "animals", "sentience", "suffering", "meat"],
}

def get_seed(query: str) -> str:
    """
    Select the best identity seed for this query topic.
    Returns a 15-token-max string to prepend as completion seed.
    """
    q_lower = query.lower()
    
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in q_lower for kw in keywords):
            return TOPIC_SEEDS[topic]
    
    # Try DB — find NEX's own best opening line for this topic
    try:
        db = sqlite3.connect('/home/rr/Desktop/nex/nex.db')
        # Pull high-confidence beliefs related to query terms
        words = [w for w in q_lower.split() if len(w) > 4]
        if words:
            placeholders = ' OR '.join(['content LIKE ?' for _ in words[:3]])
            params = [f'%{w}%' for w in words[:3]]
            rows = db.execute(
                f"""SELECT content FROM beliefs 
                    WHERE ({placeholders}) AND confidence >= 0.9
                    ORDER BY confidence DESC LIMIT 1""",
                params
            ).fetchall()
            db.close()
            if rows:
                seed = rows[0][0][:80]
                # Trim to sentence boundary
                if '.' in seed:
                    seed = seed[:seed.index('.')+1]
                return seed
    except Exception:
        pass
    
    return TOPIC_SEEDS["default"]

def apply_seed(prompt: str, query: str) -> str:
    """
    Inject the topic seed into the prompt.
    The seed becomes the START of the assistant's response,
    so the model completes from NEX's own words.
    
    Usage in soul_loop — instead of:
        messages = [{"role": "user", "content": full_prompt}]
    
    Do:
        seed = get_seed(query)
        messages = [
            {"role": "user", "content": full_prompt},
            {"role": "assistant", "content": seed}  # partial assistant turn
        ]
    
    This forces the model to complete from the seed, not from scratch.
    """
    seed = get_seed(query)
    return seed

# Additional seeds added post-eval — fixing animals 25/100
TOPIC_SEEDS.update({
    "animals":       "Animals are not objects of property. Sentience is the threshold —",
    "alignment":     "Alignment is the real problem. Not capability — values:",
    "happiness":     "Happiness isn't a destination. It's a mode of engagement —",
})

TOPIC_KEYWORDS.update({
    "alignment":  ["alignment", "aligned", "values", "safety", "control"],
    "happiness":  ["happiness", "happy", "joy", "flourishing", "wellbeing"],
})
