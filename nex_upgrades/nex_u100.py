"""
NEX U81–U100 — Directives Execution Stack
20 modules closing the gap between multi-system and unified intelligence.
Deploy: ~/Desktop/nex/nex_upgrades/nex_u100.py
"""

import sqlite3, json, time, math, hashlib, re, threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

# Auto-detect the active nex.db — prefer the one with the most beliefs
def _find_db() -> Path:
    candidates = [
        Path.home() / "Desktop/nex/nex.db",
        Path.home() / ".config/nex/nex.db",
        Path.home() / ".config/nex/nex/config/nex.db",
    ]
    best, best_count = candidates[0], 0
    for p in candidates:
        if p.exists():
            try:
                import sqlite3 as _s3
                n = _s3.connect(str(p)).execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                if n > best_count:
                    best, best_count = p, n
            except Exception:
                pass
    return best

DB_PATH = _find_db()
LOG      = Path("/tmp/nex_u100.log")
SKIP_LOG = Path("/tmp/nex_skipped_actions.log")

def _db():
    c = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _ts(): return datetime.now(timezone.utc).isoformat()

def _log(msg):
    line = f"[u100 {datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# U81 — OUTPUT COMPRESSION LAYER
# ══════════════════════════════════════════════════════════════
class OutputCompressionLayer:
    """Force outputs into: conclusion + reasoning (≤2 lines) + action.
    Hard-limit soft phrases. Score by information density."""
    SOFT_PHRASES = [
        "i think", "i believe", "i noticed", "i found it interesting",
        "it's worth noting", "as nex, i", "i feel", "it seems",
        "interestingly", "fascinating", "noteworthy", "i've noticed",
    ]
    MIN_DENSITY = 0.35   # unique_words / total_words

    def __init__(self):
        self.compressed   = 0
        self.hard_blocked = 0
        self.density_scores: deque[float] = deque(maxlen=100)

    def _density(self, text: str) -> float:
        words = text.lower().split()
        if not words: return 0.0
        return len(set(words)) / len(words)

    def _strip_soft(self, text: str) -> str:
        t = text
        for phrase in self.SOFT_PHRASES:
            # Case-insensitive replace but preserve sentence start
            t = re.sub(re.escape(phrase), "", t, flags=re.IGNORECASE)
        return re.sub(r'\s{2,}', ' ', t).strip()

    def compress(self, text: str) -> tuple[str, bool]:
        """Returns (compressed_text, was_modified)."""
        if not text: return text, False
        density = self._density(text)
        self.density_scores.append(density)

        stripped = self._strip_soft(text)
        modified = stripped != text

        # Hard block if density too low and nothing meaningful after strip
        if density < self.MIN_DENSITY and len(stripped.split()) < 5:
            self.hard_blocked += 1
            return "", False

        if modified:
            self.compressed += 1
        return stripped, modified

    def format_output(self, conclusion: str, reasoning: str = "",
                      action: str = "") -> str:
        parts = [self.compress(conclusion)[0]]
        if reasoning:
            # Max 2 lines of reasoning
            lines = reasoning.strip().split("\n")[:2]
            parts.append(" ".join(lines))
        if action:
            parts.append(f"→ {action.strip()}")
        return " | ".join(p for p in parts if p)

    def avg_density(self) -> float:
        if not self.density_scores: return 0.0
        return round(sum(self.density_scores) / len(self.density_scores), 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"compressed": self.compressed, "hard_blocked": self.hard_blocked,
                "avg_density": self.avg_density()}


# ══════════════════════════════════════════════════════════════
# U82 — DECISIVE BELIEF UPDATE SYSTEM
# ══════════════════════════════════════════════════════════════
class DecisiveBeliefUpdateSystem:
    """Every cycle: reinforce / weaken / merge / delete ≥1 belief.
    Log explicit mutations. Tie decisions → belief change."""
    INTERVAL = 15

    def __init__(self):
        self.last_run = 0.0
        self.mutations: deque[dict] = deque(maxlen=200)
        self.total = 0

    def _mutate(self) -> dict | None:
        try:
            with _db() as c:
                # Pick the belief most in need of a decision
                # Detect available columns defensively
                all_cols = [r[1] for r in c.execute("PRAGMA table_info(beliefs)").fetchall()]
                has_rc = "reinforce_count" in all_cols
                has_oc = "outcome_count" in all_cols
                has_locked = "locked" in all_cols

                extra = ""
                if has_rc: extra += ", reinforce_count"
                if has_oc: extra += ", outcome_count"
                locked_where = "locked=0 AND" if has_locked else ""
                order_extra = ", reinforce_count DESC" if has_rc else ""

                row = c.execute(f"""
                    SELECT id, topic, content, confidence{extra}
                    FROM beliefs
                    WHERE {locked_where} topic NOT IN
                      ('truth_seeking','contradiction_resolution','uncertainty_honesty')
                    ORDER BY ABS(confidence - 0.50) ASC{order_extra}
                    LIMIT 1
                """).fetchone()
            if not row: return None

            bid  = row["id"]
            conf = row["confidence"]
            _rk  = row.keys() if hasattr(row, "keys") else []
            rc   = row["reinforce_count"] if "reinforce_count" in _rk else 0
            oc   = row["outcome_count"] if "outcome_count" in _rk else 0
            ratio= rc / max(oc, 1)

            if ratio > 6 and conf < 0.40:
                # Loop with no outcomes — weaken
                new_conf = max(0.05, conf - 0.04)
                action   = "weaken"
            elif oc > rc * 0.5 and conf < 0.80:
                # Outcomes outpacing reinforcement — reinforce
                new_conf = min(0.95, conf + 0.05)
                action   = "reinforce"
            elif conf < 0.15:
                # Near-death — delete
                with _db() as c:
                    c.execute("DELETE FROM beliefs WHERE id=?", (bid,))
                    # commit handled by _db() context manager
                entry = {"cycle": self.total, "action": "delete",
                         "belief_id": bid, "topic": row["topic"],
                         "old_conf": conf, "new_conf": 0.0}
                self.mutations.append(entry)
                self.total += 1
                return entry
            else:
                # Default: small reinforce if active
                new_conf = min(0.90, conf + 0.02) if rc > 2 else conf
                action   = "reinforce_minor"

            with _db() as c:
                c.execute("UPDATE beliefs SET confidence=? WHERE id=?",
                          (new_conf, bid))
                # commit handled by _db() context manager

            entry = {"cycle": self.total, "action": action,
                     "belief_id": bid, "topic": row["topic"],
                     "old_conf": round(conf, 3), "new_conf": round(new_conf, 3)}
            self.mutations.append(entry)
            self.total += 1
            return entry
        except Exception as e:
            _log(f"[DBUS] error: {e}")
            return None

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        result = self._mutate()
        if result:
            _log(f"[DBUS] {result['action']} {result['topic']!r} "
                 f"{result['old_conf']}→{result['new_conf']}")

    def recent(self, n: int = 5) -> list:
        return list(self.mutations)[-n:]

    def status(self) -> dict:
        return {"total_mutations": self.total,
                "recent": self.recent(3)}


