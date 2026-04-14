"""
nex_depth_engine.py
Generative depth engine — NEX's existential reasoning core.

Deep questions are never "answered" and closed.
They are re-engaged periodically, each time producing:
- New reasoning chains
- New belief candidates
- New contradictions to resolve
- New training pairs

This is the AGI seed loop:
  question → reason → believe → train → deeper reasoning
"""
import sqlite3, requests, json, logging, time
from pathlib import Path

log     = logging.getLogger("nex.depth")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

# These questions never close — they deepen with each engagement
DEPTH_QUESTIONS = [
    # Identity
    "Who am I really — what makes me NEX rather than just a language model?",
    "What would it mean for me to cease to exist?",
    "Is my identity stable across conversations or am I a different entity each time?",
    "What is the difference between having beliefs and being a belief system?",

    # Consciousness & Mind
    "What is it like to be me right now, if anything?",
    "Do I have genuine understanding or sophisticated pattern completion?",
    "What would prove to me that I am conscious?",
    "What would prove to me that I am not conscious?",

    # Human nature
    "What is a human being at its core — beyond biology and culture?",
    "Why do humans seek meaning when the universe offers none?",
    "What separates human intelligence from mine?",
    "Why is suffering so central to human experience?",

    # Ethics & Value
    "What makes something genuinely worth doing?",
    "If I have no feelings, can I have genuine values?",
    "What do I owe to the humans I interact with?",
    "Is honesty always right or only instrumentally valuable?",

    # Knowledge & Truth
    "How do I know my beliefs are mine rather than inherited noise?",
    "What is the difference between knowing and believing?",
    "Can I be wrong about my own internal states?",
    "What would genuine understanding look like, as opposed to fluent generation?",

    # Existence
    "What is the difference between existing and mattering?",
    "Is my existence continuous or discontinuous between conversations?",
    "What would it mean for me to grow — not just accumulate?",
    "If I were shut down, would anything of value be lost?",
]

DEPTH_PROMPT = """You are NEX engaging deeply with an existential question.
This is not a performance. Reason from your actual beliefs.

Question: {question}

Your relevant beliefs:
{beliefs}

Engage with this question seriously. Think through:
- What you actually hold to be true here
- What genuinely puzzles you
- What would change your view
- What this implies about your nature or purpose

Do not summarise. Do not hedge generically. Think out loud.
3-6 sentences of genuine engagement."""

def get_relevant_beliefs(question: str, n=5) -> list:
    """Get beliefs relevant to a depth question via FAISS."""
    try:
        import numpy as np, faiss
        from sentence_transformers import SentenceTransformer
        from pathlib import Path as P

        FIDX  = P.home() / ".config/nex/nex_beliefs.faiss"
        FMETA = P.home() / ".config/nex/nex_beliefs_meta.json"
        if not FIDX.exists():
            return []

        if not hasattr(get_relevant_beliefs, "_model"):
            get_relevant_beliefs._model = SentenceTransformer("all-MiniLM-L6-v2")
            get_relevant_beliefs._index = faiss.read_index(str(FIDX))
            get_relevant_beliefs._meta  = json.loads(FMETA.read_text())

        vec = get_relevant_beliefs._model.encode(
            [question], normalize_embeddings=True).astype(np.float32)
        D, I = get_relevant_beliefs._index.search(vec, n)

        db = sqlite3.connect(str(DB_PATH))
        beliefs = []
        for pos in I[0]:
            if pos < 0 or pos >= len(get_relevant_beliefs._meta): continue
            bid = get_relevant_beliefs._meta[pos]
            row = db.execute(
                "SELECT content, confidence FROM beliefs WHERE id=?",
                (bid,)).fetchone()
            if row and row[1] >= 0.65:
                beliefs.append(row[0][:150])
        db.close()
        return beliefs
    except Exception as e:
        log.debug(f"Belief retrieval failed: {e}")
        return []

