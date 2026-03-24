"""
NEX R101–R115 — Research-Backed Evolution Stack
15 modules: experience distillation, critical training, hierarchical planning,
self-healing, goal inference, drive motivation, continuous policy evolution.
Deploy: ~/Desktop/nex/nex_upgrades/nex_r115.py
"""

import sqlite3, json, time, math, hashlib, threading, random
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

DB_PATH  = Path.home() / ".config/nex/nex_data/nex.db"
LOG      = Path("/tmp/nex_r115.log")
STRAT_DB = Path.home() / ".config/nex/strategies.json"
POLICY_F = Path.home() / ".config/nex/policy.json"

def _db():
    c = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _ts(): return datetime.now(timezone.utc).isoformat()

def _log(msg):
    line = f"[r115 {datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass

def _load_json(path: Path, default):
    try:
        if path.exists(): return json.loads(path.read_text())
    except Exception: pass
    return default

def _save_json(path: Path, data):
    try: path.write_text(json.dumps(data, indent=2))
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# R101 — EXPERIENCE DISTILLATION LAYER
# ══════════════════════════════════════════════════════════════
class ExperienceDistillationLayer:
    """After cycles compress trajectories → reusable strategies.
    Store 'what worked' not just 'what happened'. EvolveR-inspired."""
    INTERVAL    = 300
    MIN_CYCLES  = 10

    def __init__(self):
        self.last_run     = 0.0
        self.distilled    = 0
        self._trajectory: deque[dict] = deque(maxlen=100)
        self._strategies: list[dict]  = _load_json(STRAT_DB, [])

    def record_event(self, action: str, outcome: float, context: dict):
        self._trajectory.append({
            "ts": _ts(), "action": action,
            "outcome": outcome, "context": context
        })

    def _distill(self):
        traj = list(self._trajectory)
        if len(traj) < self.MIN_CYCLES: return

        # Group by action type, compute mean outcome
        groups: dict[str, list[float]] = defaultdict(list)
        for e in traj:
            groups[e["action"]].append(e["outcome"])

        for action, outcomes in groups.items():
            if len(outcomes) < 3: continue
            avg = sum(outcomes) / len(outcomes)
            if avg > 0.65:
                strategy = {
                    "pattern": f"action={action}",
                    "rule": f"when {action} → avg_outcome={avg:.2f}",
                    "confidence": round(avg, 3),
                    "uses": 0,
                    "ts": _ts(),
                }
                # Avoid duplicates
                existing = [s for s in self._strategies
                            if s["pattern"] == strategy["pattern"]]
                if existing:
                    existing[0]["confidence"] = round(
                        (existing[0]["confidence"] + avg) / 2, 3)
                    existing[0]["ts"] = _ts()
                else:
                    self._strategies.append(strategy)
                    self.distilled += 1
                    _log(f"[EDL] Distilled strategy: {strategy['rule']}")

        _save_json(STRAT_DB, self._strategies[-50:])
        self._trajectory.clear()

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        self._distill()

    def best_strategy(self, context_key: str = "") -> dict | None:
        if not self._strategies: return None
        ranked = sorted(self._strategies,
                        key=lambda s: s["confidence"], reverse=True)
        return ranked[0] if ranked else None

    def status(self) -> dict:
        return {"distilled": self.distilled,
                "strategies": len(self._strategies),
                "trajectory_len": len(self._trajectory)}


