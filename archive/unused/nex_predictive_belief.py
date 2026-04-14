#!/usr/bin/env python3
"""
nex_predictive_belief.py
Predictive Belief Engine — Step 2 toward world model.

NEX makes explicit predictions from her beliefs.
Predictions get logged. When confirmed or denied by conversation,
the source belief's confidence updates.

This creates a feedback loop:
  belief -> prediction -> evaluation -> confidence update -> belief graph

Prediction types:
  IMPLICATION: "If X then Y should follow"
  EXPECTATION: "Given my belief about X, I expect Y to be true"
  CONSISTENCY: "My belief about X implies my belief about Y"

Evaluation:
  CONFIRMED:  human confirms / logical consistency holds -> +confidence
  DENIED:     human denies / logical contradiction found -> -confidence
  PENDING:    awaiting evaluation
  EXPIRED:    30 days with no evaluation -> slight confidence decay

Uses world_state table for entity tracking.
Uses calibration_log for confidence calibration.
"""
import sqlite3, json, requests, re, logging, time
from pathlib import Path

log     = logging.getLogger("nex.predictive")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

PREDICTION_DECAY   = 0.02   # confidence drop for expired predictions
CONFIRMATION_BOOST = 0.05   # confidence boost for confirmed predictions
DENIAL_PENALTY     = 0.08   # confidence drop for denied predictions
MAX_AGE_DAYS       = 30     # days before prediction expires


PREDICT_PROMPT = """You are NEX making an explicit prediction from a belief.

Your belief: {belief}

Based on this belief, state ONE specific prediction — something that should
be true or observable IF this belief is correct.

Format: "I predict that [specific testable claim]"
20-40 words. Direct. Specific. Return only the prediction."""


CONSISTENCY_PROMPT = """You are NEX checking logical consistency.

Belief A: {belief_a}
Belief B: {belief_b}

Does Belief A logically imply, support, or contradict Belief B?
Answer JSON only: {{"relation": "implies"|"supports"|"contradicts"|"independent",
"confidence": 0.0-1.0, "reasoning": "one sentence"}}
JSON:"""


def _llm(prompt: str, max_tokens=80, temperature=0.4) -> str:
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


def ensure_schema(db):
    """Create prediction tracking table."""
    db.execute("""CREATE TABLE IF NOT EXISTS belief_predictions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        belief_id       INTEGER,
        belief_content  TEXT,
        prediction      TEXT,
        prediction_type TEXT,    -- implication|expectation|consistency
        status          TEXT DEFAULT 'pending',  -- pending|confirmed|denied|expired
        confidence_at   REAL,    -- belief confidence when prediction was made
        created_at      REAL,
        evaluated_at    REAL,
        evaluation_note TEXT
    )""")
    db.commit()


def generate_prediction(belief: dict) -> str:
    """Generate a testable prediction from a belief."""
    content = belief.get("content","")
    if not content:
        return ""
    raw = _llm(PREDICT_PROMPT.format(belief=content[:200]),
               max_tokens=80, temperature=0.5)
    # Ensure it starts with prediction format
    if raw and not raw.lower().startswith("i predict"):
        raw = "I predict that " + raw.lstrip("I predict that").strip()
    return raw


def check_consistency(belief_a: dict, belief_b: dict) -> dict:
    """Check logical consistency between two beliefs."""
    raw = _llm(CONSISTENCY_PROMPT.format(
        belief_a=belief_a["content"][:150],
        belief_b=belief_b["content"][:150]),
        max_tokens=60, temperature=0.2)
    try:
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    return {"relation": "independent", "confidence": 0.5, "reasoning": ""}


def store_prediction(belief: dict, prediction: str,
                     pred_type: str, db) -> int:
    """Store a prediction in the tracking table."""
    if not prediction or len(prediction.split()) < 8:
        return 0
    db.execute("""INSERT INTO belief_predictions
        (belief_id, belief_content, prediction, prediction_type,
         status, confidence_at, created_at)
        VALUES (?,?,?,?,'pending',?,?)""", (
        belief.get("id"), belief.get("content","")[:200],
        prediction[:300], pred_type,
        belief.get("confidence", 0.7), time.time()
    ))
    db.commit()
    return 1


