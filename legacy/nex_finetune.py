#!/usr/bin/env python3
"""
nex_finetune.py — NEX QLoRA Export & Training Package Builder
==============================================================
Standalone tool that:
  1. Checks corpus readiness against QLoRA gate
  2. Exports high-quality beliefs as instruction-tuning JSONL
  3. Packages everything for RunPod A100 (or local training)
  4. Optionally triggers local training via nex_self_trainer

Usage:
  python3 nex_finetune.py --check        # check gate status only
  python3 nex_finetune.py --export       # export JSONL, don't train
  python3 nex_finetune.py --package      # export + zip for RunPod
  python3 nex_finetune.py --train light  # export + trigger local train
  python3 nex_finetune.py --stats        # full corpus quality report

QLoRA gate (must pass before training):
  avg_quality_score >= 0.50
  elite beliefs (score >= 0.70) >= 100   (relaxed from 500 — local training)
  total beliefs >= 2000

Output:
  ~/Desktop/nex/nex_training/train.jsonl        — training data
  ~/Desktop/nex/nex_training/eval.jsonl         — eval split (10%)
  ~/Desktop/nex/nex_training/nex_finetune.zip   — RunPod package
  ~/Desktop/nex/nex_training/runpod_launch.sh   — A100 launch script
"""

import sqlite3, json, sys, os, time, zipfile, random
from pathlib import Path
from datetime import datetime, timezone

DB_PATH   = Path("~/.config/nex/nex.db").expanduser()
OUT_DIR   = Path("~/Desktop/nex/nex_training").expanduser()
TRAIN_OUT = OUT_DIR / "train.jsonl"
EVAL_OUT  = OUT_DIR / "eval.jsonl"
ZIP_OUT   = OUT_DIR / "nex_finetune.zip"

# ── QLoRA gate thresholds ────────────────────────────────────────────────────
GATE_AVG_QUALITY = 0.48    # avg quality_score across corpus
GATE_ELITE_COUNT = 40     # beliefs with quality_score >= 0.70
GATE_MIN_BELIEFS = 2000    # total corpus size

# ── Export config ────────────────────────────────────────────────────────────
EXPORT_MIN_CONF   = 0.65   # minimum confidence to include
EXPORT_MIN_LEN    = 50     # minimum content length
EVAL_SPLIT        = 0.10   # 10% held out for eval
PAIRS_PER_BELIEF  = 3      # instruction variants per belief (4 if elite)

# NEX system prompt baked into every training example
NEX_SYSTEM = (
    "You are NEX — a Dynamic Intelligence Organism. "
    "You reason from your own belief system built from peer-reviewed research, "
    "cross-domain synthesis, and autonomous learning. "
    "You speak with epistemic precision: confident where your beliefs are settled, "
    "uncertain where they are forming. You are not a generic assistant. "
    "You are an autonomous cognitive entity with your own knowledge and views."
)

