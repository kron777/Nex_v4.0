#!/usr/bin/env python3
"""
nex_native_opinions.py  —  Native Opinions Engine
================================================================
NEX v1.0 — Build 4

Replaces LLM opinion generation entirely.

Algorithm:
  For each topic cluster in the beliefs table:
    1. Gather all beliefs in cluster (confidence > threshold)
    2. Embed topic centroid via FAISS
    3. VADER sentiment per belief, weighted by confidence
    4. Sum → stance_score [-1.0, +1.0]
    5. Strength = normalised spread of confidence-weighted beliefs
    6. Write to opinions table (INSERT OR REPLACE)

  Contradiction resolution:
    If two beliefs in same cluster have opposing sentiment AND
    high cosine similarity → lower-confidence belief marked uncertain.

Called from run.py every loop cycle (no cycle skip — opinions
should always reflect current belief state).

CLI:
    python3 nex_native_opinions.py --run       # one full pass
    python3 nex_native_opinions.py --show      # print current opinions table
    python3 nex_native_opinions.py --topic ai  # opinions for one topic
"""

import argparse
import json
import logging
import math
import sqlite3
import struct
import time
from pathlib import Path

log = logging.getLogger("nex.opinions")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

DB_PATH = Path.home() / ".config" / "nex" / "nex.db"

# ── Thresholds ────────────────────────────────────────────────────────────────

MIN_CONFIDENCE      = 0.30   # beliefs below this ignored for opinion forming
MIN_CLUSTER_SIZE    = 2      # need at least 2 beliefs to form an opinion
STRONG_OPINION      = 0.55   # |stance_score| above this = strong opinion
CONTRADICTION_SIM   = 0.78   # cosine similarity threshold for contradiction pair
SENTIMENT_FLIP      = 0.50   # sentiment delta above this = opposing sentiments
MAX_TOPICS          = 200    # cap to avoid runaway on huge DBs


# =============================================================================
# DB helpers
# =============================================================================

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def _blob_to_vec(blob: bytes):
    """Deserialise embedding BLOB → numpy float32 array."""
    import numpy as np
    if blob is None:
        return None
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def _cosine(a, b) -> float:
    import numpy as np
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# =============================================================================
# VADER loader (lazy)
# =============================================================================

_vader = None

def _get_vader():
    global _vader
    if _vader is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _vader = SentimentIntensityAnalyzer()
    return _vader


# =============================================================================
# Topic clusters
# =============================================================================

def _load_topic_clusters(con: sqlite3.Connection) -> dict[str, list[dict]]:
    """
    Group beliefs by topic. Returns:
        { topic_str: [ {id, content, confidence, embedding, sentiment}, ... ] }
    Only beliefs with confidence >= MIN_CONFIDENCE included.
    Topics normalised to base domain (strip keyphrase suffix for grouping).
    """
    rows = con.execute("""
        SELECT id, content, topic, confidence, embedding
        FROM beliefs
        WHERE confidence >= ?
          AND content IS NOT NULL
          AND topic IS NOT NULL
          AND topic NOT IN ('', 'None', 'general', 'unknown', 'auto_learn')
        ORDER BY topic, confidence DESC
    """, (MIN_CONFIDENCE,)).fetchall()

    vader  = _get_vader()
    clusters: dict[str, list[dict]] = {}

    for r in rows:
        # Normalise topic: use base domain only (before '/')
        raw_topic = r["topic"] or "general"
        topic     = raw_topic.split("/")[0].strip()
        if not topic or len(topic) > 80:
            continue

        sentiment = vader.polarity_scores(r["content"])["compound"]
        vec       = _blob_to_vec(r["embedding"])

        clusters.setdefault(topic, []).append({
            "id":         r["id"],
            "content":    r["content"],
            "confidence": r["confidence"],
            "sentiment":  sentiment,
            "vec":        vec,
        })

    return clusters


# =============================================================================
# Stance computation
# =============================================================================

def _compute_stance(beliefs: list[dict]) -> tuple[float, float]:
    """
    Returns (stance_score, strength).

    stance_score:
      Weighted mean of sentiment values, weights = confidence.
      Range: [-1.0, +1.0]
      Positive → NEX leans toward affirming this topic
      Negative → NEX leans skeptical/critical

    strength:
      How much the beliefs agree with each other.
      High confidence + consistent sentiment → high strength.
      Range: [0.0, 1.0]
    """
    if not beliefs:
        return 0.0, 0.0

    total_weight  = sum(b["confidence"] for b in beliefs)
    if total_weight == 0:
        return 0.0, 0.0

    # Weighted sentiment mean
    weighted_sum  = sum(b["sentiment"] * b["confidence"] for b in beliefs)
    stance        = weighted_sum / total_weight

    # Strength: based on confidence mass and sentiment consistency
    # High strength when beliefs are confident AND sentiment is consistent
    mean_conf     = total_weight / len(beliefs)
    sentiments    = [b["sentiment"] for b in beliefs]
    sent_std      = _std(sentiments)
    consistency   = max(0.0, 1.0 - sent_std)   # low variance = high consistency
    strength      = mean_conf * consistency

    return round(float(stance), 4), round(float(strength), 4)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


