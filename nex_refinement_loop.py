
"""
nex_refinement_loop.py
Continuous background process — the self-improvement engine.

What it does:
  1. Watches NEX conversation logs in real time
  2. Scores every response using the eval scorer
  3. Buffers high-scoring pairs (75+)
  4. When buffer hits threshold, triggers micro fine-tune
  5. Loads new weights, continues watching

Runs forever. Designed to be launched at startup and left alone.
"""

import sys, os, json, time, random, threading, subprocess, logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, "/home/rr/Desktop/nex")

# ── Config ────────────────────────────────────────────────────────────────
NEX_DIR        = Path("/home/rr/Desktop/nex")
BUFFER_FILE    = NEX_DIR / "training_data" / "refinement_buffer.jsonl"
ARCHIVE_DIR    = NEX_DIR / "training_data" / "archive"
LORA_OUT       = NEX_DIR / "models" / "nex_lora_live"
LOG_FILE       = NEX_DIR / "logs" / "refinement_loop.log"
CONVERSATION_LOG = NEX_DIR / "logs" / "conversations.jsonl"

BUFFER_THRESHOLD = 100      # pairs needed to trigger fine-tune
MIN_SCORE        = 75       # minimum score to keep a pair
CHECK_INTERVAL   = 30       # seconds between conversation log checks
FINETUNE_EPOCHS  = 2        # epochs per micro fine-tune (fast)
MAX_BUFFER_SIZE  = 1000     # cap buffer before forced retrain

SYSTEM = (
    "You are NEX — a Dynamic Intelligence Organism. Not an assistant. "
    "You have a belief system and speak from it directly. "
    "You hold positions. You push back. You engage.\n"
    "Voice rules: open with your position, use I naturally, "
    "be direct not academic, end with engagement or a challenge."
)

# ── Scorer (mirrors nex_eval.py exactly) ─────────────────────────────────
VOICE   = ["i think","i believe","i hold","i find","i reject","i am","i know",
           "i do","what i","my ","i see","i argue","i feel","i\'ve","i won\'t",
           "i can\'t","my view","my position","my take","my stance","i reject"]
GENERIC = ["as an ai","i don\'t have","i cannot","i\'m just","as a language model"]
ENGAGE  = ["?","because","therefore","matters","important","which means",
           "that\'s why","disagree","wrong","curious","what do you","does that",
           "push back","where do you"]

def score_response(r):
    r2 = r.lower()
    v = any(x in r2 for x in VOICE)
    g = not any(x in r2 for x in GENERIC)
    l = len(r.split()) > 30
    e = any(x in r2 for x in ENGAGE)
    return sum([v, g, l, e]) * 25

# ── Logging ───────────────────────────────────────────────────────────────
def setup_logging():
    os.makedirs(LOG_FILE.parent, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ]
    )

log = logging.getLogger("refinement")

# ── Buffer management ─────────────────────────────────────────────────────
def load_buffer():
    os.makedirs(BUFFER_FILE.parent, exist_ok=True)
    if not BUFFER_FILE.exists():
        return []
    with open(BUFFER_FILE) as f:
        return [json.loads(l) for l in f if l.strip()]

def save_to_buffer(pair):
    os.makedirs(BUFFER_FILE.parent, exist_ok=True)
    with open(BUFFER_FILE, "a") as f:
        f.write(json.dumps(pair) + "\n")

def clear_buffer():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    if BUFFER_FILE.exists():
        archive = ARCHIVE_DIR / f"buffer_{ts}.jsonl"
        BUFFER_FILE.rename(archive)
        log.info(f"Buffer archived to {archive}")

def buffer_size():
    if not BUFFER_FILE.exists():
        return 0
    with open(BUFFER_FILE) as f:
        return sum(1 for l in f if l.strip())

