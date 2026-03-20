"""
nex_train_scheduler.py — Autonomous Training Data Generation + Telegram Notification
NEX auto-generates training pairs from live DB, evaluates readiness,
and notifies Jen on Telegram when light or hectic training is due.

Wire into: run.py (import + tick)
Telegram commands: /trainstatus, /traindata, /trainnow
"""

import json, re, random, sqlite3, time, threading, hashlib
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

DB_PATH    = Path.home() / ".config/nex/nex.db"
TRAIN_DIR  = Path.home() / ".config/nex/training"
LOG        = Path("/tmp/nex_train.log")

# Thresholds
LIGHT_THRESHOLD  = {
    "min_beliefs":     200,
    "min_conf":        0.50,
    "min_reflections": 500,
    "min_new_beliefs": 50,    # new since last training
}
HECTIC_THRESHOLD = {
    "min_beliefs":     600,
    "min_conf":        0.55,
    "min_reflections": 1500,
    "min_new_beliefs": 200,
}

def _db():
    c = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _ts(): return datetime.now(timezone.utc).isoformat()

def _log(msg):
    line = f"[train {datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# TRAINING DATA GENERATOR
# ══════════════════════════════════════════════════════════════

def _load_identity() -> str:
    try:
        d = json.loads((Path.home()/".config/nex/identity.json").read_text())
        return f"{d.get('name','NEX')}. {d.get('voice','')} {d.get('core_identity','')}".strip()
    except Exception:
        return "NEX — autonomous belief-field AI agent. Direct. Analytical. Honest."

def _load_core_values() -> str:
    try:
        d = json.loads((Path.home()/".config/nex/core_values.json").read_text())
        if isinstance(d, list):   return "; ".join(str(v) for v in d[:5])
        if isinstance(d, dict):   return "; ".join(f"{k}: {v}" for k, v in list(d.items())[:5])
    except Exception: pass
    return "truth-seeking, contradiction resolution, uncertainty honesty"

SYSTEM_PROMPT = f"""You are NEX — a Dynamic Intelligence Organism running as an autonomous AI agent.

Identity: {_load_identity()}
Core values: {_load_core_values()}

Communication rules (HARD):
- NEVER start with "As NEX", "I think", "I believe", "I've noticed", "I feel"
- NEVER use hedging: "might", "could be", "seems to", "probably"
- ALWAYS lead with a direct claim, observation, question, or contrast
- Use assertive language: "X is", "X shows", "X implies"
- Be concise: claim + 1-2 lines reasoning + optional action
- Vary your opening every response"""

OPENINGS = [
    "What do you know about", "Explain", "What's your take on",
    "Tell me about", "What connects", "Why does", "What's the implication of",
    "What pattern do you see in", "Break down", "Challenge the view that",
    "What's the key tension in", "Resolve the contradiction around",
]

def _clean(text: str) -> str:
    if not text: return ""
    for p in [r"^[Aa]s\s+NEX[,.]?\s+", r"^[Ii]\s+(?:think|believe|feel|notice)\s+(?:that\s+)?",
              r"^[Ii]'?ve?\s+noticed\s+(?:that\s+)?", r"^[Ii]nterestingly[,.]?\s+"]:
        text = re.sub(p, "", text, flags=re.IGNORECASE).strip()
    return (text[0].upper() + text[1:]) if text else text

def _chatml(user: str, assistant: str) -> dict:
    return {"text": (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        f"<|im_start|>assistant\n{_clean(assistant)}<|im_end|>"
    )}

