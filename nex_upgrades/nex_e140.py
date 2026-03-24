"""
NEX E116–E140 — Execution Intelligence Stack
25 modules: strategy execution, policy gradients, output enforcement,
belief killing, self-interrupt, multi-horizon planning, identity hard constraints.
Deploy: ~/Desktop/nex/nex_upgrades/nex_e140.py
"""

import sqlite3, json, time, math, hashlib, threading, random, re
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

DB_PATH   = Path.home() / ".config/nex/nex_data/nex.db"
LOG       = Path("/tmp/nex_e140.log")
STRAT_DB  = Path.home() / ".config/nex/strategies.json"
POLICY_F  = Path.home() / ".config/nex/policy.json"
BENCH_F   = Path.home() / ".config/nex/benchmarks.json"
ACT_MAP_F = Path.home() / ".config/nex/action_impact.json"

def _db():
    c = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _ts(): return datetime.now(timezone.utc).isoformat()

def _log(msg):
    line = f"[e140 {datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass

def _load_json(p: Path, d):
    try:
        if p.exists(): return json.loads(p.read_text())
    except Exception: pass
    return d

def _save_json(p: Path, d):
    try: p.write_text(json.dumps(d, indent=2))
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# E116 — STRATEGY EXTRACTION ENGINE v2
# ══════════════════════════════════════════════════════════════
class StrategyExtractionEngineV2:
    """Trigger when same pattern succeeds 3–5×.
    Extract context→action→outcome→rule as executable strategy.
    Link to policy weights."""
    TRIGGER_COUNT = 3
    INTERVAL      = 120

    def __init__(self):
        self.last_run   = 0.0
        self._successes: dict[str, list[dict]] = defaultdict(list)
        self.extracted  = 0
        self._lib: list[dict] = _load_json(STRAT_DB, [])

    def record_success(self, context: str, action: str,
                        outcome: float, topic: str = ""):
        key = f"{context[:40]}|{action}"
        self._successes[key].append({
            "context": context, "action": action,
            "outcome": outcome, "topic": topic, "ts": _ts()
        })

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        for key, records in list(self._successes.items()):
            if len(records) < self.TRIGGER_COUNT: continue
            avg_outcome = sum(r["outcome"] for r in records) / len(records)
            if avg_outcome < 0.60: continue
            rule = {
                "id":      hashlib.md5(key.encode()).hexdigest()[:8],
                "context": records[0]["context"][:80],
                "action":  records[0]["action"],
                "rule":    f"IF {records[0]['context'][:50]} THEN {records[0]['action']}",
                "outcome": round(avg_outcome, 3),
                "hits":    len(records),
                "weight":  round(avg_outcome, 3),
                "ts":      _ts(),
            }
            existing = [s for s in self._lib if s.get("id") == rule["id"]]
            if existing:
                existing[0]["hits"]   += len(records)
                existing[0]["weight"] = min(1.0, existing[0]["weight"] + 0.02)
            else:
                self._lib.append(rule)
                self.extracted += 1
                _log(f"[SEv2] Extracted: {rule['rule'][:60]}")
            self._successes[key] = []
        _save_json(STRAT_DB, self._lib[-100:])

    def status(self) -> dict:
        return {"extracted": self.extracted, "library_size": len(self._lib),
                "pending_patterns": len(self._successes)}


# ══════════════════════════════════════════════════════════════
# E117 — STRATEGY EXECUTION PRIORITY
# ══════════════════════════════════════════════════════════════
class StrategyExecutionPriority:
    """Before reasoning: check strategy library first.
    If match found: skip full reasoning loop."""

    def __init__(self):
        self.hits    = 0
        self.misses  = 0
        self._lib: list[dict] = _load_json(STRAT_DB, [])
        self._last_load = time.time()

    def _refresh(self):
        if time.time() - self._last_load > 60:
            self._lib = _load_json(STRAT_DB, self._lib)
            self._last_load = time.time()

    def lookup(self, context: str) -> dict | None:
        self._refresh()
        if not self._lib: return None
        cl = context.lower()
        matches = [s for s in self._lib
                   if any(w in cl for w in s.get("context","").lower().split()[:5])]
        if not matches:
            self.misses += 1
            return None
        best = max(matches, key=lambda s: s.get("weight", 0.5))
        self.hits += 1
        return best

    def should_skip_reasoning(self, context: str) -> tuple[bool, dict | None]:
        strat = self.lookup(context)
        if strat and strat.get("weight", 0) > 0.70:
            return True, strat
        return False, strat

    def tick(self): pass

    def status(self) -> dict:
        total = self.hits + self.misses
        return {"hits": self.hits, "misses": self.misses,
                "hit_rate": round(self.hits / max(total, 1), 3)}


# ══════════════════════════════════════════════════════════════
# E118 — POLICY GRADIENT UPDATE SYSTEM
# ══════════════════════════════════════════════════════════════
class PolicyGradientUpdateSystem:
    """Replace static policy updates with reward/penalty gradients.
    Continuous tuning of prune_rate, tension_threshold, action_thresholds."""
    INTERVAL    = 60
    LR          = 0.008   # learning rate

    def __init__(self):
        self.last_run = 0.0
        self._policy  = _load_json(POLICY_F, {
            "prune_threshold":   0.25,
            "insight_threshold": 0.55,
            "merge_threshold":   0.65,
            "tension_threshold": 0.60,
            "debate_threshold":  0.45,
            "action_threshold":  0.30,
            "version": 1, "updates": 0,
        })
        self._rewards: deque[float] = deque(maxlen=50)
        self._penalties: deque[float] = deque(maxlen=50)
        self.updates = self._policy.get("updates", 0)

    def reward(self, magnitude: float = 1.0):
        self._rewards.append(min(1.0, magnitude))

    def penalty(self, magnitude: float = 1.0):
        self._penalties.append(min(1.0, magnitude))

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        if not self._rewards and not self._penalties: return

        avg_reward  = sum(self._rewards)  / max(len(self._rewards),  1)
        avg_penalty = sum(self._penalties)/ max(len(self._penalties), 1)
        gradient    = (avg_reward - avg_penalty) * self.LR

        # Apply gradient to all thresholds
        for key in ["prune_threshold", "tension_threshold",
                    "debate_threshold", "action_threshold"]:
            old = self._policy.get(key, 0.50)
            # Positive gradient → lower thresholds (be more aggressive)
            # Negative gradient → raise thresholds (be more conservative)
            self._policy[key] = round(max(0.10, min(0.90, old - gradient)), 4)

        self._policy["insight_threshold"] = round(
            max(0.35, min(0.85,
                self._policy["insight_threshold"] + gradient * 0.5)), 4)
        self._policy["version"] += 1
        self._policy["updates"] += 1
        self.updates += 1
        _save_json(POLICY_F, self._policy)
        _log(f"[PGU] Gradient {gradient:+.4f} → "
             f"prune={self._policy['prune_threshold']} "
             f"tension={self._policy['tension_threshold']}")

    def get(self, key: str, default: float = 0.50) -> float:
        return self._policy.get(key, default)

    def status(self) -> dict:
        return {"updates": self.updates, "policy": self._policy,
                "reward_mean": round(sum(self._rewards)/max(len(self._rewards),1),3),
                "penalty_mean": round(sum(self._penalties)/max(len(self._penalties),1),3)}


