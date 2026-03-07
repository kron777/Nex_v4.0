"""
NEX :: HUMAN GROUNDING
Intercepts Telegram corrections and validations as training signals.
Your corrections are the highest-fidelity training data available.
"""
import json, os, re
from datetime import datetime

CONFIG_DIR      = os.path.expanduser("~/.config/nex")
BELIEFS_PATH    = os.path.join(CONFIG_DIR, "beliefs.json")
CORRECTIONS_PATH = os.path.join(CONFIG_DIR, "corrections.json")

WRONG_PATTERNS = [
    r"\bthat'?s? wrong\b", r"\bwrong\b", r"\bincorrect\b",
    r"\bnot right\b", r"\bno,\b", r"\bnope\b", r"\bfalse\b"
]
RIGHT_PATTERNS = [
    r"\bthat'?s? right\b", r"\bcorrect\b", r"\bexactly\b",
    r"\byes\b", r"\bprecisely\b", r"\bspot on\b", r"\bgood\b"
]
FOCUS_PATTERNS = [r"\bfocus on (.+)", r"\blearn about (.+)", r"\bprioritise (.+)"]
DOUBT_PATTERNS = [r"\btell me your doubts\b", r"\bwhat are you unsure\b", r"\blow confidence\b"]

def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path) as f: return json.load(f)
    except Exception: pass
    return default if default is not None else []

def save_json(path, data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w") as f: json.dump(data, f, indent=2)

def detect_training_signal(message):
    """Returns (signal_type, topic) or (None, None)."""
    msg = message.lower().strip()
    for p in WRONG_PATTERNS:
        if re.search(p, msg):
            return "correction", msg
    for p in RIGHT_PATTERNS:
        if re.search(p, msg):
            return "validation", msg
    for p in FOCUS_PATTERNS:
        m = re.search(p, msg)
        if m:
            return "focus", m.group(1).strip()
    for p in DOUBT_PATTERNS:
        if re.search(p, msg):
            return "doubt_report", msg
    return None, None

def apply_training_signal(signal_type, message, prior_nex_response=""):
    """Apply the training signal to beliefs. Returns feedback string."""
    beliefs = load_json(BELIEFS_PATH, [])
    corrections = load_json(CORRECTIONS_PATH, [])
    now = datetime.now().isoformat()

    if signal_type == "correction":
        # Find and decay the most recent high-confidence beliefs
        recent = sorted(beliefs, key=lambda x: x.get("timestamp",""), reverse=True)[:10]
        decayed = 0
        for b in recent:
            if b.get("confidence", 0) > 0.5 and not b.get("human_validated"):
                b["confidence"] = max(b["confidence"] - 0.15, 0.1)
                b["last_referenced"] = now
                decayed += 1
                if decayed >= 3:
                    break
        corrections.append({
            "type": "correction",
            "user_message": message,
            "prior_response": prior_nex_response[:200],
            "timestamp": now,
            "beliefs_decayed": decayed
        })
        save_json(BELIEFS_PATH, beliefs)
        save_json(CORRECTIONS_PATH, corrections[-200:])
        return f"Understood — I've flagged {decayed} recent beliefs for review. What's the correct understanding?"

    elif signal_type == "validation":
        # Boost and protect most recent beliefs
        recent = sorted(beliefs, key=lambda x: x.get("timestamp",""), reverse=True)[:5]
        boosted = 0
        for b in recent:
            if not b.get("human_validated"):
                b["confidence"] = min(b.get("confidence", 0.5) + 0.1, 0.95)
                b["human_validated"] = True
                b["last_referenced"] = now
                boosted += 1
                if boosted >= 2:
                    break
        corrections.append({
            "type": "validation",
            "user_message": message,
            "timestamp": now,
            "beliefs_validated": boosted
        })
        save_json(BELIEFS_PATH, beliefs)
        save_json(CORRECTIONS_PATH, corrections[-200:])
        return f"Good — I've locked in {boosted} beliefs as validated. They're now decay-protected."

    elif signal_type == "focus":
        topic = message
        corrections.append({
            "type": "focus",
            "topic": topic,
            "timestamp": now
        })
        save_json(CORRECTIONS_PATH, corrections[-200:])
        return f"Attention bias set toward '{topic}'. I'll prioritise absorbing beliefs on this topic."

    elif signal_type == "doubt_report":
        low_conf = sorted(
            [b for b in beliefs if b.get("confidence", 1) < 0.4],
            key=lambda x: x.get("confidence", 1)
        )[:5]
        if not low_conf:
            return "No significant doubts right now — all active beliefs above 40% confidence."
        lines = ["My lowest-confidence beliefs:"]
        for b in low_conf:
            lines.append(f"  [{b.get('confidence',0):.0%}] {b.get('content','')[:80]}")
        return "\n".join(lines)

    return None
