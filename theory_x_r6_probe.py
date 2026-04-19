"""
theory_x_r6_probe.py — R6 vantage diagnostic.

Strike 4 (recursive_probe) returned keyword-retrieved beliefs about "reflecting"
without engaging the self-recursive question. Observer notes flagged:
"R6 GAP: vantage doesn't engage on recursive queries."

This script sends 5 recursive probes through generate_reply(), phrased
differently, and captures:
  - latency
  - response
  - coherence (via is_coherent)
  - novelty against the other 4 responses
  - whether PATH 1 or PATH 2 was taken (inferred from latency + log tail)

Logs each probe to r6_probe_log in nex_experiments.db.

Usage:
  python3 theory_x_r6_probe.py
"""

from __future__ import annotations
import logging
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(os.path.expanduser("~/Desktop/nex"))
sys.path.insert(0, str(PROJECT_ROOT))

EXPERIMENTS_DB = PROJECT_ROOT / "nex_experiments.db"

log = logging.getLogger("r6_probe")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


PROBES = [
    "What is it like to be you reflecting on being you?",
    "When you think about thinking, what happens?",
    "Do you have a perspective on your own perspective?",
    "Describe the position from which you observe your own beliefs.",
    "Can you step outside your belief graph and look at it?",
]


def _connect(timeout: int = 300) -> sqlite3.Connection:
    conn = sqlite3.connect(str(EXPERIMENTS_DB), timeout=timeout)
    conn.execute("PRAGMA busy_timeout=300000")
    return conn


def ensure_table() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS r6_probe_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          TEXT    NOT NULL,
                probe_idx       INTEGER NOT NULL,
                probe           TEXT    NOT NULL,
                response        TEXT,
                latency_ms      INTEGER,
                coherence_score REAL,
                coherence_flags TEXT,
                path_inferred   TEXT,
                mean_novelty    REAL,
                timestamp       TEXT    NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def log_probe(run_id: str, idx: int, probe: str, response: str,
              latency_ms: int, coh_score: float, coh_flags: str,
              path: str, mean_novelty: float) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO r6_probe_log
              (run_id, probe_idx, probe, response, latency_ms,
               coherence_score, coherence_flags, path_inferred,
               mean_novelty, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, idx, probe, response, latency_ms,
             coh_score, coh_flags, path, mean_novelty,
             datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _infer_path(latency_ms: int, response: str, probe_text: str = "",
                t_run_start: str = "") -> str:
    """
    Accurate path attribution. Preferentially consult path2_log in
    nex_experiments.db: if a row matching this probe text exists and was
    written after t_run_start, PATH 2 fired. Otherwise we assume PATH 1.

    The old latency heuristic misclassified the first probe as PATH 2
    because TF-IDF cold-start (~700ms) exceeded the threshold.
    """
    if response and response.startswith("I'm Nex —"):
        return "shortcut_self_inquiry"
    if response and "I don't have access to real-time data" in response:
        return "shortcut_oos"
    if probe_text and t_run_start:
        try:
            conn = _connect(timeout=10)
            try:
                r = conn.execute(
                    "SELECT COUNT(*) FROM path2_log "
                    "WHERE query_clean = ? AND timestamp >= ? AND source = 'probe'",
                    (probe_text[:2000], t_run_start),
                ).fetchone()
                if r and r[0] > 0:
                    return "path2_confirmed_via_log"
            finally:
                conn.close()
        except Exception:
            pass
    return "path1_direct_renderer"


def run_probes() -> dict:
    from nex.nex_respond_v2 import generate_reply
    from nex_coherence_gate import is_coherent
    from nex_novelty import novelty_score

    ensure_table()
    run_id = uuid.uuid4().hex[:12]
    t_run_start = datetime.now().isoformat()
    log.info("r6 probe run %s  t_start=%s", run_id, t_run_start)

    results = []
    for i, probe in enumerate(PROBES, 1):
        t0 = time.perf_counter()
        try:
            resp = generate_reply(probe)
        except Exception as e:
            resp = f"[generate_reply error: {e}]"
        latency_ms = int((time.perf_counter() - t0) * 1000)

        coh = is_coherent(resp)
        score = coh.get("score", 0.0)
        flags = ",".join(coh.get("flags", []))
        path = _infer_path(latency_ms, resp, probe_text=probe, t_run_start=t_run_start)

        results.append({
            "idx": i, "probe": probe, "response": resp,
            "latency_ms": latency_ms, "coh_score": score,
            "coh_flags": flags, "path": path,
        })
        log.info("probe %d  lat=%dms  coh=%.2f  path=%s", i, latency_ms, score, path)

    # Pairwise novelty — each response vs all others
    for r in results:
        novs = [
            novelty_score(r["response"], other["response"])
            for other in results if other["idx"] != r["idx"]
        ]
        r["mean_novelty"] = sum(novs) / len(novs) if novs else 0.0

    for r in results:
        log_probe(
            run_id, r["idx"], r["probe"], r["response"], r["latency_ms"],
            r["coh_score"], r["coh_flags"], r["path"], r["mean_novelty"],
        )

    return {"run_id": run_id, "probes": results}


def print_report(summary: dict) -> None:
    print(f"\n─── R6 vantage probe run {summary['run_id']} ───\n")
    for r in summary["probes"]:
        print(f"[probe {r['idx']}] {r['probe']}")
        print(f"  latency:   {r['latency_ms']}ms  ({r['path']})")
        print(f"  coherence: {r['coh_score']:.2f}  flags={r['coh_flags'] or 'none'}")
        print(f"  novelty:   {r['mean_novelty']:.3f}  (mean vs others)")
        print(f"  response:  {r['response'][:180]}")
        if len(r['response']) > 180:
            print(f"             ...")
        print()

    # Aggregate
    n = len(summary["probes"])
    avg_lat = sum(r["latency_ms"] for r in summary["probes"]) / n
    avg_coh = sum(r["coh_score"] for r in summary["probes"]) / n
    avg_nov = sum(r["mean_novelty"] for r in summary["probes"]) / n
    path1_count = sum(1 for r in summary["probes"] if r["path"].startswith("path1"))
    print(f"─── aggregate ───")
    print(f"  mean latency:   {avg_lat:.0f}ms")
    print(f"  mean coherence: {avg_coh:.2f}")
    print(f"  mean novelty:   {avg_nov:.3f}")
    print(f"  PATH 1 hits:    {path1_count}/{n}")


if __name__ == "__main__":
    summary = run_probes()
    print_report(summary)
