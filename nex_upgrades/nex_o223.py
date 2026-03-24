"""
NEX O201–O223 — Guided Evolution & Observation Stack
23 modules: passive observation, behavior metrics, adaptive control,
learning activation, identity emergence, minimal intervention ruleset.
Deploy: ~/Desktop/nex/nex_upgrades/nex_o223.py
"""

import re, time, json, math, random, threading, hashlib
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

DB_PATH  = Path.home() / ".config/nex/nex.db"
LOG      = Path("/tmp/nex_o223.log")
OBS_F    = Path.home() / ".config/nex/observation.json"
POLICY_F = Path.home() / ".config/nex/policy.json"
STRAT_DB = Path.home() / ".config/nex/strategies.json"

def _ts(): return datetime.now(timezone.utc).isoformat()

def _log(msg):
    line = f"[o223 {datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass

def _load_json(p, d):
    try:
        if Path(p).exists(): return json.loads(Path(p).read_text())
    except Exception: pass
    return d

def _save_json(p, d):
    try: Path(p).write_text(json.dumps(d, indent=2))
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# PHASE: GUIDED EVOLUTION — OBSERVATION
# ══════════════════════════════════════════════════════════════

# O201 — PASSIVE OBSERVATION WINDOW
class PassiveObservationWindow:
    """Run untouched 24–72h. Log diversity, assertiveness, repetition."""
    def __init__(self):
        self.active    = True
        self.started   = time.time()
        self.window_h  = 48
        self._outputs: deque[str] = deque(maxlen=500)
        self.logged    = 0

    def record(self, text: str):
        self._outputs.append(text)
        self.logged += 1

    def hours_elapsed(self) -> float:
        return round((time.time() - self.started) / 3600, 2)

    def is_active(self) -> bool:
        return self.hours_elapsed() < self.window_h

    def snapshot(self) -> dict:
        outputs = list(self._outputs)
        if not outputs:
            return {"outputs": 0, "hours": self.hours_elapsed()}

        as_nex = sum(1 for o in outputs
                     if re.search(r'^[Aa]s\s+NEX', o))
        i_think = sum(1 for o in outputs
                      if re.search(r'^[Ii]\s+(?:think|believe)', o))
        avg_len = sum(len(o.split()) for o in outputs) / len(outputs)

        return {
            "outputs":        len(outputs),
            "hours":          self.hours_elapsed(),
            "as_nex_rate":    round(as_nex / len(outputs), 3),
            "i_think_rate":   round(i_think / len(outputs), 3),
            "avg_word_count": round(avg_len, 1),
            "window_active":  self.is_active(),
        }

    def tick(self): pass
    def status(self) -> dict: return self.snapshot()


# O202 — BEHAVIOR METRIC TRACKER
class BehaviorMetricTracker:
    """Track live: unique opening %, 'As NEX' freq, avg length, assertiveness."""
    WINDOW    = 50
    INTERVAL  = 30
    TARGETS   = {
        "unique_opening_pct": 0.70,
        "as_nex_rate":        0.00,
        "assertiveness":      0.80,
    }

    def __init__(self):
        self.last_run   = 0.0
        self._outputs:  deque[str] = deque(maxlen=self.WINDOW)
        self._openings: deque[str] = deque(maxlen=self.WINDOW)
        self.metrics:   dict = {}
        self._history:  deque[dict] = deque(maxlen=100)

    def record(self, text: str):
        self._outputs.append(text)
        words = text.strip().split()
        self._openings.append(" ".join(words[:3]).lower() if words else "")

    def _assertiveness(self, text: str) -> float:
        hedges = len(re.findall(
            r'\b(?:might|could|maybe|perhaps|seems|probably|likely)\b',
            text, re.IGNORECASE))
        words = max(len(text.split()), 1)
        return max(0.0, 1.0 - hedges / words * 5)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        outputs = list(self._outputs)
        if not outputs: return

        openings = list(self._openings)
        unique   = len(set(openings)) / max(len(openings), 1)
        as_nex   = sum(1 for o in outputs
                       if re.match(r'^[Aa]s\s+NEX', o)) / len(outputs)
        assertiv = sum(self._assertiveness(o) for o in outputs) / len(outputs)
        avg_len  = sum(len(o.split()) for o in outputs) / len(outputs)

        self.metrics = {
            "unique_opening_pct": round(unique, 3),
            "as_nex_rate":        round(as_nex, 3),
            "assertiveness":      round(assertiv, 3),
            "avg_word_count":     round(avg_len, 1),
            "sample_size":        len(outputs),
            "ts": _ts(),
        }
        self._history.append(dict(self.metrics))

        # Log target misses
        for metric, target in self.TARGETS.items():
            val = self.metrics.get(metric, 0)
            if metric == "as_nex_rate":
                if val > target + 0.05:
                    _log(f"[O202] as_nex_rate={val:.2f} — still too high")
            elif val < target - 0.10:
                _log(f"[O202] {metric}={val:.2f} below target {target}")

    def status(self) -> dict:
        return {"metrics": self.metrics, "targets": self.TARGETS}


