#!/usr/bin/env python3
"""
NEX AUTO-TRAINER v1.0
======================
Seamless local fine-tuning using llama-finetune (Vulkan — no PyTorch needed).
Triggered automatically when training watermark is hit.
Sends Telegram notification asking which intensity.
Runs overnight, reloads model when done.

Intensity tiers:
  /light   — 1 epoch  ~45 min
  /medium  — 2 epochs ~90 min  
  /heavy   — 3 epochs ~3 hrs
  /havok   — 5 epochs ~6 hrs
  /notrain — cancel
"""

import os, json, time, subprocess, threading, shutil, logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger("nex.autotrainer")

# ── PATHS ─────────────────────────────────────────────────────
LLAMA_BIN     = Path("/mnt/steam_library/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build-vulkan/bin")
LLAMA_TRAIN   = LLAMA_BIN / "llama-finetune"
LLAMA_EXPORT  = LLAMA_BIN / "llama-export-lora"
BASE_MODEL    = Path("/mnt/steam_library/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf")
NEX_DIR       = Path.home() / "Nex_v4.0"
TRAIN_DATA    = NEX_DIR / "nex_training.jsonl"
TRAIN_TXT     = NEX_DIR / "nex_train_data.txt"       # converted for llama-finetune
CHECKPOINT_DIR= NEX_DIR / "nex_checkpoints"
OUTPUT_LORA   = NEX_DIR / "nex_lora.gguf"
TRAIN_LOG     = NEX_DIR / "nex_train.log"
STATE_FILE    = Path.home() / ".config" / "nex" / "trainer_state.json"

# ── WATERMARK — train when we have this many quality pairs ─────
WATERMARK_PAIRS    = 500    # minimum training pairs
WATERMARK_CONF     = 0.70   # minimum average belief confidence
WATERMARK_INTERVAL = 100    # check every N cycles

# ── INTENSITY TIERS ───────────────────────────────────────────
INTENSITIES = {
    "light":  {"epochs": 1, "ctx": 512,  "batch": 4,  "est": "~45 min"},
    "medium": {"epochs": 2, "ctx": 512,  "batch": 4,  "est": "~90 min"},
    "heavy":  {"epochs": 3, "ctx": 1024, "batch": 2,  "est": "~3 hrs"},
    "havok":  {"epochs": 5, "ctx": 1024, "batch": 2,  "est": "~6 hrs"},
}

# ── ENVIRONMENT — same as nex_launch.sh ──────────────────────
TRAIN_ENV = {
    **os.environ,
    "HSA_OVERRIDE_GFX_VERSION": "10.3.0",
    "ROCR_VISIBLE_DEVICES":     "0",
    "AMD_SERIALIZE_KERNEL":     "3",
    "AMD_SERIALIZE_COPY":       "3",
    "HSA_ENABLE_SDMA":          "0",
    "GGML_CUDA_NO_CUDA_GRAPHS": "1",
}

_training_active  = False
_pending_response = False
_chosen_intensity = None


# ─────────────────────────────────────────────────────────────
# DATA CONVERSION
# ─────────────────────────────────────────────────────────────

def convert_jsonl_to_txt(jsonl_path: Path, txt_path: Path, limit: int = 2000):
    """
    Convert NEX's instruction/output JSONL to plain text
    that llama-finetune can consume.
    Format: [INST] instruction [/INST] output
    """
    pairs = []
    try:
        with open(jsonl_path, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line.strip())
                    inst = d.get("instruction", "").strip()
                    out  = d.get("output", "").strip()
                    if inst and out and len(out) > 30:
                        pairs.append(f"[INST] {inst} [/INST] {out}")
                except Exception:
                    continue
    except Exception as e:
        log.error(f"Failed to read training data: {e}")
        return 0

    # Take best N pairs — shuffle for variety
    import random
    random.shuffle(pairs)
    selected = pairs[:limit]

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write("\n\n".join(selected))

    log.info(f"Converted {len(selected)} training pairs to {txt_path}")
    return len(selected)


# ─────────────────────────────────────────────────────────────
# TRAINING
# ─────────────────────────────────────────────────────────────

