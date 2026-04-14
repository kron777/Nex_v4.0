#!/usr/bin/env python3
"""
NEX GROQ BELIEF FIX — nex_groq_belief_fix.py
=============================================
Fixes three core belief problems using Groq 120B:

  1. EMBRYO BACKLOG   — bulk-challenges 5,480 stuck embryos, promotes survivors
  2. TENSION DRAIN    — synthesizes 70 open tensions into depth=1 beliefs
  3. ARCHIVE MINE     — extracts insights from full conversations.jsonl

Run:  ./venv/bin/python3 nex_groq_belief_fix.py [--embryos] [--tensions] [--archive] [--all]

Safe to interrupt and re-run — all operations are idempotent.
"""

import argparse
import json
import os
import re
import sqlite3
import time
import urllib.request
import urllib.error
import urllib.error
from collections import defaultdict
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH   = Path.home() / "Desktop/nex/nex.db"
CONV_PATH = Path.home() / "Desktop/nex/logs/conversations.jsonl"
ENV_PATH  = Path.home() / ".config/nex/.env"

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# How many to process per run (increase if you have time/tokens)
EMBRYO_BATCH   = 200   # embryos per run
TENSION_BATCH  = 70    # drain all open tensions
ARCHIVE_BATCH  = 500   # conversation lines to scan per run

# Quality thresholds
MIN_BELIEF_LEN   = 35
MAX_BELIEF_LEN   = 280
MIN_CONF_PROMOTE = 0.72

SPAM_PATTERNS = [
    "bridge:truth seeking", "have to do with a different domain",
    "The interesting thing about bridge", "↔", "||", "[merged:",
    "this paper", "this work", "et al", "OPEN QUESTION",
    "What does this mean", "bridge:cognitive", "bridge:alignment",
    "None of these resolve in isolation", "synthesized around",
    "The insight is", "My analysis suggests", "My belief that",
]

# ── Groq helpers ─────────────────────────────────────────────────────────────

def _load_key() -> str:
    try:
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("GROQ_API_KEY"):
                k = line.split("=", 1)[1].strip().strip(chr(0))
                return k
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY", "")