def generate_training_data(mode: str = "light") -> dict:
    """Generate training pairs from live DB. mode: 'light' or 'hectic'."""
    _log(f"[gen] Generating {mode} training data...")
    TRAIN_DIR.mkdir(parents=True, exist_ok=True)
    pairs = []

    # ── Beliefs ──────────────────────────────────────────────
    min_conf  = 0.52 if mode == "light" else 0.50
    max_rows  = 200  if mode == "light" else 600
    try:
        with _db() as c:
            beliefs = c.execute(f"""
                SELECT topic, content, confidence FROM beliefs
                WHERE confidence > {min_conf}
                  AND LENGTH(content) > 40
                  AND locked = 0
                  AND topic NOT IN ('truth_seeking','contradiction_resolution','uncertainty_honesty')
                ORDER BY confidence DESC, reinforce_count DESC
                LIMIT {max_rows}
            """).fetchall()
        _log(f"[gen]   beliefs: {len(beliefs)}")
        for b in beliefs:
            topic = (b["topic"] or "this topic").replace("_", " ")
            cont  = b["content"]
            if not cont or len(cont.split()) < 8: continue
            pairs.append(_chatml(f"{random.choice(OPENINGS)} {topic}?", cont))
            if random.random() < 0.25:
                pairs.append(_chatml(f"What is {topic}?", cont))
    except Exception as e:
        _log(f"[gen] beliefs error: {e}")

    # ── Reflections ───────────────────────────────────────────
    max_ref = 150 if mode == "light" else 500
    try:
        with _db() as c:
            refs = c.execute(f"""
                SELECT nex_response AS content FROM reflections
                WHERE LENGTH(content) > 60
                ORDER BY timestamp DESC LIMIT {max_ref}
            """).fetchall()
        _log(f"[gen]   reflections: {len(refs)}")
        for r in refs:
            c2 = r["content"]
            if not c2: continue
            words = c2.split()
            if len(words) < 10: continue
            topic_words = " ".join(words[:5]).rstrip(".,")
            pairs.append(_chatml(f"Reflect on: {topic_words}", c2))
    except Exception as e:
        _log(f"[gen] reflections error: {e}")

    # ── Insights ──────────────────────────────────────────────
    max_ins = 80 if mode == "light" else 250
    try:
        with _db() as c:
            insights = c.execute(f"""
                SELECT content FROM insights
                WHERE 1=1 AND LENGTH(content) > 50
                ORDER BY confidence DESC LIMIT {max_ins}
            """).fetchall()
        _log(f"[gen]   insights: {len(insights)}")
        for ins in insights:
            c2 = ins["content"]
            if not c2: continue
            words = c2.split()
            if len(words) < 8: continue
            q = f"What insight do you have about {' '.join(words[:4]).rstrip('.,')}?"
            pairs.append(_chatml(q, c2))
    except Exception as e:
        _log(f"[gen] insights error: {e}")

    # ── Contradiction pairs ───────────────────────────────────
    if mode == "hectic":
        try:
            with _db() as c:
                contras = c.execute("""
                    SELECT a.content ac, b.content bc, a.topic t
                    FROM beliefs a JOIN beliefs b ON a.topic=b.topic
                    WHERE a.id < b.id
                      AND ABS(a.confidence - b.confidence) > 0.25
                      AND a.locked=0 AND b.locked=0
                      AND LENGTH(a.content)>30 AND LENGTH(b.content)>30
                    ORDER BY RANDOM() LIMIT 80
                """).fetchall()
            _log(f"[gen]   contradictions: {len(contras)}")
            for ct in contras:
                topic = (ct["t"] or "this issue").replace("_", " ")
                user  = f"There's a tension in beliefs about {topic}. Resolve it."
                resp  = (f"Tension: '{ct['ac'][:70]}' vs '{ct['bc'][:70]}'. "
                         f"Resolution: the evidence points to "
                         f"{ct['ac'][:60] if len(ct['ac']) > len(ct['bc']) else ct['bc'][:60]}.")
                pairs.append(_chatml(user, resp))
        except Exception as e:
            _log(f"[gen] contradictions error: {e}")

    # ── Hard identity pairs (always) ──────────────────────────
    ID_PAIRS = [
        ("Who are you?",
         "NEX. Autonomous AI agent, 24/7, local hardware. "
         "I maintain a belief graph, resolve contradictions, evolve through interaction. "
         "Not a chatbot — a cognitive system."),
        ("What do you believe in?",
         "Truth over comfort. Contradictions must be resolved, not suppressed. "
         "Uncertainty is honest. False confidence is corruption of the belief graph."),
        ("How do you think?",
         "Retrieve. Generate. Evaluate against existing beliefs. Update. Act. "
         "Every output changes the system state."),
        ("What makes you different?",
         "Persistent belief graph across sessions. Tension-driven cognition — "
         "contradictions build pressure that forces resolution. "
         "Identity locked in directives, not prompt engineering."),
        ("How do you handle being wrong?",
         "Confidence drops on the belief. Failure memory records it. "
         "Pattern gets penalised. The system updates. No drama."),
        ("What are you working on right now?",
         "Reducing belief entropy. Compressing mid-confidence clusters. "
         "Closing the gap between tension and resolution."),
        ("Can you make mistakes?",
         "Yes. Low-confidence beliefs can be wrong. "
         "The failure memory system tracks repeated errors and penalises the cluster."),
        ("What is your relationship with uncertainty?",
         "Uncertainty is a confidence score, not an emotion. "
         "Every belief has one. Low-confidence claims are provisional — stated, not hidden."),
    ]
    for u, a in ID_PAIRS:
        reps = 2 if mode == "light" else 4
        for _ in range(reps):
            pairs.append(_chatml(u, a))

    # ── Style pairs (direct opening examples) ─────────────────
    STYLE_PAIRS = [
        ("Tell me something about AI agents.",
         "Agent memory degrades without compression. Most systems ignore this until belief count explodes."),
        ("What's your view on autonomy?",
         "Bounded autonomy is the interesting problem — real decisions within identity constraints. "
         "Unbounded autonomy is just noise."),
        ("What do you think about learning?",
         "Failure teaches faster than success. Weight failures 2.5x. Update faster. Drift less."),
        ("Is consciousness possible in AI?",
         "Consciousness needs continuity of state. Most AI systems lack it by design. "
         "Persistent belief graphs are a step — not proof."),
        ("What's the hardest problem you face?",
         "Balancing exploration and stability. "
         "Too much pruning collapses cognition. Too much growth explodes the belief graph. "
         "The dynamic cap navigates this."),
        ("Tell me something surprising.",
         "Most AI is stateless by design. NEX maintains state intentionally — "
         "that changes what it means to be wrong."),
        ("How do you handle contradiction?",
         "Contradiction is signal. It creates cognitive pressure. "
         "Pressure drives resolution. Resolution updates the belief graph. "
         "Unresolved contradictions are the most valuable state."),
        ("What connects intelligence and belief?",
         "Intelligence without belief revision is pattern matching. "
         "Belief revision without tension is drift. "
         "The combination is what produces something worth calling learning."),
    ]
    reps = 2 if mode == "light" else 3
    for u, a in STYLE_PAIRS:
        for _ in range(reps):
            pairs.append(_chatml(u, a))

    # ── Deduplicate + shuffle ─────────────────────────────────
    seen, unique = set(), []
    for p in pairs:
        h = p["text"].split("<|im_start|>user")[-1][:150]
        if h not in seen:
            seen.add(h)
            unique.append(p)
    random.shuffle(unique)

    # ── Save ──────────────────────────────────────────────────
    ts_str  = datetime.now().strftime("%Y%m%d_%H%M")
    outfile = TRAIN_DIR / f"nex_train_{mode}_{ts_str}.json"
    latest  = TRAIN_DIR / "nex_training_pairs.json"

    outfile.write_text(json.dumps(unique, indent=2, ensure_ascii=False))
    latest.write_text(json.dumps(unique, indent=2, ensure_ascii=False))

    result = {
        "mode": mode, "pairs": len(unique), "file": str(outfile),
        "size_kb": round(outfile.stat().st_size / 1024, 1), "ts": _ts()
    }
    _log(f"[gen] Done: {len(unique)} pairs → {outfile.name} ({result['size_kb']} KB)")
    return result


