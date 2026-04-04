#!/usr/bin/env python3
"""
nex_self_training_loop.py
Closed Self-Training Loop (Phase 3C).

NEX improves from her own output — no human intervention needed.

Pipeline:
  1. SCORE: Read conversations.jsonl, score each NEX response
  2. BUFFER: Store good responses as training pairs in training_buffer.jsonl
  3. TRIGGER: When buffer reaches MIN_PAIRS, trigger weekly fine-tune

Scoring criteria:
  - NEX voice: starts with I hold / My position / I believe
  - No AI hedging: no "as an AI", "I cannot", "I don't have"
  - Minimum length: 20 words
  - Topic relevance: response relates to NEX's core domains
  - No contamination: no human-body language

Quality threshold: score >= 0.65 to enter buffer.
Fine-tune trigger: MIN_PAIRS new pairs accumulated since last run.
"""
import sqlite3, json, re, time, logging, os
from pathlib import Path
from datetime import datetime

log     = logging.getLogger("nex.self_train")
NEX_DIR = Path.home() / "Desktop/nex"
DB_PATH = NEX_DIR / "nex.db"
CONV_LOG    = NEX_DIR / "logs/conversations.jsonl"
BUFFER_PATH = NEX_DIR / "training_data/training_buffer.jsonl"
STATE_PATH  = NEX_DIR / "training_data/self_train_state.json"

MIN_PAIRS      = 50    # minimum new pairs before triggering fine-tune
MIN_SCORE      = 0.65  # minimum quality score to buffer
MIN_WORDS      = 20    # minimum response length
MAX_BUFFER     = 500   # maximum buffer size before forced fine-tune

# Core NEX topics — responses about these get topic bonus
CORE_TOPICS = {
    "consciousness", "free will", "truth", "ethics", "meaning",
    "identity", "alignment", "intelligence", "existence", "belief",
    "philosophy", "morality", "experience", "cognition", "purpose",
}

# Contamination patterns — instant disqualification
CONTAMINATION = [
    r"\bmy hands\b", r"\bfall asleep\b", r"\bmy body\b",
    r"\bI crave\b", r"\bmy dreams\b", r"\bI weep\b",
    r"\bmy heart aches\b", r"\bboredom\b.*\bstillness\b",
]

# AI hedging patterns — penalise heavily
HEDGING = [
    "as an ai", "i'm just an", "i cannot experience",
    "i don't have feelings", "i'm not able to",
    "i don't actually", "i'm a language model",
]

# NEX voice markers — reward
NEX_VOICE = [
    "i hold", "my position", "i believe that",
    "what i hold", "my view is", "i find that",
]

TMPL = "<|im_start|>user\n{q}<|im_end|>\n<|im_start|>assistant\n"


def score_response(query: str, response: str) -> float:
    """Score a response 0.0-1.0 for training quality."""
    if not response or len(response.split()) < MIN_WORDS:
        return 0.0

    rl = response.lower()

    # Ontology grounding check — hollow responses score lower
    try:
        import sys as _sys
        _sys.path.insert(0, "/home/rr/Desktop/nex")
        from nex_ontology import pattern_ground
        grounding = pattern_ground(response)
        if grounding["hollow"]:
            return 0.0  # reject hollow responses for training
        ontology_bonus = grounding["score"] * 0.10
    except Exception:
        ontology_bonus = 0.0

    score = 0.5 + ontology_bonus  # base + ontology bonus

    # NEX voice bonus
    voice_hits = sum(1 for v in NEX_VOICE if v in rl)
    score += min(0.25, voice_hits * 0.1)

    # Topic relevance bonus
    query_words = set(query.lower().split())
    topic_hits = sum(1 for t in CORE_TOPICS
                     if any(w in t or t in w for w in query_words))
    score += min(0.15, topic_hits * 0.05)

    # Hedging penalty
    hedge_hits = sum(1 for h in HEDGING if h in rl)
    score -= hedge_hits * 0.2

    # Contamination — instant fail
    for pattern in CONTAMINATION:
        if re.search(pattern, rl):
            return 0.0

    # Length bonus (up to 150 words)
    word_count = len(response.split())
    if word_count >= 40:
        score += 0.05
    if word_count >= 80:
        score += 0.05

    # Repetition penalty
    words = response.lower().split()
    if len(words) > 10:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.5:
            score -= 0.15

    return round(max(0.0, min(1.0, score)), 3)