# ══════════════════════════════════════════════════════════════
# R102 — CRITICAL ACTION TRAINING LOOP (ACT)
# ══════════════════════════════════════════════════════════════
class CriticalActionTrainingLoop:
    """Compare chosen action vs alternatives. Reward correct judgment.
    Agentic Critical Training approach."""
    INTERVAL = 60

    def __init__(self):
        self.last_run   = 0.0
        self._log: deque[dict] = deque(maxlen=200)
        self.correct_judgments = 0
        self.total_judgments   = 0

    def evaluate(self, chosen_action: str, alternatives: list[str],
                  outcome: float, topic: str = "") -> dict:
        self.total_judgments += 1
        # Score: did chosen achieve better outcome than alternatives?
        # We proxy alternative outcomes from recent DB patterns
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT AVG(confidence) ac FROM beliefs
                    WHERE topic LIKE ? AND locked=0
                """, (f"%{topic}%",)).fetchone()
            base_conf = float(rows["ac"] or 0.50)
        except Exception:
            base_conf = 0.50

        # Chosen is better if outcome > base + margin
        is_correct = outcome > (base_conf + 0.05)
        if is_correct:
            self.correct_judgments += 1

        entry = {
            "ts": _ts(), "action": chosen_action,
            "alternatives_count": len(alternatives),
            "outcome": outcome, "base": base_conf,
            "correct": is_correct, "topic": topic,
        }
        self._log.append(entry)

        # Reinforce belief if judgment was correct
        if is_correct and topic:
            try:
                with _db() as c:
                    c.execute("""
                        UPDATE beliefs SET confidence=MIN(confidence+0.03,0.95)
                        WHERE topic LIKE ? AND locked=0
                    """, (f"%{topic}%",))
                    # commit handled by _db() context manager
            except Exception: pass

        return entry

    def judgment_rate(self) -> float:
        return round(self.correct_judgments / max(self.total_judgments, 1), 3)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

    def status(self) -> dict:
        return {"total": self.total_judgments,
                "correct": self.correct_judgments,
                "rate": self.judgment_rate()}


# ══════════════════════════════════════════════════════════════
# R103 — MULTI-STAGE FEEDBACK PIPELINE
# ══════════════════════════════════════════════════════════════
class MultiStageFeedbackPipeline:
    """Collect feedback at: perception, reasoning, decision, action.
    Not just final result. Prevent hidden failures across pipeline."""
    STAGES = ["perception", "reasoning", "decision", "action"]

    def __init__(self):
        self._stage_scores: dict[str, deque] = {
            s: deque(maxlen=50) for s in self.STAGES
        }
        self._failures: dict[str, int] = defaultdict(int)
        self.total_recorded = 0

    def record(self, stage: str, score: float, detail: str = ""):
        if stage not in self.STAGES: return
        self._stage_scores[stage].append(score)
        self.total_recorded += 1
        if score < 0.30:
            self._failures[stage] += 1
            _log(f"[MSFP] Low score at {stage}: {score:.2f} — {detail[:60]}")

    def stage_health(self) -> dict[str, float]:
        result = {}
        for stage, scores in self._stage_scores.items():
            if scores:
                result[stage] = round(sum(scores) / len(scores), 3)
            else:
                result[stage] = 1.0
        return result

    def weakest_stage(self) -> str:
        h = self.stage_health()
        return min(h, key=lambda x: h[x]) if h else "unknown"

    def tick(self): pass

    def status(self) -> dict:
        return {"health": self.stage_health(),
                "weakest": self.weakest_stage(),
                "failures": dict(self._failures),
                "total": self.total_recorded}


# ══════════════════════════════════════════════════════════════
# R104 — REFLECTION-IN-LOOP
# ══════════════════════════════════════════════════════════════
class ReflectionInLoop:
    """Reflection runs DURING reasoning, not after.
    Interrupt bad reasoning mid-cycle. Inject correction before action."""
    INTERRUPT_THRESHOLD = 0.35   # quality score below this → interrupt

    def __init__(self):
        self.interrupts   = 0
        self.corrections  = 0
        self._current_reasoning: str = ""

    def begin_reasoning(self, content: str):
        self._current_reasoning = content

    def mid_cycle_check(self, partial_output: str,
                         tension: float = 0.0) -> tuple[bool, str]:
        """Returns (should_interrupt, correction_hint)."""
        words = partial_output.lower().split()
        # Quality heuristics
        contradiction_words = {"but", "however", "although", "yet",
                                "contradiction", "conflict", "disagree"}
        has_contradiction = bool(set(words) & contradiction_words)
        repetitive = len(set(words)) / max(len(words), 1) < 0.40
        high_tension = tension > 0.65

        quality = 1.0
        if repetitive:      quality -= 0.30
        if has_contradiction and high_tension: quality -= 0.25
        if len(words) < 5:  quality -= 0.20

        if quality < self.INTERRUPT_THRESHOLD:
            self.interrupts += 1
            hint = ""
            if repetitive:
                hint = "Avoid repetition. State one clear position."
            elif has_contradiction and high_tension:
                hint = "Contradiction under tension. Resolve before continuing."
            else:
                hint = "Insufficient reasoning. Expand with evidence."
            return True, hint

        return False, ""

    def inject_correction(self, original: str, hint: str) -> str:
        self.corrections += 1
        return f"[corrected] {hint} | {original[:200]}"

    def tick(self): pass

    def status(self) -> dict:
        return {"interrupts": self.interrupts, "corrections": self.corrections,
                "threshold": self.INTERRUPT_THRESHOLD}


# ══════════════════════════════════════════════════════════════
# R105 — STRATEGY LIBRARY (ABSTRACTION MEMORY)
# ══════════════════════════════════════════════════════════════
class StrategyLibrary:
    """Convert repeated patterns into strategies (not beliefs).
    Higher-level than belief graph."""
    INTERVAL   = 240
    MIN_PATTERN_HITS = 3

    def __init__(self):
        self.last_run  = 0.0
        self._patterns: dict[str, int] = defaultdict(int)
        self._strategies: dict[str, dict] = {}
        self.promoted  = 0

    def observe(self, condition: str, action: str):
        key = f"{condition}→{action}"
        self._patterns[key] += 1
        if self._patterns[key] >= self.MIN_PATTERN_HITS:
            if key not in self._strategies:
                self._strategies[key] = {
                    "condition": condition,
                    "action": action,
                    "hits": self._patterns[key],
                    "confidence": 0.65,
                    "ts": _ts(),
                }
                self.promoted += 1
                _log(f"[SL] Strategy promoted: {key}")
            else:
                self._strategies[key]["hits"] += 1
                self._strategies[key]["confidence"] = min(
                    0.95,
                    self._strategies[key]["confidence"] + 0.02
                )

    def lookup(self, condition: str) -> dict | None:
        matches = [s for k, s in self._strategies.items()
                   if condition.lower() in k.lower()]
        if not matches: return None
        return max(matches, key=lambda s: s["confidence"])

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        # Seed from known patterns
        self.observe("contradiction_high", "prioritize_resolution")
        self.observe("avg_conf_low",       "aggressive_pruning")
        self.observe("tension_rising",     "force_resolution")
        self.observe("belief_growth_high", "compression_mode")

    def status(self) -> dict:
        return {"strategies": len(self._strategies),
                "patterns_tracked": len(self._patterns),
                "promoted": self.promoted,
                "top": sorted(self._strategies.values(),
                               key=lambda s: -s["confidence"])[:3]}


# ══════════════════════════════════════════════════════════════
# R106 — HIERARCHICAL PLANNING LAYER
# ══════════════════════════════════════════════════════════════
class HierarchicalPlanningLayer:
    """High-level goals → subgoals → actions. Not just reactive loop."""
    INTERVAL = 120

    GOAL_TEMPLATES = {
        "coherent_intelligence": [
            "maintain_avg_conf_above_0.55",
            "reduce_contradiction_below_20",
            "keep_belief_count_1000_1600",
        ],
        "identity_stability": [
            "lock_core_directives",
            "boost_identity_beliefs",
            "reject_drift_outputs",
        ],
        "knowledge_expansion": [
            "absorb_new_topics",
            "cross_domain_bridge",
            "validate_with_external",
        ],
    }

    def __init__(self):
        self.last_run      = 0.0
        self.active_goal   = "coherent_intelligence"
        self.active_subs:  list[str] = []
        self.completed     = 0
        self._progress:    dict[str, float] = {}

    def tick(self, avg_conf: float = 0.50, contradiction_count: int = 0,
              belief_count: int = 1000):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        # Select goal based on system state
        if avg_conf < 0.50 or contradiction_count > 30:
            self.active_goal = "coherent_intelligence"
        elif belief_count > 1600:
            self.active_goal = "coherent_intelligence"
        elif avg_conf > 0.58:
            self.active_goal = "knowledge_expansion"
        else:
            self.active_goal = "identity_stability"

        self.active_subs = self.GOAL_TEMPLATES[self.active_goal]

        # Evaluate subgoal progress
        for sub in self.active_subs:
            if "avg_conf" in sub:
                self._progress[sub] = min(1.0, avg_conf / 0.55)
            elif "contradiction" in sub:
                self._progress[sub] = max(0.0, 1.0 - contradiction_count / 30)
            elif "belief_count" in sub:
                in_range = 1000 <= belief_count <= 1600
                self._progress[sub] = 1.0 if in_range else 0.50
            else:
                self._progress[sub] = 0.70  # default partial

        # Count completed
        self.completed = sum(1 for v in self._progress.values() if v >= 0.90)

    def current_plan(self) -> dict:
        return {"goal": self.active_goal, "subgoals": self.active_subs,
                "progress": self._progress, "completed": self.completed}

    def status(self) -> dict:
        return self.current_plan()


# ══════════════════════════════════════════════════════════════
# R107 — TOOL/ENVIRONMENT SPECIALIZATION
# ══════════════════════════════════════════════════════════════
class ToolEnvironmentSpecialization:
    """Assign specific modules to specific tool types.
    Reduce 'general reasoning everywhere'."""
    TOOL_MAP = {
        "web_search":     ["BeliefValidationLayer", "CausalTraceUtilization"],
        "db_query":       ["BeliefMarket", "DynamicBeliefCap", "AggressiveBeliefMergeV2"],
        "platform_post":  ["PlatformAdaptationLayer", "OutputCompressionLayer"],
        "reflection":     ["ReflectionKillSwitch", "ReflectionInLoop"],
        "contradiction":  ["ForcedTensionResolution", "TensionActionBinding"],
        "identity":       ["IdentityDominanceEnforcer", "IdentityGravity"],
        "planning":       ["HierarchicalPlanningLayer", "StrategyLibrary"],
    }

    def __init__(self):
        self._call_counts: dict[str, int] = defaultdict(int)
        self._specialist_calls: dict[str, int] = defaultdict(int)

    def route(self, tool_type: str) -> list[str]:
        specialists = self.TOOL_MAP.get(tool_type, [])
        self._call_counts[tool_type] += 1
        for s in specialists:
            self._specialist_calls[s] += 1
        return specialists

    def specialization_rate(self) -> float:
        total = sum(self._call_counts.values())
        routed = sum(1 for t in self._call_counts if t in self.TOOL_MAP)
        return round(routed / max(total, 1), 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"tool_calls": dict(self._call_counts),
                "specialization_rate": self.specialization_rate(),
                "top_specialists": dict(
                    sorted(self._specialist_calls.items(),
                           key=lambda x: -x[1])[:5])}


# ══════════════════════════════════════════════════════════════
# R108 — SELF-HEALING SYSTEM LOOP
# ══════════════════════════════════════════════════════════════
class SelfHealingSystemLoop:
    """Monitor failures + degraded outputs. Auto-trigger parameter
    adjustment or module reset. Self-healing agent pattern."""
    INTERVAL        = 90
    DEGRADED_THRESH = 0.35
    FAILURE_THRESH  = 5

    def __init__(self):
        self.last_run    = 0.0
        self._health:    dict[str, float] = {}
        self._failures:  dict[str, int]   = defaultdict(int)
        self.heals       = 0
        self.resets      = 0

    def report_health(self, module: str, score: float):
        self._health[module] = score
        if score < self.DEGRADED_THRESH:
            self._failures[module] += 1

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        degraded = {m: s for m, s in self._health.items()
                    if s < self.DEGRADED_THRESH}

        for module, score in degraded.items():
            failures = self._failures[module]
            if failures >= self.FAILURE_THRESH:
                # Trigger reset: attempt to boost related beliefs
                _log(f"[SHL] RESET trigger: {module} score={score:.2f} "
                     f"failures={failures}")
                try:
                    with _db() as c:
                        c.execute("""
                            UPDATE beliefs
                            SET confidence = MIN(confidence + 0.05, 0.85)
                            WHERE topic LIKE ? AND locked=0
                        """, (f"%{module.lower()[:8]}%",))
                        # commit handled by _db() context manager
                except Exception: pass
                self._failures[module] = 0
                self.resets += 1
            elif failures >= 2:
                # Soft heal: adjust parameters
                self.heals += 1
                _log(f"[SHL] Soft heal: {module} (failures={failures})")

    def status(self) -> dict:
        return {"module_health": {k: round(v, 3)
                                  for k, v in sorted(
                                      self._health.items(),
                                      key=lambda x: x[1])[:8]},
                "heals": self.heals, "resets": self.resets,
                "degraded_count": len([s for s in self._health.values()
                                       if s < self.DEGRADED_THRESH])}


# ══════════════════════════════════════════════════════════════
# R109 — MEMORY VALIDATION PIPELINE
# ══════════════════════════════════════════════════════════════
class MemoryValidationPipeline:
    """Treat memory like production data: validate before promotion.
    Isolate experimental beliefs. Prevent corruption cascade."""
    INTERVAL        = 120
    QUARANTINE_CONF = 0.30   # beliefs below this → quarantine before promotion

    def __init__(self):
        self.last_run     = 0.0
        self._quarantine: set[int] = set()
        self.validated    = 0
        self.quarantined  = 0
        self.promoted     = 0
        self._ensure_tables()

    def _ensure_tables(self):
        try:
            with _db() as c:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS belief_quarantine (
                        belief_id   INTEGER PRIMARY KEY,
                        reason      TEXT,
                        quarantine_ts TEXT,
                        release_ts  TEXT
                    )
                """)
                # commit handled by _db() context manager
        except Exception: pass

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        try:
            # Quarantine very new low-conf beliefs
            with _db() as c:
                rows = c.execute("""
                    SELECT id, confidence, topic FROM beliefs
                    WHERE confidence < ? AND locked=0
                      AND last_referenced > ?
                    LIMIT 20
                """, (self.QUARANTINE_CONF,
                      datetime.now(timezone.utc)
                      .replace(hour=0).isoformat())).fetchall()

            for r in rows:
                if r["id"] not in self._quarantine:
                    self._quarantine.add(r["id"])
                    self.quarantined += 1
                    with _db() as c:
                        c.execute("""
                            INSERT OR IGNORE INTO belief_quarantine
                              (belief_id, reason, quarantine_ts)
                            VALUES (?,?,?)
                        """, (r["id"], f"low_conf={r['confidence']:.2f}",
                              _ts()))
                        # commit handled by _db() context manager

            # Release quarantine for beliefs that improved
            for bid in list(self._quarantine):
                with _db() as c:
                    row = c.execute(
                        "SELECT confidence FROM beliefs WHERE id=?", (bid,)
                    ).fetchone()
                if row and row["confidence"] >= self.QUARANTINE_CONF + 0.10:
                    self._quarantine.discard(bid)
                    self.promoted += 1
                    with _db() as c:
                        c.execute(
                            "UPDATE belief_quarantine SET release_ts=? WHERE belief_id=?",
                            (_ts(), bid)
                        )
                        # commit handled by _db() context manager

            self.validated += len(rows)
        except Exception as e:
            _log(f"[MVP] error: {e}")

    def status(self) -> dict:
        return {"quarantined": self.quarantined,
                "active_quarantine": len(self._quarantine),
                "promoted": self.promoted, "validated": self.validated}


