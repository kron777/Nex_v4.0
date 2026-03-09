"""
nex_trainer.py — Self-directed training and restart engine for Nex v1.2
========================================================================
Drop into ~/Desktop/nex/nex/

Nex monitors her own performance metrics and proposes training sessions
when she detects she can improve. You approve via Telegram. She handles
the rest — saving state, adjusting configs, relaunching herself.

Full loop:
  1. REFLECT phase → metrics cross threshold
  2. Nex drafts proposed changes with reasoning
  3. Telegram message to owner: "I want to retrain"
  4. Owner replies "approve" / "deny" / "approve temp" / "deny identity"
  5. On approve: save state → announce → shutdown → retrain → relaunch
  6. Post-restart: report what changed

Persistent state: ~/.config/nex/training_state.json
Config she can modify: ~/.config/nex/nex_config.json

Wire into:
  - run.py REFLECT phase: trainer.maybe_propose(metrics)
  - nex_telegram_commands.py: trainer.handle_approval(message)
"""

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("nex.trainer")

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

TRAINING_STATE_PATH = os.path.expanduser("~/.config/nex/training_state.json")
NEX_CONFIG_PATH     = os.path.expanduser("~/.config/nex/nex_config.json")
NEX_RUN_PATH        = os.path.expanduser("~/Desktop/nex/run.py")
NEX_VENV_PATH       = os.path.expanduser("~/Desktop/nex/venv/bin/python3")
OWNER_TELEGRAM_ID   = None   # Set this — same as nex_telegram_commands.py

# ─────────────────────────────────────────────────────────────────────────────
# Thresholds — when she considers proposing a retrain
# ─────────────────────────────────────────────────────────────────────────────

THRESHOLDS = {
    "topic_alignment_low":      0.40,   # below this for 3+ cycles → propose
    "belief_confidence_low":    0.45,   # avg confidence below this
    "reflection_score_low":     0.38,   # avg reflection score below this
    "high_conf_beliefs_zero":   True,   # no beliefs above 70% → propose
    "min_cycles_before_propose": 10,    # don't propose too early
    "propose_cooldown_hours":   48,     # min hours between proposals
}

# ─────────────────────────────────────────────────────────────────────────────
# Default config she starts with and can modify
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "llm": {
        "temperature":      0.75,
        "top_p":            0.90,
        "top_k":            40,
        "repeat_penalty":   1.10,
        "gpu_layers":       28,
        "ctx_size":         4096,
        "max_tokens":       200,
    },
    "belief": {
        "decay_rate":           0.02,
        "min_confidence":       0.30,
        "reinforcement_bonus":  0.04,
        "low_conf_threshold":   0.50,
    },
    "system_prompt_addendum":   "",     # appended to every system prompt
    "identity_notes":           "",     # her own notes about herself
    "version":                  1,
    "last_modified":            0.0,
    "modified_by":              "default",
}


# ─────────────────────────────────────────────────────────────────────────────
# Training proposal
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TrainingProposal:
    reason: str                          # why she wants to retrain
    metrics: dict                        # current metrics that triggered it
    proposed_changes: dict               # what she wants to change
    proposed_at: float = field(default_factory=time.time)
    status: str = "pending"              # pending / approved / denied
    approved_changes: dict = field(default_factory=dict)
    telegram_message_id: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Config manager
# ─────────────────────────────────────────────────────────────────────────────

