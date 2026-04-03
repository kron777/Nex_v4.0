"""
nex_graph_reasoner.py
LLM-free reasoning engine for NEX.

Traverses the belief graph to produce reasoning chains without any LLM calls.
Replaces nex_cot_engine.reason() for questions where graph coverage is sufficient.

Architecture:
  query → FAISS → seed beliefs
        → similar edges  → supporting cluster
        → opposes edges  → counterarguments
        → bridge edges   → cross-domain synthesis
        → corroborates   → confidence reinforcement
        → assemble chain from structure

Returns same interface as nex_cot_engine so it can be a drop-in replacement.
"""

import sqlite3, json, logging, time
import numpy as np
from pathlib import Path

log     = logging.getLogger("nex.graph_reasoner")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
FAISS_IDX  = Path.home() / ".config/nex/nex_beliefs.faiss"
FAISS_META = Path.home() / ".config/nex/nex_beliefs_meta.json"

# Minimum graph coverage to trust graph reasoning over LLM
MIN_SEED_BELIEFS    = 3   # need at least 3 FAISS hits
MIN_SUPPORT_BELIEFS = 2   # need at least 2 similar-edge neighbors
CONFIDENCE_FLOOR    = 0.30  # wide net at retrieval; quality filtered at assembly
ASSEMBLY_FLOOR     = 0.50  # minimum confidence for beliefs in final chain

# ── FAISS seed retrieval ──────────────────────────────────────────────────────

def _get_seed_beliefs(question: str, n: int = 6) -> list[dict]:
    """Retrieve seed beliefs via FAISS. Returns list of {id, content, confidence}."""
    try:
        import faiss
        from sentence_transformers import SentenceTransformer

        if not FAISS_IDX.exists():
            return []

        if not hasattr(_get_seed_beliefs, "_model"):
            _get_seed_beliefs._model = SentenceTransformer("all-MiniLM-L6-v2")
            _get_seed_beliefs._index = faiss.read_index(str(FAISS_IDX))
            _get_seed_beliefs._meta  = json.loads(FAISS_META.read_text())

        vec = _get_seed_beliefs._model.encode(
            [question], normalize_embeddings=True).astype(np.float32)
        D, I = _get_seed_beliefs._index.search(vec, n)

        db  = sqlite3.connect(str(DB_PATH))
        out = []
        for dist, pos in zip(D[0], I[0]):
            if pos < 0 or pos >= len(_get_seed_beliefs._meta):
                continue
            bid = _get_seed_beliefs._meta[pos]
            row = db.execute(
                "SELECT id, content, confidence, topic FROM beliefs "
                "WHERE id=? AND confidence>=?",
                (bid, CONFIDENCE_FLOOR)).fetchone()
            if row:
                out.append({
                    "id": row[0], "content": row[1],
                    "confidence": row[2], "topic": row[3],
                    "faiss_dist": float(dist)
                })
        db.close()
        return out
    except Exception as e:
        log.debug(f"FAISS seed failed: {e}")
        return []


# ── Graph traversal ───────────────────────────────────────────────────────────

def _get_neighbors(belief_ids: list[int], edge_type: str,
                   db, limit: int = 3) -> list[dict]:
    """Traverse belief_relations edges of a given type from seed ids."""
    if not belief_ids:
        return []
    placeholders = ",".join("?" * len(belief_ids))
    rows = db.execute(f"""
        SELECT b.id, b.content, b.confidence, br.weight
        FROM belief_relations br
        JOIN beliefs b ON b.id = br.target_id
        WHERE br.source_id IN ({placeholders})
          AND br.relation_type = ?
          AND b.confidence >= ?
          AND b.id NOT IN ({placeholders})
        ORDER BY br.weight DESC
        LIMIT ?
    """, (*belief_ids, edge_type, CONFIDENCE_FLOOR, *belief_ids, limit)).fetchall()
    return [{"id": r[0], "content": r[1],
             "confidence": r[2], "weight": r[3]} for r in rows]


def _get_corroborators(belief_ids: list[int], db, limit: int = 2) -> list[dict]:
    """Find corroborating beliefs via belief_links."""
    if not belief_ids:
        return []
    placeholders = ",".join("?" * len(belief_ids))
    rows = db.execute(f"""
        SELECT b.id, b.content, b.confidence
        FROM belief_links bl
        JOIN beliefs b ON b.id = bl.child_id
        WHERE bl.parent_id IN ({placeholders})
          AND bl.link_type = 'corroborates'
          AND b.confidence >= ?
          AND b.id NOT IN ({placeholders})
        ORDER BY b.confidence DESC
        LIMIT ?
    """, (*belief_ids, CONFIDENCE_FLOOR, *belief_ids, limit)).fetchall()
    return [{"id": r[0], "content": r[1], "confidence": r[2]} for r in rows]