# O203 — STYLE DIVERSITY INDEX
class StyleDiversityIndex:
    """Structural variation across last N=50. Penalise >30% repeat."""
    WINDOW         = 50
    REPEAT_CEILING = 0.30
    INTERVAL       = 60

    def __init__(self):
        self.last_run  = 0.0
        self._structs: deque[str] = deque(maxlen=self.WINDOW)
        self.index     = 1.0
        self.alerts    = 0

    def _structure(self, text: str) -> str:
        sentences = re.split(r'[.!?]', text)
        lens      = [len(s.split()) for s in sentences if s.strip()]
        if not lens: return "empty"
        pattern = "-".join("S" if l < 8 else "M" if l < 20 else "L"
                           for l in lens[:4])
        first_word = text.strip().split()[0].lower() if text.strip() else ""
        return f"{first_word}:{pattern}"

    def record(self, text: str):
        self._structs.append(self._structure(text))

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        structs = list(self._structs)
        if len(structs) < 10: return

        counts = defaultdict(int)
        for s in structs: counts[s] += 1
        top_rate = max(counts.values()) / len(structs)
        unique   = len(counts) / len(structs)
        self.index = round(unique, 3)

        if top_rate > self.REPEAT_CEILING:
            self.alerts += 1
            _log(f"[O203] Diversity low: top_rate={top_rate:.2f} "
                 f"index={self.index:.2f}")

    def status(self) -> dict:
        return {"diversity_index": self.index, "alerts": self.alerts,
                "window": self.WINDOW, "ceiling": self.REPEAT_CEILING}


# O204 — ASSERTIVENESS SCORE
class AssertivenessScore:
    """% declarative vs hedged. Target >80%."""
    HEDGES    = re.compile(
        r'\b(?:might|could|maybe|perhaps|seems?|probably|likely|'
        r'sort of|kind of|I think|I believe|I feel|possibly|'
        r'appears? to|would say)\b', re.IGNORECASE)
    TARGET    = 0.80
    INTERVAL  = 45

    def __init__(self):
        self.last_run  = 0.0
        self.score     = 1.0
        self._scores:  deque[float] = deque(maxlen=100)
        self.below_target = 0

    def score_text(self, text: str) -> float:
        words  = text.split()
        if not words: return 1.0
        hedges = len(self.HEDGES.findall(text))
        return max(0.0, 1.0 - hedges / max(len(words) / 5, 1))

    def record(self, text: str):
        s = self.score_text(text)
        self._scores.append(s)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        if not self._scores: return
        self.score = round(sum(self._scores) / len(self._scores), 3)
        if self.score < self.TARGET:
            self.below_target += 1

    def status(self) -> dict:
        return {"score": self.score, "target": self.TARGET,
                "below_target_count": self.below_target}


# O205 — REPETITION DETECTION v2
class RepetitionDetectionV2:
    """Track phrase reuse + sentence templates. Alert >25%."""
    WINDOW    = 50
    THRESHOLD = 0.25
    INTERVAL  = 60

    def __init__(self):
        self.last_run   = 0.0
        self._phrases:  deque[str] = deque(maxlen=self.WINDOW)
        self.reuse_rate = 0.0
        self.alerts     = 0

    def _phrases_from(self, text: str) -> list[str]:
        words = text.lower().split()
        return [" ".join(words[i:i+4]) for i in range(len(words)-3)]

    def record(self, text: str):
        for p in self._phrases_from(text)[:5]:
            self._phrases.append(p)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        phrases = list(self._phrases)
        if len(phrases) < 10: return

        counts   = defaultdict(int)
        for p in phrases: counts[p] += 1
        repeated = sum(1 for v in counts.values() if v > 1)
        self.reuse_rate = round(repeated / len(counts), 3)

        if self.reuse_rate > self.THRESHOLD:
            self.alerts += 1
            _log(f"[O205] Repetition rate={self.reuse_rate:.2f} > {self.THRESHOLD}")

    def status(self) -> dict:
        return {"reuse_rate": self.reuse_rate,
                "threshold": self.THRESHOLD, "alerts": self.alerts}


