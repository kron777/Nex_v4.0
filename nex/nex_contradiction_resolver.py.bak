#!/usr/bin/env python3
"""
nex_contradiction_resolver.py — LLM-free contradiction detection and logging.
After every belief drain: detects opposing high-confidence beliefs,
logs them to tensions table so they surface naturally in replies.
"""

import re
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

CFG    = Path("~/.config/nex").expanduser()
DB     = CFG / "nex.db"

STOPWORDS = {
    "the","a","an","is","are","was","were","be","been","have","has","had",
    "do","does","will","would","should","may","might","must","can","could",
    "i","you","we","they","this","that","and","or","but","not","in","on",
    "of","to","for","with","at","by","from","if","so","just","than","also",
}

NEGATION_PAIRS = [
    ({"always","every","all","never","impossible","certain","absolute"},
     {"sometimes","often","rarely","possible","uncertain","relative","context"}),
    ({"conscious","sentient","subjective","experience"},
     {"unconscious","mechanical","objective","process"}),
    ({"deterministic","fixed","inevitable"},
     {"stochastic","random","contingent","emergent"}),
]


def _stem(w: str) -> str:
    for s in ("tion","ing","ness","ment","ity","ed","ly","er","es","s"):
        if w.endswith(s) and len(w) - len(s) >= 3:
            return w[:-len(s)]
    return w


def _tokens(text: str) -> set:
    raw = set(re.findall(r'\b[a-z]{3,}\b', text.lower()))
    return {_stem(w) for w in raw - STOPWORDS}


def _opposite_polarity(t1: set, t2: set) -> bool:
    for pos_set, neg_set in NEGATION_PAIRS:
        if (t1 & pos_set and t2 & neg_set) or (t1 & neg_set and t2 & pos_set):
            return True
    return False


def _ensure_tensions_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tensions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic       TEXT,
            description TEXT,
            belief_a_id INTEGER,
            belief_b_id INTEGER,
            detected_at TEXT,
            resolved    INTEGER DEFAULT 0
        )
    """)


def detect_and_log(limit: int = 500, max_new: int = 10) -> int:
    if not DB.exists():
        print("  [resolver] DB not found")
        return 0

    con = sqlite3.connect(DB)
    cur = con.cursor()
    _ensure_tensions_table(cur)
    con.commit()

    # Load recent high-confidence beliefs
    try:
        cur.execute("""
            SELECT id, content, confidence, tags
            FROM beliefs
            WHERE confidence >= 0.6 AND content IS NOT NULL AND length(content) > 20
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
    except Exception as e:
        print(f"  [resolver] Belief query error: {e}")
        con.close()
        return 0

    beliefs = []
    for bid, content, conf, tags in rows:
        tag_list = []
        if tags:
            try:
                tag_list = json.loads(tags) if tags.startswith("[") else [t.strip() for t in tags.split(",")]
            except Exception:
                tag_list = []
        beliefs.append({"id": bid, "content": content, "conf": conf or 0.5, "tokens": _tokens(content), "tags": tag_list})

    found = 0
    checked_pairs = set()

    for i, b1 in enumerate(beliefs):
        if found >= max_new:
            break
        for b2 in beliefs[i+1:]:
            pair = (min(b1["id"], b2["id"]), max(b1["id"], b2["id"]))
            if pair in checked_pairs:
                continue
            checked_pairs.add(pair)

            # Check overlap (topic similarity) + opposite polarity
            overlap = b1["tokens"] & b2["tokens"]
            if len(overlap) < 2:
                continue
            if not _opposite_polarity(b1["tokens"], b2["tokens"]):
                continue

            # Check not already logged
            cur.execute("""
                SELECT COUNT(*) FROM tensions
                WHERE belief_a_id = ? AND belief_b_id = ?
            """, pair)
            if cur.fetchone()[0] > 0:
                continue

            topic = (b1["tags"][0] if b1["tags"] else list(overlap)[0])
            desc  = f"{b1['content'][:80]} ↔ {b2['content'][:80]}"
            cur.execute("""
                INSERT INTO tensions (topic, description, belief_a_id, belief_b_id, detected_at)
                VALUES (?, ?, ?, ?, ?)
            """, (topic, desc, b1["id"], b2["id"], datetime.now(timezone.utc).isoformat()))
            print(f"  [resolver] Tension logged [{topic}]: {desc[:90]}...")
            found += 1

    con.commit()
    con.close()
    return found


if __name__ == "__main__":
    print("Running contradiction detector…")
    n = detect_and_log()
    print(f"Detected and logged {n} new tensions")
