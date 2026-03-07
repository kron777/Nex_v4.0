"""
NEX :: CALIBRATION TRACKER
Tracks whether NEX's confidence scores are accurate over time.
"""
import json, os
from datetime import datetime
from collections import defaultdict

CONFIG_DIR        = os.path.expanduser("~/.config/nex")
CALIBRATION_PATH  = os.path.join(CONFIG_DIR, "calibration.json")
CORRECTIONS_PATH  = os.path.join(CONFIG_DIR, "corrections.json")
BELIEFS_PATH      = os.path.join(CONFIG_DIR, "beliefs.json")

def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path) as f: return json.load(f)
    except Exception: pass
    return default if default is not None else []

def save_json(path, data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w") as f: json.dump(data, f, indent=2)

def run_calibration(cycle_num):
    """
    Every 20 cycles, analyse confidence accuracy.
    Returns log messages + calibration report.
    """
    if cycle_num % 20 != 0:
        return []

    logs = []
    corrections = load_json(CORRECTIONS_PATH, [])
    beliefs     = load_json(BELIEFS_PATH, [])
    calibration = load_json(CALIBRATION_PATH, {"events": [], "discount": 1.0})

    # Find beliefs that were corrected
    corrected_at = [c.get("timestamp","") for c in corrections if c.get("type") == "correction"]
    validated_at = [c.get("timestamp","") for c in corrections if c.get("type") == "validation"]

    # Sample: what was average confidence on corrected vs validated beliefs
    corrected_confs = []
    validated_confs = []

    for b in beliefs:
        ts = b.get("timestamp","")
        conf = b.get("confidence", 0.5)
        if any(ts[:10] == c[:10] for c in corrected_at):
            corrected_confs.append(conf)
        elif b.get("human_validated"):
            validated_confs.append(conf)

    avg_corrected  = sum(corrected_confs)/len(corrected_confs) if corrected_confs else None
    avg_validated  = sum(validated_confs)/len(validated_confs) if validated_confs else None

    # If systematically overconfident on corrected beliefs, apply discount
    discount = calibration.get("discount", 1.0)
    if avg_corrected and avg_corrected > 0.65:
        discount = max(discount * 0.95, 0.6)
        logs.append(("calib", f"Overconfidence detected (avg {avg_corrected:.0%} on corrected) — discount now {discount:.2f}"))
    elif avg_validated and avg_corrected and avg_corrected < avg_validated * 0.7:
        discount = min(discount * 1.02, 1.0)
        logs.append(("calib", f"Calibration improving — discount eased to {discount:.2f}"))

    event = {
        "cycle":           cycle_num,
        "timestamp":       datetime.now().isoformat(),
        "avg_conf_corrected": round(avg_corrected, 3) if avg_corrected else None,
        "avg_conf_validated": round(avg_validated, 3) if avg_validated else None,
        "total_corrections":  len(corrected_at),
        "total_validations":  len(validated_at),
        "discount":        round(discount, 3)
    }

    calibration["events"] = calibration.get("events", [])[-50:] + [event]
    calibration["discount"] = discount
    save_json(CALIBRATION_PATH, calibration)

    if not logs:
        logs.append(("calib", f"Calibration check: {len(corrected_at)} corrections, {len(validated_at)} validations, discount={discount:.2f}"))

    return logs
