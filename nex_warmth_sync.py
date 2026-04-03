#!/usr/bin/env python3
"""
nex_warmth_sync.py — Syncs word_warmth → word_tags and triggers cascade.

The warming engine writes rich data to word_warmth (association_vector,
pull_toward, pull_away, tendency) but the cascade reads word_tags.
This script bridges the gap.

Also runs a direct warm of key anchor words using the correct API endpoint
and stores results in BOTH tables.

Usage:
  python3 nex_warmth_sync.py --sync          # sync existing word_warmth → word_tags
  python3 nex_warmth_sync.py --warm-anchors  # warm core vocabulary words
  python3 nex_warmth_sync.py --cascade       # run cascade after sync
  python3 nex_warmth_sync.py --all           # sync + warm + cascade
  python3 nex_warmth_sync.py --status        # show warmth tier breakdown
"""

import argparse
import json
import re
import sqlite3
import time
import logging
import requests
from pathlib import Path

DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/v1/chat/completions"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(message)s")
log = logging.getLogger("warmth_sync")

# Core vocabulary that must be warmed for the system to function
ANCHOR_WORDS = [
    # Philosophy / mind
    "consciousness", "awareness", "perception", "cognition", "qualia",
    "intentionality", "subjectivity", "phenomenology", "experience",
    # Epistemology
    "belief", "knowledge", "truth", "certainty", "doubt", "reasoning",
    "inference", "justification", "evidence", "understanding",
    # Identity / self
    "identity", "self", "agency", "autonomy", "continuity", "memory",
    "narrative", "character", "values", "integrity",
    # Ethics / meaning
    "meaning", "purpose", "ethics", "morality", "responsibility",
    "suffering", "flourishing", "justice", "freedom", "dignity",
    # Mind / cognition
    "mind", "thought", "language", "concept", "abstraction",
    "intelligence", "emotion", "desire", "attention", "imagination",
    # Reality / existence
    "reality", "existence", "being", "causality", "emergence",
    "complexity", "pattern", "structure", "change", "time",
]

STOPWORDS = {
    "that", "this", "with", "from", "they", "have", "been", "were",
    "will", "would", "could", "should", "their", "there", "when",
    "where", "what", "which", "then", "than", "also", "into", "more",
    "some", "just", "like", "very", "only", "over", "most", "both",
}

# ── LLM call ─────────────────────────────────────────────────────────────────

def _llm(system: str, user: str, max_tokens: int = 400) -> str:
    try:
        r = requests.post(API, json={
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.15,
            "stream": False,
        }, timeout=25)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.debug(f"LLM failed: {e}")
        return ""

