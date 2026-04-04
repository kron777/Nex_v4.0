#!/usr/bin/env python3
"""
nex_belief_validator.py
Adversarial Belief Validation — D3 from roadmap.

For each high-confidence belief, generate the strongest
counter-argument. If NEX cannot address the counter-argument
with existing beliefs, confidence gets reduced.

If she can — belief earns higher confidence.

This is adversarial self-testing. NEX challenges her own
positions to see which ones hold under scrutiny.

Process:
  1. Take high-confidence belief (>= 0.80)
  2. Generate strongest counter-argument
  3. Search belief graph for response to counter-argument
  4. If response found with good similarity: SURVIVES -> +conf
  5. If no response: CHALLENGED -> -conf, flag for depth engine

Runs weekly. Feeds challenged beliefs back into goal-directed
generation to fill the gaps.
"""
import sqlite3, json, requests, re, logging, time
import numpy as np
from pathlib import Path

log     = logging.getLogger("nex.validator")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
FIDX    = Path.home() / ".config/nex/nex_beliefs.faiss"
FMETA   = Path.home() / ".config/nex/nex_beliefs_meta.json"
API     = "http://localhost:8080/completion"

SURVIVAL_THRESHOLD   = 0.55   # similarity to call counter addressed
CONFIDENCE_BOOST     = 0.04   # belief survives -> +confidence
CONFIDENCE_PENALTY   = 0.06   # belief challenged -> -confidence
MIN_BELIEF_CONF      = 0.80   # only validate high-confidence beliefs


COUNTER_PROMPT = """Generate the STRONGEST possible counter-argument to this position.
Make it as challenging as possible. Be specific, not generic.

Position: {belief}

Strongest counter-argument (2-3 sentences):"""


def _llm(prompt: str, max_tokens=120, temperature=0.6) -> str:
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


def _load_model():
    if not hasattr(_load_model, "_m"):
        from sentence_transformers import SentenceTransformer
        _load_model._m = SentenceTransformer("all-MiniLM-L6-v2")
    return _load_model._m


def find_response_in_graph(counter: str, db) -> dict:
    """
    Search belief graph for a belief that addresses the counter-argument.
    Returns best matching belief and similarity score.
    """
    import faiss
    model = _load_model()
    fidx  = faiss.read_index(str(FIDX))
    id_map = json.loads(open(FMETA).read())

    vec = model.encode([counter], normalize_embeddings=True).astype(np.float32)
    D, I = fidx.search(vec, 5)

    best_sim  = 0.0
    best_belief = ""
    for pos, sim in zip(I[0], D[0]):
        if pos < 0 or pos >= len(id_map):
            continue
        row = db.execute(
            "SELECT content FROM beliefs WHERE id=?",
            (id_map[pos],)).fetchone()
        if row and float(sim) > best_sim:
            best_sim    = float(sim)
            best_belief = row[0]

    return {"similarity": round(best_sim, 3), "belief": best_belief}


def validate_belief(belief_id: int, content: str, db) -> dict:
    """Validate a single belief against adversarial counter-argument."""

    # Generate counter-argument
    counter = _llm(COUNTER_PROMPT.format(belief=content[:200]),
                   max_tokens=120, temperature=0.7)
    if not counter or len(counter.split()) < 10:
        return {"status": "skip", "belief_id": belief_id}

    # Search for response in belief graph
    response = find_response_in_graph(counter, db)

    survived = response["similarity"] >= SURVIVAL_THRESHOLD

    return {
        "belief_id":   belief_id,
        "belief":      content[:100],
        "counter":     counter[:150],
        "response":    response["belief"][:100],
        "similarity":  response["similarity"],
        "survived":    survived,
        "status":      "survived" if survived else "challenged",
    }


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS belief_validations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        belief_id   INTEGER,
        counter     TEXT,
        response    TEXT,
        similarity  REAL,
        survived    INTEGER,
        validated_at REAL
    )""")
    db.commit()


def run_validation(n=20, dry_run=False) -> dict:
    """Validate n high-confidence beliefs adversarially."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    ensure_schema(db)

    # Get high-confidence beliefs not recently validated
    rows = db.execute("""SELECT b.id, b.content, b.confidence
        FROM beliefs b
        LEFT JOIN belief_validations v ON b.id = v.belief_id
        WHERE b.confidence >= ?
        AND b.ontology_hollow = 0
        AND (v.id IS NULL OR v.validated_at < ?)
        AND b.topic IN ('consciousness','philosophy','ethics',
                        'alignment','free_will','self','truth')
        ORDER BY b.confidence DESC, RANDOM()
        LIMIT ?""",
        (MIN_BELIEF_CONF, time.time() - 604800, n)).fetchall()

    print(f"\nNEX BELIEF VALIDATOR")
    print(f"=" * 45)
    print(f"Validating {len(rows)} beliefs...")

    survived   = 0
    challenged = 0
    skipped    = 0

    for row in rows:
        bid     = row["id"]
        content = row["content"]
        conf    = row["confidence"]

        result = validate_belief(bid, content, db)

        if result["status"] == "skip":
            skipped += 1
            continue

        status = result["status"]
        sim    = result["similarity"]

        print(f"\n  Belief: {content[:60]}")
        print(f"  Counter: {result['counter'][:80]}")
        print(f"  Response sim: {sim:.3f} -> {status.upper()}")

        if not dry_run:
            # Update confidence
            if result["survived"]:
                db.execute("""UPDATE beliefs
                    SET confidence = MIN(0.99, confidence + ?)
                    WHERE id=?""", (CONFIDENCE_BOOST, bid))
                survived += 1
            else:
                db.execute("""UPDATE beliefs
                    SET confidence = MAX(0.40, confidence - ?)
                    WHERE id=?""", (CONFIDENCE_PENALTY, bid))
                challenged += 1

            # Store validation record
            db.execute("""INSERT INTO belief_validations
                (belief_id, counter, response, similarity, survived, validated_at)
                VALUES (?,?,?,?,?,?)""", (
                bid, result["counter"][:300],
                result["response"][:300],
                sim, 1 if result["survived"] else 0,
                time.time()
            ))

        time.sleep(0.2)

    if not dry_run:
        db.commit()
    db.close()

    print(f"\nValidation complete:")
    print(f"  Survived:   {survived}")
    print(f"  Challenged: {challenged}")
    print(f"  Skipped:    {skipped}")
    return {"survived": survived, "challenged": challenged}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--n", type=int, default=10)
    args = parser.parse_args()
    run_validation(n=args.n, dry_run=args.dry_run)
