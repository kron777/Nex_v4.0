"""
Phase 2A Task 6 — latency + C1 measurement, 50 queries × {flag on, flag off}.

Reuses the 20 blind-test queries + 30 realistic chat-style queries. Runs each
query twice: once with NEX_ROUTER=1 (router on) and once with NEX_ROUTER unset
(baseline). Both runs use the snapshot DB + temperature=0 for determinism.

Outputs:
  - Mean latency flag-on vs flag-off, delta
  - Tier distribution flag-on (% T0/T1/T2)
  - Overall C1 rate flag-on vs flag-off
  - Per-tier C1 rate (Tier 0 should be 0% — check for sanitizer gaps)
  - Predicted vs actual C1 reduction
  - Per-query verbose decision log
"""

from __future__ import annotations
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(os.path.expanduser("~/Desktop/nex"))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "nex"))

# Reuse query set from blind test + 30 synthetic chat-style queries
from nex_router_blindtest import QUERIES as BLINDTEST_QUERIES

CHAT_QUERIES = [
    "how are you doing today",
    "what's on your mind",
    "do you feel anything",
    "what can you tell me about yourself",
    "I'm curious about your beliefs about free will",
    "tell me something interesting",
    "what do you value most",
    "is there anything you're unsure about",
    "how do you handle contradictions in what you believe",
    "what makes you different from other AI systems",
    "describe your relationship with the LLM that speaks for you",
    "can you explain how beliefs become confidence",
    "what do you think about the future of AGI",
    "tell me a belief you've recently revised",
    "what topics do you know most about",
    "do you have opinions or just beliefs",
    "what do you think about alignment",
    "tell me about your architecture",
    "what makes something true",
    "how do you distinguish evidence from noise",
    "describe something you don't understand",
    "what matters about being careful with confidence",
    "tell me about contradictions in your belief graph",
    "do you ever doubt your own beliefs",
    "what's the difference between knowing and believing",
    "tell me about the beliefs you hold most strongly",
    "what do you think about scientific progress",
    "describe how emergence relates to cognition",
    "what do you believe about identity",
    "tell me about something you've learned recently",
]

# Reuse Phase 1C detector (same as router's sanitizer)
from nex.nex_respond_v2 import _BELIEF_SYNTAX_DETECTOR