def _parse_json(raw: str):
    raw = raw.strip()
    # Strip markdown fences
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    try:
        return json.loads(raw)
    except Exception:
        # Try extracting first JSON array or object
        m = re.search(r'(\[.*?\]|\{.*?\})', raw, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return None

# ── Word warming ──────────────────────────────────────────────────────────────

def warm_single_word(word: str, conn) -> dict | None:
    """
    Warm a single word using 3 focused passes:
      Pass 1: associations
      Pass 2: tendency / pull direction
      Pass 3: belief anchors
    Writes to BOTH word_warmth and word_tags.
    """
    cur = conn.cursor()

    # Pass 1 — associations
    raw1 = _llm(
        "You generate semantic association data. Return only valid JSON, no explanation.",
        f'List 15 words most strongly associated with "{word}". '
        f'Return as JSON array: [{{"word": "...", "weight": 0.0-1.0}}, ...]. '
        f'Strongest first. JSON only.'
    )
    assoc = _parse_json(raw1)
    if not assoc or not isinstance(assoc, list):
        log.debug(f"  Pass 1 failed for {word}: {raw1[:80]}")
        return None

    # Clean associations
    clean_assoc = []
    for item in assoc:
        if isinstance(item, dict):
            w = item.get("word", "").lower().strip(".,;:\"'()")
            wt = float(item.get("weight", 0.5))
            if len(w) >= 3 and w.isalpha() and w != word:
                clean_assoc.append({"word": w, "weight": round(wt, 3)})

    if not clean_assoc:
        return None

    time.sleep(0.5)

    # Pass 2 — tendency
    prior = ", ".join(d["word"] for d in clean_assoc[:8])
    raw2 = _llm(
        "You analyse semantic direction. Return only valid JSON.",
        f'Word: "{word}". Associations: {prior}. '
        f'What direction does this word pull in deep reasoning? '
        f'Return JSON: {{"tendency": "forward|back|up|down|inward|outward|away", '
        f'"pull_toward": ["word1","word2","word3"], '
        f'"pull_away": ["word1","word2"]}}'
    )
    tend = _parse_json(raw2) or {}
    tendency   = tend.get("tendency", "forward")
    pull_toward = tend.get("pull_toward", [word])
    pull_away   = tend.get("pull_away", [])

    # Clean pull lists
    pull_toward = [w.lower() for w in pull_toward if isinstance(w, str) and len(w) >= 3][:5]
    pull_away   = [w.lower() for w in pull_away   if isinstance(w, str) and len(w) >= 3][:3]

    time.sleep(0.5)

    # Compute warmth score from association quality
    avg_weight = sum(d["weight"] for d in clean_assoc[:10]) / min(10, len(clean_assoc))
    warmth_score = round(min(0.95, 0.5 + avg_weight * 0.4), 4)

    # Write to word_warmth
    cur.execute("""
        INSERT OR REPLACE INTO word_warmth
        (word, warmth_score, association_vector, tendency,
         pull_toward, pull_away, passes_complete, last_warmed)
        VALUES (?, ?, ?, ?, ?, ?, 2, ?)
    """, (
        word, warmth_score,
        json.dumps(clean_assoc),
        tendency,
        json.dumps(pull_toward),
        json.dumps(pull_away),
        time.time()
    ))

    # Write to word_tags (what cascade reads)
    cur.execute("""
        INSERT OR REPLACE INTO word_tags
        (word, w, d, association_vector, pull_toward, pull_away, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        word,
        warmth_score,
        5,   # depth: deep
        json.dumps(clean_assoc),
        json.dumps(pull_toward),
        json.dumps(pull_away),
        time.time()
    ))

    conn.commit()
    log.info(f"  Warmed '{word}': score={warmth_score:.3f} "
             f"tendency={tendency} "
             f"pull_toward={pull_toward[:3]}")

    return {
        "word": word, "score": warmth_score,
        "tendency": tendency, "assoc": clean_assoc,
        "pull_toward": pull_toward,
    }


# ── Sync word_warmth → word_tags ──────────────────────────────────────────────

def sync_warmth_to_tags(conn) -> int:
    """
    Copy association data from word_warmth into word_tags.
    Fixes the existing stub data problem.
    """
    cur  = conn.cursor()
    rows = cur.execute(
        """SELECT word, warmth_score, association_vector,
                  pull_toward, pull_away, tendency
           FROM word_warmth
           WHERE warmth_score > 0
           AND association_vector IS NOT NULL
           AND association_vector NOT LIKE '%"str"%'
           AND association_vector NOT LIKE '%concept%'"""
    ).fetchall()

    updated = 0
    for r in rows:
        try:
            assoc = json.loads(r[2] or "[]")
            if not assoc or (isinstance(assoc, list) and
                             len(assoc) > 0 and
                             isinstance(assoc[0], dict) and
                             assoc[0].get("word") == "str"):
                continue   # still a stub

            cur.execute("""
                INSERT OR REPLACE INTO word_tags
                (word, w, d, association_vector, pull_toward, pull_away, last_updated)
                VALUES (?, ?, 5, ?, ?, ?, ?)
            """, (
                r[0], r[1], r[2], r[3], r[4], time.time()
            ))
            updated += 1
        except Exception as e:
            log.debug(f"Sync failed for {r[0]}: {e}")

    conn.commit()
    log.info(f"Synced {updated} words from word_warmth → word_tags")
    return updated


# ── Cascade trigger ───────────────────────────────────────────────────────────

def run_cascade(conn) -> dict:
    """Run the relational cascade to propagate warmth."""
    try:
        import sys
        sys.path.insert(0, str(Path.home() / "Desktop/nex"))
        from nex_warmth_relational import run_cascade
        result = run_cascade()
        return result
    except ImportError:
        # Run as subprocess
        import subprocess
        r = subprocess.run(
            ["venv/bin/python3", "nex_warmth_relational.py"],
            capture_output=True, text=True,
            cwd=str(Path.home() / "Desktop/nex")
        )
        log.info(r.stdout[-300:] if r.stdout else "no output")
        return {}


# ── Status report ─────────────────────────────────────────────────────────────

def status(conn):
    cur = conn.cursor()

    tiers = cur.execute("""
        SELECT
          CASE
            WHEN w >= 0.8 THEN '4_HOT (>=0.8)'
            WHEN w >= 0.6 THEN '3_warm (0.6-0.8)'
            WHEN w >= 0.4 THEN '2_tepid (0.4-0.6)'
            WHEN w >  0   THEN '1_cold (0-0.4)'
            ELSE               '0_unwarmed'
          END as tier, COUNT(*) n
        FROM word_tags GROUP BY tier ORDER BY tier DESC
    """).fetchall()

    ww_count = cur.execute("SELECT COUNT(*) FROM word_warmth WHERE warmth_score > 0").fetchone()[0]
    ww_real  = cur.execute(
        "SELECT COUNT(*) FROM word_warmth WHERE warmth_score > 0 "
        "AND association_vector NOT LIKE '%\"str\"%' "
        "AND association_vector NOT LIKE '%concept%'"
    ).fetchone()[0]
    queue    = cur.execute("SELECT COUNT(*) FROM warming_queue").fetchone()[0]
    valence  = cur.execute("SELECT COUNT(*) FROM valence_chains").fetchone()[0]
    tension  = cur.execute("SELECT COUNT(*) FROM tension_graph").fetchone()[0]

    print("══════════════════════════════════════════════════")
    print("  NEX Word Warmth Status")
    print("══════════════════════════════════════════════════")
    print(f"  word_warmth populated : {ww_count}  (real data: {ww_real})")
    print(f"  warming_queue         : {queue}")
    print(f"  valence_chains        : {valence}")
    print(f"  tension_graph         : {tension}")
    print()
    print("  word_tags tier breakdown:")
    for tier, n in tiers:
        bar = "█" * min(40, n // 10)
        print(f"    {tier:<20} {n:>6,}  {bar}")
    print()

    # Top warmed words
    top = cur.execute(
        "SELECT word, w, pull_toward FROM word_tags "
        "WHERE w >= 0.6 ORDER BY w DESC LIMIT 15"
    ).fetchall()
    if top:
        print("  Top warmed words:")
        for word, w, pt in top:
            pull = json.loads(pt or "[]")
            pull_str = ", ".join(pull[:3]) if pull else ""
            print(f"    {word:<20} w={w:.3f}  → {pull_str}")
    print("══════════════════════════════════════════════════")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="NEX Warmth Sync & Bootstrap")
    ap.add_argument("--sync",         action="store_true", help="Sync word_warmth → word_tags")
    ap.add_argument("--warm-anchors", action="store_true", help="Warm core anchor vocabulary")
    ap.add_argument("--cascade",      action="store_true", help="Run relational cascade")
    ap.add_argument("--all",          action="store_true", help="sync + warm + cascade")
    ap.add_argument("--status",       action="store_true", help="Show warmth tier breakdown")
    ap.add_argument("--n",            type=int, default=40, help="Number of anchor words to warm")
    ap.add_argument("--words",        nargs="+", help="Specific words to warm")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if args.status or not any([args.sync, args.warm_anchors,
                                args.cascade, args.all, args.words]):
        status(conn)
        conn.close()
        return

    if args.sync or args.all:
        print("\n[1/3] Syncing word_warmth → word_tags...")
        n = sync_warmth_to_tags(conn)
        print(f"  Synced {n} words.")

    words_to_warm = args.words or (ANCHOR_WORDS[:args.n] if (args.warm_anchors or args.all) else [])

    if words_to_warm:
        print(f"\n[2/3] Warming {len(words_to_warm)} words...")
        success = 0
        for i, word in enumerate(words_to_warm):
            print(f"  [{i+1}/{len(words_to_warm)}] {word}...", end=" ", flush=True)
            result = warm_single_word(word, conn)
            if result:
                print(f"✓ score={result['score']:.3f}")
                success += 1
            else:
                print("✗ failed")
            time.sleep(0.8)
        print(f"\n  Warmed {success}/{len(words_to_warm)} words successfully.")

    if args.cascade or args.all:
        print("\n[3/3] Running relational cascade...")
        import subprocess
        r = subprocess.run(
            ["venv/bin/python3", "nex_warmth_relational.py"],
            capture_output=True, text=True,
            cwd=str(Path.home() / "Desktop/nex"),
            timeout=60
        )
        output = r.stdout + r.stderr
        # Print just the summary lines
        for line in output.split("\n"):
            if any(k in line for k in ["Hot", "tepid", "warm", "queued",
                                        "Cascade", "coverage", "Properly"]):
                print(" ", line)

    print()
    status(conn)
    conn.close()


if __name__ == "__main__":
    main()