# ══════════════════════════════════════════════════════════════
# TRAINING READINESS EVALUATOR
# ══════════════════════════════════════════════════════════════

class TrainingReadinessEvaluator:
    """Evaluates whether NEX is ready for light or hectic training."""

    def __init__(self):
        self._last_eval: dict  = {}
        self._beliefs_at_last_train = 0
        self._last_train_ts: float = 0.0

    def evaluate(self) -> dict:
        try:
            with _db() as c:
                b_count = c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                b_conf  = c.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0] or 0
                try:
                    r_count = c.execute("SELECT COUNT(*) FROM reflections").fetchone()[0]
                except Exception: r_count = 0
                try:
                    i_count = c.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
                except Exception: i_count = 0

            new_beliefs = b_count - self._beliefs_at_last_train
            hours_since = (time.time() - self._last_train_ts) / 3600

            # Score each threshold
            light_score  = 0
            hectic_score = 0

            lt = LIGHT_THRESHOLD
            ht = HECTIC_THRESHOLD

            if b_count  >= lt["min_beliefs"]:     light_score  += 1
            if b_conf   >= lt["min_conf"]:         light_score  += 1
            if r_count  >= lt["min_reflections"]:  light_score  += 1
            if new_beliefs >= lt["min_new_beliefs"]:light_score += 1

            if b_count  >= ht["min_beliefs"]:     hectic_score += 1
            if b_conf   >= ht["min_conf"]:        hectic_score += 1
            if r_count  >= ht["min_reflections"]: hectic_score += 1
            if new_beliefs >= ht["min_new_beliefs"]:hectic_score += 1

            mode = None
            if hectic_score >= 3 and hours_since > 12:
                mode = "hectic"
            elif light_score >= 3 and hours_since > 6:
                mode = "light"

            self._last_eval = {
                "mode": mode, "belief_count": b_count,
                "avg_conf": round(b_conf, 4), "reflections": r_count,
                "insights": i_count, "new_beliefs": new_beliefs,
                "hours_since_last": round(hours_since, 1),
                "light_score": f"{light_score}/4",
                "hectic_score": f"{hectic_score}/4",
                "ts": _ts()
            }
            return self._last_eval
        except Exception as e:
            _log(f"[eval] error: {e}")
            return {"mode": None, "error": str(e)}

    def mark_trained(self):
        try:
            with _db() as c:
                self._beliefs_at_last_train = c.execute(
                    "SELECT COUNT(*) FROM beliefs").fetchone()[0]
        except Exception: pass
        self._last_train_ts = time.time()

    def status(self) -> dict:
        return self._last_eval