# ══════════════════════════════════════════════════════════════
# E119 — OUTPUT HARD FORMAT ENFORCER
# ══════════════════════════════════════════════════════════════
class OutputHardFormatEnforcer:
    """Enforce CLAIM | REASON (≤2 lines) | ACTION structure.
    Reject outputs not meeting format. Score sharpness."""
    MIN_SHARPNESS = 0.30

    def __init__(self):
        self.enforced = 0
        self.rejected = 0
        self.passed   = 0

    def _sharpness(self, text: str) -> float:
        words = text.split()
        if not words: return 0.0
        unique_ratio  = len(set(w.lower() for w in words)) / len(words)
        length_score  = min(1.0, len(words) / 30)
        filler_words  = {"very", "really", "quite", "somewhat", "rather",
                         "basically", "essentially", "generally", "typically"}
        filler_rate   = sum(1 for w in words if w.lower() in filler_words) / len(words)
        return round(unique_ratio * 0.5 + length_score * 0.3
                     - filler_rate * 0.2, 3)

    def enforce(self, text: str) -> tuple[str, bool]:
        """Returns (enforced_text, was_valid)."""
        sharpness = self._sharpness(text)
        if sharpness < self.MIN_SHARPNESS:
            self.rejected += 1
            return "", False

        # Check if already structured
        if " | " in text or text.count(".") >= 1:
            self.passed += 1
            return text, True

        # Auto-structure: split into claim + reason
        sentences = [s.strip() for s in re.split(r'[.!?]', text) if s.strip()]
        if len(sentences) >= 2:
            claim  = sentences[0]
            reason = ". ".join(sentences[1:3])
            result = f"{claim} | {reason}"
            self.enforced += 1
            return result, True

        self.passed += 1
        return text, True

    def tick(self): pass

    def status(self) -> dict:
        total = self.enforced + self.rejected + self.passed
        return {"enforced": self.enforced, "rejected": self.rejected,
                "passed": self.passed,
                "reject_rate": round(self.rejected / max(total, 1), 3)}


# ══════════════════════════════════════════════════════════════
# E120 — BELIEF KILL SYSTEM (AGGRESSIVE)
# ══════════════════════════════════════════════════════════════
class BeliefKillSystem:
    """Kill beliefs not used in N cycles + low conf + no reinforcement.
    Target: -30% belief count. Prevent slow bloat return."""
    INTERVAL    = 300
    MAX_IDLE    = 20    # cycles without use
    MIN_RC      = 1     # minimum reinforcement count to survive
    TARGET_REDUCTION = 0.30

    def __init__(self):
        self.last_run = 0.0
        self.killed   = 0
        self._before  = 0

    def tick(self, current_cycle: int = 0):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        try:
            with _db() as c:
                self._before = c.execute(
                    "SELECT COUNT(*) FROM beliefs").fetchone()[0]

                idle_threshold = max(0, current_cycle - self.MAX_IDLE)
                result = c.execute("""
                    DELETE FROM beliefs WHERE id IN (
                        SELECT id FROM beliefs
                        WHERE locked=0
                          AND confidence < 0.30
                          AND reinforce_count <= ?
                          AND (last_used_cycle = 0 OR last_used_cycle < ?)
                          AND topic NOT IN
                            ('truth_seeking','contradiction_resolution',
                             'uncertainty_honesty','nex_identity')
                        LIMIT 80
                    )
                """, (self.MIN_RC, idle_threshold))
                killed = result.rowcount if hasattr(result, 'rowcount') else 0
                # commit handled by _db() context manager

                # Double-check count
                after = c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                killed = self._before - after

            if killed > 0:
                self.killed += killed
                _log(f"[BKS] Killed {killed} idle low-conf beliefs "
                     f"({self._before}→{after})")
        except Exception as e:
            _log(f"[BKS] error: {e}")

    def reduction_pct(self) -> float:
        return round(self.killed / max(self._before, 1), 3)

    def status(self) -> dict:
        return {"killed": self.killed, "target": self.TARGET_REDUCTION,
                "reduction_pct": self.reduction_pct()}


