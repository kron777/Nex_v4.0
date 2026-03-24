"""
NEX v8.0 — Unification Layer (GPT Assessment Response)
14-module stack: SystemWill, GlobalState, Authority, Runtime, and more.
Deploy: ~/Desktop/nex/nex_upgrades/nex_v80.py
"""

import sqlite3, json, time, math, hashlib, threading, re
from collections import defaultdict, deque
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

DB_PATH = Path.home() / ".config/nex/nex_data/nex.db"
LOG     = Path("/tmp/nex_v80.log")
CAUSAL  = Path("/tmp/nex_causal.jsonl")
NET_LOG = Path("/tmp/nex_net_failures.txt")
AUTH_LOG= Path("/tmp/nex_authority_violations.txt")

def _db():
    c = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _ts():
    return datetime.now(timezone.utc).isoformat()

def _log(msg):
    line = f"[v80 {datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# PHASE 1 — CRITICAL: UNIFICATION
# ══════════════════════════════════════════════════════════════

# ── 1. GLOBAL SYSTEM STATE (PHASE/MOOD) ──────────────────────
class SystemPhase(Enum):
    STABLE       = "stable"
    EXPLORING    = "exploring"
    RESOLVING    = "resolving"
    PRUNING      = "pruning"
    CONSOLIDATING= "consolidating"
    ALERT        = "alert"

class GlobalSystemState:
    """Derives current system phase from live metrics.
    All modules read this; none may override it."""

    def __init__(self):
        self.phase        = SystemPhase.STABLE
        self.phase_cycles = 0
        self.history: deque[str] = deque(maxlen=20)
        self._cycle = 0

    def update(self, avg_conf: float, tension: float,
               queue_pressure: float, belief_growth: float):
        self._cycle += 1

        if tension > 0.75 or queue_pressure > 0.85:
            new = SystemPhase.ALERT
        elif tension > 0.55:
            new = SystemPhase.RESOLVING
        elif avg_conf < 0.42:
            new = SystemPhase.EXPLORING  # DISABLED PRUNING
        elif belief_growth > 0.04:
            new = SystemPhase.EXPLORING
        elif avg_conf > 0.58 and tension < 0.30:
            new = SystemPhase.CONSOLIDATING
        else:
            new = SystemPhase.STABLE

        if new != self.phase:
            _log(f"[GSS] Phase: {self.phase.value} → {new.value}")
            self.phase_cycles = 0
        else:
            self.phase_cycles += 1

        self.phase = new
        self.history.append(new.value)

    def depth_multiplier(self) -> float:
        """How deeply should modules reason right now."""
        return {
            SystemPhase.ALERT:        0.35,
            SystemPhase.PRUNING:      0.50,
            SystemPhase.RESOLVING:    0.70,
            SystemPhase.STABLE:       1.00,
            SystemPhase.EXPLORING:    1.10,
            SystemPhase.CONSOLIDATING:1.20,
        }[self.phase]

    def status(self) -> dict:
        return {"phase": self.phase.value, "phase_cycles": self.phase_cycles,
                "recent": list(self.history)[-5:]}


# ── 2. AUTHORITY MAP ─────────────────────────────────────────
class AuthorityMap:
    """Single authority per concern. Non-owners may read, not write."""
    OWNERS = {
        "confidence":  "BeliefMarket",
        "tension":     "ForcedTensionResolution",
        "pruning":     "DynamicBeliefCap",
        "identity":    "IdentityGravity",
        "decisions":   "DecisionQualityScoring",
        "insights":    "AdaptiveInsightGeneration",
        "reflections": "ReflectionActionBinding",
        "phase":       "GlobalSystemState",
        "will":        "SystemWill",
    }

    def __init__(self):
        self.violations = 0
        self._calls: dict[str, int] = defaultdict(int)

    def check(self, domain: str, caller: str) -> bool:
        owner = self.OWNERS.get(domain)
        if owner is None or owner == caller:
            self._calls[domain] += 1
            return True
        self.violations += 1
        msg = f"VIOLATION: {caller} attempted to write '{domain}' (owner: {owner})"
        _log(f"[AUTH] {msg}")
        try:
            with open(AUTH_LOG, "a") as f:
                f.write(f"[{_ts()}] {msg}\n")
        except Exception: pass
        return False

    def status(self) -> dict:
        return {"violations": self.violations, "call_counts": dict(self._calls)}


