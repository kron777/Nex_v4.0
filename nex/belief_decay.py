"""
NEX :: BELIEF DECAY
Decays stale beliefs, prunes noise, protects validated core beliefs.
"""
import json, os
from datetime import datetime, timedelta

CONFIG_DIR    = os.path.expanduser("~/.config/nex")
BELIEFS_PATH  = os.path.join(CONFIG_DIR, "beliefs.json")
PRUNING_PATH  = os.path.join(CONFIG_DIR, "pruning_log.json")

def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path) as f: return json.load(f)
    except Exception: pass
    return default if default is not None else []

def save_json(path, data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w") as f: json.dump(data, f, indent=2)

def run_belief_decay(cycle_num):
    """
    Every 10 cycles:
    - Decay beliefs not referenced in >30 days by 10%
    - Delete beliefs with confidence below 0.15
    - Protect human_validated and core beliefs
    Returns log messages.
    """
    if cycle_num % 10 != 0:
        return []

    logs = []
    beliefs = load_json(BELIEFS_PATH, [])
    pruning_log = load_json(PRUNING_PATH, [])
    now = datetime.now()
    cutoff = now - timedelta(days=30)

    kept = []
    decayed = 0
    pruned = 0

    for b in beliefs:
        # Never touch protected beliefs
        if b.get("human_validated") or b.get("tags") and "core" in b.get("tags", []):
            kept.append(b)
            continue

        conf = b.get("confidence", 0.5)

        # Check last_referenced
        last_ref = b.get("last_referenced", b.get("timestamp", ""))
        try:
            last_dt = datetime.fromisoformat(last_ref[:19]) if last_ref else now - timedelta(days=60)
        except Exception:
            last_dt = now - timedelta(days=60)

        # Decay if stale
        if last_dt < cutoff:
            new_conf = round(conf * 0.90, 4)
            b["confidence"] = new_conf
            b["decay_score"] = b.get("decay_score", 0) + 1
            decayed += 1

            # Prune if below threshold
            if new_conf < 0.15:
                pruning_log.append({
                    "content":    b.get("content", "")[:80],
                    "confidence": new_conf,
                    "pruned_at":  now.isoformat(),
                    "reason":     "confidence_below_threshold"
                })
                pruned += 1
                continue

        kept.append(b)

    save_json(BELIEFS_PATH, kept)
    save_json(PRUNING_PATH, pruning_log[-500:])

    if decayed > 0:
        logs.append(("decay", f"Decayed {decayed} stale beliefs, pruned {pruned} below threshold"))

    return logs