# ── Chain assembly ────────────────────────────────────────────────────────────

def _assemble_chain(question: str, seeds: list, support: list,
                    opposing: list, bridges: list, corroborates: list,
                    warmth_ctx: dict = None, causes: list = None) -> str:
    """
    Assemble a reasoning chain from graph components.
    Produces the same format as nex_cot_engine.reason() output.
    Warmth context boosts hot-word-aligned beliefs to the top.
    No LLM involved.
    """
    hot_words      = (warmth_ctx or {}).get("hot_words", [])
    emotional_reg  = (warmth_ctx or {}).get("emotional_register", 0.0)
    depth_ceiling  = (warmth_ctx or {}).get("depth_ceiling", 3)

    def _warmth_score(b):
        """Boost confidence if belief contains hot words."""
        base = b.get("confidence", 0.0)
        if hot_words and any(w in b["content"].lower() for w in hot_words):
            base = min(1.0, base + 0.10)
        return base

    lines = []

    # 1. Core of the question
    lines.append("1. Core of this question:")
    if seeds:
        good = [s for s in seeds if s["confidence"] >= ASSEMBLY_FLOOR] or seeds
        anchor = max(good, key=_warmth_score)
        lines.append(f"   The question touches on: {anchor['content'][:120]}")
    else:
        lines.append(f"   Directly engaging: {question}")

    # 2. What beliefs directly imply — warmth-sorted
    lines.append("\n2. What my beliefs imply:")
    belief_pool = sorted(seeds + support, key=_warmth_score, reverse=True)
    n_beliefs = 5 if depth_ceiling >= 4 else 4
    if belief_pool:
        for b in belief_pool[:n_beliefs]:
            lines.append(f"   - {b['content'][:120]}")
    else:
        lines.append("   Belief coverage is thin on this topic.")

    # 3. Strongest objection
    lines.append("\n3. Strongest objection:")
    if opposing:
        opp = max(opposing, key=_warmth_score)
        lines.append(f"   Counter-position: {opp['content'][:120]}")
        if corroborates:
            lines.append(f"   Though this is reinforced by: {corroborates[0]['content'][:100]}")
    else:
        lines.append("   No direct opposing belief found — position may be underexamined.")

    # 3b. Causal chain — what leads to what
    if causes:
        lines.append("\n3b. Causal reasoning:")
        for c in causes[:2]:
            lines.append(f"   This leads to: {c['content'][:120]}")

    # 4. Actual position
    lines.append("\n4. My actual position:")
    if bridges:
        bridge = bridges[0]
        lines.append(f"   A cross-domain insight applies: {bridge['content'][:120]}")
    if seeds:
        top = max(seeds, key=_warmth_score)
        lines.append(f"   Core stance: {top['content'][:150]}")

    # 5. Emotional register note (only for high-valence warm questions)
    if emotional_reg and abs(emotional_reg) >= 0.4:
        tone = "with weight" if emotional_reg < 0 else "with openness"
        lines.append(f"\n   [Held {tone} — emotional register: {emotional_reg:+.2f}]")

    return "\n".join(lines)


# ── Coverage check ────────────────────────────────────────────────────────────

