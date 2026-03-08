"""
Nex Belief Decay System
Runs every 24hrs via run.py
- Decays confidence based on age since last_referenced
- Human-validated beliefs decay 5x slower
- Deletes beliefs below 0.05 confidence
"""
import json, os
from datetime import datetime, timezone

CONFIG_DIR = os.path.expanduser("~/.config/nex")
BELIEFS_FILE = os.path.join(CONFIG_DIR, "beliefs.json")
DECAY_RATE = 0.005        # per day, normal
DECAY_RATE_VALIDATED = 0.001  # per day, human-validated
MIN_CONFIDENCE = 0.05

def run_decay():
    beliefs = json.load(open(BELIEFS_FILE))
    now = datetime.now(timezone.utc)
    kept, decayed, deleted = 0, 0, 0

    for b in beliefs:
        try:
            last = datetime.fromisoformat(b.get("last_referenced", b.get("timestamp", now.isoformat())))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age_days = (now - last).total_seconds() / 86400
            rate = DECAY_RATE_VALIDATED if b.get("human_validated") else DECAY_RATE
            decay = rate * age_days
            b["confidence"] = round(max(0.0, b.get("confidence", 0.5) - decay), 4)
            b["decay_score"] = round(b.get("decay_score", 0) + decay, 4)
        except Exception:
            pass

    before = len(beliefs)
    beliefs = [b for b in beliefs if b.get("confidence", 0) >= MIN_CONFIDENCE]
    deleted = before - len(beliefs)
    decayed = sum(1 for b in beliefs if b.get("decay_score", 0) > 0)

    json.dump(beliefs, open(BELIEFS_FILE, "w"), indent=2)
    print(f"  [Decay] {len(beliefs)} beliefs kept, {decayed} decayed, {deleted} pruned")
    return len(beliefs), deleted

if __name__ == "__main__":
    run_decay()
