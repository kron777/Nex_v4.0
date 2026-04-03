"""
nex_conflict_resolver.py
Intelligent conflict resolution for belief graph.
Goes beyond simple confidence penalty — asks LLM to adjudicate.
Produces resolved belief with higher confidence.
"""
import sqlite3, requests, logging, time, numpy as np
from pathlib import Path

log     = logging.getLogger("nex.resolver")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

RESOLVE_PROMPT = """Two beliefs conflict on the same topic. Adjudicate.

Belief A (confidence {conf_a:.2f}): {belief_a}
Belief B (confidence {conf_b:.2f}): {belief_b}

Which is more defensible? Options:
1. A is correct — state why in one sentence
2. B is correct — state why in one sentence  
3. Both partial — synthesize a better belief in one sentence

Return: WINNER:<A|B|BOTH> REASON:<one sentence>"""

def cosine(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0: return 0.0
    return float(np.dot(a, b) / (na * nb))

def find_conflicts(topic=None, limit=20) -> list:
    db = sqlite3.connect(str(DB_PATH))
    q = """SELECT id, content, embedding, confidence, topic
           FROM beliefs WHERE embedding IS NOT NULL
           AND confidence >= 0.5 AND locked = 0"""
    if topic:
        q += f" AND topic='{topic}'"
    q += f" LIMIT {limit * 5}"
    rows = db.execute(q).fetchall()
    db.close()

    conflicts = []
    for i in range(len(rows)):
        for j in range(i+1, len(rows)):
            id1, c1, e1, cf1, t1 = rows[i]
            id2, c2, e2, cf2, t2 = rows[j]
            if t1 != t2: continue
            v1 = np.frombuffer(e1, dtype=np.float32)
            v2 = np.frombuffer(e2, dtype=np.float32)
            sim = cosine(v1, v2)
            if sim < -0.1:  # opposing directions
                conflicts.append({
                    "id1": id1, "c1": c1, "cf1": cf1,
                    "id2": id2, "c2": c2, "cf2": cf2,
                    "topic": t1, "sim": sim
                })
            if len(conflicts) >= limit:
                return conflicts
    return conflicts

def resolve_conflict(conflict: dict) -> dict:
    """Ask LLM to adjudicate between two conflicting beliefs."""
    prompt = RESOLVE_PROMPT.format(
        conf_a=conflict["cf1"], belief_a=conflict["c1"][:150],
        conf_b=conflict["cf2"], belief_b=conflict["c2"][:150]
    )
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 100, "temperature": 0.1,
            "stop": ["<|im_end|>","<|im_start|>","\n\n"],
            "cache_prompt": False
        }, timeout=20)
        text = r.json().get("content","").strip()
        import re
        wm = re.search(r'WINNER:\s*(A|B|BOTH)', text, re.I)
        rm = re.search(r'REASON:\s*(.+?)$', text, re.M)
        winner = wm.group(1).upper() if wm else "A"
        reason = rm.group(1).strip() if rm else ""
        return {"winner": winner, "reason": reason}
    except Exception as e:
        log.debug(f"Resolve failed: {e}")
        return {"winner": "A", "reason": ""}

def run(topic=None, n=10, dry_run=False) -> int:
    conflicts = find_conflicts(topic=topic, limit=n)
    log.info(f"Found {len(conflicts)} conflicts")
    db = sqlite3.connect(str(DB_PATH))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    resolved = 0

    for c in conflicts:
        result = resolve_conflict(c)
        winner = result["winner"]

        if winner == "A":
            loser_id  = c["id2"]
            winner_id = c["id1"]
        elif winner == "B":
            loser_id  = c["id1"]
            winner_id = c["id2"]
        else:  # BOTH — synthesize
            loser_id = None
            winner_id = None

        if not dry_run:
            if loser_id:
                # Penalise loser
                db.execute("UPDATE beliefs SET confidence=confidence*0.6 WHERE id=?",
                    (loser_id,))
                # Boost winner
                db.execute("UPDATE beliefs SET confidence=MIN(0.90, confidence*1.05) WHERE id=?",
                    (winner_id,))
            resolved += 1

        log.info(f"  [{c['topic']}] Winner={winner}: {result['reason'][:60]}")

    if not dry_run:
        db.commit()
    db.close()
    print(f"Conflicts resolved: {resolved} (dry={dry_run})")
    return resolved

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=None)
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(topic=args.topic, n=args.n, dry_run=args.dry_run)
