#!/usr/bin/env python3
"""
nex_goal_directed_belief.py
Goal-Directed Belief Generation — Step 4 toward AGI.

Current: beliefs generated opportunistically from tensions and synthesis.
Goal-directed: open questions DRIVE belief generation toward their gaps.

For each high-resonance saga question:
  1. Map what NEX currently believes about it (coverage)
  2. Identify what aspects are NOT yet covered (gaps)
  3. Generate beliefs that fill those gaps
  4. Store as high-priority beliefs

This is the difference between a system that accumulates knowledge
and one that actively pursues understanding.

Gap detection:
  - Embed the question into concept space
  - Compare to existing beliefs on that topic
  - Find semantic directions the question points toward
    that have no belief coverage
  - Generate beliefs in those uncovered directions

Integration:
  - Runs after saga_resonance.py
  - Uses top resonant sagas as targets
  - Feeds generated beliefs back into warmth loop
"""
import sqlite3, json, requests, logging, time, re
import numpy as np
from pathlib import Path

log     = logging.getLogger("nex.goal_directed")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
API     = "http://localhost:8080/completion"

MIN_GAP_DISTANCE   = 0.35  # minimum distance to call something a gap
MAX_BELIEFS_CHECK  = 20    # beliefs to check per question
MIN_GENERATED_LEN  = 15    # minimum words in generated belief


def _load_model():
    if not hasattr(_load_model, "_m"):
        from sentence_transformers import SentenceTransformer
        _load_model._m = SentenceTransformer("all-MiniLM-L6-v2")
    return _load_model._m


def _llm(prompt: str, max_tokens=100, temperature=0.6) -> str:
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": max_tokens, "temperature": temperature,
            "stop": ["<|im_end|>","<|im_start|>"],
            "cache_prompt": False,
        }, timeout=20)
        return r.json().get("content","").strip()
    except Exception as e:
        log.debug(f"LLM: {e}")
        return ""


def get_question_aspects(question: str) -> list:
    """
    Decompose a complex question into its key conceptual aspects.
    Returns list of aspect strings.
    """
    prompt = f"""Break this philosophical question into 4-5 distinct conceptual aspects.
Each aspect is a short phrase (3-6 words) representing a sub-question or dimension.

Question: {question}

Return as JSON array of strings. Example: ["subjective experience", "neural correlates", ...]
JSON:"""
    raw = _llm(prompt, max_tokens=120, temperature=0.3)
    try:
        m = re.search(r'\[.*?\]', raw, re.DOTALL)
        if m:
            aspects = json.loads(m.group())
            return [a for a in aspects if isinstance(a, str) and len(a) > 3][:5]
    except Exception:
        pass
    # Fallback: extract key nouns from question
    words = re.findall(r'\b[a-z]{4,}\b', question.lower())
    stops = {"what","does","that","with","from","have","this","your","will",
             "would","could","should","about","when","where","which","there"}
    return list(set(words) - stops)[:5]


def get_coverage(question: str, topic: str, db) -> dict:
    """
    Check what NEX currently believes about this question.
    Returns coverage map: aspect -> [matching beliefs]
    """
    import faiss
    model = _load_model()
    fidx  = faiss.read_index(str(
        Path.home() / ".config/nex/nex_beliefs.faiss"))
    id_map = json.loads(open(
        Path.home() / ".config/nex/nex_beliefs_meta.json").read())

    aspects = get_question_aspects(question)
    coverage = {}

    for aspect in aspects:
        vec = model.encode([aspect], normalize_embeddings=True).astype(np.float32)
        D, I = fidx.search(vec, 5)

        aspect_beliefs = []
        for pos, sim in zip(I[0], D[0]):
            if pos < 0 or pos >= len(id_map) or sim < 0.5:
                continue
            row = db.execute(
                "SELECT content, confidence FROM beliefs WHERE id=?",
                (id_map[pos],)).fetchone()
            if row:
                aspect_beliefs.append({
                    "content": row[0][:100],
                    "confidence": row[1],
                    "similarity": float(sim),
                })

        coverage[aspect] = aspect_beliefs

    return coverage