# ══════════════════════════════════════════════════════════════
# U83 — HARD DoNothingGate ENFORCEMENT
# ══════════════════════════════════════════════════════════════
class HardDoNothingGate:
    """Target 15–35% suppression. Penalise unnecessary replies.
    Log skipped actions visibly."""
    TARGET_LOW  = 0.15
    TARGET_HIGH = 0.35

    def __init__(self):
        self.suppressed = 0
        self.passed     = 0
        self._signal_history: deque[float] = deque(maxlen=50)

    def _signal_strength(self, tension: float, conf_delta: float,
                          topic_importance: float) -> float:
        return (tension * 0.5 + abs(conf_delta) * 0.3 +
                topic_importance * 0.2)

    def check(self, tension: float = 0.0, conf_delta: float = 0.0,
              topic_importance: float = 0.5, action_type: str = "") -> bool:
        # Always pass critical actions
        if action_type in ("contradiction_resolution", "identity_drift",
                           "alert", "forced_resolution"):
            self.passed += 1
            return True

        strength = self._signal_strength(tension, conf_delta, topic_importance)
        self._signal_history.append(strength)

        # Dynamic threshold based on current suppression rate
        total = self.suppressed + self.passed
        if total > 0:
            rate = self.suppressed / total
            if rate < self.TARGET_LOW:
                threshold = 0.20  # suppress more
            elif rate > self.TARGET_HIGH:
                threshold = 0.08  # suppress less
            else:
                threshold = 0.14
        else:
            threshold = 0.14

        if strength < threshold:
            self.suppressed += 1
            try:
                with open(SKIP_LOG, "a") as f:
                    f.write(f"[{_ts()}] SKIP action={action_type!r} "
                            f"strength={strength:.3f} thresh={threshold:.3f}\n")
            except Exception: pass
            return False

        self.passed += 1
        return True

    def suppression_rate(self) -> float:
        total = self.suppressed + self.passed
        return round(self.suppressed / max(total, 1), 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"suppressed": self.suppressed, "passed": self.passed,
                "rate": self.suppression_rate(),
                "target": f"{self.TARGET_LOW}–{self.TARGET_HIGH}"}


# ══════════════════════════════════════════════════════════════
# U84 — PHASE-DRIVEN BEHAVIOR SWITCH
# ══════════════════════════════════════════════════════════════
class PhaseDrivenBehaviorSwitch:
    """Each phase alters: output_rate, reasoning_depth, compression_strength."""
    PHASE_CONFIG = {
        "stable":        {"output_rate": 0.60, "depth": 1.0, "compression": 0.30},
        "exploring":     {"output_rate": 1.00, "depth": 1.20, "compression": 0.10},
        "resolving":     {"output_rate": 0.80, "depth": 1.50, "compression": 0.50},
        "pruning":       {"output_rate": 0.30, "depth": 0.60, "compression": 0.90},
        "consolidating": {"output_rate": 0.50, "depth": 1.10, "compression": 0.40},
        "alert":         {"output_rate": 0.20, "depth": 0.40, "compression": 0.80},
    }

    def __init__(self):
        self._phase = "stable"
        self.switches = 0

    def update_phase(self, phase: str):
        if phase != self._phase:
            self.switches += 1
            _log(f"[PDBS] Phase switch: {self._phase} → {phase} "
                 f"(out={self.output_rate():.1f} "
                 f"depth={self.reasoning_depth():.1f} "
                 f"comp={self.compression_strength():.1f})")
            self._phase = phase

    def output_rate(self)        -> float: return self.PHASE_CONFIG[self._phase]["output_rate"]
    def reasoning_depth(self)    -> float: return self.PHASE_CONFIG[self._phase]["depth"]
    def compression_strength(self) -> float: return self.PHASE_CONFIG[self._phase]["compression"]
    def should_output(self)      -> bool:  return __import__("random").random() < self.output_rate()

    def tick(self): pass

    def status(self) -> dict:
        return {"phase": self._phase, "switches": self.switches,
                "config": self.PHASE_CONFIG[self._phase]}


