"""
nex_metacognition.py
Uncertainty estimation and epistemic self-regulation for NEX.
- Variance across samples = uncertainty signal
- High variance -> lower epistemic temperature
- Calibration tracker: predicted vs actual eval score
- Weekly report -> belief confidence adjustment
"""
import requests, json, logging, sqlite3, time, statistics
from pathlib import Path

log     = logging.getLogger("nex.meta")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

class MetaCognition:
    def __init__(self, db_path=DB_PATH):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS uncertainty_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            query       TEXT,
            variance    REAL,
            mean_len    REAL,
            n_samples   INTEGER,
            epistemic_temp REAL,
            timestamp   REAL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS calibration_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            topic         TEXT,
            predicted_conf REAL,
            actual_score  REAL,
            delta         REAL,
            timestamp     REAL
        )""")
        self.db.commit()

    def estimate_uncertainty(self, query: str, n=3, temperature=0.7) -> dict:
        """
        Sample n responses at temperature > 0.
        Variance in response length = proxy for uncertainty.
        High variance -> uncertain topic.
        """
        import sys
        sys.path.insert(0, "/home/rr/Desktop/nex")
        from nex_identity_anchor import get_system_prompt
        SYSTEM = get_system_prompt(include_style=False)

        prompt = (f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
                  f"<|im_start|>user\n{query}<|im_end|>\n"
                  f"<|im_start|>assistant\n")
        lengths = []
        for _ in range(n):
            try:
                r = requests.post(API, json={
                    "prompt": prompt, "n_predict": 150,
                    "temperature": temperature,
                    "stop": ["<|im_end|>","<|im_start|>"],
                    "cache_prompt": False
                }, timeout=30)
                text = r.json().get("content", "").strip()
                lengths.append(len(text.split()))
            except Exception:
                lengths.append(0)

        if len(lengths) < 2:
            return {"variance": 0.0, "mean_len": 0, "uncertain": False, "epistemic_temp": 0.7}

        var      = statistics.variance(lengths)
        mean_len = statistics.mean(lengths)
        # High variance (>200) = uncertain topic
        uncertain     = var > 200
        epistemic_temp = max(0.3, 0.7 - (var / 2000))

        self.db.execute("""INSERT INTO uncertainty_log
            (query, variance, mean_len, n_samples, epistemic_temp, timestamp)
            VALUES (?,?,?,?,?,?)""",
            (query[:200], var, mean_len, n, epistemic_temp, time.time()))
        self.db.commit()

        log.info(f"Uncertainty [{query[:40]}]: var={var:.1f} temp={epistemic_temp:.2f}")
        return {
            "variance":      var,
            "mean_len":      mean_len,
            "uncertain":     uncertain,
            "epistemic_temp": epistemic_temp
        }

    def log_calibration(self, topic: str, predicted_conf: float, actual_score: float):
        """Track predicted vs actual — feeds belief confidence adjustment."""
        delta = actual_score - predicted_conf
        self.db.execute("""INSERT INTO calibration_log
            (topic, predicted_conf, actual_score, delta, timestamp)
            VALUES (?,?,?,?,?)""",
            (topic, predicted_conf, actual_score, delta, time.time()))
        self.db.commit()

        # If consistently overconfident (delta < -0.2), penalise beliefs in topic
        if delta < -0.2:
            self._adjust_topic_confidence(topic, penalty=0.95)
            log.info(f"Calibration penalty on {topic} (delta={delta:.2f})")

    def _adjust_topic_confidence(self, topic: str, penalty=0.95):
        """Slightly reduce confidence of beliefs in over-predicted topics."""
        self.db.execute("""UPDATE beliefs SET confidence = confidence * ?
            WHERE topic=? AND confidence > 0.5 AND locked=0""",
            (penalty, topic))
        self.db.commit()

    def weekly_report(self) -> dict:
        """Summarise calibration over last 7 days."""
        cutoff = time.time() - 7 * 86400
        rows = self.db.execute("""SELECT topic, AVG(delta), COUNT(*)
            FROM calibration_log WHERE timestamp > ?
            GROUP BY topic ORDER BY AVG(delta) ASC""",
            (cutoff,)).fetchall()
        uncertain = self.db.execute("""SELECT query, variance
            FROM uncertainty_log WHERE timestamp > ?
            ORDER BY variance DESC LIMIT 5""",
            (cutoff,)).fetchall()
        return {
            "calibration": [{"topic": r[0], "avg_delta": round(r[1],3), "count": r[2]}
                            for r in rows],
            "most_uncertain": [{"query": u[0][:60], "variance": round(u[1],1)}
                               for u in uncertain]
        }

    def stats(self):
        uc = self.db.execute("SELECT COUNT(*) FROM uncertainty_log").fetchone()[0]
        cc = self.db.execute("SELECT COUNT(*) FROM calibration_log").fetchone()[0]
        return {"uncertainty_checks": uc, "calibration_logs": cc}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    meta = MetaCognition()
    print("Stats:", meta.stats())
    print("\nEstimating uncertainty on 'what is consciousness'...")
    result = meta.estimate_uncertainty("what is consciousness", n=3)
    print(f"Variance: {result['variance']:.1f}")
    print(f"Uncertain: {result['uncertain']}")
    print(f"Epistemic temp: {result['epistemic_temp']:.2f}")
    meta.log_calibration("consciousness", predicted_conf=0.8, actual_score=1.0)
    print("\nWeekly report:", meta.weekly_report())
