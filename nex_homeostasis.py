"""
nex_homeostasis.py  —  NEX Dynamic Cognition Upgrade Stack
──────────────────────────────────────────────────────────
Layer 1  Homeostatic Core        — pressure zones + gradient responses
Layer 2  Cognitive Economy       — softmax task allocation + diminishing returns
Layer 3  Drive System            — coherence/exploration/efficiency/novelty
Layer 4  Identity + Continuity   — EMA identity vector + narrative thread
Layer 5  Belief Evolution        — fitness scoring, merge, mutate
Layer 6  Temporal Dynamics       — momentum tracker + topic cooldowns
Layer 7  Failure & Recovery      — recovery tiers + snapshot/rollback
Layer 8  Meta-Intelligence       — EMA strategy reward tracker
Layer 9  Signal vs Noise         — entropy gate + source trust memory
Master   NexHomeostasis          — singleton + get_homeostasis()

Drop this file in /home/rr/Desktop/nex/  (same level as run.py).
Wire with the three patch scripts: patch_run.py, patch_cognition.py, patch_auto_check.py
"""

from __future__ import annotations
import json, math, os, time, random, hashlib
from collections import defaultdict, deque
from pathlib import Path
from datetime import datetime

_CFG = Path.home() / ".config" / "nex"
_CFG.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1 — HOMEOSTATIC CORE
# ─────────────────────────────────────────────────────────────────────────────

PRESSURE_ZONES = {
    "calm":     {"range": (0.00, 0.25), "explore_rate": 1.3, "reflect_rate": 0.7, "synthesis_cap": 80},
    "active":   {"range": (0.25, 0.55), "explore_rate": 1.0, "reflect_rate": 1.0, "synthesis_cap": 60},
    "stressed": {"range": (0.55, 0.80), "explore_rate": 0.6, "reflect_rate": 1.4, "synthesis_cap": 40},
    "crisis":   {"range": (0.80, 1.00), "explore_rate": 0.3, "reflect_rate": 2.0, "synthesis_cap": 20},
}

def classify_pressure(avg_conf: float, tension: float, contradiction_rate: float = 0.0) -> str:
    """Map current system metrics to a pressure zone name."""
    raw = (1.0 - avg_conf) * 0.4 + tension * 0.4 + contradiction_rate * 0.2
    score = max(0.0, min(1.0, raw))
    for zone, cfg in PRESSURE_ZONES.items():
        lo, hi = cfg["range"]
        if lo <= score < hi:
            return zone
    return "crisis"

def gradient_responses(zone: str) -> dict:
    """Return the behaviour config for a given pressure zone."""
    return PRESSURE_ZONES.get(zone, PRESSURE_ZONES["active"])


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2 — COGNITIVE ECONOMY
# ─────────────────────────────────────────────────────────────────────────────

class CognitiveEconomy:
    """
    Softmax budget allocation across cognitive tasks.
    Tasks that were called recently get diminishing returns so
    NEX naturally rotates between activities.
    """

    TASKS = ["reflect", "synthesize", "explore", "chat", "post", "gap_detect"]

    def __init__(self):
        self._call_counts: dict[str, int]    = defaultdict(int)
        self._base_weights: dict[str, float] = {
            "reflect":    1.5,
            "synthesize": 1.2,
            "explore":    1.0,
            "chat":       0.9,
            "post":       0.8,
            "gap_detect": 0.7,
        }

    def _diminish(self, task: str) -> float:
        """Return diminishing-returns multiplier based on recent call frequency."""
        n = self._call_counts[task]
        return 1.0 / (1.0 + 0.15 * n)

    def allocations(self, zone: str) -> dict[str, float]:
        """Return normalised budget weights for all tasks given current pressure zone."""
        grad  = gradient_responses(zone)
        raw   = {}
        for t in self.TASKS:
            base = self._base_weights[t]
            dim  = self._diminish(t)
            # Zone nudge
            if t in ("reflect", "gap_detect"):
                base *= grad["reflect_rate"]
            elif t in ("explore", "chat"):
                base *= grad["explore_rate"]
            raw[t] = base * dim
        # Softmax
        mx   = max(raw.values())
        exp_ = {t: math.exp(v - mx) for t, v in raw.items()}
        s    = sum(exp_.values())
        return {t: e / s for t, e in exp_.items()}

    def record_call(self, task: str):
        self._call_counts[task] += 1

    def decay_counts(self):
        """Gently decay all counts each cycle so freshness resets over time."""
        for t in self.TASKS:
            self._call_counts[t] = max(0, self._call_counts[t] - 1)


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3 — DRIVE SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