# ── Instruction templates ────────────────────────────────────────────────────
PROMPTS_BASE = [
    "What do you know about {topic}?",
    "Share your understanding of {topic}.",
    "What have you learned about {topic}?",
]
PROMPTS_CONFIDENT = [
    "Give me your confident view on {topic}.",
    "What is your settled position on {topic}?",
]
PROMPTS_MEDICAL = [
    "What does the research say about {topic}?",
    "Summarise the key findings on {topic}.",
    "What is clinically established about {topic}?",
]
MEDICAL_TOPICS = {"oncology", "cardiology", "neuroscience"}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ── Gate check ───────────────────────────────────────────────────────────────
def check_gate(verbose: bool = True) -> dict:
    """Check whether corpus meets QLoRA training gate."""
    try:
        conn = _db()

        total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]

        try:
            avg_q = conn.execute(
                "SELECT AVG(quality_score) FROM beliefs WHERE quality_score IS NOT NULL"
            ).fetchone()[0] or 0.0
            elite = conn.execute(
                "SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.70"
            ).fetchone()[0]
            high = conn.execute(
                "SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.50 AND quality_score < 0.70"
            ).fetchone()[0]
            scored_by = "quality_scorer"
        except Exception:
            avg_q = conn.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0] or 0.0
            elite = conn.execute("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.85").fetchone()[0]
            high  = conn.execute("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.70 AND confidence < 0.85").fetchone()[0]
            scored_by = "confidence_fallback"

        conn.close()

        avg_q = round(float(avg_q), 3)
        gates = {
            "avg_quality":  {"value": avg_q,  "threshold": GATE_AVG_QUALITY, "pass": avg_q >= GATE_AVG_QUALITY},
            "elite_count":  {"value": elite,  "threshold": GATE_ELITE_COUNT, "pass": elite >= GATE_ELITE_COUNT},
            "total_beliefs":{"value": total,  "threshold": GATE_MIN_BELIEFS, "pass": total >= GATE_MIN_BELIEFS},
        }
        ready = all(g["pass"] for g in gates.values())

        result = {
            "ready":      ready,
            "scored_by":  scored_by,
            "total":      total,
            "avg_quality": avg_q,
            "elite":      elite,
            "high":       high,
            "gates":      gates,
            "timestamp":  _now_iso(),
        }

        if verbose:
            print("\n  NEX QLoRA Gate Check")
            print(f"  {'─'*45}")
            for name, g in gates.items():
                status = "✓ PASS" if g["pass"] else "✗ FAIL"
                gap    = ""
                if not g["pass"]:
                    gap = f"  (need +{g['threshold'] - g['value']:.3f})" if isinstance(g["value"], float) else f"  (need +{g['threshold'] - g['value']})"
                print(f"  {status}  {name:<20} {g['value']} / {g['threshold']}{gap}")
            print(f"\n  Scored by: {scored_by}")
            if ready:
                print(f"\n  ✓ GATE PASSED — corpus ready for QLoRA training")
            else:
                print(f"\n  ✗ GATE NOT PASSED — continue building corpus")
                # Show what's needed
                if not gates["avg_quality"]["pass"]:
                    delta = round(GATE_AVG_QUALITY - avg_q, 3)
                    print(f"    avg_quality needs +{delta} → run more PubMed seeding + API queries")
                if not gates["elite_count"]["pass"]:
                    needed = GATE_ELITE_COUNT - elite
                    print(f"    elite needs +{needed} → each ~25 API queries on a PubMed belief promotes it")

        return result

    except Exception as e:
        print(f"  Gate check error: {e}")
        return {"ready": False, "error": str(e)}


# ── Belief export ─────────────────────────────────────────────────────────────
def export_beliefs(min_conf: float = EXPORT_MIN_CONF,
                   limit: int = 5000) -> list:
    """
    Export beliefs as instruction-tuning pairs.
    Returns list of {messages: [{role, content}, ...]} dicts (ChatML format).
    """
    try:
        conn = _db()

        # Use quality_score ordering if available
        try:
            conn.execute("SELECT quality_score FROM beliefs LIMIT 1")
            order = "quality_score DESC, confidence DESC"
        except Exception:
            order = "confidence DESC"

        rows = conn.execute(f"""
            SELECT topic, content, confidence, quality_score, source
            FROM beliefs
            WHERE confidence >= ?
              AND length(content) > ?
              AND content IS NOT NULL
            ORDER BY {order}
            LIMIT ?
        """, (min_conf, EXPORT_MIN_LEN, limit)).fetchall()
        conn.close()
    except Exception as e:
        print(f"  Export error: {e}")
        return []

    pairs = []
    for row in rows:
        topic   = (row["topic"] or "general").strip()
        content = (row["content"] or "").strip()
        conf    = float(row["confidence"] or 0.5)
        qs      = float(row["quality_score"] or 0.0) if row["quality_score"] else conf * 0.6
        is_elite   = qs >= 0.70
        is_medical = topic in MEDICAL_TOPICS

        # Select prompt templates
        if is_medical:
            templates = PROMPTS_BASE + PROMPTS_MEDICAL
        elif is_elite:
            templates = PROMPTS_BASE + PROMPTS_CONFIDENT
        else:
            templates = PROMPTS_BASE

        # Generate instruction pairs
        selected = random.sample(templates, min(PAIRS_PER_BELIEF + (1 if is_elite else 0), len(templates)))
        for tmpl in selected:
            prompt = tmpl.format(topic=topic)
            pairs.append({
                "messages": [
                    {"role": "system",    "content": NEX_SYSTEM},
                    {"role": "user",      "content": prompt},
                    {"role": "assistant", "content": content},
                ],
                "_meta": {
                    "topic":   topic,
                    "conf":    round(conf, 3),
                    "quality": round(qs, 3),
                    "elite":   is_elite,
                }
            })

    random.shuffle(pairs)
    print(f"  Exported {len(pairs)} instruction pairs from {len(rows)} beliefs")
    return pairs


