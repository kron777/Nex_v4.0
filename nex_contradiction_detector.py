"""
nex_contradiction_detector.py
Detects contradictory beliefs in the same topic using embedding cosine similarity.
Penalises lower-confidence belief. Wires into annealing crystallise cycle.
"""
import sqlite3, numpy as np, logging, argparse
from pathlib import Path

log = logging.getLogger("nex.contradiction")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
SIMILARITY_THRESHOLD = -0.15  # cosine < this = likely contradiction
CONFIDENCE_PENALTY   = 0.5    # multiply losing belief confidence by this

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))

def run(topic: str = None, dry_run: bool = False, verbose: bool = False):
    db = sqlite3.connect(DB_PATH)

    q = """SELECT id, content, embedding, confidence, topic
           FROM beliefs
           WHERE embedding IS NOT NULL AND confidence >= 0.6"""
    if topic:
        q += f" AND topic='{topic}'"

    rows = db.execute(q).fetchall()
    log.info(f"Scanning {len(rows)} beliefs for contradictions...")

    # Group by topic for efficiency
    by_topic = {}
    for bid, content, emb, conf, t in rows:
        by_topic.setdefault(t, []).append((bid, content, emb, conf))

    contradictions = []
    for t, beliefs in by_topic.items():
        if len(beliefs) < 2:
            continue
        for i in range(len(beliefs)):
            for j in range(i+1, len(beliefs)):
                id1, c1, e1, conf1 = beliefs[i]
                id2, c2, e2, conf2 = beliefs[j]
                vec1 = np.frombuffer(e1, dtype=np.float32)
                vec2 = np.frombuffer(e2, dtype=np.float32)
                sim = _cosine(vec1, vec2)
                if sim < SIMILARITY_THRESHOLD:
                    contradictions.append({
                        'topic': t, 'sim': sim,
                        'id1': id1, 'c1': c1, 'conf1': conf1,
                        'id2': id2, 'c2': c2, 'conf2': conf2,
                    })

    log.info(f"Found {len(contradictions)} contradiction pairs")

    resolved = 0
    for pair in contradictions:
        # Keep higher confidence, penalise lower
        if pair['conf1'] >= pair['conf2']:
            loser_id, loser_conf = pair['id2'], pair['conf2']
            winner_content = pair['c1']
        else:
            loser_id, loser_conf = pair['id1'], pair['conf1']
            winner_content = pair['c2']

        new_conf = round(loser_conf * CONFIDENCE_PENALTY, 4)

        if verbose:
            print(f"\n[{pair['topic']}] sim={pair['sim']:.3f}")
            print(f"  KEEP:    {winner_content[:80]}")
            print(f"  PENALISE (id={loser_id}): {pair['c1' if loser_id==pair['id1'] else 'c2'][:80]}")
            print(f"  conf: {loser_conf:.3f} -> {new_conf:.3f}")

        if not dry_run:
            db.execute("UPDATE beliefs SET confidence=? WHERE id=?", (new_conf, loser_id))
        resolved += 1

    if not dry_run:
        db.commit()
    db.close()

    print(f"Contradictions found: {len(contradictions)}")
    print(f"Resolved (penalised): {resolved}")
    print(f"Dry run: {dry_run}")
    return contradictions

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    run(topic=args.topic, dry_run=args.dry_run, verbose=args.verbose)