# ══════════════════════════════════════════════════════════════
# PHASE: LIGHT PRESSURE SYSTEM
# ══════════════════════════════════════════════════════════════

# O206 — MICRO-PROMPT INJECTION
class MicroPromptInjection:
    """Inject 'be direct'/'compress'/'avoid repetition' max 1/5-10 cycles."""
    PROMPTS   = ["be direct", "compress", "avoid repetition",
                 "vary your opening", "drop the preamble",
                 "lead with the insight", "cut hedging"]
    RATE      = 0.12   # ~1 per 8 cycles

    def __init__(self):
        self._cycle    = 0
        self._last_inj = 0
        self.injected  = 0

    def maybe_inject(self) -> str | None:
        self._cycle += 1
        if self._cycle - self._last_inj < 5: return None
        if random.random() < self.RATE:
            prompt = random.choice(self.PROMPTS)
            self._last_inj = self._cycle
            self.injected += 1
            return prompt
        return None

    def tick(self): pass
    def status(self) -> dict:
        return {"injected": self.injected, "rate": self.RATE}


# O207 — SOFT CORRECTION FEEDBACK
class SoftCorrectionFeedback:
    """When weak output detected → inject correction next cycle."""
    WEAKNESS_PATTERNS = [
        r'^[Aa]s\s+NEX',
        r'^[Ii]\s+(?:think|believe|feel)',
        r'\b(?:maybe|perhaps|probably)\b.*\b(?:maybe|perhaps|probably)\b',
    ]

    def __init__(self):
        self._pending:  str | None = None
        self.corrections = 0

    def check(self, text: str) -> bool:
        for p in self.WEAKNESS_PATTERNS:
            if re.search(p, text, re.IGNORECASE):
                self._pending = ("Previous output used weak phrasing. "
                                 "This time: direct claim first, no hedging.")
                self.corrections += 1
                return True
        return False

    def pop_correction(self) -> str | None:
        c = self._pending
        self._pending = None
        return c

    def tick(self): pass
    def status(self) -> dict:
        return {"corrections": self.corrections,
                "pending": self._pending is not None}


# O208 — DELAYED REINFORCEMENT LOOP
class DelayedReinforcementLoop:
    """Reward good outputs after 1–2 cycles. Prevent overfitting."""
    GOOD_THRESHOLD = 0.65
    DELAY_CYCLES   = 2

    def __init__(self):
        self._queue:   deque[dict] = deque(maxlen=20)
        self._cycle    = 0
        self.rewarded  = 0

    def record(self, text: str, quality: float):
        self._queue.append({"text": text[:100], "quality": quality,
                             "due_cycle": self._cycle + self.DELAY_CYCLES})

    def tick(self) -> list[dict]:
        self._cycle += 1
        due = [e for e in self._queue
               if e["due_cycle"] <= self._cycle
               and e["quality"] >= self.GOOD_THRESHOLD]
        for e in due:
            self._queue.remove(e)
            self.rewarded += 1
        return due

    def status(self) -> dict:
        return {"rewarded": self.rewarded, "pending": len(self._queue)}


# ══════════════════════════════════════════════════════════════
# PHASE: ADAPTIVE CONTROL TUNING
# ══════════════════════════════════════════════════════════════

