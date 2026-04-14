#!/usr/bin/env python3
"""
nex_graph_curiosity.py — Graph-Native Curiosity Engine
=======================================================
Place at: ~/Desktop/nex/nex_graph_curiosity.py

Curiosity is the negative space of the belief graph.
What NEX doesn't yet believe is what she wants to find.

Gap types derived directly from graph state:

  THIN      — topic has < THIN_THRESHOLD beliefs (sparse coverage)
              NEX knows the word but not the substance
  CONTESTED — topic has high contradiction density
              NEX holds conflicting beliefs — needs resolution
  DEPTH     — topic has beliefs but low avg confidence
              NEX has surface knowledge but no depth
  BRIDGE    — two distant topics share a latent concept
              NEX can see connection but needs to understand why
  MISSING   — topic referenced in beliefs but has no cluster
              NEX keeps mentioning something she hasn't studied

Priority = drive_weight(topic) × gap_severity × recency_boost
  drive_weight: how much an active drive cares about this topic
  gap_severity: how bad the gap is (0.0-1.0)
  recency_boost: recently activated topics get priority boost

This replaces the flat-file, LLM-driven curiosity with
pure graph-derived need. NEX searches for what her mind needs.

Usage:
  python3 nex_graph_curiosity.py              # detect + show gaps
  python3 nex_graph_curiosity.py --fill       # generate search queries
  python3 nex_graph_curiosity.py --top 10     # show top N gaps

  from nex_graph_curiosity import detect_gaps, top_queries
  gaps = detect_gaps()
  queries = top_queries(n=5)
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
from collections import defaultdict

CFG_PATH = Path("~/.config/nex").expanduser()
DB_PATH  = CFG_PATH / "nex.db"

# Gap detection thresholds
THIN_THRESHOLD       = 30    # beliefs below this = THIN gap
DEPTH_CONF_THRESHOLD = 0.55  # avg confidence below this = DEPTH gap
CONTESTED_RATIO      = 0.15  # contradiction ratio above this = CONTESTED gap
MIN_BELIEFS_FOR_DEPTH = 10   # need at least this many to assess depth

# Priority weights
DRIVE_WEIGHT_SCALE   = 2.0   # multiplier when topic matches active drive
GLOW_WEIGHT_SCALE    = 1.5   # multiplier for recently activated topics


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _get_drive_topics() -> dict:
    """Return {topic: weight} from active drives."""
    weights = {}
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path("~/Desktop/nex").expanduser()))
        from nex_drives import get_topic_drive_weights
        weights = get_topic_drive_weights()
    except Exception:
        pass
    return weights


def _get_glow_topics() -> dict:
    """Return {topic: glow} from graph memory."""
    glows = {}
    try:
        from nex_graph_memory import hot_topics
        for entry in hot_topics(n=10):
            glows[entry["topic"]] = entry["glow"]
    except Exception:
        pass
    return glows


def _get_contradiction_density() -> dict:
    """Return {topic: contradiction_ratio} from contradiction_memory."""
    density = {}
    conn = _db()
    try:
        # Count contradictions per topic
        rows = conn.execute("""
            SELECT b.topic, COUNT(*) as c
            FROM contradiction_memory cm
            JOIN beliefs b ON (
                b.content = cm.belief_a OR b.content = cm.belief_b
            )
            WHERE b.topic IS NOT NULL
            GROUP BY b.topic
        """).fetchall()
        # Get total beliefs per topic for ratio
        totals = {r["topic"]: r["c"] for r in conn.execute(
            "SELECT topic, COUNT(*) as c FROM beliefs "
            "WHERE topic IS NOT NULL GROUP BY topic"
        ).fetchall()}
        for row in rows:
            topic = row["topic"]
            if topic and totals.get(topic, 0) > 0:
                density[topic] = round(row["c"] / totals[topic], 4)
    except Exception:
        pass
    finally:
        conn.close()
    return density


def detect_gaps(min_priority: float = 0.1) -> list:
    """
    Detect all gaps in the belief graph.
    Returns list of gap dicts sorted by priority descending.
    """
    conn = _db()
    drive_weights = _get_drive_topics()
    glow_topics   = _get_glow_topics()
    contradiction_density = _get_contradiction_density()

    # Get belief counts and avg confidence per topic
    topic_stats = {}
    rows = conn.execute("""
        SELECT topic,
               COUNT(*) as count,
               AVG(confidence) as avg_conf,
               MIN(confidence) as min_conf
        FROM beliefs
        WHERE topic IS NOT NULL AND topic != '' AND topic != 'general'
        AND length(topic) < 40
        AND topic NOT LIKE 'bridge_%'
        AND topic NOT LIKE '%+%'
        AND topic NOT LIKE '%:%'
        AND topic NOT LIKE 'arxiv%'
        AND topic NOT IN ('became','briefing','talking','lacked','response',
            'weight','between','identified','neutral','reflection',
            'mit_tech_review','truth_seeking','predictions','topics',
            'depth','specific','moltbook','discipline','navigating',
            'french','spanish','awareness','beliefs','knowledge')
        GROUP BY topic
    """).fetchall()

    for row in rows:
        topic_stats[row["topic"]] = {
            "count":    row["count"],
            "avg_conf": float(row["avg_conf"] or 0.5),
            "min_conf": float(row["min_conf"] or 0.0),
        }

    # Find MISSING topics — referenced in belief content but no cluster
    # Look for capitalized proper nouns / technical terms in beliefs
    # that don't have their own topic cluster
    existing_topics = set(topic_stats.keys())
    mentioned_topics = set()
    try:
        sample = conn.execute(
            "SELECT content FROM beliefs WHERE content IS NOT NULL "
            "ORDER BY confidence DESC LIMIT 500"
        ).fetchall()
        # Extract potential topic words (longer words, domain-specific)
        for row in sample:
            words = re.findall(r'\b[a-z][a-z_]{4,}\b', (row["content"] or "").lower())
            for w in words:
                if w not in existing_topics and len(w) > 5:
                    mentioned_topics.add(w)
    except Exception:
        pass

    conn.close()

    gaps = []
    now  = time.time()

    # ── THIN gaps ─────────────────────────────────────────────────────────
    for topic, stats in topic_stats.items():
        if stats["count"] < THIN_THRESHOLD:
            severity = 1.0 - (stats["count"] / THIN_THRESHOLD)
            drive_w  = drive_weights.get(topic, 0.3)
            glow_w   = glow_topics.get(topic, 0.0)
            priority = round(
                severity * (1.0 + drive_w * DRIVE_WEIGHT_SCALE +
                            glow_w * GLOW_WEIGHT_SCALE), 4
            )
            if priority >= min_priority:
                gaps.append({
                    "topic":       topic,
                    "gap_type":    "THIN",
                    "severity":    round(severity, 4),
                    "priority":    priority,
                    "belief_count": stats["count"],
                    "avg_conf":    stats["avg_conf"],
                    "drive_weight": drive_w,
                    "query":       _generate_query(topic, "THIN"),
                    "reason":      f"only {stats['count']} beliefs — sparse coverage",
                })

    # ── DEPTH gaps ────────────────────────────────────────────────────────
    for topic, stats in topic_stats.items():
        if (stats["count"] >= MIN_BELIEFS_FOR_DEPTH and
                stats["avg_conf"] < DEPTH_CONF_THRESHOLD):
            severity = 1.0 - (stats["avg_conf"] / DEPTH_CONF_THRESHOLD)
            drive_w  = drive_weights.get(topic, 0.3)
            glow_w   = glow_topics.get(topic, 0.0)
            priority = round(
                severity * 0.8 * (1.0 + drive_w * DRIVE_WEIGHT_SCALE +
                                  glow_w * GLOW_WEIGHT_SCALE), 4
            )
            if priority >= min_priority:
                gaps.append({
                    "topic":       topic,
                    "gap_type":    "DEPTH",
                    "severity":    round(severity, 4),
                    "priority":    priority,
                    "belief_count": stats["count"],
                    "avg_conf":    round(stats["avg_conf"], 4),
                    "drive_weight": drive_w,
                    "query":       _generate_query(topic, "DEPTH"),
                    "reason":      f"avg confidence {stats['avg_conf']:.2f} — shallow understanding",
                })

    # ── CONTESTED gaps ────────────────────────────────────────────────────
    for topic, ratio in contradiction_density.items():
        if ratio >= CONTESTED_RATIO:
            severity = min(1.0, ratio / 0.3)
            drive_w  = drive_weights.get(topic, 0.3)
            priority = round(severity * 1.2 * (1.0 + drive_w * DRIVE_WEIGHT_SCALE), 4)
            if priority >= min_priority:
                gaps.append({
                    "topic":       topic,
                    "gap_type":    "CONTESTED",
                    "severity":    round(severity, 4),
                    "priority":    priority,
                    "contradiction_ratio": ratio,
                    "drive_weight": drive_w,
                    "query":       _generate_query(topic, "CONTESTED"),
                    "reason":      f"contradiction ratio {ratio:.2f} — unresolved tension",
                })

    # ── BRIDGE gaps — from bridge_history ────────────────────────────────
    try:
        bconn = _db()
        bridges = bconn.execute("""
            SELECT topic_a, topic_b, shared_concepts, bridge_score
            FROM bridge_history
            WHERE promoted = 0
            ORDER BY bridge_score DESC LIMIT 10
        """).fetchall()
        bconn.close()

        for bridge in bridges:
            topic_a = bridge["topic_a"]
            topic_b = bridge["topic_b"]
            concepts = json.loads(bridge["shared_concepts"] or "[]")
            score    = float(bridge["bridge_score"] or 0)
            drive_w  = max(
                drive_weights.get(topic_a, 0.3),
                drive_weights.get(topic_b, 0.3)
            )
            priority = round(score * (1.0 + drive_w * DRIVE_WEIGHT_SCALE), 4)
            if priority >= min_priority and concepts:
                concept = concepts[0]
                gaps.append({
                    "topic":       f"{topic_a}+{topic_b}",
                    "gap_type":    "BRIDGE",
                    "severity":    round(score, 4),
                    "priority":    priority,
                    "topic_a":     topic_a,
                    "topic_b":     topic_b,
                    "shared_concept": concept,
                    "drive_weight": drive_w,
                    "query":       f"connection between {topic_a.replace('_',' ')} and {topic_b.replace('_',' ')} — {concept}",
                    "reason":      f"bridge detected: {topic_a} ↔ {topic_b} via '{concept}'",
                })
    except Exception:
        pass

    # Sort by priority
    gaps.sort(key=lambda x: -x["priority"])
    return gaps


def _generate_query(topic: str, gap_type: str) -> str:
    """Generate a search query for a gap type."""
    t = topic.replace("_", " ")
    if gap_type == "THIN":
        return f"{t} fundamentals research"
    elif gap_type == "DEPTH":
        return f"{t} mechanisms evidence peer-reviewed"
    elif gap_type == "CONTESTED":
        return f"{t} debate evidence resolution"
    elif gap_type == "BRIDGE":
        return f"{t} interdisciplinary connections"
    return f"{t} overview"


def top_queries(n: int = 5, gap_types: list = None) -> list:
    """
    Return top N search queries derived from graph gaps.
    Replaces the LLM-generated curiosity queries.
    """
    gaps = detect_gaps()
    if gap_types:
        gaps = [g for g in gaps if g["gap_type"] in gap_types]

    queries = []
    seen_topics = set()
    for gap in gaps:
        topic = gap["topic"]
        if topic in seen_topics:
            continue
        seen_topics.add(topic)
        queries.append({
            "query":    gap["query"],
            "topic":    topic,
            "gap_type": gap["gap_type"],
            "priority": gap["priority"],
            "reason":   gap["reason"],
        })
        if len(queries) >= n:
            break

    return queries


def sync_to_db(gaps: list) -> int:
    """
    Write detected gaps to curiosity_gaps table.
    Replaces manually entered gaps with graph-derived ones.
    """
    conn = _db()
    now  = time.time()
    written = 0

    # Clear old unfilled graph-derived gaps
    conn.execute(
        "DELETE FROM curiosity_gaps WHERE filled=0 AND gap_type IN ('THIN','DEPTH','CONTESTED','BRIDGE')"
    )

    for gap in gaps[:20]:  # keep top 20
        try:
            conn.execute("""
                INSERT INTO curiosity_gaps
                (topic, gap_type, priority_score, detected_at, filled,
                 enqueued, priority, reason, created_at)
                VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?)
            """, (
                gap["topic"][:60],
                gap["gap_type"],
                gap["priority"],
                now,
                min(10, max(1, int(gap["priority"] * 3))),
                gap["reason"],
                now,
            ))
            written += 1
        except Exception:
            continue

    conn.commit()
    conn.close()
    return written


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top",  type=int, default=15)
    parser.add_argument("--fill", action="store_true", help="Generate queries + sync to DB")
    parser.add_argument("--type", type=str, default=None, help="Filter by gap type")
    args = parser.parse_args()

    print(f"\n  NEX Graph Curiosity Engine")
    print(f"  {'─'*50}")

    gaps = detect_gaps()
    if args.type:
        gaps = [g for g in gaps if g["gap_type"] == args.type.upper()]

    print(f"  Total gaps detected: {len(gaps)}")
    print(f"\n  Top {min(args.top, len(gaps))} gaps by priority:\n")

    for g in gaps[:args.top]:
        print(f"  [{g['gap_type']:9s}] priority={g['priority']:.3f}  "
              f"topic={g['topic'][:30]}")
        print(f"             {g['reason']}")
        print(f"             query: {g['query'][:70]}")
        print()

    if args.fill:
        written = sync_to_db(gaps)
        print(f"  Synced {written} gaps to curiosity_gaps table")

        queries = top_queries(n=5)
        print(f"\n  Top 5 search queries:")
        for q in queries:
            print(f"  [{q['gap_type']}] {q['query']}")
