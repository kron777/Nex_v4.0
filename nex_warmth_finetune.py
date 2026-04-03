"""
nex_warmth_finetune.py
Item 10 — Warmth-Weighted Fine-Tuning.

Current fine-tune treats all training pairs equally.
Pairs containing core-level warmed words should be weighted
MORE heavily — these are pairs where NEX was reasoning from
her strongest conceptual ground.

Her best thinking should train harder.
Her weakest thinking should train softer.

Process:
  1. Score every training pair by average warmth of key vocab
  2. Write a weighted JSONL where high-warmth pairs appear
     multiple times (up to 3x) and low-warmth pairs once
  3. Generate training manifest with warmth metadata
  4. Hook into existing fine-tune scheduler

Scoring formula:
  pair_score = (
    avg_warmth_of_key_words * 0.40 +
    max_warmth_of_key_words * 0.25 +
    belief_density_avg      * 0.20 +
    depth_ceiling           * 0.15
  )

  score >= 0.65 → weight 3 (appears 3x in training)
  score >= 0.45 → weight 2
  score <  0.45 → weight 1
"""
import sqlite3, json, re, time, logging, sys, shutil
from pathlib import Path
from collections import defaultdict

log     = logging.getLogger("nex.warmth_finetune")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
TD_DIR  = NEX_DIR / "training_data"
sys.path.insert(0, str(NEX_DIR))

STOPWORDS = {
    "the","and","for","that","this","with","from","have",
    "been","will","would","could","should","just","also",
    "very","more","most","some","any","all","its","what",
    "which","who","how","when","where","why","than","then",
}

SCORE_HIGH  = 0.65   # weight 3x
SCORE_MED   = 0.45   # weight 2x
# below SCORE_MED  → weight 1x


def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def _extract_key_words(text: str) -> list:
    """Extract meaningful words from text."""
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
    return [w for w in words if w not in STOPWORDS]


def _score_pair(assistant_text: str, user_text: str,
                db) -> dict:
    """
    Score a training pair by warmth of its vocabulary.
    Returns score dict with breakdown.
    """
    all_words = _extract_key_words(
        assistant_text + " " + user_text)

    if not all_words:
        return {"score": 0.1, "weight": 1,
                "word_count": 0, "avg_w": 0}

    warmth_vals  = []
    belief_dens  = []
    depth_vals   = []

    for word in set(all_words[:30]):  # cap for speed
        row = db.execute(
            "SELECT w, b, d FROM word_tags "
            "WHERE word=?", (word,)).fetchone()
        if row and row["w"] and row["w"] > 0:
            warmth_vals.append(row["w"])
            belief_dens.append(min(row["b"] or 0, 99))
            depth_vals.append(row["d"] or 1)

    if not warmth_vals:
        return {"score": 0.15, "weight": 1,
                "word_count": len(all_words), "avg_w": 0}

    avg_w   = sum(warmth_vals) / len(warmth_vals)
    max_w   = max(warmth_vals)
    avg_b   = sum(belief_dens) / len(belief_dens) / 99
    avg_d   = sum(depth_vals) / len(depth_vals) / 6

    score = (
        avg_w * 0.40 +
        max_w * 0.25 +
        avg_b * 0.20 +
        avg_d * 0.15
    )

    weight = (3 if score >= SCORE_HIGH
             else 2 if score >= SCORE_MED
             else 1)

    return {
        "score":      round(score, 3),
        "weight":     weight,
        "word_count": len(all_words),
        "avg_w":      round(avg_w, 3),
        "max_w":      round(max_w, 3),
        "avg_depth":  round(avg_d * 6, 1),
        "hot_words":  sum(1 for w in warmth_vals if w >= 0.6),
    }


def score_all_pairs(jsonl_path: Path,
                    db) -> list:
    """Score all pairs in a JSONL file."""
    scored = []
    try:
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    pair = json.loads(line)
                    convs = pair.get("conversations", [])
                    user_text      = " ".join(
                        c.get("content","") for c in convs
                        if c.get("role") == "user")
                    assistant_text = " ".join(
                        c.get("content","") for c in convs
                        if c.get("role") == "assistant")

                    if not assistant_text.strip():
                        continue

                    score_data = _score_pair(
                        assistant_text, user_text, db)
                    scored.append({
                        "pair":  pair,
                        "score": score_data,
                        "raw":   line,
                    })
                except Exception:
                    pass
    except Exception as e:
        log.debug(f"Failed reading {jsonl_path}: {e}")

    return scored