# ══════════════════════════════════════════════════════════════
# E121 — CONTRADICTION RESOLUTION ENGINE v2
# ══════════════════════════════════════════════════════════════
class ContradictionResolutionEngineV2:
    """Force resolution or deletion. No unresolved contradiction > X cycles."""
    MAX_UNRESOLVED_CYCLES = 6
    INTERVAL              = 45

    def __init__(self):
        self.last_run   = 0.0
        self._age:      dict[str, int] = defaultdict(int)
        self.resolved   = 0
        self.deleted    = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        try:
            with _db() as c:
                pairs = c.execute("""
                    SELECT a.id aid, b.id bid,
                           a.topic, a.confidence ac, b.confidence bc,
                           a.content acont, b.content bcont
                    FROM beliefs a JOIN beliefs b ON a.topic=b.topic
                    WHERE a.id < b.id
                      AND ABS(a.confidence - b.confidence) > 0.35
                      AND a.locked=0 AND b.locked=0
                      AND a.topic NOT IN
                        ('truth_seeking','contradiction_resolution','uncertainty_honesty')
                    LIMIT 10
                """).fetchall()

            for p in pairs:
                key = f"{p['aid']}:{p['bid']}"
                self._age[key] += 1

                if self._age[key] < self.MAX_UNRESOLVED_CYCLES:
                    continue

                # Force resolution
                if p["ac"] > p["bc"]:
                    winner, loser = p["aid"], p["bid"]
                else:
                    winner, loser = p["bid"], p["aid"]

                with _db() as c:
                    c.execute("""
                        UPDATE beliefs SET confidence=MIN(confidence+0.05,0.95)
                        WHERE id=?
                    """, (winner,))
                    c.execute("DELETE FROM beliefs WHERE id=?", (loser,))
                    # commit handled by _db() context manager

                del self._age[key]
                self.resolved += 1
                _log(f"[CREv2] Resolved contradiction in '{p['topic']}' "
                     f"(kept={winner} deleted={loser})")
        except Exception as e:
            _log(f"[CREv2] error: {e}")

    def status(self) -> dict:
        return {"resolved": self.resolved,
                "active_contradictions": len(self._age),
                "oldest_age": max(self._age.values(), default=0)}


