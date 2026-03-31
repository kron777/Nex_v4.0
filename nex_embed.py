#!/usr/bin/env python3
"""
nex_embed.py — NEX Build 2: Embedding Pipeline
===============================================
Place at: ~/Desktop/nex/nex_embed.py

Embeds all beliefs using all-MiniLM-L6-v2 (CPU, fast, ~80MB).
Stores embeddings as BLOBs in beliefs.embedding column.
Builds FAISS index and saves to ~/.config/nex/nex_beliefs.faiss

This is the foundation of everything downstream:
  - Semantic belief retrieval (replaces TF-IDF in soul_loop)
  - LLM-free relation mapping (Build 3)
  - Bridge detector (Build 9)
  - Native opinions engine (Build 4)

Usage:
  python3 nex_embed.py              # embed all, build index
  python3 nex_embed.py --check      # show embedding coverage only
  python3 nex_embed.py --index-only # rebuild FAISS from existing embeddings
  python3 nex_embed.py --test "consciousness and emergence"
"""

import sqlite3
import numpy as np
import pickle
import struct
import time
import sys
import argparse
from pathlib import Path

CFG_PATH   = Path("~/.config/nex").expanduser()
DB_PATH    = CFG_PATH / "nex.db"
FAISS_PATH = CFG_PATH / "nex_beliefs.faiss"
META_PATH  = CFG_PATH / "nex_beliefs_meta.pkl"   # belief_id → faiss index mapping

