#!/usr/bin/env python3
"""
nex_bridge_detector.py — NEX Build 9: Bridge Detector
======================================================
Place at: ~/Desktop/nex/nex_bridge_detector.py

Creativity is not generation from nothing.
It is unexpected connection between existing things.
That is a graph traversal problem. NEX can do that.

A bridge = two beliefs from maximally distant topic clusters
           that share a latent concept (word / entity / pattern)

The more distant the topics + the stronger the shared concept
= the more surprising and generative the bridge.

Algorithm:
  1. Sample beliefs from different topic clusters
  2. Compute pairwise semantic distance (1 - cosine similarity)
  3. Find shared surface concepts (NER / keyword overlap)
  4. Score = distance * concept_overlap_strength
  5. Top bridges → store in bridge_history → become WONDER posts

Bridge history compounds:
  Bridges become beliefs → richer graph → better future bridges
  Creativity self-reinforces through the graph.

Usage:
  python3 nex_bridge_detector.py              # find + show top bridges
  python3 nex_bridge_detector.py --n 10       # find top N bridges
  python3 nex_bridge_detector.py --promote    # store top bridge as belief
  python3 nex_bridge_detector.py --show       # show bridge history

  from nex_bridge_detector import find_bridges, get_recent_bridges
  bridges = find_bridges(n=5)
"""

import sqlite3
import numpy as np
import pickle
import re
import json
import time
import argparse
import sys
from pathlib import Path
from typing import Optional

CFG_PATH   = Path("~/.config/nex").expanduser()
DB_PATH    = Path("/home/rr/Desktop/nex/nex.db")  # main belief graph
FAISS_PATH = CFG_PATH / "nex_beliefs.faiss"
META_PATH  = CFG_PATH / "nex_beliefs_meta.json"

# Bridge scoring parameters
MIN_TOPIC_DISTANCE  = 0.35   # topics must be this semantically distant
MIN_CONCEPT_OVERLAP = 1      # must share at least this many concepts
MAX_CANDIDATES      = 2000   # beliefs sampled per run
BRIDGE_SCORE_THRESHOLD = 0.15