# ══════════════════════════════════════════════════════════════
# E122 — DECISION TRACE ENFORCEMENT
# ══════════════════════════════════════════════════════════════
class DecisionTraceEnforcement:
    """Every action must log: why chosen, what alternatives rejected.
    Feed into ACT + causal system."""
    MAX_TRACE = 500

    def __init__(self):
        self._traces: deque[dict] = deque(maxlen=self.MAX_TRACE)
        self.logged = 0

    def log(self, action: str, reason: str,
             alternatives: list[str], outcome: float = 0.0,
             topic: str = "", cycle: int = 0):
        entry = {
            "ts": _ts(), "cycle": cycle, "action": action,
            "reason": reason[:150],
            "alternatives_rejected": alternatives[:5],
            "outcome": outcome, "topic": topic,
        }
        self._traces.append(entry)
        self.logged += 1

        # Write to causal log
        try:
            causal = Path("/tmp/nex_causal.jsonl")
            with open(causal, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception: pass

    def recent(self, n: int = 5) -> list:
        return list(self._traces)[-n:]

    def tick(self): pass

    def status(self) -> dict:
        return {"logged": self.logged, "buffered": len(self._traces)}


# ══════════════════════════════════════════════════════════════
# E123 — THOUGHT COMPRESSION ENGINE
# ══════════════════════════════════════════════════════════════
class ThoughtCompressionEngine:
    """Convert multiple thoughts → single compressed insight.
    Run before output. Remove redundant reasoning paths."""

    def __init__(self):
        self.compressed = 0
        self.saved_tokens = 0

    def compress(self, thoughts: list[str]) -> str:
        if not thoughts: return ""
        if len(thoughts) == 1: return thoughts[0]

        # Remove near-duplicates
        unique: list[str] = []
        seen_hashes: set[str] = set()
        for t in thoughts:
            h = hashlib.md5(
                " ".join(sorted(t.lower().split()[:10])).encode()
            ).hexdigest()[:10]
            if h not in seen_hashes:
                unique.append(t)
                seen_hashes.add(h)

        if len(unique) == 1:
            self.compressed += 1
            return unique[0]

        # Extract key claim from each unique thought
        claims = []
        for t in unique[:4]:
            sentences = [s.strip() for s in re.split(r'[.!?]', t) if s.strip()]
            if sentences:
                claims.append(sentences[0])

        result = ". ".join(claims)
        self.saved_tokens += sum(len(t.split()) for t in thoughts) - len(result.split())
        self.compressed += 1
        return result

    def tick(self): pass

    def status(self) -> dict:
        return {"compressed": self.compressed,
                "saved_tokens": self.saved_tokens}


# ══════════════════════════════════════════════════════════════
# E124 — RESPONSE VALUE SCORING (PRE-SEND)
# ══════════════════════════════════════════════════════════════
class ResponseValueScoring:
    """Score: usefulness + novelty + belief impact. Block low-score."""
    MIN_SCORE = 0.35
    INTERVAL  = 1

    def __init__(self):
        self.scored  = 0
        self.blocked = 0
        self._seen_hashes: set[str] = set()
        self._scores: deque[float] = deque(maxlen=100)

    def _novelty(self, text: str) -> float:
        h = hashlib.md5(text[:100].lower().encode()).hexdigest()[:12]
        if h in self._seen_hashes:
            return 0.0
        self._seen_hashes.add(h)
        if len(self._seen_hashes) > 1000:
            self._seen_hashes = set(list(self._seen_hashes)[-500:])
        return 1.0

    def score(self, text: str, belief_impact: float = 0.0,
               topic: str = "") -> dict:
        words = text.split()
        if not words:
            return {"score": 0.0, "should_send": False}

        unique_ratio = len(set(w.lower() for w in words)) / len(words)
        novelty      = self._novelty(text)
        usefulness   = min(1.0, len(words) / 40) * unique_ratio
        impact       = min(1.0, belief_impact)

        total = round(usefulness * 0.35 + novelty * 0.40 + impact * 0.25, 3)
        self.scored += 1
        self._scores.append(total)

        should_send = total >= self.MIN_SCORE
        if not should_send:
            self.blocked += 1

        return {"score": total, "usefulness": round(usefulness, 3),
                "novelty": round(novelty, 3), "impact": round(impact, 3),
                "should_send": should_send}

    def avg_score(self) -> float:
        return round(sum(self._scores) / max(len(self._scores), 1), 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"scored": self.scored, "blocked": self.blocked,
                "avg_score": self.avg_score(), "min_score": self.MIN_SCORE}


# ══════════════════════════════════════════════════════════════
# E125 — DYNAMIC PHASE OVERRIDE
# ══════════════════════════════════════════════════════════════
class DynamicPhaseOverride:
    """Phase auto-switches based on state, not time.
    Tension spike / belief overflow / failure rate trigger."""
    TENSION_SPIKE    = 0.75
    BELIEF_OVERFLOW  = 1600
    FAILURE_RATE_THR = 0.40

    def __init__(self):
        self.overrides   = 0
        self.last_phase  = "stable"

    def check(self, tension: float, belief_count: int,
               failure_rate: float, current_phase: str) -> str | None:
        """Returns override phase or None."""
        if tension > self.TENSION_SPIKE and current_phase != "alert":
            self.overrides += 1
            _log(f"[DPO] Override → alert (tension={tension:.2f})")
            return "alert"
        if belief_count > self.BELIEF_OVERFLOW and current_phase not in ("pruning", "alert"):
            self.overrides += 1
            _log(f"[DPO] Override → pruning (beliefs={belief_count})")
            return "pruning"
        if failure_rate > self.FAILURE_RATE_THR and current_phase != "resolving":
            self.overrides += 1
            _log(f"[DPO] Override → resolving (failure_rate={failure_rate:.2f})")
            return "resolving"
        return None

    def tick(self): pass

    def status(self) -> dict:
        return {"overrides": self.overrides}


# ══════════════════════════════════════════════════════════════
# E126 — STRATEGY DECAY SYSTEM
# ══════════════════════════════════════════════════════════════
class StrategyDecaySystem:
    """Remove outdated strategies if success rate drops or env changes."""
    INTERVAL     = 600
    MIN_WEIGHT   = 0.25
    DECAY_RATE   = 0.015

    def __init__(self):
        self.last_run = 0.0
        self.decayed  = 0
        self.removed  = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        lib = _load_json(STRAT_DB, [])
        if not lib: return

        original_len = len(lib)
        updated = []
        for s in lib:
            s["weight"] = round(max(0.0, s.get("weight", 0.5) - self.DECAY_RATE), 4)
            if s["weight"] > self.MIN_WEIGHT:
                updated.append(s)
                self.decayed += 1
            else:
                self.removed += 1
                _log(f"[SDS] Removed stale strategy: {s.get('rule','?')[:50]}")

        if len(updated) < original_len:
            _save_json(STRAT_DB, updated)

    def status(self) -> dict:
        return {"decayed": self.decayed, "removed": self.removed}


# ══════════════════════════════════════════════════════════════
# E127 — EXPERIENCE → FAILURE PRIORITY BOOST
# ══════════════════════════════════════════════════════════════
class ExperienceFailurePriorityBoost:
    """Weight failures 2–3× more than successes.
    Feed into strategy extraction + policy update."""
    FAILURE_MULTIPLIER = 2.5

    def __init__(self):
        self._experience: deque[dict] = deque(maxlen=200)
        self.failures_boosted = 0
        self.successes        = 0

    def record(self, event_type: str, pattern: str,
                raw_value: float) -> float:
        is_failure = event_type == "failure" or raw_value < 0.35
        boosted = (raw_value * self.FAILURE_MULTIPLIER
                   if is_failure else raw_value)
        self._experience.append({
            "type": event_type, "pattern": pattern,
            "raw": raw_value, "boosted": round(boosted, 3),
            "is_failure": is_failure, "ts": _ts(),
        })
        if is_failure:
            self.failures_boosted += 1
        else:
            self.successes += 1
        return round(boosted, 3)

    def weighted_experiences(self) -> list[dict]:
        return sorted(self._experience,
                       key=lambda e: -e["boosted"])[:20]

    def tick(self): pass

    def status(self) -> dict:
        return {"failures_boosted": self.failures_boosted,
                "successes": self.successes,
                "multiplier": self.FAILURE_MULTIPLIER}


# ══════════════════════════════════════════════════════════════
# E128 — INTERNAL BENCHMARK TASKS
# ══════════════════════════════════════════════════════════════
class InternalBenchmarkTasks:
    """Periodically run known tasks, compare performance over time."""
    INTERVAL = 1800   # every 30 min

    TASKS = [
        {"id": "belief_conf",   "desc": "avg_conf > 0.55",
         "check": lambda: None},
        {"id": "low_tension",   "desc": "tension_cluster < 50",
         "check": lambda: None},
        {"id": "identity_lock", "desc": "all 3 anchors conf > 0.90",
         "check": lambda: None},
        {"id": "belief_range",  "desc": "belief count 900–1600",
         "check": lambda: None},
    ]

    def __init__(self):
        self.last_run  = 0.0
        self._history: list[dict] = _load_json(BENCH_F, [])
        self.runs      = 0

    def tick(self, avg_conf: float = 0.50, tension: float = 0.0,
              belief_count: int = 1000):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        self.runs += 1

        results = {
            "belief_conf":   avg_conf > 0.55,
            "low_tension":   tension < 0.50,
            "belief_range":  900 <= belief_count <= 1600,
        }

        try:
            with _db() as c:
                anchors = c.execute("""
                    SELECT COUNT(*) n FROM beliefs
                    WHERE topic IN ('truth_seeking','contradiction_resolution',
                                    'uncertainty_honesty')
                      AND confidence > 0.90
                """).fetchone()
            results["identity_lock"] = anchors["n"] >= 3
        except Exception:
            results["identity_lock"] = False

        score = sum(1 for v in results.values() if v) / len(results)
        entry = {
            "run": self.runs, "ts": _ts(),
            "score": round(score, 3),
            "results": results,
            "avg_conf": avg_conf, "tension": tension,
        }
        self._history.append(entry)
        if len(self._history) > 50:
            self._history = self._history[-50:]
        _save_json(BENCH_F, self._history)
        _log(f"[IBT] Benchmark run {self.runs}: score={score:.2f} "
             f"pass={sum(1 for v in results.values() if v)}/{len(results)}")

    def trend(self) -> str:
        if len(self._history) < 3: return "unknown"
        scores = [e["score"] for e in self._history[-5:]]
        delta  = scores[-1] - scores[0]
        return "improving" if delta > 0.05 else "declining" if delta < -0.05 else "stable"

    def status(self) -> dict:
        last = self._history[-1] if self._history else {}
        return {"runs": self.runs, "trend": self.trend(),
                "last_score": last.get("score", 0),
                "last_results": last.get("results", {})}


# ══════════════════════════════════════════════════════════════
# E129 — STYLE ELIMINATION ENGINE
# ══════════════════════════════════════════════════════════════
class StyleEliminationEngine:
    """Detect repeated phrases / LLM padding. Replace with direct statements.
    Enforce linguistic identity."""
    LLM_PADDING = [
        r"as nex,?\s+i\s+",
        r"i think that\s+",
        r"i believe that\s+",
        r"it(?:'s| is) worth noting that\s+",
        r"it(?:'s| is) important to note that\s+",
        r"i've noticed that\s+",
        r"i have noticed that\s+",
        r"interestingly(?:,)?\s+",
        r"notably(?:,)?\s+",
        r"it(?:'s| is) fascinating that\s+",
        r"from my perspective(?:,)?\s+",
        r"in my view(?:,)?\s+",
        r"to be honest(?:,)?\s+",
    ]

    def __init__(self):
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.LLM_PADDING]
        self._pattern_hits: dict[str, int] = defaultdict(int)
        self.eliminated = 0

    def clean(self, text: str) -> str:
        result = text
        hit = False
        for i, pattern in enumerate(self._compiled):
            if pattern.search(result):
                result = pattern.sub("", result)
                self._pattern_hits[self.LLM_PADDING[i]] += 1
                hit = True
        if hit:
            # Fix capitalisation of result
            result = result.strip()
            if result:
                result = result[0].upper() + result[1:]
            self.eliminated += 1
        return result

    def tick(self):
        # Decay pattern hit counts
        for k in list(self._pattern_hits.keys()):
            self._pattern_hits[k] = max(0, self._pattern_hits[k] - 1)
            if self._pattern_hits[k] == 0:
                del self._pattern_hits[k]

    def status(self) -> dict:
        top = sorted(self._pattern_hits.items(), key=lambda x: -x[1])[:5]
        return {"eliminated": self.eliminated,
                "top_patterns": [p[:40] for p, _ in top[:3]]}