def build_weighted_batch(output_path: Path = None,
                         max_source_pairs: int = 500,
                         ) -> dict:
    """
    Build a warmth-weighted training batch.
    Scans all existing training JSONL files,
    scores each pair, writes weighted output.
    """
    if output_path is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        output_path = TD_DIR / f"weighted_batch_{ts}.jsonl"

    db = _get_db()

    # Collect all training pairs
    all_pairs = []
    source_files = list(TD_DIR.glob("*.jsonl"))

    print(f"Scanning {len(source_files)} training files...")

    for jsonl_path in source_files:
        # Skip previously weighted batches
        if "weighted" in jsonl_path.name:
            continue
        scored = score_all_pairs(jsonl_path, db)
        all_pairs.extend(scored)
        if len(all_pairs) >= max_source_pairs * 3:
            break

    print(f"  Total pairs found: {len(all_pairs)}")

    # Sort by score descending
    all_pairs.sort(
        key=lambda x: x["score"]["score"], reverse=True)

    # Take top pairs by score
    top_pairs = all_pairs[:max_source_pairs]

    # Score distribution
    weight3 = sum(1 for p in top_pairs
                  if p["score"]["weight"] == 3)
    weight2 = sum(1 for p in top_pairs
                  if p["score"]["weight"] == 2)
    weight1 = sum(1 for p in top_pairs
                  if p["score"]["weight"] == 1)

    # Write weighted output
    written = 0
    manifest = []

    with open(output_path, "w") as f:
        for item in top_pairs:
            pair   = item["pair"]
            score  = item["score"]
            weight = score["weight"]

            # Write pair weight times
            for _ in range(weight):
                f.write(json.dumps(pair) + "\n")
                written += 1

            manifest.append({
                "score":  score["score"],
                "weight": weight,
                "avg_w":  score["avg_w"],
                "hot_words": score["hot_words"],
            })

    # Write manifest
    manifest_path = output_path.with_suffix(".manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source_pairs": len(top_pairs),
            "weighted_pairs": written,
            "weight3": weight3,
            "weight2": weight2,
            "weight1": weight1,
            "avg_score": (sum(m["score"] for m in manifest) /
                         max(len(manifest), 1)),
            "output": str(output_path),
        }, f, indent=2)

    db.close()

    print(f"\n{'═'*50}")
    print(f"Warmth-weighted batch built:")
    print(f"  Source pairs     : {len(top_pairs)}")
    print(f"  Written pairs    : {written}")
    print(f"  Weight 3x (high) : {weight3}")
    print(f"  Weight 2x (med)  : {weight2}")
    print(f"  Weight 1x (low)  : {weight1}")
    print(f"  Output           : {output_path.name}")
    print(f"{'═'*50}")

    # Show top scored pairs
    print(f"\nTop 5 highest-weighted pairs:")
    for item in top_pairs[:5]:
        s = item["score"]
        convs = item["pair"].get("conversations",[])
        preview = next(
            (c.get("content","")[:60]
             for c in convs if c.get("role")=="assistant"),
            "?")
        print(f"  score={s['score']:.3f} w={s['weight']}x "
              f"hot={s['hot_words']} "
              f"| {preview}")

    return {
        "source_pairs":   len(top_pairs),
        "written_pairs":  written,
        "weight3":        weight3,
        "output":         str(output_path),
    }


def inject_into_scheduler() -> bool:
    """
    Tell the existing train scheduler to use the latest
    weighted batch in its next fine-tune run.
    """
    # Find the latest weighted batch
    weighted = sorted(
        TD_DIR.glob("weighted_batch_*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    if not weighted:
        return False

    latest = weighted[0]
    pointer_path = TD_DIR / "warmth_weighted_latest.txt"
    pointer_path.write_text(str(latest))

    log.info(f"Scheduler pointer updated: {latest.name}")
    return True


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--max-pairs", type=int, default=500)
    args = parser.parse_args()

    if args.build:
        result = build_weighted_batch(
            max_source_pairs=args.max_pairs)
        inject_into_scheduler()
        print(f"\nResult: {result}")
    else:
        # Show current weighted batch status
        weighted = sorted(
            TD_DIR.glob("weighted_batch_*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if weighted:
            print(f"Latest weighted batch: {weighted[0].name}")
            n = sum(1 for _ in open(weighted[0]))
            print(f"  Pairs: {n}")
        else:
            print("No weighted batches yet. Run --build")