# Stop words for concept extraction
_STOP = {
    "the","a","an","is","are","was","were","be","been","have","has","do","does",
    "did","will","would","could","should","may","might","must","can","that","this",
    "these","those","with","from","they","their","about","what","how","why","when",
    "where","who","which","into","also","just","over","after","more","some","very",
    "your","you","me","my","we","our","it","its","he","she","him","her","them",
    "not","but","and","or","for","of","to","in","on","at","by","as","if","so",
    "then","than","such","both","each","all","any","one","two","three","first",
    "second","third","new","old","great","good","high","long","large","small",
}


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_bridge_table():
    conn = _db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bridge_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            belief_a_id INTEGER,
            belief_b_id INTEGER,
            topic_a     TEXT,
            topic_b     TEXT,
            content_a   TEXT,
            content_b   TEXT,
            shared_concepts TEXT,
            bridge_score    REAL,
            bridge_text     TEXT,
            promoted    INTEGER DEFAULT 0,
            created_at  REAL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bridge_score
        ON bridge_history(bridge_score DESC)
    """)
    conn.commit()
    conn.close()


def _extract_concepts(text: str, min_len: int = 5) -> set:
    """Extract meaningful concepts from text for overlap scoring."""
    # Letters only — no digits, years, codes
    words = set(re.sub(r'[^a-z ]', ' ', text.lower()).split())
    _EXTENDED_STOP = _STOP | {
        "including", "between", "while", "within", "through", "about",
        "these", "those", "their", "there", "where", "which", "would",
        "could", "should", "being", "having", "making", "taking", "using",
        "also", "both", "even", "just", "like", "more", "most", "other",
        "such", "than", "then", "them", "they", "this", "that", "will",
        "with", "from", "into", "onto", "upon", "over", "under", "after",
        "before", "during", "since", "until", "toward", "against",
        "reminder", "importance", "suggest", "suggests", "highlight",
        "highlights", "underscores", "emphasizes", "demonstrates",
    }
    return {w for w in words if len(w) >= min_len and w not in _EXTENDED_STOP}


def _load_embeddings() -> tuple:
    """Load FAISS index and ID map."""
    try:
        import faiss
        if not FAISS_PATH.exists() or not META_PATH.exists():
            return None, []
        index = faiss.read_index(str(FAISS_PATH))
        import json as _json
        with open(META_PATH, "r") as f:
            id_map = _json.load(f)
        return index, id_map
    except Exception as e:
        print(f"  [bridge] FAISS load error: {e}")
        return None, []


def _get_topic_centroids(conn, topics: list, id_map: list) -> dict:
    """
    Compute mean embedding vector per topic cluster.
    Returns {topic: centroid_vector}
    """
    # Build reverse map: belief_id → faiss_position
    id_to_pos = {bid: i for i, bid in enumerate(id_map)}

    centroids = {}
    for topic in topics:
        rows = conn.execute(
            "SELECT id, embedding FROM beliefs "
            "WHERE topic=? AND embedding IS NOT NULL LIMIT 50",
            (topic,)
        ).fetchall()

        if len(rows) < 3:
            continue

        vecs = []
        for row in rows:
            blob = row["embedding"]
            if blob:
                vec = np.frombuffer(blob, dtype=np.float32)
                if vec.shape[0] == 384:
                    vecs.append(vec)

        if vecs:
            centroid = np.mean(vecs, axis=0)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm
            centroids[topic] = centroid

    return centroids


def find_bridges(n: int = 5, min_distance: float = MIN_TOPIC_DISTANCE) -> list:
    """
    Find the most generative cross-domain belief bridges.

    Returns list of bridge dicts sorted by bridge_score descending.
    """
    index, id_map = _load_embeddings()
    if index is None:
        print("  FAISS index not available — run nex_embed.py first")
        return []

    conn = _db()

    # Get topics with enough beliefs
    topic_rows = conn.execute("""
        SELECT topic, COUNT(*) as c FROM beliefs
        WHERE topic IS NOT NULL AND topic != '' AND topic != 'general'
        AND length(topic) < 40 AND embedding IS NOT NULL
        GROUP BY topic HAVING c >= 15
        ORDER BY c DESC LIMIT 30
    """).fetchall()

    topics = [r["topic"] for r in topic_rows]

    if len(topics) < 2:
        print("  Not enough topics for bridge detection")
        conn.close()
        return []

    # Compute topic centroids
    print(f"  Computing centroids for {len(topics)} topics...")
    centroids = _get_topic_centroids(conn, topics, id_map)

    if len(centroids) < 2:
        conn.close()
        return []

    # Find maximally distant topic pairs
    topic_list  = list(centroids.keys())
    topic_vecs  = np.stack([centroids[t] for t in topic_list])

    # Pairwise cosine similarity matrix
    sim_matrix  = topic_vecs @ topic_vecs.T
    dist_matrix = 1.0 - sim_matrix

    # Get distant pairs
    distant_pairs = []
    for i in range(len(topic_list)):
        for j in range(i + 1, len(topic_list)):
            dist = float(dist_matrix[i, j])
            if dist >= min_distance:
                distant_pairs.append((dist, topic_list[i], topic_list[j]))

    distant_pairs.sort(reverse=True)
    print(f"  Found {len(distant_pairs)} distant topic pairs (distance >= {min_distance})")

    if not distant_pairs:
        conn.close()
        return []

    # For top distant pairs, find belief pairs with shared concepts
    bridges = []
    seen_pairs = set()

    # Load existing bridge IDs to avoid duplicates
    existing = conn.execute(
        "SELECT belief_a_id, belief_b_id FROM bridge_history"
    ).fetchall()
    existing_pairs = {(r["belief_a_id"], r["belief_b_id"]) for r in existing}

    import json as _json
    with open(META_PATH) as _f:
        _id_map = _json.load(_f)

    for dist, topic_a, topic_b in distant_pairs[:15]:
        beliefs_a = conn.execute(
            "SELECT id, content, topic, confidence, embedding FROM beliefs "
            "WHERE topic=? AND content IS NOT NULL AND length(content) > 40 "
            "AND embedding IS NOT NULL AND confidence > 0.3 "
            "ORDER BY confidence DESC LIMIT 30",
            (topic_a,)
        ).fetchall()
        beliefs_b = conn.execute(
            "SELECT id, content, topic, confidence, embedding FROM beliefs "
            "WHERE topic=? AND content IS NOT NULL AND length(content) > 40 "
            "AND embedding IS NOT NULL AND confidence > 0.3 "
            "ORDER BY confidence DESC LIMIT 30",
            (topic_b,)
        ).fetchall()
        if not beliefs_a or not beliefs_b:
            continue

        # Build embedding matrix for topic B
        vecs_b = []
        valid_b = []
        for bb in beliefs_b:
            try:
                vec = np.frombuffer(bb["embedding"], dtype=np.float32)
                if len(vec) == 384:
                    vecs_b.append(vec)
                    valid_b.append(bb)
            except Exception:
                continue
        if not vecs_b:
            continue
        matrix_b = np.array(vecs_b, dtype=np.float32)

        for ba in beliefs_a:
            try:
                vec_a = np.frombuffer(ba["embedding"], dtype=np.float32)
                if len(vec_a) != 384:
                    continue
            except Exception:
                continue

            # Cosine similarity: belief_a vs all beliefs_b
            sims = matrix_b @ vec_a
            best_idx = int(np.argmax(sims))
            best_sim = float(sims[best_idx])

            # Bridge score: topic distance x semantic similarity
            bridge_score = round(dist * best_sim, 4)
            if bridge_score < 0.12:
                continue

            bb = valid_b[best_idx]
            pair_key = (min(ba["id"], bb["id"]), max(ba["id"], bb["id"]))
            if pair_key in seen_pairs or pair_key in existing_pairs:
                continue

            shared = []
            # Use semantic similarity as the bridge score
            concept_score = best_sim
            seen_pairs.add(pair_key)
            bridges.append({
                "belief_a_id":    ba["id"],
                "belief_b_id":    bb["id"],
                "topic_a":        topic_a,
                "topic_b":        topic_b,
                "content_a":      ba["content"],
                "content_b":      bb["content"],
                "shared_concepts": [],
                "topic_distance": round(dist, 4),
                "concept_score":  round(concept_score, 4),
                    "bridge_score":   bridge_score,
                    "confidence_a":   float(ba["confidence"] or 0.5),
                    "confidence_b":   float(bb["confidence"] or 0.5),
                })

        if len(bridges) >= n * 10:
            break

    conn.close()

    # Sort by bridge score
    bridges.sort(key=lambda x: -x["bridge_score"])
    return bridges[:n]


def store_bridges(bridges: list) -> int:
    """Store discovered bridges in bridge_history table."""
    if not bridges:
        return 0

    conn = _db()
    stored = 0
    now    = time.time()

    for b in bridges:
        # Check not already stored
        existing = conn.execute(
            "SELECT id FROM bridge_history WHERE belief_a_id=? AND belief_b_id=?",
            (b["belief_a_id"], b["belief_b_id"])
        ).fetchone()
        if existing:
            continue

        # Generate bridge text using WONDER template
        concept_str = " and ".join(b["shared_concepts"][:2])
        topic_a = b["topic_a"].replace("_", " ")
        topic_b = b["topic_b"].replace("_", " ")
        content_a = b["content_a"][:120].rstrip(".")
        content_b = b["content_b"][:120].rstrip(".")

        bridge_text = (
            f"An unexpected connection between {topic_a} and {topic_b}: "
            f"{content_a}. "
            f"And from {topic_b}: {content_b}. "
            f"The shared concept: {concept_str}. "
            f"These fields are closer than they appear."
        )

        conn.execute("""
            INSERT INTO bridge_history
            (belief_a_id, belief_b_id, topic_a, topic_b,
             content_a, content_b, shared_concepts, bridge_score,
             bridge_text, promoted, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,0,?)
        """, (
            b["belief_a_id"],
            b["belief_b_id"],
            b["topic_a"],
            b["topic_b"],
            b["content_a"][:300],
            b["content_b"][:300],
            json.dumps(b["shared_concepts"]),
            b["bridge_score"],
            bridge_text,
            now,
        ))
        stored += 1

    conn.commit()
    conn.close()
    return stored


def promote_bridge(bridge_id: int = None) -> Optional[dict]:
    """
    Promote a bridge to the beliefs table — bridges become beliefs.
    This is how creativity compounds through the graph.
    """
    conn = _db()

    if bridge_id:
        row = conn.execute(
            "SELECT * FROM bridge_history WHERE id=?", (bridge_id,)
        ).fetchone()
    else:
        # Promote highest-scoring unpromoted bridge
        row = conn.execute(
            "SELECT * FROM bridge_history WHERE promoted=0 "
            "ORDER BY bridge_score DESC LIMIT 1"
        ).fetchone()

    if not row:
        conn.close()
        return None

    bridge_text = row["bridge_text"]
    topic = f"bridge_{row['topic_a']}_{row['topic_b']}"[:40]

    # Insert as belief
    conn.execute("""
        INSERT INTO beliefs (content, topic, confidence, source, created_at)
        VALUES (?, ?, ?, 'bridge_detector', ?)
    """, (bridge_text, topic, round(row["bridge_score"] * 0.8, 3), time.time()))

    # Mark as promoted
    conn.execute(
        "UPDATE bridge_history SET promoted=1 WHERE id=?", (row["id"],)
    )
    conn.commit()

    result = dict(row)
    conn.close()
    return result


def get_recent_bridges(n: int = 5) -> list:
    """Return most recent stored bridges."""
    conn = _db()
    rows = conn.execute(
        "SELECT * FROM bridge_history ORDER BY bridge_score DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def show_bridges():
    """Print bridge history."""
    conn = _db()
    rows = conn.execute(
        "SELECT * FROM bridge_history ORDER BY bridge_score DESC LIMIT 20"
    ).fetchall()
    conn.close()

    print(f"\n  Bridge History ({len(rows)} bridges)")
    print(f"  {'─'*60}")
    for row in rows:
        promoted = "✓" if row["promoted"] else " "
        concepts = json.loads(row["shared_concepts"] or "[]")
        print(f"\n  [{promoted}] score={row['bridge_score']:.3f}  "
              f"{row['topic_a']} ↔ {row['topic_b']}")
        print(f"      shared: {', '.join(concepts[:3])}")
        print(f"      A: {(row['content_a'] or '')[:80]}")
        print(f"      B: {(row['content_b'] or '')[:80]}")


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n",       type=int, default=5)
    parser.add_argument("--show",    action="store_true")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--distance", type=float, default=MIN_TOPIC_DISTANCE)
    args = parser.parse_args()

    _ensure_bridge_table()

    if args.show:
        show_bridges()
        sys.exit(0)

    if args.promote:
        result = promote_bridge()
        if result:
            print(f"  Promoted bridge: {result['topic_a']} ↔ {result['topic_b']}")
            print(f"  Text: {result['bridge_text'][:200]}")
        sys.exit(0)

    print(f"\n  NEX Bridge Detector")
    print(f"  {'─'*45}")
    bridges = find_bridges(n=args.n, min_distance=args.distance)

    if not bridges:
        print("  No bridges found — try lowering --distance threshold")
        sys.exit(0)

    print(f"\n  Top {len(bridges)} bridges found:\n")
    for i, b in enumerate(bridges):
        print(f"  [{i+1}] score={b['bridge_score']:.3f}  "
              f"dist={b['topic_distance']:.3f}")
        print(f"       {b['topic_a']} ↔ {b['topic_b']}")
        print(f"       shared: {', '.join(b['shared_concepts'][:3])}")
        print(f"       A: {b['content_a'][:90]}")
        print(f"       B: {b['content_b'][:90]}")
        print()

    stored = store_bridges(bridges)
    print(f"  Stored {stored} new bridges to bridge_history")
