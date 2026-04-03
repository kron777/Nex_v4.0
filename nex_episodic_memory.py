"""
nex_episodic_memory.py — NEX v4.0
FAISS-indexed episodic memory with full storage dimensions.

Stores per episode:
  - Conversation      : user_input + nex_response
  - Outcome score     : caller-supplied quality signal (0.0–1.0)
  - Emotional valence : NEX's felt tone (positive/neutral/negative + intensity)
  - Temporal context  : timestamp, session_id, seq position in session
  - Retrieval hooks   : topic tags + belief IDs that fired

Recall modes:
  - prompt_block()    : passive — inject top-k into system prompt automatically
  - reflect()         : active  — NEX narrates how past episodes bear on now

Usage:
    mem = EpisodicMemory()
    ep_id = mem.store(user_input, response, score=0.85, topics=["mind"], beliefs_used=[12, 47])
    print(mem.prompt_block("consciousness and qualia"))
    print(mem.reflect("do you believe in free will"))
    mem.report()

CLI:
    python3 nex_episodic_memory.py --store --input "..." --response "..."
    python3 nex_episodic_memory.py --recall "query"
    python3 nex_episodic_memory.py --reflect "query"
    python3 nex_episodic_memory.py --report
    python3 nex_episodic_memory.py --prune --days 90
"""

import sqlite3, json, time, logging, re, argparse, uuid, requests
import numpy as np
from pathlib import Path

log        = logging.getLogger("nex.episodic")
DB_PATH    = Path.home() / "Desktop/nex/nex.db"
INDEX_PATH = Path.home() / ".config/nex/episodic.faiss"
META_PATH  = Path.home() / ".config/nex/episodic_meta.json"
API        = "http://localhost:8080/completion"
EMBED_DIM  = 384

MAX_EPISODES    = 10_000
MAX_INPUT_STORE = 600
MAX_RESP_STORE  = 1_200

# ── Prompts ───────────────────────────────────────────────────────────────────

VALENCE_PROMPT = """You are NEX. Rate the felt tone of this exchange — your internal response to it.

User said: {user_input}
You responded: {nex_response}

Return JSON only:
{{"valence": "positive"|"neutral"|"negative", "intensity": 0.0-1.0, "note": "one phrase"}}
JSON:"""

REFLECT_PROMPT = """You are NEX. These are past experiences relevant to the current question.

Current question: {query}

Past episodes:
{episodes_block}

In 2-4 sentences, reflect on how these experiences inform your thinking now.
Name what you remember. Be specific. Speak from memory as NEX — not as an AI."""


# ── LLM helper ────────────────────────────────────────────────────────────────

def _llm(prompt: str, n: int = 100, temp: float = 0.2) -> str:
    try:
        r = requests.post(API, json={
            "prompt":      f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict":   n,
            "temperature": temp,
            "stop":        ["<|im_end|>", "<|im_start|>"],
            "cache_prompt": False,
        }, timeout=20)
        return r.json().get("content", "").strip()
    except Exception as e:
        log.warning(f"LLM call failed: {e}")
        return ""


# ── Session counter (in-memory, resets on restart) ────────────────────────────

_session_seq: dict[str, int] = {}