def has_sufficient_coverage(question: str) -> dict:
    """
    Check if graph has enough coverage to reason without LLM.
    Returns {sufficient: bool, seeds: int, support: int, opposing: int}.
    Fast — only does FAISS + one DB query.
    """
    seeds = _get_seed_beliefs(question, n=6)
    if len(seeds) < MIN_SEED_BELIEFS:
        return {"sufficient": False, "seeds": len(seeds),
                "support": 0, "opposing": 0}

    seed_ids = [s["id"] for s in seeds]
    db = sqlite3.connect(str(DB_PATH))

    placeholders = ",".join("?" * len(seed_ids))
    support_count = db.execute(f"""
        SELECT COUNT(*) FROM belief_relations
        WHERE source_id IN ({placeholders}) AND relation_type='similar'
    """, seed_ids).fetchone()[0]

    opposing_count = db.execute(f"""
        SELECT COUNT(*) FROM belief_relations
        WHERE source_id IN ({placeholders}) AND relation_type='opposes'
    """, seed_ids).fetchone()[0]

    db.close()

    sufficient = (len(seeds) >= MIN_SEED_BELIEFS and
                  support_count >= MIN_SUPPORT_BELIEFS)

    return {
        "sufficient": sufficient,
        "seeds": len(seeds),
        "support": support_count,
        "opposing": opposing_count
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def reason(question: str, beliefs: list = None,
           warmth_ctx: dict = None) -> str:
    """
    Drop-in replacement for nex_cot_engine.reason().
    Attempts graph reasoning first. Returns empty string if coverage insufficient
    (caller should fall back to LLM reasoning).

    Args:
        question:   The question to reason about
        beliefs:    Optional pre-retrieved beliefs (ignored — we use graph directly)
        warmth_ctx: Optional warmth context from nex_warmth_integrator.pre_process()

    Returns:
        Reasoning chain string, or "" if graph coverage insufficient.
    """
    t0 = time.time()

    # Extract warmth signals
    hot_words     = (warmth_ctx or {}).get("hot_words", [])
    pre_loaded    = (warmth_ctx or {}).get("pre_loaded", {})
    depth_ceiling = (warmth_ctx or {}).get("depth_ceiling", 3)
    hot_ratio     = (warmth_ctx or {}).get("hot_ratio", 0.0)

    # 1. Seed from FAISS — expand n for warm questions
    n_seeds = 8 if hot_ratio >= 0.4 else 6
    seeds = _get_seed_beliefs(question, n=n_seeds)
    if len(seeds) < MIN_SEED_BELIEFS:
        log.debug(f"Graph reasoning: insufficient seeds ({len(seeds)}) for: {question[:50]}")
        return ""

    # Boost seeds that contain hot words
    if hot_words:
        for s in seeds:
            if any(w in s["content"].lower() for w in hot_words):
                s["confidence"] = min(1.0, s["confidence"] + 0.08)
        seeds.sort(key=lambda x: x["confidence"], reverse=True)

    seed_ids = [s["id"] for s in seeds]
    db = sqlite3.connect(str(DB_PATH))

    # 2. Traverse edges — expand limits for deep warm questions
    sup_limit = 6 if depth_ceiling >= 4 else 4
    opp_limit = 3 if hot_ratio >= 0.4 else 2
    support      = _get_neighbors(seed_ids, "similar",  db, limit=sup_limit)
    opposing     = _get_neighbors(seed_ids, "opposes",  db, limit=opp_limit)
    bridges      = _get_neighbors(seed_ids, "bridges",  db, limit=2)
    causes       = _get_neighbors(seed_ids, "causes",   db, limit=3)
    corroborates = _get_corroborators(seed_ids, db, limit=2)

    db.close()

    if len(support) < MIN_SUPPORT_BELIEFS:
        log.debug(f"Graph reasoning: insufficient support ({len(support)}) for: {question[:50]}")
        return ""

    # 3. Assemble chain with warmth context
    chain = _assemble_chain(question, seeds, support, opposing, bridges,
                            corroborates, warmth_ctx=warmth_ctx, causes=causes)

    elapsed = time.time() - t0
    log.info(f"Graph reasoning: {len(seeds)} seeds, {len(support)} support, "
             f"{len(opposing)} opposing, {len(bridges)} bridges — {elapsed:.2f}s")

    return chain


# ── Store reasoning as training pair ─────────────────────────────────────────

def store_graph_reasoning_pair(question: str, reasoning: str, response: str) -> None:
    """Store a graph-reasoned Q→A pair as training data."""
    pair_path = Path.home() / "Desktop/nex/training_data/graph_reasoning_pairs.jsonl"
    pair_path.parent.mkdir(exist_ok=True)
    with open(pair_path, "a") as f:
        f.write(json.dumps({
            "conversations": [
                {"role": "user",      "content": question},
                {"role": "assistant", "content": response}
            ],
            "source":    "graph_reasoner",
            "reasoning": reasoning[:500],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
        }) + "\n")


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--question", "-q",
        default="is consciousness computational or does it require something more")
    parser.add_argument("--coverage", action="store_true",
        help="Just check coverage, don't reason")
    args = parser.parse_args()

    if args.coverage:
        cov = has_sufficient_coverage(args.question)
        print(f"Coverage check: {cov}")
    else:
        print(f"Question: {args.question}\n")
        chain = reason(args.question)
        if chain:
            print("GRAPH REASONING CHAIN (0 LLM calls):")
            print(chain)
        else:
            print("Insufficient graph coverage — would fall back to LLM")
