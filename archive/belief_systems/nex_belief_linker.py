"""
nex_belief_linker.py
Builds edges between beliefs using embedding similarity.
Populates belief_relations table for graph traversal and activation.
Runs once to seed, then incrementally on new beliefs.
"""
import sqlite3, numpy as np, logging
from pathlib import Path

log     = logging.getLogger("nex.linker")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

SIMILARITY_THRESHOLD = 0.75  # cosine sim threshold for edge creation
MAX_EDGES_PER_NODE   = 10    # max outgoing edges per belief
BATCH_SIZE           = 200

def cosine(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0: return 0.0
    return float(np.dot(a, b) / (na * nb))

def build_edges(topic=None, limit=2000, dry_run=False, unlinked_only=False):
    db = sqlite3.connect(str(DB_PATH))

    # Ensure belief_relations table exists
    db.execute("""CREATE TABLE IF NOT EXISTS belief_relations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id   INTEGER NOT NULL,
        target_id   INTEGER NOT NULL,
        weight      REAL DEFAULT 0.5,
        relation_type TEXT DEFAULT 'similar',
        UNIQUE(source_id, target_id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_br_source ON belief_relations(source_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_br_target ON belief_relations(target_id)")
    db.commit()

    # Load beliefs with embeddings
    if unlinked_only:
        q = """SELECT id, content, embedding, topic, confidence
               FROM beliefs WHERE embedding IS NOT NULL AND confidence >= 0.3
               AND id NOT IN (SELECT DISTINCT source_id FROM belief_relations)"""
        if topic:
            q += f" AND topic='{topic}'"
        q += f" ORDER BY id ASC LIMIT {limit}"
    else:
        q = """SELECT id, content, embedding, topic, confidence
               FROM beliefs WHERE embedding IS NOT NULL AND confidence >= 0.3"""
        if topic:
            q += f" AND topic='{topic}'"
        q += f" ORDER BY confidence DESC LIMIT {limit}"

    rows = db.execute(q).fetchall()
    log.info(f"Loaded {len(rows)} beliefs for linking")

    beliefs = []
    for bid, content, emb, t, conf in rows:
        vec = np.frombuffer(emb, dtype=np.float32)
        beliefs.append({"id": bid, "vec": vec, "topic": t, "conf": conf})

    edges_added = 0
    skipped     = 0

    for i, b1 in enumerate(beliefs):
        if i % 100 == 0:
            log.info(f"  Processing {i}/{len(beliefs)}...")

        edges_this = 0
        candidates = []

        for j, b2 in enumerate(beliefs):
            if i == j: continue
            sim = cosine(b1["vec"], b2["vec"])
            if sim >= SIMILARITY_THRESHOLD:
                candidates.append((sim, b2["id"]))

        # Keep top MAX_EDGES_PER_NODE
        candidates.sort(reverse=True)
        for sim, target_id in candidates[:MAX_EDGES_PER_NODE]:
            if not dry_run:
                try:
                    db.execute("""INSERT OR IGNORE INTO belief_relations
                        (source_id, target_id, weight, relation_type)
                        VALUES (?,?,?,?)""",
                        (b1["id"], target_id, round(sim, 4), "similar"))
                    edges_added += 1
                except Exception:
                    skipped += 1

        if i % 500 == 0 and not dry_run:
            db.commit()

    if not dry_run:
        db.commit()
    db.close()

    print(f"Edges added: {edges_added}, skipped: {skipped}, dry: {dry_run}")
    return edges_added

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=None)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--unlinked", action="store_true", help="Only process beliefs with 0 edges")
    args = parser.parse_args()
    build_edges(topic=args.topic, limit=args.limit, dry_run=args.dry_run, unlinked_only=args.unlinked)