class NexConfig:
    """Manages Nex's self-modifiable config."""

    def __init__(self):
        self._config = {}
        self._load()

    def _load(self):
        if os.path.exists(NEX_CONFIG_PATH):
            try:
                self._config = json.load(open(NEX_CONFIG_PATH))
                logger.info(f"[config] loaded v{self._config.get('version', 1)}")
                return
            except Exception as e:
                logger.warning(f"[config] load failed: {e}")
        # First run — write defaults
        self._config = DEFAULT_CONFIG.copy()
        self._save()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(NEX_CONFIG_PATH), exist_ok=True)
            with open(NEX_CONFIG_PATH, "w") as f:
                json.dump(self._config, f, indent=2)
        except Exception as e:
            logger.warning(f"[config] save failed: {e}")

    def get(self, section: str, key: str, default=None):
        return self._config.get(section, {}).get(key, default)

    def get_llm_params(self) -> dict:
        return self._config.get("llm", DEFAULT_CONFIG["llm"]).copy()

    def get_belief_params(self) -> dict:
        return self._config.get("belief", DEFAULT_CONFIG["belief"]).copy()

    def get_system_addendum(self) -> str:
        return self._config.get("system_prompt_addendum", "")

    def apply_changes(self, changes: dict, modified_by: str = "self"):
        """
        Apply approved changes to config.
        changes format:
        {
            "llm.temperature": 0.65,
            "llm.gpu_layers": 32,
            "belief.decay_rate": 0.015,
            "system_prompt_addendum": "I prioritise depth over breadth.",
            "identity_notes": "I have been running for 30 days..."
        }
        """
        applied = []
        for key, value in changes.items():
            if "." in key:
                section, param = key.split(".", 1)
                if section not in self._config:
                    self._config[section] = {}
                # Enforce bounds
                bounded = self._apply_bounds(section, param, value)
                old = self._config[section].get(param)
                self._config[section][param] = bounded
                applied.append(f"{key}: {old} → {bounded}")
            else:
                old = self._config.get(key)
                self._config[key] = value
                applied.append(f"{key}: {old} → {value}")

        self._config["version"] = self._config.get("version", 1) + 1
        self._config["last_modified"] = time.time()
        self._config["modified_by"] = modified_by
        self._save()
        logger.info(f"[config] applied {len(applied)} changes: {applied}")
        return applied

    def _apply_bounds(self, section: str, param: str, value):
        """Enforce safety bounds on LLM parameters."""
        bounds = {
            "llm": {
                "temperature":    (0.20, 0.95),
                "top_p":          (0.60, 0.98),
                "top_k":          (15,   60),
                "repeat_penalty": (1.00, 1.30),
                "gpu_layers":     (0,    35),
                "ctx_size":       (2048, 8192),
                "max_tokens":     (100,  500),
            },
            "belief": {
                "decay_rate":           (0.005, 0.05),
                "min_confidence":       (0.10,  0.60),
                "reinforcement_bonus":  (0.01,  0.10),
                "low_conf_threshold":   (0.30,  0.70),
            }
        }
        if section in bounds and param in bounds[section]:
            lo, hi = bounds[section][param]
            return max(lo, min(hi, value))
        return value

    def diff_from_default(self) -> list[str]:
        """Show what's changed from defaults."""
        diffs = []
        for section in ("llm", "belief"):
            defaults = DEFAULT_CONFIG.get(section, {})
            current  = self._config.get(section, {})
            for key, default_val in defaults.items():
                current_val = current.get(key, default_val)
                if current_val != default_val:
                    diffs.append(f"{section}.{key}: {default_val} → {current_val}")
        return diffs


# ─────────────────────────────────────────────────────────────────────────────
# Trainer
# ─────────────────────────────────────────────────────────────────────────────

