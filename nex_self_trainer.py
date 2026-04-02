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
BASE_MODEL = "/media/rr/NEX/models/Qwen2.5-3B-Instruct"  # Qwen2.5-3B: ~6GB fp16, fits 8GB VRAM with LoRA overhead
# Fallback: "/media/rr/4TB DATA/llmz/Mistral-7B-Instruct-v0.3-hf"
TRAINED    = "/home/rr/Desktop/nex/nex_trained"
TRAIN_DIR  = "/home/rr/Desktop/nex/nex_training"
LOG        = "/media/rr/4TB DATA/llmz/nex_training/train.log"
STATE_FILE = Path.home() / ".config" / "nex" / "trainer_state.json"

# ── Llama server ──────────────────────────────────────────────────────────────
LLAMA_SERVER_BIN = (
    "/media/rr/4TB DATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF"
    "/llama.cpp/build-rocm/bin/llama-server"
)
# After training, the merged GGUF will be saved here and served
TRAINED_GGUF = "/home/rr/Desktop/nex/nex_lora.gguf"

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
    # avg_conf thresholds now match nex_belief_quality scorer scale (0.0-1.0)
    # quality_score 0.47+ = healthy corpus; 0.55+ = strong; 0.65+ = elite-heavy
    "light":  {"new_beliefs": 200,  "avg_conf": 0.44},
    "medium": {"new_beliefs": 500,  "avg_conf": 0.50},
    "heavy":  {"new_beliefs": 1000, "avg_conf": 0.55},
    "havok":  {"new_beliefs": 2000, "avg_conf": 0.62},
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
    """Pull belief count, avg quality_score (or confidence fallback), high-conf count."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM beliefs")
        total = cur.fetchone()[0] or 0

        # Use quality_score if available (set by nex_belief_refiner)
        try:
            cur.execute("SELECT AVG(quality_score) FROM beliefs WHERE quality_score IS NOT NULL")
            avg_q = cur.fetchone()[0]
            avg_conf = round(float(avg_q or 0.0), 3)
            # Fall back to confidence if quality_score not populated
            if avg_conf < 0.01:
                cur.execute("SELECT AVG(confidence) FROM beliefs")
                avg_conf = round(float(cur.fetchone()[0] or 0.0), 3)
        except Exception:
            cur.execute("SELECT AVG(confidence) FROM beliefs")
            avg_conf = round(float(cur.fetchone()[0] or 0.0), 3)

        try:
            cur.execute("SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.70")
            high_conf = cur.fetchone()[0] or 0
        except Exception:
            cur.execute("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.70")
            high_conf = cur.fetchone()[0] or 0

        cur.execute("SELECT COUNT(DISTINCT topic) FROM beliefs")
        topics = cur.fetchone()[0] or 0

        conn.close()
        return {
            "total":     total,
            "avg_conf":  avg_conf,
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

TRAIN_COMMANDS = {"/light", "/medium", "/heavy", "/havok", "/notrain", "/train", "/beliefs", "/digest"}




def _db_belief_count():
    try:
        import sqlite3
        from pathlib import Path as _P
        con = sqlite3.connect(_P("~/.config/nex/nex.db").expanduser())
        n = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0


def _crawl_topic_bg(topic, url, send_fn):
    """Crawl one topic in background thread, send Telegram updates."""
    import sys, threading
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).parent))

    def _run():
        import asyncio
        # Each thread needs its own event loop for crawl4ai
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        before = _db_belief_count()
        try:
            from nex.nex_crawler import NexCrawler, _resolve_search_url
            from nex.belief_store import get_db
            crawler = NexCrawler(belief_store=get_db)
            resolved = url or _resolve_search_url(topic)
            crawler.on_knowledge_gap(topic=topic, search_url=resolved)
            gained = _db_belief_count() - before
            after  = _db_belief_count()
            if gained > 0:
                send_fn(f"✓ {topic}\n+{gained} beliefs (db={after})")
                try:
                    from nex.nex_opinions import refresh_opinions
                    n_op = refresh_opinions()
                    if n_op > 0:
                        send_fn(f"🧠 {n_op} opinion(s) updated")
                except Exception:
                    pass
            else:
                send_fn(f"⚠ {topic} — 0 new beliefs (already known or source empty)")
        except Exception as e:
            send_fn(f"❌ {topic}: {str(e)[:120]}")

    threading.Thread(target=_run, daemon=True).start()


def _handle_train_command(text, send_fn):
    """
    Handle /train <topic or URL>
    Examples:
      /train phenomenology of consciousness
      /train goodhart law, sycophancy, ELK
      /train https://arxiv.org/abs/2301.07597
      /beliefs          — show belief count + top topics
      /digest           — run opinions + tensions + reflect now
    """
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).parent))

    parts = text.strip().split(None, 1)
    cmd   = parts[0].lower()
    arg   = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/beliefs":
        try:
            import sqlite3
            con = sqlite3.connect(_P("~/.config/nex/nex.db").expanduser())
            total = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
            topics = con.execute(
                "SELECT topic, COUNT(*) as n FROM beliefs GROUP BY topic ORDER BY n DESC LIMIT 10"
            ).fetchall()
            con.close()
            lines = [f"🧠 <b>Belief Status</b>", f"Total: {total}", ""]
            lines += [f"  {n:3d}  {t}" for t, n in topics]
            send_fn("\n".join(lines))
        except Exception as e:
            send_fn(f"❌ {e}")
        return

    if cmd == "/digest":
        send_fn("⚙️ Running digest (opinions + tensions + reflect)...")
        try:
            from nex.nex_opinions import refresh_opinions
            ops = refresh_opinions()
        except Exception:
            ops = 0
        try:
            from nex.nex_contradiction_resolver import detect_and_log
            tens = detect_and_log(limit=500, max_new=20)
        except Exception:
            tens = 0
        try:
            from nex.nex_reflect import reflect_tick
            ref = reflect_tick()
        except Exception:
            ref = 0
        send_fn(f"✓ Digest complete\nOpinions: {ops}  Tensions: {tens}  Reflect: {ref}")
        return

    if cmd == "/train":
        if not arg:
            send_fn("Usage:\n/train <topic>\n/train <topic1>, <topic2>\n/train https://...")
            return

        # URL direct crawl
        if arg.startswith("http://") or arg.startswith("https://"):
            send_fn(f"🔗 Crawling URL directly...\n{arg[:60]}")
            _crawl_topic_bg(arg, arg, send_fn)
            return

        # Comma-separated topics
        raw_topics = [t.strip() for t in arg.split(",") if t.strip()]
        if not raw_topics:
            send_fn("❌ No topics found in message")
            return

        send_fn(f"🧠 Training on {len(raw_topics)} topic(s):\n" +
                "\n".join(f"  • {t}" for t in raw_topics))

        # Inject into curiosity queue and crawl each
        import json
        from pathlib import Path as _P

        # Clear cooldown for these specific topics
        qf = _P("~/.config/nex/curiosity_queue.json").expanduser()

        for topic in raw_topics:
            _crawl_topic_bg(topic, None, send_fn)

        return

    send_fn(f"Unknown command: {cmd}")

def handle_training_command(text: str, send_fn) -> bool:
    cmd = text.strip().lower().split()[0] if text.strip() else ""
    if cmd in {"/train", "/beliefs", "/digest"}:
        _handle_train_command(text, send_fn)
        return
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
        # ── Isolate: kill NEX run.py to free VRAM ────────────────────────────
        try:
            import subprocess as _sp2
            _result = _sp2.run(["pgrep", "-f", "run.py"], capture_output=True, text=True)
            if _result.stdout.strip():
                _log("Stopping NEX run.py to free VRAM for training...")
                send_fn("⏸ Pausing NEX for training isolation...")
                _sp2.run(["pkill", "-f", "run.py"], timeout=10)
                time.sleep(5)
                _log("NEX stopped — VRAM freed")
        except Exception as _ke:
            _log(f"Could not stop NEX: {_ke} — proceeding anyway")
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
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model, TaskType
    from trl import SFTConfig, SFTTrainer
    from datasets import Dataset

    cfg = INTENSITIES[intensity]

    # ── Load voice training dataset ──────────────────────────────────────────
    import json as _json, random as _rnd
    VOICE_FILE = "/home/rr/Desktop/nex/nex_training/train.jsonl"
    _lines = open(VOICE_FILE).readlines()
    limit = cfg["belief_limit"]
    if len(_lines) > limit:
        _lines = _rnd.sample(_lines, limit)
    if len(_lines) < 20:
        raise RuntimeError(f"Only {len(_lines)} training pairs — not enough to train.")
    send_fn(f"📚 Loaded {len(_lines):,} training pairs from voice dataset")
    _log(f"Loaded {len(_lines)} pairs from {VOICE_FILE}")
    # ── Build dataset ─────────────────────────────────────────────────────────
    def _to_chatml(d):
        msgs = d["messages"]
        t = ""
        for m in msgs:
            t += f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n"
        return {"text": t}
    formatted = [_to_chatml(_json.loads(l)) for l in _lines]
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

    # ── GPU/CPU + 4-bit quant for 8GB VRAM ──────────────────────────────────
    os.environ["PYTORCH_HIP_ALLOC_CONF"] = "expandable_segments:True"
    _use_gpu = torch.cuda.is_available()
    if _use_gpu:
        _log("GPU detected — loading fp16 on GPU only (no offload)")
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            device_map={"": 0},
            trust_remote_code=True,
        )
    else:
        _log("No GPU — loading on CPU (slow)")
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            device_map={"": torch.device("cpu")},
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
    model = get_peft_model(model, lora_config)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    _log(f"Trainable params: {trainable:,}")
    send_fn(f"🔧 Model loaded · Trainable params: {trainable:,}")

    # ── SFTConfig (TRL ≥ 0.9) ─────────────────────────────────────────────────
    output = Path(TRAINED) / f"run_{intensity}_{int(time.time())}"
    training_cfg = SFTConfig(
        output_dir=str(output),
        
        num_train_epochs=cfg["epochs"],
        per_device_train_batch_size=1,  # reduced for 8GB VRAM
        gradient_accumulation_steps=8,
        learning_rate=cfg["lr"],
        fp16=_use_gpu,
        gradient_checkpointing=False,
        logging_steps=20,
        save_strategy="no",
        save_total_limit=1,
        warmup_steps=10,
        lr_scheduler_type="cosine",
        report_to="none",
        dataloader_num_workers=0,
        dataset_text_field="text",
        max_seq_length=512,
        packing=False,
    )

    # gradient_checkpointing disabled — conflicts with LoRA on ROCm
    model.config.use_cache = False
    trainer = SFTTrainer(
        model=model,
        args=training_cfg,
        train_dataset=dataset,
        tokenizer=tokenizer,
    )

    _log("Training started...")
    try:
        trainer.train()
        _log("Training complete — saving adapter...")
    except Exception as _te:
        _log(f"Training error: {_te}")
        send_fn(f"❌ Training failed during epoch: {_te}")
        raise
    try:
        output_final = output / "final"
        output_final.mkdir(parents=True, exist_ok=True)
        trainer.save_model(str(output_final))
        _log(f"Adapter saved → {output_final}")
    except Exception as _se:
        _log(f"Save error: {_se}")
        send_fn(f"❌ Adapter save failed: {_se}")
        raise

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
        base  = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=torch.float16, device_map="cpu")
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
            "/media/rr/4TB DATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF"
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
        # Use quality_score for ordering when available
        try:
            cur.execute("SELECT COUNT(*) FROM pragma_table_info('beliefs') WHERE name='quality_score'")
            has_qs = cur.fetchone()[0]
        except Exception:
            has_qs = 0
        order_col = "quality_score DESC, confidence DESC" if has_qs else "confidence DESC, last_referenced DESC"
        cur.execute(f"""
            SELECT topic, content, confidence FROM beliefs
            WHERE confidence >= ? AND length(content) > 40
            ORDER BY {order_col}
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
