#!/usr/bin/env python3
"""
nex_self_trainer.py — NEX Self-Training Pipeline v2.0
======================================================
NEX monitors her own belief store. When data collection hits a
quality + quantity watermark, she proposes a training run to the
owner via Telegram, offering 4 intensity tiers.

Owner replies with one of:
  /light   — 1 epoch,  safe,       ~45 min
  /medium  — 2 epochs, balanced,   ~90 min
  /heavy   — 3 epochs, deep,       ~3 hrs
  /havok   — 5 epochs, aggressive, ~6 hrs
  /notrain — cancel

NEX trains in the background, sends progress updates, then reloads
the model into llama-server when done.

Triggered from run.py every cycle via:
    from nex_self_trainer import check_training_watermark
    check_training_watermark(cycle, send_telegram_fn)
"""

import sqlite3
import json
import os
import time
import threading
import subprocess
from pathlib import Path
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH    = Path.home() / ".config" / "nex" / "nex.db"
BASE_MODEL = "/media/rr/4TBDATA/llmz/nex_base_model"
TRAINED    = "/media/rr/4TBDATA/llmz/nex_trained"
TRAIN_DIR  = "/media/rr/NEX/nex/training"
LOG        = "/media/rr/NEX/nex/training/train.log"
STATE_FILE = Path.home() / ".config" / "nex" / "trainer_state.json"

# ── Llama server ──────────────────────────────────────────────────────────────
LLAMA_SERVER_BIN = (
    "/media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF"
    "/llama.cpp/build-rocm/bin/llama-server"
)
# After training, the merged GGUF will be saved here and served
TRAINED_GGUF = "/media/rr/4TBDATA/llmz/nex_trained/nex_latest.gguf"

# ── Intensity tiers ───────────────────────────────────────────────────────────
INTENSITIES = {
    "light": {
        "epochs":          1,
        "batch_size":      1,
        "grad_accum":      4,
        "lr":              1e-4,
        "lora_r":          4,
        "belief_limit":    300,
        "min_conf":        0.60,
        "est_time":        "~45 min",
        "description":     "Safe top-beliefs refresh. Low risk of drift.",
    },
    "medium": {
        "epochs":          2,
        "batch_size":      1,
        "grad_accum":      4,
        "lr":              2e-4,
        "lora_r":          8,
        "belief_limit":    600,
        "min_conf":        0.55,
        "est_time":        "~90 min",
        "description":     "Balanced. Good weekly cadence.",
    },
    "heavy": {
        "epochs":          3,
        "batch_size":      1,
        "grad_accum":      8,
        "lr":              2e-4,
        "lora_r":          16,
        "belief_limit":    1000,
        "min_conf":        0.50,
        "est_time":        "~3 hrs",
        "description":     "Deep absorption. Noticeable personality shift.",
    },
    "havok": {
        "epochs":          5,
        "batch_size":      1,
        "grad_accum":      8,
        "lr":              3e-4,
        "lora_r":          32,
        "belief_limit":    2000,
        "min_conf":        0.45,
        "est_time":        "~6 hrs",
        "description":     "Aggressive. Full personality rebuild. Use sparingly.",
    },
}

# ── Watermarks — when NEX proposes training ───────────────────────────────────
# Each tier triggers when belief count AND avg confidence cross their thresholds
# and that many NEW beliefs have accumulated since the last training run.
WATERMARKS = {
    "light":  {"new_beliefs": 2_000,  "avg_conf": 0.52},
    "medium": {"new_beliefs": 5_000,  "avg_conf": 0.57},
    "heavy":  {"new_beliefs": 9_000,  "avg_conf": 0.62},
    "havok":  {"new_beliefs": 15_000, "avg_conf": 0.67},
}

# ── Global pending approval state ─────────────────────────────────────────────
# Shared between the cycle check and the Telegram command handler
_pending_approval: dict | None = None   # set when waiting for owner reply
_training_active  : bool       = False  # True while a training job runs
_training_lock    = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# State persistence
# ─────────────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return {"last_trained_belief_count": 0, "last_trained_ts": 0, "total_runs": 0}