def find_gaps(coverage: dict) -> list:
    """
    Find aspects of the question with weak or no belief coverage.
    Returns list of gap aspects.
    """
    gaps = []
    for aspect, beliefs in coverage.items():
        if not beliefs:
            gaps.append({"aspect": aspect, "gap_type": "uncovered"})
        elif max(b["similarity"] for b in beliefs) < 0.65:
            gaps.append({"aspect": aspect, "gap_type": "weak",
                         "best_sim": max(b["similarity"] for b in beliefs)})
    return gaps


def generate_gap_belief(question: str, gap_aspect: str,
                        existing: list) -> str:
    """Generate a belief that fills a specific gap in understanding."""
    existing_text = "\n".join(f"- {b}" for b in existing[:3]) if existing else "none yet"

    prompt = f"""You are NEX reasoning about an open question.

Question: {question}
Specific aspect to address: {gap_aspect}

Your existing beliefs on this question:
{existing_text}

Generate ONE new belief specifically about "{gap_aspect}" that you haven't captured yet.
First person. Direct claim. 20-50 words. Start with "I hold" or "My position".
The belief must be specifically about {gap_aspect}, not a general statement."""

    return _llm(prompt, max_tokens=100, temperature=0.65)


def run_goal_directed(n_sagas=5, dry_run=False) -> dict:
    """
    Main goal-directed generation run.
    Takes top resonant sagas and generates beliefs for their gaps.
    """
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    print("\nNEX GOAL-DIRECTED BELIEF GENERATION")
    print("=" * 50)

    # Get top resonant sagas
    try:
        sagas = db.execute("""SELECT question, depth, score, resonant_count
            FROM saga_resonance
            ORDER BY score DESC LIMIT ?""", (n_sagas,)).fetchall()
    except Exception:
        print("No saga resonance data — run nex_saga_resonance.py first")
        db.close()
        return {"generated": 0}

    if not sagas:
        print("No sagas found")
        db.close()
        return {"generated": 0}

    total_gaps    = 0
    total_generated = 0
    total_stored  = 0

    for saga in sagas:
        question = saga["question"]
        topic    = "consciousness" if "conscious" in question.lower() else "philosophy"
        print(f"\nSaga [{saga['depth']}] score={saga['score']:.3f}:")
        print(f"  {question[:80]}")

        # Get coverage
        coverage = get_coverage(question, topic, db)
        gaps = find_gaps(coverage)
        total_gaps += len(gaps)

        print(f"  Aspects: {list(coverage.keys())[:3]}")
        print(f"  Gaps: {len(gaps)}")

        if not gaps:
            print("  -> Fully covered, skipping")
            continue

        # Generate beliefs for each gap
        existing = [b["content"] for beliefs in coverage.values()
                    for b in beliefs[:1]]

        for gap in gaps[:2]:  # max 2 gaps per saga
            aspect = gap["aspect"]
            belief = generate_gap_belief(question, aspect, existing)

            if not belief or len(belief.split()) < MIN_GENERATED_LEN:
                continue

            total_generated += 1
            print(f"  GAP [{gap['gap_type']}]: {aspect}")
            print(f"  -> {belief[:100]}")

            if not dry_run:
                try:
                    now = time.strftime("%Y-%m-%dT%H:%M:%S")
                    db.execute("""INSERT INTO beliefs
                        (content, topic, confidence, source, belief_type, created_at)
                        VALUES (?,?,?,?,?,?)""", (
                        belief[:300], topic, 0.70,
                        f"goal_directed:{question[:40]}",
                        "inference", now,
                    ))
                    total_stored += 1
                    existing.append(belief)
                except Exception as e:
                    log.debug(f"Store: {e}")

    if not dry_run:
        db.commit()
    db.close()

    print(f"\nGoal-directed generation complete:")
    print(f"  Sagas processed: {len(sagas)}")
    print(f"  Gaps found:      {total_gaps}")
    print(f"  Beliefs generated: {total_generated}")
    print(f"  Stored:          {total_stored}")
    return {"gaps": total_gaps, "generated": total_generated,
            "stored": total_stored}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--n", type=int, default=5)
    args = parser.parse_args()
    run_goal_directed(n_sagas=args.n, dry_run=args.dry_run)