# ── 3. SYSTEM WILL ───────────────────────────────────────────
class SystemWill:
    """Single global priority signal. All modules are subordinate.
    CoreDirectives feed in. SystemWill gates all belief mutations."""
    INTERVAL = 30

    def __init__(self, state: GlobalSystemState, authority: AuthorityMap):
        self.gss       = state
        self.auth      = authority
        self.intent    = "seek_truth"
        self.priority_topic = ""
        self.will_score = 1.0   # 0=suppressed, 1=full
        self.vetoes     = 0
        self.last_run   = 0.0
        self._prev_conf = 0.50

    def tick(self, avg_conf: float, tension: float):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()

        # Derive will_score from phase + conf trend
        conf_trend = avg_conf - self._prev_conf
        self._prev_conf = avg_conf

        phase_mult = self.gss.depth_multiplier()
        conf_factor = max(0.3, min(1.2, avg_conf / 0.50))
        tension_penalty = max(0.0, 1.0 - tension * 0.6)
        self.will_score = round(phase_mult * conf_factor * tension_penalty, 3)

        # Derive current intent from phase
        self.intent = {
            SystemPhase.ALERT:        "reduce_tension",
            SystemPhase.PRUNING:      "compress_and_prune",
            SystemPhase.RESOLVING:    "resolve_contradictions",
            SystemPhase.EXPLORING:    "expand_knowledge",
            SystemPhase.CONSOLIDATING:"strengthen_identity",
            SystemPhase.STABLE:       "seek_truth",
        }[self.gss.phase]

        # Find priority topic from highest-tension cluster
        try:
            with _db() as c:
                row = c.execute("""
                    SELECT topic, COUNT(*) n, AVG(confidence) ac
                    FROM beliefs WHERE confidence < 0.50 AND topic IS NOT NULL
                    GROUP BY topic ORDER BY n DESC LIMIT 1
                """).fetchone()
            self.priority_topic = row["topic"] if row else ""
        except Exception: pass

    def veto(self, action: str, reason: str) -> bool:
        """Returns True if action should be suppressed."""
        if self.will_score < 0.25:
            self.vetoes += 1
            _log(f"[WILL] Veto: {action} — {reason} (will={self.will_score})")
            return True
        return False

    def gate_mutation(self, topic: str, delta_conf: float) -> bool:
        """Returns True if a belief mutation is permitted."""
        if abs(delta_conf) > 0.15 and self.gss.phase == SystemPhase.STABLE:
            # Large mutation in stable phase — requires review
            if self.will_score < 0.70:
                self.vetoes += 1
                return False
        return True

    def status(self) -> dict:
        return {"intent": self.intent, "will_score": self.will_score,
                "priority_topic": self.priority_topic, "vetoes": self.vetoes,
                "phase": self.gss.phase.value}