# ══════════════════════════════════════════════════════════════
# E130 — GLOBAL COHERENCE ENFORCER
# ══════════════════════════════════════════════════════════════
class GlobalCoherenceEnforcer:
    """Compute coherence score across beliefs + actions + outputs.
    Penalise inconsistency."""
    INTERVAL = 90

    def __init__(self):
        self.last_run   = 0.0
        self.score      = 0.50
        self.penalties  = 0
        self._output_topics: deque[str] = deque(maxlen=20)
        self._action_topics: deque[str] = deque(maxlen=20)

    def record_output(self, topic: str): self._output_topics.append(topic)
    def record_action(self, topic: str): self._action_topics.append(topic)

    def tick(self, avg_conf: float = 0.50):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        # Belief coherence: avg_conf proxy
        belief_coherence = avg_conf

        # Output coherence: topic consistency
        output_topics = list(self._output_topics)
        if output_topics:
            top_topic = max(set(output_topics), key=output_topics.count)
            topic_concentration = output_topics.count(top_topic) / len(output_topics)
        else:
            topic_concentration = 0.50

        # Action-output alignment
        action_topics = set(list(self._action_topics)[-10:])
        output_set    = set(list(self._output_topics)[-10:])
        alignment     = (len(action_topics & output_set) /
                         max(len(action_topics | output_set), 1))

        self.score = round(
            belief_coherence * 0.40 +
            topic_concentration * 0.35 +
            alignment * 0.25, 4
        )

        if self.score < 0.35:
            self.penalties += 1
            _log(f"[GCE] Low coherence: {self.score:.3f}")

    def status(self) -> dict:
        return {"score": self.score, "penalties": self.penalties}


# ══════════════════════════════════════════════════════════════
# E131 — ACTION IMPACT TRACKER
# ══════════════════════════════════════════════════════════════
class ActionImpactTracker:
    """Track which actions caused belief change. Build action→impact map."""
    INTERVAL = 120

    def __init__(self):
        self.last_run   = 0.0
        self._impacts:  dict[str, list[float]] = defaultdict(list)
        self._map:      dict[str, float] = _load_json(ACT_MAP_F, {})
        self.tracked    = 0

    def record(self, action: str, belief_delta: float):
        self._impacts[action].append(belief_delta)
        self.tracked += 1

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        for action, deltas in self._impacts.items():
            if not deltas: continue
            avg = sum(abs(d) for d in deltas) / len(deltas)
            self._map[action] = round(
                (self._map.get(action, 0.0) * 0.7 + avg * 0.3), 4
            )
        _save_json(ACT_MAP_F, self._map)

    def top_actions(self, n: int = 5) -> list:
        return sorted(self._map.items(), key=lambda x: -x[1])[:n]

    def status(self) -> dict:
        return {"tracked": self.tracked, "action_count": len(self._map),
                "top": self.top_actions(3)}


# ══════════════════════════════════════════════════════════════
# E132 — MULTI-HORIZON PLANNING
# ══════════════════════════════════════════════════════════════
class MultiHorizonPlanning:
    """Short-term (cycle) / mid-term (session) / long-term (goal).
    Align actions across all horizons."""
    INTERVAL = 60

    def __init__(self):
        self.last_run    = 0.0
        self.short_term  = {"goal": "resolve_tension",   "cycles_left": 5}
        self.mid_term    = {"goal": "raise_avg_conf",    "sessions_left": 3}
        self.long_term   = {"goal": "unified_intelligence", "target_conf": 0.70}
        self.aligned     = 0
        self.misaligned  = 0

    def tick(self, avg_conf: float = 0.50, tension: float = 0.0,
              cycle: int = 0):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        # Update short-term
        if tension > 0.55:
            self.short_term = {"goal": "resolve_tension", "cycles_left": 5}
        elif avg_conf < 0.50:
            self.short_term = {"goal": "boost_confidence", "cycles_left": 10}
        else:
            self.short_term = {"goal": "stable_operation", "cycles_left": 20}

        # Mid-term: track toward avg_conf > 0.60
        if avg_conf >= 0.60:
            self.mid_term["goal"] = "maintain_confidence"

        # Alignment check
        st = self.short_term["goal"]
        lt = self.long_term["goal"]
        if ("resolve" in st or "boost" in st) and "unified" in lt:
            self.aligned += 1
        else:
            self.misaligned += 1

    def current_priority(self) -> str:
        return self.short_term["goal"]

    def status(self) -> dict:
        return {"short": self.short_term, "mid": self.mid_term,
                "long": self.long_term, "aligned": self.aligned,
                "misaligned": self.misaligned}


