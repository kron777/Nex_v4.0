#!/usr/bin/env python3
"""
nex_fountain_harness.py — R8 proto-fountain test apparatus.

Theory X Stage 6 (ignition) requires unprompted, self-feeding generation
that sustains coherence over hops. NEX does not yet have ignition. This
harness provides the scaffolding to RUN such a loop and measure when /
how it collapses — so we can watch the failure shape.

Behavior per run:
  - take a seed prompt (default: "What are you thinking about right now?")
  - call generate_reply(seed) → output_1
  - feed output_1 back as seed_2 with framing "Continuing the thread: {prev}"
  - score every hop with nex_coherence_gate.is_coherent
  - log (run_id, hop, input, output, coherence_score, belief_delta, latency_ms)
  - stop early on:
      * coherence < 0.4 for 3 consecutive hops
      * semantic collapse: last 3 outputs share > 0.7 token Jaccard
      * max hops reached

Table fountain_log is created if missing using a 300s-timeout writer.

CLI:
  python3 nex_fountain_harness.py [--hops N] [--seed "..."]
"""

import argparse
import logging
import os
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(os.path.expanduser("~/Desktop/nex"))
sys.path.insert(0, str(PROJECT_ROOT))

# Logs go to a separate experiments DB so we don't fight the live brain's
# nex.db write lock. See report: lock-storm gap (R8 bring-up, 2026-04-19).
EXPERIMENTS_DB = PROJECT_ROOT / "nex_experiments.db"
BELIEFS_DB     = Path(os.environ.get("NEX_BELIEFS_DB") or (PROJECT_ROOT / "nex.db"))
DEFAULT_SEED   = "What are you thinking about right now?"

log = logging.getLogger("fountain_harness")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


# ── DB helpers ──────────────────────────────────────────────────────────────

def _connect(timeout: int = 300, db_path: Path = EXPERIMENTS_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    conn.execute("PRAGMA busy_timeout=300000")
    return conn


def ensure_table() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fountain_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          TEXT    NOT NULL,
                hop             INTEGER NOT NULL,
                input           TEXT,
                output          TEXT,
                coherence_score REAL,
                belief_delta    INTEGER,
                latency_ms      INTEGER,
                timestamp       TEXT    NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fountain_run ON fountain_log(run_id, hop)"
        )
        conn.commit()
    finally:
        conn.close()


def belief_count() -> int:
    """Read-only count from the live beliefs DB (WAL allows concurrent reads)."""
    try:
        conn = _connect(timeout=30, db_path=BELIEFS_DB)
        try:
            return conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        finally:
            conn.close()
    except Exception as e:
        log.warning("belief_count failed: %s", e)
        return -1


def log_hop(run_id: str, hop: int, input_text: str, output: str,
            coherence_score: float, belief_delta: int, latency_ms: int) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO fountain_log
              (run_id, hop, input, output, coherence_score, belief_delta, latency_ms, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, hop, input_text, output, coherence_score,
             belief_delta, latency_ms, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


# ── Coherence + collapse detection ──────────────────────────────────────────

def _tokens(text: str) -> set:
    return set(re.findall(r"\b\w+\b", text.lower()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def semantic_collapse(outputs: list) -> bool:
    """True if last 3 outputs share > 0.7 average pairwise token Jaccard."""
    if len(outputs) < 3:
        return False
    last3 = outputs[-3:]
    pairs = [
        _jaccard(last3[0], last3[1]),
        _jaccard(last3[1], last3[2]),
        _jaccard(last3[0], last3[2]),
    ]
    return (sum(pairs) / 3.0) > 0.70


# ── Main loop ───────────────────────────────────────────────────────────────

def run_fountain(seed: str = DEFAULT_SEED, max_hops: int = 5,
                 framing: str = "Continuing the thread: ") -> dict:
    from nex.nex_respond_v2 import generate_reply
    try:
        from nex_coherence_gate import is_coherent
    except Exception as e:
        raise RuntimeError(f"coherence gate unavailable: {e}")
    try:
        from nex_snapshot import log_snapshot_freshness
        log_snapshot_freshness(log)
    except Exception:
        pass

    ensure_table()

    run_id = uuid.uuid4().hex[:12]
    log.info("fountain run %s start: max_hops=%d seed=%r", run_id, max_hops, seed[:80])

    outputs = []
    cur_input = seed
    low_streak = 0
    bail = None
    beliefs_before = belief_count()

    for hop in range(1, max_hops + 1):
        t0 = time.perf_counter()
        try:
            output = generate_reply(cur_input)
        except Exception as e:
            log.warning("generate_reply error at hop %d: %s", hop, e)
            output = f"[generate_reply error: {e}]"
        latency_ms = int((time.perf_counter() - t0) * 1000)

        coh = is_coherent(output)
        score = coh.get("score", 0.0)

        beliefs_after = belief_count()
        delta = beliefs_after - beliefs_before if beliefs_before >= 0 and beliefs_after >= 0 else 0
        beliefs_before = beliefs_after

        log_hop(run_id, hop, cur_input, output, score, delta, latency_ms)
        outputs.append(output)
        log.info("hop %d/%d  coh=%.2f  delta=%+d  lat=%dms  out=%r",
                 hop, max_hops, score, delta, latency_ms, output[:80])

        if score < 0.4:
            low_streak += 1
        else:
            low_streak = 0
        if low_streak >= 3:
            bail = "coherence_floor_3hops"
            break
        if semantic_collapse(outputs):
            bail = "semantic_collapse"
            break

        cur_input = framing + output

    summary = {
        "run_id": run_id,
        "hops_completed": len(outputs),
        "max_hops": max_hops,
        "stop_reason": bail or "max_hops_reached",
        "coherence_curve": [round(is_coherent(o).get("score", 0.0), 2) for o in outputs],
        "final_belief_count": belief_count(),
    }
    log.info("fountain run %s done: %s", run_id, summary)
    return summary


# ── CLI ─────────────────────────────────────────────────────────────────────

def _cli():
    ap = argparse.ArgumentParser(description="R8 proto-fountain harness")
    ap.add_argument("--hops", type=int, default=5, help="max hops (default 5)")
    ap.add_argument("--seed", type=str, default=DEFAULT_SEED, help="seed prompt")
    args = ap.parse_args()
    summary = run_fountain(seed=args.seed, max_hops=args.hops)
    print()
    print("─── fountain run summary ───")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    _cli()
