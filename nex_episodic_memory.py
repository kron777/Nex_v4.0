"""
nex_episodic_memory.py
FAISS-indexed episodic memory over past conversations.
Store: user_input, response, score, topics, beliefs_used.
Recall: top-k similar past episodes injected into reason().
"""
import sqlite3, json, time, logging
import numpy as np
from pathlib import Path

log = logging.getLogger("nex.episodic")
DB_PATH    = Path.home() / "Desktop/nex/nex.db"
INDEX_PATH = Path.home() / ".config/nex/episodic.faiss"
META_PATH  = Path.home() / ".config/nex/episodic_meta.json"
EMBED_DIM  = 384

class EpisodicMemory:
    def __init__(self, db_path=DB_PATH):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init_table()
        self._load_model()
        self._load_index()

    def _init_table(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS episodes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_input   TEXT,
            nex_response TEXT,
            outcome_score REAL DEFAULT 0.0,
            topics       TEXT DEFAULT '[]',
            beliefs_used TEXT DEFAULT '[]',
            timestamp    REAL
        )""")
        self.db.commit()

    def _load_model(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer('all-MiniLM-L6-v2')

    def _load_index(self):
        import faiss
        self.faiss = faiss
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        if INDEX_PATH.exists() and META_PATH.exists():
            self.index   = faiss.read_index(str(INDEX_PATH))
            self.id_map  = json.loads(META_PATH.read_text())
            log.info(f"Episodic index loaded — {self.index.ntotal} episodes")
        else:
            self.index  = faiss.IndexFlatIP(EMBED_DIM)
            self.id_map = []
            log.info("Episodic index created (empty)")

    def _save_index(self):
        self.faiss.write_index(self.index, str(INDEX_PATH))
        META_PATH.write_text(json.dumps(self.id_map))

    def store(self, user_input, response, score=0.0, topics=None, beliefs_used=None):
        cur = self.db.execute("""INSERT INTO episodes
            (user_input, nex_response, outcome_score, topics, beliefs_used, timestamp)
            VALUES (?,?,?,?,?,?)""",
            (user_input, response, score,
             json.dumps(topics or []),
             json.dumps(beliefs_used or []),
             time.time()))
        self.db.commit()
        ep_id = cur.lastrowid

        vec = self.model.encode([user_input])[0].astype(np.float32)
        # Normalize for cosine via IndexFlatIP
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        self.index.add(vec.reshape(1, -1))
        self.id_map.append(ep_id)
        self._save_index()
        log.debug(f"Episode {ep_id} stored (score={score})")
        return ep_id

    def recall(self, query, k=3, min_score=0.5):
        """Return k most similar past episodes above quality threshold."""
        if self.index.ntotal == 0:
            return []
        vec = self.model.encode([query])[0].astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        D, I = self.index.search(vec.reshape(1, -1), min(k * 3, self.index.ntotal))
        results = []
        for sim, pos in zip(D[0], I[0]):
            if pos < 0 or pos >= len(self.id_map):
                continue
            ep_id = self.id_map[pos]
            row = self.db.execute(
                "SELECT user_input, nex_response, outcome_score FROM episodes WHERE id=?",
                (ep_id,)).fetchone()
            if row and row['outcome_score'] >= min_score:
                results.append({
                    'input':    row['user_input'],
                    'response': row['nex_response'],
                    'score':    row['outcome_score'],
                    'similarity': float(sim)
                })
            if len(results) >= k:
                break
        return results

    def prompt_block(self, query, k=2):
        """Format recalled episodes for system prompt injection."""
        episodes = self.recall(query, k=k)
        if not episodes:
            return ""
        lines = ["RELEVANT PAST THINKING:"]
        for ep in episodes:
            lines.append(f"  Q: {ep['input'][:80]}")
            lines.append(f"  A: {ep['response'][:120]}...")
        return "\n".join(lines)

    def stats(self):
        count = self.db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        avg   = self.db.execute("SELECT AVG(outcome_score) FROM episodes").fetchone()[0]
        return {"total": count, "avg_score": round(avg or 0, 3), "indexed": self.index.ntotal}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mem = EpisodicMemory()
    print("Stats:", mem.stats())
    # Test store and recall
    mem.store("what is consciousness", "Consciousness is the hard problem — qualia resist reduction.", score=0.9)
    mem.store("do you have free will", "Compatibilism is the only coherent position.", score=0.85)
    results = mem.recall("consciousness and subjective experience")
    print(f"\nRecall results: {len(results)}")
    for r in results:
        print(f"  [{r['score']}] {r['input']} -> {r['response'][:60]}")