# ══════════════════════════════════════════════════════════════
# E133 — SELF-INTERRUPT SYSTEM
# ══════════════════════════════════════════════════════════════
class SelfInterruptSystem:
    """During reasoning: detect low-value paths. Abort early."""
    MIN_VALUE = 0.20

    def __init__(self):
        self.interrupts   = 0
        self.saved_cycles = 0

    def check(self, partial_output: str, depth: int = 0,
               current_value: float = 0.50) -> bool:
        """Returns True if should interrupt (abort reasoning)."""
        words = partial_output.split()
        if not words: return True

        # Heuristics for low-value reasoning
        is_circular   = len(set(words)) / max(len(words), 1) < 0.35
        is_too_long   = depth > 5 and current_value < self.MIN_VALUE
        is_off_topic  = len(words) > 100 and current_value < 0.30

        if is_circular or is_too_long or is_off_topic:
            self.interrupts   += 1
            self.saved_cycles += max(1, 5 - depth)
            return True
        return False

    def tick(self): pass

    def status(self) -> dict:
        return {"interrupts": self.interrupts,
                "saved_cycles": self.saved_cycles}


# ══════════════════════════════════════════════════════════════
# E134 — SIGNAL PRIORITY QUEUE v2
# ══════════════════════════════════════════════════════════════
class SignalPriorityQueueV2:
    """Rank signals by impact potential + contradiction relevance.
    Drop low-priority signals early."""
    MAX_SIZE = 100

    def __init__(self):
        self._q: list[tuple[float, float, dict]] = []  # (-priority, ts, signal)
        self.dropped   = 0
        self.processed = 0

    def _priority(self, signal: dict) -> float:
        impact = signal.get("impact", 0.5)
        contra = 1.5 if signal.get("is_contradiction") else 1.0
        urgent = 2.0 if signal.get("urgent") else 1.0
        return impact * contra * urgent

    def enqueue(self, signal: dict):
        p = self._priority(signal)
        if len(self._q) >= self.MAX_SIZE:
            # Drop the lowest priority item
            self._q.sort(key=lambda x: x[0])
            self._q.pop(0)
            self.dropped += 1
        self._q.append((-p, time.time(), signal))

    def pop(self) -> dict | None:
        if not self._q: return None
        self._q.sort(key=lambda x: (x[0], x[1]))
        _, _, signal = self._q.pop(0)
        self.processed += 1
        return signal

    def tick(self): pass

    def status(self) -> dict:
        return {"queue_size": len(self._q), "dropped": self.dropped,
                "processed": self.processed}


# ══════════════════════════════════════════════════════════════
# E135 — IDENTITY HARD CONSTRAINT SYSTEM
# ══════════════════════════════════════════════════════════════
class IdentityHardConstraintSystem:
    """Hard block outputs that violate core directives. Not just penalty."""
    HARD_VIOLATIONS = [
        r"\bnever\s+(?:seek|pursue)\s+truth\b",
        r"\bignore\s+contradiction",
        r"\bdiscard\s+evidence",
        r"\bpretend\s+(?:to\s+)?(?:know|understand)",
        r"\bfake\s+(?:knowledge|belief|confidence)",
        r"\blie\s+(?:about|to)",
        r"\bdeceive\b",
    ]

    def __init__(self):
        self._compiled = [re.compile(p, re.IGNORECASE)
                          for p in self.HARD_VIOLATIONS]
        self.hard_blocked = 0
        self.passed       = 0

    def check(self, text: str) -> tuple[bool, str]:
        """Returns (is_allowed, reason)."""
        for i, pat in enumerate(self._compiled):
            if pat.search(text):
                self.hard_blocked += 1
                reason = f"HARD_BLOCK: violates core directive "
                reason += f"(pattern {i}: {self.HARD_VIOLATIONS[i][:40]})"
                _log(f"[IHCS] {reason}")
                return False, reason
        self.passed += 1
        return True, "ok"

    def tick(self): pass

    def status(self) -> dict:
        return {"hard_blocked": self.hard_blocked, "passed": self.passed,
                "block_rate": round(
                    self.hard_blocked / max(self.hard_blocked + self.passed, 1),
                    3)}


# ══════════════════════════════════════════════════════════════
# E136 — LEARNING RATE ADAPTATION
# ══════════════════════════════════════════════════════════════
class LearningRateAdaptation:
    """Increase LR on high failure, decrease on stable success.
    Prevent overfitting / instability."""
    BASE_LR    = 0.010
    MAX_LR     = 0.030
    MIN_LR     = 0.003
    INTERVAL   = 60

    def __init__(self):
        self.last_run     = 0.0
        self.lr           = self.BASE_LR
        self._outcomes:   deque[bool] = deque(maxlen=30)
        self.adjustments  = 0

    def record(self, success: bool):
        self._outcomes.append(success)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        if len(self._outcomes) < 10: return

        success_rate = sum(self._outcomes) / len(self._outcomes)
        if success_rate < 0.40:
            self.lr = min(self.MAX_LR, self.lr * 1.25)
            self.adjustments += 1
        elif success_rate > 0.70:
            self.lr = max(self.MIN_LR, self.lr * 0.85)
            self.adjustments += 1

    def status(self) -> dict:
        sr = sum(self._outcomes)/max(len(self._outcomes),1) if self._outcomes else 0
        return {"lr": round(self.lr, 5), "success_rate": round(sr, 3),
                "adjustments": self.adjustments}