def groq(prompt: str, max_tokens: int = 250, temp: float = 0.4) -> str:
    key = _load_key()
    if not key:
        raise RuntimeError("GROQ_API_KEY not found in ~/.config/nex/.env")
    payload = json.dumps({
        "model": GROQ_MODEL,
        "max_tokens": max_tokens,
        "temperature": temp,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        GROQ_URL, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"].strip()


# ── DB helpers ────────────────────────────────────────────────────────────────

def db():
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def is_spam(text: str) -> bool:
    return any(s in text for s in SPAM_PATTERNS)


def is_clean(text: str) -> bool:
    if not text or is_spam(text):
        return False
    if len(text) < MIN_BELIEF_LEN or len(text) > MAX_BELIEF_LEN:
        return False
    if text.endswith("?"):
        return False
    return True


def already_exists(conn, text: str) -> bool:
    """Check if a near-duplicate already exists in beliefs."""
    words = set(text.lower().split())
    rows = conn.execute(
        "SELECT content FROM beliefs ORDER BY rowid DESC LIMIT 300"
    ).fetchall()
    for r in rows:
        existing = set((r["content"] or "").lower().split())
        overlap = len(words & existing) / max(len(words), 1)
        if overlap > 0.80:
            return True
    return False


def insert_belief(conn, content: str, topic: str, confidence: float,
                  synthesis_depth: int, source: str) -> bool:
    try:
        conn.execute(
            """INSERT OR IGNORE INTO beliefs
               (content, topic, confidence, synthesis_depth,
                reinforce_count, locked, source, last_referenced)
               VALUES (?, ?, ?, ?, 1, 1, ?, datetime('now'))""",
            (content, topic, confidence, synthesis_depth, source),
        )
        if conn.total_changes > 0:
            conn.commit()
            return True
    except Exception as e:
        print(f"    [DB ERR] {e}")
    return False


# ── 1. EMBRYO BACKLOG FIX ─────────────────────────────────────────────────────

EMBRYO_CHALLENGE_PROMPT = """\
Evaluate this candidate belief:
"{belief}"

Score it 0-10 on:
- Epistemic quality: is it a genuine insight, not just a fact or fragment?
- Originality: does it say something non-obvious?
- Completeness: does it stand alone as a full thought?

If score >= 6, respond with:
PROMOTE: <compressed version in under 160 characters, assertive tone>

If score < 6, respond with:
REJECT: <one-word reason>

Respond with ONLY the PROMOTE or REJECT line."""


def fix_embryo_backlog(batch: int = EMBRYO_BATCH) -> dict:
    print(f"\n{'='*60}")
    print(f"EMBRYO BACKLOG FIX  (batch={batch})")
    print('='*60)

    conn = db()
    total_embryos = conn.execute(
        "SELECT COUNT(*) FROM belief_embryos WHERE stage='embryo' AND promoted=0"
    ).fetchone()[0]
    print(f"Total stuck embryos: {total_embryos}")

    # Prioritise self_research since that's the biggest source of noise
    rows = conn.execute(
        """SELECT id, raw_text, source, topic, source_quality
           FROM belief_embryos
           WHERE stage='embryo' AND promoted=0
           ORDER BY source_quality DESC, id ASC
           LIMIT ?""",
        (batch,),
    ).fetchall()
    print(f"Processing: {len(rows)}")

    stats = {"challenged": 0, "promoted": 0, "rejected": 0, "errors": 0}

    for i, row in enumerate(rows):
        raw = (row["raw_text"] or "").strip()
        if not raw or len(raw) < 20:
            conn.execute(
                "UPDATE belief_embryos SET promoted=0, stage='rejected' WHERE id=?",
                (row["id"],),
            )
            conn.commit()
            stats["rejected"] += 1
            continue

        if is_spam(raw):
            conn.execute(
                "UPDATE belief_embryos SET promoted=0, stage='rejected' WHERE id=?",
                (row["id"],),
            )
            conn.commit()
            stats["rejected"] += 1
            continue

        try:
            resp = groq(EMBRYO_CHALLENGE_PROMPT.format(belief=raw[:300]),
                        max_tokens=120, temp=0.3)
            stats["challenged"] += 1

            if resp.startswith("PROMOTE:"):
                compressed = resp[8:].strip().strip('"').strip("'")
                if not is_clean(compressed) or already_exists(conn, compressed):
                    conn.execute(
                        "UPDATE belief_embryos SET promoted=0, stage='rejected' WHERE id=?",
                        (row["id"],),
                    )
                    conn.commit()
                    stats["rejected"] += 1
                    continue

                topic = row["topic"] or "general"
                conf = min(0.85, (row["source_quality"] or 0.5) + 0.20)
                ok = insert_belief(conn, compressed, topic, conf, 1,
                                   f"forge:{row['source']}")
                if ok:
                    conn.execute(
                        "UPDATE belief_embryos SET promoted=1, stage='promoted' WHERE id=?",
                        (row["id"],),
                    )
                    conn.commit()
                    stats["promoted"] += 1
                    print(f"  [{i+1}] ✓ [{topic}] {compressed[:90]}")
                else:
                    stats["rejected"] += 1

            elif resp.startswith("REJECT:"):
                conn.execute(
                    "UPDATE belief_embryos SET promoted=0, stage='rejected' WHERE id=?",
                    (row["id"],),
                )
                conn.commit()
                stats["rejected"] += 1

            else:
                # Unexpected response — skip
                stats["errors"] += 1

        except urllib.error.HTTPError as e:
            if e.code == 403:
                conn.execute("UPDATE belief_embryos SET stage='rejected' WHERE id=?", (row['id'],))
                conn.commit()
                stats["rejected"] += 1
            else:
                print(f"  [ERR embryo {row['id']}] {e}")
                stats["errors"] += 1
                time.sleep(1)
        except Exception as e:
            print(f"  [ERR embryo {row['id']}] {e}")
            stats["errors"] += 1
            time.sleep(1)

        # Brief pause to avoid rate limit
        if (i + 1) % 10 == 0:
            time.sleep(0.5)
            print(f"  Progress: {i+1}/{len(rows)} — "
                  f"promoted={stats['promoted']} rejected={stats['rejected']}")

    conn.close()
    print(f"\nEMBRYO RESULT: {stats}")
    return stats


# ── 2. TENSION DRAIN ─────────────────────────────────────────────────────────

TENSION_SYNTHESIS_PROMPT = """\
Two beliefs are in tension:

A: {belief_a}
B: {belief_b}

These don't fully agree. Find the insight that resolves or transcends the tension — \
a new claim that explains why BOTH could be true, or what deeper principle they both \
point toward.

Rules:
- One sentence only, under 180 characters
- Must be assertive, not a question
- Must not repeat either belief verbatim
- If no genuine synthesis exists, respond: NONE

Respond with ONLY the synthesis sentence or NONE."""


def fix_tension_drain(batch: int = TENSION_BATCH) -> dict:
    print(f"\n{'='*60}")
    print(f"TENSION DRAIN  (batch={batch})")
    print('='*60)

    conn = db()
    rows = conn.execute(
        """SELECT t.id, t.topic, b1.content as a, b2.content as b,
                  b1.confidence as ca, b2.confidence as cb
           FROM tensions t
           JOIN beliefs b1 ON t.belief_a_id = b1.id
           JOIN beliefs b2 ON t.belief_b_id = b2.id
           WHERE t.resolved = 0
           ORDER BY t.id ASC
           LIMIT ?""",
        (batch,),
    ).fetchall()
    print(f"Open tensions: {len(rows)}")

    stats = {"processed": 0, "synthesized": 0, "skipped": 0}

    for i, row in enumerate(rows):
        a, b = row["a"] or "", row["b"] or ""
        if is_spam(a) or is_spam(b):
            conn.execute("UPDATE tensions SET resolved=1 WHERE id=?", (row["id"],))
            conn.commit()
            stats["skipped"] += 1
            continue

        try:
            resp = groq(
                TENSION_SYNTHESIS_PROMPT.format(
                    belief_a=a[:220], belief_b=b[:220]
                ),
                max_tokens=200, temp=0.45,
            )
            stats["processed"] += 1

            if not resp or "NONE" in resp.upper()[:8]:
                conn.execute("UPDATE tensions SET resolved=1 WHERE id=?", (row["id"],))
                conn.commit()
                stats["skipped"] += 1
                continue

            resp = resp.strip().strip('"').strip("'")

            # Overlap check against inputs
            resp_words = set(resp.lower().split())
            for src in [a, b]:
                src_words = set(src.lower().split())
                if len(resp_words & src_words) / max(len(resp_words), 1) > 0.70:
                    conn.execute("UPDATE tensions SET resolved=1 WHERE id=?", (row["id"],))
                    conn.commit()
                    stats["skipped"] += 1
                    resp = None
                    break

            if not resp:
                continue

            if not is_clean(resp) or already_exists(conn, resp):
                conn.execute("UPDATE tensions SET resolved=1 WHERE id=?", (row["id"],))
                conn.commit()
                stats["skipped"] += 1
                continue

            topic = row["topic"] or "dialectic"
            conf = min(0.82, ((row["ca"] or 0.5) + (row["cb"] or 0.5)) / 2 + 0.15)
            ok = insert_belief(conn, resp, topic, conf, 1, "dialectic_groq")
            if ok:
                conn.execute("UPDATE tensions SET resolved=1 WHERE id=?", (row["id"],))
                conn.commit()
                stats["synthesized"] += 1
                print(f"  [{i+1}] ✓ [{topic}] {resp[:90]}")
            else:
                stats["skipped"] += 1

        except urllib.error.HTTPError as e:
            if e.code == 403:
                conn.execute("UPDATE tensions SET resolved=1 WHERE id=?", (row['id'],))
                conn.commit()
                stats["skipped"] += 1
            else:
                print(f"  [ERR tension {row['id']}] {e}")
                time.sleep(1)
        except Exception as e:
            print(f"  [ERR tension {row['id']}] {e}")
            time.sleep(1)

        if (i + 1) % 10 == 0:
            time.sleep(0.5)
            print(f"  Progress: {i+1}/{len(rows)} — synthesized={stats['synthesized']}")

    conn.close()
    print(f"\nTENSION RESULT: {stats}")
    return stats


# ── 3. ARCHIVE MINE ───────────────────────────────────────────────────────────

ARCHIVE_EXTRACT_PROMPT = """\
Extract the single sharpest insight from this text. It must be:
- A clear assertive claim (not a question, not a summary)
- About consciousness, memory, reasoning, alignment, emergence, or identity
- Original — not a restatement of common knowledge
- Under 175 characters
- Does NOT start with "The insight is", "My", or "I think"

TEXT: {text}

Respond with ONLY the insight, or NONE if no strong claim exists."""

QUALITY_MARKERS = [
    "because", "therefore", "however", "suggests", "reveals",
    "implies", "demonstrates", "structure", "emerges", "pattern",
    "rather than", "not merely", "fundamentally", "ultimately",
]


def _load_quality_responses(limit: int) -> list:
    if not CONV_PATH.exists():
        print(f"  [WARN] {CONV_PATH} not found")
        return []

    lines = CONV_PATH.read_text(errors="ignore").splitlines()
    quality = []
    for line in lines:
        try:
            e = json.loads(line)
            if e.get("role") != "assistant":
                continue
            text = e.get("content", "")
            if len(text) < 200 or len(text) > 1800:
                continue
            if is_spam(text):
                continue
            score = sum(1 for m in QUALITY_MARKERS if m in text.lower())
            if score >= 3:
                quality.append(text)
        except Exception:
            continue

    print(f"  Quality responses in archive: {len(quality)}")
    return quality[:limit]


def fix_archive_mine(batch: int = ARCHIVE_BATCH) -> dict:
    print(f"\n{'='*60}")
    print(f"ARCHIVE MINE  (scanning up to {batch} quality responses)")
    print('='*60)

    responses = _load_quality_responses(batch)
    if not responses:
        print("  No quality responses found.")
        return {"scanned": 0, "harvested": 0}

    conn = db()
    stats = {"scanned": len(responses), "harvested": 0, "skipped": 0}

    for i, text in enumerate(responses):
        try:
            resp = groq(
                ARCHIVE_EXTRACT_PROMPT.format(text=text[:700]),
                max_tokens=200, temp=0.3,
            )

            if not resp or "NONE" in resp.upper()[:8]:
                stats["skipped"] += 1
                continue

            resp = resp.strip().strip('"').strip("'")

            if not is_clean(resp) or is_spam(resp):
                stats["skipped"] += 1
                continue

            if already_exists(conn, resp):
                stats["skipped"] += 1
                continue

            ok = insert_belief(conn, resp, "self_insight", 0.82, 1,
                               "response_harvest_groq")
            if ok:
                stats["harvested"] += 1
                print(f"  [{i+1}] ✓ {resp[:100]}")
            else:
                stats["skipped"] += 1

        except urllib.error.HTTPError as e:
            if e.code != 403:
                print(f"  [ERR response {i}] {e}")
                time.sleep(1)
            stats["skipped"] += 1
        except Exception as e:
            print(f"  [ERR response {i}] {e}")
            time.sleep(1)

        if (i + 1) % 20 == 0:
            time.sleep(0.3)
            print(f"  Progress: {i+1}/{len(responses)} — harvested={stats['harvested']}")

    conn.close()
    print(f"\nARCHIVE RESULT: {stats}")
    return stats


# ── STATS SUMMARY ─────────────────────────────────────────────────────────────

def print_stats():
    conn = db()
    print(f"\n{'='*60}")
    print("CURRENT PYRAMID STATE")
    print('='*60)
    total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    locked = conn.execute("SELECT COUNT(*) FROM beliefs WHERE locked=1").fetchone()[0]
    for d in [0, 1, 2, 3]:
        n = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE synthesis_depth=?", (d,)
        ).fetchone()[0]
        avg = conn.execute(
            "SELECT AVG(confidence) FROM beliefs WHERE synthesis_depth=?", (d,)
        ).fetchone()[0] or 0
        label = ["raw", "forge-synth", "cross-topic", "meta"][d]
        print(f"  depth={d} ({label:>12}): {n:>5}  avg_conf={avg:.3f}")
    print(f"  TOTAL: {total}  |  LOCKED: {locked}")

    remaining = conn.execute(
        "SELECT COUNT(*) FROM belief_embryos WHERE stage='embryo' AND promoted=0"
    ).fetchone()[0]
    open_t = conn.execute(
        "SELECT COUNT(*) FROM tensions WHERE resolved=0"
    ).fetchone()[0]
    print(f"\n  Embryo backlog remaining: {remaining}")
    print(f"  Open tensions remaining:  {open_t}")

    print("\n  Top sources:")
    for r in conn.execute(
        "SELECT source, COUNT(*) n FROM beliefs GROUP BY source ORDER BY n DESC LIMIT 8"
    ).fetchall():
        print(f"    {r['n']:>5}  {r['source']}")

    conn.close()


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NEX Groq Belief Fix")
    parser.add_argument("--embryos",  action="store_true", help="Fix embryo backlog")
    parser.add_argument("--tensions", action="store_true", help="Drain tension queue")
    parser.add_argument("--archive",  action="store_true", help="Mine conversation archive")
    parser.add_argument("--all",      action="store_true", help="Run all three fixes")
    parser.add_argument("--stats",    action="store_true", help="Show current stats only")
    parser.add_argument("--embryo-batch",  type=int, default=EMBRYO_BATCH)
    parser.add_argument("--tension-batch", type=int, default=TENSION_BATCH)
    parser.add_argument("--archive-batch", type=int, default=ARCHIVE_BATCH)
    args = parser.parse_args()

    # Verify Groq key
    key = _load_key()
    if not key:
        print("ERROR: GROQ_API_KEY not found in ~/.config/nex/.env")
        return
    print(f"Groq key loaded: {key[:12]}...")

    print_stats()

    if args.stats:
        return

    run_embryos  = args.embryos  or args.all
    run_tensions = args.tensions or args.all
    run_archive  = args.archive  or args.all

    if not any([run_embryos, run_tensions, run_archive]):
        print("\nNo action specified. Use --embryos, --tensions, --archive, or --all")
        print("Example: ./venv/bin/python3 nex_groq_belief_fix.py --all")
        return

    total_promoted = 0

    if run_embryos:
        r = fix_embryo_backlog(args.embryo_batch)
        total_promoted += r.get("promoted", 0)

    if run_tensions:
        r = fix_tension_drain(args.tension_batch)
        total_promoted += r.get("synthesized", 0)

    if run_archive:
        r = fix_archive_mine(args.archive_batch)
        total_promoted += r.get("harvested", 0)

    print(f"\n{'='*60}")
    print(f"TOTAL NEW BELIEFS ADDED: {total_promoted}")
    print('='*60)
    print_stats()


if __name__ == "__main__":
    main()
