#!/usr/bin/env python3
"""
nex_nightly_trainer.py — Nightly 2am QLoRA fine-tuning pipeline
Runs automatically when called during the 2am window from run.py.

Training weights:
  light  — 1 epoch,  lr 2e-4  (< 500 new examples since last run)
  medium — 2 epochs, lr 2e-4  (500–1500 new examples)
  heavy  — 3 epochs, lr 1e-4  (1500–3000 new examples)
  super  — 4 epochs, lr 8e-5  (3000+ new examples)

Protocol (from TRAINING_PROTOCOL.md):
  - Kill llama-server before training
  - HSA_OVERRIDE_GFX_VERSION=10.3.0 HIP_VISIBLE_DEVICES=0
  - dtype=torch.float16, device_map={"": 0}
  - No BitsAndBytes
  - fp16 ≈ 6.4GB VRAM
"""

import os
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

CFG_PATH        = Path("~/.config/nex").expanduser()
TRAINER_STATE   = CFG_PATH / "trainer_state.json"
TRAINING_JSONL  = CFG_PATH / "nex_training.jsonl"
BASE_MODEL      = "/media/rr/4TBDATA/llmz/nex_base_model/"
OUTPUT_DIR      = "/media/rr/4TBDATA/llmz/nex_trained/"
TRAINING_SCRIPT = "/media/rr/NEX/nex/training/train_qlora.py"
LLAMA_SERVER    = "/media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build-rocm/bin/llama-server"


def _load_state() -> dict:
    try:
        if TRAINER_STATE.exists():
            return json.loads(TRAINER_STATE.read_text())
    except Exception:
        pass
    return {"last_trained_belief_count": 0, "last_trained_ts": 0, "total_runs": 0, "last_intensity": None}


def _save_state(state: dict):
    CFG_PATH.mkdir(parents=True, exist_ok=True)
    TRAINER_STATE.write_text(json.dumps(state, indent=2))


def _count_training_examples() -> int:
    try:
        if TRAINING_JSONL.exists():
            return sum(1 for _ in TRAINING_JSONL.open())
    except Exception:
        pass
    return 0


def _get_intensity(new_examples: int) -> tuple[str, int, float]:
    """Returns (intensity_label, epochs, learning_rate)"""
    if new_examples < 500:
        return "light", 1, 2e-4
    elif new_examples < 1500:
        return "medium", 2, 2e-4
    elif new_examples < 3000:
        return "heavy", 3, 1e-4
    else:
        return "super", 4, 8e-5


def _kill_llama_server():
    """Kill llama-server before training to free VRAM."""
    try:
        subprocess.run(["pkill", "-f", "llama-server"], timeout=10)
        time.sleep(3)
        print("  [NIGHTLY] llama-server killed")
    except Exception as e:
        print(f"  [NIGHTLY] kill llama-server: {e}")


