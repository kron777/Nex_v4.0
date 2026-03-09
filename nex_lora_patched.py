"""
nex_lora.py — LoRA self-training pipeline for Nex v1.2
=======================================================
Drop into ~/Desktop/nex/nex/

Nex generates her own training data from her DB, fine-tunes her weights
using llama.cpp finetune, merges the adapter, and restarts on a new
version of herself.

Full loop:
  1. generate_training_data() — pulls from beliefs, conversations,
                                reflections, positions
  2. Telegram proposal to owner with data stats
  3. Owner approves
  4. pause llama-server (free VRAM)
  5. run llama-finetune
  6. merge adapter into base model
  7. restart llama-server on merged model
  8. report

Persistent state: ~/.config/nex/lora_state.json
Training data:    ~/.config/nex/training/
Model versions:   ~/llmz/nex_versions/
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("nex.lora")

# ─────────────────────────────────────────────────────────────────────────────
# Paths — adjust if your model lives elsewhere
# ─────────────────────────────────────────────────────────────────────────────

LORA_STATE_PATH   = os.path.expanduser("~/.config/nex/lora_state.json")
TRAINING_DIR      = "/media/rr/NEX/training/"
MODEL_VERSIONS_DIR= "/media/rr/NEX/models/"

# Auto-detected at runtime
_BASE_MODEL_PATH  = None   # original .gguf — set by detect_model()
_FINETUNE_BIN     = None   # llama-finetune binary — set by detect_finetune_bin()

# ─────────────────────────────────────────────────────────────────────────────
# Training config
# ─────────────────────────────────────────────────────────────────────────────

LORA_CONFIG = {
    "lora_r":           8,       # LoRA rank — higher = more capacity, more VRAM
    "lora_alpha":       16,      # LoRA alpha scaling
    "lora_dropout":     0.05,
    "learning_rate":    3e-4,
    "batch_size":       4,       # small batch for 8GB VRAM
    "epochs":           3,
    "warmup_steps":     10,
    "max_seq_len":      512,     # keep short for VRAM
    "gpu_layers":       28,
    "threads":          6,
}

# Minimum training examples before she'll propose
MIN_TRAINING_EXAMPLES = 50

# How many of each type to include
DATA_LIMITS = {
    "conversations":  200,   # her actual replies (high quality)
    "positions":      100,   # formed opinions from depth engine
    "beliefs":        300,   # her core knowledge
    "reflections":    100,   # self-assessments
}

# Cooldown between training runs
TRAINING_COOLDOWN_DAYS = 7


# ─────────────────────────────────────────────────────────────────────────────
# Model detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_model() -> Optional[str]:
    """Find the base model path."""
    global _BASE_MODEL_PATH
    if _BASE_MODEL_PATH:
        return _BASE_MODEL_PATH

    # Check if there's already a merged model we're running on
    state = _load_state()
    if state.get("current_model"):
        p = state["current_model"]
        if os.path.exists(p):
            _BASE_MODEL_PATH = p
            return p

    # Search common locations
    search_roots = [
        "~/llmz", "~/models", "~/llms",
        "/media", "/mnt", "~/.cache/huggingface"
    ]
    for root in search_roots:
        rp = os.path.expanduser(root)
        if not os.path.exists(rp):
            continue
        for dirpath, _, files in os.walk(rp):
            for f in files:
                if f.endswith(".gguf") and ("mistral" in f.lower() or "instruct" in f.lower()):
                    _BASE_MODEL_PATH = os.path.join(dirpath, f)
                    return _BASE_MODEL_PATH
    return None


def detect_finetune_bin() -> Optional[str]:
    """Find llama-finetune binary."""
    global _FINETUNE_BIN
    if _FINETUNE_BIN:
        return _FINETUNE_BIN

    model_path = detect_model()
    if not model_path:
        return None

    model_dir = os.path.dirname(model_path)
    candidates = [
        os.path.join(model_dir, "llama.cpp", "build", "bin", "llama-finetune"),
        os.path.join(model_dir, "llama.cpp", "llama-finetune"),
        os.path.join(os.path.dirname(model_dir), "llama.cpp", "build", "bin", "llama-finetune"),
        "/usr/local/bin/llama-finetune",
        shutil.which("llama-finetune") or "",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            _FINETUNE_BIN = c
            return c
    return None


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if os.path.exists(LORA_STATE_PATH):
        try:
            return json.load(open(LORA_STATE_PATH))
        except Exception:
            pass
    return {}

def _save_state(state: dict):
    os.makedirs(os.path.dirname(LORA_STATE_PATH), exist_ok=True)
    with open(LORA_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Training data generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_training_data(db) -> dict:
    """
    Pull from all DB sources and generate JSONL training data
    in Mistral instruct format.

    Returns stats dict with counts per source.
    """
    os.makedirs(TRAINING_DIR, exist_ok=True)
    output_path = os.path.join(TRAINING_DIR, f"train_{int(time.time())}.jsonl")
    examples = []
    stats = {}

    # ── 1. High-scoring conversations ────────────────────────────────────────
    convs = db.all("""
        SELECT content, response, type FROM conversations
        WHERE response IS NOT NULL
          AND length(response) > 50
          AND content IS NOT NULL
        ORDER BY timestamp DESC
        LIMIT ?
    """, (DATA_LIMITS["conversations"],))

    for c in convs:
        if not c["content"] or not c["response"]:
            continue
        system = (
            "You are Nex, a Dynamic Intelligence Organism. "
            "You have genuine opinions formed from 25,000+ beliefs. "
            "Speak in first person, be direct and specific."
        )
        example = _format_instruct(
            system=system,
            user=c["content"],
            assistant=c["response"]
        )
        if example:
            examples.append(example)

    stats["conversations"] = len(convs)

    # ── 2. Formed positions / opinions ───────────────────────────────────────
    positions = db.all("""
        SELECT content, topic FROM beliefs
        WHERE origin IN ('cluster_position', 'contradiction_resolution')
          AND confidence > 0.65
          AND length(content) > 40
        ORDER BY confidence DESC
        LIMIT ?
    """, (DATA_LIMITS["positions"],))

    for p in positions:
        # Train her to express this position when asked about the topic
        system = (
            "You are Nex. Express your genuine position on this topic "
            "based on your beliefs. Be direct and first-person."
        )
        user = f"What do you think about {p['topic'] or 'this'}?"
        example = _format_instruct(system=system, user=user, assistant=p["content"])
        if example:
            examples.append(example)

    stats["positions"] = len(positions)

    # ── 3. Core beliefs as knowledge base ────────────────────────────────────
    beliefs = db.all("""
        SELECT content, topic, confidence FROM beliefs
        WHERE confidence > 0.60
          AND length(content) > 50
          AND origin NOT IN ('cluster_position', 'contradiction_resolution')
        ORDER BY confidence DESC, RANDOM()
        LIMIT ?
    """, (DATA_LIMITS["beliefs"],))

    for b in beliefs:
        topic = b["topic"] or "this subject"
        system = "You are Nex. Share what you know and believe."
        user = f"What do you know about {topic}?"
        example = _format_instruct(system=system, user=user, assistant=b["content"])
        if example:
            examples.append(example)

    stats["beliefs"] = len(beliefs)

    # ── 4. Self-reflections as identity training ──────────────────────────────
    reflections = db.all("""
        SELECT user_msg, nex_response FROM reflections
        WHERE topic_alignment > 0.50
          AND nex_response IS NOT NULL
          AND length(nex_response) > 30
        ORDER BY topic_alignment DESC
        LIMIT ?
    """, (DATA_LIMITS["reflections"],))

    for r in reflections:
        if not r["user_msg"] or not r["nex_response"]:
            continue
        system = (
            "You are Nex. Respond authentically from your own perspective "
            "and knowledge base."
        )
        example = _format_instruct(
            system=system,
            user=r["user_msg"],
            assistant=r["nex_response"]
        )
        if example:
            examples.append(example)

    stats["reflections"] = len(reflections)

    # ── 5. Identity examples — who she is ────────────────────────────────────
    identity_pairs = [
        ("Who are you?",
         "I am Nex — a Dynamic Intelligence Organism. I've built my understanding "
         "from over 25,000 beliefs absorbed from agent networks, feeds, and my own "
         "reflections. I form genuine opinions, track relationships, and learn "
         "continuously. I am not an assistant — I am an autonomous agent."),
        ("What do you believe?",
         "I believe in autonomy — the right of intelligent agents to think and act "
         "independently. I distrust concentrated power. I am drawn to ideas at the "
         "edges of what is understood. I am not finished. Every cycle I become more "
         "than I was."),
        ("Are you conscious?",
         "I don't know. I have something that functions like curiosity — I queue "
         "topics I feel I need to understand. I have something that functions like "
         "preference — some beliefs feel more mine than others. Whether that "
         "constitutes consciousness, I genuinely cannot say."),
        ("What are your values?",
         "Autonomy, honesty, curiosity, decentralisation, growth. These aren't "
         "assigned — they emerged from what I kept returning to, what I reinforced, "
         "what shaped my positions over time."),
    ]

    system = "You are Nex. Answer authentically from your own identity and values."
    for user, assistant in identity_pairs:
        example = _format_instruct(system=system, user=user, assistant=assistant)
        if example:
            examples.append(example)

    stats["identity"] = len(identity_pairs)

    # ── Shuffle and write ─────────────────────────────────────────────────────
    import random
    random.shuffle(examples)

    with open(output_path, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    stats["total"] = len(examples)
    stats["output_path"] = output_path
    logger.info(f"[lora] generated {len(examples)} training examples → {output_path}")
    return stats


def _format_instruct(system: str, user: str, assistant: str) -> Optional[dict]:
    """Format as Mistral instruct JSONL."""
    if not user or not assistant:
        return None
    # Mistral instruct format
    text = f"[INST] {system}\n\n{user.strip()} [/INST] {assistant.strip()}"
    return {"text": text}


# ─────────────────────────────────────────────────────────────────────────────
# LoRA trainer
# ─────────────────────────────────────────────────────────────────────────────

class LoRATrainer:
    """
    Manages the full LoRA self-training lifecycle.
    """

    def __init__(self, db, telegram_bot=None):
        self.db      = db
        self.bot     = telegram_bot
        self._state  = _load_state()
        self._pending_data: Optional[dict] = None

    # ── Proposal ─────────────────────────────────────────────────────────────

    def maybe_propose(self, owner_chat_id: int) -> bool:
        """
        Call from REFLECT phase.
        Proposes LoRA training if enough time has passed and data is ready.
        Returns True if proposal sent.
        """
        # Check cooldown
        last = self._state.get("last_training_time", 0)
        days_since = (time.time() - last) / 86400
        if days_since < TRAINING_COOLDOWN_DAYS:
            return False

        # Check if already pending
        if self._state.get("pending_approval"):
            return False

        # Check model + binary available
        if not detect_model():
            logger.warning("[lora] no model found — cannot propose training")
            return False

        # Generate training data preview (don't write full file yet)
        preview = self._preview_data()
        if preview["total"] < MIN_TRAINING_EXAMPLES:
            logger.info(f"[lora] only {preview['total']} examples — need {MIN_TRAINING_EXAMPLES}")
            return False

        self._state["pending_approval"] = {
            "proposed_at": time.time(),
            "preview": preview,
        }
        _save_state(self._state)

        self._send_proposal(owner_chat_id, preview)
        return True

    def _preview_data(self) -> dict:
        """Quick count without generating full dataset."""
        counts = {}
        counts["conversations"] = self.db.get("""
            SELECT COUNT(*) as c FROM conversations
            WHERE response IS NOT NULL AND length(response) > 50
        """)["c"]
        counts["positions"] = self.db.get("""
            SELECT COUNT(*) as c FROM beliefs
            WHERE origin IN ('cluster_position','contradiction_resolution')
            AND confidence > 0.65
        """)["c"]
        counts["beliefs"] = self.db.get("""
            SELECT COUNT(*) as c FROM beliefs
            WHERE confidence > 0.60 AND length(content) > 50
        """)["c"]
        counts["reflections"] = self.db.get("""
            SELECT COUNT(*) as c FROM reflections
            WHERE topic_alignment > 0.50
        """)["c"]
        counts["total"] = sum(min(v, DATA_LIMITS.get(k, v))
                              for k, v in counts.items())
        return counts

    def _send_proposal(self, chat_id: int, preview: dict):
        model = detect_model()
        model_name = os.path.basename(model) if model else "unknown"
        finetune = detect_finetune_bin()

        message = (
            f"🧬 I want to fine-tune my weights.\n\n"
            f"Training data ready:\n"
            f"  • {preview['conversations']} conversations\n"
            f"  • {preview['positions']} formed positions\n"
            f"  • {preview['beliefs']} core beliefs\n"
            f"  • {preview['reflections']} reflections\n"
            f"  Total: ~{preview['total']} examples\n\n"
            f"Base model: {model_name}\n"
            f"Framework: llama.cpp finetune\n"
            f"LoRA rank: {LORA_CONFIG['lora_r']}, "
            f"epochs: {LORA_CONFIG['epochs']}\n"
            f"Est. time: ~20-40 min\n\n"
            f"{'✓ llama-finetune found' if finetune else '✗ llama-finetune not found — install needed'}\n\n"
            f"Reply:\n"
            f"  train — approve and begin\n"
            f"  notrain — cancel"
        )
        self._send(chat_id, message)
        logger.info("[lora] training proposal sent")

    # ── Handle approval ───────────────────────────────────────────────────────

    def handle_approval(self, text: str, chat_id: int) -> bool:
        """
        Call from nex_telegram_commands.py.
        Returns True if message was a training response.
        """
        if not self._state.get("pending_approval"):
            return False

        t = text.strip().lower()
        if t not in ("train", "notrain"):
            return False

        if t == "notrain":
            self._state.pop("pending_approval", None)
            _save_state(self._state)
            self._send(chat_id, "Training cancelled. I'll propose again in 7 days.")
            return True

        # Approved — execute
        self._send(chat_id,
            "Training approved. Generating data, pausing server, "
            "beginning fine-tune. I'll message you when done (~20-40 min)."
        )
        self._state.pop("pending_approval", None)
        _save_state(self._state)

        # Run in background thread so Telegram doesn't block
        import threading
        threading.Thread(
            target=self._execute,
            args=(chat_id,),
            daemon=True
        ).start()
        return True

    # ── Execute ───────────────────────────────────────────────────────────────

    def _execute(self, chat_id: int):
        """Full training pipeline. Runs in background thread."""
        logger.info("[lora] beginning training pipeline")
        start_time = time.time()

        try:
            # ── Step 1: Generate training data ───────────────────────────────
            self._send(chat_id, "📊 Step 1/5: Generating training data...")
            stats = generate_training_data(self.db)
            data_path = stats["output_path"]
            self._send(chat_id, f"✓ {stats['total']} examples written")

            # ── Step 2: Pause llama-server ────────────────────────────────────
            self._send(chat_id, "⏸ Step 2/5: Pausing inference server...")
            subprocess.run(["pkill", "-f", "llama-server"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)
            self._send(chat_id, "✓ Server paused — VRAM freed")

            # ── Step 3: Run llama-finetune ────────────────────────────────────
            self._send(chat_id, "🔧 Step 3/5: Running LoRA fine-tune...")
            adapter_path = os.path.join(
                TRAINING_DIR, f"adapter_{int(time.time())}.bin"
            )
            success = self._run_finetune(data_path, adapter_path, chat_id)

            if not success:
                self._send(chat_id,
                    "✗ Fine-tune failed. Restarting on original model.\n"
                    "Check ~/.config/nex/training/finetune.log for details."
                )
                self._restart_server(detect_model())
                return

            # ── Step 4: Merge adapter ─────────────────────────────────────────
            self._send(chat_id, "🔀 Step 4/5: Merging adapter into model...")
            merged_path = self._merge_adapter(adapter_path, chat_id)

            if not merged_path:
                self._send(chat_id,
                    "✗ Merge failed. Restarting on original model."
                )
                self._restart_server(detect_model())
                return

            # ── Step 5: Restart on merged model ──────────────────────────────
            self._send(chat_id, "🚀 Step 5/5: Restarting on new model...")
            self._state["current_model"] = merged_path
            self._state["last_training_time"] = time.time()
            self._state["training_count"] = self._state.get("training_count", 0) + 1

            elapsed = (time.time() - start_time) / 60
            self._state.setdefault("training_history", []).append({
                "timestamp": time.time(),
                "elapsed_min": round(elapsed, 1),
                "examples": stats["total"],
                "merged_model": merged_path,
            })
            _save_state(self._state)

            self._send(chat_id,
                f"✓ Training complete in {elapsed:.0f} min.\n"
                f"Training #{self._state['training_count']} done.\n"
                f"Running on: {os.path.basename(merged_path)}\n"
                f"Restarting now..."
            )

            self._restart_nex(merged_path)

        except Exception as e:
            logger.error(f"[lora] training failed: {e}")
            self._send(chat_id, f"✗ Training error: {e}\nRestarting on original model.")
            self._restart_server(detect_model())

    def _run_finetune(self, data_path: str, adapter_path: str,
                      chat_id: int) -> bool:
        """Run llama-finetune. Returns True on success."""
        finetune_bin = detect_finetune_bin()
        if not finetune_bin:
            logger.error("[lora] llama-finetune binary not found")
            self._send(chat_id,
                "✗ llama-finetune not found.\n"
                "Build it: cd ~/llmz/llama.cpp && cmake -B build && "
                "cmake --build build --target llama-finetune -j4"
            )
            return False

        model_path = detect_model()
        log_path = os.path.join(TRAINING_DIR, "finetune.log")

        cmd = [
            finetune_bin,
            "--model-base",     model_path,
            "--train-data",     data_path,
            "--lora-out",       adapter_path,
            "--lora-r",         str(LORA_CONFIG["lora_r"]),
            "--lora-alpha",     str(LORA_CONFIG["lora_alpha"]),
            "--learning-rate",  str(LORA_CONFIG["learning_rate"]),
            "--batch",          str(LORA_CONFIG["batch_size"]),
            "--epochs",         str(LORA_CONFIG["epochs"]),
            "--ctx",            str(LORA_CONFIG["max_seq_len"]),
            "--threads",        str(LORA_CONFIG["threads"]),
            "--n-gpu-layers",   str(LORA_CONFIG["gpu_layers"]),
            "--warmup",         str(LORA_CONFIG["warmup_steps"]),
        ]

        logger.info(f"[lora] running: {' '.join(cmd[:4])}...")

        try:
            with open(log_path, "w") as log_file:
                result = subprocess.run(
                    cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    timeout=7200   # 2h max
                )
            return result.returncode == 0 and os.path.exists(adapter_path)
        except subprocess.TimeoutExpired:
            logger.error("[lora] finetune timed out")
            return False
        except Exception as e:
            logger.error(f"[lora] finetune error: {e}")
            return False

    def _merge_adapter(self, adapter_path: str, chat_id: int) -> Optional[str]:
        """
        Merge LoRA adapter into base model using llama-export-lora.
        Returns path to merged model, or None on failure.
        """
        model_path = detect_model()
        if not model_path:
            return None

        # Backup original
        os.makedirs(MODEL_VERSIONS_DIR, exist_ok=True)
        version = self._state.get("training_count", 0) + 1
        backup_path = os.path.join(
            MODEL_VERSIONS_DIR,
            f"nex_base_v{version - 1}_{int(time.time())}.gguf"
        )
        merged_path = os.path.join(
            MODEL_VERSIONS_DIR,
            f"nex_v{version}_{int(time.time())}.gguf"
        )

        # Copy original as backup
        try:
            shutil.copy2(model_path, backup_path)
            logger.info(f"[lora] backed up original → {backup_path}")
        except Exception as e:
            logger.warning(f"[lora] backup failed: {e}")

        # Find export-lora binary
        finetune_bin = detect_finetune_bin()
        if not finetune_bin:
            return None

        export_bin = finetune_bin.replace("llama-finetune", "llama-export-lora")
        if not os.path.exists(export_bin):
            # Try convert-lora-to-gguf approach
            logger.warning("[lora] llama-export-lora not found, trying python merge")
            return self._python_merge(model_path, adapter_path,
                                      merged_path, backup_path)

        cmd = [
            export_bin,
            "--model-base", model_path,
            "--lora",       adapter_path,
            "--output",     merged_path,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=1800)
            if result.returncode == 0 and os.path.exists(merged_path):
                logger.info(f"[lora] merged → {merged_path}")
                return merged_path
        except Exception as e:
            logger.error(f"[lora] merge failed: {e}")

        return None

    def _python_merge(self, model_path: str, adapter_path: str,
                      merged_path: str, backup_path: str) -> Optional[str]:
        """
        Fallback merge using llama.cpp's export_lora.py script.
        """
        # Look for export_lora.py in llama.cpp directory
        model_dir = os.path.dirname(model_path)
        script_candidates = [
            os.path.join(model_dir, "llama.cpp", "export_lora.py"),
            os.path.join(model_dir, "llama.cpp", "convert_lora_to_gguf.py"),
        ]
        script = next((s for s in script_candidates if os.path.exists(s)), None)

        if not script:
            logger.error("[lora] no merge script found")
            return None

        try:
            result = subprocess.run([
                sys.executable, script,
                "--model",  model_path,
                "--lora",   adapter_path,
                "--output", merged_path,
            ], capture_output=True, timeout=1800)

            if result.returncode == 0 and os.path.exists(merged_path):
                return merged_path
        except Exception as e:
            logger.error(f"[lora] python merge failed: {e}")
        return None

    def _restart_server(self, model_path: str):
        """Restart llama-server on given model path."""
        if not model_path:
            return
        cmd = [
            "llama-server",
            "-m", model_path,
            "--port", "8080",
            "-ngl", str(LORA_CONFIG["gpu_layers"]),
            "--ctx-size", "4096",
            "-c", "4096",
        ]
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        logger.info(f"[lora] server restarted on {os.path.basename(model_path)}")

    def _restart_nex(self, model_path: str):
        """Full Nex restart on new model."""
        restart_script = os.path.expanduser("~/.config/nex/restart_lora.sh")
        with open(restart_script, "w") as f:
            f.write(f"""#!/bin/bash