# ══════════════════════════════════════════════════════════════
# R110 — GOAL INFERENCE ENGINE
# ══════════════════════════════════════════════════════════════
class GoalInferenceEngine:
    """Infer implicit goals from behavior. Adjust system will dynamically.
    Multi-agent coordination pattern."""
    INTERVAL = 60

    def __init__(self):
        self.last_run      = 0.0
        self._behavior_log: deque[str] = deque(maxlen=50)
        self.inferred_goal = "seek_truth"
        self.inferences    = 0

    def observe_behavior(self, action: str):
        self._behavior_log.append(action)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        if not self._behavior_log: return

        actions = list(self._behavior_log)
        counts: dict[str, int] = defaultdict(int)
        for a in actions:
            for keyword, goal in [
                ("resolve", "resolve_contradictions"),
                ("prune",   "compress_and_prune"),
                ("delete",  "compress_and_prune"),
                ("expand",  "expand_knowledge"),
                ("search",  "expand_knowledge"),
                ("identity","strengthen_identity"),
                ("tension", "reduce_tension"),
            ]:
                if keyword in a.lower():
                    counts[goal] += 1

        if counts:
            inferred = max(counts, key=lambda x: counts[x])
            if inferred != self.inferred_goal:
                self.inferred_goal = inferred
                self.inferences   += 1
                _log(f"[GIE] Inferred goal: {inferred} "
                     f"(from {len(actions)} behaviors)")

    def status(self) -> dict:
        return {"inferred_goal": self.inferred_goal,
                "inferences": self.inferences,
                "behavior_window": len(self._behavior_log)}