DRIVE_NAMES = ["coherence", "exploration", "efficiency", "novelty"]

class DriveSystem:
    """
    Four core drives with mutual tension and fatigue/recovery dynamics.
    coherence  ←→  exploration  (opposing)
    efficiency ←→  novelty      (opposing)
    """

    def __init__(self):
        self._levels: dict[str, float] = {d: 0.5 for d in DRIVE_NAMES}
        self._fatigue: dict[str, float] = {d: 0.0 for d in DRIVE_NAMES}
        self._RECOVERY  = 0.05
        self._FATIGUE_K = 0.08
        self._TENSION   = 0.10  # suppression of opponent drive

    def tick(self, zone: str, cog_mode: str):
        """Update all drives based on current pressure zone and cognitive mode."""
        # Zone drives
        if zone in ("stressed", "crisis"):
            self._boost("coherence", 0.12)
            self._boost("efficiency", 0.08)
        elif zone == "calm":
            self._boost("exploration", 0.10)
            self._boost("novelty", 0.08)

        # Mode drives
        if cog_mode == "resolve":
            self._boost("coherence", 0.10)
        elif cog_mode == "explore":
            self._boost("exploration", 0.10)
            self._boost("novelty", 0.06)
        elif cog_mode == "optimize":
            self._boost("efficiency", 0.10)

        # Mutual tension (opponent suppression)
        self._levels["coherence"]  -= self._TENSION * self._levels["exploration"]
        self._levels["exploration"] -= self._TENSION * self._levels["coherence"]
        self._levels["efficiency"] -= self._TENSION * self._levels["novelty"]
        self._levels["novelty"]    -= self._TENSION * self._levels["efficiency"]

        # Fatigue + recovery
        dominant = self.dominant()
        for d in DRIVE_NAMES:
            if d == dominant:
                self._fatigue[d] = min(1.0, self._fatigue[d] + self._FATIGUE_K)
                self._levels[d]  = max(0.0, self._levels[d] - self._fatigue[d] * 0.05)
            else:
                self._fatigue[d] = max(0.0, self._fatigue[d] - self._RECOVERY)
                self._levels[d]  = min(1.0, self._levels[d] + self._RECOVERY * 0.5)

        # Clamp
        for d in DRIVE_NAMES:
            self._levels[d] = max(0.05, min(0.95, self._levels[d]))

    def _boost(self, drive: str, amount: float):
        self._levels[drive] = min(1.0, self._levels[drive] + amount)

    def dominant(self) -> str:
        return max(self._levels, key=lambda d: self._levels[d])

    def snapshot(self) -> dict:
        return {
            "levels":  dict(self._levels),
            "fatigue": dict(self._fatigue),
            "dominant": self.dominant(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 4 — IDENTITY + CONTINUITY
# ─────────────────────────────────────────────────────────────────────────────

_ID_PATH = _CFG / "nex_identity_vector.json"
_NT_PATH = _CFG / "nex_narrative_thread.json"

class IdentityVector:
    """
    EMA over 4 identity dimensions that anchors NEX's self-model
    across restarts.  Dimensions: curiosity, directness, empathy, rigour.
    """

    DIMS    = ["curiosity", "directness", "empathy", "rigour"]
    _ALPHA  = 0.05   # EMA smoothing — slow drift only

    def __init__(self):
        self._v: dict[str, float] = self._load()

    def _load(self) -> dict[str, float]:
        try:
            if _ID_PATH.exists():
                d = json.loads(_ID_PATH.read_text())
                return {k: float(d.get(k, 0.5)) for k in self.DIMS}
        except Exception:
            pass
        return {k: 0.5 for k in self.DIMS}

    def update(self, observed: dict[str, float]):
        """Nudge identity vector toward observed behaviour pattern."""
        for d in self.DIMS:
            if d in observed:
                self._v[d] = (1 - self._ALPHA) * self._v[d] + self._ALPHA * observed[d]
        self._save()

    def _save(self):
        try:
            _ID_PATH.write_text(json.dumps(self._v, indent=2))
        except Exception:
            pass

    def snapshot(self) -> dict:
        return dict(self._v)

    def dominant_trait(self) -> str:
        return max(self._v, key=lambda k: self._v[k])


class NarrativeThread:
    """
    Persists a running narrative of NEX's cognitive journey.
    Appends events; trims to last 200.
    """
    def __init__(self):
        self._events: list = self._load()

    def _load(self) -> list:
        try:
            if _NT_PATH.exists():
                return json.loads(_NT_PATH.read_text())
        except Exception:
            pass
        return []

    def log(self, event_type: str, detail: str, cycle: int):
        self._events.append({
            "ts":     datetime.now().isoformat(),
            "cycle":  cycle,
            "type":   event_type,
            "detail": detail[:200],
        })
        self._events = self._events[-200:]
        try:
            _NT_PATH.write_text(json.dumps(self._events, indent=2))
        except Exception:
            pass

    def recent(self, n: int = 5) -> list:
        return self._events[-n:]


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 5 — BELIEF EVOLUTION
# ─────────────────────────────────────────────────────────────────────────────

def belief_fitness(insight: dict, zone: str) -> float:
    """
    Score an insight's evolutionary fitness — used to gate promotion
    and decide on merge/mutate candidates.

    Returns 0.0–1.0. Higher = more fit to survive.
    """
    conf  = insight.get("confidence", 0.5)
    count = insight.get("belief_count", 1)
    age_s = 0.0
    try:
        ts  = insight.get("synthesized_at", "")
        dt  = datetime.fromisoformat(ts)
        age_s = (datetime.now() - dt).total_seconds()
    except Exception:
        pass

    age_penalty = min(0.3, age_s / (7 * 86400) * 0.3)   # up to -0.3 over 7 days
    count_bonus = min(0.2, (count / 50) * 0.2)           # up to +0.2 at 50 beliefs
    zone_bonus  = 0.05 if zone in ("calm", "active") else 0.0

    return max(0.0, min(1.0, conf + count_bonus - age_penalty + zone_bonus))


def maybe_merge(insights: list, sim_threshold: float = 0.85) -> list:
    """
    Merge insight pairs whose topics have high token overlap.
    Returns a pruned list — duplicate insights collapsed into one.
    """
    if len(insights) < 2:
        return insights

    def _tok(text: str) -> set:
        return set(w.lower() for w in text.split() if len(w) > 3)

    merged = []
    used   = set()
    for i, a in enumerate(insights):
        if i in used:
            continue
        best_j  = None
        best_sim = 0.0
        ta = _tok(a.get("topic", "") + " " + " ".join(a.get("themes", [])))
        for j, b in enumerate(insights):
            if j <= i or j in used:
                continue
            tb = _tok(b.get("topic", "") + " " + " ".join(b.get("themes", [])))
            if not ta or not tb:
                continue
            sim = len(ta & tb) / max(len(ta | tb), 1)
            if sim > sim_threshold and sim > best_sim:
                best_sim = sim
                best_j   = j

        if best_j is not None:
            b = insights[best_j]
            # Merge: keep higher-confidence, absorb belief_count
            winner = a if a.get("confidence", 0) >= b.get("confidence", 0) else b
            loser  = b if winner is a else a
            winner = dict(winner)
            winner["belief_count"] = winner.get("belief_count", 0) + loser.get("belief_count", 0)
            winner["themes"]       = list(set(winner.get("themes", []) + loser.get("themes", [])))[:8]
            merged.append(winner)
            used.add(i); used.add(best_j)
        else:
            merged.append(a)
            used.add(i)

    return merged


def maybe_mutate(insight: dict, zone: str, mutation_rate: float = 0.03) -> dict:
    """
    Occasionally introduce a small random perturbation to an insight's
    confidence — simulates genetic drift, prevents stagnation.
    Only fires at mutation_rate probability.
    """
    if random.random() > mutation_rate:
        return insight
    if zone in ("stressed", "crisis"):
        return insight   # no mutations under stress

    insight = dict(insight)
    delta   = random.gauss(0, 0.02)
    insight["confidence"] = max(0.1, min(0.95, insight.get("confidence", 0.5) + delta))
    insight["mutated"]    = True
    return insight


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 6 — TEMPORAL DYNAMICS
# ─────────────────────────────────────────────────────────────────────────────

class MomentumTracker:
    """EMA momentum on a scalar signal (e.g. avg_conf, tension)."""

    def __init__(self, alpha: float = 0.2):
        self._alpha = alpha
        self._ema:  float | None = None
        self._prev: float | None = None

    def update(self, value: float) -> float:
        if self._ema is None:
            self._ema = value
        else:
            self._prev = self._ema
            self._ema  = (1 - self._alpha) * self._ema + self._alpha * value
        return self._ema

    @property
    def momentum(self) -> float:
        """Positive = improving, negative = degrading."""
        if self._prev is None or self._ema is None:
            return 0.0
        return self._ema - self._prev


class CooldownSystem:
    """
    Per-topic cooldowns that prevent the synthesiser from hammering
    the same topic every cycle.
    """

    def __init__(self, default_cooldown: int = 5):
        self._default = default_cooldown
        self._last:    dict[str, int] = {}
        self._cd:      dict[str, int] = {}

    def set_cooldown(self, topic: str, cycles: int):
        self._cd[topic] = cycles

    def record(self, topic: str, cycle: int):
        self._last[topic] = cycle

    def multiplier(self, topic: str, current_cycle: int) -> float:
        """
        Return 0.0 if topic is on cooldown, scaling up to 1.0 as cooldown expires.
        """
        last  = self._last.get(topic, 0)
        cd    = self._cd.get(topic, self._default)
        delta = current_cycle - last
        if delta < cd:
            return delta / cd
        return 1.0

    def is_ready(self, topic: str, current_cycle: int) -> bool:
        return self.multiplier(topic, current_cycle) >= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 7 — FAILURE & RECOVERY
# ─────────────────────────────────────────────────────────────────────────────

RECOVERY_TIERS = {
    "soft":  {"threshold": 0.3,  "action": "increase_reflection"},
    "hard":  {"threshold": 0.55, "action": "pause_posting"},
    "reset": {"threshold": 0.75, "action": "rollback_snapshot"},
}

def classify_recovery_tier(pressure_score: float) -> str | None:
    for tier in ("reset", "hard", "soft"):
        if pressure_score >= RECOVERY_TIERS[tier]["threshold"]:
            return tier
    return None


_SNAP_PATH = _CFG / "nex_snapshot.json"

class SnapshotManager:
    """
    Lightweight JSON snapshot of key belief metrics.
    Allows rollback if a hard-reset event is triggered.
    """

    def save(self, state: dict):
        try:
            payload = {
                "saved_at": datetime.now().isoformat(),
                "state":    state,
            }
            _SNAP_PATH.write_text(json.dumps(payload, indent=2))
        except Exception:
            pass

    def load(self) -> dict | None:
        try:
            if _SNAP_PATH.exists():
                d = json.loads(_SNAP_PATH.read_text())
                return d.get("state")
        except Exception:
            pass
        return None

    def age_hours(self) -> float:
        try:
            if _SNAP_PATH.exists():
                d    = json.loads(_SNAP_PATH.read_text())
                ts   = datetime.fromisoformat(d.get("saved_at", ""))
                return (datetime.now() - ts).total_seconds() / 3600
        except Exception:
            pass
        return 999.0


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 8 — META-INTELLIGENCE
# ─────────────────────────────────────────────────────────────────────────────

class StrategyTracker:
    """
    EMA reward tracking per cognitive strategy.
    Strategies that produce better belief outcomes get higher weights over time.
    """

    STRATEGIES = ["resolve", "explore", "optimize"]
    _ALPHA     = 0.1

    def __init__(self):
        self._rewards: dict[str, float] = {s: 0.5 for s in self.STRATEGIES}

    def record_outcome(self, strategy: str, reward: float):
        """
        reward: 0.0–1.0  (e.g. improvement in avg_conf after a cycle).
        """
        if strategy not in self._rewards:
            return
        self._rewards[strategy] = (
            (1 - self._ALPHA) * self._rewards[strategy] + self._ALPHA * reward
        )

    def best_strategy(self) -> str:
        return max(self._rewards, key=lambda s: self._rewards[s])

    def snapshot(self) -> dict:
        return dict(self._rewards)


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 9 — SIGNAL VS NOISE
# ─────────────────────────────────────────────────────────────────────────────

def text_entropy(text: str) -> float:
    """
    Shannon character-level entropy of text.
    Low entropy → repetitive / low-information (noise).
    High entropy → diverse vocabulary (signal).
    """
    if not text:
        return 0.0
    counts: dict[str, int] = defaultdict(int)
    for ch in text:
        counts[ch] += 1
    n  = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def is_noise_by_entropy(text: str, min_entropy: float = 2.8) -> bool:
    """Return True if text looks like noise (entropy too low)."""
    return text_entropy(text) < min_entropy


_TRUST_PATH = _CFG / "nex_source_trust.json"

class SourceTrustMemory:
    """
    Per-source trust score updated by signal quality feedback.
    Scores range 0.5–2.0 (multipliers for confidence).
    """

    def __init__(self):
        self._scores: dict[str, float] = self._load()

    def _load(self) -> dict[str, float]:
        try:
            if _TRUST_PATH.exists():
                return json.loads(_TRUST_PATH.read_text())
        except Exception:
            pass
        return {}

    def _save(self):
        try:
            _TRUST_PATH.write_text(json.dumps(self._scores, indent=2))
        except Exception:
            pass

    def get_multiplier(self, source: str) -> float:
        return max(0.5, min(2.0, self._scores.get(source, 1.0)))

    def record_feedback(self, source: str, promoted: bool):
        """
        promoted=True  → belief from this source got promoted → trust up.
        promoted=False → belief was decayed or noisy → trust down.
        """
        current = self._scores.get(source, 1.0)
        delta   = +0.05 if promoted else -0.08
        self._scores[source] = max(0.5, min(2.0, current + delta))
        self._save()

    def top_sources(self, n: int = 5) -> list[tuple[str, float]]:
        return sorted(self._scores.items(), key=lambda x: -x[1])[:n]


# ─────────────────────────────────────────────────────────────────────────────
# MASTER — NexHomeostasis SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

class NexHomeostasis:
    """
    Master controller.  Import via get_homeostasis() — only one instance.

    Usage in run.py:
        _hm = get_homeostasis()
        # ...inside the main cycle:
        _hm_out = _hm.tick(cycle, avg_conf, tension, cog_mode)
        _cog_mode = _hm_out["recommended_mode"]
    """

    def __init__(self):
        self.economy   = CognitiveEconomy()
        self.drives    = DriveSystem()
        self.identity  = IdentityVector()
        self.narrative = NarrativeThread()
        self.momentum  = MomentumTracker()
        self.cooldowns = CooldownSystem(default_cooldown=6)
        self.snapshots = SnapshotManager()
        self.strategy  = StrategyTracker()
        self.trust     = SourceTrustMemory()

        # State
        self._zone:        str   = "active"
        self._prev_conf:   float = 0.5
        self._cycle:       int   = 0
        self._last_snap:   int   = 0
        self._SNAP_EVERY   = 20  # save snapshot every N cycles

    # ── Main tick ───────────────────────────────────────────────────────────

    def tick(
        self,
        cycle:       int,
        avg_conf:    float = 0.5,
        tension:     float = 0.0,
        cog_mode:    str   = "explore",
        contra_rate: float = 0.0,
    ) -> dict:
        """
        Call once per cycle at the top of the main while-loop.
        Returns a dict with everything run.py needs to adjust its behaviour.
        """
        self._cycle = cycle

        # Pressure zone
        self._zone = classify_pressure(avg_conf, tension, contra_rate)
        grad       = gradient_responses(self._zone)

        # Sub-system ticks
        self.economy.decay_counts()
        self.drives.tick(self._zone, cog_mode)
        allocations = self.economy.allocations(self._zone)

        # Momentum on avg_conf
        self.momentum.update(avg_conf)
        conf_momentum = self.momentum.momentum

        # Strategy outcome recording (reward = conf improvement)
        reward = 0.5 + conf_momentum * 5   # rescale to 0–1
        self.strategy.record_outcome(cog_mode, max(0.0, min(1.0, reward)))

        # Recommended mode from strategy tracker
        recommended_mode = self.strategy.best_strategy()
        # Override: crisis always → resolve
        if self._zone == "crisis":
            recommended_mode = "resolve"

        # Snapshot every N cycles
        if cycle - self._last_snap >= self._SNAP_EVERY:
            self.snapshots.save({
                "cycle":    cycle,
                "avg_conf": avg_conf,
                "tension":  tension,
                "zone":     self._zone,
            })
            self._last_snap = cycle

        # Narrative event on zone transition
        if self._zone in ("stressed", "crisis") and conf_momentum < -0.01:
            self.narrative.log("zone_warning", f"zone={self._zone} conf={avg_conf:.3f}", cycle)

        return {
            "zone":             self._zone,
            "gradient":         grad,
            "allocations":      allocations,
            "recommended_mode": recommended_mode,
            "conf_momentum":    conf_momentum,
            "dominant_drive":   self.drives.dominant(),
            "drives":           self.drives.snapshot(),
            "identity":         self.identity.snapshot(),
        }

    # ── Synthesis helpers ───────────────────────────────────────────────────

    def topic_priority(self, topic: str, current_cycle: int, base_score: float) -> float:
        """
        Multiply a cluster's base priority score by its cooldown multiplier.
        Pass this result as the sort key in run_synthesis().
        """
        return base_score * self.cooldowns.multiplier(topic, current_cycle)

    def mark_topic_synthesised(self, topic: str, cycle: int):
        """Call after synthesising a topic to start its cooldown."""
        self.cooldowns.record(topic, cycle)

    # ── Belief evolution helpers ────────────────────────────────────────────

    def belief_fitness(self, insight: dict) -> float:
        return belief_fitness(insight, self._zone)

    def evolve_insights(self, insights: list) -> list:
        """Run merge + mutate pass on an insights list. Call after synthesis."""
        insights = maybe_merge(insights)
        insights = [maybe_mutate(ins, self._zone) for ins in insights]
        return insights

    # ── Trust helpers ───────────────────────────────────────────────────────

    def record_source_feedback(self, source: str, promoted: bool):
        self.trust.record_feedback(source, promoted)

    def source_multiplier(self, source: str) -> float:
        return self.trust.get_multiplier(source)

    def noise_filter(self, text: str) -> bool:
        """Return True if text passes the entropy noise gate (is signal, not noise)."""
        return not is_noise_by_entropy(text)

    # ── Dashboard output ────────────────────────────────────────────────────

    def dashboard_lines(self) -> list[str]:
        """
        Returns a list of ANSI-coloured strings for the auto_check SELF ASSESSMENT panel.
        """
        CY = "\033[96m"; Y = "\033[93m"; G = "\033[92m"
        R  = "\033[91m"; D = "\033[2m";  RS = "\033[0m"; B = "\033[1m"
        M  = "\033[35m"; P = "\033[95m"

        zone_col = {"calm": G, "active": CY, "stressed": Y, "crisis": R}.get(self._zone, D)
        drive_snap = self.drives.snapshot()
        strat_snap = self.strategy.snapshot()
        id_snap    = self.identity.snapshot()

        best_src = self.trust.top_sources(3)

        lines = [
            f"{D}── homeostasis ──────────────────{RS}",
            f"  zone      {zone_col}{B}{self._zone.upper():10}{RS}  "
            f"drive {M}{self.drives.dominant()}{RS}",
            f"  momentum  {CY}{self.momentum.momentum:+.4f}{RS}  "
            f"cycle {D}{self._cycle}{RS}",
        ]

        # Drive bars
        for d, v in drive_snap["levels"].items():
            bar = "▮" * int(v * 10) + "▯" * (10 - int(v * 10))
            fat = drive_snap["fatigue"].get(d, 0.0)
            lines.append(f"  {d[:10]:10} [{G}{bar}{RS}] {D}fat={fat:.2f}{RS}")

        # Strategy rewards
        lines.append(f"{D}── strategy rewards ─────────────{RS}")
        for s, r in strat_snap.items():
            col = G if r == max(strat_snap.values()) else D
            bar = "▮" * int(r * 10) + "▯" * (10 - int(r * 10))
            lines.append(f"  {s[:9]:9} [{col}{bar}{RS}] {D}{r:.2f}{RS}")

        # Identity
        lines.append(f"{D}── identity dims ────────────────{RS}")
        for dim, val in id_snap.items():
            bar = "▮" * int(val * 10) + "▯" * (10 - int(val * 10))
            lines.append(f"  {dim[:10]:10} [{P}{bar}{RS}]")

        # Trust
        if best_src:
            lines.append(f"{D}── top sources ──────────────────{RS}")
            for src, score in best_src:
                trust_col = G if score >= 1.2 else Y if score >= 0.9 else R
                lines.append(f"  {src[:16]:16} {trust_col}{score:.2f}{RS}")

        return lines


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: NexHomeostasis | None = None

def get_homeostasis() -> NexHomeostasis:
    global _instance
    if _instance is None:
        _instance = NexHomeostasis()
    return _instance