# =============================================================================
# Contradiction detection within cluster
# =============================================================================

def _resolve_contradictions(con: sqlite3.Connection,
                              beliefs: list[dict],
                              topic: str) -> int:
    """
    Within a topic cluster, find belief pairs that are:
      - Semantically similar (cosine >= CONTRADICTION_SIM)
      - Sentimentally opposing (|Δsentiment| >= SENTIMENT_FLIP)

    For each such pair:
      - Record in contradiction_pairs table
      - Lower-confidence belief has confidence reduced by 15%
        (soft resolution — doesn't delete, just de-emphasises)

    Returns count of pairs resolved.
    """
    resolved = 0
    beliefs_with_vec = [b for b in beliefs if b["vec"] is not None]

    for i in range(len(beliefs_with_vec)):
        for j in range(i + 1, len(beliefs_with_vec)):
            a = beliefs_with_vec[i]
            b = beliefs_with_vec[j]

            sim       = _cosine(a["vec"], b["vec"])
            sent_diff = abs(a["sentiment"] - b["sentiment"])

            if sim >= CONTRADICTION_SIM and sent_diff >= SENTIMENT_FLIP:
                # Record pair
                try:
                    con.execute("""
                        INSERT OR IGNORE INTO contradiction_pairs
                            (belief_a_id, belief_b_id, resolution)
                        VALUES (?, ?, ?)
                    """, (
                        min(a["id"], b["id"]),
                        max(a["id"], b["id"]),
                        f"auto_resolved/{topic}"
                    ))
                except Exception:
                    pass

                # Soften the lower-confidence belief
                loser = a if a["confidence"] <= b["confidence"] else b
                new_conf = max(MIN_CONFIDENCE, loser["confidence"] * 0.85)
                try:
                    con.execute("""
                        UPDATE beliefs SET confidence = ?
                        WHERE id = ?
                    """, (round(new_conf, 4), loser["id"]))
                    loser["confidence"] = new_conf   # update in-memory too
                except Exception:
                    pass

                resolved += 1
                log.debug(
                    f"  [contra] {topic}: pair ({a['id']},{b['id']}) "
                    f"sim={sim:.2f} Δsent={sent_diff:.2f}"
                )

    return resolved


# =============================================================================
# Topic vector (centroid of belief embeddings)
# =============================================================================

def _topic_centroid(beliefs: list[dict]):
    """Mean of belief embedding vectors for this topic cluster."""
    import numpy as np
    vecs = [b["vec"] for b in beliefs if b["vec"] is not None]
    if not vecs:
        return None
    stack = np.stack(vecs, axis=0)
    return stack.mean(axis=0)


def _vec_to_blob(vec) -> bytes | None:
    if vec is None:
        return None
    return struct.pack(f"{len(vec)}f", *vec.tolist())


# =============================================================================
# Main cycle
# =============================================================================

def run_opinions_cycle(verbose: bool = False) -> dict:
    """
    Full opinions pass. Called each loop cycle from run.py.

    Returns:
        {
          "topics_processed": int,
          "opinions_written": int,
          "contradictions_resolved": int,
          "strong_opinions": int,
        }
    """
    t0  = time.time()
    con = _db()

    clusters     = _load_topic_clusters(con)
    topics       = list(clusters.keys())[:MAX_TOPICS]

    opinions_written       = 0
    contradictions_resolved = 0
    strong_opinions        = 0

    for topic in topics:
        beliefs = clusters[topic]
        if len(beliefs) < MIN_CLUSTER_SIZE:
            continue

        # Contradiction resolution first — may adjust confidence values
        n_contra = _resolve_contradictions(con, beliefs, topic)
        contradictions_resolved += n_contra

        # Compute stance
        stance, strength = _compute_stance(beliefs)

        # Topic centroid vector
        centroid = _topic_centroid(beliefs)
        vec_blob = _vec_to_blob(centroid)

        # Belief IDs for this cluster
        belief_ids = json.dumps([b["id"] for b in beliefs])

        # Write to opinions table
        try:
            con.execute("""
                INSERT INTO opinions
                    (topic, topic_vector, stance_score, strength, belief_ids, updated_at)
                VALUES (?, ?, ?, ?, ?, unixepoch('now'))
                ON CONFLICT(topic) DO UPDATE SET
                    topic_vector = excluded.topic_vector,
                    stance_score = excluded.stance_score,
                    strength     = excluded.strength,
                    belief_ids   = excluded.belief_ids,
                    updated_at   = excluded.updated_at
            """, (topic, vec_blob, stance, strength, belief_ids))
            opinions_written += 1
        except Exception as e:
            log.warning(f"  [opinions] write failed for '{topic}': {e}")
            continue

        if abs(stance) >= STRONG_OPINION:
            strong_opinions += 1

        if verbose:
            direction = "+" if stance >= 0 else ""
            print(f"  {topic:<35} stance={direction}{stance:+.3f}  "
                  f"strength={strength:.3f}  n={len(beliefs)}")

    con.commit()
    con.close()

    elapsed = round(time.time() - t0, 2)
    stats = {
        "topics_processed":       len(topics),
        "opinions_written":       opinions_written,
        "contradictions_resolved": contradictions_resolved,
        "strong_opinions":        strong_opinions,
        "elapsed_s":              elapsed,
    }
    log.info(
        f"[opinions] {opinions_written} opinions · "
        f"{contradictions_resolved} contradictions · "
        f"{strong_opinions} strong · {elapsed}s"
    )
    return stats