BATCH_SIZE   = 128    # beliefs per embedding batch
MODEL_NAME   = "all-MiniLM-L6-v2"
EMBED_DIM    = 384    # all-MiniLM-L6-v2 output dimension


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def load_model():
    print(f"  Loading {MODEL_NAME}...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    print(f"  Model loaded.")
    return model


def embed_all(model, force: bool = False):
    """
    Embed all beliefs missing embeddings.
    Saves embedding BLOBs directly to DB.
    Returns count of beliefs embedded.
    """
    conn = _db()

    if force:
        rows = conn.execute(
            "SELECT id, content FROM beliefs WHERE content IS NOT NULL AND length(content) > 10"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content FROM beliefs "
            "WHERE embedding IS NULL AND content IS NOT NULL AND length(content) > 10"
        ).fetchall()

    if not rows:
        print("  All beliefs already embedded.")
        conn.close()
        return 0

    print(f"  Embedding {len(rows)} beliefs in batches of {BATCH_SIZE}...")
    total = len(rows)
    embedded = 0
    t0 = time.time()

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        texts = [r["content"][:512] for r in batch]  # truncate long beliefs
        ids   = [r["id"] for r in batch]

        vecs = model.encode(texts, show_progress_bar=False, batch_size=BATCH_SIZE)

        updates = []
        for bid, vec in zip(ids, vecs):
            blob = vec.astype(np.float32).tobytes()
            updates.append((blob, bid))

        conn.executemany("UPDATE beliefs SET embedding=? WHERE id=?", updates)
        conn.commit()

        embedded += len(batch)
        elapsed  = time.time() - t0
        rate     = embedded / elapsed
        eta      = (total - embedded) / rate if rate > 0 else 0
        print(f"  [{embedded}/{total}] {rate:.0f} beliefs/sec  ETA {eta:.0f}s", end="\r")

    print(f"\n  Embedded {embedded} beliefs in {time.time()-t0:.1f}s")
    conn.close()
    return embedded


def build_faiss_index():
    """
    Build FAISS flat L2 index from all embedded beliefs.
    Saves index + belief_id mapping to disk.
    Returns (index, id_map) where id_map[faiss_idx] = belief_id
    """
    try:
        import faiss
    except ImportError:
        print("  faiss not installed — installing...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "faiss-cpu", "--quiet"], check=True)
        import faiss

    conn = _db()
    rows = conn.execute(
        "SELECT id, embedding FROM beliefs WHERE embedding IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        print("  No embeddings found — run embed_all first")
        return None, []

    print(f"  Building FAISS index over {len(rows)} beliefs...")

    id_map = []
    vecs   = []
    for row in rows:
        blob = row["embedding"]
        vec  = np.frombuffer(blob, dtype=np.float32)
        if vec.shape[0] == EMBED_DIM:
            id_map.append(row["id"])
            vecs.append(vec)

    matrix = np.stack(vecs).astype(np.float32)

    # Normalize for cosine similarity via inner product
    norms  = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    matrix = matrix / norms

    index = faiss.IndexFlatIP(EMBED_DIM)   # Inner Product = cosine on normalized vecs
    index.add(matrix)

    # Save
    faiss.write_index(index, str(FAISS_PATH))
    with open(META_PATH, "wb") as f:
        pickle.dump(id_map, f)

    print(f"  FAISS index: {index.ntotal} vectors → {FAISS_PATH}")
    print(f"  ID map:      {len(id_map)} entries → {META_PATH}")
    return index, id_map


def semantic_search(query: str, k: int = 10, model=None) -> list:
    """
    Search beliefs by semantic similarity to query.
    Returns list of {belief_id, score, content, topic}.
    """
    try:
        import faiss
    except ImportError:
        return []

    if not FAISS_PATH.exists() or not META_PATH.exists():
        print("  FAISS index not found — run nex_embed.py first")
        return []

    if model is None:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(MODEL_NAME)

    index = faiss.read_index(str(FAISS_PATH))
    with open(META_PATH, "rb") as f:
        id_map = pickle.load(f)

    # Embed query
    vec = model.encode([query], show_progress_bar=False)[0].astype(np.float32)
    vec = vec / (np.linalg.norm(vec) or 1.0)
    vec = vec.reshape(1, -1)

    scores, indices = index.search(vec, k)

    # Fetch belief content
    conn = _db()
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(id_map):
            continue
        bid = id_map[idx]
        row = conn.execute(
            "SELECT id, content, topic, confidence FROM beliefs WHERE id=?", (bid,)
        ).fetchone()
        if row:
            results.append({
                "belief_id": bid,
                "score":     round(float(score), 4),
                "content":   row["content"],
                "topic":     row["topic"] or "general",
                "confidence": row["confidence"],
            })
    conn.close()
    return results


def coverage_report():
    """Print embedding coverage stats."""
    conn = _db()
    total   = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    has_emb = conn.execute("SELECT COUNT(*) FROM beliefs WHERE embedding IS NOT NULL").fetchone()[0]
    conn.close()
    print(f"\n  Embedding coverage: {has_emb}/{total} ({100*has_emb//total if total else 0}%)")
    if FAISS_PATH.exists():
        size_mb = round(FAISS_PATH.stat().st_size / 1024 / 1024, 1)
        print(f"  FAISS index:        {FAISS_PATH} ({size_mb} MB)")
    else:
        print(f"  FAISS index:        not built yet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check",      action="store_true", help="Coverage report only")
    parser.add_argument("--index-only", action="store_true", help="Rebuild FAISS from existing embeddings")
    parser.add_argument("--force",      action="store_true", help="Re-embed all beliefs")
    parser.add_argument("--test",       type=str, default=None, help="Test semantic search query")
    args = parser.parse_args()

    if args.check:
        coverage_report()
        sys.exit(0)

    if args.test:
        print(f"\n  Semantic search: '{args.test}'")
        results = semantic_search(args.test, k=8)
        for r in results:
            print(f"\n  [{r['score']:.4f}] {r['topic']}")
            print(f"  {r['content'][:120]}")
        sys.exit(0)

    if args.index_only:
        build_faiss_index()
        sys.exit(0)

    # Full run: embed → index
    print(f"\n  NEX Build 2 — Embedding Pipeline")
    print(f"  {'─'*45}")
    coverage_report()

    model = load_model()

    n = embed_all(model, force=args.force)
    if n > 0 or args.force:
        build_faiss_index()
    elif not FAISS_PATH.exists():
        build_faiss_index()

    print(f"\n  Done.")
    coverage_report()
