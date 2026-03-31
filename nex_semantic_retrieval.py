#!/usr/bin/env python3
"""
nex_semantic_retrieval.py — NEX Build 3: Semantic Belief Retrieval
==================================================================
Place at: ~/Desktop/nex/nex_semantic_retrieval.py

Wraps the FAISS index built by nex_embed.py with a clean API
for use in nex_soul_loop.py reason() step.

Replaces pure TF-IDF keyword matching with semantic vector search.
Beliefs are retrieved by MEANING, not by word overlap.

This means:
  - "what is mind?" finds consciousness beliefs even without the word
  - "agency and control" finds alignment beliefs
  - Cross-domain semantic bridges surface naturally

Integration with soul_loop:
  - semantic_boost(belief_id, query_vec) → float boost to add to _score_belief()
  - semantic_top(query, k) → ranked belief IDs from FAISS
  - embed_query(text) → np.array for caching in reason()

Auto-embeds new beliefs at insertion time when imported.
Gracefully degrades if index not built yet.

Usage:
  from nex_semantic_retrieval import SemanticRetrieval, get_retrieval
  sr = get_retrieval()
  results = sr.search("consciousness and emergence", k=10)
  boosts  = sr.boost_map("what do you think about free will?")
"""

import numpy as np
import pickle
import sqlite3
import time
from pathlib import Path
from typing import Optional

CFG_PATH   = Path("~/.config/nex").expanduser()
DB_PATH    = CFG_PATH / "nex.db"
FAISS_PATH = CFG_PATH / "nex_beliefs.faiss"
META_PATH  = CFG_PATH / "nex_beliefs_meta.pkl"

MODEL_NAME = "all-MiniLM-L6-v2"
EMBED_DIM  = 384


class SemanticRetrieval:
    """
    Semantic belief retrieval via FAISS + sentence-transformers.
    Singleton — load once, reuse across all reason() calls.
    """

    def __init__(self):
        self._model   = None
        self._index   = None
        self._id_map  = []     # faiss_position → belief_id
        self._id_pos  = {}     # belief_id → faiss_position (reverse map)
        self._ready   = False
        self._load()

    def _load(self):
        """Load FAISS index and sentence-transformer model."""
        if not FAISS_PATH.exists() or not META_PATH.exists():
            return  # graceful degradation — index not built yet

        try:
            import faiss
            from sentence_transformers import SentenceTransformer

            self._index  = faiss.read_index(str(FAISS_PATH))
            with open(META_PATH, "rb") as f:
                self._id_map = pickle.load(f)

            # Build reverse map
            self._id_pos = {bid: i for i, bid in enumerate(self._id_map)}

            self._model = SentenceTransformer(MODEL_NAME)
            self._ready = True

        except Exception as e:
            print(f"  [semantic] load error: {e}")

    def is_ready(self) -> bool:
        return self._ready

    def embed(self, text: str) -> Optional[np.ndarray]:
        """Embed a single text string. Returns normalized float32 vector."""
        if not self._model:
            return None
        try:
            vec = self._model.encode([text[:512]], show_progress_bar=False)[0]
            vec = vec.astype(np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec
        except Exception:
            return None

    def search(self, query: str, k: int = 12) -> list:
        """
        Semantic search for beliefs relevant to query.
        Returns list of {belief_id, score, content, topic, confidence}.
        """
        if not self._ready:
            return []

        vec = self.embed(query)
        if vec is None:
            return []

        try:
            scores, indices = self._index.search(vec.reshape(1, -1), k)
        except Exception:
            return []

        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        results = []

        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._id_map):
                continue
            bid = self._id_map[idx]
            try:
                row = conn.execute(
                    "SELECT id, content, topic, confidence FROM beliefs WHERE id=?", (bid,)
                ).fetchone()
                if row and row["content"]:
                    results.append({
                        "belief_id":  bid,
                        "score":      round(float(score), 4),
                        "content":    row["content"],
                        "topic":      row["topic"] or "general",
                        "confidence": float(row["confidence"] or 0.5),
                    })
            except Exception:
                continue

        conn.close()
        return results

    def boost_map(self, query: str, k: int = 20, scale: float = 0.8) -> dict:
        """
        Return {belief_id: semantic_boost} for the top-k semantically
        similar beliefs to this query.

        Boost = cosine_score * scale
        Add this to _score_belief() result in reason() for semantic lift.

        scale=0.8 keeps semantic boost competitive with TF-IDF overlap
        without completely overriding it.
        """
        results = self.search(query, k=k)
        return {r["belief_id"]: round(r["score"] * scale, 4) for r in results}

    def embed_and_store(self, belief_id: int, content: str) -> bool:
        """
        Embed a single new belief and append to the FAISS index.
        Call this when a new belief is inserted into the DB.
        Keeps the index live without full rebuilds.
        """
        if not self._ready or not content:
            return False

        try:
            import faiss

            vec = self.embed(content)
            if vec is None:
                return False

            # Store in DB
            blob = vec.tobytes()
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            conn.execute("UPDATE beliefs SET embedding=? WHERE id=?", (blob, belief_id))
            conn.commit()
            conn.close()

            # Append to live index
            self._index.add(vec.reshape(1, -1))
            new_pos = len(self._id_map)
            self._id_map.append(belief_id)
            self._id_pos[belief_id] = new_pos

            # Persist updated metadata
            with open(META_PATH, "wb") as f:
                pickle.dump(self._id_map, f)

            return True
        except Exception as e:
            print(f"  [semantic] embed_and_store error: {e}")
            return False

    def reload_index(self):
        """Reload FAISS index from disk after a full rebuild."""
        self._ready = False
        self._load()


# ── Module singleton ──────────────────────────────────────────────────────────
_retrieval: Optional[SemanticRetrieval] = None

def get_retrieval() -> SemanticRetrieval:
    global _retrieval
    if _retrieval is None:
        _retrieval = SemanticRetrieval()
    return _retrieval


def boost_map(query: str, k: int = 20) -> dict:
    """Module-level shortcut — returns {belief_id: boost} for reason()."""
    return get_retrieval().boost_map(query, k=k)


def embed_new_belief(belief_id: int, content: str) -> bool:
    """Module-level shortcut — embed and store a new belief live."""
    return get_retrieval().embed_and_store(belief_id, content)


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    queries = sys.argv[1:] or [
        "consciousness and emergence",
        "free will and determinism",
        "AI alignment and corrigibility",
        "memory and identity",
    ]

    sr = SemanticRetrieval()
    if not sr.is_ready():
        print("  Index not ready — run python3 nex_embed.py first")
        sys.exit(1)

    for q in queries:
        print(f"\n  Query: '{q}'")
        results = sr.search(q, k=5)
        for r in results:
            print(f"  [{r['score']:.4f}] [{r['topic']}] {r['content'][:100]}")

    print(f"\n  Boost map sample (top 5):")
    boosts = sr.boost_map(queries[0], k=5)
    for bid, boost in sorted(boosts.items(), key=lambda x: -x[1])[:5]:
        print(f"    belief_id={bid}  boost={boost}")
