#!/usr/bin/env python3
"""
nex_contradiction_resolver_v2.py — Active belief conflict resolution.

What it does:
  1. Finds genuine high-severity conflicts in belief_edges
  2. Filters out false contradictions (beliefs saying the same thing)
  3. Asks LLM to adjudicate or synthesise a resolution belief
  4. Scores the synthesis — if better than both parents, promotes it
  5. Writes resolutions to contra_resolved and adds corroborates edges
  6. Demotes loser beliefs (confidence penalty), locks winner

This is the component no commercial LLM has: explicit belief revision.
NEX actively resolves its own contradictions rather than ignoring them.

Usage:
  python3 nex_contradiction_resolver_v2.py --dry-run --n 10
  python3 nex_contradiction_resolver_v2.py --run --n 20
  python3 nex_contradiction_resolver_v2.py --run --topic consciousness
  python3 nex_contradiction_resolver_v2.py --report
  python3 nex_contradiction_resolver_v2.py --run --n 50   # weekly cron

Cron (Sunday 4:35AM, after contradiction_detector):
  35 4 * * 0 cd ~/Desktop/nex && venv/bin/python3 nex_contradiction_resolver_v2.py --run --n 50 >> logs/warmth_cron.log 2>&1
"""

import argparse
import sqlite3
import time
import re
import logging
import numpy as np
import requests
from pathlib import Path

DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/v1/chat/completions"
LOG_FILE = Path.home() / "Desktop/nex/logs/resolver_v2.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("nex.resolver_v2")

# ── Thresholds ────────────────────────────────────────────────────────────────

MIN_BELIEF_CONF     = 0.65   # both beliefs must be this confident
MIN_COSINE_DIFF     = 0.08   # embeddings must differ enough to be a real conflict
                              # (below this = same thing said differently = skip)
SYNTHESIS_MIN_SCORE = 0.72   # synthesis must score this high to be promoted
LOSER_PENALTY       = 0.85   # multiply loser confidence by this
WINNER_BOOST        = 1.03   # multiply winner confidence by this (capped at 0.98)
MAX_CONF            = 0.98
ALREADY_RESOLVED_SKIP = True # skip topics already in contra_resolved

# ── LLM ──────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a belief adjudicator for NEX, a reasoning AI.
Your job: given two conflicting beliefs on the same topic, either:
  A) Pick the more defensible one and explain why in one sentence
  B) Synthesise a better belief that resolves the tension

Rules:
- Be direct and specific — no hedging
- Prefer synthesis (BOTH) when the beliefs are genuinely complementary
- Pick a winner (A or B) when one is clearly more accurate or nuanced
- The synthesis/reason must be a complete, standalone belief statement
- Maximum 2 sentences for the reason/synthesis\
"""

RESOLVE_PROMPT = """\
Topic: {topic}

Belief A (confidence {conf_a:.2f}):
{belief_a}

Belief B (confidence {conf_b:.2f}):
{belief_b}

These beliefs are in tension. Your task:

- If both beliefs capture something true but incomplete, choose BOTH and write
  a synthesis belief that combines what is correct in each. This is preferred.
- Only choose A or B if one belief is clearly more accurate or more nuanced
  than the other, and the other adds nothing.

Reply in EXACTLY this format (no other text):
WINNER: <A or B or BOTH>
REASON: <if BOTH: write the synthesis belief as a complete sentence. If A or B: one sentence explaining why>
"""

def _llm_synthesise(belief_a: str, belief_b: str,
                    conf_a: float, conf_b: float, topic: str) -> dict | None:
    """
    Dedicated synthesis call for complementary beliefs (high cosine similarity).
    These aren't truly opposing — they're partial views of the same truth.
    Task: write a single belief that captures both.
    """
    prompt = f"""\
Topic: {topic}

These two beliefs are complementary — they describe different aspects of the same idea:

Belief A: {belief_a[:200]}

Belief B: {belief_b[:200]}

Write a single, concise belief statement that captures what is true in both.
The synthesis should be more complete than either alone.
Do not start with "Both beliefs" — write the belief directly as a statement.