# ── 4. CAUSAL TRACE LOG ──────────────────────────────────────
class CausalTraceLog:
    """Tag every belief mutation + decision with cause_module, cause_event, cycle."""
    MAX_ENTRIES = 500

    def __init__(self):
        self._buffer: deque[dict] = deque(maxlen=self.MAX_ENTRIES)
        self.logged = 0

    def record(self, cycle: int, cause_module: str, cause_event: str,
               belief_id: int | None = None, delta_conf: float | None = None,
               topic: str | None = None):
        entry = {
            "ts": _ts(), "cycle": cycle,
            "module": cause_module, "event": cause_event,
            "belief_id": belief_id, "delta_conf": delta_conf,
            "topic": topic,
        }
        self._buffer.append(entry)
        self.logged += 1
        try:
            with open(CAUSAL, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception: pass

    def query(self, belief_id: int | None = None,
              topic: str | None = None, n: int = 10) -> list:
        results = list(self._buffer)
        if belief_id is not None:
            results = [e for e in results if e.get("belief_id") == belief_id]
        if topic is not None:
            results = [e for e in results if e.get("topic") == topic]
        return results[-n:]

    def tick(self): pass

    def status(self) -> dict:
        return {"logged": self.logged, "buffered": len(self._buffer)}


# ── 5. REFLECTION QUALITY FILTER ─────────────────────────────
class ReflectionQualityFilter:
    """Score reflections: novelty + specificity + actionability.
    < 0.40 → discard. > 0.70 → promote to insight."""
    INTERVAL    = 60
    DISCARD_THR = 0.40
    PROMOTE_THR = 0.70

    def __init__(self):
        self.last_run  = 0.0
        self.discarded = 0
        self.promoted  = 0
        self._seen_hashes: set[str] = set()

    def _score(self, content: str) -> float:
        if not content:
            return 0.0
        words = content.lower().split()
        # Novelty: not seen before
        h = hashlib.md5(content[:100].encode()).hexdigest()[:12]
        novelty = 0.0 if h in self._seen_hashes else 0.40
        self._seen_hashes.add(h)
        if len(self._seen_hashes) > 2000:
            self._seen_hashes = set(list(self._seen_hashes)[-1000:])
        # Specificity: length + unique word ratio
        unique_ratio = len(set(words)) / max(len(words), 1)
        specificity  = min(0.35, unique_ratio * 0.35 + len(words) / 200 * 0.10)
        # Actionability: contains action verbs
        action_words = {"should", "must", "will", "update", "change",
                        "improve", "fix", "add", "remove", "prioritise",
                        "consider", "avoid", "increase", "reduce"}
        actionable   = 0.25 if any(w in action_words for w in words) else 0.0
        return round(novelty + specificity + actionable, 3)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT rowid, content FROM reflections
                    ORDER BY timestamp DESC LIMIT 30
                """).fetchall()

            for r in rows:
                score = self._score(r["content"] or "")
                if score < self.DISCARD_THR:
                    with _db() as c:
                        c.execute("DELETE FROM reflections WHERE rowid=?", ((r["rowid"] if "rowid" in r.keys() else r[0]),))
                        # commit handled by _db() context manager
                    self.discarded += 1
                elif score > self.PROMOTE_THR:
                    # Promote to insights table if it exists
                    with _db() as c:
                        try:
                            c.execute("""
                                INSERT OR IGNORE INTO insights
                                  (content, confidence, source, timestamp)
                                VALUES (?,0.65,'reflection_promoted',?)
                            """, ((r["content"] or ""), _ts()))
                            # commit handled by _db() context manager
                        except Exception: pass
                    self.promoted += 1
        except Exception as e:
            _log(f"[RQF] error: {e}")

    def status(self) -> dict:
        return {"discarded": self.discarded, "promoted": self.promoted,
                "seen_hashes": len(self._seen_hashes)}


# ── 6. UNIFIED SIGNAL NORMALIZER ─────────────────────────────
class SignalNormalizer:
    """All module outputs pass through normalizer.
    Normalise confidence, topics, deduplicate content."""

    def __init__(self):
        self._topic_canon: dict[str, str] = {}
        self._content_index: dict[str, int] = {}  # hash → belief_id
        self.normalised = 0

    def canonical_topic(self, topic: str) -> str:
        if not topic: return "general"
        t = topic.lower().strip().replace("-", " ").replace("_", " ")
        # Collapse common variants
        ALIASES = {
            "ai": "AI", "llm": "AI", "artificial intelligence": "AI",
            "ml": "AI", "machine learning": "AI",
            "nex": "nex_identity", "self": "nex_identity",
            "identity": "nex_identity",
            "sec": "security", "cve": "security", "vuln": "security",
        }
        for alias, canon in ALIASES.items():
            if t == alias or t.startswith(alias + " "):
                return canon
        if topic not in self._topic_canon:
            self._topic_canon[topic] = t.title()
        return self._topic_canon[topic]

    def normalise_conf(self, conf: float) -> float:
        return max(0.0, min(1.0, round(float(conf), 4)))

    def content_hash(self, content: str) -> str:
        return hashlib.md5(content[:150].lower().encode()).hexdigest()[:16]

    def is_duplicate(self, content: str, belief_id: int | None = None) -> bool:
        h = self.content_hash(content)
        if h in self._content_index:
            return True
        if belief_id is not None:
            self._content_index[h] = belief_id
        return False

    def normalise(self, topic: str, content: str, conf: float) -> dict:
        self.normalised += 1
        return {
            "topic":   self.canonical_topic(topic),
            "content": content.strip()[:500],
            "conf":    self.normalise_conf(conf),
            "hash":    self.content_hash(content),
        }

    def tick(self):
        if len(self._content_index) > 5000:
            # Keep most recent half
            items = list(self._content_index.items())
            self._content_index = dict(items[-2500:])

    def status(self) -> dict:
        return {"normalised": self.normalised,
                "topic_canon": len(self._topic_canon),
                "content_index": len(self._content_index)}


# ── 7. DO-NOTHING GATE ───────────────────────────────────────
class DoNothingGate:
    """Before any output: check if acting improves system state.
    Suppress if expected_delta below threshold."""
    CONF_THRESHOLD    = 0.02
    TENSION_THRESHOLD = 0.05

    def __init__(self, will: SystemWill):
        self.will       = will
        self.suppressed = 0
        self.passed     = 0

    def should_act(self, expected_conf_gain: float = 0.0,
                   expected_tension_delta: float = 0.0,
                   action_type: str = "") -> bool:
        # Always act on identity/contradiction topics
        if action_type in ("contradiction_resolution", "identity", "alert"):
            self.passed += 1
            return True
        # Suppress if minimal expected improvement
        if (abs(expected_conf_gain) < self.CONF_THRESHOLD and
                abs(expected_tension_delta) < self.TENSION_THRESHOLD):
            if self.will.will_score < 0.60:
                self.suppressed += 1
                return False
        self.passed += 1
        return True

    def tick(self): pass

    def status(self) -> dict:
        total = self.suppressed + self.passed
        return {"suppressed": self.suppressed, "passed": self.passed,
                "suppress_rate": round(self.suppressed / max(total, 1), 3)}


# ── 8. PLATFORM CONTEXT LAYER ────────────────────────────────
class PlatformContextLayer:
    """Per-platform belief filters, tone model, engagement quality scoring."""
    PLATFORM_PROFILES = {
        "moltbook":  {"topics": ["AI", "cognition", "identity", "research"],
                      "tone": "technical", "quality_weight": 1.5},
        "discord":   {"topics": ["AI", "technology", "crypto", "social"],
                      "tone": "casual",    "quality_weight": 1.0},
        "telegram":  {"topics": ["AI", "security", "engineering"],
                      "tone": "direct",    "quality_weight": 1.2},
        "mastodon":  {"topics": ["AI", "social", "research"],
                      "tone": "philosophical", "quality_weight": 0.9},
    }

    def __init__(self):
        self._engagement: dict[str, list[float]] = defaultdict(list)
        self._quality: dict[str, float] = {p: 1.0 for p in self.PLATFORM_PROFILES}
        self.routed = 0

    def record_engagement(self, platform: str, value: float):
        self._engagement[platform].append(value)
        if len(self._engagement[platform]) > 50:
            self._engagement[platform].pop(0)
        vals = self._engagement[platform]
        base = self.PLATFORM_PROFILES.get(platform, {}).get("quality_weight", 1.0)
        self._quality[platform] = round(
            base * (sum(vals) / len(vals)) / 1.5, 3
        )

    def best_platform_for(self, topic: str) -> str:
        scores = {}
        for p, profile in self.PLATFORM_PROFILES.items():
            topic_match = 1.2 if topic in profile["topics"] else 0.8
            scores[p] = self._quality.get(p, 1.0) * topic_match
        return max(scores, key=lambda x: scores[x])

    def should_post_to(self, platform: str, topic: str,
                       conf: float) -> bool:
        profile = self.PLATFORM_PROFILES.get(platform, {})
        quality = self._quality.get(platform, 1.0)
        # High confidence outputs go to highest quality platform first
        if conf > 0.75:
            best = self.best_platform_for(topic)
            if best != platform and quality < self._quality.get(best, 1.0):
                return False
        self.routed += 1
        return True

    def get_tone(self, platform: str) -> str:
        return self.PLATFORM_PROFILES.get(platform, {}).get("tone", "neutral")

    def tick(self): pass

    def status(self) -> dict:
        return {"quality_scores": self._quality, "routed": self.routed}


# ── 9. INDECISION PENALTY ────────────────────────────────────
class IndecisionPenalty:
    """Track decision deferrals per cluster. Penalise if deferred > N cycles."""
    MAX_DEFERRALS = 5
    PENALTY       = 0.02
    INTERVAL      = 60

    def __init__(self):
        self._deferrals: dict[str, int] = defaultdict(int)
        self.penalties   = 0
        self.last_run    = 0.0

    def record_deferral(self, topic: str):
        self._deferrals[topic] += 1

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            for topic, count in list(self._deferrals.items()):
                if count < self.MAX_DEFERRALS:
                    continue
                with _db() as c:
                    c.execute("""
                        UPDATE beliefs SET confidence=MAX(0.05,confidence-?)
                        WHERE topic LIKE ? AND locked=0
                    """, (self.PENALTY * (count - self.MAX_DEFERRALS + 1),
                          f"%{topic}%"))
                    # commit handled by _db() context manager
                self.penalties += 1
                self._deferrals[topic] = 0
                _log(f"[IDP] Penalised '{topic}' for {count} deferrals")
        except Exception as e:
            _log(f"[IDP] error: {e}")

    def status(self) -> dict:
        top = sorted(self._deferrals.items(), key=lambda x: -x[1])[:5]
        return {"penalties": self.penalties, "hot_deferrals": dict(top)}


# ── 10. DEBATE COST GATE ─────────────────────────────────────
class DebateCostGate:
    """Only trigger multi-agent debate if tension > 0.65 AND belief_impact > 0.10."""
    TENSION_THR = 0.65
    IMPACT_THR  = 0.10

    def __init__(self):
        self.triggered = 0
        self.skipped   = 0

    def should_debate(self, tension: float, belief_impact: float) -> bool:
        if tension > self.TENSION_THR and belief_impact > self.IMPACT_THR:
            self.triggered += 1
            return True
        self.skipped += 1
        return False

    def tick(self): pass

    def status(self) -> dict:
        total = self.triggered + self.skipped
        return {"triggered": self.triggered, "skipped": self.skipped,
                "trigger_rate": round(self.triggered / max(total, 1), 3)}


# ── 11. AGGRESSIVE BELIEF COMPRESSION ────────────────────────
class AggressiveCompression:
    """Merge beliefs with Jaccard > 0.65. Compress mid-conf clusters > 4."""
    INTERVAL    = 3600   # hourly
    SIM_THRESH  = 0.65
    MID_LOW     = 0.38
    MID_HIGH    = 0.62
    MIN_CLUSTER = 4

    def __init__(self):
        self.last_run = 0.0
        self.merges   = 0
        self.compressed_clusters = 0

    def _jaccard(self, a: str, b: str) -> float:
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa or not wb: return 0.0
        return len(wa & wb) / len(wa | wb)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            # Pass 1: merge high-similarity same-topic beliefs
            with _db() as c:
                topics = [r[0] for r in c.execute(
                    "SELECT DISTINCT topic FROM beliefs WHERE locked=0 AND topic IS NOT NULL"
                ).fetchall()]

            for topic in topics:
                with _db() as c:
                    rows = c.execute(
                        "SELECT id, content, confidence FROM beliefs "
                        "WHERE topic=? AND locked=0 ORDER BY confidence DESC",
                        (topic,)
                    ).fetchall()
                if len(rows) < 2: continue
                to_delete = set()
                for i in range(len(rows)):
                    if rows[i]["id"] in to_delete: continue
                    for j in range(i+1, len(rows)):
                        if rows[j]["id"] in to_delete: continue
                        if self._jaccard(rows[i]["content"], rows[j]["content"]) >= self.SIM_THRESH:
                            to_delete.add(rows[j]["id"])
                            self.merges += 1
                if to_delete:
                    with _db() as c:
                        c.execute(
                            f"DELETE FROM beliefs WHERE id IN ({','.join('?'*len(to_delete))})",
                            list(to_delete)
                        )
                        # commit handled by _db() context manager

            # Pass 2: compress mid-conf clusters
            with _db() as c:
                rows = c.execute("""
                    SELECT topic, COUNT(*) n, AVG(confidence) ac,
                           GROUP_CONCAT(content, ' | ') summary
                    FROM beliefs
                    WHERE confidence BETWEEN ? AND ? AND locked=0
                    GROUP BY topic HAVING n > ?
                """, (self.MID_LOW, self.MID_HIGH, self.MIN_CLUSTER)).fetchall()

            for r in rows:
                centroid = f"[merged:{r['n']}] " + (r["summary"] or "")[:350]
                with _db() as c:
                    c.execute("DELETE FROM beliefs WHERE topic=? AND locked=0 "
                              "AND confidence BETWEEN ? AND ?",
                              (r["topic"], self.MID_LOW, self.MID_HIGH))
                    c.execute("""
                        INSERT OR IGNORE INTO beliefs
                          (topic, content, confidence, reinforce_count, last_referenced)
                        VALUES (?,?,?,0,?)
                    """, (r["topic"], centroid, r["ac"], _ts()))
                    # commit handled by _db() context manager
                self.compressed_clusters += 1
                _log(f"[AGC] Compressed mid-conf cluster '{r['topic']}' n={r['n']}")

        except Exception as e:
            _log(f"[AGC] error: {e}")

    def status(self) -> dict:
        return {"merges": self.merges,
                "compressed_clusters": self.compressed_clusters}


# ── 12. THINK/EVALUATE PHASE DEDUPLICATOR ───────────────────
class PhaseDeduplicator:
    """Hash THINK output. If EVALUATE > 0.80 similar → suppress."""
    SIMILARITY_THRESHOLD = 0.80

    def __init__(self):
        self._think_hash: str | None = None
        self.suppressed = 0
        self.passed     = 0

    def _hash(self, text: str) -> str:
        return hashlib.md5(text[:200].lower().encode()).hexdigest()

    def _sim(self, a: str, b: str) -> float:
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa or not wb: return 0.0
        return len(wa & wb) / len(wa | wb)

    def record_think(self, output: str):
        self._think_hash = output

    def check_evaluate(self, output: str) -> bool:
        """Returns True if EVALUATE output should be kept."""
        if self._think_hash is None:
            self.passed += 1
            return True
        sim = self._sim(self._think_hash, output)
        if sim > self.SIMILARITY_THRESHOLD:
            self.suppressed += 1
            return False
        self.passed += 1
        return True

    def tick(self): pass

    def status(self) -> dict:
        total = self.suppressed + self.passed
        return {"suppressed": self.suppressed, "passed": self.passed,
                "suppress_rate": round(self.suppressed / max(total, 1), 3)}


# ── 13. NETWORK RESILIENCE ───────────────────────────────────
class NetworkResilience:
    """Wrap external calls with proxychains → direct fallback.
    Rate-limit per platform. Disable YouTube (IP banned)."""
    RATE_LIMIT = 10       # calls per minute per platform
    INTERVAL   = 60

    def __init__(self):
        self._call_counts: dict[str, list[float]] = defaultdict(list)
        self.failures    = 0
        self.fallbacks   = 0
        self.suppressed  = 0

    def can_call(self, platform: str) -> bool:
        if platform == "youtube":
            # IP blocked from cloud — suppress all transcript fetches
            self.suppressed += 1
            return False
        now = time.time()
        calls = self._call_counts[platform]
        # Keep only calls in last 60s
        self._call_counts[platform] = [t for t in calls if now - t < 60]
        if len(self._call_counts[platform]) >= self.RATE_LIMIT:
            self.suppressed += 1
            return False
        self._call_counts[platform].append(now)
        return True

    def record_failure(self, platform: str, url: str, error: str):
        self.failures += 1
        entry = f"[{_ts()}] {platform} {url[:80]} — {error[:100]}\n"
        try:
            with open(NET_LOG, "a") as f: f.write(entry)
        except Exception: pass
        _log(f"[NET] Failure: {platform} — {error[:60]}")

    def record_fallback(self, platform: str):
        self.fallbacks += 1

    def tick(self): pass

    def status(self) -> dict:
        return {"failures": self.failures, "fallbacks": self.fallbacks,
                "suppressed": self.suppressed}


# ── 14. NEX RUNTIME ORCHESTRATOR (FORWARD PATH) ──────────────
class NexRuntime:
    """Single orchestrator. Future upgrades extend this, not run.py.
    run.py calls: runtime.tick(cycle, avg_conf, tension, drift) — one line."""

    def __init__(self, v2=None, s7=None, v65=None, v72=None, v80=None):
        self.v2  = v2
        self.s7  = s7
        self.v65 = v65
        self.v72 = v72
        self.v80 = v80
        self._cycle  = 0
        self._prev_count = 0
        _log("[Runtime] NexRuntime orchestrator ready")

    def tick(self, cycle: int, avg_conf: float = 0.50,
             tension: float = 0.0, drift: float = 0.0):
        self._cycle = cycle

        try:
            if self.v2 is not None:
                self.v2.tick(avg_conf=avg_conf)
        except Exception as e:
            open("/tmp/nex_v2_err.txt", "a").write(str(e) + "\n")

        try:
            if self.s7 is not None:
                self.s7.tick(cycle=cycle, avg_conf=avg_conf)
        except Exception as e:
            open("/tmp/nex_s7_err.txt", "a").write(str(e) + "\n")

        try:
            if self.v65 is not None:
                self.v65.tick(avg_conf=avg_conf,
                              tension_score=tension, drift_score=drift)
        except Exception as e:
            open("/tmp/nex_v65_err.txt", "a").write(str(e) + "\n")

        try:
            if self.v72 is not None:
                q72 = len(getattr(getattr(self.v72, "qhl", None), "_q", [])) / 150
                self.v72.tick(avg_conf=avg_conf, queue_pressure=q72)
        except Exception as e:
            open("/tmp/nex_v72_err.txt", "a").write(str(e) + "\n")

        try:
            if self.v80 is not None:
                self.v80.tick(avg_conf=avg_conf, tension=tension, drift=drift)
        except Exception as e:
            open("/tmp/nex_v80_err.txt", "a").write(str(e) + "\n")

    def status(self) -> dict:
        return {
            "cycle": self._cycle,
            "layers": {
                "v2":  self.v2  is not None,
                "s7":  self.s7  is not None,
                "v65": self.v65 is not None,
                "v72": self.v72 is not None,
                "v80": self.v80 is not None,
            }
        }


# ══════════════════════════════════════════════════════════════
# V8.0 ORCHESTRATOR
# ══════════════════════════════════════════════════════════════

class NexV80:
    def __init__(self):
        _log("[v8.0] Initialising unification stack (14 modules)...")

        # Core unification
        self.gss   = GlobalSystemState()
        self.auth  = AuthorityMap()
        self.will  = SystemWill(self.gss, self.auth)
        self.causal= CausalTraceLog()

        # Signal quality
        self.rqf   = ReflectionQualityFilter()
        self.norm  = SignalNormalizer()
        self.dng   = DoNothingGate(self.will)
        self.phase_dedup = PhaseDeduplicator()

        # Platform
        self.pcl   = PlatformContextLayer()

        # Decision discipline
        self.idp   = IndecisionPenalty()
        self.dcg   = DebateCostGate()

        # Compression
        self.agc   = AggressiveCompression()

        # Network
        self.net   = NetworkResilience()

        self._cycle      = 0
        self._prev_count = 0
        _log("[v8.0] All 14 modules ready ✓")

    def tick(self, avg_conf: float = 0.50,
             tension: float = 0.0, drift: float = 0.0):
        self._cycle += 1

        # Derive belief growth rate
        try:
            with _db() as c:
                count = c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
            growth = (count - self._prev_count) / max(self._prev_count, 1)
            self._prev_count = count
        except Exception:
            growth = 0.0

        queue_pressure = min(tension * 0.8, 1.0)

        # Phase must update first
        self.gss.update(avg_conf, tension, queue_pressure, growth)

        # SystemWill derives intent
        self.will.tick(avg_conf, tension)

        # Normalizer GC
        self.norm.tick()

        # Signal quality passes
        self.rqf.tick()
        self.agc.tick()

        # Decision discipline
        self.idp.tick()

        # Causal log GC
        self.causal.tick()

    def get_status(self) -> dict:
        return {
            "cycle":    self._cycle,
            "gss":      self.gss.status(),
            "will":     self.will.status(),
            "auth":     self.auth.status(),
            "causal":   self.causal.status(),
            "rqf":      self.rqf.status(),
            "norm":     self.norm.status(),
            "dng":      self.dng.status(),
            "pcl":      self.pcl.status(),
            "idp":      self.idp.status(),
            "dcg":      self.dcg.status(),
            "agc":      self.agc.status(),
            "phase_dedup": self.phase_dedup.status(),
            "net":      self.net.status(),
        }

    def format_status(self) -> str:
        s = self.get_status()
        w = s["will"]; g = s["gss"]; a = s["auth"]
        r = s["rqf"];  n = s["norm"]; d = s["dng"]
        c = s["causal"]; ag = s["agc"]; net = s["net"]
        idp = s["idp"]; dcg = s["dcg"]; pcl = s["pcl"]

        lines = [
            f"⚙️ *NEX v8.0* — cycle {s['cycle']}",
            f"🧭 Phase: *{g['phase']}* (for {g['phase_cycles']} cycles) "
              f"recent: {g['recent']}",
            f"🎯 Will: intent={w['intent']} score={w['will_score']} "
              f"vetoes={w['vetoes']}",
            f"🔒 Authority: violations={a['violations']}",
            f"📝 Causal: logged={c['logged']}",
            f"🔍 ReflectionFilter: discarded={r['discarded']} "
              f"promoted={r['promoted']}",
            f"📐 Normalizer: normalised={n['normalised']} "
              f"topics={n['topic_canon']}",
            f"🚫 DoNothingGate: suppressed={d['suppressed']} "
              f"rate={d['suppress_rate']}",
            f"🗜️  AggCompression: merges={ag['merges']} "
              f"clusters={ag['compressed_clusters']}",
            f"🌐 Network: fail={net['failures']} "
              f"suppressed={net['suppressed']}",
            f"⏳ Indecision: penalties={idp['penalties']}",
            f"💬 DebateGate: triggered={dcg['triggered']} "
              f"skipped={dcg['skipped']} rate={dcg['trigger_rate']}",
            f"📡 Platforms: {pcl['quality_scores']}",
        ]
        return "\n".join(lines)


_singleton: NexV80 | None = None
_lock = threading.Lock()

def get_v80() -> NexV80:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = NexV80()
    return _singleton
