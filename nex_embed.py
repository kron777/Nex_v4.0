#!/usr/bin/env python3
"""
nex_embed.py — NEX Build 2: Embedding Pipeline
===============================================
Place at: ~/Desktop/nex/nex_embed.py

Embeds all beliefs in nex.db using all-MiniLM-L6-v2,
stores embeddings as BLOBs in the beliefs table,
and builds a FAISS index for semantic search.

Run once, then nex_bridge_detector and nex_semantic_retrieval
will use the index automatically.

Usage:
    python3 nex_embed.py              # embed all unembedded beliefs
    python3 nex_embed.py --rebuild    # rebuild entire index from scratch
    python3 nex_embed.py --index-only # just rebuild FAISS from existing BLOBs
"""

import sys
import time
import struct
import sqlite3
import argparse
import numpy as np
from pathlib import Path

NEX_DIR   = Path("/home/rr/Desktop/nex")
DB_PATH   = NEX_DIR / "nex.db"
CFG_PATH  = Path("~/.config/nex").expanduser()
FAISS_PATH = CFG_PATH / "nex_beliefs.faiss"
META_PATH  = CFG_PATH / "nex_beliefs_meta.json"

BATCH_SIZE  = 256   # beliefs per embedding batch
MODEL_NAME  = "all-MiniLM-L6-v2"
DIM         = 384   # embedding dimensions for MiniLM


def _get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_embedding_column():
    """Add embedding column to beliefs table if missing."""
    conn = _get_db()
    try:
        conn.execute("ALTER TABLE beliefs ADD COLUMN embedding BLOB")
        conn.commit()
        print("  Added embedding column to beliefs table")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.close()


def _vec_to_blob(vec: np.ndarray) -> bytes:
    return vec.astype(np.float32).tobytes()


def _blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def embed_beliefs(rebuild: bool = False):
    """
    Embed all beliefs without embeddings (or all, if rebuild=True).
    Stores as BLOB in beliefs.embedding column.
    """
    from sentence_transformers import SentenceTransformer

    print(f"  Loading model: {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)
    print(f"  Model loaded.")

    conn = _get_db()

    if rebuild:
        print("  Rebuild mode — clearing existing embeddings...")
        conn.execute("UPDATE beliefs SET embedding = NULL")
        conn.commit()

    # Count unembedded
    total = conn.execute(
        "SELECT COUNT(*) FROM beliefs WHERE embedding IS NULL AND content IS NOT NULL"
    ).fetchone()[0]
    print(f"  Beliefs to embed: {total:,}")

    if total == 0:
        print("  All beliefs already embedded.")
        conn.close()
        return

    embedded = 0
    start    = time.time()

    while True:
        rows = conn.execute(
            "SELECT id, content FROM beliefs "
            "WHERE embedding IS NULL AND content IS NOT NULL "
            "LIMIT ?",
            (BATCH_SIZE,)
        ).fetchall()

        if not rows:
            break

        ids      = [r["id"] for r in rows]
        contents = [r["content"][:512] for r in rows]  # truncate for speed

        vecs = model.encode(
            contents,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True,
        )

        for bid, vec in zip(ids, vecs):
            blob = _vec_to_blob(vec)
            conn.execute(
                "UPDATE beliefs SET embedding = ? WHERE id = ?",
                (blob, bid)
            )

        conn.commit()
        embedded += len(rows)

        elapsed  = time.time() - start
        rate     = embedded / elapsed if elapsed > 0 else 0
        remaining = (total - embedded) / rate if rate > 0 else 0

        print(
            f"  [{embedded:,}/{total:,}] "
            f"{rate:.0f}/s — "
            f"~{remaining/60:.1f}min remaining",
            end="\r"
        )

    print(f"\n  Embedded {embedded:,} beliefs in {time.time()-start:.1f}s")
    conn.close()


def build_faiss_index():
    """
    Build FAISS index from all embedded beliefs.
    Saves to ~/.config/nex/nex_beliefs.faiss
    """
    import faiss
    import json

    print("  Building FAISS index...")
    conn = _get_db()

    rows = conn.execute(
        "SELECT id, embedding FROM beliefs "
        "WHERE embedding IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        print("  No embeddings found — run embed_beliefs first")
        return

    print(f"  Loading {len(rows):,} embeddings...")
    ids  = []
    vecs = []
    for row in rows:
        try:
            vec = _blob_to_vec(row["embedding"])
            if len(vec) == DIM:
                ids.append(row["id"])
                vecs.append(vec)
        except Exception:
            continue

    if not vecs:
        print("  No valid embeddings found")
        return

    matrix = np.array(vecs, dtype=np.float32)
    print(f"  Matrix shape: {matrix.shape}")

    # Build flat L2 index (exact search — upgrade to IVF for >1M beliefs)
    index = faiss.IndexFlatIP(DIM)   # Inner product = cosine on normalized vecs
    index.add(matrix)

    CFG_PATH.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(FAISS_PATH))

    # Save ID map
    import json
    with open(META_PATH, 'w') as f:
        json.dump(ids, f)

    print(f"  FAISS index saved: {FAISS_PATH}")
    print(f"  ID map saved:      {META_PATH}")
    print(f"  Index size:        {index.ntotal:,} vectors")


def search(query: str, k: int = 10):
    """
    Semantic search — find k most similar beliefs to query.
    Used to test the index after building.
    """
    import faiss
    import json
    from sentence_transformers import SentenceTransformer

    if not FAISS_PATH.exists():
        print("  No FAISS index found — run build first")
        return

    model = SentenceTransformer(MODEL_NAME)
    vec   = model.encode([query], normalize_embeddings=True).astype(np.float32)

    index  = faiss.read_index(str(FAISS_PATH))
    with open(META_PATH) as f:
        id_map = json.load(f)

    distances, indices = index.search(vec, k)

    conn = _get_db()
    print(f"\n  Top {k} results for: '{query}'\n")
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0:
            continue
        bid = id_map[idx]
        row = conn.execute(
            "SELECT content, topic, confidence FROM beliefs WHERE id=?", (bid,)
        ).fetchone()
        if row:
            print(f"  [{row['topic']}|{row['confidence']:.2f}|sim={dist:.3f}]")
            print(f"  {row['content'][:120]}")
            print()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NEX Embedding Pipeline — Build 2")
    parser.add_argument("--rebuild",    action="store_true", help="Re-embed all beliefs")
    parser.add_argument("--index-only", action="store_true", help="Just rebuild FAISS index")
    parser.add_argument("--search",     type=str, default="", help="Test search query")
    parser.add_argument("--k",          type=int, default=10,  help="Search results count")
    args = parser.parse_args()

    print("\n  NEX Embedding Pipeline — Build 2")
    print("  " + "─"*50)

    if args.search:
        search(args.search, k=args.k)
        sys.exit(0)

    _ensure_embedding_column()

    if not args.index_only:
        embed_beliefs(rebuild=args.rebuild)

    build_faiss_index()

    print("\n  Build 2 complete.")
    print(f"  FAISS index: {FAISS_PATH}")
    print(f"  Run test:    python3 nex_embed.py --search 'consciousness and computation'")