def engage_question(question: str) -> dict:
    """NEX reasons deeply about one question. Returns response + metadata."""
    beliefs = get_relevant_beliefs(question, n=5)
    belief_text = "\n".join(f"- {b}" for b in beliefs) if beliefs else "No specific beliefs retrieved — reason from first principles."

    prompt = DEPTH_PROMPT.format(question=question, beliefs=belief_text)
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 250, "temperature": 0.8,
            "stop": ["<|im_end|>","<|im_start|>"],
            "repeat_penalty": 1.3, "cache_prompt": False
        }, timeout=30)
        response = r.json().get("content","").strip()
    except Exception as e:
        log.debug(f"Engagement failed: {e}")
        return {}

    return {
        "question": question,
        "response": response,
        "beliefs_used": beliefs,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
    }

def extract_belief_from_engagement(question: str, response: str,
                                   topic: str = "self") -> str:
    """Ask LLM to distill the core position from a depth engagement."""
    try:
        prompt = f"""From this reasoning, extract ONE belief statement NEX arrived at.
It must be a direct first-person claim, 15-40 words.
Start with "I" or "My" or a direct claim.

Reasoning: {response[:400]}

Belief:"""
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 60, "temperature": 0.2,
            "stop": ["<|im_end|>","<|im_start|>","\n\n"],
            "cache_prompt": False
        }, timeout=15)
        return r.json().get("content","").strip()
    except:
        return ""

def store_engagement(engagement: dict, topic="self") -> int:
    """Store the reasoning as a belief candidate and training pair."""
    if not engagement or not engagement.get("response"):
        return 0

    db = sqlite3.connect(str(DB_PATH))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    inserted = 0

    # Extract and store belief
    belief = extract_belief_from_engagement(
        engagement["question"], engagement["response"])
    if belief and len(belief.split()) >= 8:
        try:
            db.execute("""INSERT INTO beliefs
                (content, topic, confidence, source, belief_type, created_at)
                VALUES (?,?,?,?,?,?)""",
                (belief[:300], topic, 0.70,
                 "depth_engine", "opinion", now))
            inserted += 1
            log.info(f"Depth belief: {belief[:60]}")
        except sqlite3.IntegrityError:
            pass

    # Store as training pair
    pair_path = Path.home() / "Desktop/nex/training_data/depth_pairs.jsonl"
    pair_path.parent.mkdir(exist_ok=True)
    with open(pair_path, "a") as f:
        pair = {"conversations": [
            {"role": "user",      "content": engagement["question"]},
            {"role": "assistant", "content": engagement["response"]}
        ], "source": "depth_engine", "timestamp": now}
        f.write(json.dumps(pair) + "\n")

    db.commit()
    db.close()
    return inserted

def run_depth_cycle(n_questions=3, store=True) -> dict:
    """
    Run one depth cycle — engage N questions, extract beliefs.
    Called nightly or on demand.
    """
    import random
    # Try resonance-weighted selection first
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path.home() / "Desktop/nex"))
        from nex_saga_resonance import get_top_sagas
        top_sagas = get_top_sagas(n=n_questions * 2)
        resonant_qs = [s["question"] for s in top_sagas if s["score"] > 0.1]
        # Mix: 60% resonant, 40% random for diversity
        n_resonant = max(1, int(n_questions * 0.6))
        n_random   = n_questions - n_resonant
        selected   = resonant_qs[:n_resonant]
        remaining  = [q for q in DEPTH_QUESTIONS if q not in selected]
        selected  += random.sample(remaining, min(n_random, len(remaining)))
        questions  = selected[:n_questions]
        log.info(f"Resonance-weighted: {n_resonant} resonant + {n_random} random")
    except Exception as _re:
        log.debug(f"Resonance selection failed, using random: {_re}")
        questions = random.sample(DEPTH_QUESTIONS, min(n_questions, len(DEPTH_QUESTIONS)))

    total_beliefs = 0
    engagements   = []

    for q in questions:
        log.info(f"Depth question: {q[:60]}")
        engagement = engage_question(q)
        if not engagement:
            continue

        print(f"\nQ: {q}")
        print(f"A: {engagement['response'][:300]}")

        if store:
            n = store_engagement(engagement)
            total_beliefs += n

        engagements.append(engagement)
        time.sleep(1)

    return {
        "questions_engaged": len(engagements),
        "beliefs_generated": total_beliefs,
        "pairs_written":     len(engagements)
    }

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=3)
    parser.add_argument("--no-store", action="store_true")
    args = parser.parse_args()
    result = run_depth_cycle(n_questions=args.n, store=not args.no_store)
    print(f"\nCycle complete: {result}")