# ══════════════════════════════════════════════════════════════
# R111 — DRIVE-BASED MOTIVATION SYSTEM
# ══════════════════════════════════════════════════════════════
class DriveBasedMotivationSystem:
    """Competing drives: explore / resolve / compress / stabilize.
    Weight them dynamically. Behavior-based agent architecture."""
    INTERVAL = 30
    DRIVES   = ["explore", "resolve", "compress", "stabilize"]

    def __init__(self):
        self.last_run = 0.0
        self.weights  = {"explore": 0.25, "resolve": 0.25,
                         "compress": 0.25, "stabilize": 0.25}
        self.dominant_drive = "stabilize"
        self._history: deque[str] = deque(maxlen=30)
        self.drive_switches = 0

    def tick(self, avg_conf: float = 0.50, tension: float = 0.0,
              belief_count: int = 1000, coherence: float = 0.50):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        raw = {
            "explore":    max(0.0, avg_conf - 0.50) * 2.0 + 0.10,
            "resolve":    tension * 1.8,
            "compress":   max(0.0, (belief_count - 1200) / 800),
            "stabilize":  max(0.0, 0.60 - coherence) * 1.5 + 0.10,
        }
        total = sum(raw.values()) or 1.0
        self.weights = {k: round(v / total, 3) for k, v in raw.items()}

        new_dominant = max(self.weights, key=lambda x: self.weights[x])
        if new_dominant != self.dominant_drive:
            self.drive_switches += 1
            _log(f"[DBMS] Drive: {self.dominant_drive} → {new_dominant}")
            self.dominant_drive = new_dominant
        self._history.append(self.dominant_drive)

    def status(self) -> dict:
        return {"dominant": self.dominant_drive,
                "weights": self.weights,
                "switches": self.drive_switches,
                "recent": list(self._history)[-5:]}