def _restart_llama_server():
    """Restart llama-server after training."""
    try:
        env = os.environ.copy()
        env["HSA_OVERRIDE_GFX_VERSION"] = "10.3.0"
        env["HIP_VISIBLE_DEVICES"] = "0"
        launch_script = Path("~/nex_launch.sh").expanduser()
        if launch_script.exists():
            subprocess.Popen(["bash", str(launch_script)],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            time.sleep(5)
            print("  [NIGHTLY] llama-server restarted")
        else:
            print("  [NIGHTLY] nex_launch.sh not found — restart manually")
    except Exception as e:
        print(f"  [NIGHTLY] restart llama-server: {e}")


def _send_telegram(msg: str, send_fn=None):
    """Send Telegram notification."""
    if send_fn:
        try:
            send_fn(msg)
        except Exception as e:
            print(f"  [NIGHTLY] Telegram send failed: {e}")
    print(f"  [NIGHTLY] {msg}")


def _run_training(intensity: str, epochs: int, lr: float, total_examples: int) -> bool:
    """
    Run QLoRA fine-tuning. Returns True if successful.
    Uses training script at TRAINING_SCRIPT if it exists,
    otherwise runs inline via transformers/trl.
    """
    env = os.environ.copy()
    env["HSA_OVERRIDE_GFX_VERSION"] = "10.3.0"
    env["HIP_VISIBLE_DEVICES"] = "0"

    script = Path(TRAINING_SCRIPT)
    if script.exists():
        cmd = [
            "python3", str(script),
            "--model_path", BASE_MODEL,
            "--output_dir", OUTPUT_DIR,
            "--data_path", str(TRAINING_JSONL),
            "--epochs", str(epochs),
            "--lr", str(lr),
            "--intensity", intensity,
        ]
        try:
            result = subprocess.run(cmd, env=env, timeout=7200,
                capture_output=True, text=True)
            if result.returncode == 0:
                return True
            else:
                print(f"  [NIGHTLY] Training failed: {result.stderr[-500:]}")
                return False
        except subprocess.TimeoutExpired:
            print("  [NIGHTLY] Training timed out after 2 hours")
            return False
        except Exception as e:
            print(f"  [NIGHTLY] Training error: {e}")
            return False
    else:
        # Inline training via trl SFTTrainer
        return _run_inline_training(epochs, lr, total_examples, env)


def _run_inline_training(epochs: int, lr: float, total_examples: int, env: dict) -> bool:
    """Fallback: run training inline if no external script exists."""
    script = f"""
import os, json, torch
from pathlib import Path
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments
from trl import SFTConfig, SFTTrainer

os.environ["HSA_OVERRIDE_GFX_VERSION"] = "10.3.0"
os.environ["HIP_VISIBLE_DEVICES"] = "0"

DATA_PATH  = "{str(TRAINING_JSONL)}"
MODEL_PATH = "{BASE_MODEL}"
OUT_DIR    = "{OUTPUT_DIR}"
EPOCHS     = {epochs}
LR         = {lr}

# Load data
rows = []
with open(DATA_PATH) as f:
    for line in f:
        try:
            rows.append(json.loads(line))
        except Exception:
            pass

print(f"  Loaded {{len(rows)}} training examples")

# Format as text
def to_text(row):
    msgs = row.get("messages", [])
    parts = []
    for m in msgs:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "system":
            parts.append(f"<|system|>{{content}}</s>")
        elif role == "user":
            parts.append(f"<|user|>{{content}}</s>")
        elif role == "assistant":
            parts.append(f"<|assistant|>{{content}}</s>")
    return {{"text": "".join(parts)}}

dataset = Dataset.from_list([to_text(r) for r in rows])

tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    torch_dtype=torch.float16,
    device_map={{"": 0}},
    trust_remote_code=True,
)

from peft import LoraConfig, get_peft_model
lora_cfg = LoraConfig(r=16, lora_alpha=32, target_modules=["q_proj","v_proj"],
    lora_dropout=0.05, bias="none", task_type="CAUSAL_LM")
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()

cfg = SFTConfig(
    output_dir=OUT_DIR,
    num_train_epochs=EPOCHS,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    learning_rate=LR,
    fp16=True,
    logging_steps=20,
    save_strategy="epoch",
    warmup_ratio=0.03,
    lr_scheduler_type="cosine",
    max_seq_length=512,
    dataset_text_field="text",
    packing=False,
)

trainer = SFTTrainer(model=model, train_dataset=dataset, args=cfg, tokenizer=tokenizer)
trainer.train()
trainer.save_model(OUT_DIR)
tokenizer.save_pretrained(OUT_DIR)
print("Training complete.")
"""
    tmp = Path("/tmp/nex_train_run.py")
    tmp.write_text(script)
    try:
        result = subprocess.run(["python3", str(tmp)], env=env,
            timeout=7200, capture_output=True, text=True)
        print(result.stdout[-1000:] if result.stdout else "")
        if result.returncode != 0:
            print(f"  [NIGHTLY] inline training failed: {result.stderr[-500:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("  [NIGHTLY] inline training timed out")
        return False
    except Exception as e:
        print(f"  [NIGHTLY] inline training error: {e}")
        return False


def maybe_run_nightly_training(send_telegram_fn=None) -> bool:
    """
    Entry point from run.py. Call when hour == 2.
    Guards against running more than once per night.
    Returns True if training ran.
    """
    state = _load_state()

    # Guard: only run once per night (cooldown 20 hours)
    last_ts = state.get("last_trained_ts", 0)
    if (time.time() - last_ts) < 20 * 3600:
        return False

    total_examples = _count_training_examples()
    last_count     = state.get("last_trained_belief_count", 0)
    new_examples   = max(0, total_examples - last_count)

    # Need at least 100 new examples to bother training
    if new_examples < 100:
        print(f"  [NIGHTLY] only {new_examples} new examples — skipping")
        return False

    intensity, epochs, lr = _get_intensity(new_examples)

    _send_telegram(
        f"🧠 *NEX Nightly Training Starting*\n"
        f"Intensity: *{intensity.upper()}*\n"
        f"New examples: {new_examples} ({total_examples} total)\n"
        f"Epochs: {epochs} | LR: {lr}\n"
        f"Started: {datetime.now(timezone.utc).strftime('%H:%M UTC')}",
        send_telegram_fn
    )

    # Kill llama-server to free VRAM
    _kill_llama_server()

    t_start = time.time()
    success = _run_training(intensity, epochs, lr, total_examples)
    elapsed = (time.time() - t_start) / 60

    if success:
        state["last_trained_ts"]          = int(time.time())
        state["last_trained_belief_count"] = total_examples
        state["total_runs"]               = state.get("total_runs", 0) + 1
        state["last_intensity"]           = intensity
        _save_state(state)

        _send_telegram(
            f"✅ *NEX Training Complete*\n"
            f"Intensity: *{intensity.upper()}*\n"
            f"Duration: {elapsed:.0f} min\n"
            f"Total runs: {state['total_runs']}\n"
            f"Restarting llama-server...",
            send_telegram_fn
        )
        _restart_llama_server()
    else:
        _send_telegram(
            f"❌ *NEX Training Failed*\n"
            f"Intensity was: {intensity}\n"
            f"Duration: {elapsed:.0f} min\n"
            f"Check logs. Restarting llama-server anyway.",
            send_telegram_fn
        )
        _restart_llama_server()

    return success


if __name__ == "__main__":
    print("Running nightly training check...")
    maybe_run_nightly_training()
