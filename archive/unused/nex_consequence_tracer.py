#!/usr/bin/env python3
"""
nex_consequence_tracer.py
Consequence Tracing Engine — Step 1 toward world model.

NEX holds beliefs. Beliefs have causal consequences.
Consequences should be consistent with other held beliefs.
When they aren't — that's a detected contradiction in NEX's reasoning.

This module:
  1. Takes a seed belief
  2. Traces its causal chain (what must follow if this is true)
  3. Checks each consequence against existing beliefs
  4. Flags: CONSISTENT / CONTRADICTS / NOVEL

CONSISTENT: consequence already held as belief — reinforces confidence
CONTRADICTS: consequence conflicts with held belief — epistemic tension
NOVEL: consequence not yet in belief graph — candidate for new belief

Novel consequences get proposed for belief graph insertion.
Contradictions get flagged for dialectical synthesis resolution.
Consistent consequences boost confidence of the chain.

Runs nightly on high-confidence causal chains.
Feeds into: nex_dialectical_synthesis.py (contradictions)
            nex_belief_synthesis.py (novel consequences)
"""
import sqlite3, json, re, logging, time
from pathlib import Path
from collections import defaultdict

log     = logging.getLogger("nex.consequence")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"

MIN_CHAIN_CONF    = 0.75  # minimum confidence for chain beliefs
MIN_SIMILARITY    = 0.72  # cosine similarity to call something "consistent"
MIN_CONTRADICTION = 0.30  # cosine similarity below this = contradiction
NOVEL_THRESHOLD   = 0.55  # between contradiction and consistent = novel


def _load_model():
    if not hasattr(_load_model, "_m"):
        from sentence_transformers import SentenceTransformer
        _load_model._m = SentenceTransformer("all-MiniLM-L6-v2")
    return _load_model._m


def _embed(texts: list) -> "np.ndarray":
    import numpy as np
    model = _load_model()
    return model.encode(texts, normalize_embeddings=True).astype("float32")


def get_all_causal_chains(db, max_chains=50) -> list:
    """Get high-confidence causal chains from the belief graph."""
    import sys
    sys.path.insert(0, str(NEX_DIR))
    from nex_causal_engine import CausalEngine

    ce = CausalEngine()
    sources = db.execute("""SELECT DISTINCT b.id, b.content, b.topic, b.confidence
        FROM belief_relations br
        JOIN beliefs b ON br.source_id = b.id
        WHERE br.relation_type = 'causes'
        AND b.confidence >= ?
        ORDER BY b.confidence DESC LIMIT 20""",
        (MIN_CHAIN_CONF,)).fetchall()

    all_chains = []
    for row in sources:
        chains = ce.causal_chain(
            row["id"], max_depth=3, relation_types=("causes",))
        for chain in chains:
            if len(chain.get("beliefs", [])) >= 2:
                all_chains.append(chain)
        if len(all_chains) >= max_chains:
            break

    return all_chains[:max_chains]


def check_consequence(consequence: dict, db) -> dict:
    """
    Check a consequence belief against the existing belief graph.
    Returns: {status, matched_belief, similarity, content}

    Status:
      CONSISTENT   - already held, same position
      CONTRADICTS  - held belief with opposing position
      NOVEL        - not yet in graph, worth adding
    """
    import numpy as np, faiss
    from pathlib import Path

    content = consequence.get("content", "")
    if not content or len(content.split()) < 5:
        return {"status": "SKIP", "content": content}

    # Embed the consequence
    c_vec = _embed([content])[0]

    # Load FAISS for fast similarity search
    fidx  = faiss.read_index(str(
        Path.home() / ".config/nex/nex_beliefs.faiss"))
    id_map = json.loads(open(
        Path.home() / ".config/nex/nex_beliefs_meta.json").read())

    D, I = fidx.search(c_vec.reshape(1, -1), 5)

    best_sim     = 0.0
    best_content = ""
    best_id      = None

    for pos, sim in zip(I[0], D[0]):
        if pos < 0 or pos >= len(id_map):
            continue
        bid = id_map[pos]
        if bid == consequence.get("id"):
            continue  # skip self
        row = db.execute(
            "SELECT content FROM beliefs WHERE id=?", (bid,)).fetchone()
        if row and sim > best_sim:
            best_sim     = float(sim)
            best_content = row[0]
            best_id      = bid

    if best_sim >= MIN_SIMILARITY:
        status = "CONSISTENT"
    elif best_sim <= MIN_CONTRADICTION:
        status = "NOVEL"
    else:
        # Check if semantically opposing
        # Simple heuristic: negation words in one but not other
        neg_words = {"not", "no", "never", "cannot", "impossible",
                     "without", "reject", "deny", "against"}
        c_negs = len(neg_words & set(content.lower().split()))
        b_negs = len(neg_words & set(best_content.lower().split()))
        if abs(c_negs - b_negs) >= 2:
            status = "CONTRADICTS"
        else:
            status = "NOVEL"

    return {
        "status":        status,
        "content":       content,
        "matched_id":    best_id,
        "matched":       best_content[:100],
        "similarity":    round(best_sim, 3),
    }