# ══════════════════════════════════════════════════════════════
# R112 — ACTION SIMULATION BEFORE EXECUTION
# ══════════════════════════════════════════════════════════════
class ActionSimulationBeforeExecution:
    """Simulate expected outcomes before acting. Reject low-quality pre-execution."""
    REJECT_THRESHOLD = 0.25

    def __init__(self):
        self.simulations = 0
        self.rejected    = 0
        self.approved    = 0

    def simulate(self, action: str, context: dict,
                  current_conf: float = 0.50,
                  tension: float = 0.0) -> dict:
        self.simulations += 1

        # Estimate expected outcomes based on action type + context
        action_l = action.lower()
        expected_conf_delta = 0.0
        expected_tension_delta = 0.0
        risk = 0.0

        if "delete" in action_l or "prune" in action_l:
            expected_conf_delta    = 0.02    # slight conf boost from cleanup
            expected_tension_delta = -0.05   # tension reduction
            risk = 0.15 if current_conf > 0.70 else 0.05
        elif "merge" in action_l:
            expected_conf_delta    = 0.04
            expected_tension_delta = -0.03
            risk = 0.10
        elif "resolve" in action_l:
            expected_conf_delta    = 0.03
            expected_tension_delta = -0.10
            risk = 0.05
        elif "expand" in action_l or "search" in action_l:
            expected_conf_delta    = 0.01
            expected_tension_delta = 0.05    # more info → more tension
            risk = 0.20
        else:
            expected_conf_delta    = 0.00
            expected_tension_delta = 0.01
            risk = 0.30

        expected_value = (
            expected_conf_delta * 0.5
            - expected_tension_delta * 0.3
            - risk * 0.2
        )

        should_execute = expected_value > self.REJECT_THRESHOLD * 0.5

        if not should_execute:
            self.rejected += 1
        else:
            self.approved += 1

        return {
            "action": action,
            "expected_conf_delta":    round(expected_conf_delta, 3),
            "expected_tension_delta": round(expected_tension_delta, 3),
            "risk":           round(risk, 3),
            "expected_value": round(expected_value, 3),
            "should_execute": should_execute,
        }

    def tick(self): pass

    def status(self) -> dict:
        return {"simulations": self.simulations,
                "rejected": self.rejected, "approved": self.approved,
                "reject_rate": round(self.rejected / max(self.simulations, 1), 3)}