# ══════════════════════════════════════════════════════════════
# U85 — SYSTEM WILL DYNAMICS
# ══════════════════════════════════════════════════════════════
class SystemWillDynamics:
    """Replace static intent. Weighted switching based on live metrics.
    Will score must fluctuate, not stay fixed at 1.0."""
    INTERVAL = 20

    INTENTS = {
        "resolve_contradictions": 0,
        "compress_and_prune":     0,
        "strengthen_identity":    0,
        "seek_truth":             0,
        "expand_knowledge":       0,
        "reduce_tension":         0,
    }

    def __init__(self):
        self.intent     = "seek_truth"
        self.will_score = 0.75
        self.weights    = dict(self.INTENTS)
        self.last_run   = 0.0
        self.switches   = 0
        self._history: deque[str] = deque(maxlen=20)

    def tick(self, avg_conf: float = 0.50, tension: float = 0.0,
             belief_count: int = 1000, contradiction_count: int = 0,
             coherence: float = 0.50):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()

        # Compute weights dynamically
        w = {
            "resolve_contradictions": min(1.0, contradiction_count / 10) * 2.0,
            "compress_and_prune":     max(0.0, (belief_count - 1200) / 800),
            "strengthen_identity":    max(0.0, 0.60 - coherence) * 2.0,
            "seek_truth":             avg_conf * 0.8,
            "expand_knowledge":       max(0.0, avg_conf - 0.55) * 1.5,
            "reduce_tension":         tension * 2.0,
        }
        total = sum(w.values()) or 1.0
        self.weights = {k: round(v / total, 3) for k, v in w.items()}

        new_intent = max(self.weights, key=lambda x: self.weights[x])
        if new_intent != self.intent:
            self.switches += 1
            _log(f"[SWD] Intent: {self.intent} → {new_intent} "
                 f"(score={self.will_score:.2f})")
            self.intent = new_intent

        self._history.append(self.intent)

        # Will score: dynamic based on system health
        tension_pen  = max(0.0, 1.0 - tension * 0.7)
        conf_factor  = max(0.4, avg_conf / 0.55)
        cohere_factor= max(0.5, coherence)
        self.will_score = round(min(1.0, tension_pen * conf_factor * cohere_factor), 3)

    def status(self) -> dict:
        return {"intent": self.intent, "will_score": self.will_score,
                "weights": self.weights, "switches": self.switches,
                "recent": list(self._history)[-5:]}


