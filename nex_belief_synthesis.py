"""
nex_belief_synthesis.py
Generates new beliefs by combining existing ones.
Takes 2-3 related beliefs, asks LLM to derive a new position.
Runs nightly — adds to belief graph with moderate confidence.
"""
import sqlite3, requests, json, logging, time, random
from pathlib import Path

log     = logging.getLogger("nex.synthesis")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

SYNTH_PROMPT = """You are NEX synthesizing a new position from existing beliefs.

Existing beliefs:
{beliefs}

Derive ONE new, specific position that follows from combining these beliefs.
It must be:
- A direct logical consequence or tension between them
- Not already stated above
- Expressed as a single declarative sentence in first person or direct claim
- 15-40 words

Return only the new belief statement, nothing else."""

def get_belief_cluster(topic: str, n=3) -> list:
    """Get n high-confidence beliefs from same topic."""
    db = sqlite3.connect(str(DB_PATH))
    rows = db.execute("""SELECT id, content FROM beliefs
        WHERE topic=? AND confidence >= 0.75
        ORDER BY RANDOM() LIMIT ?""", (topic, n)).fetchall()
    db.close()
    return [{"id": r[0], "content": r[1]} for r in rows]

def get_warmth_cluster(n=3) -> list:
    """
    Get beliefs clustered by word warmth pull_toward vectors.
    Finds cross-topic beliefs whose key words pull toward each other.
    This surfaces connections topic-based clustering misses.
    """
    db = sqlite3.connect(str(DB_PATH))
    import re as _re

    # Get hot words with pull_toward vectors
    hot = db.execute(
        "SELECT word, pull_toward FROM word_tags WHERE w >= 0.55 AND pull_toward IS NOT NULL"
    ).fetchall()
    if len(hot) < 2:
        db.close()
        return []

    # Build pull_toward sets per word
    import json as _json
    word_pulls = {}
    for word, pull_json in hot:
        try:
            pulls = _json.loads(pull_json) if isinstance(pull_json, str) else pull_json
            if isinstance(pulls, list):
                word_pulls[word] = set(str(p).lower() for p in pulls)
        except Exception:
            pass

    if len(word_pulls) < 2:
        db.close()
        return []

    # Find word pairs with overlapping pull_toward
    words = list(word_pulls.keys())
    best_pair = None
    best_overlap = 0
    import random
    random.shuffle(words)
    for i in range(min(len(words), 20)):
        for j in range(i+1, min(len(words), 20)):
            overlap = word_pulls[words[i]] & word_pulls[words[j]]
            if len(overlap) > best_overlap:
                best_overlap = len(overlap)
                best_pair = (words[i], words[j])

    if not best_pair or best_overlap == 0:
        db.close()
        return []

    w1, w2 = best_pair
    # Find high-confidence beliefs containing either word, different topics
    rows = db.execute("""
        SELECT id, content, topic FROM beliefs
        WHERE confidence >= 0.72
        AND (content LIKE ? OR content LIKE ?)
        ORDER BY confidence DESC LIMIT 20
    """, (f"%{w1}%", f"%{w2}%")).fetchall()

    # Pick from different topics if possible
    seen_topics = set()
    cluster = []
    for bid, content, topic in rows:
        if topic not in seen_topics or len(cluster) < 2:
            cluster.append({"id": bid, "content": content, "topic": topic})
            seen_topics.add(topic)
        if len(cluster) >= n:
            break

    db.close()
    return cluster


def synthesize(beliefs: list, topic: str) -> str:
    """Ask LLM to synthesize a new belief from existing ones."""
    belief_text = "\n".join(f"- {b['content']}" for b in beliefs)
    prompt = SYNTH_PROMPT.format(beliefs=belief_text)
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 80, "temperature": 0.4,
            "stop": ["<|im_end|>","<|im_start|>","\n\n"],
            "cache_prompt": False
        }, timeout=20)
        text = r.json().get("content","").strip()
        # Clean up
        text = text.strip('"\'').strip()
        if len(text.split()) >= 10 and len(text.split()) <= 60:
            return text
    except Exception as e:
        log.debug(f"Synthesis failed: {e}")
    return ""

def run_synthesis(topics=None, n_per_topic=3, dry_run=False) -> int:
    db = sqlite3.connect(str(DB_PATH))

    if not topics:
        # Get top topics by belief count
        rows = db.execute("""SELECT topic FROM beliefs
            WHERE confidence >= 0.75
            GROUP BY topic ORDER BY COUNT(*) DESC LIMIT 8""").fetchall()
        topics = [r[0] for r in rows]

    inserted = 0
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    for topic in topics:
        for _ in range(n_per_topic):
            # 30% chance to use warmth-cluster instead of topic-cluster
            if random.random() < 0.30:
                cluster = get_warmth_cluster(n=3)
            else:
                cluster = get_belief_cluster(topic, n=3)
            if len(cluster) < 2:
                continue

            new_belief = synthesize(cluster, topic)
            if not new_belief:
                continue

            log.info(f"Synthesized [{topic}]: {new_belief[:60]}")

            if not dry_run:
                try:
                    db.execute("""INSERT INTO beliefs
                        (content, topic, confidence, source, belief_type, created_at)
                        VALUES (?,?,?,?,?,?)""",
                        (new_belief, topic, 0.65,
                         "nex_synthesis", "opinion", now))
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass

    if not dry_run:
        db.commit()
    db.close()

    print(f"Synthesized beliefs: {inserted} (dry={dry_run})")
    return inserted

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--topics", nargs="+", default=None)
    parser.add_argument("--n", type=int, default=2)
    args = parser.parse_args()
    run_synthesis(topics=args.topics, n_per_topic=args.n, dry_run=args.dry_run)
