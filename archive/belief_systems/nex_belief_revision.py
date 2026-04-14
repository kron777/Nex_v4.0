#!/usr/bin/env python3
"""
NEX BELIEF REVISION ENGINE
When predictions fail, revise the beliefs that generated them.
This is the missing link between prediction and learning.
"""
import sys, json, logging
from pathlib import Path
from datetime import datetime, timezone

NEX_DIR    = Path.home() / "Desktop/nex"
CONFIG_DIR = Path.home() / ".config/nex"
LOG_PATH   = CONFIG_DIR / "nex_belief_revision.log"
REVISION_LOG = CONFIG_DIR / "nex_revision_history.json"

logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
    format="[%(asctime)s] [revision] %(message)s")
log = logging.getLogger("revision")

sys.path.insert(0, str(NEX_DIR))

def load_predictions():
    f = CONFIG_DIR / "nex_predictions.json"
    try: return json.loads(f.read_text()) if f.exists() else []
    except: return []

def load_beliefs():
    f = CONFIG_DIR / "beliefs.json"
    try: return json.loads(f.read_text())
    except: return []

def save_beliefs(beliefs):
    (CONFIG_DIR / "beliefs.json").write_text(json.dumps(beliefs, indent=2))

def load_revision_history():
    try: return json.loads(REVISION_LOG.read_text()) if REVISION_LOG.exists() else []
    except: return []

def save_revision_history(h):
    REVISION_LOG.write_text(json.dumps(h, indent=2))

def find_belief_by_id(beliefs, belief_id):
    for b in beliefs:
        if str(b.get("id","")) == str(belief_id):
            return b
    return None

def revise_from_disconfirmation(belief, prediction, beliefs):
    """
    A disconfirmed prediction means the belief that generated it
    was wrong about what it implies. Two responses:
    1. Reduce confidence slightly
    2. Generate a revision candidate — what would need to be true instead?
    """
    content  = belief.get("content", "")
    topic    = belief.get("topic", "general")
    conf     = belief.get("confidence", 0.5)
    pred_text = prediction.get("prediction_text", "")

    # Confidence reduction — graduated by how many times this belief
    # has generated disconfirmed predictions
    disconfirm_count = belief.get("disconfirm_count", 0) + 1
    belief["disconfirm_count"] = disconfirm_count

    # Graduated penalty
    penalty = min(0.03 * disconfirm_count, 0.12)
    new_conf = max(0.25, conf - penalty)
    belief["confidence"] = new_conf

    log.info(f"revised belief {belief.get('id')} conf {conf:.3f}→{new_conf:.3f} "
             f"(disconfirm #{disconfirm_count})")

    return {
        "belief_id":       str(belief.get("id","")),
        "belief_content":  content[:150],
        "topic":           topic,
        "prediction":      pred_text[:150],
        "conf_before":     conf,
        "conf_after":      new_conf,
        "disconfirm_count": disconfirm_count,
        "revised_at":      datetime.now(timezone.utc).isoformat(),
        "revision_type":   "confidence_reduction",
    }

def revise_from_confirmation(belief):
    """Confirmed prediction — earned confidence boost."""
    conf     = belief.get("confidence", 0.5)
    confirm_count = belief.get("confirm_count", 0) + 1
    belief["confirm_count"] = confirm_count
    bonus    = min(0.02 * confirm_count, 0.08)
    new_conf = min(0.95, conf + bonus)
    belief["confidence"] = new_conf
    log.info(f"confirmed belief {belief.get('id')} conf {conf:.3f}→{new_conf:.3f}")
    return {"belief_id": str(belief.get("id","")), "conf_before": conf,
            "conf_after": new_conf, "revision_type": "confirmation_boost",
            "revised_at": datetime.now(timezone.utc).isoformat()}

def main():
    print("\n[NEX] BELIEF REVISION ENGINE — RUNNING")
    predictions = load_predictions()
    beliefs     = load_beliefs()
    history     = load_revision_history()

    tested       = [p for p in predictions if p.get("result") in ("confirmed","disconfirmed")]
    unprocessed  = [p for p in tested if not p.get("revision_applied")][:20]  # cap per cycle

    print(f"[NEX] Unprocessed predictions: {len(unprocessed)}")

    revisions = []
    for pred in unprocessed:
        belief_id = pred.get("belief_id","")
        belief    = find_belief_by_id(beliefs, belief_id)
        if not belief:
            continue

        if pred["result"] == "disconfirmed":
            rev = revise_from_disconfirmation(belief, pred, beliefs)
        else:
            rev = revise_from_confirmation(belief)

        pred["revision_applied"] = True
        revisions.append(rev)
        print(f"  [{pred['result']}] belief={belief_id[:8]}  "
              f"{rev['conf_before']:.3f}→{rev['conf_after']:.3f}  "
              f"{belief.get('content','')[:60]}")

    if revisions:
        save_beliefs(beliefs)
        history.extend(revisions)
        save_revision_history(history)

        # Also update DB
        try:
            import sqlite3
            conn = sqlite3.connect(str(Path.home()/"Desktop/nex/nex.db"))
            cur  = conn.cursor()
            for rev in revisions:
                cur.execute("UPDATE beliefs SET confidence=? WHERE id=?",
                           (rev["conf_after"], rev["belief_id"]))
            conn.commit(); conn.close()
        except: pass

    print(f"[NEX] Revisions applied: {len(revisions)}")
    log.info(f"cycle complete: {len(revisions)} revisions")

if __name__ == "__main__":
    main()