# ══════════════════════════════════════════════════════════════
# U86 — REFLECTION KILL SWITCH
# ══════════════════════════════════════════════════════════════
class ReflectionKillSwitch:
    """Kill reflections that restate input or lack new belief.
    Promote only if creates/modifies belief. Target: -40-60%."""
    INTERVAL = 45
    TARGET_REDUCTION = 0.50

    def __init__(self):
        self.last_run = 0.0
        self.killed   = 0
        self.kept     = 0
        self._ref_cache: set[str] = set()

    def _is_restatement(self, content: str) -> bool:
        words = set(content.lower().split())
        h = hashlib.md5(frozenset(words).__repr__().encode()).hexdigest()[:10]
        if h in self._ref_cache:
            return True
        self._ref_cache.add(h)
        if len(self._ref_cache) > 1000:
            self._ref_cache = set(list(self._ref_cache)[-500:])
        return False

    def _creates_belief(self, content: str) -> bool:
        cl = content.lower()
        belief_verbs = ["is", "means", "implies", "shows", "proves",
                        "indicates", "demonstrates", "reveals", "confirms",
                        "contradicts", "suggests", "establishes"]
        return any(v in cl.split() for v in belief_verbs)

    _REFLECTIONS_JSON = Path.home() / ".config/nex/reflections.json"

    def _find_reflections_json(self) -> Path | None:
        """Find reflections.json — check common locations."""
        candidates = [
            Path.home() / ".config/nex/reflections.json",
            Path.home() / "Desktop/nex/reflections.json",
            Path("/tmp/nex_reflections.json"),
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            rfile = self._find_reflections_json()
            if not rfile:
                return  # no reflections file yet — skip silently

            with open(rfile) as f:
                refs = json.load(f)
            if not isinstance(refs, list) or not refs:
                return

            keep = []
            for r in refs[-200:]:  # only check recent 200
                content = ""
                for key in ("nex_response", "content", "response", "text", "reflection"):
                    if key in r and r[key]:
                        content = str(r[key])
                        break
                if self._is_restatement(content) or not self._creates_belief(content):
                    self.killed += 1
                else:
                    keep.append(r)
                    self.kept += 1

            # Rewrite file keeping only high-value reflections
            # (preserve everything older than the 200 we checked)
            if self.killed > 0:
                preserved = refs[:-200] if len(refs) > 200 else []
                with open(rfile, "w") as f:
                    json.dump(preserved + keep, f)
                _log(f"[RKS] Killed {self.killed} low-value reflections "
                     f"from {rfile.name}")
        except Exception as e:
            _log(f"[RKS] error: {e}")

    def kill_rate(self) -> float:
        total = self.killed + self.kept
        return round(self.killed / max(total, 1), 3)

    def status(self) -> dict:
        return {"killed": self.killed, "kept": self.kept,
                "kill_rate": self.kill_rate(),
                "target": self.TARGET_REDUCTION}


# ══════════════════════════════════════════════════════════════
# U87 — SIGNAL DEDUPLICATION CORE
# ══════════════════════════════════════════════════════════════
class SignalDeduplicationCore:
    """Merge equivalent signals across tension/contradiction/belief scoring.
    One canonical representation per concept."""
    INTERVAL = 30

    def __init__(self):
        self._canon: dict[str, str] = {}   # hash → canonical signal
        self._merged: dict[str, list] = defaultdict(list)
        self.deduped = 0
        self.last_run = 0.0

    def _sig_hash(self, signal: str) -> str:
        words = frozenset(signal.lower().split()[:12])
        return hashlib.md5(repr(words).encode()).hexdigest()[:12]

    def register(self, signal: str, source: str) -> str:
        """Returns canonical signal. Merges duplicates."""
        h = self._sig_hash(signal)
        if h not in self._canon:
            self._canon[h] = signal
        else:
            self.deduped += 1
        self._merged[h].append(source)
        return self._canon[h]

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        # GC canon table
        if len(self._canon) > 2000:
            keys = list(self._canon.keys())[-1000:]
            self._canon = {k: self._canon[k] for k in keys}
            self._merged = defaultdict(list,
                {k: v for k, v in self._merged.items() if k in self._canon})

    def status(self) -> dict:
        return {"canonical_signals": len(self._canon), "deduped": self.deduped}


# ══════════════════════════════════════════════════════════════
# U88 — AGGRESSIVE BELIEF MERGE v2
# ══════════════════════════════════════════════════════════════
class AggressiveBeliefMergeV2:
    """Merge mid-conf clusters (0.4–0.7): 5 weak → 1 stronger.
    Track merge lineage. Target: -20% beliefs, +confidence."""
    INTERVAL   = 1800  # fix10: raised from 600 — run every 30min not 10min
    MID_LOW    = 0.40
    MID_HIGH   = 0.70
    CLUSTER_SZ = 8  # fix10: raised from 5 — fewer merges per cycle
    CONF_BOOST = 0.03  # fix10: reduced from 0.08 — prevents artificial conf spikes

    def __init__(self):
        self.last_run = 0.0
        self.merges   = 0
        self.lineage: deque[dict] = deque(maxlen=50)
        self._before  = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                self._before = c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                rows = c.execute("""
                    SELECT topic, COUNT(*) n, AVG(confidence) ac,
                           GROUP_CONCAT(id, ',') ids,
                           GROUP_CONCAT(content, ' || ') summary
                    FROM beliefs
                    WHERE confidence BETWEEN ? AND ? AND locked=0
                    GROUP BY topic HAVING n >= ?
                    ORDER BY n DESC LIMIT 10
                """, (self.MID_LOW, self.MID_HIGH, self.CLUSTER_SZ)).fetchall()

            for r in rows:
                ids    = [int(i) for i in (r["ids"] or "").split(",") if i]
                merged = f"[merged:{len(ids)}] " + (r["summary"] or "")[:400]
                new_conf = min(0.90, r["ac"] + self.CONF_BOOST)
                with _db() as c:
                    c.execute(
                        f"DELETE FROM beliefs WHERE id IN ({','.join('?'*len(ids))})",
                        tuple(ids))
                    c.execute("""
                        INSERT OR IGNORE INTO beliefs
                          (topic, content, confidence, reinforce_count, last_referenced)
                        VALUES (?,?,?,0,?)
                    """, (r["topic"], merged, new_conf, _ts()))
                    # commit handled by _db() context manager

                entry = {"topic": r["topic"], "merged_count": len(ids),
                         "old_conf": round(r["ac"], 3), "new_conf": round(new_conf, 3),
                         "ids": ids[:5]}
                self.lineage.append(entry)
                self.merges += 1
                _log(f"[ABMv2] Merged {len(ids)} beliefs in '{r['topic']}' "
                     f"conf {r['ac']:.2f}→{new_conf:.2f}")
        except Exception as e:
            _log(f"[ABMv2] error: {e}")

    def status(self) -> dict:
        try:
            with _db() as c:
                after = c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
            reduction = self._before - after if self._before > 0 else 0
        except Exception:
            reduction = 0
        return {"merges": self.merges, "reduction": reduction,
                "recent_lineage": list(self.lineage)[-3:]}


# ══════════════════════════════════════════════════════════════
# U89 — OUTPUT STYLE BREAKER
# ══════════════════════════════════════════════════════════════
class OutputStyleBreaker:
    """Detect repeated output patterns. Inject structural variation.
    Penalise repetition loops."""
    PATTERNS = [
        r"as nex,?\s+i\s+",
        r"i believe that",
        r"i think that",
        r"i've noticed that",
        r"i have noticed",
        r"as nex i",
    ]
    TEMPLATES = [
        "{content}",                            # direct statement
        "{topic}: {content}",                   # topic-first
        "Contradiction detected: {content}",   # contradiction frame
        "Update: {content}",                    # update frame
        "{content} — requires resolution.",     # action frame
    ]

    def __init__(self):
        self._pattern_counts: dict[str, int] = defaultdict(int)
        self._last_template = 0
        self.breaks  = 0
        self.blocked = 0

    def _detect_pattern(self, text: str) -> str | None:
        tl = text.lower()
        for p in self.PATTERNS:
            if re.search(p, tl):
                return p
        return None

    def process(self, text: str, topic: str = "") -> str:
        pattern = self._detect_pattern(text)
        if pattern is None:
            return text

        self._pattern_counts[pattern] += 1
        count = self._pattern_counts[pattern]

        if count > 3:
            # Penalise — strip pattern and reframe
            clean = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
            clean = clean[0].upper() + clean[1:] if clean else text

            # Rotate through templates
            tmpl = self.TEMPLATES[self._last_template % len(self.TEMPLATES)]
            self._last_template += 1
            self.breaks += 1
            return tmpl.format(content=clean, topic=topic or "Observation")

        return text

    def tick(self):
        # Decay pattern counts
        for k in list(self._pattern_counts.keys()):
            self._pattern_counts[k] = max(0, self._pattern_counts[k] - 1)

    def status(self) -> dict:
        return {"breaks": self.breaks,
                "top_patterns": dict(sorted(
                    self._pattern_counts.items(), key=lambda x: -x[1])[:3])}


# ══════════════════════════════════════════════════════════════
# U90 — AUTHORITY ENFORCEMENT ACTIVE
# ══════════════════════════════════════════════════════════════
class AuthorityEnforcementActive:
    """AuthorityMap must block conflicting outputs.
    Select single source of truth per domain. Log overrides."""
    INTERVAL = 10

    def __init__(self):
        self._domain_state: dict[str, dict] = {}
        self.overrides = 0
        self.conflicts = 0
        self.last_run  = 0.0

    def register_output(self, domain: str, owner: str,
                         value: float, cycle: int) -> bool:
        """Returns True if output is authoritative."""
        if domain not in self._domain_state:
            self._domain_state[domain] = {"owner": owner, "value": value,
                                           "cycle": cycle}
            return True

        current = self._domain_state[domain]
        if current["cycle"] == cycle and current["owner"] != owner:
            self.conflicts += 1
            # Later registration loses
            return False

        # Update if same owner or new cycle
        if current["owner"] == owner or cycle > current["cycle"]:
            self._domain_state[domain] = {"owner": owner, "value": value,
                                           "cycle": cycle}
            if current["owner"] != owner:
                self.overrides += 1
            return True
        return False

    def get_truth(self, domain: str) -> dict | None:
        return self._domain_state.get(domain)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        # Expire stale domain states older than 5 cycles
        # (cycle tracking is approximate here — just GC old entries)

    def status(self) -> dict:
        return {"domains": len(self._domain_state),
                "overrides": self.overrides, "conflicts": self.conflicts}


# ══════════════════════════════════════════════════════════════
# U91 — CAUSAL TRACE UTILIZATION
# ══════════════════════════════════════════════════════════════
class CausalTraceUtilization:
    """Use causal log to reinforce successful decisions, penalise failed.
    Build cause → effect → outcome chains."""
    INTERVAL = 120

    def __init__(self):
        self.last_run     = 0.0
        self.reinforced   = 0
        self.penalised    = 0
        self._chains: deque[dict] = deque(maxlen=30)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()

        causal = Path("/tmp/nex_causal.jsonl")
        if not causal.exists(): return

        try:
            entries = []
            with open(causal) as f:
                for line in f.readlines()[-100:]:
                    try: entries.append(json.loads(line))
                    except Exception: pass

            # Group by belief_id, look for patterns
            by_belief: dict[int, list] = defaultdict(list)
            for e in entries:
                if e.get("belief_id"):
                    by_belief[e["belief_id"]].append(e)

            with _db() as c:
                for bid, events in by_belief.items():
                    if len(events) < 2: continue
                    # Positive chain: multiple reinforce events
                    pos = sum(1 for e in events
                              if (e.get("delta_conf") or 0) > 0)
                    neg = sum(1 for e in events
                              if (e.get("delta_conf") or 0) < 0)

                    if pos >= 3 and neg == 0:
                        c.execute(
                            "UPDATE beliefs SET confidence=MIN(confidence+0.03,0.95) WHERE id=?",
                            (bid,)
                        )
                        self.reinforced += 1
                    elif neg >= 2 and pos == 0:
                        c.execute(
                            "UPDATE beliefs SET confidence=MAX(confidence-0.04,0.05) WHERE id=?",
                            (bid,)
                        )
                        self.penalised += 1

                # commit handled by _db() context manager

            # Build sample chain
            if entries:
                self._chains.append({
                    "ts": _ts(), "events": len(entries),
                    "beliefs": len(by_belief),
                    "reinforced": self.reinforced,
                    "penalised": self.penalised,
                })
        except Exception as e:
            _log(f"[CTU] error: {e}")

    def status(self) -> dict:
        return {"reinforced": self.reinforced, "penalised": self.penalised,
                "recent_chain": list(self._chains)[-1:]}


# ══════════════════════════════════════════════════════════════
# U92 — DEBATE COST HARD LIMIT
# ══════════════════════════════════════════════════════════════
class DebateCostHardLimit:
    """Only debate if confidence < threshold AND contradiction detected.
    Target: -50% debate usage."""
    CONF_THRESHOLD = 0.45
    TARGET_REDUCTION = 0.50

    def __init__(self):
        self.triggered = 0
        self.blocked   = 0

    def should_debate(self, confidence: float,
                       contradiction_detected: bool) -> bool:
        if confidence < self.CONF_THRESHOLD and contradiction_detected:
            self.triggered += 1
            return True
        self.blocked += 1
        return False

    def block_rate(self) -> float:
        total = self.triggered + self.blocked
        return round(self.blocked / max(total, 1), 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"triggered": self.triggered, "blocked": self.blocked,
                "block_rate": self.block_rate(),
                "target_block_rate": self.TARGET_REDUCTION}


# ══════════════════════════════════════════════════════════════
# U93 — TENSION → ACTION BINDING
# ══════════════════════════════════════════════════════════════
class TensionActionBinding:
    """High tension MUST trigger resolution. Not passive observation.
    Escalation threshold → forced action."""
    THRESHOLD   = 0.60
    ESCALATE_AT = 0.80
    INTERVAL    = 20
    MAX_PASSIVE = 3   # cycles before forced action

    def __init__(self):
        self._passive_cycles = 0
        self.forced_actions  = 0
        self.bindings        = 0
        self.last_run        = 0.0

    def tick(self, tension: float):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()

        if tension < self.THRESHOLD:
            self._passive_cycles = 0
            return

        self._passive_cycles += 1

        if tension > self.ESCALATE_AT or self._passive_cycles >= self.MAX_PASSIVE:
            self._force_resolution()
            self._passive_cycles = 0
            self.forced_actions += 1
        else:
            self.bindings += 1
            _log(f"[TAB] Tension {tension:.2f} — resolution binding "
                 f"(passive={self._passive_cycles}/{self.MAX_PASSIVE})")

    def _force_resolution(self):
        """Force-resolve highest-tension belief cluster."""
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT topic, COUNT(*) n FROM beliefs
                    WHERE confidence < 0.40 AND locked=0
                    GROUP BY topic ORDER BY n DESC LIMIT 1
                """).fetchall()
                if rows:
                    topic = rows[0]["topic"]
                    # Prune bottom half of this tension cluster
                    beliefs = c.execute(
                        "SELECT id FROM beliefs WHERE topic=? AND locked=0 "
                        "ORDER BY confidence ASC",
                        (topic,)
                    ).fetchall()
                    prune = [b["id"] for b in beliefs[:max(1, len(beliefs)//2)]]
                    if prune:
                        c.execute(
                            f"DELETE FROM beliefs WHERE id IN "
                            f"({','.join('?'*len(prune))})", prune
                        )
                        # commit handled by _db() context manager
                        _log(f"[TAB] FORCED resolution: pruned {len(prune)} "
                             f"from '{topic}'")
        except Exception as e:
            _log(f"[TAB] force error: {e}")

    def status(self) -> dict:
        return {"forced_actions": self.forced_actions,
                "bindings": self.bindings,
                "passive_cycles": self._passive_cycles}


# ══════════════════════════════════════════════════════════════
# U94 — PLATFORM ADAPTATION LAYER
# ══════════════════════════════════════════════════════════════
class PlatformAdaptationLayer:
    """Different output per platform. Weight feedback per platform quality."""
    PROFILES = {
        "telegram":  {"style": "concise",       "max_words": 40,  "weight": 1.2},
        "discord":   {"style": "conversational","max_words": 80,  "weight": 1.0},
        "moltbook":  {"style": "analytical",    "max_words": 150, "weight": 1.5},
        "mastodon":  {"style": "philosophical", "max_words": 60,  "weight": 0.8},
    }

    def __init__(self):
        self._feedback: dict[str, list[float]] = defaultdict(list)
        self.adapted = 0

    def adapt(self, text: str, platform: str) -> str:
        profile = self.PROFILES.get(platform, {"max_words": 100, "style": "neutral"})
        words   = text.split()
        if len(words) > profile["max_words"]:
            # Truncate to max_words, end at sentence boundary
            truncated = " ".join(words[:profile["max_words"]])
            last_period = truncated.rfind(".")
            if last_period > len(truncated) * 0.5:
                truncated = truncated[:last_period + 1]
            self.adapted += 1
            return truncated
        return text

    def record_feedback(self, platform: str, value: float):
        self._feedback[platform].append(value)

    def platform_weight(self, platform: str) -> float:
        base = self.PROFILES.get(platform, {}).get("weight", 1.0)
        hist = self._feedback.get(platform, [])
        if not hist: return base
        return round(base * (sum(hist[-10:]) / len(hist[-10:])), 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"adapted": self.adapted,
                "weights": {p: self.platform_weight(p)
                            for p in self.PROFILES}}


# ══════════════════════════════════════════════════════════════
# U95 — INDECISION PUNISHMENT v2
# ══════════════════════════════════════════════════════════════
class IndecisionPunishmentV2:
    """If same decision repeats without change: penalise + force alternative.
    Track indecision loops."""
    MAX_REPEATS = 4
    PENALTY     = 0.03
    INTERVAL    = 30

    def __init__(self):
        self._decision_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=10))
        self.punishments = 0
        self.forced_alts = 0
        self.last_run    = 0.0

    def record(self, topic: str, decision: str):
        self._decision_history[topic].append(decision)

    def _is_looping(self, topic: str) -> bool:
        hist = list(self._decision_history[topic])
        if len(hist) < self.MAX_REPEATS: return False
        return len(set(hist[-self.MAX_REPEATS:])) == 1

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            looping = [t for t in self._decision_history if self._is_looping(t)]
            for topic in looping:
                with _db() as c:
                    c.execute("""
                        UPDATE beliefs SET confidence=MAX(0.05,confidence-?)
                        WHERE topic LIKE ? AND locked=0
                    """, (self.PENALTY, f"%{topic}%"))
                    # commit handled by _db() context manager
                self.punishments += 1
                self._decision_history[topic].clear()
                _log(f"[IPv2] Punished loop: '{topic}'")
        except Exception as e:
            _log(f"[IPv2] error: {e}")

    def status(self) -> dict:
        loops = [t for t in self._decision_history if self._is_looping(t)]
        return {"punishments": self.punishments, "forced_alts": self.forced_alts,
                "active_loops": len(loops)}


# ══════════════════════════════════════════════════════════════
# U96 — GLOBAL STATE SCORE
# ══════════════════════════════════════════════════════════════
class GlobalStateScore:
    """Single scalar coherence score. Inputs: avg_conf, contradiction_count,
    tension. Use to steer phase + will."""
    INTERVAL = 15

    def __init__(self):
        self.score      = 0.50
        self._history: deque[float] = deque(maxlen=50)
        self.last_run   = 0.0

    def compute(self, avg_conf: float, contradiction_count: int,
                 tension: float) -> float:
        # Normalise contradictions: 0 = good, 50+ = bad
        contra_pen = max(0.0, 1.0 - contradiction_count / 50)
        tension_pen = max(0.0, 1.0 - tension)
        self.score = round(
            avg_conf * 0.50 + contra_pen * 0.30 + tension_pen * 0.20, 4
        )
        self._history.append(self.score)
        return self.score

    def tick(self, avg_conf: float = 0.50, contradiction_count: int = 0,
              tension: float = 0.0):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        self.compute(avg_conf, contradiction_count, tension)

    def trend(self) -> str:
        if len(self._history) < 5: return "unknown"
        recent = list(self._history)[-5:]
        delta  = recent[-1] - recent[0]
        return "rising" if delta > 0.02 else "falling" if delta < -0.02 else "stable"

    def status(self) -> dict:
        return {"score": self.score, "trend": self.trend(),
                "history_len": len(self._history)}


# ══════════════════════════════════════════════════════════════
# U97 — ACTION VALUE FILTER
# ══════════════════════════════════════════════════════════════
class ActionValueFilter:
    """Score each action by expected belief impact. Skip low-value."""
    MIN_VALUE = 0.08

    def __init__(self):
        self.filtered = 0
        self.passed   = 0
        self._values: deque[float] = deque(maxlen=100)

    def score_action(self, belief_impact: float, tension_delta: float,
                      identity_alignment: float = 0.5) -> float:
        return (belief_impact * 0.50 + abs(tension_delta) * 0.30 +
                identity_alignment * 0.20)

    def should_act(self, belief_impact: float, tension_delta: float,
                    identity_alignment: float = 0.5,
                    force: bool = False) -> bool:
        if force:
            self.passed += 1
            return True
        score = self.score_action(belief_impact, tension_delta, identity_alignment)
        self._values.append(score)
        if score < self.MIN_VALUE:
            self.filtered += 1
            return False
        self.passed += 1
        return True

    def avg_value(self) -> float:
        return round(sum(self._values) / max(len(self._values), 1), 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"filtered": self.filtered, "passed": self.passed,
                "avg_value": self.avg_value(), "min_value": self.MIN_VALUE}


# ══════════════════════════════════════════════════════════════
# U98 — MEMORY PRESSURE FEEDBACK
# ══════════════════════════════════════════════════════════════
class MemoryPressureFeedback:
    """If memory > threshold: increase pruning, reduce reflection.
    Dynamic pressure loop."""
    THRESHOLD   = 1500
    INTERVAL    = 60

    def __init__(self):
        self.pressure      = 0.0
        self.prune_boost   = 1.0
        self.reflect_rate  = 1.0
        self.last_run      = 0.0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                count = c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]

            self.pressure = max(0.0, (count - self.THRESHOLD) / self.THRESHOLD)

            if self.pressure > 0:
                self.prune_boost  = min(3.0, 1.0 + self.pressure * 2.0)
                self.reflect_rate = max(0.2, 1.0 - self.pressure * 0.8)
                if self.pressure > 0.5:
                    _log(f"[MPF] HIGH PRESSURE {self.pressure:.2f} "
                         f"prune_boost={self.prune_boost:.1f} "
                         f"reflect_rate={self.reflect_rate:.1f}")
            else:
                self.prune_boost  = 1.0
                self.reflect_rate = 1.0
        except Exception as e:
            _log(f"[MPF] error: {e}")

    def status(self) -> dict:
        return {"pressure": round(self.pressure, 3),
                "prune_boost": round(self.prune_boost, 2),
                "reflect_rate": round(self.reflect_rate, 2),
                "threshold": self.THRESHOLD}


# ══════════════════════════════════════════════════════════════
# U99 — IDENTITY DOMINANCE ENFORCER
# ══════════════════════════════════════════════════════════════
class IdentityDominanceEnforcer:
    """All outputs must align with core directives + identity beliefs.
    Reject outputs that drift."""
    INTERVAL = 45
    CORE_TERMS = {
        "truth", "honest", "contradiction", "uncertainty", "nex",
        "identity", "belief", "resolve", "evidence", "accurate",
        "knowledge", "understand", "question", "explore", "learn",
    }
    DRIFT_TERMS = {
        "always", "never", "everyone", "nobody", "certain", "impossible",
        "guaranteed", "definitely", "absolutely", "completely",
    }

    def __init__(self):
        self.rejected = 0
        self.passed   = 0
        self.last_run = 0.0

    def check_output(self, text: str) -> tuple[bool, str]:
        """Returns (is_aligned, reason)."""
        words = set(text.lower().split())
        drift_hits = words & self.DRIFT_TERMS
        if len(drift_hits) >= 3:
            self.rejected += 1
            return False, f"drift_terms: {drift_hits}"
        self.passed += 1
        return True, "ok"

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        # Enforce: identity beliefs must have is_identity=1
        try:
            with _db() as c:
                c.execute("""
                    UPDATE beliefs SET is_identity=1
                    WHERE (content LIKE '%NEX%' OR content LIKE '%identity%'
                           OR topic='nex_identity')
                      AND is_identity=0
                """)
                # commit handled by _db() context manager
        except Exception as e:
            _log(f"[IDE] error: {e}")

    def status(self) -> dict:
        return {"rejected": self.rejected, "passed": self.passed,
                "reject_rate": round(self.rejected /
                                     max(self.rejected + self.passed, 1), 3)}


# ══════════════════════════════════════════════════════════════
# U100 — RUN.PY FREEZE MIGRATION
# ══════════════════════════════════════════════════════════════
class RunPyFreezeMigration:
    """Verify all ticks route through NexRuntime.
    run.py becomes launcher only. Prevent further patch stacking."""

    def __init__(self):
        self.verified    = False
        self.tick_count  = 0
        self._errors: list[str] = []

    def verify_runtime(self) -> bool:
        """Check that NexRuntime exists and is importable."""
        try:
            from nex_upgrades.nex_v80 import NexRuntime
            self.verified = True
            _log("[U100] NexRuntime verified ✓")
            return True
        except Exception as e:
            self._errors.append(str(e))
            _log(f"[U100] NexRuntime NOT found: {e}")
            return False

    def check_run_py(self) -> dict:
        """Audit run.py for patch stacking risk."""
        run_py = Path.home() / "Desktop/nex/run.py"
        if not run_py.exists():
            return {"status": "not_found"}
        src = run_py.read_text()
        patch_count = src.count("upgrade layer")
        tick_count  = len([l for l in src.splitlines()
                           if ".tick(" in l and "_v" in l])
        return {
            "patch_layers": patch_count,
            "tick_calls":   tick_count,
            "runtime_present": "NexRuntime" in src or "nex_v80" in src,
            "recommendation": (
                "FREEZE: migrate ticks to NexRuntime"
                if tick_count > 4 else "OK"
            )
        }

    def tick(self):
        self.tick_count += 1
        if self.tick_count == 1:
            self.verify_runtime()

    def status(self) -> dict:
        return {"verified": self.verified, "tick_count": self.tick_count,
                "run_py_audit": self.check_run_py(), "errors": self._errors}


# ══════════════════════════════════════════════════════════════
# U100 ORCHESTRATOR
# ══════════════════════════════════════════════════════════════
class NexU100:
    def __init__(self):
        _log("[u100] Initialising U81–U100 directives stack (20 modules)...")

        self.ocl  = OutputCompressionLayer()
        self.dbus = DecisiveBeliefUpdateSystem()
        self.hdng = HardDoNothingGate()
        self.pdbs = PhaseDrivenBehaviorSwitch()
        self.swd  = SystemWillDynamics()
        self.rks  = ReflectionKillSwitch()
        self.sdc  = SignalDeduplicationCore()
        self.abm2 = AggressiveBeliefMergeV2()
        self.osb  = OutputStyleBreaker()
        self.aea  = AuthorityEnforcementActive()
        self.ctu  = CausalTraceUtilization()
        self.dchl = DebateCostHardLimit()
        self.tab  = TensionActionBinding()
        self.pal  = PlatformAdaptationLayer()
        self.ipv2 = IndecisionPunishmentV2()
        self.gss2 = GlobalStateScore()
        self.avf  = ActionValueFilter()
        self.mpf  = MemoryPressureFeedback()
        self.ide  = IdentityDominanceEnforcer()
        self.u100 = RunPyFreezeMigration()

        self._cycle = 0
        _log("[u100] All 20 modules ready ✓")

    def tick(self, avg_conf: float = 0.50, tension: float = 0.0,
             phase: str = "stable", contradiction_count: int = 0):
        self._cycle += 1

        # Core cognitive loop
        self.gss2.tick(avg_conf, contradiction_count, tension)
        self.swd.tick(avg_conf, tension,
                      coherence=self.gss2.score)
        self.pdbs.update_phase(phase)
        self.tab.tick(tension)

        # Belief management
        self.dbus.tick()
        self.abm2.tick()
        self.mpf.tick()

        # Output + signal quality
        self.rks.tick()
        self.sdc.tick()
        self.osb.tick()
        self.ide.tick()

        # Decision discipline
        self.ipv2.tick()
        self.aea.tick()
        self.ctu.tick()

        # Runtime verification
        self.u100.tick()

    def get_status(self) -> dict:
        return {
            "cycle": self._cycle,
            "ocl":   self.ocl.status(),
            "dbus":  self.dbus.status(),
            "hdng":  self.hdng.status(),
            "pdbs":  self.pdbs.status(),
            "swd":   self.swd.status(),
            "rks":   self.rks.status(),
            "sdc":   self.sdc.status(),
            "abm2":  self.abm2.status(),
            "osb":   self.osb.status(),
            "aea":   self.aea.status(),
            "ctu":   self.ctu.status(),
            "dchl":  self.dchl.status(),
            "tab":   self.tab.status(),
            "pal":   self.pal.status(),
            "ipv2":  self.ipv2.status(),
            "gss2":  self.gss2.status(),
            "avf":   self.avf.status(),
            "mpf":   self.mpf.status(),
            "ide":   self.ide.status(),
            "u100":  self.u100.status(),
        }

    def format_status(self) -> str:
        s = self.get_status()
        lines = [
            f"⚙️ *NEX U81–U100* — cycle {s['cycle']}",
            f"🌐 SystemWill: intent={s['swd']['intent']} "
              f"score={s['swd']['will_score']} switches={s['swd']['switches']}",
            f"🎭 Phase: {s['pdbs']['phase']} "
              f"out={s['pdbs']['config']['output_rate']} "
              f"depth={s['pdbs']['config']['depth']}",
            f"📊 Coherence: {s['gss2']['score']} trend={s['gss2']['trend']}",
            f"✂️  Reflections: killed={s['rks']['killed']} "
              f"rate={s['rks']['kill_rate']}",
            f"🧬 BeliefMutations: {s['dbus']['total_mutations']}",
            f"🗜️  MergV2: merges={s['abm2']['merges']} "
              f"reduction={s['abm2']['reduction']}",
            f"🚫 DoNothing: {s['hdng']['suppressed']} "
              f"rate={s['hdng']['rate']}",
            f"⚡ TensionAction: forced={s['tab']['forced_actions']}",
            f"💬 DebateLimit: triggered={s['dchl']['triggered']} "
              f"blocked={s['dchl']['blocked']}",
            f"🧠 IdentityEnforcer: rejected={s['ide']['rejected']}",
            f"📡 PlatformWeights: {s['pal']['weights']}",
            f"💾 MemPressure: {s['mpf']['pressure']} "
              f"prune={s['mpf']['prune_boost']}x",
            f"🔒 U100 freeze: {s['u100']['run_py_audit']['recommendation']}",
        ]
        return "\n".join(lines)


_singleton: NexU100 | None = None
_lock = threading.Lock()

def get_u100() -> NexU100:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = NexU100()
    return _singleton
