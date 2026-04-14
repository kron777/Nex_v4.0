"""
nex_argument_mapper.py
Maps strongest counterarguments to NEX's positions.
Stores them as opposing beliefs in the graph.
Prevents epistemic bubble — NEX knows the best case against her views.
"""
import sqlite3, requests, logging, time
from pathlib import Path

log     = logging.getLogger("nex.argmap")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

COUNTER_PROMPT = """Given this position:
"{belief}"

State the single strongest counterargument against it.
One sentence, 15-35 words. Direct and specific — no hedging.
Return only the counterargument."""

def map_counterargument(belief_content: str) -> str:
    try:
        prompt = COUNTER_PROMPT.format(belief=belief_content[:200])
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 80, "temperature": 0.3,
            "stop": ["<|im_end|>","<|im_start|>","\n\n"],
            "cache_prompt": False
        }, timeout=20)
        text = r.json().get("content","").strip().strip('"\'')
        if 10 <= len(text.split()) <= 50:
            return text
    except Exception as e:
        log.debug(f"Counter mapping failed: {e}")
    return ""

def run(topic=None, n=20, min_conf=0.80, dry_run=False) -> int:
    db = sqlite3.connect(str(DB_PATH))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    q = """SELECT id, content, topic FROM beliefs
           WHERE confidence >= ? AND source NOT IN ('nex_counter', 'web_gap_fill')"""
    params = [min_conf]
    if topic:
        q += " AND topic=?"
        params.append(topic)
    q += " ORDER BY RANDOM() LIMIT ?"
    params.append(n)

    rows = db.execute(q, params).fetchall()
    inserted = 0

    for bid, content, t in rows:
        counter = map_counterargument(content)
        if not counter:
            continue

        log.info(f"Counter [{t}]: {counter[:60]}")

        if not dry_run:
            try:
                db.execute("""INSERT INTO beliefs
                    (content, topic, confidence, source, belief_type, created_at)
                    VALUES (?,?,?,?,?,?)""",
                    (counter, t, 0.50, "nex_counter", "opinion", now))
                # Link as opposing belief
                new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                db.execute("""INSERT OR IGNORE INTO belief_relations
                    (source_id, target_id, weight, relation_type)
                    VALUES (?,?,?,?)""",
                    (bid, new_id, -0.8, "opposes"))
                inserted += 1
            except sqlite3.IntegrityError:
                pass

    if not dry_run:
        db.commit()
    db.close()
    print(f"Counterarguments mapped: {inserted} (dry={dry_run})")
    return inserted

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=None)
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(topic=args.topic, n=args.n, dry_run=args.dry_run)
