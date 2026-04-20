#!/usr/bin/env python3
"""
rebuild_faiss.py — full rebuild of the semantic belief index.

Writes ~/.config/nex/nex_beliefs.faiss and nex_beliefs_meta.json
from all beliefs currently in ~/Desktop/nex/nex.db.

Contract (matches 7 live readers: run.py, nex_graph_reasoner,
nex_precognition, nex_activation, nex_pull_alignment,
nex_question_sagas, nex_api):
  - Index: faiss.IndexFlatIP (cosine via normalized inner product)
  - Dim: 384  (SentenceTransformer "all-MiniLM-L6-v2")
  - Meta: list[int] where meta[faiss_position] == belief_id

Motivation: the existing meta contains belief IDs up to 322425 while
current max(id) in beliefs is 268678 — the index references many
rows that have since been deleted. Incremental update isn't safe
with that much drift; a clean atomic rebuild is the right move.

Atomic write: contents land in .tmp files, then os.replace() swaps
them in. Readers using faiss.read_index() / json.loads() always
see a coherent pair (old or new), never a half-written index.

Usage:
  python3 /home/rr/Desktop/nex/rebuild_faiss.py

Does not touch the live brain's DB write path — read-only SELECT
on beliefs. Safe to run while the brain is up.
"""
import os
import json
import sqlite3
import time
from pathlib import Path

import numpy as np


DB_PATH      = Path.home() / "Desktop/nex/nex.db"
CFG_DIR      = Path.home() / ".config/nex"
FAISS_PATH   = CFG_DIR / "nex_beliefs.faiss"
META_PATH    = CFG_DIR / "nex_beliefs_meta.json"
FAISS_TMP    = CFG_DIR / "nex_beliefs.faiss.tmp"
META_TMP     = CFG_DIR / "nex_beliefs_meta.json.tmp"

MODEL_NAME   = "all-MiniLM-L6-v2"
EMBED_DIM    = 384
BATCH_SIZE   = 64
PROGRESS_EVERY = 500


def main() -> int:
    t_start = time.perf_counter()

    # 1. Load beliefs (read-only).
    print(f"[rebuild_faiss] opening {DB_PATH} (read-only)")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT id, content FROM beliefs "
        "WHERE content IS NOT NULL AND LENGTH(content) > 0 "
        "ORDER BY id"
    ).fetchall()
    conn.close()

    belief_ids   = [r[0] for r in rows]
    texts        = [r[1] for r in rows]
    n            = len(belief_ids)
    if n == 0:
        print("[rebuild_faiss] no beliefs with content; aborting")
        return 1
    print(f"[rebuild_faiss] loaded {n} beliefs (ids {belief_ids[0]}..{belief_ids[-1]})")

    # 2. Load embedding model.
    print(f"[rebuild_faiss] loading model: {MODEL_NAME}")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    got_dim = model.get_sentence_embedding_dimension()
    if got_dim != EMBED_DIM:
        print(f"[rebuild_faiss] FATAL: model dim {got_dim} != expected {EMBED_DIM}")
        return 2

    # 3. Encode in batches with L2 normalization (for cosine via IP).
    print(f"[rebuild_faiss] encoding {n} beliefs (batch={BATCH_SIZE}, normalize=True)")
    t_encode = time.perf_counter()
    all_vecs: list[np.ndarray] = []
    for i in range(0, n, BATCH_SIZE):
        chunk = texts[i:i + BATCH_SIZE]
        vecs  = model.encode(
            chunk,
            batch_size=BATCH_SIZE,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype(np.float32)
        all_vecs.append(vecs)
        done = min(i + BATCH_SIZE, n)
        if done % PROGRESS_EVERY < BATCH_SIZE or done == n:
            elapsed = time.perf_counter() - t_encode
            rate = done / elapsed if elapsed > 0 else 0
            print(f"[rebuild_faiss]   {done}/{n} ({rate:.0f}/s)")
    embeddings = np.vstack(all_vecs)
    assert embeddings.shape == (n, EMBED_DIM), \
        f"embeddings shape {embeddings.shape} != ({n}, {EMBED_DIM})"
    print(f"[rebuild_faiss] encode done in {time.perf_counter() - t_encode:.1f}s")

    # 4. Build FAISS index.
    print(f"[rebuild_faiss] building IndexFlatIP({EMBED_DIM})")
    import faiss
    index = faiss.IndexFlatIP(EMBED_DIM)
    index.add(embeddings)
    assert index.ntotal == n, f"index.ntotal {index.ntotal} != {n}"

    # 5. Atomic write: .tmp first, then rename.
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[rebuild_faiss] writing {FAISS_TMP}")
    faiss.write_index(index, str(FAISS_TMP))
    print(f"[rebuild_faiss] writing {META_TMP}")
    META_TMP.write_text(json.dumps(belief_ids))

    # Atomic rename — readers never see a half-written pair.
    os.replace(FAISS_TMP, FAISS_PATH)
    os.replace(META_TMP, META_PATH)

    # 6. Summary.
    faiss_size = FAISS_PATH.stat().st_size
    meta_size  = META_PATH.stat().st_size
    total_elapsed = time.perf_counter() - t_start
    print(
        f"[rebuild_faiss] DONE — {n} beliefs indexed in "
        f"{total_elapsed:.1f}s (faiss={faiss_size:,}B, meta={meta_size:,}B)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
