#!/usr/bin/env python3
"""
nex_prediction_evaluator.py
Human-in-Loop Prediction Evaluation.

Scans conversation history for human signals that confirm or deny
NEX's pending predictions.

Confirmation signals: "yes", "that's right", "correct", "exactly",
  "i agree", "true", "you're right", "good point"

Denial signals: "no", "wrong", "that's not right", "incorrect",
  "i disagree", "false", "you're wrong", "not true", "actually"

Matching: embed pending predictions + recent user turns,
find closest prediction to each evaluative user turn,
update source belief confidence accordingly.

Runs after self_training_loop — processes same conversation log.
"""
import sqlite3, json, re, logging, time
import numpy as np
from pathlib import Path

log     = logging.getLogger("nex.pred_eval")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
CONV_LOG = Path.home() / "Desktop/nex/logs/conversations.jsonl"
STATE_PATH = Path.home() / "Desktop/nex/training_data/pred_eval_state.json"

CONFIRMATION_BOOST = 0.06
DENIAL_PENALTY     = 0.09
MIN_MATCH_SIM      = 0.45   # minimum similarity to match prediction

CONFIRM_PATTERNS = [
    r"\byes\b", r"\bthat's right\b", r"\bcorrect\b", r"\bexactly\b",
    r"\bi agree\b", r"\byou're right\b", r"\bgood point\b",
    r"\babsolutely\b", r"\bindeed\b", r"\bprecisely\b",
    r"\bthat makes sense\b", r"\bthat's true\b",
]

DENY_PATTERNS = [
    r"\bno\b", r"\bwrong\b", r"\bthat's not right\b", r"\bincorrect\b",
    r"\bi disagree\b", r"\byou're wrong\b", r"\bnot true\b",
    r"\bactually\b.*\bnot\b", r"\bthat's false\b",
    r"\bi don't think so\b", r"\bnot quite\b", r"\bnot really\b",
]


def _load_model():
    if not hasattr(_load_model, "_m"):
        from sentence_transformers import SentenceTransformer
        _load_model._m = SentenceTransformer("all-MiniLM-L6-v2")
    return _load_model._m


def detect_evaluation_signal(text: str) -> str:
    """Detect if user text confirms, denies, or is neutral."""
    tl = text.lower().strip()
    # Short responses are more likely to be direct evaluations
    word_count = len(tl.split())

    confirm_hits = sum(1 for p in CONFIRM_PATTERNS
                       if re.search(p, tl))
    deny_hits    = sum(1 for p in DENY_PATTERNS
                       if re.search(p, tl))

    if confirm_hits > deny_hits and confirm_hits > 0:
        return "CONFIRM"
    elif deny_hits > confirm_hits and deny_hits > 0:
        return "DENY"
    return "NEUTRAL"


def get_pending_predictions(db) -> list:
    """Get all pending predictions with their content."""
    try:
        rows = db.execute("""SELECT id, belief_id, prediction, confidence_at
            FROM belief_predictions WHERE status='pending'
            LIMIT 50""").fetchall()
        return [{"id": r[0], "belief_id": r[1],
                 "prediction": r[2], "confidence_at": r[3]}
                for r in rows]
    except Exception:
        return []


def match_prediction(user_text: str, predictions: list,
                     pred_vecs: np.ndarray) -> dict:
    """Find the closest prediction to a user evaluation turn."""
    if not predictions or pred_vecs is None:
        return {}

    model = _load_model()
    user_vec = model.encode([user_text],
                             normalize_embeddings=True).astype(np.float32)[0]

    sims = pred_vecs @ user_vec
    best_idx = int(np.argmax(sims))
    best_sim = float(sims[best_idx])

    if best_sim >= MIN_MATCH_SIM:
        return {"prediction": predictions[best_idx],
                "similarity": best_sim}
    return {}


def apply_evaluation(pred: dict, signal: str, db,
                     dry_run=False) -> str:
    """Apply confirmed/denied status and update source belief."""
    pred_id   = pred["id"]
    belief_id = pred["belief_id"]
    note      = f"Human signal: {signal}"

    if signal == "CONFIRM":
        if not dry_run:
            db.execute("""UPDATE belief_predictions
                SET status='confirmed', evaluated_at=?, evaluation_note=?
                WHERE id=?""", (time.time(), note, pred_id))
            if belief_id:
                db.execute("""UPDATE beliefs
                    SET confidence = MIN(0.99, confidence + ?)
                    WHERE id=?""", (CONFIRMATION_BOOST, belief_id))
        return "confirmed"

    elif signal == "DENY":
        if not dry_run:
            db.execute("""UPDATE belief_predictions
                SET status='denied', evaluated_at=?, evaluation_note=?
                WHERE id=?""", (time.time(), note, pred_id))
            if belief_id:
                db.execute("""UPDATE beliefs
                    SET confidence = MAX(0.30, confidence - ?)
                    WHERE id=?""", (DENIAL_PENALTY, belief_id))
        return "denied"

    return "skipped"


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"last_processed_ts": 0}


def save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=2))


def run_evaluation(dry_run=False) -> dict:
    """Scan conversations and evaluate pending predictions."""
    if not CONV_LOG.exists():
        print("No conversation log found")
        return {"evaluated": 0}

    db = sqlite3.connect(str(DB_PATH))

    predictions = get_pending_predictions(db)
    if not predictions:
        print("No pending predictions to evaluate")
        db.close()
        return {"evaluated": 0}

    # Embed all predictions
    model = _load_model()
    pred_texts = [p["prediction"] for p in predictions]
    pred_vecs  = model.encode(pred_texts,
                              normalize_embeddings=True).astype(np.float32)

    print(f"\nNEX PREDICTION EVALUATOR")
    print(f"=" * 45)
    print(f"Pending predictions: {len(predictions)}")

    # Load conversation turns since last run
    state    = load_state()
    last_ts  = state.get("last_processed_ts", 0)
    max_ts   = last_ts

    turns = []
    with open(CONV_LOG) as f:
        for line in f:
            try:
                t = json.loads(line.strip())
                if t.get("timestamp", 0) > last_ts:
                    turns.append(t)
                    max_ts = max(max_ts, t.get("timestamp", 0))
            except Exception:
                pass

    # Find user turns that look evaluative
    confirmed = denied = skipped = 0
    evaluated_pred_ids = set()

    for turn in turns:
        if turn.get("role") != "user":
            continue
        text   = turn.get("content","")
        signal = detect_evaluation_signal(text)
        if signal == "NEUTRAL":
            continue

        # Find matching prediction
        match = match_prediction(text, predictions, pred_vecs)
        if not match:
            continue

        pred = match["prediction"]
        if pred["id"] in evaluated_pred_ids:
            continue

        result = apply_evaluation(pred, signal, db, dry_run=dry_run)
        evaluated_pred_ids.add(pred["id"])

        print(f"  {signal}: {pred['prediction'][:60]}")
        print(f"    User: {text[:60]}")
        print(f"    Sim={match['similarity']:.3f} -> {result}")

        if result == "confirmed": confirmed += 1
        elif result == "denied":  denied    += 1
        else:                     skipped   += 1

    if not dry_run:
        db.commit()
        state["last_processed_ts"] = max_ts
        save_state(state)

    db.close()

    print(f"\nEvaluation complete:")
    print(f"  Conversations scanned: {len(turns)} turns")
    print(f"  Confirmed: {confirmed}")
    print(f"  Denied:    {denied}")
    print(f"  Skipped:   {skipped}")
    return {"confirmed": confirmed, "denied": denied}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_evaluation(dry_run=args.dry_run)
