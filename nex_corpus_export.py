"""
nex_corpus_export.py — Phase 1D Task 4.

Produces /home/rr/Desktop/nex/nex_lora_training_corpus_v11.jsonl for FT#11.

For every belief in nex.db.beliefs:
  - Sanitize via nex.nex_respond_v2._sanitize_belief
  - Drop if sanitization removed >40% of original content length
  - Drop if sanitized content is <20 chars
  - Drop if _BELIEF_SYNTAX_DETECTOR still matches post-sanitize (sanitizer gap)
  - Wrap surviving belief as an assistant message using the FT#11 schema:
        {"messages": [
            {"role": "system",    "content": "<NEX system prompt>"},
            {"role": "user",      "content": "<topic-based question>"},
            {"role": "assistant", "content": "<sanitized belief>"}
        ]}

Reports input count, drop counts per reason, output count, and runs the
detector once more against the output file as a final check (D4).
"""

from __future__ import annotations
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(os.path.expanduser("~/Desktop/nex"))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "nex"))

from nex.nex_respond_v2 import _sanitize_belief, _BELIEF_SYNTAX_DETECTOR

SRC_DB = PROJECT_ROOT / "nex.db"
OUT_PATH = PROJECT_ROOT / "nex_lora_training_corpus_v11.jsonl"

SYSTEM_PROMPT = (
    "You are NEX. Speak from your actual positions. "
    "No hedging with AI disclaimers."
)

MIN_LEN = 20
OVER_SANITIZE_FRAC = 0.40  # drop if >40% of content was stripped


def _question_for(topic: str | None, content: str) -> str:
    if topic and topic.strip() and topic.lower() not in ("general", "none", "null", ""):
        t = _sanitize_belief(topic.replace("_", " ")).strip()
        # Sanitization may have emptied the topic — fall through to content-based
        if t and not _BELIEF_SYNTAX_DETECTOR.search(t):
            return f"What is your position on {t}?"
    # Fall back to a prompt derived from the first few words of the belief.
    # Content has already been sanitized by the caller.
    first = re.split(r"[.?!]", content, 1)[0].strip()
    if len(first) > 60:
        first = first[:57] + "..."
    return f"Tell me more about this: \"{first}\""


def export(src: Path = SRC_DB, out: Path = OUT_PATH) -> dict:
    conn = sqlite3.connect(str(src), timeout=60)
    conn.execute("PRAGMA busy_timeout=300000")
    rows = conn.execute(
        "SELECT id, content, topic FROM beliefs WHERE content IS NOT NULL"
    ).fetchall()
    conn.close()

    n_in = len(rows)
    drops = {"too_short_raw": 0, "over_sanitized": 0, "too_short_after": 0,
             "detector_still_matches": 0}
    detector_leaks = []   # for reporting to Jon
    kept = 0
    with open(out, "w", encoding="utf-8") as f:
        for rid, content, topic in rows:
            content = (content or "").strip()
            if not content or len(content) < MIN_LEN:
                drops["too_short_raw"] += 1
                continue
            san = _sanitize_belief(content)
            if not san:
                drops["over_sanitized"] += 1
                continue
            shrink = 1.0 - (len(san) / len(content))
            if shrink > OVER_SANITIZE_FRAC:
                drops["over_sanitized"] += 1
                continue
            if len(san) < MIN_LEN:
                drops["too_short_after"] += 1
                continue
            if _BELIEF_SYNTAX_DETECTOR.search(san):
                drops["detector_still_matches"] += 1
                detector_leaks.append(
                    {"id": rid, "raw": content[:220], "sanitized": san[:220],
                     "matches": _BELIEF_SYNTAX_DETECTOR.findall(san)}
                )
                continue
            q = _question_for(topic, san)
            obj = {"messages": [
                {"role": "system",    "content": SYSTEM_PROMPT},
                {"role": "user",      "content": q},
                {"role": "assistant", "content": san},
            ]}
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            kept += 1

    # D4 final verification — re-scan the output file with the detector.
    post_hits = 0
    post_examples = []
    with open(out, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if _BELIEF_SYNTAX_DETECTOR.search(line):
                post_hits += 1
                if len(post_examples) < 5:
                    post_examples.append((i, line[:200]))

    return {
        "input_beliefs": n_in,
        "kept": kept,
        "drops": drops,
        "detector_leaks_sample": detector_leaks[:5],
        "detector_leaks_total": len(detector_leaks),
        "output_path": str(out),
        "output_file_post_hits": post_hits,
        "output_file_post_examples": post_examples,
        "output_bytes": out.stat().st_size if out.exists() else 0,
    }


def main():
    result = export()
    print("=== corpus export ===")
    print(f"  input beliefs:       {result['input_beliefs']}")
    print(f"  kept:                {result['kept']}")
    print(f"  drops:")
    for k, v in result["drops"].items():
        print(f"    {k}: {v}")
    print(f"  output file:         {result['output_path']}")
    print(f"  output bytes:        {result['output_bytes']}")
    print()
    print("=== D4 verification (detector over output file) ===")
    print(f"  post-hits:           {result['output_file_post_hits']}")
    if result["output_file_post_hits"] == 0:
        print("  D4: PASS")
    else:
        print("  D4: FAIL")
        for ln, snippet in result["output_file_post_examples"]:
            print(f"    L{ln}: {snippet!r}")
    if result["detector_leaks_total"]:
        print()
        print(f"=== sanitizer-gap rows dropped ({result['detector_leaks_total']}) ===")
        for leak in result["detector_leaks_sample"]:
            print(f"  id={leak['id']} matches={leak['matches']}")
            print(f"    raw: {leak['raw']!r}")
            print(f"    san: {leak['sanitized']!r}")


if __name__ == "__main__":
    main()