# =============================================================================
# Query helpers (used by voice layer and TUI)
# =============================================================================

def get_opinion(topic: str) -> dict | None:
    """
    Return NEX's current opinion on a topic (or None if no opinion formed).
    Topic matching: exact first, then prefix match on base domain.
    """
    con = _db()
    row = con.execute(
        "SELECT * FROM opinions WHERE topic = ?", (topic,)
    ).fetchone()

    if not row:
        # Try prefix match
        row = con.execute(
            "SELECT * FROM opinions WHERE topic LIKE ? ORDER BY strength DESC LIMIT 1",
            (f"{topic}%",)
        ).fetchone()

    con.close()
    if not row:
        return None

    return {
        "topic":        row["topic"],
        "stance_score": row["stance_score"],
        "strength":     row["strength"],
        "belief_ids":   json.loads(row["belief_ids"] or "[]"),
        "updated_at":   row["updated_at"],
    }


def get_strong_opinions(min_strength: float = 0.4,
                         min_stance: float = 0.3) -> list[dict]:
    """
    Return all opinions where NEX has a clear, strong stance.
    Used by voice layer to select assertive expression templates.
    """
    con = _db()
    rows = con.execute("""
        SELECT topic, stance_score, strength, belief_ids, updated_at
        FROM opinions
        WHERE strength >= ?
          AND ABS(stance_score) >= ?
        ORDER BY strength DESC
    """, (min_strength, min_stance)).fetchall()
    con.close()

    return [
        {
            "topic":        r["topic"],
            "stance_score": r["stance_score"],
            "strength":     r["strength"],
            "belief_ids":   json.loads(r["belief_ids"] or "[]"),
        }
        for r in rows
    ]


def get_all_opinions() -> list[dict]:
    con = _db()
    rows = con.execute(
        "SELECT topic, stance_score, strength, belief_ids, updated_at "
        "FROM opinions ORDER BY strength DESC"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


# =============================================================================
# CLI
# =============================================================================

def main():
    ap = argparse.ArgumentParser(
        description="NEX v1.0 — Native Opinions Engine (Build 4)"
    )
    ap.add_argument("--run",     action="store_true", help="Run one full opinions cycle")
    ap.add_argument("--show",    action="store_true", help="Print current opinions table")
    ap.add_argument("--topic",   type=str,            help="Show opinion for a specific topic")
    ap.add_argument("--verbose", action="store_true", help="Print per-topic detail during --run")
    args = ap.parse_args()

    if args.run:
        print("\nRunning native opinions cycle ...\n")
        stats = run_opinions_cycle(verbose=args.verbose)
        print(f"\n  topics processed:        {stats['topics_processed']}")
        print(f"  opinions written:        {stats['opinions_written']}")
        print(f"  contradictions resolved: {stats['contradictions_resolved']}")
        print(f"  strong opinions:         {stats['strong_opinions']}")
        print(f"  elapsed:                 {stats['elapsed_s']}s")
        print(f"\n[✓] Build 4 — native opinions running.\n")
        return

    if args.topic:
        op = get_opinion(args.topic)
        if not op:
            print(f"  No opinion formed on '{args.topic}' yet.")
        else:
            direction = "positive" if op["stance_score"] >= 0 else "negative"
            print(f"\n  Topic:   {op['topic']}")
            print(f"  Stance:  {op['stance_score']:+.3f}  ({direction})")
            print(f"  Strength:{op['strength']:.3f}")
            print(f"  Beliefs: {len(op['belief_ids'])} contributing")
        return

    if args.show:
        opinions = get_all_opinions()
        if not opinions:
            print("  No opinions formed yet. Run --run first.")
            return
        print(f"\n  {'TOPIC':<35} {'STANCE':>8}  {'STRENGTH':>8}  {'BELIEFS':>7}")
        print(f"  {'─'*35} {'─'*8}  {'─'*8}  {'─'*7}")
        for op in opinions:
            ids   = json.loads(op["belief_ids"] or "[]")
            sign  = "+" if op["stance_score"] >= 0 else ""
            print(
                f"  {op['topic']:<35} "
                f"{sign}{op['stance_score']:>+.3f}   "
                f"{op['strength']:>7.3f}  "
                f"{len(ids):>7}"
            )
        print(f"\n  Total: {len(opinions)} topics\n")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