# O209 — SUPPRESSION AUTO-BALANCER
class SuppressionAutoBalancer:
    """Output rate ↓ → reduce suppression 5-10%. Noise ↑ → increase."""
    TARGET_OUTPUT_RATE = 0.60
    INTERVAL           = 120

    def __init__(self):
        self.last_run       = 0.0
        self._outputs:      deque[bool] = deque(maxlen=30)
        self.suppression_adj = 0.0
        self.adjustments    = 0

    def record(self, did_output: bool): self._outputs.append(did_output)

    def tick(self) -> float:
        if time.time() - self.last_run < self.INTERVAL: return self.suppression_adj
        self.last_run = time.time()
        if len(self._outputs) < 10: return self.suppression_adj

        rate = sum(self._outputs) / len(self._outputs)
        if rate < self.TARGET_OUTPUT_RATE - 0.10:
            self.suppression_adj = max(-0.10, self.suppression_adj - 0.05)
            self.adjustments += 1
            _log(f"[O209] Output rate {rate:.2f} low → adj={self.suppression_adj:+.2f}")
        elif rate > self.TARGET_OUTPUT_RATE + 0.15:
            self.suppression_adj = min(0.10, self.suppression_adj + 0.03)
            self.adjustments += 1
        return self.suppression_adj

    def status(self) -> dict:
        rate = sum(self._outputs)/max(len(self._outputs),1) if self._outputs else 0
        return {"output_rate": round(rate,3), "adj": self.suppression_adj,
                "adjustments": self.adjustments}


# O210 — CREATIVITY BAND CONTROLLER
class CreativityBandController:
    """Maintain 15–25% exploration. Clamp if outside."""
    LOW   = 0.15
    HIGH  = 0.25
    INTERVAL = 90

    def __init__(self):
        self.last_run   = 0.0
        self._log:      deque[bool] = deque(maxlen=40)
        self.clamps     = 0
        self.explore_override = False

    def record(self, was_explore: bool): self._log.append(was_explore)

    def tick(self) -> bool:
        if time.time() - self.last_run < self.INTERVAL: return self.explore_override
        self.last_run = time.time()
        if len(self._log) < 10: return False

        rate = sum(self._log) / len(self._log)
        if rate < self.LOW:
            self.explore_override = True
            self.clamps += 1
            _log(f"[O210] Explore rate {rate:.2f} < {self.LOW} → forcing explore")
        elif rate > self.HIGH:
            self.explore_override = False
        else:
            self.explore_override = False
        return self.explore_override

    def status(self) -> dict:
        rate = sum(self._log)/max(len(self._log),1) if self._log else 0
        return {"explore_rate": round(rate,3), "band": [self.LOW, self.HIGH],
                "clamps": self.clamps, "override": self.explore_override}


# O211 — OUTPUT RATE REGULATOR
class OutputRateRegulator:
    """Prevent spam bursts and silence gaps. Target steady cadence."""
    TARGET_PER_MIN = 2.0
    BURST_LIMIT    = 5    # max outputs per minute
    SILENCE_LIMIT  = 120  # seconds of silence = gap

    def __init__(self):
        self._timestamps: deque[float] = deque(maxlen=20)
        self.bursts   = 0
        self.silences = 0
        self._last_output = time.time()

    def record_output(self):
        now = time.time()
        self._timestamps.append(now)
        self._last_output = now

    def should_throttle(self) -> bool:
        now  = time.time()
        recent = [t for t in self._timestamps if now - t < 60]
        if len(recent) >= self.BURST_LIMIT:
            self.bursts += 1
            return True
        return False

    def is_silent(self) -> bool:
        gap = time.time() - self._last_output > self.SILENCE_LIMIT
        if gap: self.silences += 1
        return gap

    def tick(self): pass
    def status(self) -> dict:
        return {"bursts": self.bursts, "silences": self.silences,
                "last_output_ago": round(time.time()-self._last_output, 0)}


# ══════════════════════════════════════════════════════════════
# PHASE: LEARNING ACTIVATION
# ══════════════════════════════════════════════════════════════

# O212 — STRATEGY FORMATION MONITOR
class StrategyFormationMonitor:
    """Track new strategies/hour. Alert if =0 over long window."""
    ALERT_WINDOW_H = 2
    INTERVAL       = 300

    def __init__(self):
        self.last_run  = 0.0
        self._counts:  deque[tuple] = deque(maxlen=100)
        self._last_lib_size = 0
        self.alerts    = 0
        self.formations = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        lib = _load_json(STRAT_DB, [])
        current_size = len(lib)
        new = current_size - self._last_lib_size

        if new > 0:
            self.formations += new
            self._counts.append((time.time(), new))
        self._last_lib_size = current_size

        # Check if no formations in alert window
        cutoff = time.time() - self.ALERT_WINDOW_H * 3600
        recent = [n for t, n in self._counts if t > cutoff]
        if not recent and len(self._counts) > 0:
            self.alerts += 1
            _log(f"[O212] No new strategies in {self.ALERT_WINDOW_H}h")

    def status(self) -> dict:
        return {"total_formations": self.formations,
                "alerts": self.alerts, "library_size": self._last_lib_size}