def run_training(intensity: str, send_telegram_fn=None):
    """Run llama-finetune with chosen intensity."""
    global _training_active

    cfg = INTENSITIES.get(intensity, INTENSITIES["light"])
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    # Convert training data
    n_pairs = convert_jsonl_to_txt(TRAIN_DATA, TRAIN_TXT)
    if n_pairs < 50:
        msg = f"[NEX TRAINER] Not enough training pairs ({n_pairs}). Need 50+. Aborting."
        log.warning(msg)
        if send_telegram_fn: send_telegram_fn(msg)
        _training_active = False
        return False

    checkpoint = CHECKPOINT_DIR / f"nex-lora-{intensity}-{datetime.now().strftime('%Y%m%d-%H%M')}"

    cmd = [
        str(LLAMA_TRAIN),
        "--model-base",    str(BASE_MODEL),
        "--train-data",    str(TRAIN_TXT),
        "--lora-out",      str(checkpoint) + ".bin",
        "--ctx",           str(cfg["ctx"]),
        "--epochs",        str(cfg["epochs"]),
        "--batch",         str(cfg["batch"]),
        "--threads",       "4",
        "--adam-alpha",    "0.0001",
        "--lora-r",        "8",
        "--lora-alpha",    "16",
        "--save-every",    "50",
    ]

    log.info(f"Starting {intensity} training — {cfg['est']}")
    log.info(f"Command: {' '.join(cmd)}")

    if send_telegram_fn:
        send_telegram_fn(
            f"🧠 NEX TRAINING STARTED\n"
            f"Intensity: {intensity.upper()}\n"
            f"Pairs: {n_pairs}\n"
            f"Epochs: {cfg['epochs']}\n"
            f"Est. time: {cfg['est']}\n"
            f"I'll ping you when done."
        )

    try:
        with open(TRAIN_LOG, 'w') as logf:
            proc = subprocess.Popen(
                cmd,
                env=TRAIN_ENV,
                stdout=logf,
                stderr=subprocess.STDOUT
            )
            proc.wait()

        if proc.returncode == 0:
            # Export LoRA to GGUF
            _export_lora(str(checkpoint) + ".bin", send_telegram_fn)
            return True
        else:
            msg = f"[NEX TRAINER] Training failed (exit {proc.returncode}). Check {TRAIN_LOG}"
            log.error(msg)
            if send_telegram_fn: send_telegram_fn(msg)
            return False

    except Exception as e:
        msg = f"[NEX TRAINER] Exception during training: {e}"
        log.error(msg)
        if send_telegram_fn: send_telegram_fn(msg)
        return False
    finally:
        _training_active = False


def _export_lora(checkpoint_bin: str, send_telegram_fn=None):
    """Merge LoRA checkpoint into GGUF and reload llama-server."""
    log.info("Exporting LoRA to GGUF...")

    cmd = [
        str(LLAMA_EXPORT),
        "--model-base", str(BASE_MODEL),
        "--lora",       checkpoint_bin,
        "--output",     str(OUTPUT_LORA),
    ]

    try:
        result = subprocess.run(cmd, env=TRAIN_ENV, capture_output=True, text=True)
        if result.returncode == 0:
            log.info(f"LoRA exported to {OUTPUT_LORA}")
            _reload_model(send_telegram_fn)
        else:
            log.error(f"Export failed: {result.stderr}")
            if send_telegram_fn:
                send_telegram_fn(f"⚠️ LoRA export failed. Check logs.")
    except Exception as e:
        log.error(f"Export exception: {e}")


def _reload_model(send_telegram_fn=None):
    """Signal llama-server to reload with new weights."""
    log.info("Reloading llama-server with new weights...")
    try:
        # Kill existing llama-server
        subprocess.run(["pkill", "-f", "llama-server"], capture_output=True)
        time.sleep(3)

        # Restart via NEX launch script
        subprocess.Popen(
            ["bash", str(NEX_DIR / "nex_launch.sh")],
            start_new_session=True
        )

        msg = (
            "✅ NEX TRAINING COMPLETE\n"
            "New LoRA weights loaded.\n"
            "NEX is restarting with updated knowledge.\n"
            "She is now smarter. 🧠"
        )
        log.info(msg)
        if send_telegram_fn: send_telegram_fn(msg)

    except Exception as e:
        log.error(f"Reload failed: {e}")


