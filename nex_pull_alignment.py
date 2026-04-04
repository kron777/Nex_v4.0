#!/usr/bin/env python3
"""
nex_pull_alignment.py
Pull Alignment FAISS Retrieval.

Enhances belief retrieval using warmth pull_toward vectors.

Standard FAISS: query embedding -> nearest belief embeddings
Pull alignment: query embedding + pull_toward concepts -> re-ranked beliefs

How it works:
  1. Extract warm words from query
  2. Collect their pull_toward concept lists
  3. Embed the pull concepts as a direction vector
  4. Re-rank FAISS results: beliefs that align with pull direction get boost
  5. Return re-ranked belief IDs

Effect: retrieval steered toward conceptually relevant beliefs,
not just semantically similar ones. A query about "free will"
pulls toward "deliberation", "agency", "causation" — beliefs
about those concepts get surfaced even if lexically distant.
"""
import sqlite3, json, logging
import numpy as np
from pathlib import Path

log     = logging.getLogger("nex.pull_align")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
FMETA   = Path.home() / ".config/nex/nex_beliefs_meta.json"

# Garbage placeholder values from early warming
BAD_PULL = {"str", "concept1", "concept2", "concept3"}

MIN_WARMTH    = 0.40   # minimum warmth to use pull_toward
PULL_WEIGHT   = 0.25   # how much pull alignment affects final score
MIN_PULL_SIM  = 0.30   # minimum cosine similarity to boost


def _load_model():
    if not hasattr(_load_model, "_m"):
        from sentence_transformers import SentenceTransformer
        _load_model._m = SentenceTransformer("all-MiniLM-L6-v2")
    return _load_model._m


def get_pull_concepts(query: str, db) -> list:
    """
    Find warm words in query and collect their pull_toward concepts.
    Returns list of concept strings.
    """
    words = set(query.lower().split())
    concepts = []

    rows = db.execute(
        "SELECT word, pull_toward, w FROM word_tags WHERE w >= ? AND word IN ({})".format(
            ",".join("?" * len(words))
        ),
        [MIN_WARMTH] + list(words)
    ).fetchall()

    for word, pull_json, warmth in rows:
        try:
            pull = json.loads(pull_json or "[]")
            # Filter garbage
            valid = [p for p in pull
                     if isinstance(p, str) and p not in BAD_PULL
                     and len(p) > 2]
            if valid:
                concepts.extend(valid)
                log.debug(f"  {word} (w={warmth:.2f}) -> {valid[:3]}")
        except Exception:
            pass

    return list(set(concepts))


def compute_pull_vector(concepts: list) -> np.ndarray:
    """Embed pull concepts into a direction vector."""
    if not concepts:
        return None
    model = _load_model()
    vecs = model.encode(concepts, normalize_embeddings=True).astype(np.float32)
    pull_vec = vecs.mean(axis=0)
    norm = np.linalg.norm(pull_vec)
    if norm > 0:
        pull_vec = pull_vec / norm
    return pull_vec


def rerank_by_pull(belief_ids: list, belief_vecs: np.ndarray,
                   pull_vec: np.ndarray) -> list:
    """
    Re-rank beliefs by combining original FAISS score with pull alignment.
    belief_ids: list of belief IDs in original rank order
    belief_vecs: corresponding embedding vectors
    pull_vec: pull direction vector
    Returns re-ranked belief IDs.
    """
    if pull_vec is None or len(belief_ids) == 0:
        return belief_ids

    # Compute pull alignment scores
    pull_sims = belief_vecs @ pull_vec  # cosine similarity

    # Combine: original rank score (position-based) + pull alignment
    n = len(belief_ids)
    rank_scores = np.linspace(1.0, 0.0, n)  # 1.0 for first, 0.0 for last

    # Only boost if pull similarity is meaningful
    pull_boost = np.where(pull_sims >= MIN_PULL_SIM,
                          pull_sims * PULL_WEIGHT, 0.0)

    combined = rank_scores + pull_boost

    # Re-rank
    new_order = np.argsort(-combined)
    return [belief_ids[i] for i in new_order]


def pull_aligned_search(query: str, n: int = 8,
                        faiss_index=None, id_map: list = None,
                        db=None) -> list:
    """
    Full pull-aligned retrieval pipeline.
    Returns list of top-n belief IDs, re-ranked by pull alignment.
    """
    import faiss as _faiss

    close_db = False
    if db is None:
        db = sqlite3.connect(str(DB_PATH))
        close_db = True

    # Load FAISS if not provided
    if faiss_index is None:
        fidx_path = Path.home() / ".config/nex/nex_beliefs.faiss"
        faiss_index = _faiss.read_index(str(fidx_path))
    if id_map is None:
        id_map = json.loads(open(FMETA).read())

    model = _load_model()

    # Standard FAISS search — get top 2n candidates
    q_vec = model.encode([query], normalize_embeddings=True).astype(np.float32)
    D, I = faiss_index.search(q_vec, min(n * 2, len(id_map)))

    # Get candidate IDs and their vectors
    candidate_ids = []
    candidate_vecs = []
    for pos in I[0]:
        if pos < 0 or pos >= len(id_map):
            continue
        candidate_ids.append(id_map[pos])
        vec = np.zeros(faiss_index.d, dtype=np.float32)
        faiss_index.reconstruct(int(pos), vec)
        candidate_vecs.append(vec)

    if not candidate_ids:
        if close_db: db.close()
        return []

    candidate_vecs = np.array(candidate_vecs, dtype=np.float32)

    # Get pull concepts from query warm words
    concepts = get_pull_concepts(query, db)
    if close_db: db.close()

    if not concepts:
        # No pull — return standard FAISS order
        return candidate_ids[:n]

    log.debug(f"Pull concepts for [{query}]: {concepts[:5]}")

    # Compute pull direction
    pull_vec = compute_pull_vector(concepts)

    # Re-rank
    reranked = rerank_by_pull(candidate_ids, candidate_vecs, pull_vec)
    return reranked[:n]


def test_pull_alignment(query: str):
    """Test pull alignment on a query — compare standard vs pull-aligned results."""
    import faiss as _faiss
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    fidx  = _faiss.read_index(str(Path.home() / ".config/nex/nex_beliefs.faiss"))
    id_map = json.loads(open(FMETA).read())
    model  = _load_model()

    q_vec = model.encode([query], normalize_embeddings=True).astype(np.float32)
    D, I  = fidx.search(q_vec, 8)

    standard_ids = [id_map[pos] for pos in I[0] if pos >= 0 and pos < len(id_map)]
    pull_ids     = pull_aligned_search(query, n=8, faiss_index=fidx,
                                       id_map=id_map, db=db)

    concepts = get_pull_concepts(query, db)
    print(f"\nQuery: {query}")
    print(f"Pull concepts: {concepts[:5]}")
    print(f"\nStandard FAISS top 5:")
    for bid in standard_ids[:5]:
        row = db.execute("SELECT content, topic FROM beliefs WHERE id=?",
                        (bid,)).fetchone()
        if row:
            print(f"  [{row['topic']}] {row['content'][:70]}")

    print(f"\nPull-aligned top 5:")
    for bid in pull_ids[:5]:
        row = db.execute("SELECT content, topic FROM beliefs WHERE id=?",
                        (bid,)).fetchone()
        if row:
            marker = " *" if bid not in standard_ids[:5] else ""
            print(f"  [{row['topic']}] {row['content'][:70]}{marker}")

    db.close()


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="what is consciousness")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    if args.test:
        test_pull_alignment(args.query)
        test_pull_alignment("do you believe in free will")
        test_pull_alignment("what is truth")