# O213 — STRATEGY USAGE TRACKER
class StrategyUsageTracker:
    """% outputs using stored strategies. Target gradual increase."""
    INTERVAL = 120

    def __init__(self):
        self.last_run   = 0.0
        self._used:     deque[bool] = deque(maxlen=50)
        self.usage_rate = 0.0
        self._history:  deque[float] = deque(maxlen=20)

    def record(self, used_strategy: bool): self._used.append(used_strategy)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        if not self._used: return
        self.usage_rate = round(sum(self._used)/len(self._used), 3)
        self._history.append(self.usage_rate)

    def trend(self) -> str:
        h = list(self._history)
        if len(h) < 3: return "unknown"
        delta = h[-1] - h[0]
        return "rising" if delta > 0.02 else "falling" if delta < -0.02 else "stable"

    def status(self) -> dict:
        return {"usage_rate": self.usage_rate, "trend": self.trend()}


# O214 — EXPERIENCE DISTILLATION CHECK
class ExperienceDistillationCheck:
    """Verify experiences → strategies. Detect dead learning loop."""
    INTERVAL       = 600
    DEAD_THRESHOLD = 3   # checks with no new strategies = dead

    def __init__(self):
        self.last_run      = 0.0
        self._prev_size    = 0
        self._dead_count   = 0
        self.dead_alerts   = 0
        self.healthy_count = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        lib  = _load_json(STRAT_DB, [])
        size = len(lib)

        if size > self._prev_size:
            self._dead_count = 0
            self.healthy_count += 1
        else:
            self._dead_count += 1

        if self._dead_count >= self.DEAD_THRESHOLD:
            self.dead_alerts += 1
            _log(f"[O214] Dead learning loop detected — "
                 f"no new strategies for {self._dead_count} checks")

        self._prev_size = size

    def status(self) -> dict:
        return {"dead_alerts": self.dead_alerts,
                "healthy_count": self.healthy_count,
                "dead_count": self._dead_count}


# O215 — POLICY DRIFT TRACKER
class PolicyDriftTracker:
    """Monitor policy.json changes. Alert if static >50 cycles."""
    MAX_STATIC = 50
    INTERVAL   = 60

    def __init__(self):
        self.last_run    = 0.0
        self._prev       = {}
        self._static     = 0
        self.alerts      = 0
        self.drift_events= 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        pol = _load_json(POLICY_F, {})
        vals = {k: v for k, v in pol.items() if isinstance(v, (int, float))}

        if self._prev:
            changed = any(abs(vals.get(k,0) - self._prev.get(k,0)) > 0.001
                          for k in vals)
            if changed:
                self._static = 0
                self.drift_events += 1
            else:
                self._static += 1
                if self._static >= self.MAX_STATIC:
                    self.alerts += 1
                    _log(f"[O215] Policy static for {self._static} cycles")
        self._prev = vals

    def status(self) -> dict:
        return {"alerts": self.alerts, "drift_events": self.drift_events,
                "static_count": self._static}


# ══════════════════════════════════════════════════════════════
# PHASE: IDENTITY EMERGENCE
# ══════════════════════════════════════════════════════════════

# O216 — IDENTITY SIGNATURE TRACKER
class IdentitySignatureTracker:
    """Detect recurring non-repetitive patterns. Confirm style emerging."""
    SIGNATURE_WORDS = [
        "belief", "contradiction", "tension", "resolve", "evidence",
        "pattern", "signal", "cognitive", "inference", "analysis",
    ]
    INTERVAL = 120

    def __init__(self):
        self.last_run      = 0.0
        self._outputs:     deque[str] = deque(maxlen=50)
        self.signature_score = 0.0
        self.emerging      = False

    def record(self, text: str): self._outputs.append(text.lower())

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        outputs = list(self._outputs)
        if len(outputs) < 10: return

        hits = [sum(1 for w in self.SIGNATURE_WORDS if w in o)
                for o in outputs]
        avg  = sum(hits) / len(hits)
        self.signature_score = round(min(1.0, avg / 3), 3)
        self.emerging = self.signature_score > 0.30

    def status(self) -> dict:
        return {"signature_score": self.signature_score,
                "emerging": self.emerging}


