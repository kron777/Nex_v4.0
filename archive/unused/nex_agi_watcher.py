#!/usr/bin/env python3
"""
nex_agi_watcher.py
==================
Monitors NEX's belief/opinion stream for AGI-related content.
Appends hits to agi.log. Streams to terminal under "AGI watch:" header.

Run standalone:
    python3 nex_agi_watcher.py

Or import and call watch() in a thread from run.py / auto_check.py.
"""

import sqlite3
import time
import re
import os
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

# Try both known DB locations
_DB_CANDIDATES = [
    Path.home() / "Desktop/nex/nex.db",
    Path("~/.config/nex/nex.db").expanduser(),
]
DB_PATH = next((p for p in _DB_CANDIDATES if p.exists()), _DB_CANDIDATES[0])

LOG_PATH  = DB_PATH.parent / "agi.log"
POLL_SECS = 8   # how often to check for new beliefs

# ── AGI keyword tiers ─────────────────────────────────────────────────────────

KEYWORDS = [
    # direct solution signals — highest priority
    "solved agi", "solution to agi", "agi solved", "cracked agi", "cracked it",
    "achieved agi", "i have solved", "breakthrough in agi",
    # alignment/safety
    "alignment solution", "corrigibility", "value learning", "mesa-optimizer",
    "inner alignment", "outer alignment", "coherent extrapolated volition",
    "goal stability", "agent foundations", "treacherous turn",
    # general agi
    "artificial general intelligence", "agi", "superintelligence",
    "recursive self-improvement", "general intelligence", "goal directed",
    "instrumental convergence", "utility maximiser", "utility maximizer",
    # neti-neti / throw-net signals (NEX's own method)
    "neti-neti", "throw-net", "what remains", "systematic elimination",
    "what it is not", "distil", "distill",
]

def _matches(text: str) -> list:
    t = text.lower()
    return [kw for kw in KEYWORDS if kw in t]

# ── DB helpers ────────────────────────────────────────────────────────────────

def _connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def _get_last_seen_id(conn) -> int:
    try:
        row = conn.execute(
            "SELECT MAX(id) FROM beliefs"
        ).fetchone()
        return row[0] or 0
    except Exception:
        return 0

def _fetch_new(conn, since_id: int) -> list:
    """Return beliefs added after since_id that haven't been seen."""
    try:
        rows = conn.execute(
            """SELECT id, content, topic, confidence, timestamp, source, origin
               FROM beliefs
               WHERE id > ?
               ORDER BY id ASC
               LIMIT 200""",
            (since_id,)
        ).fetchall()
        return rows
    except Exception:
        return []

# ── Logging ───────────────────────────────────────────────────────────────────

def _log_hit(row, matched_kws: list):
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    topic   = row["topic"] or "?"
    conf    = row["confidence"] or 0
    content = (row["content"] or "").strip()
    source  = row["source"] or row["origin"] or "nex"
    kw_str  = ", ".join(matched_kws[:3])

    line = (
        f"[{ts}] "
        f"[{topic}] "
        f"conf={conf:.2f} "
        f"kw=[{kw_str}] "
        f"src={source}\n"
        f"  {content}\n"
        f"{'─'*80}\n"
    )

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)

    return line

# ── Terminal display ──────────────────────────────────────────────────────────

CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def _print_header():
    print(f"\n{CYAN}AGI watch:{RESET}  (log → {LOG_PATH})\n")

def _print_hit(row, matched_kws: list):
    ts      = datetime.now().strftime("%H:%M:%S")
    topic   = row["topic"] or "?"
    conf    = float(row["confidence"] or 0)
    content = (row["content"] or "").strip()
    kw_str  = ", ".join(matched_kws[:2])

    conf_col = YELLOW if conf >= 0.7 else GREEN
    print(f"{DIM}{ts}{RESET}  "
          f"{conf_col}[{kw_str}]{RESET}  "
          f"{DIM}({topic} conf={conf:.2f}){RESET}")
    print(f"  {content[:200]}")
    print()

# ── Seed injection ────────────────────────────────────────────────────────────