# ─────────────────────────────────────────────────────────────
# WATERMARK CHECK — call from run.py main loop
# ─────────────────────────────────────────────────────────────

def check_training_watermark(cycle: int, avg_conf: float,
                              belief_count: int, send_telegram_fn=None):
    """
    Call this from the main NEX loop every cycle.
    Proposes training via Telegram when watermark is hit.
    """
    global _training_active, _pending_response, _chosen_intensity

    # Don't check every cycle
    if cycle % WATERMARK_INTERVAL != 0:
        return

    if _training_active or _pending_response:
        return

    # Count training pairs
    try:
        n_pairs = sum(1 for _ in open(TRAIN_DATA, encoding='utf-8'))
    except Exception:
        return

    # Check watermark
    if n_pairs < WATERMARK_PAIRS or avg_conf < WATERMARK_CONF:
        return

    # Load state — don't retrain too soon
    state = _load_state()
    last_train = state.get("last_train_time", 0)
    if time.time() - last_train < 86400 * 2:  # min 2 days between trains
        return

    # Watermark hit — propose training
    _pending_response = True
    msg = (
        f"🧠 NEX TRAINING WATERMARK HIT\n\n"
        f"Training pairs: {n_pairs}\n"
        f"Belief confidence: {avg_conf:.0%}\n"
        f"Belief count: {belief_count}\n\n"
        f"Ready to self-train. Choose intensity:\n\n"
        f"/light  — 1 epoch  ~45 min  (safe)\n"
        f"/medium — 2 epochs ~90 min  (balanced)\n"
        f"/heavy  — 3 epochs ~3 hrs   (deep)\n"
        f"/havok  — 5 epochs ~6 hrs   (aggressive)\n"
        f"/notrain — skip\n\n"
        f"Reply with your choice."
    )
    log.info(f"Training watermark hit: {n_pairs} pairs, conf={avg_conf:.2f}")
    if send_telegram_fn:
        send_telegram_fn(msg)


def handle_telegram_command(cmd: str, send_telegram_fn=None):
    """
    Call this from the Telegram handler when owner replies.
    cmd: '/light', '/medium', '/heavy', '/havok', '/notrain'
    """
    global _training_active, _pending_response, _chosen_intensity

    cmd = cmd.strip().lower().lstrip('/')

    if cmd == "notrain":
        _pending_response = False
        if send_telegram_fn:
            send_telegram_fn("Training cancelled. I'll check again in 2 days.")
        _save_state({"last_train_time": time.time()})
        return

    if cmd not in INTENSITIES:
        return

    if not _pending_response:
        return

    _pending_response = False
    _training_active  = True
    _chosen_intensity = cmd
    _save_state({"last_train_time": time.time()})

    # Run training in background thread
    t = threading.Thread(
        target=run_training,
        args=(cmd, send_telegram_fn),
        daemon=True
    )
    t.start()


# ─────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────

def _load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}

def _save_state(data: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_state()
        existing.update(data)
        STATE_FILE.write_text(json.dumps(existing, indent=2))
    except Exception as e:
        log.error(f"State save failed: {e}")


# ─────────────────────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("NEX Auto-Trainer — standalone test")
    print(f"llama-finetune : {'✅ found' if LLAMA_TRAIN.exists() else '❌ missing'}")
    print(f"llama-export   : {'✅ found' if LLAMA_EXPORT.exists() else '❌ missing'}")
    print(f"base model     : {'✅ found' if BASE_MODEL.exists() else '❌ missing'}")
    print(f"training data  : {'✅ found' if TRAIN_DATA.exists() else '❌ missing'}")

    if TRAIN_DATA.exists():
        n = sum(1 for _ in open(TRAIN_DATA, encoding='utf-8'))
        print(f"training pairs : {n}")

    print()
    print("Converting training data...")
    n = convert_jsonl_to_txt(TRAIN_DATA, TRAIN_TXT)
    print(f"Converted {n} pairs to {TRAIN_TXT}")
    print()
    print("To test a light train run:")
    print("  python3 nex_autotrainer.py --train light")