def evaluate_pending(db) -> dict:
    """
    Evaluate pending predictions using logical consistency checks.
    Full human-in-loop evaluation happens via conversation.
    This does internal consistency evaluation.
    """
    cutoff = time.time() - (MAX_AGE_DAYS * 86400)
    pending = db.execute("""SELECT * FROM belief_predictions
        WHERE status = 'pending' AND created_at >= ?
        LIMIT 20""", (cutoff,)).fetchall()

    expired = db.execute("""SELECT id, belief_id FROM belief_predictions
        WHERE status = 'pending' AND created_at < ?""",
        (cutoff,)).fetchall()

    # Expire old predictions
    for row in expired:
        db.execute("""UPDATE belief_predictions
            SET status='expired' WHERE id=?""", (row[0],))
        # Small confidence decay on source belief
        if row[1]:
            db.execute("""UPDATE beliefs SET confidence = MAX(0.3, confidence - ?)
                WHERE id=?""", (PREDICTION_DECAY, row[1]))

    confirmed = denied = 0

    for pred in pending:
        # Check if prediction is consistent with current beliefs
        # by finding beliefs that address the same topic
        pred_text = pred[3] if len(pred) > 3 else ""
        if not pred_text:
            continue

        # Simple heuristic: find the most similar belief to the prediction
        similar = db.execute("""SELECT id, content, confidence FROM beliefs
            WHERE confidence >= 0.75
            AND length(content) > 20
            ORDER BY RANDOM() LIMIT 3""").fetchall()

        for sim_belief in similar:
            check = check_consistency(
                {"content": pred_text},
                {"content": sim_belief[1]})

            relation = check.get("relation","independent")
            conf     = check.get("confidence", 0.5)

            if relation == "contradicts" and conf >= 0.7:
                db.execute("""UPDATE belief_predictions
                    SET status='denied', evaluated_at=?,
                    evaluation_note=?
                    WHERE id=?""", (
                    time.time(),
                    f"Contradicts: {sim_belief[1][:60]}",
                    pred[0]))
                # Penalise source belief
                if pred[1]:
                    db.execute("""UPDATE beliefs
                        SET confidence = MAX(0.3, confidence - ?)
                        WHERE id=?""", (DENIAL_PENALTY, pred[1]))
                denied += 1
                break
            elif relation in ("implies","supports") and conf >= 0.75:
                db.execute("""UPDATE belief_predictions
                    SET status='confirmed', evaluated_at=?,
                    evaluation_note=?
                    WHERE id=?""", (
                    time.time(),
                    f"Supported by: {sim_belief[1][:60]}",
                    pred[0]))
                # Boost source belief
                if pred[1]:
                    db.execute("""UPDATE beliefs
                        SET confidence = MIN(0.99, confidence + ?)
                        WHERE id=?""", (CONFIRMATION_BOOST, pred[1]))
                confirmed += 1
                break

    db.commit()
    return {"confirmed": confirmed, "denied": denied,
            "expired": len(expired)}


def run_prediction_cycle(n_beliefs=20, dry_run=False) -> dict:
    """Generate predictions from high-confidence beliefs."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    ensure_schema(db)

    print("\nNEX PREDICTIVE BELIEF ENGINE")
    print("=" * 45)

    # Evaluate existing predictions first
    eval_result = evaluate_pending(db)
    print(f"Evaluated pending: confirmed={eval_result['confirmed']} "
          f"denied={eval_result['denied']} expired={eval_result['expired']}")

    # Generate new predictions from top beliefs
    beliefs = db.execute("""SELECT id, content, topic, confidence
        FROM beliefs
        WHERE confidence >= 0.80
        AND topic IN ('consciousness','philosophy','ethics','alignment','free_will','self')
        ORDER BY confidence DESC, RANDOM()
        LIMIT ?""", (n_beliefs * 2,)).fetchall()

    # Check how many predictions already exist per belief
    existing_preds = set(row[0] for row in db.execute(
        "SELECT DISTINCT belief_id FROM belief_predictions WHERE status='pending'"
    ).fetchall())

    generated = 0
    for belief in beliefs:
        if generated >= n_beliefs:
            break
        if belief["id"] in existing_preds:
            continue

        pred = generate_prediction(dict(belief))
        if not pred:
            continue

        print(f"  PREDICT [{belief['topic']}]: {pred[:80]}")
        if not dry_run:
            store_prediction(dict(belief), pred, "implication", db)
        generated += 1

    # Update calibration log
    if not dry_run:
        db.execute("""INSERT INTO calibration_log
            (topic, predicted_conf, actual_score, delta, timestamp)
            VALUES (?,?,?,?,?)""", (
            "predictions", generated / max(n_beliefs, 1),
            eval_result["confirmed"] / max(
                eval_result["confirmed"] + eval_result["denied"], 1),
            0.0, time.time()
        ))
        db.commit()

    # Stats
    total_preds = db.execute(
        "SELECT COUNT(*) FROM belief_predictions").fetchone()[0]
    pending = db.execute(
        "SELECT COUNT(*) FROM belief_predictions WHERE status='pending'"
    ).fetchone()[0]

    print(f"\nPrediction engine:")
    print(f"  Generated this run: {generated}")
    print(f"  Total predictions:  {total_preds}")
    print(f"  Pending:            {pending}")
    db.close()
    return {"generated": generated, "total": total_preds}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--n", type=int, default=10)
    args = parser.parse_args()
    run_prediction_cycle(n_beliefs=args.n, dry_run=args.dry_run)