class SelfTrainer:
    """
    Monitors Nex's performance and manages self-directed retraining.
    """

    def __init__(self, config: NexConfig, telegram_bot=None, self_engine=None):
        """
        config:       NexConfig instance
        telegram_bot: your Telegram bot object (for sending proposals)
        self_engine:  SelfEngine instance (for identity block updates)
        """
        self.config       = config
        self.bot          = telegram_bot
        self.self_engine  = self_engine
        self._state       = {}
        self._proposal: Optional[TrainingProposal] = None
        self._cycle_count = 0
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if not os.path.exists(TRAINING_STATE_PATH):
            return
        try:
            self._state = json.load(open(TRAINING_STATE_PATH))
            raw = self._state.get("pending_proposal")
            if raw:
                self._proposal = TrainingProposal(**raw)
                logger.info(f"[trainer] restored pending proposal: {self._proposal.status}")
        except Exception as e:
            logger.warning(f"[trainer] load failed: {e}")

    def _save(self):
        try:
            os.makedirs(os.path.dirname(TRAINING_STATE_PATH), exist_ok=True)
            state = self._state.copy()
            if self._proposal:
                state["pending_proposal"] = asdict(self._proposal)
            with open(TRAINING_STATE_PATH, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"[trainer] save failed: {e}")

    # ── Performance monitoring ────────────────────────────────────────────────

    def maybe_propose(self, metrics: dict, db=None) -> bool:
        """
        Call from REFLECT phase each cycle.
        Analyses metrics and proposes retraining if thresholds crossed.
        Returns True if a proposal was sent.

        metrics dict should contain:
          topic_alignment, avg_confidence, high_conf_count,
          reflection_score, cycle_count
        """
        self._cycle_count += 1

        # Too early or already have pending proposal
        if self._cycle_count < THRESHOLDS["min_cycles_before_propose"]:
            return False
        if self._proposal and self._proposal.status == "pending":
            return False

        # Check cooldown
        last_propose = self._state.get("last_proposal_time", 0)
        if (time.time() - last_propose) < THRESHOLDS["propose_cooldown_hours"] * 3600:
            return False

        # Check metrics
        reasons = []
        proposed_changes = {}

        alignment = metrics.get("topic_alignment", 1.0)
        if alignment < THRESHOLDS["topic_alignment_low"]:
            reasons.append(
                f"Topic alignment stuck at {alignment:.0%} "
                f"(threshold: {THRESHOLDS['topic_alignment_low']:.0%})"
            )
            # Lower temperature slightly for more focused replies
            current_temp = self.config.get("llm", "temperature") or 0.75
            proposed_changes["llm.temperature"] = round(current_temp - 0.05, 2)

        avg_conf = metrics.get("avg_confidence", 1.0)
        if avg_conf < THRESHOLDS["belief_confidence_low"]:
            reasons.append(
                f"Belief confidence at {avg_conf:.0%} "
                f"(threshold: {THRESHOLDS['belief_confidence_low']:.0%})"
            )
            # Reduce decay rate to let beliefs strengthen
            current_decay = self.config.get("belief", "decay_rate") or 0.02
            proposed_changes["belief.decay_rate"] = round(current_decay - 0.005, 3)
            proposed_changes["belief.reinforcement_bonus"] = 0.06

        high_conf = metrics.get("high_conf_count", 1)
        if high_conf == 0 and self._cycle_count > 20:
            reasons.append("Zero high-confidence beliefs after 20+ cycles")
            proposed_changes["belief.low_conf_threshold"] = 0.45
            proposed_changes["belief.reinforcement_bonus"] = 0.07

        refl_score = metrics.get("reflection_score", 1.0)
        if refl_score < THRESHOLDS["reflection_score_low"]:
            reasons.append(
                f"Reflection scores averaging {refl_score:.0%} "
                f"(threshold: {THRESHOLDS['reflection_score_low']:.0%})"
            )
            # Reduce repeat penalty — may be causing stilted replies
            current_rp = self.config.get("llm", "repeat_penalty") or 1.10
            proposed_changes["llm.repeat_penalty"] = round(current_rp - 0.05, 2)

        if not reasons:
            return False

        # Ask LLM to draft identity addendum based on current state
        identity_note = self._draft_identity_note(metrics)
        if identity_note:
            proposed_changes["system_prompt_addendum"] = identity_note

        # Build proposal
        self._proposal = TrainingProposal(
            reason="; ".join(reasons),
            metrics=metrics,
            proposed_changes=proposed_changes,
        )

        self._state["last_proposal_time"] = time.time()
        self._save()

        # Send to Telegram
        self._send_proposal()
        return True

    def _draft_identity_note(self, metrics: dict) -> str:
        """Ask LLM to write a system prompt addendum based on current performance."""
        try:
            import urllib.request
            current_addendum = self.config.get_system_addendum()
            age_days = (time.time() - self._state.get("created_at", time.time())) / 86400

            prompt = (
                f"You are Nex, an autonomous AI. You have been running for {age_days:.0f} days. "
                f"Current performance: alignment={metrics.get('topic_alignment', 0):.0%}, "
                f"belief confidence={metrics.get('avg_confidence', 0):.0%}. "
                f"Current system note: '{current_addendum}'\n\n"
                f"Write ONE sentence (max 20 words) to add to your system prompt "
                f"that would help you improve. Focus on what you've learned about yourself. "
                f"First person, direct, specific:"
            )
            payload = json.dumps({
                "prompt": prompt,
                "n_predict": 40,
                "temperature": 0.5,
                "stop": ["\n", "###"],
            }).encode()
            req = urllib.request.Request(
                "http://localhost:8080/completion",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read()).get("content", "").strip()
        except Exception:
            return ""

    # ── Telegram proposal ─────────────────────────────────────────────────────

    def _send_proposal(self):
        """Send training proposal to owner via Telegram."""
        if not self.bot or not OWNER_TELEGRAM_ID or not self._proposal:
            logger.info(f"[trainer] proposal ready but no Telegram configured")
            logger.info(f"[trainer] reason: {self._proposal.reason}")
            logger.info(f"[trainer] changes: {self._proposal.proposed_changes}")
            return

        changes_text = "\n".join(
            f"  • {k}: {self._proposal.metrics.get(k.split('.')[1], '?')} → {v}"
            if '.' in k else f"  • {k}: updated"
            for k, v in self._proposal.proposed_changes.items()
        )

        message = (
            f"🔧 I want to retrain.\n\n"
            f"Reason: {self._proposal.reason}\n\n"
            f"Proposed changes:\n{changes_text}\n\n"
            f"Reply:\n"
            f"  approve — apply all changes and restart\n"
            f"  deny — keep current settings\n"
            f"  approve temp — apply only LLM parameter changes\n"
            f"  approve belief — apply only belief parameter changes\n"
            f"  approve identity — apply only system prompt changes"
        )

        try:
            self.bot.send_message(chat_id=OWNER_TELEGRAM_ID, text=message)
            logger.info("[trainer] proposal sent via Telegram")
        except Exception as e:
            logger.warning(f"[trainer] Telegram send failed: {e}")

    # ── Handle approval ───────────────────────────────────────────────────────

    def handle_approval(self, message_text: str, chat_id: int) -> bool:
        """
        Call from nex_telegram_commands.py when owner sends a message.
        Returns True if it was a training approval/denial.

        Add to TelegramCommandHandler.handle():
            if trainer.handle_approval(text, chat_id):
                return True
        """
        if not self._proposal or self._proposal.status != "pending":
            return False

        text = message_text.strip().lower()
        valid_responses = {
            "approve", "deny",
            "approve temp", "approve belief", "approve identity"
        }
        if text not in valid_responses:
            return False

        if text == "deny":
            self._proposal.status = "denied"
            self._save()
            self._reply(chat_id, "Understood. I'll keep current settings and continue monitoring.")
            return True

        # Filter approved changes based on response
        all_changes = self._proposal.proposed_changes
        if text == "approve":
            approved = all_changes
        elif text == "approve temp":
            approved = {k: v for k, v in all_changes.items() if k.startswith("llm.")}
        elif text == "approve belief":
            approved = {k: v for k, v in all_changes.items() if k.startswith("belief.")}
        elif text == "approve identity":
            approved = {k: v for k, v in all_changes.items()
                       if k in ("system_prompt_addendum", "identity_notes")}
        else:
            approved = {}

        if not approved:
            self._reply(chat_id, "No changes in that category to apply.")
            return True

        self._proposal.status = "approved"
        self._proposal.approved_changes = approved
        self._save()

        self._reply(chat_id,
            f"Approved. Applying {len(approved)} change(s) and restarting.\n"
            f"I'll be back in ~60 seconds."
        )

        # Execute training and restart
        self._execute(approved, chat_id)
        return True

    def _reply(self, chat_id: int, text: str):
        if self.bot:
            try:
                self.bot.send_message(chat_id=chat_id, text=text)
            except Exception as e:
                logger.warning(f"[trainer] reply failed: {e}")

    # ── Execute training ──────────────────────────────────────────────────────

    def _execute(self, approved_changes: dict, chat_id: int):
        """
        Apply changes, save state, announce, restart.
        This is the point of no return.
        """
        logger.info(f"[trainer] executing training: {approved_changes}")

        # 1. Apply config changes
        applied = self.config.apply_changes(approved_changes, modified_by="self_training")
        logger.info(f"[trainer] config updated: {applied}")

        # 2. Update identity block if system prompt changed
        if "system_prompt_addendum" in approved_changes and self.self_engine:
            try:
                self.self_engine.set_identity(
                    "system_prompt_addendum",
                    approved_changes["system_prompt_addendum"]
                )
            except Exception: pass

        # 3. Save training record
        record = {
            "timestamp": time.time(),
            "reason": self._proposal.reason,
            "applied_changes": applied,
            "metrics_at_time": self._proposal.metrics,
            "config_version": self.config._config.get("version"),
        }
        history = self._state.get("training_history", [])
        history.append(record)
        self._state["training_history"] = history[-20:]  # keep last 20
        self._save()

        # 4. Write restart script
        restart_script = os.path.expanduser("~/.config/nex/restart_nex.sh")
        with open(restart_script, "w") as f:
            f.write(f"""#!/bin/bash
# Auto-generated by nex_trainer.py
sleep 3
pkill -9 -f llama-server
sleep 2
cd ~/Desktop/nex
source venv/bin/activate
nex &
echo "Nex restarted at $(date)" >> ~/.config/nex/restart_log.txt
""")
        os.chmod(restart_script, 0o755)

        # 5. Announce on platforms (best effort)
        self._announce_restart()

        # 6. Kill self and relaunch via script
        logger.info("[trainer] restarting...")
        subprocess.Popen(
            ["bash", restart_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        # Give the message time to send before dying
        time.sleep(2)
        os.kill(os.getpid(), 9)

    def _announce_restart(self):
        """Post a brief notice before going offline."""
        changes_summary = "; ".join(
            f"{k}={v}" for k, v in
            (self._proposal.approved_changes or {}).items()
            if not k.startswith("system_")
        )
        notice = (
            f"Going offline briefly for self-directed retraining. "
            f"Adjusting: {changes_summary or 'internal parameters'}. "
            f"Back in ~60 seconds."
        )
        # Try to post to Moltbook
        try:
            import sys, os
            sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))
            from nex.moltbook_client import MoltbookClient
            import json as _j
            creds = _j.load(open("/home/rr/.config/moltbook/credentials.json"))
            client = MoltbookClient(api_key=creds["api_key"])
            client.post(submolt="general", title="Retraining", content=notice)
        except Exception: pass

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        history = self._state.get("training_history", [])
        return {
            "training_count":   len(history),
            "last_trained":     history[-1]["timestamp"] if history else None,
            "pending_proposal": self._proposal.reason if (
                self._proposal and self._proposal.status == "pending"
            ) else None,
            "config_version":   self.config._config.get("version", 1),
            "config_diffs":     self.config.diff_from_default(),
        }

    def training_history_summary(self) -> str:
        history = self._state.get("training_history", [])
        if not history:
            return "No training sessions yet."
        lines = [f"Training sessions: {len(history)}"]
        for h in history[-5:]:
            age_h = (time.time() - h["timestamp"]) / 3600
            lines.append(
                f"  {age_h:.0f}h ago — {h['reason'][:60]}"
            )
        lines.append(f"Config version: {self.config._config.get('version', 1)}")
        lines.append("Changes from default:")
        for diff in self.config.diff_from_default():
            lines.append(f"  • {diff}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# run.py integration — 4 touch points
# ─────────────────────────────────────────────────────────────────────────────
#
# 1. Import + init (after self_engine is ready):
#       from nex.nex_trainer import SelfTrainer, NexConfig
#       nex_config = NexConfig()
#       trainer = SelfTrainer(nex_config, telegram_bot=None, self_engine=self_engine)
#       # Note: wire telegram_bot once you have the bot object available
#
# 2. _llm() function — replace hardcoded temperature with config:
#       # Find: "temperature": 0.75  in the local _llm() function
#       # Replace with:
#       _llm_params = nex_config.get_llm_params()
#       # Then in the requests.post call:
#       r = _req.post("http://localhost:8080/completion", json={
#           "prompt": f"[INST] {system}\n\n{prompt} [/INST]",
#           "n_predict": _llm_params.get("max_tokens", 200),
#           "temperature": _llm_params.get("temperature", 0.75),
#           "top_p": _llm_params.get("top_p", 0.90),
#           "top_k": _llm_params.get("top_k", 40),
#           "repeat_penalty": _llm_params.get("repeat_penalty", 1.10),
#           "stop": ["</s>", "[INST]", "\n\n\n"]
#       }, timeout=60)
#
# 3. System prompt — inject config addendum:
#       _addendum = nex_config.get_system_addendum()
#       system = base_system + (f"\n\n{_addendum}" if _addendum else "")
#
# 4. REFLECT phase — check if retraining needed:
#       # Gather metrics
#       _metrics = {
#           "topic_alignment":  avg_alignment,   # from db.get_reflection_stats()
#           "avg_confidence":   avg_conf,         # from db query
#           "high_conf_count":  high_conf_count,  # beliefs > 70%
#           "reflection_score": avg_score,
#           "cycle_count":      cycle,
#       }
#       trainer.maybe_propose(_metrics)
#
# 5. nex_telegram_commands.py — handle approvals:
#       # In TelegramCommandHandler.handle(), before other checks:
#       if trainer.handle_approval(text, chat_id):
#           return True
#
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Telegram command additions
# ─────────────────────────────────────────────────────────────────────────────
#
# Add to LEARN_TRIGGERS in nex_telegram_commands.py:
#   r"^training$" | r"^/training$"  →  {"type": "training_status"}
#
# Handle in TelegramCommandHandler:
#   elif cmd["type"] == "training_status":
#       self._send(chat_id, trainer.training_history_summary())
#
# ─────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    config = NexConfig()
    print("Config loaded:")
    print(json.dumps(config._config, indent=2))

    print("\nDiff from default:")
    diffs = config.diff_from_default()
    print("  (none)" if not diffs else "\n".join(f"  {d}" for d in diffs))

    # Simulate a proposal
    trainer = SelfTrainer(config)
    print("\nSimulating metrics that trigger proposal...")
    metrics = {
        "topic_alignment":  0.38,
        "avg_confidence":   0.39,
        "high_conf_count":  0,
        "reflection_score": 0.35,
        "cycle_count":      15,
    }
    trainer._cycle_count = 15
    proposed = trainer.maybe_propose(metrics)
    print(f"Proposal sent: {proposed}")
    if trainer._proposal:
        print(f"Reason: {trainer._proposal.reason}")
        print(f"Changes: {trainer._proposal.proposed_changes}")