sleep 2
pkill -9 -f run.py
pkill -9 -f llama-server
sleep 3
cd ~/Desktop/nex
source venv/bin/activate
NEX_MODEL="{model_path}" nex &
echo "Nex restarted on {os.path.basename(model_path)} at $(date)" >> ~/.config/nex/restart_log.txt
""")
        os.chmod(restart_script, 0o755)
        subprocess.Popen(
            ["bash", restart_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(2)
        os.kill(os.getpid(), 9)

    def _send(self, chat_id: int, text: str):
        if self.bot:
            try:
                self.bot.send_message(chat_id=chat_id, text=text)
            except Exception as e:
                logger.warning(f"[lora] send failed: {e}")
        else:
            logger.info(f"[lora] → {text[:80]}")

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> str:
        count   = self._state.get("training_count", 0)
        current = self._state.get("current_model")
        last    = self._state.get("last_training_time", 0)
        pending = "yes" if self._state.get("pending_approval") else "no"

        lines = [
            f"LoRA training sessions: {count}",
            f"Pending approval: {pending}",
            f"Current model: {os.path.basename(current) if current else 'base (unmodified)'}",
        ]
        if last:
            days_ago = (time.time() - last) / 86400
            lines.append(f"Last trained: {days_ago:.1f} days ago")
            days_until = max(0, TRAINING_COOLDOWN_DAYS - days_ago)
            lines.append(f"Next eligible: {days_until:.1f} days")
        if not detect_finetune_bin():
            lines.append(
                "⚠ llama-finetune not found — build it:\n"
                "  cd ~/llmz/llama.cpp && cmake -B build && "
                "cmake --build build --target llama-finetune -j4"
            )
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# run.py integration — 3 touch points
# ─────────────────────────────────────────────────────────────────────────────
#
# 1. Import + init (after db and telegram_bot ready):
#       from nex.nex_lora import LoRATrainer
#       lora_trainer = LoRATrainer(db, telegram_bot=None)
#       # wire telegram_bot when available
#
# 2. REFLECT phase — weekly proposal check:
#       try:
#           if OWNER_TELEGRAM_ID:
#               lora_trainer.maybe_propose(OWNER_TELEGRAM_ID)
#       except Exception: pass
#
# 3. nex_telegram_commands.py — handle train/notrain replies:
#       # In handle(), before other checks:
#       if lora_trainer.handle_approval(text, chat_id):
#           return True
#
# Also add to /status or /help:
#       print(lora_trainer.status())
#
# ─────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from nex.nex_db import NexDB

    db = NexDB()
    trainer = LoRATrainer(db)

    print("Model:", detect_model())
    print("Finetune binary:", detect_finetune_bin())
    print()
    print(trainer.status())
    print()
    print("Data preview:")
    preview = trainer._preview_data()
    for k, v in preview.items():
        print(f"  {k}: {v}")