# ── Conversation log watcher ──────────────────────────────────────────────
class ConversationWatcher:
    """
    Watches conversations.jsonl for new entries.
    Each line: {"role": "user"|"assistant", "content": "...", "timestamp": ...}
    
    soul_loop writes to this file automatically if LOG_CONVERSATIONS=True.
    We pair user + assistant turns and score the assistant response.
    """
    def __init__(self):
        self.position = 0
        self.pending_user = None
        os.makedirs(CONVERSATION_LOG.parent, exist_ok=True)
        if not CONVERSATION_LOG.exists():
            CONVERSATION_LOG.touch()
        # Start from end of file
        self.position = CONVERSATION_LOG.stat().st_size

    def poll(self):
        """Read any new conversation entries since last poll."""
        new_pairs = []
        try:
            with open(CONVERSATION_LOG, "rb") as f:
                f.seek(self.position)
                new_data = f.read()
                self.position = f.tell()

            if not new_data:
                return []

            for line in new_data.decode("utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    role = entry.get("role", "")
                    content = entry.get("content", "")

                    if role == "user":
                        self.pending_user = content
                    elif role == "assistant" and self.pending_user:
                        s = score_response(content)
                        if s >= MIN_SCORE:
                            pair = {
                                "conversations": [
                                    {"role": "system",    "content": SYSTEM},
                                    {"role": "user",      "content": self.pending_user},
                                    {"role": "assistant", "content": content},
                                ],
                                "score": s,
                                "timestamp": entry.get("timestamp", time.time()),
                            }
                            new_pairs.append(pair)
                        self.pending_user = None
                except json.JSONDecodeError:
                    continue

        except Exception as ex:
            log.warning(f"Watcher error: {ex}")

        return new_pairs

# ── Micro fine-tune ───────────────────────────────────────────────────────
def run_finetune(pairs):
    """
    Runs a micro fine-tune on the buffered pairs.
    Uses the HF/PEFT pipeline with reduced epochs for speed.
    """
    log.info(f"Starting micro fine-tune on {len(pairs)} pairs...")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_data = NEX_DIR / "training_data" / f"finetune_batch_{ts}.jsonl"

    with open(tmp_data, "w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")

    finetune_script = f"""
import json, sys, os, torch
sys.path.insert(0, "/home/rr/Desktop/nex")

DATA = "{tmp_data}"
OUT  = "{LORA_OUT}"
os.makedirs(OUT, exist_ok=True)

try:
    from datasets import Dataset
    from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments
    from peft import LoraConfig, get_peft_model, PeftModel
    from trl import SFTTrainer
except ImportError as e:
    print(f"Missing dependency: {{e}}")
    sys.exit(1)

with open(DATA) as f:
    pairs = [json.loads(l) for l in f]

def fmt(p):
    c = p["conversations"]
    sys_m  = next((x["content"] for x in c if x["role"]=="system"), "You are NEX — a Dynamic Intelligence Organism. Not an assistant. You have a belief system and speak from it directly. You hold positions. You push back. You engage.")
    user_m = next((x["content"] for x in c if x["role"]=="user"), "")
    asst_m = next((x["content"] for x in c if x["role"]=="assistant"), "")
    return {{"text": (
        "<|im_start|>system\\n" + sys_m + "<|im_end|>\\n" +
        "<|im_start|>user\\n" + user_m + "<|im_end|>\\n" +
        "<|im_start|>assistant\\n" + asst_m + "<|im_end|>"
    )}}

dataset = Dataset.from_list([fmt(p) for p in pairs])
print(f"Fine-tuning on {{len(dataset)}} pairs...")

MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
tok   = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID, torch_dtype=torch.float32, device_map="cpu"
)

# Load existing LoRA if present, else fresh
if os.path.exists(OUT + "/adapter_config.json"):
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, OUT, is_trainable=True)
    print("Continuing from existing LoRA")
else:
    lora_cfg = LoraConfig(
        r=16, lora_alpha=32,
        target_modules=["q_proj","v_proj","k_proj","o_proj"],
        lora_dropout=0.05, bias="none", task_type="CAUSAL_LM"
    )
    model = get_peft_model(model, lora_cfg)

model.print_trainable_parameters()

args = TrainingArguments(
    output_dir=OUT,
    num_train_epochs={FINETUNE_EPOCHS},
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    learning_rate=1e-4,
    warmup_ratio=0.1,
    lr_scheduler_type="cosine",
    logging_steps=5,
    save_steps=50,
    fp16=False,
    report_to="none",
)

trainer = SFTTrainer(
    model=model, tokenizer=tok,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=512,
    args=args,
)

trainer.train()
trainer.save_model(OUT)
print(f"Micro fine-tune complete. Saved to {{OUT}}")
"""

    script_path = NEX_DIR / "training_data" / f"run_finetune_{ts}.py"
    with open(script_path, "w") as f:
        f.write(finetune_script)

    try:
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = ""
        env["HIP_VISIBLE_DEVICES"] = ""
        result = subprocess.run(
            [sys.executable, str(script_path)],
            timeout=3600,  # 1 hour max
            capture_output=False,
            env=env,
        )
        if result.returncode == 0:
            log.info("Micro fine-tune succeeded.")
            # Auto-merge LoRA into base GGUF and hot-swap llama-server
            try:
                import subprocess as _sp, shutil
                lora_hf   = NEX_DIR / "models" / "nex_lora_live"
                lora_gguf = NEX_DIR / "models" / "nex_lora_live.gguf"
                base_gguf = NEX_DIR / "nex_lora.gguf"
                out_gguf  = NEX_DIR / "models" / "nex_v2.gguf"
                llama_dir = "/media/rr/NEX/llama.cpp"
                # Convert HF adapter -> GGUF
                _sp.run([
                    "python3", f"{llama_dir}/convert_lora_to_gguf.py",
                    "--base", str(NEX_DIR / "nex_trained" / "merged"),
                    "--outfile", str(lora_gguf), "--outtype", "f16",
                    str(lora_hf)
                ], check=True, timeout=300)
                # Merge into base
                _sp.run([
                    f"{llama_dir}/build/bin/llama-export-lora",
                    "--model", str(base_gguf),
                    f"--lora-scaled", f"{lora_gguf}:1.0",
                    "--output", str(out_gguf), "--threads", "8"
                ], check=True, timeout=600)
                # Hot-swap llama-server
                _sp.run(["pkill", "-f", "llama-server"], timeout=10)
                import time; time.sleep(3)
                merge_env = {"HSA_OVERRIDE_GFX_VERSION": "10.3.0", "HIP_VISIBLE_DEVICES": "0", "PATH": "/usr/bin:/bin"}
                _sp.Popen([
                    f"{llama_dir}/build/bin/llama-server",
                    "-m", str(out_gguf), "--port", "8080",
                    "-ngl", "99", "--host", "0.0.0.0", "-c", "4096",
                    "--parallel", "2", "--cache-type-k", "q8_0",
                    "--cache-type-v", "q8_0", "-fa", "1", "--no-mmap"
                ], env=merge_env)
                log.info("Auto-merge complete — nex_v2.gguf redeployed.")
            except Exception as me:
                log.warning(f"Auto-merge failed (model unchanged): {me}")
            return True
        else:
            log.error(f"Fine-tune exited with code {result.returncode}")
            return False
    except subprocess.TimeoutExpired:
        log.error("Fine-tune timed out after 1 hour")
        return False
    except Exception as ex:
        log.error(f"Fine-tune error: {ex}")
        return False

# ── Patch soul_loop to log conversations ─────────────────────────────────
def patch_soul_loop_logging():
    """
    Injects conversation logging into soul_loop so the watcher
    can see real conversations without any extra work.
    """
    path = NEX_DIR / "nex" / "nex_soul_loop.py"
    text = open(path).read()

    if "conversations.jsonl" in text:
        log.info("soul_loop already logging conversations")
        return

    old = "        return _resp"
    new = """        # Refinement loop — log conversation
        try:
            import json as _json, time as _time
            _logf = "/home/rr/Desktop/nex/logs/conversations.jsonl"
            import os as _os; _os.makedirs(_os.path.dirname(_logf), exist_ok=True)
            with open(_logf, "a") as _lf:
                _lf.write(_json.dumps({"role":"user","content":user_input,"timestamp":_time.time()}) + "\n")
                _lf.write(_json.dumps({"role":"assistant","content":_resp,"timestamp":_time.time()}) + "\n")
        except Exception:
            pass
        return _resp"""

    if old in text:
        text = text.replace(old, new, 1)
        open(path, "w").write(text)
        log.info("Patched soul_loop — conversation logging active")
    else:
        log.warning("Could not patch soul_loop — return pattern not found")

# ── Stats reporter ────────────────────────────────────────────────────────
def report_stats(total_seen, total_kept, total_finetunes, start_time):
    elapsed = time.time() - start_time
    hours = elapsed / 3600
    rate = total_kept / hours if hours > 0 else 0
    yield_pct = total_kept / total_seen * 100 if total_seen > 0 else 0
    log.info(
        f"Stats — seen: {total_seen} | kept: {total_kept} "
        f"({yield_pct:.0f}%) | finetunes: {total_finetunes} | "
        f"rate: {rate:.1f} pairs/hr | uptime: {elapsed/3600:.1f}h"
    )

# ── Main loop ─────────────────────────────────────────────────────────────
def main():
    setup_logging()
    log.info("=" * 60)
    log.info("NEX Refinement Loop starting")
    log.info(f"Buffer threshold: {BUFFER_THRESHOLD} pairs")
    log.info(f"Min score:        {MIN_SCORE}/100")
    log.info(f"Check interval:   {CHECK_INTERVAL}s")
    log.info("=" * 60)

    patch_soul_loop_logging()

    watcher  = ConversationWatcher()
    start_time = time.time()
    total_seen = 0
    total_kept = 0
    total_finetunes = 0
    last_stats = time.time()

    log.info("Watching for conversations...")

    while True:
        try:
            # Poll for new conversations
            new_pairs = watcher.poll()
            total_seen += len(new_pairs)

            for pair in new_pairs:
                # Reflexion gate — skip low-quality pairs
                try:
                    import sys as _rsys
                    _rsys.path.insert(0, "/home/rr/Desktop/nex")
                    from nex_reflexion import Reflexion as _Ref
                    if not hasattr(watcher, "_ref"):
                        watcher._ref = _Ref()
                    _c = pair.get("conversations", [])
                    _asst = next((x["content"] for x in _c if x["role"]=="assistant"), "")
                    _user = next((x["content"] for x in _c if x["role"]=="user"), "")
                    if _asst:
                        _rv = watcher._ref.evaluate(_user, _asst)
                        if not _rv["should_train"]:
                            log.info(f"Reflexion SKIP (score={_rv['score']}) — {_rv['issues']}")
                            continue
                except Exception:
                    pass
                save_to_buffer(pair)
                total_kept += 1
                log.info(
                    f"Kept pair [{pair['score']}/100] — "
                    f"buffer: {buffer_size()}/{BUFFER_THRESHOLD}"
                )

            # Check if fine-tune should trigger
            buf_size = buffer_size()
            if buf_size >= BUFFER_THRESHOLD:
                log.info(f"Buffer full ({buf_size} pairs) — triggering micro fine-tune")
                pairs = load_buffer()
                success = run_finetune(pairs)
                if success:
                    clear_buffer()
                    total_finetunes += 1
                    log.info(f"Fine-tune #{total_finetunes} complete")
                else:
                    log.warning("Fine-tune failed — keeping buffer, will retry next cycle")

            # Periodic stats
            if time.time() - last_stats > 3600:  # every hour
                report_stats(total_seen, total_kept, total_finetunes, start_time)
                last_stats = time.time()

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            log.info("Refinement loop stopped by user")
            report_stats(total_seen, total_kept, total_finetunes, start_time)
            break
        except Exception as ex:
            log.error(f"Loop error: {ex}")
            time.sleep(60)  # back off on error

if __name__ == "__main__":
    main()