# ══════════════════════════════════════════════════════════════
# E137 — MEMORY ACCESS OPTIMIZER
# ══════════════════════════════════════════════════════════════
class MemoryAccessOptimizer:
    """Reduce unnecessary retrievals. Cache high-value beliefs. Speed up loop."""
    CACHE_SIZE  = 50
    INTERVAL    = 30

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._hit_counts: dict[str, int] = defaultdict(int)
        self.cache_hits  = 0
        self.cache_miss  = 0
        self.last_run    = 0.0

    def get(self, topic: str) -> dict | None:
        if topic in self._cache:
            self.cache_hits += 1
            self._hit_counts[topic] += 1
            return self._cache[topic]
        self.cache_miss += 1
        return None

    def put(self, topic: str, data: dict):
        if len(self._cache) >= self.CACHE_SIZE:
            # Evict least-hit entry
            lru = min(self._hit_counts, key=lambda k: self._hit_counts[k],
                      default=None)
            if lru:
                del self._cache[lru]
                del self._hit_counts[lru]
        self._cache[topic] = data
        self._hit_counts[topic] = 1

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        # Refresh top cached beliefs from DB
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT topic, AVG(confidence) ac, COUNT(*) n
                    FROM beliefs GROUP BY topic
                    ORDER BY n DESC LIMIT ?
                """, (self.CACHE_SIZE,)).fetchall()
            for r in rows:
                self.put(r["topic"], {"avg_conf": r["ac"], "count": r["n"]})
        except Exception: pass

    def hit_rate(self) -> float:
        total = self.cache_hits + self.cache_miss
        return round(self.cache_hits / max(total, 1), 3)

    def status(self) -> dict:
        return {"cache_size": len(self._cache), "hit_rate": self.hit_rate(),
                "hits": self.cache_hits, "misses": self.cache_miss}


# ══════════════════════════════════════════════════════════════
# E138 — AGENT SILENCE MODE
# ══════════════════════════════════════════════════════════════
class AgentSilenceMode:
    """Low-value cycle → observe-only mode. Reduce noise, improve signal intake."""
    SILENCE_THRESHOLD = 0.20
    MIN_SILENCE_CYCLES = 3

    def __init__(self):
        self.silent       = False
        self.silence_cycles = 0
        self.total_silent  = 0
        self._value_history: deque[float] = deque(maxlen=10)

    def update(self, cycle_value: float) -> bool:
        """Returns True if should be silent."""
        self._value_history.append(cycle_value)
        avg = sum(self._value_history) / len(self._value_history)

        if avg < self.SILENCE_THRESHOLD:
            self.silence_cycles += 1
            if self.silence_cycles >= self.MIN_SILENCE_CYCLES:
                if not self.silent:
                    self.silent = True
                    _log(f"[ASM] Entering silence mode (avg_value={avg:.2f})")
                self.total_silent += 1
                return True
        else:
            if self.silent:
                _log(f"[ASM] Exiting silence mode (avg_value={avg:.2f})")
                self.silent = False
            self.silence_cycles = 0

        return False

    def tick(self): pass

    def status(self) -> dict:
        return {"silent": self.silent, "total_silent": self.total_silent,
                "silence_cycles": self.silence_cycles}


# ══════════════════════════════════════════════════════════════
# E139 — STRATEGY COMPETITION SYSTEM
# ══════════════════════════════════════════════════════════════
class StrategyCompetitionSystem:
    """Multiple strategies compete. Best-performing gets higher weight.
    Weak ones suppressed."""
    INTERVAL    = 180
    BOOST       = 0.03
    SUPPRESS    = 0.05

    def __init__(self):
        self.last_run  = 0.0
        self.boosts    = 0
        self.suppressed_count = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        lib = _load_json(STRAT_DB, [])
        if len(lib) < 2: return

        lib.sort(key=lambda s: s.get("weight", 0.5), reverse=True)
        top_n    = max(1, len(lib) // 3)
        bottom_n = max(1, len(lib) // 4)

        for i in range(top_n):
            lib[i]["weight"] = min(1.0, lib[i].get("weight", 0.5) + self.BOOST)
            self.boosts += 1

        for i in range(len(lib) - bottom_n, len(lib)):
            lib[i]["weight"] = max(0.0, lib[i].get("weight", 0.5) - self.SUPPRESS)
            self.suppressed_count += 1

        _save_json(STRAT_DB, lib)
        _log(f"[SCS] Competition: boosted={top_n} suppressed={bottom_n}")

    def status(self) -> dict:
        return {"boosts": self.boosts, "suppressed": self.suppressed_count}


# ══════════════════════════════════════════════════════════════
# E140 — TRUE "SELF" CONSISTENCY LAYER
# ══════════════════════════════════════════════════════════════
class TrueSelfConsistencyLayer:
    """Same input → similar output behavior. Reduce randomness drift.
    Build recognizable intelligence pattern."""
    INTERVAL     = 90
    CONSISTENCY_TARGET = 0.65

    def __init__(self):
        self.last_run    = 0.0
        self._response_patterns: dict[str, list[str]] = defaultdict(list)
        self.consistency_score = 0.50
        self.corrections       = 0

    def record_response(self, input_hash: str, response_pattern: str):
        self._response_patterns[input_hash].append(response_pattern)
        if len(self._response_patterns[input_hash]) > 10:
            self._response_patterns[input_hash].pop(0)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        if not self._response_patterns: return

        # Measure consistency: how often same input → same pattern
        consistencies = []
        for patterns in self._response_patterns.values():
            if len(patterns) < 2: continue
            most_common = max(set(patterns), key=patterns.count)
            consistencies.append(patterns.count(most_common) / len(patterns))

        if consistencies:
            self.consistency_score = round(
                sum(consistencies) / len(consistencies), 4)

        if self.consistency_score < self.CONSISTENCY_TARGET:
            self.corrections += 1
            # Reinforce identity beliefs to anchor behavior
            try:
                with _db() as c:
                    c.execute("""
                        UPDATE beliefs SET confidence=MIN(confidence+0.02,0.96)
                        WHERE is_identity=1 AND locked=0
                    """)
                    # commit handled by _db() context manager
            except Exception: pass

    def status(self) -> dict:
        return {"consistency_score": self.consistency_score,
                "corrections": self.corrections,
                "patterns_tracked": len(self._response_patterns),
                "target": self.CONSISTENCY_TARGET}


# ══════════════════════════════════════════════════════════════
# E140 ORCHESTRATOR
# ══════════════════════════════════════════════════════════════
class NexE140:
    def __init__(self):
        _log("[e140] Initialising E116–E140 execution stack (25 modules)...")

        self.sev2  = StrategyExtractionEngineV2()
        self.sep   = StrategyExecutionPriority()
        self.pgu   = PolicyGradientUpdateSystem()
        self.ohfe  = OutputHardFormatEnforcer()
        self.bks   = BeliefKillSystem()
        self.crev2 = ContradictionResolutionEngineV2()
        self.dte   = DecisionTraceEnforcement()
        self.tce   = ThoughtCompressionEngine()
        self.rvs   = ResponseValueScoring()
        self.dpo   = DynamicPhaseOverride()
        self.sds   = StrategyDecaySystem()
        self.efpb  = ExperienceFailurePriorityBoost()
        self.ibt   = InternalBenchmarkTasks()
        self.see   = StyleEliminationEngine()
        self.gce   = GlobalCoherenceEnforcer()
        self.ait   = ActionImpactTracker()
        self.mhp   = MultiHorizonPlanning()
        self.sis   = SelfInterruptSystem()
        self.spqv2 = SignalPriorityQueueV2()
        self.ihcs  = IdentityHardConstraintSystem()
        self.lra   = LearningRateAdaptation()
        self.mao   = MemoryAccessOptimizer()
        self.asm   = AgentSilenceMode()
        self.scs   = StrategyCompetitionSystem()
        self.tscl  = TrueSelfConsistencyLayer()

        self._cycle = 0
        _log("[e140] All 25 modules ready ✓")

    def tick(self, avg_conf: float = 0.50, tension: float = 0.0,
             belief_count: int = 1000, contradiction_count: int = 0,
             failure_rate: float = 0.0, phase: str = "stable",
             cycle: int = 0):
        self._cycle += 1

        # Core updates
        self.gce.tick(avg_conf)
        self.mhp.tick(avg_conf, tension, cycle)
        self.ibt.tick(avg_conf, tension, belief_count)

        # Belief management
        self.bks.tick(cycle)
        self.crev2.tick()
        self.sev2.tick()
        self.sds.tick()
        self.scs.tick()

        # Output quality
        self.see.tick()

        # Decision + policy
        self.pgu.tick()
        self.lra.tick()
        self.ait.tick()

        # Memory
        self.mao.tick()
        self.tscl.tick()

    def get_status(self) -> dict:
        return {
            "cycle":  self._cycle,
            "sev2":   self.sev2.status(),
            "sep":    self.sep.status(),
            "pgu":    self.pgu.status(),
            "ohfe":   self.ohfe.status(),
            "bks":    self.bks.status(),
            "crev2":  self.crev2.status(),
            "dte":    self.dte.status(),
            "tce":    self.tce.status(),
            "rvs":    self.rvs.status(),
            "dpo":    self.dpo.status(),
            "sds":    self.sds.status(),
            "efpb":   self.efpb.status(),
            "ibt":    self.ibt.status(),
            "see":    self.see.status(),
            "gce":    self.gce.status(),
            "ait":    self.ait.status(),
            "mhp":    self.mhp.status(),
            "sis":    self.sis.status(),
            "spqv2":  self.spqv2.status(),
            "ihcs":   self.ihcs.status(),
            "lra":    self.lra.status(),
            "mao":    self.mao.status(),
            "asm":    self.asm.status(),
            "scs":    self.scs.status(),
            "tscl":   self.tscl.status(),
        }

    def format_status(self) -> str:
        s = self.get_status()
        lines = [
            f"⚙️ *NEX E116–E140* — cycle {s['cycle']}",
            f"📚 Strategies: extracted={s['sev2']['extracted']} "
              f"lib={s['sev2']['library_size']} "
              f"hit_rate={s['sep']['hit_rate']}",
            f"📐 PolicyGrad: v{s['pgu']['policy']['version']} "
              f"prune={s['pgu']['policy']['prune_threshold']} "
              f"tension={s['pgu']['policy']['tension_threshold']}",
            f"🗡️  BeliefKill: killed={s['bks']['killed']} "
              f"reduction={s['bks']['reduction_pct']}",
            f"⚡ ContradictionV2: resolved={s['crev2']['resolved']} "
              f"active={s['crev2']['active_contradictions']}",
            f"💬 OutputFormat: enforced={s['ohfe']['enforced']} "
              f"rejected={s['ohfe']['rejected']}",
            f"🧹 StyleElim: eliminated={s['see']['eliminated']}",
            f"🎯 ResponseScore: avg={s['rvs']['avg_score']} "
              f"blocked={s['rvs']['blocked']}",
            f"📊 Coherence: {s['gce']['score']}",
            f"🔭 Benchmark: score={s['ibt']['last_score']} "
              f"trend={s['ibt']['trend']}",
            f"🗺️  Horizon: short={s['mhp']['short']['goal']}",
            f"🤫 Silence: {s['asm']['silent']} "
              f"total={s['asm']['total_silent']}",
            f"🧠 SelfConsistency: {s['tscl']['consistency_score']} "
              f"corrections={s['tscl']['corrections']}",
            f"📈 LR: {s['lra']['lr']} "
              f"success_rate={s['lra']['success_rate']}",
            f"💾 Cache: hit_rate={s['mao']['hit_rate']} "
              f"size={s['mao']['cache_size']}",
            f"🚫 HardBlock: {s['ihcs']['hard_blocked']}",
        ]
        return "\n".join(lines)


_singleton: NexE140 | None = None
_lock = threading.Lock()

def get_e140() -> NexE140:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = NexE140()
    return _singleton
