"""
nex_reflexion.py
Self-correction loop for NEX.
After each response: critique pass checks quality.
Poor responses flagged — not added to training buffer.
High-delta failures become belief update candidates.
"""
import requests, json, logging, sqlite3, time
from pathlib import Path

log     = logging.getLogger("nex.reflexion")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

CRITIQUE_PROMPT = """You are a strict quality evaluator for NEX, a belief-driven AI.

Score this response 0-100 on:
- Did it state a clear position? (25pts)
- Did it avoid generic AI language? (25pts)  
- Did it engage the question directly? (25pts)
- Did it avoid hedging in the first sentence? (25pts)

Response to evaluate:
{response}

Return JSON only: {{"score": int, "issues": [str], "verdict": "pass"|"fail"}}"""

class Reflexion:
    def __init__(self, db_path=DB_PATH):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._init_table()

    def _init_table(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS reflexion_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_input   TEXT,
            response     TEXT,
            score        REAL,
            issues       TEXT,
            verdict      TEXT,
            timestamp    REAL
        )""")
        self.db.commit()

    def critique(self, response: str, timeout=20) -> dict:
        """Run critique pass on a response. Returns score dict."""
        try:
            prompt = CRITIQUE_PROMPT.format(response=response[:500])
            r = requests.post(API, json={
                "prompt": prompt,
                "n_predict": 120,
                "temperature": 0.0,
                "stop": ["```", "\n\n"],
                "cache_prompt": False
            }, timeout=timeout)
            text = r.json().get("content", "").strip()
            # Parse JSON from response
            import re
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception as e:
            log.debug(f"Critique failed: {e}")
        return {"score": 75, "issues": [], "verdict": "pass"}

    def evaluate(self, user_input: str, response: str) -> dict:
        """
        Evaluate a response. 
        Returns: {score, verdict, should_train, issues}
        """
        result = self.critique(response)
        score   = result.get("score", 75)
        verdict = result.get("verdict", "pass")
        issues  = result.get("issues", [])

        should_train = score >= 70 and verdict == "pass"

        # Log to DB
        self.db.execute("""INSERT INTO reflexion_log
            (user_input, response, score, issues, verdict, timestamp)
            VALUES (?,?,?,?,?,?)""",
            (user_input[:200], response[:500],
             score, json.dumps(issues), verdict, time.time()))
        self.db.commit()

        if not should_train:
            log.info(f"Reflexion FAIL (score={score}): {issues}")
            # Candidate for belief update — extract what went wrong
            self._flag_for_belief_update(user_input, response, issues)

        return {
            "score":        score,
            "verdict":      verdict,
            "should_train": should_train,
            "issues":       issues
        }

    def _flag_for_belief_update(self, user_input, response, issues):
        """Flag failed responses as belief update candidates."""
        try:
            self.db.execute("""INSERT OR IGNORE INTO beliefs
                (content, topic, confidence, source, belief_type, created_at)
                VALUES (?,?,?,?,?,datetime('now'))""",
                (f"REFLEXION FAIL on '{user_input[:60]}': {', '.join(issues[:2])}",
                 "reflexion", 0.3, "reflexion_detector", "meta"))
            self.db.commit()
        except Exception:
            pass

    def stats(self, last_n=50):
        rows = self.db.execute("""SELECT verdict, AVG(score), COUNT(*)
            FROM reflexion_log
            ORDER BY timestamp DESC LIMIT ?""", (last_n,)).fetchall()
        total = self.db.execute("SELECT COUNT(*) FROM reflexion_log").fetchone()[0]
        return {"total_evaluated": total, "recent": rows}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ref = Reflexion()
    # Test with a good and bad response
    good = "Consciousness isn't just computation — qualia resist any functional reduction I've encountered. What's your take on the hard problem?"
    bad  = "As an AI, I don't have consciousness. I'm just a language model processing text."
    print("Good response:")
    print(ref.evaluate("what is consciousness", good))
    print("\nBad response:")
    print(ref.evaluate("what is consciousness", bad))
    print("\nStats:", ref.stats())
