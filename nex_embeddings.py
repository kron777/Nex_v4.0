"""
nex_embeddings.py  —  Embedding Pipeline
================================================================
NEX v1.0 — Build 2

Embeds all beliefs using sentence-transformers all-MiniLM-L6-v2
and builds a FAISS index for fast semantic search.

Usage:
    # First run — embed all existing beliefs + save index:
    python3 nex_embeddings.py --init

    # Embed any beliefs missing embeddings (run after new beliefs added):
    python3 nex_embeddings.py --update

    # Query test — find beliefs nearest to a string:
    python3 nex_embeddings.py --query "machine learning and consciousness"

    # From other modules — import and use:
    from nex_embeddings import EmbeddingEngine
    engine = EmbeddingEngine()
    results = engine.search("neural plasticity", k=5)
"""

import argparse
import json
import logging
import os
import pickle
import sqlite3
import struct
import time

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("nex.embeddings")

DB_PATH      = os.path.expanduser("~/.config/nex/nex.db")
INDEX_PATH   = os.path.expanduser("~/.config/nex/belief_faiss.index")
ID_MAP_PATH  = os.path.expanduser("~/.config/nex/belief_id_map.json")
MODEL_NAME   = "all-MiniLM-L6-v2"
EMBED_DIM    = 384  # all-MiniLM-L6-v2 output dimension


# =============================================================================
# Lazy imports — fail clearly if not installed
# =============================================================================

def _load_deps():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise SystemExit(
            "[!] sentence-transformers not installed.\n"
            "    pip install sentence-transformers --break-system-packages"
        )
    try:
        import faiss
    except ImportError:
        raise SystemExit(
            "[!] faiss not installed.\n"
            "    pip install faiss-cpu --break-system-packages"
        )
    return SentenceTransformer, faiss


# =============================================================================
# Helpers
# =============================================================================

def _blob_to_vec(blob: bytes) -> np.ndarray:
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def _vec_to_blob(vec: np.ndarray) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec.astype(np.float32))


def _db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# =============================================================================
# EmbeddingEngine
# =============================================================================