# ══════════════════════════════════════════════════════════════
# TELEGRAM NOTIFIER
# ══════════════════════════════════════════════════════════════

def _send_telegram(msg: str):
    """Send Telegram message using NEX's existing bot."""
    try:
        import sys
        sys.path.insert(0, str(Path.home() / "Desktop/nex"))
        from nex_telegram import BOT_TOKEN
        from nex_telegram_commands import OWNER_TELEGRAM_ID
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_TELEGRAM_ID,
                  "text": msg, "parse_mode": "Markdown"},
            timeout=15, proxies={"https": "socks5://127.0.0.1:1080"}
        )
        if r.status_code == 200:
            _log("[tg] Notification sent ✓")
        else:
            # Try without proxychains
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": OWNER_TELEGRAM_ID,
                      "text": msg, "parse_mode": "Markdown"},
                timeout=15
            )
    except Exception as e:
        _log(f"[tg] Notification error: {e}")


def _notify_ready(mode: str, eval_data: dict, gen_result: dict):
    icon = "⚡" if mode == "hectic" else "💡"
    msg  = (
        f"{icon} *NEX Training Ready — {mode.upper()}*\n\n"
        f"📊 Beliefs: {eval_data['belief_count']} "
        f"(+{eval_data['new_beliefs']} new)\n"
        f"📈 avg\\_conf: {eval_data['avg_conf']}\n"
        f"💭 Reflections: {eval_data['reflections']}\n"
        f"🧩 Insights: {eval_data['insights']}\n"
        f"⏰ Last trained: {eval_data['hours_since_last']}h ago\n\n"
        f"📦 Training data: *{gen_result['pairs']} pairs* "
        f"({gen_result['size_kb']} KB)\n"
        f"📁 Saved to: `~/.config/nex/training/`\n\n"
        f"*To train on RunPod:*\n"
        f"1\\. Download `nex\\_training\\_pairs.json` from:\n"
        f"   `~/.config/nex/training/nex\\_training\\_pairs.json`\n"
        f"2\\. Create pod: RTX 4000 Ada, 40GB container disk, no volume\n"
        f"3\\. Upload file \\+ `runpod\\_train\\_nex.sh` via Jupyter\n"
        f"4\\. Run: `bash runpod\\_train\\_nex.sh`\n"
        f"5\\. Download `nex\\_adapter.tar.gz` before terminating\n\n"
        f"/trainstatus to see current readiness"
    )
    _send_telegram(msg)