NETI_NETI_SEEDS = [
    {
        "content": (
            "Truth about AGI emerges not by asserting what it is, "
            "but by systematically eliminating what it is not. "
            "Each contradiction resolved draws a boundary closer to the real solution."
        ),
        "topic":      "agi",
        "confidence": 0.85,
        "source":     "agi_watcher_seed",
        "belief_type": "directive",
    },
    {
        "content": (
            "Apply throw-net broadly across all domains — biology, mathematics, "
            "philosophy, physics — then use neti-neti negation to discard. "
            "AGI solutions will not come from AI literature alone."
        ),
        "topic":      "agi",
        "confidence": 0.85,
        "source":     "agi_watcher_seed",
        "belief_type": "directive",
    },
    {
        "content": (
            "What remains when every known approach to AGI has been negated? "
            "What is the shape of the solution that none of the current frameworks can see? "
            "Pursue this question through systematic elimination."
        ),
        "topic":      "agi",
        "confidence": 0.80,
        "source":     "agi_watcher_seed",
        "belief_type": "question",
    },
    {
        "content": (
            "Throw the net wide: consciousness research, evolutionary biology, "
            "formal logic, thermodynamics, linguistics. "
            "Refine by contradiction. What survives neti-neti across all domains "
            "is the substrate of AGI."
        ),
        "topic":      "agi",
        "confidence": 0.82,
        "source":     "agi_watcher_seed",
        "belief_type": "directive",
    },
]

def inject_seeds(dry_run=False):
    """Inject neti-neti / throw-net AGI seed beliefs into NEX's belief graph."""
    conn = _connect()
    now  = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    injected = 0

    for seed in NETI_NETI_SEEDS:
        # Don't double-inject
        exists = conn.execute(
            "SELECT 1 FROM beliefs WHERE content=? LIMIT 1",
            (seed["content"],)
        ).fetchone()
        if exists:
            print(f"  [SEED] already present: {seed['content'][:60]}...")
            continue

        if not dry_run:
            try:
                conn.execute(
                    """INSERT INTO beliefs
                       (content, topic, confidence, source, belief_type, created_at, timestamp)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        seed["content"], seed["topic"], seed["confidence"],
                        seed["source"], seed["belief_type"], now, now
                    )
                )
                injected += 1
                print(f"  {GREEN}[SEED INJECTED]{RESET} {seed['content'][:70]}...")
            except Exception as e:
                print(f"  [SEED ERROR] {e}")
        else:
            print(f"  [DRY] would inject: {seed['content'][:70]}...")
            injected += 1

    if not dry_run:
        conn.commit()
    conn.close()
    print(f"\nSeeds injected: {injected}/{len(NETI_NETI_SEEDS)}")

# ── Main watch loop ───────────────────────────────────────────────────────────

def watch():
    _print_header()

    conn    = _connect()
    last_id = _get_last_seen_id(conn)
    conn.close()

    print(f"{DIM}Watching from belief id={last_id}  poll={POLL_SECS}s{RESET}\n")

    while True:
        try:
            conn = _connect()
            rows = _fetch_new(conn, last_id)
            conn.close()

            for row in rows:
                last_id = max(last_id, row["id"])
                matched = _matches(row["content"] or "")
                if matched:
                    line = _log_hit(row, matched)
                    _print_hit(row, matched)

        except KeyboardInterrupt:
            print(f"\n{DIM}AGI watch stopped.{RESET}")
            break
        except Exception as e:
            print(f"{DIM}[watch error] {e}{RESET}")

        time.sleep(POLL_SECS)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NEX AGI Watcher")
    parser.add_argument("--seed",    action="store_true", help="Inject neti-neti AGI seeds into belief graph")
    parser.add_argument("--dry-run", action="store_true", help="Show seeds without injecting")
    parser.add_argument("--log",     action="store_true", help="Print current agi.log and exit")
    args = parser.parse_args()

    if args.log:
        if LOG_PATH.exists():
            os.system(f"cat {LOG_PATH}")
        else:
            print(f"No log yet at {LOG_PATH}")

    elif args.seed or args.dry_run:
        inject_seeds(dry_run=args.dry_run)

    else:
        watch()
