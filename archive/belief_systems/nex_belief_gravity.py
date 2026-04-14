"""
nex_belief_gravity.py — Belief Gravity & Attractor System for NEX
==================================================================
NEX's belief field has a natural attractor: "structure" appears in all 4
depth=3 meta-principles. This module formalizes that.

GRAVITY: Measures which concepts appear most across synthesis outputs.
High-gravity concepts become ATTRACTORS — active seed nodes that:
  1. Pull in new beliefs from external sources targeting that concept
  2. Bias the forge's enrichment toward attractor topics
  3. Seed new dialectic tensions around attractor concepts
  4. Track attractor evolution over time (what NEX keeps returning to)

ATTRACTOR EVOLUTION: An attractor that persists for 3+ cycles becomes
a CORE ATTRACTOR — part of NEX's intellectual identity. These are
distinct from identity beliefs (which are values) — they are the
concepts NEX gravitates toward intellectually.

Current observed attractors (from depth=3 meta-principles):
  - "structure" (appears in all 4 meta-principles)
  - "memory" (appears in 3)
  - "power" (appears in 2)
  - "belief" (appears in all 4)

Wire into run.py alongside other engines.
"""

import sqlite3
import time
import threading
import logging
import json
import re
import urllib.request
from pathlib import Path
from collections import Counter

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH          = str(Path.home() / "Desktop/nex/nex.db")
LOG_PATH         = str(Path.home() / "Desktop/nex/logs/belief_gravity.log")
LLM_URL          = "http://localhost:8080/v1/chat/completions"
LLM_MODEL        = "qwen2.5"

GRAVITY_INTERVAL  = 3600   # recalculate gravity every 1h
SEED_INTERVAL     = 7200   # seed new beliefs for attractors every 2h
TOP_ATTRACTORS    = 5      # number of attractors to track
CORE_THRESHOLD    = 3      # cycles before attractor becomes "core"
MIN_GRAVITY_SCORE = 3      # minimum appearances to count as attractor

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "have",
    "has", "had", "do", "does", "will", "would", "should", "may", "might",
    "must", "can", "could", "this", "that", "and", "or", "but", "not",
    "in", "on", "of", "to", "for", "with", "at", "by", "from", "if",
    "so", "just", "than", "also", "what", "which", "who", "how", "all",
    "any", "both", "each", "more", "most", "other", "some", "such",
    "only", "same", "very", "merely", "its", "it", "their", "these",
    "those", "about", "above", "because", "between", "into", "through",
    "during", "before", "after", "where", "when", "there", "here",
    "that", "then", "them", "they", "from", "have", "with", "been",
    "appears", "actually", "merely", "truly", "often", "always", "never"
}

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
log = logging.getLogger("belief_gravity")