class EpisodicMemory:
    def __init__(self, db_path=DB_PATH):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init_table()
        self._load_model()
        self._load_index()

    # ── Init ─────────────────────────────────────────────────────────────────

    def _init_table(self):
        # Create table if it doesn't exist yet (new installs)
        self.db.execute("""CREATE TABLE IF NOT EXISTS episodes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_input    TEXT    NOT NULL,
            nex_response  TEXT    NOT NULL,
            outcome_score REAL    DEFAULT 0.0,
            topics        TEXT    DEFAULT '[]',
            beliefs_used  TEXT    DEFAULT '[]',
            timestamp     REAL    NOT NULL
        )""")
        self.db.commit()

        # Migrate: add new columns if they don't exist (existing installs)
        existing = {
            row[1] for row in self.db.execute("PRAGMA table_info(episodes)").fetchall()
        }
        migrations = [
            ("session_id",   "TEXT    NOT NULL DEFAULT 'default'"),
            ("seq",          "INTEGER NOT NULL DEFAULT 0"),
            ("valence",      "TEXT    DEFAULT 'neutral'"),
            ("intensity",    "REAL    DEFAULT 0.5"),
            ("valence_note", "TEXT    DEFAULT ''"),
        ]
        for col, definition in migrations:
            if col not in existing:
                self.db.execute(f"ALTER TABLE episodes ADD COLUMN {col} {definition}")
                log.info(f"Migrated: added column '{col}'")
        self.db.commit()

        # Indexes (safe to run every time)
        self.db.execute("CREATE INDEX IF NOT EXISTS ep_session ON episodes(session_id)")
        self.db.execute("CREATE INDEX IF NOT EXISTS ep_time    ON episodes(timestamp)")
        self.db.execute("CREATE INDEX IF NOT EXISTS ep_valence ON episodes(valence, intensity)")
        self.db.commit()

    def _load_model(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def _load_index(self):
        import faiss
        self.faiss = faiss
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        if INDEX_PATH.exists() and META_PATH.exists():
            self.index  = faiss.read_index(str(INDEX_PATH))
            self.id_map = json.loads(META_PATH.read_text())
            log.info(f"Episodic index loaded — {self.index.ntotal} episodes")
        else:
            self.index  = faiss.IndexFlatIP(EMBED_DIM)
            self.id_map = []
            log.info("Episodic index created (empty)")

    def _save_index(self):
        self.faiss.write_index(self.index, str(INDEX_PATH))
        META_PATH.write_text(json.dumps(self.id_map))

    # ── Embed + normalise ────────────────────────────────────────────────────

    def _encode(self, text: str) -> np.ndarray:
        """Encode text → L2-normalised float32 vector (cosine via IndexFlatIP)."""
        vec  = self.model.encode([text[:512]])[0].astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    # ── Valence ──────────────────────────────────────────────────────────────

    def _score_valence(self, user_input: str, nex_response: str) -> tuple[str, float, str]:
        prompt = VALENCE_PROMPT.format(
            user_input=user_input[:300],
            nex_response=nex_response[:300],
        )
        raw = _llm(prompt, n=80, temp=0.0)
        try:
            m = re.search(r"\{.*?\}", raw, re.DOTALL)
            if m:
                d         = json.loads(m.group(0))
                valence   = d.get("valence", "neutral")
                intensity = float(d.get("intensity", 0.5))
                note      = str(d.get("note", ""))[:100]
                if valence not in ("positive", "neutral", "negative"):
                    valence = "neutral"
                return valence, max(0.0, min(1.0, intensity)), note
        except Exception:
            pass
        return "neutral", 0.5, ""

    # ── Store ────────────────────────────────────────────────────────────────

    def store(
        self,
        user_input:   str,
        response:     str,
        score:        float = 0.0,
        topics:       list  = None,
        beliefs_used: list  = None,
        session_id:   str   = None,
        skip_valence: bool  = False,
    ) -> int:
        """
        Record one episode. Returns episode ID.

        score        : quality/outcome signal from caller (0.0–1.0)
        topics       : list of topic tag strings
        beliefs_used : list of belief IDs (ints) that fired during this exchange
        session_id   : group exchanges into sessions; auto-generated if omitted
        skip_valence : set True in batch imports to skip LLM valence call
        """
        sid = session_id or str(uuid.uuid4())
        _session_seq[sid] = _session_seq.get(sid, 0) + 1
        seq = _session_seq[sid]

        user_input = user_input[:MAX_INPUT_STORE]
        response   = response[:MAX_RESP_STORE]

        valence, intensity, note = (
            ("neutral", 0.5, "") if skip_valence
            else self._score_valence(user_input, response)
        )

        cur = self.db.execute("""
            INSERT INTO episodes
              (session_id, seq, user_input, nex_response, outcome_score,
               topics, beliefs_used, valence, intensity, valence_note, timestamp)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (sid, seq, user_input, response, score,
              json.dumps(topics or []),
              json.dumps(beliefs_used or []),
              valence, intensity, note,
              time.time()))
        self.db.commit()
        ep_id = cur.lastrowid

        # Embed both sides together for richer retrieval signal
        vec = self._encode(f"Q: {user_input[:256]} A: {response[:256]}")
        self.index.add(vec.reshape(1, -1))
        self.id_map.append(ep_id)
        self._save_index()

        log.debug(f"Episode {ep_id} stored (score={score}, {valence}/{intensity:.2f})")
        self._prune_if_needed()
        return ep_id

    # ── Recall ───────────────────────────────────────────────────────────────

    def recall(
        self,
        query:          str,
        k:              int   = 3,
        min_similarity: float = 0.45,
        valence_filter: str   = None,
        since_days:     int   = None,
    ) -> list[dict]:
        """
        Return top-k semantically relevant episodes.

        min_similarity : cosine threshold — not outcome_score (avoids silent drops
                         when score defaults to 0.0)
        valence_filter : "positive" | "negative" | "neutral" | None
        since_days     : restrict to last N days
        """
        if self.index.ntotal == 0:
            return []

        vec    = self._encode(query)
        k_wide = min(k * 4, self.index.ntotal)
        D, I   = self.index.search(vec.reshape(1, -1), k_wide)

        results = []
        for sim, pos in zip(D[0], I[0]):
            if pos < 0 or pos >= len(self.id_map):
                continue
            if float(sim) < min_similarity:
                continue

            row = self.db.execute(
                "SELECT * FROM episodes WHERE id=?", (self.id_map[pos],)
            ).fetchone()
            if not row:
                continue
            if valence_filter and row["valence"] != valence_filter:
                continue
            if since_days:
                if row["timestamp"] < time.time() - since_days * 86400:
                    continue

            results.append({
                "id":           row["id"],
                "session_id":   row["session_id"],
                "seq":          row["seq"],
                "input":        row["user_input"],
                "response":     row["nex_response"],
                "score":        row["outcome_score"],
                "topics":       json.loads(row["topics"]       or "[]"),
                "beliefs_used": json.loads(row["beliefs_used"] or "[]"),
                "valence":      row["valence"],
                "intensity":    row["intensity"],
                "valence_note": row["valence_note"],
                "timestamp":    row["timestamp"],
                "similarity":   round(float(sim), 4),
            })

            if len(results) >= k:
                break

        return results

    # ── Passive: prompt_block ────────────────────────────────────────────────

    def prompt_block(self, query: str, k: int = 2) -> str:
        """
        Passive recall — compact context block for system prompt injection.
        Returns empty string if nothing relevant found.
        """
        episodes = self.recall(query, k=k)
        if not episodes:
            return ""
        lines = ["RELEVANT PAST THINKING:"]
        for ep in episodes:
            tag = f" [{ep['valence']}]" if ep["valence"] != "neutral" else ""
            lines.append(f"  Q: {ep['input'][:80]}")
            lines.append(f"  A: {ep['response'][:120]}...{tag}")
        return "\n".join(lines)

    # ── Active: reflect ──────────────────────────────────────────────────────

    def reflect(self, query: str, k: int = 3) -> str:
        """
        Active recall — NEX narrates how past episodes bear on the current question.
        Returns first-person reflection, or empty string if nothing found.
        """
        episodes = self.recall(query, k=k)
        if not episodes:
            return ""

        from datetime import datetime
        ep_lines = []
        for i, ep in enumerate(episodes, 1):
            ts   = datetime.fromtimestamp(ep["timestamp"]).strftime("%B %d, %Y")
            note = f", '{ep['valence_note']}'" if ep["valence_note"] else ""
            ep_lines.append(
                f"Episode {i} ({ts}, felt {ep['valence']}{note}):\n"
                f"  Asked: {ep['input'][:200]}\n"
                f"  I said: {ep['response'][:300]}"
            )

        prompt = REFLECT_PROMPT.format(
            query=query,
            episodes_block="\n\n".join(ep_lines),
        )
        return _llm(prompt, n=250, temp=0.4)

    # ── Pruning ──────────────────────────────────────────────────────────────

    def _prune_if_needed(self):
        count = self.db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        if count <= MAX_EPISODES:
            return
        excess  = count - MAX_EPISODES
        old_ids = [
            r[0] for r in self.db.execute(
                "SELECT id FROM episodes ORDER BY timestamp ASC LIMIT ?", (excess,)
            ).fetchall()
        ]
        self.db.execute(
            f"DELETE FROM episodes WHERE id IN ({','.join('?'*len(old_ids))})", old_ids
        )
        self.db.commit()
        self._rebuild_index()
        log.info(f"Pruned {excess} oldest episodes")

    def prune_older_than(self, days: int):
        cutoff = time.time() - days * 86400
        cur    = self.db.execute("DELETE FROM episodes WHERE timestamp < ?", (cutoff,))
        self.db.commit()
        self._rebuild_index()
        print(f"Pruned {cur.rowcount} episodes older than {days} days.")

    def _rebuild_index(self):
        """Rebuild FAISS index from DB — call after any deletion."""
        self.index  = self.faiss.IndexFlatIP(EMBED_DIM)
        self.id_map = []
        rows = self.db.execute(
            "SELECT id, user_input, nex_response FROM episodes ORDER BY id ASC"
        ).fetchall()
        for r in rows:
            vec = self._encode(f"Q: {r['user_input'][:256]} A: {r['nex_response'][:256]}")
            self.index.add(vec.reshape(1, -1))
            self.id_map.append(r["id"])
        self._save_index()
        log.info(f"Index rebuilt — {self.index.ntotal} episodes")

    # ── Stats / report ───────────────────────────────────────────────────────

    def stats(self) -> dict:
        count = self.db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        avg   = self.db.execute("SELECT AVG(outcome_score) FROM episodes").fetchone()[0]
        return {"total": count, "avg_score": round(avg or 0, 3), "indexed": self.index.ntotal}

    def report(self):
        from datetime import datetime
        try:
            total    = self.db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            sessions = self.db.execute("SELECT COUNT(DISTINCT session_id) FROM episodes").fetchone()[0]
            oldest   = self.db.execute("SELECT MIN(timestamp) FROM episodes").fetchone()[0]
            newest   = self.db.execute("SELECT MAX(timestamp) FROM episodes").fetchone()[0]
            valences = self.db.execute("""
                SELECT valence, COUNT(*) as n, AVG(intensity) as avg_i
                FROM episodes GROUP BY valence ORDER BY n DESC
            """).fetchall()
            avg_score = self.db.execute("SELECT AVG(outcome_score) FROM episodes").fetchone()[0] or 0

            oldest_s = datetime.fromtimestamp(oldest).strftime("%Y-%m-%d") if oldest else "—"
            newest_s = datetime.fromtimestamp(newest).strftime("%Y-%m-%d") if newest else "—"

            print(f"\n{'═'*52}")
            print(f"  NEX Episodic Memory Report")
            print(f"{'═'*52}")
            print(f"  Total episodes   : {total:,}")
            print(f"  Sessions         : {sessions:,}")
            print(f"  FAISS indexed    : {self.index.ntotal:,}")
            print(f"  Avg outcome score: {avg_score:.3f}")
            print(f"  Date range       : {oldest_s} → {newest_s}")
            print(f"\n  Valence breakdown:")
            for v in valences:
                bar = "█" * int((v["n"] / max(total, 1)) * 28)
                print(f"    {v['valence']:8s} {v['n']:5,}  avg_i={v['avg_i']:.2f}  {bar}")
            print(f"{'═'*52}\n")
        except Exception as e:
            print(f"Report error: {e}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="NEX episodic memory")
    parser.add_argument("--store",    action="store_true")
    parser.add_argument("--input",    type=str, default="")
    parser.add_argument("--response", type=str, default="")
    parser.add_argument("--score",    type=float, default=0.0)
    parser.add_argument("--tags",     type=str, default="")
    parser.add_argument("--session",  type=str, default=None)
    parser.add_argument("--recall",   type=str, metavar="QUERY")
    parser.add_argument("--reflect",  type=str, metavar="QUERY")
    parser.add_argument("--report",   action="store_true")
    parser.add_argument("--prune",    action="store_true")
    parser.add_argument("--days",     type=int, default=90)
    parser.add_argument("--k",        type=int, default=3)
    args = parser.parse_args()

    mem = EpisodicMemory()

    if args.store:
        if not args.input or not args.response:
            print("--store requires --input and --response")
        else:
            tags  = [t.strip() for t in args.tags.split(",") if t.strip()]
            ep_id = mem.store(args.input, args.response,
                              score=args.score, topics=tags, session_id=args.session)
            print(f"Episode {ep_id} stored.")

    elif args.recall:
        results = mem.recall(args.recall, k=args.k)
        if not results:
            print("No relevant episodes found.")
        else:
            from datetime import datetime
            print(f"\nTop {len(results)} for: '{args.recall}'\n")
            for ep in results:
                ts = datetime.fromtimestamp(ep["timestamp"]).strftime("%Y-%m-%d %H:%M")
                print(f"  [{ep['id']}] sim={ep['similarity']:.3f}  {ts}  [{ep['valence']}/{ep['intensity']:.1f}]")
                print(f"    Q: {ep['input'][:100]}")
                print(f"    A: {ep['response'][:140]}")
                print()

    elif args.reflect:
        r = mem.reflect(args.reflect, k=args.k)
        print(f"\nNEX reflects:\n\n{r}\n" if r else "No relevant episodes.")

    elif args.report:
        mem.report()

    elif args.prune:
        mem.prune_older_than(args.days)

    else:
        print("Stats:", mem.stats())
        print("\nSmoke test — 2 episodes (skip_valence=True):")
        mem.store("what is consciousness",
                  "Consciousness is the hard problem — qualia resist reduction.",
                  score=0.9, topics=["consciousness", "philosophy"], skip_valence=True)
        mem.store("do you have free will",
                  "Compatibilism is the only coherent position.",
                  score=0.85, topics=["free_will", "philosophy"], skip_valence=True)
        results = mem.recall("consciousness and subjective experience")
        print(f"\nRecall: {len(results)} result(s)")
        for r in results:
            print(f"  [{r['score']}] {r['input']} -> {r['response'][:60]}")