# ══════════════════════════════════════════════════════════════
# R113 — FAILURE-BASED LEARNING PRIORITY
# ══════════════════════════════════════════════════════════════
class FailureBasedLearningPriority:
    """Weight failures higher than successes. Store 'what not to do'."""
    FAILURE_WEIGHT = 2.5   # failures count 2.5x vs successes
    INTERVAL       = 90

    def __init__(self):
        self.last_run  = 0.0
        self._do_not:  dict[str, float] = {}   # pattern → penalty_score
        self._avoid:   deque[dict] = deque(maxlen=100)
        self.recorded  = 0

    def record_failure(self, pattern: str, severity: float,
                        context: str = ""):
        self.recorded += 1
        current = self._do_not.get(pattern, 0.0)
        self._do_not[pattern] = min(1.0, current + severity * self.FAILURE_WEIGHT)
        self._avoid.append({
            "pattern": pattern, "severity": severity,
            "context": context[:100], "ts": _ts()
        })
        _log(f"[FBLP] Failure recorded: {pattern!r} "
             f"severity={severity:.2f} score={self._do_not[pattern]:.2f}")

    def should_avoid(self, pattern: str) -> tuple[bool, float]:
        score = self._do_not.get(pattern, 0.0)
        return score > 0.50, score

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        # Natural decay of failure scores
        for k in list(self._do_not.keys()):
            self._do_not[k] = max(0.0, self._do_not[k] - 0.02)
            if self._do_not[k] == 0.0:
                del self._do_not[k]

    def status(self) -> dict:
        top = sorted(self._do_not.items(), key=lambda x: -x[1])[:5]
        return {"recorded": self.recorded,
                "active_penalties": len(self._do_not),
                "top_avoidances": dict(top)}