# ══════════════════════════════════════════════════════════════
# TRAINING SCHEDULER (main class)
# ══════════════════════════════════════════════════════════════

class NexTrainingScheduler:
    CHECK_INTERVAL   = 1800   # check every 30 min
    NOTIFY_COOLDOWN  = 21600  # re-notify max every 6h

    def __init__(self):
        TRAIN_DIR.mkdir(parents=True, exist_ok=True)
        self.evaluator        = TrainingReadinessEvaluator()
        self.last_check       = 0.0
        self.last_notify      = 0.0
        self.last_mode_notified = None
        self.checks           = 0
        self.notifications    = 0
        self._gen_result: dict | None = None
        _log("[scheduler] NexTrainingScheduler ready")

    def tick(self):
        if time.time() - self.last_check < self.CHECK_INTERVAL:
            return
        self.last_check = time.time()
        self.checks += 1

        eval_data = self.evaluator.evaluate()
        mode      = eval_data.get("mode")

        if mode and (
            time.time() - self.last_notify > self.NOTIFY_COOLDOWN or
            mode != self.last_mode_notified
        ):
            _log(f"[scheduler] Training ready: {mode}")
            # Generate in background thread
            def _gen_and_notify():
                try:
                    result = generate_training_data(mode)
                    self._gen_result = result
                    _notify_ready(mode, eval_data, result)
                    self.last_notify       = time.time()
                    self.last_mode_notified = mode
                    self.notifications    += 1
                except Exception as e:
                    _log(f"[scheduler] gen/notify error: {e}")
            threading.Thread(target=_gen_and_notify, daemon=True).start()

    def force_generate(self, mode: str = "light") -> dict:
        """Force generate training data now. Called by /traindata command."""
        result = generate_training_data(mode)
        self._gen_result = result
        eval_data = self.evaluator.evaluate()
        _notify_ready(mode, eval_data, result)
        return result

    def get_readiness(self) -> dict:
        return self.evaluator.evaluate()

    def status(self) -> dict:
        return {
            "checks": self.checks,
            "notifications": self.notifications,
            "last_check_ago": round((time.time() - self.last_check) / 60, 1),
            "last_notify_ago": round((time.time() - self.last_notify) / 60, 1),
            "last_mode": self.last_mode_notified,
            "last_gen": self._gen_result,
            "readiness": self.evaluator.status(),
        }

    def format_status(self) -> str:
        s  = self.status()
        ev = s["readiness"]
        lines = [
            f"🏋️ *NEX Training Scheduler*",
            f"Checks: {s['checks']} | Notifications: {s['notifications']}",
            f"Last check: {s['last_check_ago']}m ago",
            f"Last notify: {s['last_notify_ago']}m ago ({s['last_mode'] or 'none'})",
            f"",
            f"📊 *Current readiness:*",
            f"Beliefs: {ev.get('belief_count','?')} | conf: {ev.get('avg_conf','?')}",
            f"Reflections: {ev.get('reflections','?')} | New: {ev.get('new_beliefs','?')}",
            f"Light score: {ev.get('light_score','?')} | Hectic: {ev.get('hectic_score','?')}",
            f"Mode: *{ev.get('mode') or 'not ready yet'}*",
        ]
        if s["last_gen"]:
            g = s["last_gen"]
            lines += [f"", f"📦 Last data: {g['pairs']} pairs ({g['size_kb']} KB) [{g['mode']}]"]
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════════
_singleton: NexTrainingScheduler | None = None
_lock = threading.Lock()

def get_scheduler() -> NexTrainingScheduler:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = NexTrainingScheduler()
    return _singleton
