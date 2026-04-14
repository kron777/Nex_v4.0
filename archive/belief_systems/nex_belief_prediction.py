#!/usr/bin/env python3
"""NEX LAYER 2 — PREDICTIVE BELIEF TESTING"""
import sys, json, re, hashlib, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

NEX_DIR    = Path.home() / "Desktop/nex"
CONFIG_DIR = Path.home() / ".config/nex"
LOG_PATH   = CONFIG_DIR / "nex_belief_prediction.log"
PRED_FILE  = CONFIG_DIR / "nex_predictions.json"

logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
    format="[%(asctime)s] [predict] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("predict")

sys.path.insert(0, str(NEX_DIR))
from nex_beliefs_adapter import (
    get_high_confidence_beliefs, get_recent_absorb_content,
    load_predictions, save_predictions
)

HIGH_CONFIDENCE_THRESHOLD = 0.72
MIN_REINFORCE_FOR_TEST    = 5
CONFIRM_BONUS             = 0.04
DISCONFIRM_PENALTY        = 0.08
REVISION_THRESHOLD        = 0.30
PREDICTION_EXPIRY_DAYS    = 14


def extract_keywords(text):
    stop = {
        "the","a","an","is","are","was","were","be","been","have","has","had",
        "do","does","will","would","could","should","may","might","must","can",
        "it","its","this","that","these","i","you","he","she","we","they",
        "and","but","or","if","of","in","on","at","to","for","with","by",
        "from","as","into","about","not","what","which","who","when","where",
        "how","all","some","more","most","very","just","than","so","also",
        "then","such","each","both","after","before","through","between"
    }
    words  = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
    seen   = set()
    result = []
    for w in words:
        if w not in stop and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:6]


def derive_implication(content):
    cl = content.lower()
    for pat in [
        r'(\w+(?:\s\w+)?)\s+(?:causes?|leads? to|produces?|results? in)\s+(\w+(?:\s\w+)?)',
        r'(\w+(?:\s\w+)?)\s+(?:is|are)\s+(?:essential|critical|necessary)\s+for\s+(\w+(?:\s\w+)?)',
    ]:
        m = re.search(pat, cl)
        if m:
            return {"text": f"If '{m.group(1)}' → '{m.group(2)}', content about '{m.group(2)}' should appear",
                    "keywords": [m.group(1).strip(), m.group(2).strip()]}
    m = re.search(r'(\w+(?:\s\w+)?)\s+(?:relates? to|connected to|associated with)\s+(\w+(?:\s\w+)?)', cl)
    if m:
        return {"text": f"'{m.group(1)}' and '{m.group(2)}' should co-occur",
                "keywords": [m.group(1).strip(), m.group(2).strip()]}
    return None


def derive_predictions(belief):
    content = belief.get("content", "")
    topic   = belief.get("topic", "general")
    conf    = belief.get("confidence", 0.5)
    b_id    = str(belief.get("rowid", ""))
    if not content or len(content) < 20:
        return []
    uid  = hashlib.md5(f"{b_id}{content[:40]}".encode()).hexdigest()[:8]
    preds = []
    kw    = extract_keywords(content)
    if kw:
        preds.append({
            "prediction_id":   f"pred_cont_{uid}",
            "belief_id":       b_id,
            "belief_content":  content[:200],
            "topic":           topic,
            "prediction_text": f"Content about '{kw[0]}' should continue appearing",
            "prediction_type": "continuation",
            "test_keywords":   kw[:3],
            "created_at":      datetime.now(timezone.utc).isoformat(),
            "tested_at":       None,
            "result":          "pending",
            "confidence_before": conf,
            "confidence_after":  None,
            "evidence_snippet":  None,
        })
    impl = derive_implication(content)
    if impl:
        preds.append({
            "prediction_id":   f"pred_impl_{uid}",
            "belief_id":       b_id,
            "belief_content":  content[:200],
            "topic":           topic,
            "prediction_text": impl["text"],
            "prediction_type": "implication",
            "test_keywords":   impl["keywords"],
            "created_at":      datetime.now(timezone.utc).isoformat(),
            "tested_at":       None,
            "result":          "pending",
            "confidence_before": conf,
            "confidence_after":  None,
            "evidence_snippet":  None,
        })
    if conf > 0.80:
        preds.append({
            "prediction_id":   f"pred_freq_{uid}",
            "belief_id":       b_id,
            "belief_content":  content[:200],
            "topic":           topic,
            "prediction_text": f"Topic '{topic}' should appear frequently",
            "prediction_type": "frequency",
            "test_keywords":   [topic] + (kw[:2] if kw else []),
            "created_at":      datetime.now(timezone.utc).isoformat(),
            "tested_at":       None,
            "result":          "pending",
            "confidence_before": conf,
            "confidence_after":  None,
            "evidence_snippet":  None,
        })
    return preds


