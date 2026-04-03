#!/usr/bin/env python3
"""
nex_warmth_batch.py
Batch warming for pass 1 — associations.

Pass 1 is independent per word so can be batched.
Generates associations for 3 words in one LLM call.
Passes 2-7 remain sequential (each depends on prior output).

Speed improvement: ~60% fewer LLM calls for cold words.
"""
import sqlite3, json, logging, time, sys
from pathlib import Path

log     = logging.getLogger("nex.batch_warm")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
API     = "http://localhost:8080/completion"
sys.path.insert(0, str(NEX_DIR))

BATCH_SIZE = 3  # words per batch call — matches llama-server parallel=2, safe at 3

BATCH_PASS1_PROMPT = """For each word below, list 15 words most strongly associated with it.
Return as JSON object with each word as key, value is array of {{"word": str, "weight": 0.0-1.0}}.
Words: {words}
JSON only. Example format:
{{"consciousness": [{{"word": "awareness", "weight": 0.9}}], "belief": [{{"word": "faith", "weight": 0.8}}]}}"""


def _llm(prompt: str, max_tokens=400) -> str:
    import requests
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": max_tokens, "temperature": 0.2,
            "stop": ["<|im_end|>","<|im_start|>"],
            "cache_prompt": False
        }, timeout=45)
        return r.json().get("content","").strip()
    except Exception as e:
        log.debug(f"LLM failed: {e}")
        return ""


def _parse_json(raw: str) -> dict:
    import re
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Try extracting JSON block
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    # Handle truncated JSON — extract complete word entries
    result = {}
    pattern = r'"\'(\w+)\'\s*:\s*\[(.*?)\]'
    for match in re.finditer(pattern, raw, re.DOTALL):
        word = match.group(1)
        try:
            items = json.loads("[" + match.group(2) + "]")
            result[word] = items
        except Exception:
            pass
    return result


def batch_warm_pass1(words: list) -> dict:
    """
    Run pass 1 for multiple words in one LLM call.
    Returns {word: [{"word": str, "weight": float}]} or {}
    """
    if not words:
        return {}
    prompt = BATCH_PASS1_PROMPT.format(words=", ".join(words))
    raw = _llm(prompt, max_tokens=900)
    data = _parse_json(raw)
    # Validate structure
    result = {}
    for word in words:
        if word in data and isinstance(data[word], list):
            result[word] = data[word]
        else:
            log.debug(f"  batch_pass1: no result for {word}")
    return result


def store_pass1(word: str, associations: list, db) -> bool:
    """Store pass 1 associations into word_tags."""
    try:
        existing = db.execute(
            "SELECT warming_history FROM word_tags WHERE word=?",
            (word,)).fetchone()
        if existing and existing[0] and existing[0] not in ("[]","","null"):
            return False  # Already has pass 1
        assoc_json = json.dumps(associations)
        now = time.time()
        if existing:
            db.execute("""UPDATE word_tags SET
                association_vector=?,
                warming_history=?,
                last_updated=?
                WHERE word=?""", (assoc_json, '[{"pass":1}]', now, word))
        else:
            db.execute("""INSERT INTO word_tags
                (word, w, t, d, a, c, f, b, s, g, r, e,
                 association_vector, last_updated)
                VALUES (?,0.1,0,1,0,0.1,1,0,0,0,0,0,?,?)""",
                (word, assoc_json, now))
        return True
    except Exception as e:
        log.debug(f"store_pass1 failed for {word}: {e}")
        return False


def run_batch_warm(n=60, priority="high") -> dict:
    """
    Batch warm n cold words through pass 1.
    Then hand off to standard warmer for passes 2-7.
    """
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # Get cold words (no warming_history yet) from queue
    rows = db.execute("""
        SELECT q.word FROM warming_queue q
        LEFT JOIN word_tags t ON q.word = t.word
        WHERE q.priority = ?
        AND (t.word IS NULL OR t.warming_history IS NULL
             OR t.warming_history = '[]' OR t.warming_history = '')
        ORDER BY q.gap_count DESC
        LIMIT ?""", (priority, n)).fetchall()

    cold_words = [r["word"] for r in rows]
    print(f"Batch warming {len(cold_words)} cold words through pass 1...")

    stored = 0
    failed = 0
    batches = [cold_words[i:i+BATCH_SIZE]
               for i in range(0, len(cold_words), BATCH_SIZE)]

    for batch in batches:
        results = batch_warm_pass1(batch)
        for word in batch:
            if word in results and results[word]:
                if store_pass1(word, results[word], db):
                    stored += 1
                    log.info(f"  batch_pass1: {word} -> {len(results[word])} assoc")
                else:
                    failed += 1
            else:
                failed += 1
        db.commit()
        time.sleep(0.5)

    db.close()

    print(f"Batch pass 1 complete: {stored} stored, {failed} failed")
    print(f"LLM calls: {len(batches)} (vs {len(cold_words)} sequential)")
    print(f"Speedup: {len(cold_words)/max(len(batches),1):.1f}x")

    return {"stored": stored, "failed": failed,
            "batches": len(batches), "words": len(cold_words)}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=60)
    parser.add_argument("--priority", default="high",
                        choices=["urgent","high","low"])
    args = parser.parse_args()
    run_batch_warm(n=args.n, priority=args.priority)