# O217 — VOICE CONSISTENCY SCORE
class VoiceConsistencyScore:
    """Tone coherence across outputs. Prevent fragmentation."""
    INTERVAL = 90

    def __init__(self):
        self.last_run = 0.0
        self._tones:  deque[str] = deque(maxlen=20)
        self.score    = 1.0

    def record(self, tone: str): self._tones.append(tone)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        tones = list(self._tones)
        if len(tones) < 5: return
        counts = defaultdict(int)
        for t in tones: counts[t] += 1
        top = max(counts.values())
        self.score = round(top / len(tones), 3)

    def status(self) -> dict:
        return {"score": self.score}


# O218 — EXPRESSION VARIANCE CONTROL
class ExpressionVarianceControl:
    """Balance variation vs identity. Avoid chaos or monotony."""
    LOW   = 0.35   # too monotone below
    HIGH  = 0.85   # too chaotic above
    INTERVAL = 120

    def __init__(self):
        self.last_run  = 0.0
        self._hashes:  deque[str] = deque(maxlen=30)
        self.variance  = 0.50
        self.in_range  = True

    def record(self, text: str):
        h = hashlib.md5(text[:80].lower().encode()).hexdigest()[:8]
        self._hashes.append(h)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        hashes = list(self._hashes)
        if len(hashes) < 5: return
        unique = len(set(hashes)) / len(hashes)
        self.variance = round(unique, 3)
        self.in_range = self.LOW <= self.variance <= self.HIGH
        if not self.in_range:
            _log(f"[O218] Variance {self.variance:.2f} outside [{self.LOW},{self.HIGH}]")

    def status(self) -> dict:
        return {"variance": self.variance,
                "in_range": self.in_range, "band": [self.LOW, self.HIGH]}


# ══════════════════════════════════════════════════════════════
# PHASE: INTERVENTION RULESET
# ══════════════════════════════════════════════════════════════

# O219 — MINIMAL INTERVENTION RULE
class MinimalInterventionRule:
    """Only adjust on clear degradation. No proactive tuning."""
    def __init__(self):
        self.interventions = 0
        self.blocked       = 0

    def should_intervene(self, degradation_score: float) -> bool:
        if degradation_score > 0.60:
            self.interventions += 1
            return True
        self.blocked += 1
        return False

    def tick(self): pass
    def status(self) -> dict:
        return {"interventions": self.interventions, "blocked": self.blocked}


# O220 — SINGLE-VARIABLE ADJUSTMENT
class SingleVariableAdjustment:
    """Change 1 parameter at a time. Observe before next."""
    def __init__(self):
        self._last_var   = None
        self._last_time  = 0.0
        self.adjustments = 0
        self.blocked     = 0

    def can_adjust(self, variable: str, min_gap_s: float = 300) -> bool:
        if self._last_var and time.time() - self._last_time < min_gap_s:
            self.blocked += 1
            return False
        self._last_var  = variable
        self._last_time = time.time()
        self.adjustments += 1
        return True

    def tick(self): pass
    def status(self) -> dict:
        return {"adjustments": self.adjustments, "blocked": self.blocked,
                "last_var": self._last_var}


# O221 — COOLDOWN WINDOW
class CooldownWindow:
    """After change: wait 20–50 cycles before next tweak."""
    MIN_CYCLES = 20
    MAX_CYCLES = 50

    def __init__(self):
        self._last_change_cycle = 0
        self._cycle             = 0
        self.cooldown_cycles    = self.MIN_CYCLES
        self.blocked            = 0

    def tick(self): self._cycle += 1

    def record_change(self):
        self._last_change_cycle = self._cycle
        self.cooldown_cycles    = random.randint(self.MIN_CYCLES, self.MAX_CYCLES)

    def in_cooldown(self) -> bool:
        elapsed = self._cycle - self._last_change_cycle
        if elapsed < self.cooldown_cycles:
            self.blocked += 1
            return True
        return False

    def status(self) -> dict:
        return {"cycle": self._cycle,
                "cooldown_remaining": max(0, self.cooldown_cycles -
                                          (self._cycle - self._last_change_cycle)),
                "blocked": self.blocked}