def trace_chain(chain: dict, db) -> dict:
    """
    Trace a full causal chain and check each step.
    Returns chain analysis with consistency scores.
    """
    beliefs = chain.get("beliefs", [])
    if len(beliefs) < 2:
        return {}

    seed     = beliefs[0]
    steps    = beliefs[1:]
    results  = []
    consistent = contradicts = novel = 0

    for step in steps:
        check = check_consequence(step, db)
        results.append(check)
        if check["status"] == "CONSISTENT":
            consistent += 1
        elif check["status"] == "CONTRADICTS":
            contradicts += 1
        elif check["status"] == "NOVEL":
            novel += 1

    coherence = consistent / max(len(steps), 1)

    return {
        "seed":        seed.get("content","")[:100],
        "seed_id":     seed.get("id"),
        "seed_topic":  seed.get("topic",""),
        "chain_len":   len(beliefs),
        "consistent":  consistent,
        "contradicts": contradicts,
        "novel":       novel,
        "coherence":   round(coherence, 3),
        "steps":       results,
    }


def propose_novel_beliefs(chain_results: list, db) -> list:
    """
    Extract novel consequences from chain analysis.
    These are consequences that follow logically but aren't yet held.
    """
    proposals = []
    for chain in chain_results:
        for step in chain.get("steps", []):
            if step.get("status") == "NOVEL":
                content = step.get("content","")
                if content and len(content.split()) >= 12:
                    proposals.append({
                        "content":     content,
                        "source_chain": chain["seed"][:60],
                        "topic":       chain["seed_topic"],
                        "confidence":  0.68,
                    })
    return proposals


def store_novel_beliefs(proposals: list, db, dry_run=False) -> int:
    """Store novel consequence beliefs in the graph."""
    stored = 0
    for p in proposals:
        if dry_run:
            continue
        try:
            now = time.strftime("%Y-%m-%dT%H:%M:%S")
            db.execute("""INSERT INTO beliefs
                (content, topic, confidence, source, belief_type, created_at)
                VALUES (?,?,?,?,?,?)""", (
                p["content"][:300],
                p["topic"],
                p["confidence"],
                f"consequence:{p['source_chain'][:40]}",
                "inference",
                now,
            ))
            stored += 1
        except Exception as e:
            log.debug(f"Store failed: {e}")
    if not dry_run:
        db.commit()
    return stored


def flag_contradictions(chain_results: list) -> list:
    """Extract contradictions for dialectical synthesis."""
    contradictions = []
    for chain in chain_results:
        if chain.get("contradicts", 0) > 0:
            for step in chain.get("steps", []):
                if step.get("status") == "CONTRADICTS":
                    contradictions.append({
                        "chain_seed":   chain["seed"][:80],
                        "consequence":  step["content"][:80],
                        "conflicts_with": step["matched"][:80],
                        "similarity":   step["similarity"],
                    })
    return contradictions


def run_consequence_trace(dry_run=False, max_chains=20) -> dict:
    """Main consequence tracing run."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    print("\nNEX CONSEQUENCE TRACER")
    print("=" * 50)

    chains = get_all_causal_chains(db, max_chains=max_chains)
    print(f"Causal chains to trace: {len(chains)}")

    chain_results = []
    for chain in chains:
        result = trace_chain(chain, db)
        if result:
            chain_results.append(result)

    # Aggregate stats
    total_consistent  = sum(r["consistent"]  for r in chain_results)
    total_contradicts = sum(r["contradicts"] for r in chain_results)
    total_novel       = sum(r["novel"]       for r in chain_results)
    avg_coherence     = sum(r["coherence"]   for r in chain_results) / max(len(chain_results), 1)

    print(f"Chains traced:      {len(chain_results)}")
    print(f"Consistent steps:   {total_consistent}")
    print(f"Contradictions:     {total_contradicts}")
    print(f"Novel consequences: {total_novel}")
    print(f"Avg coherence:      {avg_coherence:.2f}")

    # Show contradictions
    contradictions = flag_contradictions(chain_results)
    if contradictions:
        print(f"\nCONTRADICTIONS FOUND ({len(contradictions)}):")
        for c in contradictions[:3]:
            print(f"  Chain: {c['chain_seed'][:60]}")
            print(f"  -> Implies: {c['consequence'][:60]}")
            print(f"  -> Conflicts: {c['conflicts_with'][:60]}")
            print(f"  -> Similarity: {c['similarity']:.3f}")
            print()

    # Propose and store novel beliefs
    proposals = propose_novel_beliefs(chain_results, db)
    print(f"Novel belief proposals: {len(proposals)}")
    for p in proposals[:3]:
        print(f"  [{p['topic']}] {p['content'][:80]}")

    stored = store_novel_beliefs(proposals, db, dry_run=dry_run)
    print(f"Stored: {stored} novel beliefs")

    db.close()
    return {
        "chains":      len(chain_results),
        "consistent":  total_consistent,
        "contradicts": total_contradicts,
        "novel":       total_novel,
        "coherence":   round(avg_coherence, 3),
        "stored":      stored,
    }


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--n", type=int, default=20)
    args = parser.parse_args()
    run_consequence_trace(dry_run=args.dry_run, max_chains=args.n)