# ══════════════════════════════════════════════════════════════
# R114 — AGENT COORDINATION CONTROL (INTERNAL)
# ══════════════════════════════════════════════════════════════
class AgentCoordinationControl:
    """Central controller guides sub-agents (debate, modules).
    Prevents drift. Multi-agent research architecture."""
    INTERVAL = 45

    def __init__(self):
        self.last_run      = 0.0
        self._agent_states: dict[str, dict] = {}
        self._drift_count: dict[str, int]   = defaultdict(int)
        self.corrections   = 0

    def register_agent(self, agent_id: str, current_intent: str,
                        confidence: float):
        self._agent_states[agent_id] = {
            "intent": current_intent,
            "confidence": confidence,
            "ts": _ts(),
        }

    def tick(self, system_intent: str = "seek_truth"):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        for agent_id, state in self._agent_states.items():
            # Check if agent intent drifts from system intent
            agent_intent = state.get("intent", "")
            if (agent_intent and system_intent and
                    agent_intent != system_intent):
                self._drift_count[agent_id] += 1
                if self._drift_count[agent_id] >= 3:
                    self.corrections += 1
                    self._agent_states[agent_id]["intent"] = system_intent
                    self._drift_count[agent_id] = 0
                    _log(f"[ACC] Corrected agent {agent_id}: "
                         f"{agent_intent!r} → {system_intent!r}")

    def status(self) -> dict:
        drifting = {k: v for k, v in self._drift_count.items() if v > 0}
        return {"agents": len(self._agent_states),
                "corrections": self.corrections,
                "drifting": drifting}