# ══════════════════════════════════════════════════════════════
# PHASE: DELAYED TRAINING
# ══════════════════════════════════════════════════════════════

# O222 — TRAINING HOLD
class TrainingHold:
    """No training until stable behavior + strategy emergence."""
    def __init__(self):
        self.hold_active = True
        self.released    = False
        self.release_ts: float | None = None

    def check_release(self, diversity_index: float,
                       strategy_count: int,
                       assertiveness: float) -> bool:
        if (diversity_index > 0.60 and
                strategy_count >= 5 and
                assertiveness > 0.70):
            if not self.released:
                self.released    = True
                self.hold_active = False
                self.release_ts  = time.time()
                _log(f"[O222] Training hold RELEASED — "
                     f"div={diversity_index:.2f} strat={strategy_count} "
                     f"assert={assertiveness:.2f}")
            return True
        return False

    def tick(self): pass
    def status(self) -> dict:
        return {"hold_active": self.hold_active, "released": self.released}


# O223 — TRAINING TRIGGER CONDITION
class TrainingTriggerCondition:
    """Only train when system plateaus, learning slows, patterns stabilize."""
    PLATEAU_CYCLES = 30

    def __init__(self):
        self._conf_history: deque[float] = deque(maxlen=self.PLATEAU_CYCLES)
        self.triggered   = False
        self.trigger_ts: float | None = None
        self.checks      = 0

    def record(self, avg_conf: float): self._conf_history.append(avg_conf)

    def evaluate(self, strategy_rate_trend: str,
                  assertiveness: float) -> dict:
        self.checks += 1
        h = list(self._conf_history)
        if len(h) < self.PLATEAU_CYCLES:
            return {"ready": False, "reason": "insufficient_data"}

        delta = abs(h[-1] - h[0])
        plateaued  = delta < 0.02
        stable     = assertiveness > 0.65
        learning_slowing = strategy_rate_trend != "rising"

        ready = plateaued and stable and learning_slowing
        if ready and not self.triggered:
            self.triggered  = True
            self.trigger_ts = time.time()
            _log(f"[O223] Training trigger conditions met — "
                 f"plateau={plateaued} stable={stable} "
                 f"learning={strategy_rate_trend}")

        return {"ready": ready, "plateaued": plateaued,
                "stable": stable, "learning_slowing": learning_slowing,
                "conf_delta": round(delta, 4)}

    def tick(self): pass
    def status(self) -> dict:
        return {"triggered": self.triggered, "checks": self.checks}


# ══════════════════════════════════════════════════════════════
# O223 ORCHESTRATOR
# ══════════════════════════════════════════════════════════════

