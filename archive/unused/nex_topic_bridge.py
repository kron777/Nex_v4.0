"""
nex_topic_bridge.py
Finds unexpected connections between beliefs from different topics.
Cross-topic FAISS search — finds beliefs that are semantically close
despite being categorised in different domains.
These bridges become NEX's most interesting insights.
"""
import sqlite3, numpy as np, json, logging, time
from pathlib import Path

log     = logging.getLogger("nex.bridge")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
FAISS_PATH = Path.home() / ".config/nex/nex_beliefs.faiss"
META_PATH  = Path.home() / ".config/nex/nex_beliefs_meta.json"

BRIDGE_THRESHOLD = 0.78  # cosine sim for cross-topic bridge

def find_bridges(min_conf=0.75, max_bridges=50) -> list:
    import faiss
    if not FAISS_PATH.exists():
        log.error("FAISS index not found")
        return []

    index  = faiss.read_index(str(FAISS_PATH))
    id_map = json.loads(META_PATH.read_text())

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # Get high-conf beliefs with embeddings
    rows = db.execute("""SELECT id, content, topic, embedding, confidence
        FROM beliefs WHERE confidence >= ? AND embedding IS NOT NULL
        ORDER BY confidence DESC LIMIT 1000""", (min_conf,)).fetchall()

    bridges = []
    seen = set()

    for row in rows:
        bid = row["id"]
        topic = row["topic"]
        vec = np.frombuffer(row["embedding"], dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm == 0: continue
        vec_n = (vec / norm).reshape(1, -1)

        # Search for similar beliefs
        scores, positions = index.search(vec_n, 10)

        for score, pos in zip(scores[0], positions[0]):
            if pos < 0 or pos >= len(id_map): continue
            target_id = id_map[pos]
            if target_id == bid: continue

            pair_key = tuple(sorted([bid, target_id]))
            if pair_key in seen: continue

            # Get target belief
            target = db.execute(
                "SELECT id, content, topic, confidence FROM beliefs WHERE id=?",
                (target_id,)).fetchone()
            if not target: continue

            # Only cross-topic bridges
            if target["topic"] == topic: continue
            if float(score) < BRIDGE_THRESHOLD: continue

            seen.add(pair_key)
            bridges.append({
                "belief_a": {"id": bid, "content": row["content"][:100],
                             "topic": topic, "conf": row["confidence"]},
                "belief_b": {"id": target_id, "content": target["content"][:100],
                             "topic": target["topic"], "conf": target["confidence"]},
                "similarity": round(float(score), 3)
            })

            if len(bridges) >= max_bridges:
                db.close()
                return bridges

    db.close()
    return bridges

def store_bridges(bridges: list) -> int:
    """Store bridges as belief_relations with 'bridges' type."""
    db = sqlite3.connect(str(DB_PATH))
    inserted = 0
    for b in bridges:
        try:
            db.execute("""INSERT OR IGNORE INTO belief_relations
                (source_id, target_id, weight, relation_type)
                VALUES (?,?,?,?)""",
                (b["belief_a"]["id"], b["belief_b"]["id"],
                 b["similarity"], "bridges"))
            inserted += 1
        except Exception:
            pass
    db.commit()
    db.close()
    return inserted

def report(bridges: list, n=10):
    print(f"\nTop {n} cross-topic bridges:")
    for b in sorted(bridges, key=lambda x: -x["similarity"])[:n]:
        print(f"\n  [{b['similarity']:.3f}] {b['belief_a']['topic']} <-> {b['belief_b']['topic']}")
        print(f"  A: {b['belief_a']['content'][:80]}")
        print(f"  B: {b['belief_b']['content'][:80]}")

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", action="store_true")
    parser.add_argument("--n", type=int, default=10)
    args = parser.parse_args()

    print("Finding cross-topic bridges...")
    bridges = find_bridges(max_bridges=100)
    print(f"Found {len(bridges)} bridges")
    report(bridges, n=args.n)

    if args.store:
        n = store_bridges(bridges)
        print(f"\nStored {n} bridge edges in belief_relations")
