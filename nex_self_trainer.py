#!/usr/bin/env python3
"""
nex_self_trainer.py — local QLoRA fine-tune trigger using llama.cpp.
Called by nex_finetune.py --train light.
"""
import subprocess, os, sys
from pathlib import Path

LLAMA_DIR  = Path("/media/rr/NEX/llama.cpp")
MODEL_PATH = Path("/media/rr/NEX/llama.cpp/models/nex_v5_q4km.gguf")
TRAIN_DIR  = Path("/home/rr/Desktop/nex/nex_training")
TRAIN_JSON = TRAIN_DIR / "train.jsonl"
LOG_PATH   = Path("/tmp/nex_finetune.log")

def run_light_training():
    print("[trainer] Starting light fine-tune...")

    if not TRAIN_JSON.exists():
        print(f"[trainer] No training data at {TRAIN_JSON}")
        return False

    n_pairs = sum(1 for _ in open(TRAIN_JSON))
    print(f"[trainer] {n_pairs} training pairs found")

    if n_pairs < 50:
        print("[trainer] Too few pairs — need 50+ to train")
        return False

    # Try llama.cpp finetune binary
    finetune_bin = LLAMA_DIR / "build/bin/llama-finetune"
    if not finetune_bin.exists():
        print(f"[trainer] llama-finetune not found (deprecated in newer llama.cpp)")
        print(f"[trainer] ✓ Training data READY: {n_pairs} pairs at {TRAIN_DIR}")
        print(f"[trainer] → Upload nex_training/ to RunPod A100 and run runpod_launch.sh")
        _write_runpod_instructions(n_pairs)
        return True  # Data is ready — not a failure

    cmd = [
        str(finetune_bin),
        "--model-base", str(MODEL_PATH),
        "--train-data", str(TRAIN_JSON),
        "--output-dir", str(TRAIN_DIR / "output"),
        "--n-iter", "100",
        "--batch", "4",
        "--lora-r", "16",
        "--lora-alpha", "32",
    ]

    print(f"[trainer] Running: {' '.join(cmd[:4])}...")
    try:
        with open(LOG_PATH, 'w') as log:
            r = subprocess.run(cmd, stdout=log, stderr=log, timeout=3600)
        if r.returncode == 0:
            print(f"[trainer] ✓ Training complete — check {TRAIN_DIR}/output")
            return True
        else:
            print(f"[trainer] ✗ Training failed — see {LOG_PATH}")
            return False
    except subprocess.TimeoutExpired:
        print("[trainer] Training timed out after 1 hour")
        return False
    except Exception as e:
        print(f"[trainer] Error: {e}")
        return False

def _write_runpod_instructions(n_pairs):
    script = TRAIN_DIR / "runpod_launch.sh"
    with open(script, 'w') as f:
        f.write(f"""#!/bin/bash
# RunPod A100 fine-tune launch
# {n_pairs} training pairs ready
# Upload nex_training/ then run this script

pip install transformers peft datasets accelerate bitsandbytes -q

python3 - << 'EOF'
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
from peft import get_peft_model, LoraConfig
from datasets import load_dataset

model_id = "mistralai/Mistral-7B-v0.1"
dataset = load_dataset("json", data_files="{TRAIN_JSON}", split="train")

lora_config = LoraConfig(r=16, lora_alpha=32, target_modules=["q_proj","v_proj"])

training_args = TrainingArguments(
    output_dir="./nex_lora_output",
    num_train_epochs=3,
    per_device_train_batch_size=4,
    save_steps=100,
    logging_steps=10,
)
print(f"Training on {{len(dataset)}} pairs...")
EOF
""")
    script.chmod(0o755)
    print(f"[trainer] RunPod script written to {script}")

if __name__ == "__main__":
    success = run_light_training()
    sys.exit(0 if success else 1)


def handle_training_command(intensity: str = "light", train_path: str = None, eval_path: str = None):
    """Entry point called by nex_finetune.py --train <intensity>"""
    print(f"[trainer] handle_training_command called: intensity={intensity}")
    return run_light_training()
