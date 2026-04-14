#!/usr/bin/env python3
"""
nex_improvement_gate.py — Recursive Self-Improvement Gate for NEX v4.0

Before any new belief is committed to the graph, this gate:
1. Checks for contradictions with existing high-confidence beliefs
2. Estimates if the belief fills a genuine gap (not redundant)
3. Scores belief quality (specificity, confidence, domain coverage)
4. Accept/reject with reason logged

This closes the self-improvement loop:
propose → gate → accept/reject → commit/discard

Usage:
    from nex_improvement_gate import gate_belief
    result = gate_belief(content, topic, confidence, source)
    if result["accepted"]:
        # write to DB

CLI:
    python3 nex_improvement_gate.py --test "Consciousness requires physical substrate"
    python3 nex_improvement_gate.py --report
    python3 nex_improvement_gate.py --audit --n 100
"""

import sqlite3, requests, re, time, argparse, logging, json
import numpy as np
from pathlib import Path

log     = logging.getLogger("nex.gate")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

# Gate thresholds
MIN_LENGTH        = 30    # min chars
MAX_LENGTH        = 600   # max chars
MIN_CONFIDENCE    = 0.40  # reject below this
REDUNDANCY_THRESH = 0.92  # cosine sim above this = redundant
CONFLICT_THRESH   = 0.85  # confidence required to block on conflict
MIN_QUALITY_SCORE = 0.35  # reject below this quality

QUALITY_PROMPT = """Rate this belief statement on 3 dimensions (0.0-1.0 each):
1. Specificity: does it make a concrete, falsifiable claim?
2. Originality: is it non-obvious, not just a definition?
3. Epistemic_honesty: does it acknowledge appropriate uncertainty?

Belief: {belief}

Return JSON only: {{"specificity": 0.0-1.0, "originality": 0.0-1.0, "epistemic_honesty": 0.0-1.0}}
JSON:"""

CONFLICT_PROMPT = """Does this new belief directly contradict the existing belief?
Answer YES or NO only.

New belief: {new}
Existing belief: {existing}

Answer:"""


def _db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    # Create gate log table
    db.execute("""CREATE TABLE IF NOT EXISTS gate_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        content     TEXT,
        topic       TEXT,
        confidence  REAL,
        source      TEXT,
        accepted    INTEGER,
        reason      TEXT,
        quality_score REAL,
        created_at  REAL
    )""")
    db.commit()
    return db


def _llm(prompt, n=80):
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": n, "temperature": 0.0,
            "stop": ["<|im_end|>", "<|im_start|>", "\n\n"],
            "cache_prompt": False,
        }, timeout=15)
        return r.json().get("content", "").strip()
    except:
        return ""


def _get_embedding(text: str):
    """Get embedding via sentence_transformers."""
    try:
        from sentence_transformers import SentenceTransformer
        if not hasattr(_get_embedding, "_model"):
            _get_embedding._model = SentenceTransformer("all-MiniLM-L6-v2")
        return _get_embedding._model.encode([text], show_progress_bar=False)[0]
    except:
        return None