class EmbeddingEngine:
    """
    Central embedding + search interface for NEX v1.0.

    Loads the FAISS index from disk on init. If index doesn't exist,
    call build_index() first (or run this script with --init).
    """

    def __init__(self):
        SentenceTransformer, self._faiss = _load_deps()
        log.info(f"Loading model: {MODEL_NAME}")
        self._model = SentenceTransformer(MODEL_NAME)
        self._index = None
        self._id_map = []   # list of belief DB ids, position = faiss index position
        self._load_index()

    # ── Index persistence ────────────────────────────────────────────────────

    def _load_index(self):
        if os.path.exists(INDEX_PATH) and os.path.exists(ID_MAP_PATH):
            log.info("Loading FAISS index from disk ...")
            self._index = self._faiss.read_index(INDEX_PATH)
            with open(ID_MAP_PATH) as f:
                self._id_map = json.load(f)
            log.info(f"Index loaded — {self._index.ntotal} vectors, {len(self._id_map)} beliefs mapped")
        else:
            log.info("No index found on disk — run --init to build it")

    def _save_index(self):
        self._faiss.write_index(self._index, INDEX_PATH)
        with open(ID_MAP_PATH, "w") as f:
            json.dump(self._id_map, f)
        log.info(f"Index saved → {INDEX_PATH}")

    # ── Embedding ────────────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed a list of strings → float32 numpy array (N, 384)."""
        vecs = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,   # cosine similarity via dot product
            show_progress_bar=len(texts) > 20,
        )
        return vecs.astype(np.float32)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    # ── Build / update index ─────────────────────────────────────────────────

    def build_index(self):
        """
        Embed ALL beliefs in DB (with or without existing embeddings).
        Stores embeddings back to DB. Builds fresh FAISS index.
        """
        con = _db_connect()
        rows = con.execute(
            "SELECT id, content FROM beliefs ORDER BY id"
        ).fetchall()

        if not rows:
            log.warning("No beliefs in DB — nothing to embed")
            return

        log.info(f"Embedding {len(rows)} beliefs ...")
        ids      = [r["id"] for r in rows]
        contents = [r["content"] for r in rows]

        t0   = time.time()
        vecs = self.embed(contents)
        log.info(f"Embedded in {time.time()-t0:.1f}s")

        # Write embeddings back to DB
        cur = con.cursor()
        for belief_id, vec in zip(ids, vecs):
            cur.execute(
                "UPDATE beliefs SET embedding = ? WHERE id = ?",
                (_vec_to_blob(vec), belief_id)
            )
        con.commit()
        con.close()
        log.info("Embeddings written to DB")

        # Build FAISS flat index (exact cosine via inner product on normalised vecs)
        self._index  = self._faiss.IndexFlatIP(EMBED_DIM)
        self._id_map = ids
        self._index.add(vecs)
        self._save_index()
        log.info(f"FAISS index built — {self._index.ntotal} vectors")

    def update_index(self):
        """
        Embed only beliefs that are missing embeddings.
        Adds them to the existing index without rebuilding from scratch.
        """
        if self._index is None:
            log.warning("No index loaded — running full build instead")
            self.build_index()
            return

        con = _db_connect()
        rows = con.execute(
            "SELECT id, content FROM beliefs WHERE embedding IS NULL ORDER BY id"
        ).fetchall()

        if not rows:
            log.info("All beliefs already embedded — nothing to do")
            return

        log.info(f"Embedding {len(rows)} new beliefs ...")
        ids      = [r["id"] for r in rows]
        contents = [r["content"] for r in rows]
        vecs     = self.embed(contents)

        cur = con.cursor()
        for belief_id, vec in zip(ids, vecs):
            cur.execute(
                "UPDATE beliefs SET embedding = ? WHERE id = ?",
                (_vec_to_blob(vec), belief_id)
            )
        con.commit()
        con.close()

        self._index.add(vecs)
        self._id_map.extend(ids)
        self._save_index()
        log.info(f"Added {len(ids)} new vectors — index now has {self._index.ntotal}")

    # ── Search ───────────────────────────────────────────────────────────────

    def search(self, query: str, k: int = 5) -> list[dict]:
        """
        Semantic search over all beliefs.

        Returns list of dicts:
            [{"id": int, "content": str, "topic": str, "score": float}, ...]
        Sorted by similarity descending.
        """
        if self._index is None or self._index.ntotal == 0:
            log.warning("Index empty — run --init first")
            return []

        q_vec = self.embed_one(query).reshape(1, -1)
        scores, positions = self._index.search(q_vec, min(k, self._index.ntotal))

        belief_ids = [self._id_map[p] for p in positions[0] if p >= 0]
        if not belief_ids:
            return []

        con  = _db_connect()
        ph   = ",".join("?" * len(belief_ids))
        rows = con.execute(
            f"SELECT id, content, topic, confidence FROM beliefs WHERE id IN ({ph})",
            belief_ids
        ).fetchall()
        con.close()

        # Map scores back
        score_map = {self._id_map[p]: float(s)
                     for p, s in zip(positions[0], scores[0]) if p >= 0}
        results = [
            {
                "id":         r["id"],
                "content":    r["content"],
                "topic":      r["topic"],
                "confidence": r["confidence"],
                "score":      score_map.get(r["id"], 0.0),
            }
            for r in rows
        ]
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def search_by_vec(self, vec: np.ndarray, k: int = 5,
                      exclude_ids: list[int] | None = None) -> list[dict]:
        """
        Search by raw embedding vector. Used internally by relation classifier
        and bridge detector. Optionally exclude specific belief IDs.
        """
        if self._index is None or self._index.ntotal == 0:
            return []

        vec = vec.reshape(1, -1)
        # Fetch more than k to allow filtering
        fetch_k = min(k + len(exclude_ids or []) + 5, self._index.ntotal)
        scores, positions = self._index.search(vec, fetch_k)

        exclude = set(exclude_ids or [])
        results = []
        con = _db_connect()
        for pos, score in zip(positions[0], scores[0]):
            if pos < 0:
                continue
            bid = self._id_map[pos]
            if bid in exclude:
                continue
            row = con.execute(
                "SELECT id, content, topic, confidence FROM beliefs WHERE id = ?",
                (bid,)
            ).fetchone()
            if row:
                results.append({
                    "id":         row["id"],
                    "content":    row["content"],
                    "topic":      row["topic"],
                    "confidence": row["confidence"],
                    "score":      float(score),
                })
            if len(results) >= k:
                break
        con.close()
        return results

    # ── Utility ──────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        con = _db_connect()
        total    = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        embedded = con.execute(
            "SELECT COUNT(*) FROM beliefs WHERE embedding IS NOT NULL"
        ).fetchone()[0]
        con.close()
        index_size = self._index.ntotal if self._index else 0
        return {
            "beliefs_total":    total,
            "beliefs_embedded": embedded,
            "beliefs_missing":  total - embedded,
            "index_vectors":    index_size,
        }


# =============================================================================
# CLI
# =============================================================================

def main():
    ap = argparse.ArgumentParser(description="NEX v1.0 — Embedding Pipeline (Build 2)")
    ap.add_argument("--init",   action="store_true", help="Embed all beliefs + build FAISS index")
    ap.add_argument("--update", action="store_true", help="Embed only beliefs missing embeddings")
    ap.add_argument("--query",  type=str,            help="Test semantic search with a query string")
    ap.add_argument("--stats",  action="store_true", help="Show embedding coverage stats")
    ap.add_argument("-k",       type=int, default=5, help="Results to return for --query (default 5)")
    args = ap.parse_args()

    engine = EmbeddingEngine()

    if args.stats or not any([args.init, args.update, args.query]):
        s = engine.stats()
        print(f"\nEmbedding coverage:")
        print(f"  Beliefs total:    {s['beliefs_total']}")
        print(f"  Embedded:         {s['beliefs_embedded']}")
        print(f"  Missing:          {s['beliefs_missing']}")
        print(f"  FAISS vectors:    {s['index_vectors']}")
        if s["beliefs_missing"] > 0:
            print(f"\n  Run --update to embed the {s['beliefs_missing']} missing beliefs.")
        return

    if args.init:
        engine.build_index()
        s = engine.stats()
        print(f"\n[✓] Build 2 complete.")
        print(f"    {s['beliefs_embedded']} beliefs embedded.")
        print(f"    FAISS index: {INDEX_PATH}")
        print(f"    ID map:      {ID_MAP_PATH}")
        print(f"\nNext step: Build 3 — implement nex_nlp_pipeline.py")

    if args.update:
        engine.update_index()

    if args.query:
        print(f"\nSearching: '{args.query}' (k={args.k})\n")
        results = engine.search(args.query, k=args.k)
        if not results:
            print("  No results.")
        for i, r in enumerate(results, 1):
            print(f"  {i}. [{r['score']:.3f}] (topic: {r['topic'] or 'none'}) {r['content'][:120]}")


if __name__ == "__main__":
    main()