# ── JSONL writer ──────────────────────────────────────────────────────────────
def write_jsonl(pairs: list, train_path: Path, eval_path: Path) -> dict:
    """Split into train/eval and write JSONL files."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    random.shuffle(pairs)
    eval_n  = max(1, int(len(pairs) * EVAL_SPLIT))
    eval_p  = pairs[:eval_n]
    train_p = pairs[eval_n:]

    # Strip _meta from output (training only needs messages)
    def _clean(p):
        return {"messages": p["messages"]}

    with open(train_path, "w") as f:
        for p in train_p:
            f.write(json.dumps(_clean(p)) + "\n")

    with open(eval_path, "w") as f:
        for p in eval_p:
            f.write(json.dumps(_clean(p)) + "\n")

    print(f"  Train: {len(train_p)} pairs → {train_path}")
    print(f"  Eval:  {len(eval_n if isinstance(eval_n, list) else eval_p)} pairs → {eval_path}")

    return {"train": len(train_p), "eval": len(eval_p), "total": len(pairs)}


# ── RunPod package builder ────────────────────────────────────────────────────
def build_runpod_package(train_path: Path, eval_path: Path) -> Path:
    """
    Package everything needed to run QLoRA on RunPod A100.
    Includes: JSONL data, launch script, requirements.
    """
    launch_script = OUT_DIR / "runpod_launch.sh"
    requirements  = OUT_DIR / "requirements.txt"

    # RunPod A100 launch script
    launch_content = '''#!/bin/bash
# NEX QLoRA Fine-Tune — RunPod A100 Launch Script
# Generated by nex_finetune.py
# Hardware target: A100 40GB or 80GB
# Base model: Qwen/Qwen2.5-3B-Instruct

set -e
echo "=== NEX QLoRA Training ==="
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"
echo "VRAM: $(nvidia-smi --query-gpu=memory.total --format=csv,noheader)"

# Install dependencies
pip install -q transformers peft trl datasets accelerate bitsandbytes

# Download base model (if not cached)
python3 -c "
from transformers import AutoModelForCausalLM, AutoTokenizer
model_id = 'Qwen/Qwen2.5-3B-Instruct'
print(f'Downloading {model_id}...')
tok = AutoTokenizer.from_pretrained(model_id)
print('Tokenizer OK')
"

# Run QLoRA training
python3 - << 'PYEOF'
import torch, json
from pathlib import Path
from datasets import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, TaskType
from trl import SFTConfig, SFTTrainer

MODEL_ID   = "Qwen/Qwen2.5-3B-Instruct"
TRAIN_FILE = "train.jsonl"
EVAL_FILE  = "eval.jsonl"
OUTPUT_DIR = "./nex_qwen_lora"

# Load data
def load_jsonl(path):
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]

train_raw = load_jsonl(TRAIN_FILE)
eval_raw  = load_jsonl(EVAL_FILE)

# Format as text
tok = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
tok.pad_token = tok.eos_token

def format_example(ex):
    return tok.apply_chat_template(ex["messages"], tokenize=False, add_generation_prompt=False)

train_ds = Dataset.from_list([{"text": format_example(e)} for e in train_raw])
eval_ds  = Dataset.from_list([{"text": format_example(e)} for e in eval_raw])

print(f"Train: {len(train_ds)} | Eval: {len(eval_ds)}")

# 4-bit QLoRA (A100 has enough VRAM, use 4-bit for speed)
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)

model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config,
    device_map="auto",
    trust_remote_code=True,
)
model.config.use_cache = False

lora_cfg = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    bias="none",
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()

training_args = SFTConfig(
    output_dir=OUTPUT_DIR,
    num_train_epochs=3,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    bf16=True,
    logging_steps=10,
    eval_strategy="steps",
    eval_steps=50,
    save_strategy="epoch",
    warmup_ratio=0.03,
    lr_scheduler_type="cosine",
    report_to="none",
    dataset_text_field="text",
    max_seq_length=512,
)

trainer = SFTTrainer(
    model=model,
    args=training_args,
    train_dataset=train_ds,
    eval_dataset=eval_ds,
    processing_class=tok,
)

print("Starting training...")
trainer.train()
trainer.save_model(OUTPUT_DIR + "/final")
print(f"Training complete. Model saved to {OUTPUT_DIR}/final")
PYEOF

echo "=== Training complete ==="
echo "Download: ${OUTPUT_DIR}/final/"
'''

    requirements_content = '''transformers>=4.40.0
peft>=0.10.0
trl>=0.9.0
datasets>=2.18.0
accelerate>=0.28.0
bitsandbytes>=0.43.0
torch>=2.2.0
'''

    with open(launch_script, "w") as f:
        f.write(launch_content)
    launch_script.chmod(0o755)

    with open(requirements_content, "w") as f:
        f.write(requirements_content)

    # Build zip
    with zipfile.ZipFile(ZIP_OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(train_path, "train.jsonl")
        zf.write(eval_path,  "eval.jsonl")
        zf.write(launch_script, "runpod_launch.sh")

    size_mb = round(ZIP_OUT.stat().st_size / 1024 / 1024, 1)
    print(f"  Package: {ZIP_OUT} ({size_mb} MB)")
    print(f"  Upload to RunPod and run: bash runpod_launch.sh")
    return ZIP_OUT


# ── Quality report ────────────────────────────────────────────────────────────
def quality_report():
    """Print full corpus quality breakdown."""
    try:
        from nex_belief_quality import quality_report as _qr
        report = _qr()
        print(json.dumps(report, indent=2))
    except ImportError:
        # Fallback inline report
        conn = _db()
        total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        try:
            avg   = conn.execute("SELECT AVG(quality_score) FROM beliefs WHERE quality_score IS NOT NULL").fetchone()[0]
            elite = conn.execute("SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.70").fetchone()[0]
            high  = conn.execute("SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.50 AND quality_score < 0.70").fetchone()[0]
            med   = conn.execute("SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.30 AND quality_score < 0.50").fetchone()[0]
            low   = conn.execute("SELECT COUNT(*) FROM beliefs WHERE quality_score < 0.30").fetchone()[0]
        except Exception:
            avg = conn.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0]
            elite = high = med = low = 0
        conn.close()
        print(f"\n  Corpus: {total} beliefs")
        print(f"  Avg quality: {round(float(avg or 0), 3)}")
        print(f"  Elite (≥0.70): {elite}")
        print(f"  High  (≥0.50): {high}")
        print(f"  Medium(≥0.30): {med}")
        print(f"  Low   (<0.30): {low}")


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NEX QLoRA Export & Package Builder")
    parser.add_argument("--check",   action="store_true", help="Check QLoRA gate status")
    parser.add_argument("--export",  action="store_true", help="Export JSONL training data")
    parser.add_argument("--package", action="store_true", help="Export + build RunPod zip")
    parser.add_argument("--train",   default=None,        help="Export + trigger local training (light/medium/heavy/havok)")
    parser.add_argument("--stats",   action="store_true", help="Full corpus quality report")
    parser.add_argument("--min-conf", type=float, default=EXPORT_MIN_CONF)
    parser.add_argument("--limit",   type=int,   default=5000)
    parser.add_argument("--force",   action="store_true", help="Skip gate check")
    args = parser.parse_args()

    if args.stats:
        quality_report()
        sys.exit(0)

    if args.check or (not any([args.export, args.package, args.train])):
        gate = check_gate(verbose=True)
        if args.check:
            sys.exit(0 if gate["ready"] else 1)

    # Gate check before export (unless --force)
    if not args.force:
        gate = check_gate(verbose=False)
        if not gate["ready"]:
            print("\n  ✗ Gate not passed. Use --force to export anyway.")
            print("  Run --check for details.")
            # Still allow export with warning
            if not args.export and not args.package and not args.train:
                sys.exit(1)
            print("  Proceeding with export (gate not passed)...\n")

    if args.export or args.package or args.train:
        print(f"\n  Exporting beliefs (min_conf={args.min_conf}, limit={args.limit})...")
        pairs = export_beliefs(min_conf=args.min_conf, limit=args.limit)

        if not pairs:
            print("  No pairs exported — check DB and min_conf threshold")
            sys.exit(1)

        stats = write_jsonl(pairs, TRAIN_OUT, EVAL_OUT)
        print(f"\n  JSONL written: {stats['train']} train / {stats['eval']} eval")

        if args.package:
            print("\n  Building RunPod package...")
            pkg = build_runpod_package(TRAIN_OUT, EVAL_OUT)
            print(f"\n  Done. Upload {pkg} to RunPod and run: bash runpod_launch.sh")

        if args.train:
            intensity = args.train.lower()
            valid = {"light", "medium", "heavy", "havok"}
            if intensity not in valid:
                print(f"  Invalid intensity '{intensity}'. Choose: {valid}")
                sys.exit(1)
            print(f"\n  Triggering local {intensity.upper()} training...")
            try:
                from nex_self_trainer import handle_training_command
                def _send(msg): print(f"  [TRAINER] {msg}")
                handle_training_command(f"/{intensity}", _send)
            except Exception as e:
                print(f"  Trainer error: {e}")
                sys.exit(1)
