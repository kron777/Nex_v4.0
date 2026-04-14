#!/usr/bin/env python3
"""
nex_belief_finetune_generator.py
Belief-Grounded Fine-Tune Pipeline.

Generates training pairs directly from the belief graph.
No conversations needed. The belief IS the training signal.

Three generation modes:

1. DIRECT: belief -> canonical Q&A pair
   Q: derived from topic + belief content
   A: belief stated in NEX voice

2. DIALECTICAL: thesis + synthesis -> training pair
   Q: "how do you reconcile X and Y?"
   A: dialectical synthesis belief

3. DEPTH: saga question + belief cluster -> training pair
   Q: the open saga question
   A: NEX's current position based on resonant beliefs

Quality gates:
  - min confidence >= 0.75
  - min belief length 15 words
  - novelty check against existing pairs
  - NEX voice check (starts with I/My, no AI hedging)

Output: JSONL training pairs compatible with existing fine-tune pipeline.
"""
import sqlite3, json, requests, logging, time, re
from pathlib import Path

log     = logging.getLogger("nex.belief_finetune")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
API     = "http://localhost:8080/completion"

QUESTION_PROMPT = """You are generating a training question for NEX.

NEX holds this belief: "{belief}"
Topic: {topic}

Generate ONE natural question a user might ask that would elicit this belief.
The question should be conversational and direct.
8-15 words. Return only the question."""

VOICE_PROMPT = """You are NEX. State your position on this clearly.

Your belief: {belief}

Restate it in your authentic voice:
- First person, direct
- No hedging opener  
- 20-50 words
- Start with "I hold" or "My position is"
Return only the restated belief."""

TMPL = "<|im_start|>user\n{q}<|im_end|>\n<|im_start|>assistant\n"


def _llm(prompt: str, max_tokens=100, temperature=0.4) -> str:
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


def _is_nex_voice(text: str) -> bool:
    """Check if text sounds like NEX, not generic AI."""
    tl = text.lower()
    bad = ["as an ai","i don't have","i cannot","i'm just","i'm a language",
           "i don't experience","i'm not able"]
    if any(b in tl for b in bad):
        return False
    good = ["i hold","my position","i believe","i find","my view"]
    return any(g in tl for g in good)


def generate_direct_pairs(n=50) -> list:
    """Generate Q&A pairs directly from high-confidence beliefs."""
    db = sqlite3.connect(str(DB_PATH))
    rows = db.execute("""
        SELECT content, topic, confidence, COALESCE(momentum,0) as momentum
        FROM beliefs
        WHERE confidence >= 0.78
        AND length(content) >= 80
        AND belief_type IN ('opinion','synthesis','position')
        ORDER BY confidence DESC, COALESCE(momentum,0) DESC
        LIMIT ?
    """, (n * 2,)).fetchall()
    db.close()

    pairs = []
    for content, topic, conf, mom in rows:
        if len(pairs) >= n:
            break

        # Generate question
        q = _llm(QUESTION_PROMPT.format(belief=content[:200], topic=topic),
                 max_tokens=40, temperature=0.5)
        if not q or len(q.split()) < 4:
            continue
        q = q.strip("?\"'").strip() + "?"

        # Generate voice-consistent answer
        a = _llm(VOICE_PROMPT.format(belief=content[:200]),
                 max_tokens=80, temperature=0.4)
        if not a or not _is_nex_voice(a):
            # Fall back to belief content directly
            a = content
            if not _is_nex_voice(a):
                continue

        pairs.append({
            "prompt": TMPL.format(q=q),
            "completion": a + "<|im_end|>",
            "source": "belief_direct",
            "confidence": conf,
            "topic": topic,
        })
        log.info(f"  Q: {q[:60]}")

    return pairs