# ── DB ────────────────────────────────────────────────────────────────────────
def _db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _ensure_schema():
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS belief_attractors (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                concept     TEXT UNIQUE,
                gravity     REAL DEFAULT 0,
                cycle_count INTEGER DEFAULT 0,
                is_core     INTEGER DEFAULT 0,
                first_seen  TEXT DEFAULT (datetime('now')),
                last_seen   TEXT DEFAULT (datetime('now')),
                peak_gravity REAL DEFAULT 0
            )
        """)


def _llm_groq(prompt: str, max_tokens: int = 300, temp: float = 0.4) -> str:
    import urllib.request, json, os
    try:
        key = open(os.path.expanduser("~/.config/nex/.env")).read()
        key = [l.split("=",1)[1].strip() for l in key.splitlines() if l.startswith("GROQ_API_KEY")][0]
        payload = json.dumps({"model":"llama-3.3-70b-versatile","max_tokens":max_tokens,"temperature":temp,"messages":[{"role":"user","content":prompt}]}).encode()
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",data=payload,headers={"Content-Type":"application/json","Authorization":f"Bearer {key}"},method="POST")
        with urllib.request.urlopen(req,timeout=30) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"[GROQ] fallback to local: {e}")
        return _llm(prompt, max_tokens, temp)

# ── LLM ───────────────────────────────────────────────────────────────────────
def _llm(prompt: str, max_tokens: int = 200, temp: float = 0.4) -> str:
    try:
        payload = json.dumps({
            "model": LLM_MODEL,
            "max_tokens": max_tokens,
            "temperature": temp,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()
        req = urllib.request.Request(
            LLM_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"[GRAVITY] LLM error: {e}")
        return ""

# ── Gravity calculation ───────────────────────────────────────────────────────
def calculate_gravity() -> dict:
    """
    Count concept frequency across synthesis outputs (depth>=1).
    Weighted by synthesis depth — depth=3 words count 3x.
    """
    weighted = Counter()
    with _db() as conn:
        rows = conn.execute("""
            SELECT content, synthesis_depth FROM beliefs
            WHERE synthesis_depth >= 1
        """).fetchall()

    for row in rows:
        words = re.findall(r'\b[a-z]{4,}\b', row["content"].lower())
        meaningful = [w for w in words if w not in STOPWORDS]
        depth_weight = row["synthesis_depth"]
        for w in meaningful:
            weighted[w] += depth_weight

    return dict(weighted.most_common(20))

def update_attractors(gravity_scores: dict) -> list:
    """Update attractor table and return current top attractors."""
    attractors = []
    with _db() as conn:
        for concept, score in gravity_scores.items():
            if score < MIN_GRAVITY_SCORE:
                continue
            existing = conn.execute(
                "SELECT id, cycle_count, peak_gravity FROM belief_attractors WHERE concept=?",
                (concept,)
            ).fetchone()
            if existing:
                new_cycles = existing["cycle_count"] + 1
                new_peak = max(existing["peak_gravity"], score)
                is_core = 1 if new_cycles >= CORE_THRESHOLD else 0
                conn.execute("""
                    UPDATE belief_attractors
                    SET gravity=?, cycle_count=?, is_core=?, last_seen=datetime('now'), peak_gravity=?
                    WHERE concept=?
                """, (score, new_cycles, is_core, new_peak, concept))
            else:
                conn.execute("""
                    INSERT INTO belief_attractors (concept, gravity, cycle_count, peak_gravity)
                    VALUES (?, ?, 1, ?)
                """, (concept, score, score))
        top = conn.execute("""
            SELECT concept, gravity, cycle_count, is_core
            FROM belief_attractors
            ORDER BY gravity DESC LIMIT ?
        """, (TOP_ATTRACTORS,)).fetchall()
        attractors = [dict(r) for r in top]
    return attractors

# ── Attractor seeding ─────────────────────────────────────────────────────────
SEED_PROMPT = """NEX is an AI deeply focused on the concept of "{concept}".

Existing beliefs about {concept}:
{existing_beliefs}

Write ONE new precise belief about {concept} that goes deeper than the above.
It must be a falsifiable assertion, not a question or summary.
Under 180 characters.

Respond with ONLY the belief, or NONE."""

def seed_attractor(concept: str) -> bool:
    """Generate a new high-quality belief targeting a gravity attractor."""
    with _db() as conn:
        existing = conn.execute("""
            SELECT content FROM beliefs
            WHERE content LIKE ? AND confidence >= 0.6
            ORDER BY confidence DESC LIMIT 5
        """, (f"%{concept}%",)).fetchall()

    if not existing:
        return False

    existing_text = "\n".join(f"- {r['content'][:120]}" for r in existing)
    resp = _llm_groq(
        SEED_PROMPT.format(concept=concept, existing_beliefs=existing_text),
        max_tokens=200, temp=0.5
    )

    if not resp or "NONE" in resp.upper()[:10]:
        return False

    resp = resp.strip().strip('"').strip("'")
    spam = ["bridge:truth", "have to do with", "The insight is",
            "My belief", "↔", "||", "[merged:"]
    if any(s in resp for s in spam):
        return False
    if len(resp) < 30 or len(resp) > 250 or resp.endswith("?"):
        return False

    try:
        with _db() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO beliefs
                (content, topic, confidence, synthesis_depth,
                 reinforce_count, locked, source, last_referenced)
                VALUES (?, ?, 0.78, 1, 1, 1, 'gravity_seed', datetime('now'))
            """, (resp, concept))
            if conn.total_changes > 0:
                log.info(f"[GRAVITY] seeded [{concept}]: {resp[:80]}")
                print(f"  [GRAVITY] seeded [{concept}]: {resp[:90]}")
                return True
    except Exception as e:
        log.warning(f"[GRAVITY] seed error: {e}")
    return False

