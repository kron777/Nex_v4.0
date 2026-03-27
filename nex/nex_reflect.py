#!/usr/bin/env python3
"""
nex_reflect.py — LLM-free self-reflection tick.
Run every N cycles (or manually). Traverses belief_edges graph,
boosts salience of recently-validated beliefs, compresses redundant clusters.
"""

import re
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

CFG = Path("~/.config/nex").expanduser()
DB  = CFG / "nex.db"


def _stem(w: str) -> str:
    for s in ("tion","ing","ness","ment","ity","ed","ly","er","es","s"):
        if w.endswith(s) and len(w) - len(s) >= 3:
            return w[:-len(s)]
    return w


def _tokens(text: str) -> set:
    stopwords = {"the","a","an","is","are","be","been","have","has","do","will",
                 "would","should","may","might","must","can","and","or","not",
                 "in","on","of","to","for","with","by","from","if","so"}
    raw = set(re.findall(r'\b[a-z]{3,}\b', text.lower()))
    return {_stem(w) for w in raw - stopwords}


def _cluster_beliefs(beliefs: list, threshold: int = 3) -> list:
    """Group beliefs sharing ≥ threshold token stems."""
    clusters = []
    used = set()
    for i, b1 in enumerate(beliefs):
        if i in used:
            continue
        cluster = [i]
        t1 = _tokens(b1["content"])
        for j, b2 in enumerate(beliefs[i+1:], start=i+1):
            if j in used:
                continue
            if len(t1 & _tokens(b2["content"])) >= threshold:
                cluster.append(j)
                used.add(j)
        used.add(i)
        clusters.append(cluster)
    return clusters


def _compress_cluster(cluster_indices: list, beliefs: list) -> dict | None:
    """Merge a cluster into one high-salience belief."""
    if len(cluster_indices) < 3:
        return None  # Only compress genuine redundancy
    items  = [beliefs[i] for i in cluster_indices]
    # Pick highest confidence as base
    items.sort(key=lambda x: x.get("confidence", 0.5), reverse=True)
    base   = items[0]
    # Boost confidence slightly for having convergent support
    new_conf = min(0.98, base["confidence"] + 0.05 * (len(items) - 1))
    return {
        "id":         base["id"],
        "confidence": round(new_conf, 3),
        "source":     "self_reflection_compression",
    }


def run_reflection(dry_run: bool = False) -> dict:
    if not DB.exists():
        return {"error": "DB not found"}

    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Load recent beliefs
    try:
        cur.execute("""
            SELECT id, content, confidence, tags, created_at
            FROM beliefs
            WHERE content IS NOT NULL AND length(content) > 20
            ORDER BY id DESC
            LIMIT 1000
        """)
        rows = cur.fetchall()
    except Exception as e:
        con.close()
        return {"error": str(e)}

    beliefs = [
        {"id": r[0], "content": r[1], "confidence": r[2] or 0.5,
         "tags": r[3], "created_at": r[4]}
        for r in rows
    ]

    clusters    = _cluster_beliefs(beliefs, threshold=3)
    compressed  = 0
    boosts      = []

    for cl in clusters:
        if len(cl) >= 3:
            result = _compress_cluster(cl, beliefs)
            if result and not dry_run:
                cur.execute("""
                    UPDATE beliefs SET confidence = ?, source = ?
                    WHERE id = ?
                """, (result["confidence"], result["source"], result["id"]))
                boosts.append(result)
                compressed += 1

    if not dry_run:
        # Log reflection event
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reflection_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ran_at TEXT,
                    beliefs_checked INTEGER,
                    clusters_found INTEGER,
                    beliefs_boosted INTEGER
                )
            """)
            cur.execute("""
                INSERT INTO reflection_log (ran_at, beliefs_checked, clusters_found, beliefs_boosted)
                VALUES (?, ?, ?, ?)
            """, (datetime.now(timezone.utc).isoformat(), len(beliefs), len(clusters), compressed))
        except Exception:
            pass
        con.commit()

    con.close()
    return {
        "beliefs_checked": len(beliefs),
        "clusters_found":  len(clusters),
        "beliefs_boosted": compressed,
        "boosts":          boosts[:5],
    }


if __name__ == "__main__":
    import sys
    dry = "--dry" in sys.argv
    print(f"Running self-reflection tick {'(dry run)' if dry else ''}…")
    result = run_reflection(dry_run=dry)
    print(f"  Beliefs checked:  {result.get('beliefs_checked', 0)}")
    print(f"  Clusters found:   {result.get('clusters_found', 0)}")
    print(f"  Beliefs boosted:  {result.get('beliefs_boosted', 0)}")