def test_prediction_against_content(pred, content_batch):
    test_kw = pred.get("test_keywords", [])
    if not test_kw or not content_batch:
        return pred
    corpus   = " ".join(c.get("content", "") or "" for c in content_batch).lower()
    hits     = [kw for kw in test_kw if kw.lower() in corpus]
    hit_ratio = len(hits) / len(test_kw)
    thresholds = {"frequency": 0.6, "continuation": 0.4, "implication": 0.5}
    thresh     = thresholds.get(pred.get("prediction_type", "continuation"), 0.4)
    pred["result"]          = "confirmed" if hit_ratio >= thresh else "disconfirmed"
    pred["tested_at"]       = datetime.now(timezone.utc).isoformat()
    pred["hit_ratio"]       = round(hit_ratio, 3)
    pred["evidence_snippet"] = corpus[corpus.find(hits[0]):corpus.find(hits[0])+100] if hits else None
    return pred


def check_expiry(pred):
    try:
        created = datetime.fromisoformat(pred.get("created_at","").replace("Z","+00:00"))
        return (datetime.now(timezone.utc) - created).days > PREDICTION_EXPIRY_DAYS
    except Exception:
        return True


def main():
    import argparse
    p = argparse.ArgumentParser(description="NEX Predictive Belief Testing")
    p.add_argument("--dry",     action="store_true")
    p.add_argument("--hours",   type=int, default=24)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    print("\n[NEX] PREDICTIVE BELIEF TESTING — INITIALISING")
    log.info("belief prediction cycle started")

    predictions = load_predictions()
    new_preds   = []
    tested      = []

    # Derive new predictions
    beliefs      = get_high_confidence_beliefs()
    existing_ids = {p["belief_id"] for p in predictions}
    print(f"[NEX] High-confidence beliefs: {len(beliefs)}")

    for belief in beliefs:
        if str(belief.get("rowid","")) in existing_ids:
            continue
        derived = derive_predictions(belief)
        new_preds.extend(derived)

    predictions.extend(new_preds)
    print(f"[NEX] New predictions derived: {len(new_preds)}")

    # Test pending
    content_batch = get_recent_absorb_content(hours=args.hours)
    pending       = [p for p in predictions if p.get("result") == "pending"]
    print(f"[NEX] Pending predictions: {len(pending)}  Content items: {len(content_batch)}")

    confirmed = disconfirmed = expired = 0
    for pred in pending:
        if check_expiry(pred):
            pred["result"]    = "expired"
            pred["tested_at"] = datetime.now(timezone.utc).isoformat()
            expired += 1
            tested.append(pred)
            continue
        pred = test_prediction_against_content(pred, content_batch)
        tested.append(pred)
        if pred["result"] == "confirmed":
            confirmed += 1
        else:
            disconfirmed += 1
        if args.verbose:
            print(f"  [{pred['prediction_type']}] {pred['result']}  ratio={pred.get('hit_ratio',0):.2f}  {pred['prediction_text'][:60]}")

    if not args.dry:
        save_predictions(predictions)

    print(f"\n[NEX] Confirmed={confirmed}  Disconfirmed={disconfirmed}  Expired={expired}")
    log.info(f"cycle: new={len(new_preds)} confirmed={confirmed} disconfirmed={disconfirmed}")
    return predictions


if __name__ == "__main__":
    main()