def _cosine(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _check_redundancy(content: str, topic: str, db) -> tuple[bool, float, str]:
    """Check if belief is too similar to existing beliefs. Returns (redundant, max_sim, similar_content)."""
    emb = _get_embedding(content)
    if emb is None:
        return False, 0.0, ""

    rows = db.execute("""
        SELECT id, content, embedding FROM beliefs
        WHERE topic = ? AND embedding IS NOT NULL AND confidence >= 0.6
        LIMIT 100
    """, (topic,)).fetchall()

    max_sim = 0.0
    most_similar = ""
    for r in rows:
        if not r["embedding"]:
            continue
        existing_emb = np.frombuffer(r["embedding"], dtype=np.float32)
        sim = _cosine(emb, existing_emb)
        if sim > max_sim:
            max_sim = sim
            most_similar = r["content"]

    return max_sim >= REDUNDANCY_THRESH, max_sim, most_similar


def _check_conflict(content: str, topic: str, db) -> tuple[bool, str]:
    """Check if belief conflicts with high-confidence existing beliefs."""
    rows = db.execute("""
        SELECT content FROM beliefs
        WHERE topic = ? AND confidence >= ?
        ORDER BY confidence DESC LIMIT 20
    """, (topic, CONFLICT_THRESH)).fetchall()

    for r in rows:
        existing = r["content"]
        if existing[:30] == content[:30]:
            continue
        prompt = CONFLICT_PROMPT.format(new=content[:150], existing=existing[:150])
        answer = _llm(prompt, n=5).upper()
        if answer.startswith("YES"):
            return True, existing
    return False, ""


def _score_quality(content: str) -> float:
    """Score belief quality 0.0-1.0."""
    prompt = QUALITY_PROMPT.format(belief=content[:200])
    raw    = _llm(prompt, n=80)
    try:
        m = re.search(r"\{.*?\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            scores = [
                float(data.get("specificity", 0.5)),
                float(data.get("originality", 0.5)),
                float(data.get("epistemic_honesty", 0.5)),
            ]
            return round(sum(scores) / len(scores), 3)
    except:
        pass
    return 0.5  # default if LLM fails


def _log_decision(db, content, topic, confidence, source, accepted, reason, quality):
    db.execute("""
        INSERT INTO gate_log (content, topic, confidence, source, accepted, reason, quality_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (content[:300], topic, confidence, source, int(accepted), reason, quality, time.time()))
    db.commit()


def gate_belief(content: str, topic: str = "general",
                confidence: float = 0.7, source: str = "unknown",
                skip_llm: bool = False) -> dict:
    """
    Main gate function. Call before writing any belief to DB.

    Returns:
        {
            "accepted": bool,
            "reason": str,
            "quality_score": float,
            "redundancy_sim": float,
        }
    """
    db = _db()
    result = {
        "accepted": False,
        "reason": "",
        "quality_score": 0.0,
        "redundancy_sim": 0.0,
    }

    # ── Rule 1: Length check ─────────────────────────────────────
    if len(content) < MIN_LENGTH:
        result["reason"] = f"too_short ({len(content)} chars)"
        _log_decision(db, content, topic, confidence, source, False, result["reason"], 0.0)
        db.close()
        return result

    if len(content) > MAX_LENGTH:
        content = content[:MAX_LENGTH]

    # ── Rule 2: Confidence check ─────────────────────────────────
    if confidence < MIN_CONFIDENCE:
        result["reason"] = f"low_confidence ({confidence:.2f})"
        _log_decision(db, content, topic, confidence, source, False, result["reason"], 0.0)
        db.close()
        return result

    # ── Rule 3: Redundancy check ─────────────────────────────────
    redundant, sim, similar = _check_redundancy(content, topic, db)
    result["redundancy_sim"] = sim
    if redundant:
        result["reason"] = f"redundant (sim={sim:.3f}): {similar[:60]}"
        _log_decision(db, content, topic, confidence, source, False, result["reason"], 0.0)
        db.close()
        return result

    # ── Rule 4: Conflict check (LLM) ────────────────────────────
    if not skip_llm:
        conflicted, conflict_belief = _check_conflict(content, topic, db)
        if conflicted:
            result["reason"] = f"conflicts_with: {conflict_belief[:80]}"
            _log_decision(db, content, topic, confidence, source, False, result["reason"], 0.0)
            db.close()
            return result

    # ── Rule 5: Quality score ────────────────────────────────────
    if not skip_llm:
        quality = _score_quality(content)
    else:
        quality = 0.6  # default when skipping LLM
    result["quality_score"] = quality

    if quality < MIN_QUALITY_SCORE:
        result["reason"] = f"low_quality ({quality:.2f})"
        _log_decision(db, content, topic, confidence, source, False, result["reason"], quality)
        db.close()
        return result

    # ── ACCEPTED ─────────────────────────────────────────────────
    result["accepted"] = True
    result["reason"]   = f"passed_all_checks (quality={quality:.2f}, sim={sim:.3f})"
    _log_decision(db, content, topic, confidence, source, True, result["reason"], quality)
    db.close()
    log.debug(f"Gate ACCEPT: {content[:60]} (q={quality:.2f})")
    return result


def report():
    db = _db()
    try:
        total    = db.execute("SELECT COUNT(*) FROM gate_log").fetchone()[0]
        accepted = db.execute("SELECT COUNT(*) FROM gate_log WHERE accepted=1").fetchone()[0]
        rejected = total - accepted
        reasons  = db.execute("""
            SELECT substr(reason, 1, 30) as r, COUNT(*) as n
            FROM gate_log WHERE accepted=0
            GROUP BY r ORDER BY n DESC LIMIT 8
        """).fetchall()
        avg_q = db.execute("SELECT AVG(quality_score) FROM gate_log WHERE accepted=1").fetchone()[0] or 0

        print(f"\n{'═'*50}")
        print(f"  Improvement Gate Report")
        print(f"{'═'*50}")
        print(f"  Total evaluated : {total:,}")
        print(f"  Accepted        : {accepted:,} ({100*accepted//max(total,1)}%)")
        print(f"  Rejected        : {rejected:,}")
        print(f"  Avg quality     : {avg_q:.3f}")
        print(f"\n  Rejection reasons:")
        for r in reasons:
            print(f"    {r['r']:30s} : {r['n']}")
        print(f"{'═'*50}\n")
    except Exception as e:
        print(f"Report error: {e}")
    db.close()


def audit(n=100):
    """Run gate against existing beliefs to find low-quality ones."""
    db = _db()
    rows = db.execute("""
        SELECT id, content, topic, confidence, source FROM beliefs
        WHERE confidence >= 0.6 AND length(content) > 30
        ORDER BY RANDOM() LIMIT ?
    """, (n,)).fetchall()

    accepted = rejected = 0
    low_quality = []

    for r in rows:
        result = gate_belief(r["content"], r["topic"], r["confidence"],
                             r["source"], skip_llm=True)
        if result["accepted"]:
            accepted += 1
        else:
            rejected += 1
            low_quality.append({
                "id": r["id"],
                "content": r["content"][:80],
                "reason": result["reason"]
            })

    print(f"\n[AUDIT] {n} beliefs checked:")
    print(f"  Would pass : {accepted}")
    print(f"  Would fail : {rejected}")
    if low_quality[:5]:
        print(f"\n  Sample failures:")
        for b in low_quality[:5]:
            print(f"    [{b['id']}] {b['content'][:60]} — {b['reason']}")
    db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="NEX improvement gate")
    parser.add_argument("--test",   type=str, help="Test a belief string")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--audit",  action="store_true")
    parser.add_argument("--n",      type=int, default=100)
    args = parser.parse_args()

    if args.report:
        report()
    elif args.audit:
        audit(args.n)
    elif args.test:
        print(f"\nTesting: '{args.test}'")
        result = gate_belief(args.test, topic="philosophy", confidence=0.75)
        print(f"Accepted      : {result['accepted']}")
        print(f"Reason        : {result['reason']}")
        print(f"Quality score : {result['quality_score']:.3f}")
        print(f"Redundancy sim: {result['redundancy_sim']:.3f}")
    else:
        parser.print_help()