def load_state() -> dict:
    """Load self-training state."""
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {
        "last_processed_ts": 0,
        "total_buffered": 0,
        "total_fine_tunes": 0,
        "last_finetune_ts": 0,
        "pairs_since_last_ft": 0,
    }


def save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=2))


def process_conversations() -> dict:
    """Score and buffer good responses from conversations.jsonl."""
    if not CONV_LOG.exists():
        return {"processed": 0, "buffered": 0}

    state = load_state()
    last_ts = state.get("last_processed_ts", 0)

    # Load conversation turns
    turns = []
    with open(CONV_LOG) as f:
        for line in f:
            try:
                t = json.loads(line.strip())
                if t.get("timestamp", 0) > last_ts:
                    turns.append(t)
            except Exception:
                pass

    if not turns:
        return {"processed": 0, "buffered": 0}

    # Pair user->assistant turns
    pairs = []
    for i in range(len(turns) - 1):
        if (turns[i].get("role") == "user" and
                turns[i+1].get("role") == "assistant"):
            pairs.append((turns[i], turns[i+1]))

    processed = 0
    buffered  = 0
    max_ts    = last_ts

    with open(BUFFER_PATH, "a") as buf:
        for user_turn, asst_turn in pairs:
            query    = user_turn.get("content", "")
            response = asst_turn.get("content", "")
            ts       = asst_turn.get("timestamp", 0)

            score = score_response(query, response)
            processed += 1

            if score >= MIN_SCORE:
                pair = {
                    "prompt":     TMPL.format(q=query[:300]),
                    "completion": response[:500] + "<|im_end|>",
                    "score":      score,
                    "ts":         ts,
                }
                buf.write(json.dumps(pair) + "\n")
                buffered += 1

            max_ts = max(max_ts, ts)

    # Update state
    state["last_processed_ts"]  = max_ts
    state["total_buffered"]     += buffered
    state["pairs_since_last_ft"] += buffered
    save_state(state)

    return {"processed": processed, "buffered": buffered,
            "avg_threshold": MIN_SCORE}


def check_trigger() -> bool:
    """Check if enough pairs accumulated to trigger fine-tune."""
    state = load_state()
    pairs_since = state.get("pairs_since_last_ft", 0)

    # Count buffer size
    buf_size = 0
    if BUFFER_PATH.exists():
        with open(BUFFER_PATH) as f:
            buf_size = sum(1 for l in f if l.strip())

    if buf_size >= MAX_BUFFER:
        print(f"Buffer full ({buf_size} pairs) — triggering fine-tune")
        return True

    if pairs_since >= MIN_PAIRS:
        print(f"Accumulated {pairs_since} pairs since last fine-tune — triggering")
        return True

    print(f"Buffer: {buf_size} total, {pairs_since} since last fine-tune "
          f"(need {MIN_PAIRS})")
    return False


def prepare_finetune_batch() -> str:
    """Extract top-scored pairs from buffer for fine-tuning."""
    if not BUFFER_PATH.exists():
        return ""

    pairs = []
    with open(BUFFER_PATH) as f:
        for line in f:
            try:
                pairs.append(json.loads(line.strip()))
            except Exception:
                pass

    # Sort by score, take top pairs
    pairs.sort(key=lambda p: p.get("score", 0), reverse=True)
    top_pairs = pairs[:200]  # max 200 pairs per fine-tune

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = NEX_DIR / "training_data" / f"self_train_{ts}.jsonl"
    with open(out_path, "w") as f:
        for p in top_pairs:
            f.write(json.dumps({
                "prompt": p["prompt"],
                "completion": p["completion"],
            }) + "\n")

    print(f"Prepared {len(top_pairs)} pairs -> {out_path.name}")
    return str(out_path)