def seed_all_attractors() -> dict:
    results = {"seeded": 0, "failed": 0}
    with _db() as conn:
        attractors = conn.execute("""
            SELECT concept, gravity, is_core FROM belief_attractors
            ORDER BY gravity DESC LIMIT ?
        """, (TOP_ATTRACTORS,)).fetchall()
    for a in attractors:
        if seed_attractor(a["concept"]):
            results["seeded"] += 1
        else:
            results["failed"] += 1
    return results

def attractor_report() -> dict:
    _ensure_schema()
    scores = calculate_gravity()
    attractors = update_attractors(scores)
    with _db() as conn:
        core = conn.execute(
            "SELECT concept, gravity, cycle_count FROM belief_attractors WHERE is_core=1 ORDER BY gravity DESC"
        ).fetchall()
        emerging = conn.execute(
            "SELECT concept, gravity, cycle_count FROM belief_attractors WHERE is_core=0 ORDER BY gravity DESC LIMIT 5"
        ).fetchall()
    return {
        "top_attractors": attractors,
        "core_attractors": [dict(r) for r in core],
        "emerging_attractors": [dict(r) for r in emerging],
        "gravity_scores": dict(list(scores.items())[:10])
    }

# ── GravityEngine daemon ──────────────────────────────────────────────────────
class GravityEngine:
    def __init__(self):
        self._gravity_last = 0.0
        self._seed_last    = 0.0
        self._thread       = None
        _ensure_schema()

    def tick(self):
        now = time.time()
        if now - self._gravity_last >= GRAVITY_INTERVAL:
            self._gravity_last = now
            try:
                scores = calculate_gravity()
                attractors = update_attractors(scores)
                if attractors:
                    top = attractors[0]
                    print(f"  [GRAVITY] top attractor: '{top['concept']}' "
                          f"(score={top['gravity']:.0f}, cycles={top['cycle_count']}, "
                          f"core={'yes' if top['is_core'] else 'no'})")
                log.info(f"[GRAVITY] calculated: {list(scores.items())[:5]}")
            except Exception as e:
                log.warning(f"[GRAVITY] gravity error: {e}")

        if now - self._seed_last >= SEED_INTERVAL:
            self._seed_last = now
            try:
                results = seed_all_attractors()
                if results["seeded"] > 0:
                    print(f"  [GRAVITY] seeded {results['seeded']} attractor beliefs")
            except Exception as e:
                log.warning(f"[GRAVITY] seed error: {e}")

    def _loop(self):
        time.sleep(180)
        while True:
            try:
                self.tick()
            except Exception as e:
                log.warning(f"[GRAVITY] loop error: {e}")
            time.sleep(600)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("[GRAVITY] GravityEngine started")

# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="NEX Belief Gravity")
    p.add_argument("--report",  action="store_true")
    p.add_argument("--seed",    action="store_true")
    p.add_argument("--gravity", action="store_true")
    p.add_argument("--concept", type=str)
    args = p.parse_args()
    _ensure_schema()

    if args.report:
        report = attractor_report()
        print("\n=== BELIEF GRAVITY REPORT ===")
        print(f"\nTop gravity scores:")
        for concept, score in report["gravity_scores"].items():
            print(f"  {score:>6.1f}  {concept}")
        print(f"\nCore attractors ({len(report['core_attractors'])}):")
        for a in report["core_attractors"]:
            print(f"  [{a['cycle_count']} cycles] {a['concept']}  gravity={a['gravity']:.0f}")
        print(f"\nEmerging attractors:")
        for a in report["emerging_attractors"]:
            print(f"  [{a['cycle_count']} cycles] {a['concept']}  gravity={a['gravity']:.0f}")

    elif args.gravity:
        scores = calculate_gravity()
        print("Gravity scores (top 15):")
        for concept, score in list(scores.items())[:15]:
            print(f"  {score:>6.1f}  {concept}")

    elif args.seed:
        scores = calculate_gravity()
        update_attractors(scores)
        results = seed_all_attractors()
        print(f"Seeded: {results}")

    elif args.concept:
        success = seed_attractor(args.concept)
        print(f"{'Success' if success else 'Failed'}")

    else:
        p.print_help()