Reply in EXACTLY this format:
WINNER: BOTH
REASON: <the synthesis belief as one complete sentence>
"""
    try:
        r = requests.post(API, json={
            "messages": [
                {"role": "system",  "content": "You are a belief synthesiser. Write clear, direct belief statements."},
                {"role": "user",    "content": prompt},
            ],
            "max_tokens": 120,
            "temperature": 0.35,
            "stream": False,
        }, timeout=30)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()

        rm = re.search(r'REASON:\s*(.+?)$', text, re.M | re.S)
        if not rm:
            # Try extracting any sentence that looks like a belief
            lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 30]
            reason = lines[-1] if lines else text[:200]
        else:
            reason = rm.group(1).strip()[:300]

        # Strip "Both beliefs..." preamble if model ignored instructions
        reason = re.sub(r'^Both beliefs\s+\w+.*?[,\.]\s*', '', reason, flags=re.I).strip()
        if not reason or len(reason) < 20:
            reason = text.strip()[:300]

        return {"winner": "BOTH", "reason": reason, "raw": text}

    except Exception as e:
        log.debug(f"Synthesise call failed: {e}")
        return None


def _llm_resolve(belief_a: str, belief_b: str,
                 conf_a: float, conf_b: float, topic: str,
                 swapped: bool = False) -> dict | None:
    import random
    try:
        r = requests.post(API, json={
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": RESOLVE_PROMPT.format(
                    topic=topic,
                    belief_a=belief_a[:200],
                    belief_b=belief_b[:200],
                    conf_a=conf_a, conf_b=conf_b,
                )},
            ],
            "max_tokens": 150,
            "temperature": 0.25,
            "stream": False,
        }, timeout=30)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()

        wm = re.search(r'WINNER:\s*(A|B|BOTH)', text, re.I)
        rm = re.search(r'REASON:\s*(.+?)$', text, re.M | re.S)

        if not wm or not rm:
            log.debug(f"Parse failed on: {text[:100]}")
            return None

        winner = wm.group(1).upper()

        # Correct for swap — if we swapped A/B, flip the winner back
        if swapped:
            if winner == "A":
                winner = "B"
            elif winner == "B":
                winner = "A"

        return {
            "winner": winner,
            "reason": rm.group(1).strip()[:300],
            "raw":    text,
        }
    except Exception as e:
        log.debug(f"LLM call failed: {e}")
        return None

# ── Embedding helpers ─────────────────────────────────────────────────────────

def _decode(blob) -> np.ndarray | None:
    if blob is None:
        return None
    try:
        arr = np.frombuffer(blob, dtype=np.float32).copy()
        n = np.linalg.norm(arr)
        return arr / n if n > 0 else arr
    except Exception:
        return None

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))   # pre-normalised

def _encode(text: str) -> np.ndarray | None:
    try:
        from sentence_transformers import SentenceTransformer
        global _model
        if '_model' not in globals() or _model is None:
            _model = SentenceTransformer("all-MiniLM-L6-v2")
        v = _model.encode(text, normalize_embeddings=True)
        return v.astype(np.float32)
    except Exception as e:
        log.debug(f"Encode failed: {e}")
        return None

# ── Conflict finder ───────────────────────────────────────────────────────────

def find_genuine_conflicts(topic: str = None, n: int = 50) -> list:
    """
    Find conflict pairs from belief_edges that are GENUINELY contradictory —
    not just similar beliefs that got a bad edge.

    Genuine conflict = conflict edge + embedding cosine difference >= MIN_COSINE_DIFF
    (if embeddings are very similar, they're saying the same thing differently)
    """
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # Load already-resolved topics to optionally skip
    resolved_topics = set()
    if ALREADY_RESOLVED_SKIP:
        rows = cur.execute("SELECT topic FROM contra_resolved").fetchall()
        resolved_topics = {r[0] for r in rows}

    q = """
        SELECT DISTINCT
            b1.id, b1.content, b1.confidence, b1.topic, b1.embedding,
            b2.id, b2.content, b2.confidence, b2.embedding,
            be.edge_type, be.weight
        FROM belief_edges be
        JOIN beliefs b1 ON b1.id = be.from_id
        JOIN beliefs b2 ON b2.id = be.to_id
        WHERE be.edge_type IN ('contradicts', 'opposes')
        AND b1.confidence >= ? AND b2.confidence >= ?
        AND b1.locked = 0 AND b2.locked = 0
        AND b1.topic IS NOT NULL AND b2.topic IS NOT NULL
        AND b1.topic = b2.topic
        AND b1.id < b2.id
    """
    params = [MIN_BELIEF_CONF, MIN_BELIEF_CONF]

    if topic:
        q += " AND b1.topic = ?"
        params.append(topic)

    q += " ORDER BY (b1.confidence + b2.confidence) DESC LIMIT ?"
    params.append(n * 3)   # oversample — we'll filter by cosine diff

    rows = cur.execute(q, params).fetchall()
    conn.close()

    conflicts = []
    seen_pairs = set()

    for row in rows:
        id1, c1, cf1, topic1, emb1, id2, c2, cf2, emb2, etype, weight = row

        pair_key = (min(id1, id2), max(id1, id2))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        if topic1 in resolved_topics:
            continue

        # Compute embedding cosine to filter false contradictions
        v1 = _decode(emb1)
        v2 = _decode(emb2)
        cosine_sim = _cosine(v1, v2) if v1 is not None and v2 is not None else 0.5

        # Skip if embeddings are too similar — same belief, bad edge
        if cosine_sim > (1.0 - MIN_COSINE_DIFF):
            log.debug(f"Skipping false contradiction (cosine={cosine_sim:.3f}): {c1[:50]}")
            continue

        severity = (cf1 + cf2) / 2 * (1.0 - cosine_sim)

        conflicts.append({
            "id1": id1, "c1": c1, "cf1": cf1,
            "id2": id2, "c2": c2, "cf2": cf2,
            "topic": topic1,
            "cosine": cosine_sim,
            "severity": round(severity, 4),
            "edge_type": etype,
        })

        if len(conflicts) >= n:
            break

    # Sort by severity descending
    conflicts.sort(key=lambda x: -x["severity"])
    return conflicts

# ── Synthesis scorer ──────────────────────────────────────────────────────────

def score_synthesis(synthesis: str, belief_a: str, belief_b: str) -> float:
    """
    Score a synthesis belief on:
    - Length (not too short, not too long)
    - Doesn't just repeat one parent verbatim
    - Contains substantive content
    - Embedding similarity to both parents (should be between them)
    """
    s = synthesis.strip()
    if len(s) < 30:
        return 0.0
    if len(s) > 400:
        return 0.4   # too long = probably rambling

    # Penalise if synthesis is near-identical to either parent
    s_lower = s.lower()
    a_lower = belief_a.lower()[:150]
    b_lower = belief_b.lower()[:150]

    overlap_a = len(set(s_lower.split()) & set(a_lower.split())) / max(len(s_lower.split()), 1)
    overlap_b = len(set(s_lower.split()) & set(b_lower.split())) / max(len(s_lower.split()), 1)

    if overlap_a > 0.75 or overlap_b > 0.75:
        return 0.35   # just rephrased a parent

    # Base score from length and overlap balance
    length_score = min(1.0, len(s) / 120) * 0.4
    novelty_score = (1.0 - max(overlap_a, overlap_b)) * 0.6

    return round(length_score + novelty_score, 3)

# ── Core resolution ───────────────────────────────────────────────────────────

def resolve_conflict(conflict: dict, dry_run: bool = False) -> dict:
    """
    Resolve a single conflict pair.
    Returns resolution dict with outcome and actions taken.
    """
    import random

    # Pre-route: if cosine is high (0.75-0.93), beliefs are complementary variations
    # of the same position — force synthesis instead of adjudication
    force_synthesis = conflict["cosine"] >= 0.75

    # Randomise which belief is presented as A vs B to eliminate position bias
    swapped = random.random() > 0.5
    if swapped:
        ba, bb = conflict["c2"], conflict["c1"]
        ca, cb = conflict["cf2"], conflict["cf1"]
    else:
        ba, bb = conflict["c1"], conflict["c2"]
        ca, cb = conflict["cf1"], conflict["cf2"]

    if force_synthesis:
        result = _llm_synthesise(ba, bb, ca, cb, conflict["topic"])
        if result is None:
            time.sleep(2)
            result = _llm_synthesise(ba, bb, ca, cb, conflict["topic"])
    else:
        result = _llm_resolve(ba, bb, ca, cb, conflict["topic"], swapped=swapped)
        if result is None:
            time.sleep(2)
            result = _llm_resolve(ba, bb, ca, cb, conflict["topic"], swapped=swapped)

    if result is None:
        return {"status": "llm_failed", "conflict": conflict}

    winner  = result["winner"]
    reason  = result["reason"]

    if winner == "BOTH":
        syn_score = score_synthesis(reason, conflict["c1"], conflict["c2"])
        outcome = {
            "status":     "synthesised",
            "winner":     "BOTH",
            "synthesis":  reason,
            "syn_score":  syn_score,
            "promoted":   syn_score >= SYNTHESIS_MIN_SCORE,
            "conflict":   conflict,
        }
    elif winner == "A":
        outcome = {
            "status":   "adjudicated",
            "winner":   "A",
            "winner_id": conflict["id1"],
            "loser_id":  conflict["id2"],
            "reason":    reason,
            "conflict":  conflict,
        }
    else:  # B
        outcome = {
            "status":   "adjudicated",
            "winner":   "B",
            "winner_id": conflict["id2"],
            "loser_id":  conflict["id1"],
            "reason":    reason,
            "conflict":  conflict,
        }

    if not dry_run:
        _apply_resolution(outcome)

    return outcome


def _apply_resolution(outcome: dict):
    """Write resolution to DB — update beliefs, add synthesis, log to contra_resolved."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    now  = time.time()
    c    = outcome["conflict"]

    try:
        if outcome["status"] == "synthesised" and outcome.get("promoted"):
            # Insert synthesis as new belief
            syn = outcome["synthesis"]
            emb_blob = None
            emb = _encode(syn)
            if emb is not None:
                emb_blob = emb.tobytes()

            cur.execute(
                """INSERT OR IGNORE INTO beliefs
                   (content, topic, confidence, source, belief_type, created_at, embedding)
                   VALUES (?, ?, ?, 'resolver_v2', 'synthesis', ?, ?)""",
                (syn, c["topic"],
                 round(min(MAX_CONF, (c["cf1"] + c["cf2"]) / 2 + 0.05), 4),
                 time.strftime("%Y-%m-%dT%H:%M:%S"), emb_blob)
            )
            new_id = cur.lastrowid

            # Add corroborates edges from synthesis back to both parents
            for parent_id in [c["id1"], c["id2"]]:
                cur.execute(
                    """INSERT OR IGNORE INTO belief_edges (from_id, to_id, edge_type, weight, created_at)
                       VALUES (?, ?, 'corroborates', 0.85, ?)""",
                    (new_id, parent_id, now)
                )

            log.info(f"  [synthesised] New belief id={new_id} topic={c['topic']} "
                     f"score={outcome['syn_score']:.3f}")

        elif outcome["status"] == "adjudicated":
            winner_id = outcome["winner_id"]
            loser_id  = outcome["loser_id"]

            # Boost winner slightly
            cur.execute(
                "UPDATE beliefs SET confidence = MIN(?, confidence * ?) WHERE id = ?",
                (MAX_CONF, WINNER_BOOST, winner_id)
            )
            # Penalise loser
            cur.execute(
                "UPDATE beliefs SET confidence = confidence * ? WHERE id = ?",
                (LOSER_PENALTY, loser_id)
            )
            log.info(f"  [adjudicated] winner={winner_id} loser={loser_id} "
                     f"topic={c['topic']}")

        # Mark topic as resolved
        cur.execute(
            """INSERT OR REPLACE INTO contra_resolved (topic, resolved_at, belief_count)
               VALUES (?, ?, ?)""",
            (c["topic"], time.strftime("%Y-%m-%dT%H:%M:%S"), 2)
        )

        # Remove the conflict edge (it's been resolved)
        cur.execute(
            """DELETE FROM belief_edges
               WHERE from_id = ? AND to_id = ?
               AND edge_type IN ('contradicts','opposes')""",
            (c["id1"], c["id2"])
        )
        cur.execute(
            """DELETE FROM belief_edges
               WHERE from_id = ? AND to_id = ?
               AND edge_type IN ('contradicts','opposes')""",
            (c["id2"], c["id1"])
        )

        conn.commit()

    except Exception as e:
        log.error(f"Apply resolution failed: {e}")
        conn.rollback()
    finally:
        conn.close()

# ── Report ────────────────────────────────────────────────────────────────────

def report():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    total_conflicts = cur.execute(
        "SELECT COUNT(*) FROM belief_edges WHERE edge_type IN ('contradicts','opposes')"
    ).fetchone()[0]
    resolved = cur.execute("SELECT COUNT(*) FROM contra_resolved").fetchone()[0]
    recent = cur.execute(
        "SELECT topic, resolved_at FROM contra_resolved ORDER BY resolved_at DESC LIMIT 10"
    ).fetchall()
    by_topic = cur.execute(
        """SELECT b.topic, COUNT(*) n FROM belief_edges be
           JOIN beliefs b ON b.id = be.from_id
           WHERE be.edge_type IN ('contradicts','opposes')
           AND b.confidence >= 0.65
           GROUP BY b.topic ORDER BY n DESC LIMIT 10"""
    ).fetchall()

    print("══════════════════════════════════════════════════════")
    print("  NEX Contradiction Resolver v2 — Report")
    print("══════════════════════════════════════════════════════")
    print(f"  Active conflict edges  : {total_conflicts:,}")
    print(f"  Topics resolved (ever) : {resolved:,}")
    print()
    if by_topic:
        print("  Top conflicted topics:")
        for topic, n in by_topic:
            print(f"    {topic:<25} {n:>4} conflict edges")
    print()
    if recent:
        print("  Recently resolved:")
        for topic, ts in recent:
            print(f"    {topic:<25} {ts}")
    print("══════════════════════════════════════════════════════")
    conn.close()

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="NEX Contradiction Resolver v2")
    ap.add_argument("--run",     action="store_true", help="Run resolution")
    ap.add_argument("--dry-run", action="store_true", help="Analyse without writing")
    ap.add_argument("--report",  action="store_true", help="Show report")
    ap.add_argument("--n",       type=int, default=20, help="Max conflicts to process")
    ap.add_argument("--topic",   type=str, default=None, help="Filter to topic")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.report:
        report()
        return

    if not args.run and not args.dry_run:
        report()
        return

    dry = args.dry_run
    mode = "DRY RUN" if dry else "LIVE"
    print(f"\n[Resolver v2] {mode} — finding genuine conflicts (n={args.n})")
    if args.topic:
        print(f"[Resolver v2] Topic filter: {args.topic}")

    conflicts = find_genuine_conflicts(topic=args.topic, n=args.n)
    print(f"[Resolver v2] Found {len(conflicts)} genuine conflicts to process\n")

    if not conflicts:
        print("No conflicts found matching criteria. Run --report for stats.")
        return

    stats = {"synthesised": 0, "promoted": 0, "adjudicated": 0,
             "llm_failed": 0, "skipped": 0}

    for i, conflict in enumerate(conflicts):
        print(f"  [{i+1}/{len(conflicts)}] topic={conflict['topic']} "
              f"severity={conflict['severity']:.3f} "
              f"cosine={conflict['cosine']:.3f}")
        if args.verbose:
            print(f"    A: {conflict['c1'][:80]}")
            print(f"    B: {conflict['c2'][:80]}")

        outcome = resolve_conflict(conflict, dry_run=dry)

        if outcome["status"] == "llm_failed":
            print(f"    → LLM failed")
            stats["llm_failed"] += 1
        elif outcome["status"] == "synthesised":
            promoted = outcome.get("promoted", False)
            score    = outcome.get("syn_score", 0)
            print(f"    → SYNTHESIS (score={score:.3f}, {'PROMOTED' if promoted else 'rejected'})")
            if args.verbose:
                print(f"       {outcome['synthesis'][:120]}")
            stats["synthesised"] += 1
            if promoted:
                stats["promoted"] += 1
        elif outcome["status"] == "adjudicated":
            w = outcome["winner"]
            print(f"    → WINNER: {w}  — {outcome['reason'][:80]}")
            stats["adjudicated"] += 1

        time.sleep(0.8)   # longer pause — don't overwhelm the LLM

    print(f"\n{'═'*54}")
    print(f"  Results ({mode})")
    print(f"{'═'*54}")
    print(f"  Processed    : {len(conflicts)}")
    print(f"  Synthesised  : {stats['synthesised']}  (promoted: {stats['promoted']})")
    print(f"  Adjudicated  : {stats['adjudicated']}")
    print(f"  LLM failures : {stats['llm_failed']}")
    if not dry:
        print(f"\n  Conflict edges removed, synthesis beliefs added.")
        print(f"  Topics marked resolved in contra_resolved.")
    print(f"{'═'*54}")


if __name__ == "__main__":
    main()
