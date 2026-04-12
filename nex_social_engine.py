"""
nex_social_engine.py — Belief-graph-native conversation intelligence
Provides SocialEngine used by nex_soul_loop.py
"""
import os, sys, sqlite3, logging
_ROOT = os.path.expanduser("~/Desktop/nex")
for _p in [_ROOT, os.path.join(_ROOT,"nex")]:
    if _p not in sys.path: sys.path.insert(0, _p)
log = logging.getLogger("nex_social_engine")

class SocialEngine:
    def __init__(self, db_path="nex.db"):
        self.db_path = os.path.join(_ROOT, db_path) if not os.path.isabs(db_path) else db_path
        self._ready = False
        try:
            con = sqlite3.connect(self.db_path)
            con.execute("SELECT COUNT(*) FROM beliefs").fetchone()
            con.close()
            self._ready = True
            log.info("SocialEngine ready")
        except Exception as e:
            log.warning(f"SocialEngine init: {e}")

    def get_conversation_context(self, query: str, limit: int = 5) -> list:
        if not self._ready: return []
        try:
            keywords = [w.lower() for w in query.split() if len(w) > 3][:5]
            if not keywords: return []
            con = sqlite3.connect(self.db_path)
            placeholders = " OR ".join(["LOWER(content) LIKE ?"] * len(keywords))
            rows = con.execute(f"""
                SELECT content, topic, confidence FROM beliefs
                WHERE ({placeholders}) AND confidence > 0.5
                ORDER BY confidence DESC LIMIT ?
            """, [f"%{k}%" for k in keywords] + [limit]).fetchall()
            con.close()
            return [{"content": r[0], "topic": r[1], "confidence": r[2]} for r in rows]
        except Exception as e:
            log.warning(f"get_conversation_context: {e}")
            return []

    def score_response(self, response: str, context: list) -> float:
        if not response or not context: return 0.5
        resp_words = set(response.lower().split())
        scores = []
        for c in context:
            ctx_words = set(c.get("content","").lower().split())
            overlap = len(resp_words & ctx_words) / max(len(resp_words), 1)
            scores.append(overlap * c.get("confidence", 0.5))
        return sum(scores) / len(scores) if scores else 0.5

    def is_ready(self) -> bool:
        return self._ready

    def analyse(self, query: str, history: list = None) -> dict:
        """Called by soul_loop social intercept."""
        context = self.get_conversation_context(query, limit=5)
        return {
            "context":      context,
            "query":        query,
            "score":        self.score_response(query, context),
            "topics":       list({c["topic"] for c in context}),
            "ready":        self._ready,
        }
