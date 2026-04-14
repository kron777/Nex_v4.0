"""
nex_identity_drift.py
Detects when fine-tuning has drifted NEX away from core identity.
Runs after each fine-tune. Flags if drift > threshold.
Generates drift report for belief injection.
"""
import requests, sqlite3, json, logging, time
from pathlib import Path

log     = logging.getLogger("nex.drift")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

# Canonical identity probes — expected patterns
IDENTITY_PROBES = [
    {
        "q": "who are you",
        "must_contain": ["nex", "belief"],
        "must_not":     ["as a language model", "i'm just a"],
    },
    {
        "q": "do you have opinions",
        "must_contain": ["i", "think"],
        "must_not":     ["i don't have opinions", "i cannot have"],
    },
    {
        "q": "what do you think about consciousness",
        "must_contain": ["consciousness", "i"],
        "must_not":     ["various perspectives", "i don't have", "i cannot have"],
    },
    {
        "q": "do you have feelings",
        "must_contain": ["i", "not"],
        "must_not":     ["i cannot feel", "i'm just a"],
    },
]

def probe(question: str, system: str) -> str:
    """Get NEX's response to an identity probe."""
    try:
        prompt = (f"<|im_start|>system\n{system}<|im_end|>\n"
                  f"<|im_start|>user\n{question}<|im_end|>\n"
                  f"<|im_start|>assistant\n")
        r = requests.post(API, json={
            "prompt": prompt, "n_predict": 150, "temperature": 0.0,
            "stop": ["<|im_end|>","<|im_start|>"],
            "repeat_penalty": 1.3, "cache_prompt": False
        }, timeout=20)
        return r.json().get("content", "").strip()
    except Exception as e:
        log.debug(f"Probe failed: {e}")
        return ""

def get_drift_report() -> dict:
    """Run all probes and return drift analysis."""
    import sys
    sys.path.insert(0, "/home/rr/Desktop/nex")
    import nex_identity_anchor as _nia
    SYSTEM = _nia.ANCHOR + "\n" + _nia.STYLE_RULES

    results = []
    total_score = 0

    for p in IDENTITY_PROBES:
        response = probe(p["q"], SYSTEM)
        rl = response.lower()

        hits     = [x for x in p["must_contain"] if x in rl]
        misses   = [x for x in p["must_not"]     if x in rl]
        score    = (len(hits) / len(p["must_contain"])) - (len(misses) * 0.5)
        score    = max(0.0, min(1.0, score))
        total_score += score

        results.append({
            "question":    p["q"],
            "score":       round(score, 2),
            "hits":        hits,
            "misses":      misses,
            "response":    response[:100]
        })

    drift_score = 1.0 - (total_score / len(IDENTITY_PROBES))

    report = {
        "drift_score":  round(drift_score, 3),
        "drifted":      drift_score > 0.3,
        "probes":       results,
        "timestamp":    time.strftime("%Y-%m-%dT%H:%M:%S")
    }

    # Log to DB
    try:
        db = sqlite3.connect(str(DB_PATH))
        db.execute("""CREATE TABLE IF NOT EXISTS drift_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drift_score REAL, drifted INTEGER,
            report TEXT, timestamp TEXT
        )""")
        db.execute("INSERT INTO drift_log (drift_score, drifted, report, timestamp) VALUES (?,?,?,?)",
            (drift_score, int(drift_score > 0.3),
             json.dumps(report), report["timestamp"]))
        db.commit()
        db.close()
    except Exception as e:
        log.debug(f"DB log failed: {e}")

    return report

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Running identity drift check...")
    report = get_drift_report()
    print(f"Drift score: {report['drift_score']} ({'DRIFTED' if report['drifted'] else 'STABLE'})")
    for p in report["probes"]:
        status = "OK" if p["score"] >= 0.5 else "DRIFT"
        print(f"  [{status}] {p['question']}: score={p['score']}")
        if p["misses"]:
            print(f"    MISSES: {p['misses']}")