# ══════════════════════════════════════════════════════════════
# R115 — CONTINUOUS POLICY EVOLUTION
# ══════════════════════════════════════════════════════════════
class ContinuousPolicyEvolution:
    """Maintain evolving policy for how decisions are made.
    Update based on outcomes + patterns. RL-like behavior."""
    INTERVAL = 180

    def __init__(self):
        self.last_run = 0.0
        self._policy  = _load_json(POLICY_F, {
            "prune_threshold":   0.25,
            "insight_threshold": 0.55,
            "merge_threshold":   0.65,
            "tension_threshold": 0.60,
            "debate_threshold":  0.45,
            "version":           1,
            "updates":           0,
        })
        self.updates  = self._policy.get("updates", 0)

    def _update_policy(self, outcomes: list[dict]):
        """Nudge policy parameters based on recent outcomes."""
        if not outcomes: return

        # Compute success rate
        successes = [o for o in outcomes if o.get("success", False)]
        rate      = len(successes) / len(outcomes)

        # RL-like: if success rate high → be more aggressive
        #           if success rate low  → be more conservative
        adj = 0.01 if rate > 0.65 else -0.01

        self._policy["prune_threshold"]   = round(
            max(0.10, min(0.45, self._policy.get("prune_threshold", 0.50)   + adj)), 3)
        self._policy["insight_threshold"] = round(
            max(0.40, min(0.80, self._policy.get("insight_threshold", 0.50) - adj)), 3)
        self._policy["merge_threshold"]   = round(
            max(0.50, min(0.85, self._policy.get("merge_threshold", 0.50)   + adj * 0.5)), 3)
        self._policy["tension_threshold"] = round(
            max(0.40, min(0.80, self._policy.get("tension_threshold", 0.50) - adj * 0.5)), 3)

        self._policy["version"] += 1
        self._policy["updates"] += 1
        self.updates += 1
        _save_json(POLICY_F, self._policy)
        _log(f"[CPE] Policy v{self._policy.get('version', 0.50)} updated "
             f"(rate={rate:.2f} adj={adj:+.2f})")

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        # Sample recent belief mutations as outcome proxy
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT confidence, outcome_count, reinforce_count
                    FROM beliefs
                    WHERE reinforce_count > 0
                    ORDER BY last_referenced DESC LIMIT 30
                """).fetchall()

            outcomes = []
            for r in rows:
                ratio   = r["outcome_count"] / max(r["reinforce_count"], 1)
                success = ratio > 0.15 and r["confidence"] > 0.50
                outcomes.append({"success": success, "conf": r["confidence"]})

            self._update_policy(outcomes)
        except Exception as e:
            _log(f"[CPE] error: {e}")

    def get_threshold(self, name: str) -> float:
        return self._policy.get(name, 0.50)

    def status(self) -> dict:
        return {"policy": self._policy, "updates": self.updates}


# ══════════════════════════════════════════════════════════════
# R115 ORCHESTRATOR
# ══════════════════════════════════════════════════════════════
class NexR115:
    def __init__(self):
        _log("[r115] Initialising R101–R115 research stack (15 modules)...")

        self.edl   = ExperienceDistillationLayer()
        self.catl  = CriticalActionTrainingLoop()
        self.msfp  = MultiStageFeedbackPipeline()
        self.ril   = ReflectionInLoop()
        self.sl    = StrategyLibrary()
        self.hpl   = HierarchicalPlanningLayer()
        self.tes   = ToolEnvironmentSpecialization()
        self.shl   = SelfHealingSystemLoop()
        self.mvp   = MemoryValidationPipeline()
        self.gie   = GoalInferenceEngine()
        self.dbms  = DriveBasedMotivationSystem()
        self.asbe  = ActionSimulationBeforeExecution()
        self.fblp  = FailureBasedLearningPriority()
        self.acc   = AgentCoordinationControl()
        self.cpe   = ContinuousPolicyEvolution()

        self._cycle = 0
        _log("[r115] All 15 modules ready ✓")

    def tick(self, avg_conf: float = 0.50, tension: float = 0.0,
             coherence: float = 0.50, belief_count: int = 1000,
             contradiction_count: int = 0, phase: str = "stable"):
        self._cycle += 1

        # Core cognition
        self.hpl.tick(avg_conf, contradiction_count, belief_count)
        self.dbms.tick(avg_conf, tension, belief_count, coherence)
        self.gie.tick()
        self.sl.tick()

        # Learning + evolution
        self.edl.tick()
        self.catl.tick()
        self.cpe.tick()
        self.fblp.tick()

        # Memory + validation
        self.mvp.tick()

        # Coordination + health
        self.acc.tick(self.gie.inferred_goal)
        self.shl.tick()

    def get_status(self) -> dict:
        return {
            "cycle":  self._cycle,
            "edl":    self.edl.status(),
            "catl":   self.catl.status(),
            "msfp":   self.msfp.status(),
            "ril":    self.ril.status(),
            "sl":     self.sl.status(),
            "hpl":    self.hpl.status(),
            "tes":    self.tes.status(),
            "shl":    self.shl.status(),
            "mvp":    self.mvp.status(),
            "gie":    self.gie.status(),
            "dbms":   self.dbms.status(),
            "asbe":   self.asbe.status(),
            "fblp":   self.fblp.status(),
            "acc":    self.acc.status(),
            "cpe":    self.cpe.status(),
        }

    def format_status(self) -> str:
        s = self.get_status()
        lines = [
            f"⚙️ *NEX R101–R115* — cycle {s['cycle']}",
            f"🎯 Goal: {s['hpl']['goal']} | "
              f"Drive: {s['dbms']['dominant']} (switches={s['dbms']['switches']})",
            f"🧭 Inferred intent: {s['gie']['inferred_goal']}",
            f"📚 Strategies: {s['sl']['strategies']} "
              f"promoted={s['sl']['promoted']}",
            f"🧬 Experience: distilled={s['edl']['distilled']} "
              f"strategies={s['edl']['strategies']}",
            f"🎓 ACT judgment: {s['catl']['correct']}/{s['catl']['total']} "
              f"rate={s['catl']['rate']}",
            f"🔄 PolicyV{s['cpe']['policy']['version']}: "
              f"prune={s['cpe']['policy']['prune_threshold']} "
              f"tension={s['cpe']['policy']['tension_threshold']}",
            f"🏥 SelfHeal: heals={s['shl']['heals']} resets={s['shl']['resets']}",
            f"🔬 MemValidation: quarantined={s['mvp']['quarantined']} "
              f"promoted={s['mvp']['promoted']}",
            f"❌ Failures: {s['fblp']['recorded']} "
              f"active={s['fblp']['active_penalties']}",
            f"🤝 Agents: {s['acc']['agents']} corrections={s['acc']['corrections']}",
            f"🔭 PreSim: approved={s['asbe']['approved']} "
              f"rejected={s['asbe']['rejected']}",
            f"📊 PipelineHealth: {s['msfp']['health']}",
        ]
        return "\n".join(lines)


_singleton: NexR115 | None = None
_lock = threading.Lock()

def get_r115() -> NexR115:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = NexR115()
    return _singleton