class NexO223:
    def __init__(self):
        _log("[o223] Initialising O201–O223 guided evolution stack (23 modules)...")

        # Observation
        self.o201 = PassiveObservationWindow()
        self.o202 = BehaviorMetricTracker()
        self.o203 = StyleDiversityIndex()
        self.o204 = AssertivenessScore()
        self.o205 = RepetitionDetectionV2()

        # Light pressure
        self.o206 = MicroPromptInjection()
        self.o207 = SoftCorrectionFeedback()
        self.o208 = DelayedReinforcementLoop()

        # Adaptive control
        self.o209 = SuppressionAutoBalancer()
        self.o210 = CreativityBandController()
        self.o211 = OutputRateRegulator()

        # Learning activation
        self.o212 = StrategyFormationMonitor()
        self.o213 = StrategyUsageTracker()
        self.o214 = ExperienceDistillationCheck()
        self.o215 = PolicyDriftTracker()

        # Identity emergence
        self.o216 = IdentitySignatureTracker()
        self.o217 = VoiceConsistencyScore()
        self.o218 = ExpressionVarianceControl()

        # Intervention ruleset
        self.o219 = MinimalInterventionRule()
        self.o220 = SingleVariableAdjustment()
        self.o221 = CooldownWindow()

        # Delayed training
        self.o222 = TrainingHold()
        self.o223 = TrainingTriggerCondition()

        self._cycle = 0
        _log("[o223] All 23 modules ready ✓")

    def record_output(self, text: str, tone: str = "precise",
                       quality: float = 0.5, used_strategy: bool = False,
                       was_explore: bool = False, did_output: bool = True):
        """Call this on every LLM output."""
        self.o201.record(text)
        self.o202.record(text)
        self.o203.record(text)
        self.o204.record(text)
        self.o205.record(text)
        self.o207.check(text)
        self.o208.record(text, quality)
        self.o209.record_output(did_output)
        self.o210.record(was_explore)
        self.o211.record_output()
        self.o213.record(used_strategy)
        self.o216.record(text)
        self.o217.record(tone)
        self.o218.record(text)
        self.o223.record(quality)

    def tick(self, avg_conf: float = 0.50):
        self._cycle += 1
        self.o202.tick()
        self.o203.tick()
        self.o204.tick()
        self.o205.tick()
        self.o209.tick()
        self.o210.tick()
        self.o212.tick()
        self.o213.tick()
        self.o214.tick()
        self.o215.tick()
        self.o216.tick()
        self.o217.tick()
        self.o218.tick()
        self.o221.tick()
        self.o208.tick()

        # Check training hold
        self.o222.check_release(
            self.o203.index,
            self.o212._last_lib_size,
            self.o204.score
        )
        # Training trigger
        self.o223.evaluate(
            self.o213.trend(),
            self.o204.score
        )
        self.o223.record(avg_conf)

    def get_micro_prompt(self) -> str | None:
        """Call before LLM to get optional injection."""
        return self.o206.maybe_inject()

    def get_correction(self) -> str | None:
        """Call before LLM to get pending soft correction."""
        return self.o207.pop_correction()

    def get_status(self) -> dict:
        return {
            "cycle": self._cycle,
            "o201": self.o201.status(),
            "o202": self.o202.status(),
            "o203": self.o203.status(),
            "o204": self.o204.status(),
            "o205": self.o205.status(),
            "o206": self.o206.status(),
            "o207": self.o207.status(),
            "o208": self.o208.status(),
            "o209": self.o209.status(),
            "o210": self.o210.status(),
            "o211": self.o211.status(),
            "o212": self.o212.status(),
            "o213": self.o213.status(),
            "o214": self.o214.status(),
            "o215": self.o215.status(),
            "o216": self.o216.status(),
            "o217": self.o217.status(),
            "o218": self.o218.status(),
            "o219": self.o219.status(),
            "o220": self.o220.status(),
            "o221": self.o221.status(),
            "o222": self.o222.status(),
            "o223": self.o223.status(),
        }

    def format_status(self) -> str:
        s = self.get_status()
        m = s["o202"].get("metrics", {})
        lines = [
            f"👁️ *NEX O201–O223* — cycle {s['cycle']}",
            f"📊 Behavior metrics:",
            f"  Unique openings: {m.get('unique_opening_pct','?')} "
              f"(target >{self.o202.TARGETS['unique_opening_pct']})",
            f"  As NEX rate: {m.get('as_nex_rate','?')} (target 0.0)",
            f"  Assertiveness: {m.get('assertiveness','?')} "
              f"(target >{self.o202.TARGETS['assertiveness']})",
            f"  Avg words: {m.get('avg_word_count','?')}",
            f"🎨 Diversity: {s['o203']['diversity_index']} "
              f"alerts={s['o203']['alerts']}",
            f"🔁 Repetition: {s['o205']['reuse_rate']} "
              f"alerts={s['o205']['alerts']}",
            f"💡 Micro-prompts: {s['o206']['injected']}",
            f"📚 Strategy formation: {s['o212']['total_formations']} "
              f"alerts={s['o212']['alerts']}",
            f"🎯 Strategy usage: {s['o213']['usage_rate']} "
              f"trend={s['o213']['trend']}",
            f"🔬 Learning health: dead_alerts={s['o214']['dead_alerts']}",
            f"🧬 Identity signature: {s['o216']['signature_score']} "
              f"emerging={s['o216']['emerging']}",
            f"⚡ Variance: {s['o218']['variance']} "
              f"in_range={s['o218']['in_range']}",
            f"🏋️ Training hold: {s['o222']['hold_active']} "
              f"released={s['o222']['released']}",
            f"🎯 Train trigger: {s['o223']['triggered']}",
        ]
        return "\n".join(lines)


_singleton: NexO223 | None = None
_lock = threading.Lock()

def get_o223() -> NexO223:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = NexO223()
    return _singleton
