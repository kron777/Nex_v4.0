#!/usr/bin/env python3
"""
nex_native_opinions.py — NEX Build 4: Native Opinions Engine
=============================================================
Place at: ~/Desktop/nex/nex_native_opinions.py

NEX knows what she thinks. Mathematically. Without asking an LLM.

For each topic cluster in the belief graph:
  1. Retrieve all beliefs in that topic
  2. Score each belief's sentiment polarity (+1 positive / -1 negative)
  3. Weight by confidence
  4. Aggregate → stance_score [-1.0 to +1.0]
  5. Compute strength from belief count + confidence spread
  6. Write to opinions table

Sentiment scoring uses:
  - VADER (if available) — sentence-level sentiment
  - Lexicon fallback — opposition pairs + positive/negative word lists
  - No LLM required

This replaces LLM-generated opinions with graph-computed positions.
NEX's opinion on any topic is the mathematical centre of gravity
of her belief cluster on that topic.

Usage:
  python3 nex_native_opinions.py              # compute all opinions
  python3 nex_native_opinions.py --topic ai   # single topic
  python3 nex_native_opinions.py --show       # print all current opinions
  python3 nex_native_opinions.py --check      # compare native vs stored

Wire into scheduler:
  from nex_native_opinions import update_all_opinions
  update_all_opinions()   # call every N cycles
"""

import sqlite3
import json
import math
import re
import time
import argparse
import sys
from pathlib import Path
from typing import Optional

CFG_PATH = Path("~/.config/nex").expanduser()
DB_PATH  = CFG_PATH / "nex.db"

# Minimum beliefs in a topic to form an opinion
MIN_BELIEFS_FOR_OPINION = 5

# ── Sentiment lexicon ─────────────────────────────────────────────────────────
# Positive signal words (contribute +1 polarity)
_POSITIVE = {
    "effective","beneficial","important","significant","improves","supports",
    "enables","advances","solves","robust","reliable","valid","correct",
    "true","proven","confirmed","evidence","demonstrates","shows","suggests",
    "increases","enhances","promotes","achieves","succeeds","works","useful",
    "valuable","promising","compelling","strong","clear","established",
    "essential","necessary","fundamental","critical","key","core","central",
    "aligned","safe","positive","good","better","best","optimal","superior",
    "capable","powerful","intelligent","coherent","consistent","stable",
}

# Negative signal words (contribute -1 polarity)
_NEGATIVE = {
    "ineffective","harmful","dangerous","fails","undermines","prevents",
    "limits","constrains","reduces","decreases","weakens","invalid","false",
    "disproven","refuted","myth","incorrect","wrong","flawed","broken",
    "unreliable","unstable","incoherent","inconsistent","misaligned","unsafe",
    "problematic","difficult","challenging","insufficient","inadequate",
    "uncertain","unclear","unknown","unresolved","contested","disputed",
    "skeptical","doubt","concern","risk","threat","danger","failure","error",
    "bias","discrimination","unfair","unjust","harmful","toxic","corrupt",
}

# Strong negation words (flip polarity of following word)
_NEGATIONS = {"not","no","never","neither","nor","without","lack","lacking",
              "absent","absence","impossible","cannot","can't","doesn't","isn't"}


def _sentiment_lexicon(text: str) -> float:
    """
    Fast lexicon-based sentiment. Returns -1.0 to +1.0.
    Handles negation within a 3-word window.
    """
    words = re.sub(r'[^a-z ]', ' ', text.lower()).split()
    if not words:
        return 0.0

    score = 0.0
    count = 0
    for i, w in enumerate(words):
        # Check for negation in preceding 3 words
        negated = any(words[max(0,i-j)] in _NEGATIONS for j in range(1,4))
        if w in _POSITIVE:
            score += -1.0 if negated else 1.0
            count += 1
        elif w in _NEGATIVE:
            score += 1.0 if negated else -1.0
            count += 1

    return round(score / max(count, 1), 4) if count > 0 else 0.0


def _sentiment_vader(text: str) -> Optional[float]:
    """VADER sentiment if available. Returns compound score or None."""
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _vader = SentimentIntensityAnalyzer()
        return round(_vader.polarity_scores(text)["compound"], 4)
    except ImportError:
        return None


def belief_sentiment(content: str) -> float:
    """
    Score a belief's sentiment polarity.
    Tries VADER first, falls back to lexicon.
    Returns -1.0 (negative) to +1.0 (positive).
    """
    vader = _sentiment_vader(content)
    if vader is not None:
        return vader
    return _sentiment_lexicon(content)


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def compute_topic_opinion(topic: str, beliefs: list) -> Optional[dict]:
    """
    Compute NEX's opinion on a topic from her belief cluster.

    stance_score: confidence-weighted mean sentiment
      > +0.3  = positive stance
      < -0.3  = negative/skeptical stance
      ≈  0.0  = genuinely divided / uncertain

    strength: how settled the opinion is
      = mean confidence * log1p(belief_count) / log1p(200)
      High count + high confidence = strong opinion
    """
    if len(beliefs) < MIN_BELIEFS_FOR_OPINION:
        return None

    weighted_sentiment = 0.0
    total_weight       = 0.0
    belief_ids         = []
    confidences        = []

    for b in beliefs:
        content = b.get("content", "") or ""
        conf    = float(b.get("confidence", 0.5) or 0.5)
        bid     = b.get("id")

        sentiment = belief_sentiment(content)

        weighted_sentiment += sentiment * conf
        total_weight       += conf
        belief_ids.append(bid)
        confidences.append(conf)

    if total_weight == 0:
        return None

    stance_score = round(weighted_sentiment / total_weight, 4)
    mean_conf    = sum(confidences) / len(confidences)

    # Strength: settled if high confidence + many beliefs
    strength = round(
        mean_conf * (math.log1p(len(beliefs)) / math.log1p(200)),
        4
    )
    strength = min(1.0, strength)

    # Top beliefs by confidence — stored as evidence
    top_ids = [b["id"] for b in sorted(beliefs, key=lambda x: -float(x.get("confidence",0)))[:10]]

    return {
        "topic":        topic,
        "stance_score": stance_score,
        "strength":     strength,
        "belief_count": len(beliefs),
        "belief_ids":   json.dumps(top_ids),
        "mean_conf":    round(mean_conf, 4),
    }


