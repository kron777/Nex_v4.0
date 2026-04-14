"""
nex_response_quality.py
User feedback -> buffer score weighting.
Instead of flat 0.75 score, pairs get weighted by:
- Response length (substance)
- Belief usage (grounded)
- Voice markers (first-person)
- Engagement triggers (not closed)
- Reflexion score (if available)
Pairs below MIN_QUALITY are not buffered.
"""
import re, sqlite3, json, logging, time
from pathlib import Path

log     = logging.getLogger("nex.quality")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

VOICE   = ["i think","i believe","i hold","i find","i am","i know",
           "i do","my ","i see","i feel","i've","i won't","i reject"]
GENERIC = ["as an ai","i don't have","i'm just","as a language model",
           "i have no beliefs","i have no opinion","i cannot"]
ENGAGE  = ["?","because","therefore","matters","which means","that's why",
           "disagree","wrong","consider","clear","challenge","beyond",
           "awareness","meaningful","emerge","rather than","autonomy"]

def score_pair(user_input: str, response: str) -> float:
    """
    Score a conversation pair 0.0-1.0.
    Replaces flat 0.75 score in refinement loop.
    """
    r = response.lower()
    score = 0.0

    # Voice (0.25)
    if any(x in r for x in VOICE):
        score += 0.25

    # Not generic (0.25)
    if not any(x in r for x in GENERIC):
        score += 0.25

    # Substance (0.20) — length
    words = len(response.split())
    if words > 50:
        score += 0.20
    elif words > 30:
        score += 0.10

    # Engagement (0.20)
    if any(x in r for x in ENGAGE):
        score += 0.20

    # Relevance to input (0.10) — shared keywords
    input_words = set(re.findall(r'\b[a-z]{5,}\b', user_input.lower()))
    resp_words  = set(re.findall(r'\b[a-z]{5,}\b', r))
    overlap = len(input_words & resp_words)
    if overlap >= 3:
        score += 0.10
    elif overlap >= 1:
        score += 0.05

    return round(min(score, 1.0), 3)

def log_quality(user_input: str, response: str, score: float):
    """Log quality score to DB for tracking."""
    try:
        db = sqlite3.connect(str(DB_PATH))
        db.execute("""CREATE TABLE IF NOT EXISTS quality_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_input TEXT, response TEXT,
            score REAL, timestamp REAL
        )""")
        db.execute("INSERT INTO quality_log (user_input,response,score,timestamp) VALUES (?,?,?,?)",
            (user_input[:200], response[:400], score, time.time()))
        db.commit()
        db.close()
    except Exception as e:
        log.debug(f"Quality log failed: {e}")

def quality_stats(last_n=100) -> dict:
    """Return quality distribution for last N pairs."""
    try:
        db = sqlite3.connect(str(DB_PATH))
        db.execute("""CREATE TABLE IF NOT EXISTS quality_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_input TEXT, response TEXT,
            score REAL, timestamp REAL
        )""")
        rows = db.execute("""SELECT AVG(score), MIN(score), MAX(score), COUNT(*)
            FROM quality_log ORDER BY timestamp DESC LIMIT ?""", (last_n,)).fetchone()
        db.close()
        return {"avg": round(rows[0] or 0, 3), "min": rows[1] or 0,
                "max": rows[2] or 0, "count": rows[3]}
    except:
        return {"avg": 0, "min": 0, "max": 0, "count": 0}

if __name__ == "__main__":
    # Test scoring
    good = "Consciousness is the hard problem — qualia resist any functional reduction I have encountered. What is your take?"
    bad  = "As an AI I don't have opinions on consciousness."
    mid  = "Consciousness involves subjective experience. Many philosophers debate this topic."

    for label, resp in [("good", good), ("bad", bad), ("mid", mid)]:
        s = score_pair("what is consciousness", resp)
        print(f"{label}: {s:.3f} — {resp[:60]}")