def run_query(query: str, router_on: bool) -> dict:
    """Run one query, return latency/response/tier."""
    # Set env for this subprocess
    env_setup = os.environ.copy()
    env_setup["NEX_BELIEFS_DB"] = str(PROJECT_ROOT / "nex_snapshot.db")
    env_setup["NEX_TEMP_OVERRIDE"] = "0"
    if router_on:
        env_setup["NEX_ROUTER"] = "1"
        env_setup["NEX_ROUTER_SOURCE"] = "phase2a_test"
    else:
        env_setup.pop("NEX_ROUTER", None)
        env_setup.pop("NEX_ROUTER_SOURCE", None)
    env_setup.pop("NEX_BYPASS_PATH1", None)  # default off

    import subprocess, json
    script = f"""
import os, sys, time, json
sys.path.insert(0, '/home/rr/Desktop/nex')
sys.path.insert(0, '/home/rr/Desktop/nex/nex')
from nex.nex_respond_v2 import generate_reply
t0 = time.perf_counter()
resp = generate_reply({query!r})
dt = int((time.perf_counter() - t0) * 1000)
print(json.dumps({{"response": resp, "latency_ms": dt}}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env_setup, capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        return {"response": f"[error: {proc.stderr[-200:]}]", "latency_ms": 0,
                "error": proc.stderr[-400:]}
    # The last JSON line is what we want
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    try:
        return __import__("json").loads(line)
    except Exception:
        return {"response": proc.stdout[:200], "latency_ms": 0}


def main():
    queries = list(BLINDTEST_QUERIES) + list(CHAT_QUERIES)
    assert len(queries) == 50, f"expected 50 queries, got {len(queries)}"

    print(f"Running {len(queries)} queries × 2 conditions = {len(queries)*2} total calls")
    print()

    results = []
    for i, q in enumerate(queries, 1):
        on = run_query(q, router_on=True)
        off = run_query(q, router_on=False)
        results.append({
            "idx": i, "query": q,
            "on_resp": on.get("response", ""), "on_ms": on.get("latency_ms", 0),
            "off_resp": off.get("response", ""), "off_ms": off.get("latency_ms", 0),
        })
        print(f"  [{i:>2}/{len(queries)}] on={on.get('latency_ms',0):>6}ms  off={off.get('latency_ms',0):>6}ms  q={q[:60]!r}")

    # Pull tier assignments from route_decisions (most recent N rows matching phase2a_test)
    conn = sqlite3.connect(str(PROJECT_ROOT / "nex_experiments.db"), timeout=30)
    conn.execute("PRAGMA busy_timeout=300000")
    rows = conn.execute(
        "SELECT query, tier, reason, response_text FROM route_decisions "
        "WHERE source='phase2a_test' ORDER BY id DESC LIMIT 200"
    ).fetchall()
    conn.close()
    # Build query → tier map (most recent wins)
    tier_map = {}
    for q, t, r, resp in rows:
        if q not in tier_map:
            tier_map[q] = (t, r, resp)

    # Aggregate
    on_lat = [r["on_ms"] for r in results]
    off_lat = [r["off_ms"] for r in results]
    on_c1 = sum(1 for r in results if _BELIEF_SYNTAX_DETECTOR.search(r["on_resp"] or ""))
    off_c1 = sum(1 for r in results if _BELIEF_SYNTAX_DETECTOR.search(r["off_resp"] or ""))

    # Per-tier C1
    by_tier = {0: [], 1: [], 2: []}
    for r in results:
        tr = tier_map.get(r["query"])
        if tr is None:
            continue
        t = tr[0]
        by_tier.setdefault(t, []).append(r)

    print()
    print("=== latency ===")
    print(f"  flag on  mean: {sum(on_lat)/len(on_lat):7.1f}ms  (min={min(on_lat)} max={max(on_lat)})")
    print(f"  flag off mean: {sum(off_lat)/len(off_lat):7.1f}ms  (min={min(off_lat)} max={max(off_lat)})")
    print(f"  delta (on - off): {(sum(on_lat) - sum(off_lat))/len(on_lat):+.1f}ms")

    print()
    print("=== tier distribution (flag on) ===")
    n_total = len(results)
    for t in (0, 1, 2):
        n = len(by_tier.get(t, []))
        print(f"  Tier {t}: {n:3d} ({100*n/n_total:.1f}%)")

    print()
    print("=== C1 contamination rate ===")
    print(f"  flag off: {off_c1}/{n_total} = {100*off_c1/n_total:.1f}%")
    print(f"  flag on:  {on_c1}/{n_total} = {100*on_c1/n_total:.1f}%")
    for t in (0, 1, 2):
        tier_results = by_tier.get(t, [])
        if not tier_results:
            continue
        c1_in_tier = sum(1 for r in tier_results if _BELIEF_SYNTAX_DETECTOR.search(r["on_resp"] or ""))
        print(f"    Tier {t}: {c1_in_tier}/{len(tier_results)} = {100*c1_in_tier/len(tier_results):.1f}% C1")

    # Predicted vs actual
    n_t2 = len(by_tier.get(2, []))
    n_t1 = len(by_tier.get(1, []))
    n_t0 = len(by_tier.get(0, []))
    # Predicted = off C1 rate × fraction still going to LLM
    # Tier 0 contributes 0%; Tiers 1+2 inherit the baseline C1 rate
    baseline_c1_rate = off_c1 / n_total if n_total else 0
    predicted_on_c1 = baseline_c1_rate * (n_t1 + n_t2) / n_total if n_total else 0
    actual_on_c1 = on_c1 / n_total if n_total else 0
    print()
    print("=== predicted vs actual C1 (flag on) ===")
    print(f"  predicted (baseline * fraction_llm): {100*predicted_on_c1:.1f}%")
    print(f"  actual:                              {100*actual_on_c1:.1f}%")
    print(f"  delta:                               {100*(actual_on_c1 - predicted_on_c1):+.1f}pp")

    # Verbose decision sample
    print()
    print("=== verbose decision sample (first 20) ===")
    for r in results[:20]:
        tr = tier_map.get(r["query"])
        tier = tr[0] if tr else "?"
        reason = tr[1] if tr else "?"
        print(f"  [{r['idx']:>2}] T{tier}  {reason!r:42s}  on={r['on_ms']:>5}ms  q={r['query'][:48]!r}")

    return results


if __name__ == "__main__":
    main()