def update_topic_opinion(conn, opinion: dict):
    """Upsert a computed opinion into the opinions table."""
    existing = conn.execute(
        "SELECT id FROM opinions WHERE topic=?", (opinion["topic"],)
    ).fetchone()

    now = time.time()
    if existing:
        conn.execute("""
            UPDATE opinions
            SET stance_score=?, strength=?, belief_ids=?, updated_at=?
            WHERE topic=?
        """, (
            opinion["stance_score"],
            opinion["strength"],
            opinion["belief_ids"],
            now,
            opinion["topic"],
        ))
    else:
        conn.execute("""
            INSERT INTO opinions (topic, stance_score, strength, belief_ids, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            opinion["topic"],
            opinion["stance_score"],
            opinion["strength"],
            opinion["belief_ids"],
            now,
        ))


def update_all_opinions(min_beliefs: int = MIN_BELIEFS_FOR_OPINION,
                        verbose: bool = True) -> dict:
    """
    Recompute all opinions from the current belief graph.
    Returns summary dict.
    """
    conn = _db()

    # Load all beliefs grouped by topic
    rows = conn.execute("""
        SELECT id, content, topic, confidence
        FROM beliefs
        WHERE content IS NOT NULL AND length(content) > 10
        AND topic IS NOT NULL AND topic != ''
        ORDER BY topic, confidence DESC
    """).fetchall()

    # Group by topic
    by_topic: dict[str, list] = {}
    for row in rows:
        topic = (row["topic"] or "").strip().lower()
        if not topic or len(topic) > 60:
            continue
        # Skip junk topics (bridge artifacts, single-word noise)
        if "bridge:" in topic or "↔" in topic or "+" in topic:
            continue
        if topic not in by_topic:
            by_topic[topic] = []
        by_topic[topic].append(dict(row))

    computed = 0
    skipped  = 0
    opinions_written = []

    for topic, beliefs in sorted(by_topic.items()):
        opinion = compute_topic_opinion(topic, beliefs)
        if opinion is None:
            skipped += 1
            continue

        update_topic_opinion(conn, opinion)
        opinions_written.append(opinion)
        computed += 1

    conn.commit()
    conn.close()

    if verbose:
        print(f"\n  Native Opinions Engine")
        print(f"  {'─'*45}")
        print(f"  Topics processed: {computed + skipped}")
        print(f"  Opinions written: {computed}")
        print(f"  Skipped (< {min_beliefs} beliefs): {skipped}")
        print(f"\n  Top opinions by strength:")
        top = sorted(opinions_written, key=lambda x: -x["strength"])[:10]
        for op in top:
            direction = "+" if op["stance_score"] > 0.1 else ("-" if op["stance_score"] < -0.1 else "~")
            print(f"  {direction} {op['topic']:<30} stance={op['stance_score']:+.3f}  "
                  f"strength={op['strength']:.3f}  n={op['belief_count']}")

    return {
        "computed": computed,
        "skipped":  skipped,
        "opinions": opinions_written,
    }


def update_single_topic(topic: str) -> Optional[dict]:
    """Recompute opinion for a single topic."""
    conn = _db()
    rows = conn.execute("""
        SELECT id, content, topic, confidence
        FROM beliefs
        WHERE lower(topic)=? AND content IS NOT NULL
        ORDER BY confidence DESC
    """, (topic.lower(),)).fetchall()
    conn.close()

    if not rows:
        print(f"  No beliefs found for topic: {topic}")
        return None

    beliefs = [dict(r) for r in rows]
    opinion = compute_topic_opinion(topic.lower(), beliefs)

    if opinion:
        conn = _db()
        update_topic_opinion(conn, opinion)
        conn.commit()
        conn.close()
        print(f"  {topic}: stance={opinion['stance_score']:+.3f}  "
              f"strength={opinion['strength']:.3f}  n={opinion['belief_count']}")

    return opinion


def show_opinions():
    """Print all current opinions sorted by strength."""
    conn = _db()
    rows = conn.execute("""
        SELECT topic, stance_score, strength, belief_ids, updated_at
        FROM opinions
        ORDER BY strength DESC
    """).fetchall()
    conn.close()

    print(f"\n  Current opinions ({len(rows)} topics):")
    print(f"  {'─'*55}")
    for row in rows:
        try:
            n = len(json.loads(row["belief_ids"] or "[]"))
        except Exception:
            n = 0
        stance = float(row["stance_score"] or 0)
        strength = float(row["strength"] or 0)
        direction = "+" if stance > 0.1 else ("-" if stance < -0.1 else "~")
        print(f"  {direction} {row['topic']:<32} "
              f"stance={stance:+.3f}  strength={strength:.3f}  n={n}")


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", type=str, default=None, help="Recompute single topic")
    parser.add_argument("--show",  action="store_true", help="Show all current opinions")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")
    args = parser.parse_args()

    if args.show:
        show_opinions()
        sys.exit(0)

    if args.topic:
        update_single_topic(args.topic)
        sys.exit(0)

    update_all_opinions(verbose=not args.quiet)