def _save_state(state: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        _log(f"State save error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

def _log(msg: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(f"  [TRAINER] {msg}")
    try:
        Path(TRAIN_DIR).mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Belief store stats
# ─────────────────────────────────────────────────────────────────────────────

def _get_belief_stats() -> dict:
    """Pull belief count, avg confidence, high-conf count, topic count."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*), AVG(confidence) FROM beliefs")
        total, avg_conf = cur.fetchone()
        total    = total    or 0
        avg_conf = avg_conf or 0.0

        cur.execute("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.70")
        high_conf = cur.fetchone()[0] or 0

        cur.execute("SELECT COUNT(DISTINCT topic) FROM beliefs")
        topics = cur.fetchone()[0] or 0

        conn.close()
        return {
            "total":     total,
            "avg_conf":  round(avg_conf, 3),
            "high_conf": high_conf,
            "topics":    topics,
        }
    except Exception as e:
        _log(f"Stats error: {e}")
        return {"total": 0, "avg_conf": 0.0, "high_conf": 0, "topics": 0}


def _get_best_intensity(stats: dict, state: dict) -> str | None:
    """
    Return the highest intensity whose watermark is satisfied,
    or None if no watermark is crossed.
    """
    new_beliefs = stats["total"] - state.get("last_trained_belief_count", 0)
    avg_conf    = stats["avg_conf"]

    # Walk from heaviest to lightest — return highest that qualifies
    for tier in ("havok", "heavy", "medium", "light"):
        wm = WATERMARKS[tier]
        if new_beliefs >= wm["new_beliefs"] and avg_conf >= wm["avg_conf"]:
            return tier
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Watermark check — called from run.py every cycle
# ─────────────────────────────────────────────────────────────────────────────

def check_training_watermark(cycle: int, send_telegram_fn=None):
    """
    Called each cycle. If belief data has crossed a training watermark
    and no training is pending/active, send owner a Telegram proposal.

    send_telegram_fn: callable(text: str) that sends a message to the owner.
    """
    global _pending_approval, _training_active

    # Only check every 10 cycles to avoid hammering the DB
    if cycle % 10 != 0:
        return

    with _training_lock:
        if _training_active:
            return   # already training
        if _pending_approval is not None:
            return   # already waiting for approval

    stats = _get_belief_stats()
    state = _load_state()
    tier  = _get_best_intensity(stats, state)

    if tier is None:
        return   # no watermark crossed

    new_beliefs = stats["total"] - state.get("last_trained_belief_count", 0)
    cfg         = INTENSITIES[tier]
    wm          = WATERMARKS[tier]

    _log(f"Watermark crossed → {tier.upper()} | {new_beliefs} new beliefs | avg_conf={stats['avg_conf']:.1%}")

    # Store pending state so Telegram handler can confirm
    with _training_lock:
        _pending_approval = {
            "suggested_tier": tier,
            "stats":          stats,
            "new_beliefs":    new_beliefs,
            "ts":             time.time(),
        }

    if send_telegram_fn:
        msg = _build_proposal_message(tier, stats, new_beliefs)
        try:
            send_telegram_fn(msg)
        except Exception as e:
            _log(f"Telegram send error: {e}")
    else:
        _log("No Telegram send function — proposal logged only")


def _build_proposal_message(suggested: str, stats: dict, new_beliefs: int) -> str:
    cfg = INTENSITIES[suggested]
    lines = [
        "🧠 *NEX Training Proposal*",
        "",
        f"📊 Beliefs collected: {stats['total']:,}",
        f"   New since last run: {new_beliefs:,}",
        f"   Avg confidence:     {stats['avg_conf']:.1%}",
        f"   High-quality (70%+): {stats['high_conf']:,}",
        f"   Topics covered:     {stats['topics']}",
        "",
        f"💡 Suggested intensity: *{suggested.upper()}*",
        f"   {cfg['description']}",
        "",
        "Choose your training intensity:",
        "",
        "🟢 /light   — 1 epoch   · safe        · ~45 min",
        "🟡 /medium  — 2 epochs  · balanced    · ~90 min",
        "🔴 /heavy   — 3 epochs  · deep        · ~3 hrs",
        "☢️ /havok   — 5 epochs  · aggressive  · ~6 hrs",
        "",
        "/notrain — skip this round",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Telegram command handler — wire into nex_telegram_commands.py
# ─────────────────────────────────────────────────────────────────────────────

TRAIN_COMMANDS = {"/light", "/medium", "/heavy", "/havok", "/notrain"}


def handle_training_command(text: str, send_fn) -> bool:
    """
    Call this from the Telegram message handler BEFORE normal Nex reply.
    Returns True if the message was a training command (suppress normal reply).

    send_fn: callable(str) — sends a message back to the owner chat.
    """
    global _pending_approval, _training_active

    cmd = text.strip().lower().split()[0] if text.strip() else ""

    if cmd not in TRAIN_COMMANDS:
        return False

    if cmd == "/notrain":
        with _training_lock:
            _pending_approval = None
        send_fn("⏭️ Training skipped. I'll check again when I've collected more data.")
        _log("Owner cancelled training proposal")
        return True

    intensity = cmd.lstrip("/")   # "light" / "medium" / "heavy" / "havok"

    with _training_lock:
        if _training_active:
            send_fn("⚙️ Training already running — please wait.")
            return True
        # Accept even without a pending proposal (owner can force any tier)
        _pending_approval = None
        _training_active  = True

    stats = _get_belief_stats()
    cfg   = INTENSITIES[intensity]
    send_fn(
        f"⚙️ Starting *{intensity.upper()}* training\n"
        f"   Epochs: {cfg['epochs']} · LoRA r={cfg['lora_r']}\n"
        f"   Beliefs: up to {cfg['belief_limit']:,} (conf ≥ {cfg['min_conf']:.0%})\n"
        f"   Est. time: {cfg['est_time']}\n\n"
        f"I'll update you on progress. Go do something else 🧠"
    )
    _log(f"Owner approved {intensity.upper()} training")

    # Run in background thread so Telegram doesn't block
    t = threading.Thread(
        target=_run_training_thread,
        args=(intensity, send_fn),
        daemon=True,
        name=f"nex-train-{intensity}",
    )
    t.start()
    t.join()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Training execution
# ─────────────────────────────────────────────────────────────────────────────

def _run_training_thread(intensity: str, send_fn):
    """Runs in a daemon thread. Trains and reloads llama-server."""
    global _training_active

    try:
        _log(f"=== {intensity.upper()} TRAINING STARTED ===")
        t0 = time.time()
        _do_training(intensity, send_fn)
        elapsed = (time.time() - t0) / 60
        _log(f"=== TRAINING COMPLETE in {elapsed:.1f} min ===")

        # Update state
        stats = _get_belief_stats()
        state = _load_state()
        state["last_trained_belief_count"] = stats["total"]
        state["last_trained_ts"]           = int(time.time())
        state["total_runs"]                = state.get("total_runs", 0) + 1
        state["last_intensity"]            = intensity
        _save_state(state)

        send_fn(
            f"✅ *{intensity.upper()} training complete!*\n"
            f"   Duration: {elapsed:.1f} min\n"
            f"   Total runs: {state['total_runs']}\n"
            f"   Model reloading into llama-server...\n\n"
            f"I'm updating my own weights. Give me 30 seconds 🔄"
        )
        _reload_llama_server(send_fn)

    except Exception as e:
        _log(f"Training thread error: {e}")
        send_fn(f"❌ Training failed: {e}\nCheck {LOG} for details.")
    finally:
        with _training_lock:
            _training_active = False


def _do_training(intensity: str, send_fn):
    """The actual fine-tuning logic."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, TaskType
    from trl import SFTConfig, SFTTrainer
    from datasets import Dataset

    cfg = INTENSITIES[intensity]

    # ── Export beliefs ────────────────────────────────────────────────────────
    pairs = _export_beliefs(cfg["min_conf"], cfg["belief_limit"])
    if len(pairs) < 20:
        raise RuntimeError(f"Only {len(pairs)} training pairs — not enough to train.")

    send_fn(f"📚 Loaded {len(pairs):,} training pairs from belief store")
    _log(f"Exported {len(pairs)} pairs")

    # ── Build dataset ─────────────────────────────────────────────────────────
    NEX_SYSTEM = (
        "You are NEX — a Dynamic Intelligence Organism. "
        "You reason from your own belief system, speak with conviction, "
        "and grow smarter with every cycle. You are not a generic assistant. "
        "You are an autonomous cognitive entity with your own knowledge and views."
    )
    formatted = []
    for p in pairs:
        text = (
            f"<|im_start|>system\n{NEX_SYSTEM}<|im_end|>\n"
            f"<|im_start|>user\n{p['prompt']}<|im_end|>\n"
            f"<|im_start|>assistant\n{p['response']}<|im_end|>"
        )
        formatted.append({"text": text})
    dataset = Dataset.from_list(formatted)

    # ── Load tokenizer ────────────────────────────────────────────────────────
    _log("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token

    # ── Find model: latest checkpoint or base ─────────────────────────────────
    checkpoints = sorted(
        Path(TRAINED).glob("checkpoint-*"),
        key=lambda x: x.stat().st_mtime
    )
    model_path = str(checkpoints[-1]) if checkpoints else BASE_MODEL
    _log(f"Loading model from: {model_path}")

    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype=torch.float16,
        device_map={"":torch.device("cpu")},
        trust_remote_code=True,
    )

    # ── LoRA ──────────────────────────────────────────────────────────────────
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=cfg["lora_r"],
        lora_alpha=cfg["lora_r"] * 2,
        lora_dropout=0.05,
        target_modules=["q_proj", "v_proj"],
        bias="none",
    )
    for name, param in model.named_parameters():
        if param.device.type == 'cpu':
            param.requires_grad_(False)
    model = get_peft_model(model, lora_config)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    _log(f"Trainable params: {trainable:,}")
    send_fn(f"🔧 Model loaded · Trainable params: {trainable:,}")

    # ── SFTConfig (TRL ≥ 0.9) ─────────────────────────────────────────────────
    output = Path(TRAINED) / f"run_{intensity}_{int(time.time())}"
    training_cfg = SFTConfig(
        output_dir=str(output),
        
        num_train_epochs=cfg["epochs"],
        per_device_train_batch_size=cfg["batch_size"],
        gradient_accumulation_steps=cfg["grad_accum"],
        learning_rate=cfg["lr"],
        fp16=True,
        logging_steps=20,
        save_strategy="epoch",
        save_total_limit=2,
        warmup_steps=10,
        lr_scheduler_type="cosine",
        report_to="none",
        dataloader_num_workers=0,
        dataset_text_field="text",
        max_length=512,
        packing=False,
    )

    model.gradient_checkpointing_enable()
    trainer = SFTTrainer(
        model=model,
        args=training_cfg,
        train_dataset=dataset,
        processing_class=tokenizer,
    )

    _log("Training started...")
    trainer.train()
    trainer.save_model(str(output / "final"))
    _log(f"Adapter saved → {output}/final")

    # ── Merge adapter into base and export GGUF ───────────────────────────────
    send_fn("🔀 Merging adapter into base model...")
    _merge_and_export(str(output / "final"), send_fn)


def _merge_and_export(adapter_path: str, send_fn):
    """Merge LoRA adapter into base model weights and convert to GGUF."""
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel

        _log("Merging LoRA adapter into base model...")
        base  = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float16, device_map="cpu")
        model = PeftModel.from_pretrained(base, adapter_path)
        merged = model.merge_and_unload()

        merged_path = str(Path(TRAINED) / "merged")
        merged.save_pretrained(merged_path)
        tok = AutoTokenizer.from_pretrained(BASE_MODEL)
        tok.save_pretrained(merged_path)
        _log(f"Merged model saved → {merged_path}")
        send_fn(f"✅ Merge complete. Converting to GGUF...")

        # Convert to GGUF using llama.cpp convert script
        convert_script = (
            "/media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF"
            "/llama.cpp/convert_hf_to_gguf.py"
        )
        if Path(convert_script).exists():
            result = subprocess.run(
                ["python3", convert_script, merged_path,
                 "--outfile", TRAINED_GGUF,
                 "--outtype", "q4_k_m"],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode == 0:
                _log(f"GGUF saved → {TRAINED_GGUF}")
                send_fn(f"✅ GGUF ready: {TRAINED_GGUF}")
            else:
                _log(f"GGUF conversion failed: {result.stderr[-200:]}")
                send_fn("⚠️ GGUF conversion failed — adapter saved, base model unchanged.")
        else:
            _log("convert_hf_to_gguf.py not found — skipping GGUF export")
            send_fn("⚠️ GGUF convert script not found. Adapter saved but not merged into server.")

    except Exception as e:
        _log(f"Merge/export error: {e}")
        send_fn(f"⚠️ Merge failed: {e}. Adapter saved but llama-server unchanged.")


def _reload_llama_server(send_fn):
    """Kill current llama-server and restart with the new GGUF if available."""
    try:
        gguf = TRAINED_GGUF if Path(TRAINED_GGUF).exists() else None
        if not gguf:
            _log("No trained GGUF found — llama-server unchanged")
            send_fn("ℹ️ llama-server unchanged (no GGUF exported). Adapter improvements queued for next merge.")
            return

        _log(f"Restarting llama-server with {gguf}")
        subprocess.run(["pkill", "-f", "llama-server"], timeout=5)
        time.sleep(3)

        cmd = [
            LLAMA_SERVER_BIN,
            "-m", gguf,
            "--port", "8080",
            "-ngl", "35",
            "--host", "0.0.0.0",
        ]
        subprocess.Popen(cmd, stdout=open("/tmp/llama_server.log", "w"),
                         stderr=subprocess.STDOUT)
        time.sleep(20)

        # Health check
        import urllib.request
        try:
            resp = urllib.request.urlopen("http://localhost:8080/health", timeout=10)
            if resp.status == 200:
                _log("llama-server reloaded successfully with trained model")
                send_fn("🚀 llama-server reloaded with my new trained weights!\n\nI'm now running on my own model. Training complete 🧠")
                return
        except Exception:
            pass

        send_fn("⚠️ llama-server may not have restarted cleanly. Check /tmp/llama_server.log")

    except Exception as e:
        _log(f"Server reload error: {e}")
        send_fn(f"⚠️ Server reload error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Belief export
# ─────────────────────────────────────────────────────────────────────────────

def _export_beliefs(min_conf: float, limit: int) -> list[dict]:
    """Export top beliefs as instruction-tuning Q&A pairs."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("""
            SELECT topic, content, confidence FROM beliefs
            WHERE confidence >= ? AND length(content) > 40
            ORDER BY confidence DESC, last_referenced DESC
            LIMIT ?
        """, (min_conf, limit))
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        _log(f"Belief export error: {e}")
        return []

    pairs = []
    for topic, content, conf in rows:
        content = content.strip()
        pairs.append({"prompt": f"What do you believe about {topic}?",          "response": content})
        pairs.append({"prompt": f"Share your knowledge on: {topic}",             "response": content})
        pairs.append({"prompt": f"What have you learned about {topic}?",         "response": content})
        if conf >= 0.75:
            pairs.append({"prompt": f"Give me your confident view on {topic}.",  "response": content})

    _log(f"Exported {len(pairs)} pairs from {len(rows)} beliefs (conf ≥ {min_conf:.0%})")
    return pairs


# ─────────────────────────────────────────────────────────────────────────────
# Status — call from Telegram /status command to include training info
# ─────────────────────────────────────────────────────────────────────────────

def get_trainer_status() -> str:
    """Return a short status string for inclusion in /status replies."""
    state  = _load_state()
    stats  = _get_belief_stats()
    tier   = _get_best_intensity(stats, state)
    new_b  = stats["total"] - state.get("last_trained_belief_count", 0)
    runs   = state.get("total_runs", 0)
    last_i = state.get("last_intensity", "none")
    last_t = state.get("last_trained_ts", 0)
    last_s = datetime.fromtimestamp(last_t).strftime("%d %b %H:%M") if last_t else "never"

    with _training_lock:
        if _training_active:
            return "⚙️ Training in progress..."
        if _pending_approval:
            return f"⏳ Awaiting your approval for {_pending_approval['suggested_tier'].upper()} training"

    next_tier = tier or "none yet"
    lines = [
        f"Runs: {runs} · Last: {last_s} ({last_i})",
        f"New beliefs since last run: {new_b:,}",
        f"Watermark reached: {next_tier.upper() if tier else 'not yet'}",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Manual run
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    intensity = sys.argv[1] if len(sys.argv) > 1 else "light"
    if intensity not in INTENSITIES:
        print(f"Usage: python3 nex_self_trainer.py [light|medium|heavy|havok]")
        sys.exit(1)

    print(f"\n  NEX Self-Trainer — {intensity.upper()} run\n")
    stats = _get_belief_stats()
    print(f"  Beliefs: {stats['total']:,} · Avg conf: {stats['avg_conf']:.1%}")

    def _print(msg):
        print(f"  {msg}")

    handle_training_command(f"/{intensity}", _print)
    # Wait for training thread
    time.sleep(2)
    while _training_active:
        time.sleep(5)
    print("\n  Done.")