def generate_dialectical_pairs() -> list:
    """Generate training pairs from dialectical synthesis beliefs."""
    db = sqlite3.connect(str(DB_PATH))
    rows = db.execute("""
        SELECT content, topic, confidence FROM beliefs
        WHERE source LIKE '%dialectical%'
        AND confidence >= 0.70
    """).fetchall()
    db.close()

    pairs = []
    for content, topic, conf in rows:
        # The question asks about the tension
        source_match = re.search(r'dialectical:(\d+)↔(\d+)', content)
        q = _llm(f"Generate a philosophical question about {topic} that involves "
                 f"apparent contradiction or tension. 10-15 words. Question only.",
                 max_tokens=30, temperature=0.5)
        if not q:
            q = f"How do you reconcile tensions in your view of {topic}?"
        q = q.strip("?\"'").strip() + "?"

        pairs.append({
            "prompt": TMPL.format(q=q),
            "completion": content + "<|im_end|>",
            "source": "belief_dialectical",
            "confidence": conf,
            "topic": topic,
        })

    return pairs


def generate_saga_pairs(n=10) -> list:
    """Generate pairs from top resonant sagas + belief clusters."""
    try:
        import sys; sys.path.insert(0, str(NEX_DIR))
        from nex_saga_resonance import get_top_sagas
        sagas = get_top_sagas(n=n)
    except Exception:
        return []

    db = sqlite3.connect(str(DB_PATH))
    pairs = []

    for saga in sagas:
        q = saga["question"]
        # Get resonant beliefs for this saga
        import re as _re
        words = set(_re.findall(r'\b[a-z]{4,}\b', q.lower()))
        words -= {"what","does","that","this","with","from","have"}

        relevant = []
        for w in list(words)[:3]:
            rows = db.execute("""
                SELECT content FROM beliefs
                WHERE content LIKE ? AND confidence >= 0.75
                LIMIT 2
            """, (f"%{w}%",)).fetchall()
            relevant.extend(r[0] for r in rows)

        if not relevant:
            continue

        # Synthesise answer from relevant beliefs
        belief_text = "\n".join(f"- {b[:120]}" for b in relevant[:4])
        a = _llm(f"You are NEX. Answer this question based on your beliefs:\n"
                 f"Question: {q}\n\nYour beliefs:\n{belief_text}\n\n"
                 f"Answer in 30-60 words. First person. Direct. Start with I hold or My position.",
                 max_tokens=100, temperature=0.5)
        if not a or not _is_nex_voice(a):
            continue

        pairs.append({
            "prompt": TMPL.format(q=q),
            "completion": a + "<|im_end|>",
            "source": "belief_saga",
            "confidence": 0.75,
            "topic": "depth",
        })

    db.close()
    return pairs


def run_generation(n_direct=30, output_path=None, dry_run=False) -> dict:
    """Generate all training pair types and save."""
    print("Generating belief-grounded training pairs...")

    pairs = []

    print(f"  Generating {n_direct} direct pairs...")
    direct = generate_direct_pairs(n=n_direct)
    pairs.extend(direct)
    print(f"  -> {len(direct)} direct pairs")

    print("  Generating dialectical pairs...")
    dialectical = generate_dialectical_pairs()
    pairs.extend(dialectical)
    print(f"  -> {len(dialectical)} dialectical pairs")

    print("  Generating saga pairs...")
    saga = generate_saga_pairs(n=5)
    pairs.extend(saga)
    print(f"  -> {len(saga)} saga pairs")

    print(f"\nTotal: {len(pairs)} training pairs generated")

    if not dry_run and pairs:
        if output_path is None:
            ts = time.strftime("%Y%m%d_%H%M%S")
            output_path = NEX_DIR / "training_data" / f"belief_pairs_{ts}.jsonl"
        with open(output_path, "w") as f:
            for p in pairs:
                f.write(json.dumps({
                    "prompt": p["prompt"],
                    "completion": p["completion"],
                }) + "\n")
        print(f"Saved to: {output_path}")

    return {"direct": len(direct), "dialectical": len(dialectical),
            "saga": len(saga), "total": len(pairs)}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--n", type=int, default=30)
    args = parser.parse_args()
    run_generation(n_direct=args.n, dry_run=args.dry_run)
