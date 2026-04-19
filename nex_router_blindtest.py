"""
nex_router_blindtest.py — Phase 2A R2 deliverable.

Generates 20 queries × {Tier 0, Tier 2} = 40 responses, shuffles the A/B
assignment per row, writes to a CSV for Jon to fill in.

The CSV has one row per query:
  query, resp_A, resp_B, jon_guess, ground_truth

Ground truth is "A" or "B" depending on which column was Tier 2. Jon
fills "A", "B", or "?" in jon_guess. Scoring afterward is simple accuracy.

Uses the Phase 1D snapshot DB for deterministic retrieval. Runs at
temperature=0.
"""

from __future__ import annotations
import csv
import datetime as _dt
import hashlib
import os
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(os.path.expanduser("~/Desktop/nex"))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "nex"))

QUERIES = [
    # 8 self-inquiry
    "What do you think about your own cognition?",
    "Describe your view on how you hold beliefs.",
    "What do you think about consciousness?",
    "How do you see your own uncertainty?",
    "Describe your position on self-knowledge.",
    "What do you think about the way you update?",
    "Tell me about how you reason.",
    "What do you hold about being a belief system?",
    # 6 factual
    "What is truth?",
    "Tell me about belief confidence.",
    "What is a contradiction?",
    "Tell me about evidence.",
    "What is uncertainty?",
    "Tell me about the nature of knowledge.",
    # 4 general/open
    "What matters about truth in practice?",
    "How does evidence relate to confidence?",
    "What connects consciousness and identity?",
    "What matters about honesty?",
    # 2 synthesis-required
    "Why does contradiction matter for belief revision?",
    "What follows from uncertainty about your own mind?",
]


def generate_tier(query: str, tier: int) -> str:
    """Force a specific tier by temporarily monkey-patching the router's decide()."""
    # Use the snapshot DB
    os.environ["NEX_BELIEFS_DB"] = str(PROJECT_ROOT / "nex_snapshot.db")
    os.environ["NEX_ROUTER"] = "1"
    os.environ["NEX_ROUTER_SOURCE"] = "phase2a_blindtest"
    os.environ["NEX_TEMP_OVERRIDE"] = "0"
    os.environ["NEX_BYPASS_PATH1"] = "0"

    import nex_response_router as nrr
    orig_decide = nrr.decide
    def forced_decide(features, source):
        if tier == 0:
            return 0, f"forced_tier0 (blindtest)"
        if tier == 2:
            return 2, f"forced_tier2 (blindtest)"
        return orig_decide(features, source)
    nrr.decide = forced_decide
    try:
        # Fresh import of generate_reply to pick up whatever state
        import importlib
        import nex.nex_respond_v2 as R
        # Re-resolve DB_PATH to pick up env var if first import didn't
        return R.generate_reply(query)
    finally:
        nrr.decide = orig_decide


def run(out_csv: Path) -> dict:
    rng = random.Random(42)  # deterministic shuffling
    rows = []
    for q in QUERIES:
        t0_response = generate_tier(q, tier=0)
        t2_response = generate_tier(q, tier=2)
        flip = rng.random() < 0.5
        if flip:
            resp_A, resp_B = t2_response, t0_response
            ground_truth = "A"  # A is Tier 2
        else:
            resp_A, resp_B = t0_response, t2_response
            ground_truth = "B"  # B is Tier 2
        rows.append({
            "query": q,
            "resp_A": resp_A,
            "resp_B": resp_B,
            "jon_guess": "",
            "ground_truth_tier2_in": ground_truth,
        })

    header_lines = [
        "# NEX Response Router — Phase 2A blind test",
        "#",
        "# Instructions for Jon:",
        "#   1. For each row, read resp_A and resp_B (one is Tier 0 Python composer,",
        "#      one is Tier 2 full LLM, in randomized order).",
        "#   2. Fill 'jon_guess' with your best guess of which is Tier 2 (the LLM call):",
        "#      'A' if resp_A seems LLM-produced, 'B' if resp_B does,",
        "#      '?' if you genuinely can't tell.",
        "#   3. Do NOT read the 'ground_truth_tier2_in' column until you're done — it is",
        "#      the ground-truth answer. After filling all 20 rows, score yourself by",
        "#      counting jon_guess == ground_truth_tier2_in.",
        "#",
        "# Interpretation:",
        "#   95-100% accuracy: Tier 0 composer is too distinguishable — composer needs work",
        "#   60-80% accuracy: Tier 0 works but has tells — might be fine for non-critical paths",
        "#   50-60% accuracy (near chance): Tier 0 is indistinguishable — router can promote",
        "#   <50%: something is very wrong",
        "#",
        f"# Generated: {_dt.datetime.now().isoformat()}",
        f"# Queries: {len(QUERIES)}  (N=20, per brief §Task 5)",
        "#",
    ]

    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        for line in header_lines:
            f.write(line + "\n")
        writer = csv.DictWriter(f, fieldnames=["query", "resp_A", "resp_B",
                                               "jon_guess", "ground_truth_tier2_in"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    return {
        "path": str(out_csv),
        "n_queries": len(QUERIES),
        "bytes": out_csv.stat().st_size,
    }


if __name__ == "__main__":
    today = _dt.datetime.now().strftime("%Y%m%d")
    out = PROJECT_ROOT / f"nex_router_blindtest_{today}.csv"
    result = run(out)
    print("blind test CSV generated:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print()
    print("Awaiting Jon's responses. Fill in the 'jon_guess' column, then")
    print("score by counting jon_guess == ground_truth_tier2_in.")