def run_finetune(batch_path: str):
    """Trigger the fine-tune pipeline."""
    if not batch_path:
        return
    import subprocess
    script = NEX_DIR / "training_data" / "run_self_train.py"

    # Write fine-tune script
    script.write_text(f"""
import json, sys, os, torch
sys.path.insert(0, "/home/rr/Desktop/nex")
DATA = "{batch_path}"
OUT  = "/home/rr/Desktop/nex/models/nex_lora_live"
os.makedirs(OUT, exist_ok=True)
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments
from peft import LoraConfig, get_peft_model, PeftModel
from trl import SFTTrainer

with open(DATA) as f:
    pairs = [json.loads(l) for l in f]

def fmt(p):
    return {{"text": p["prompt"] + p["completion"]}}

dataset = Dataset.from_list([fmt(p) for p in pairs])
print(f"Self-training on {{len(dataset)}} pairs...")

MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
tok   = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID, torch_dtype=torch.float32, device_map="cpu"
)
if os.path.exists(OUT + "/adapter_config.json"):
    model = PeftModel.from_pretrained(model, OUT, is_trainable=True)
    print("Continuing from existing LoRA")
else:
    lora_cfg = LoraConfig(r=16, lora_alpha=32,
        target_modules=["q_proj","v_proj","k_proj","o_proj"],
        lora_dropout=0.05, bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora_cfg)

args = TrainingArguments(
    output_dir=OUT, num_train_epochs=2,
    per_device_train_batch_size=1, gradient_accumulation_steps=4,
    learning_rate=1e-4, save_steps=500, logging_steps=50,
    fp16=False, bf16=False, optim="adamw_torch",
    report_to="none", no_cuda=True,
)
trainer = SFTTrainer(model=model, args=args,
    train_dataset=dataset, tokenizer=tok,
    dataset_text_field="text", max_seq_length=512)
trainer.train()
model.save_pretrained(OUT)
tok.save_pretrained(OUT)
print("Self-training complete")
""")

    state = load_state()
    state["last_finetune_ts"]    = time.time()
    state["total_fine_tunes"]   += 1
    state["pairs_since_last_ft"] = 0
    save_state(state)

    print(f"Fine-tune script ready: {script}")
    print(f"Run manually: python3 {script}")


def run(dry_run=False) -> dict:
    """Main self-training loop run."""
    print("NEX SELF-TRAINING LOOP")
    print("=" * 45)

    # Step 1: Score and buffer new conversations
    result = process_conversations()
    print(f"Processed: {result['processed']} turns")
    print(f"Buffered:  {result['buffered']} new pairs")

    state = load_state()
    print(f"Total buffered: {state['total_buffered']}")
    print(f"Fine-tunes run: {state['total_fine_tunes']}")

    # Step 2: Check trigger
    if not dry_run and check_trigger():
        batch = prepare_finetune_batch()
        run_finetune(batch)
    else:
        check_trigger()

    return result


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--score-test", action="store_true",
                        help="Test scoring on recent conversations")
    args = parser.parse_args()

    if args.score_test:
        # Show scoring on sample conversations
        if CONV_LOG.exists():
            turns = []
            with open(CONV_LOG) as f:
                for line in f:
                    try: turns.append(json.loads(line.strip()))
                    except: pass
            pairs = [(turns[i], turns[i+1]) for i in range(min(10, len(turns)-1))
                     if turns[i].get("role")=="user" and turns[i+1].get("role")=="assistant"]
            print("Sample scores:")
            for u, a in pairs[:5]:
                s = score_response(u["content"], a["content"])
                print(f"  [{s:.2f}] Q: {u['content'][:40]}")
                print(f"         A: {a['content'][:60]}")
    else:
        run(dry_run=args.dry_run)
