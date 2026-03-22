"""
NEX v6.5 — Calculated Upgrade Layer
18-module cognitive enhancement stack
Deploy: ~/Desktop/nex/nex_upgrades/nex_v65.py
Wire:   see deploy_v65.sh
"""

import sqlite3, json, time, math, random, threading, hashlib, subprocess
from collections import defaultdict, deque
from pathlib import Path
from datetime import datetime


def _ts() -> str:
    """Return current time as ISO string for last_referenced column."""
    from datetime import datetime
    return datetime.utcnow().isoformat()


DB_PATH   = Path.home() / ".config/nex/nex.db"
V65_LOG   = Path("/tmp/nex_v65.log")

def _db():
    c = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _log(msg: str):
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[v65 {ts}] {msg}"
    print(line)
    try:
        with open(V65_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# 1. DECISION ENGINE
#    Converts tension loops → actual resolutions (dominant/merge/prune)
# ══════════════════════════════════════════════════════════════

class DecisionEngine:
    TENSION_THRESHOLD = 0.65

    def __init__(self):
        self.decisions_made = 0
        self.last_decision: dict | None = None

    def tick(self, tension_score: float):
        if tension_score < self.TENSION_THRESHOLD:
            return None
        decision = self._resolve()
        if decision:
            self.decisions_made += 1
            self.last_decision  = decision
            _log(f"[DecisionEngine] {decision['action']} topic={decision.get('topic','?')} "
                 f"tension={tension_score:.2f}")
        return decision

    def _resolve(self) -> dict | None:
        try:
            with _db() as conn:
                beliefs = conn.execute("""
                    SELECT id, topic, content, confidence, reinforce_count, last_referenced
                    FROM beliefs
                    WHERE confidence < 0.55
                    ORDER BY confidence ASC, last_referenced ASC
                    LIMIT 30
                """).fetchall()

            if not beliefs:
                return None

            # Group by topic root
            groups: dict[str, list] = defaultdict(list)
            for b in beliefs:
                groups[b["topic"]].append(dict(b))

            for topic, group in groups.items():
                if len(group) < 2:
                    continue
                group.sort(key=lambda x: x["confidence"])
                weakest  = group[0]
                dominant = group[-1]
                delta    = dominant["confidence"] - weakest["confidence"]

                with _db() as conn:
                    if delta > 0.30:
                        # Dominant: boost winner, prune loser
                        conn.execute("""
                            UPDATE beliefs
                            SET confidence = MIN(confidence + 0.05, 1.0), last_referenced = ?
                            WHERE id = ?
                        """, (time.time(), dominant["id"]))
                        conn.execute("DELETE FROM beliefs WHERE id = ?", (weakest["id"],))
                        # commit handled by _db() context manager
                        return {"action": "dominant", "topic": topic,
                                "belief_id": dominant["id"], "pruned_id": weakest["id"]}
                    else:
                        # Merge: average conf, combine content
                        merged_conf    = (weakest["confidence"] + dominant["confidence"]) / 2
                        merged_content = (f"{dominant['content']} "
                                          f"[+{weakest['content'][:60]}]")[:500]
                        conn.execute("""
                            UPDATE beliefs
                            SET confidence = ?, content = ?, last_referenced = ?
                            WHERE id = ?
                        """, (merged_conf, merged_content, time.time(), dominant["id"]))
                        conn.execute("DELETE FROM beliefs WHERE id = ?", (weakest["id"],))
                        # commit handled by _db() context manager
                        return {"action": "merge", "topic": topic,
                                "belief_id": dominant["id"], "new_conf": round(merged_conf, 3)}

            # Fallback: prune absolute weakest
            target = min(beliefs, key=lambda x: x["confidence"])
            with _db() as conn:
                conn.execute("DELETE FROM beliefs WHERE id = ?", (target["id"],))
                # commit handled by _db() context manager
            return {"action": "prune", "topic": target["topic"],
                    "belief_id": target["id"], "conf": round(target["confidence"], 3)}

        except Exception as e:
            _log(f"[DecisionEngine] error: {e}")
            return None

    def status(self) -> dict:
        return {"decisions_made": self.decisions_made, "last": self.last_decision}


# ══════════════════════════════════════════════════════════════
# 2. HARD PRUNING SYSTEM
#    Hard caps on belief count. No negotiation.
# ══════════════════════════════════════════════════════════════

class HardPruningSystem:
    MAX_BELIEFS = 1000

    def __init__(self):
        self.prune_count = 0

    def tick(self) -> int:
        try:
            with _db() as conn:
                count = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                if count <= self.MAX_BELIEFS:
                    return 0
                excess = count - self.MAX_BELIEFS
                # Protect identity; prune lowest combined score
                conn.execute("""
                    DELETE FROM beliefs WHERE id IN (
                        SELECT id FROM beliefs
                        WHERE topic NOT LIKE '%identity%'
                          AND topic NOT LIKE '%truth%'
                          AND topic NOT LIKE '%contradiction%'
                        ORDER BY (confidence * 0.5 + reinforce_count * 0.01) ASC,
                                 last_referenced ASC
                        LIMIT ?
                    )
                """, (excess,))
                # commit handled by _db() context manager
                self.prune_count += excess
                _log(f"[HardPrune] Pruned {excess} (was {count} → {self.MAX_BELIEFS})")
                return excess
        except Exception as e:
            _log(f"[HardPrune] error: {e}")
            return 0

    def status(self) -> dict:
        try:
            with _db() as conn:
                count = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        except Exception:
            count = -1
        return {"belief_count": count, "max": self.MAX_BELIEFS,
                "total_pruned": self.prune_count,
                "pressure": round(count / self.MAX_BELIEFS, 2) if count > 0 else 0}


# ══════════════════════════════════════════════════════════════
# 3. TENSION → ACTION LOCK
#    High tension overrides scheduler and forces resolution.
# ══════════════════════════════════════════════════════════════

class TensionActionLock:
    THRESHOLD = 0.70
    COOLDOWN  = 30   # seconds

    def __init__(self, decision_engine: DecisionEngine):
        self.de          = decision_engine
        self.last_fired  = 0.0
        self.lock_count  = 0

    def tick(self, tension_score: float) -> bool:
        if tension_score < self.THRESHOLD:
            return False
        if time.time() - self.last_fired < self.COOLDOWN:
            return False
        _log(f"[TensionLock] FIRE — tension {tension_score:.3f}")
        self.last_fired = time.time()
        self.lock_count += 1
        self.de._resolve()
        return True

    def status(self) -> dict:
        return {"lock_count": self.lock_count, "threshold": self.THRESHOLD,
                "last_fired": round(self.last_fired, 1)}


# ══════════════════════════════════════════════════════════════
# 4. STRICT INSIGHT GATE
#    confidence ≥ 0.55 AND seen ≥ 2 AND cross-context validated
# ══════════════════════════════════════════════════════════════

class StrictInsightGate:
    MIN_CONFIDENCE = 0.55
    MIN_SEEN       = 2

    def __init__(self):
        self._seen: dict[str, int] = {}
        self.passed  = 0
        self.blocked = 0

    def _hash(self, content: str) -> str:
        return hashlib.md5(content[:120].lower().encode()).hexdigest()[:16]

    def check(self, content: str, confidence: float,
              context_tags: list | None = None) -> bool:
        h = self._hash(content)
        self._seen[h] = self._seen.get(h, 0) + 1
        seen = self._seen[h]

        cross_ok = True
        if context_tags is not None:
            cross_ok = len(context_tags) >= 1

        if confidence >= self.MIN_CONFIDENCE and seen >= self.MIN_SEEN and cross_ok:
            self.passed += 1
            return True
        self.blocked += 1
        return False

    def tick(self):
        # GC singleton-seen hashes to prevent unbounded growth
        if len(self._seen) > 2000:
            cutoff = sorted(self._seen.values())[int(len(self._seen) * 0.4)]
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}

    def status(self) -> dict:
        total = self.passed + self.blocked
        return {"passed": self.passed, "blocked": self.blocked,
                "pass_rate": round(self.passed / max(total, 1), 2),
                "tracked_hashes": len(self._seen)}


# ══════════════════════════════════════════════════════════════
# 5. BELIEF VALIDATION LAYER  (Wikipedia)
#    External grounding: support / contradict scored per belief
# ══════════════════════════════════════════════════════════════

class BeliefValidationLayer:
    INTERVAL      = 120   # seconds between passes
    SUPPORT_BOOST = 0.04
    CONTRA_PENALTY = 0.06

    def __init__(self):
        self.last_run    = 0.0
        self.validated   = 0
        self.supported   = 0
        self.contradicted = 0
        self._cache: dict[str, str] = {}

    def _wiki(self, term: str) -> str:
        try:
            url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
                   + term.strip().replace(" ", "_"))
            r = subprocess.run(
                ["proxychains", "-q", "curl", "-s", "--max-time", "8", url],
                capture_output=True, text=True, timeout=12
            )
            return json.loads(r.stdout).get("extract", "")
        except Exception:
            return ""

    def _score(self, belief: str, wiki: str) -> float:
        bw = set(belief.lower().split())
        ww = set(wiki.lower().split())
        return len(bw & ww) / max(len(bw), 1)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as conn:
                beliefs = conn.execute("""
                    SELECT id, topic, content, confidence FROM beliefs
                    WHERE confidence BETWEEN 0.28 AND 0.72
                    ORDER BY RANDOM() LIMIT 5
                """).fetchall()

            for b in beliefs:
                topic = b["topic"]
                wiki  = self._cache.get(topic) or self._wiki(topic)
                if wiki:
                    self._cache[topic] = wiki
                if not wiki:
                    continue

                score = self._score(b["content"], wiki)
                self.validated += 1
                if score > 0.15:
                    nc = min(b["confidence"] + self.SUPPORT_BOOST, 1.0)
                    self.supported += 1
                elif score < 0.03 and len(wiki) > 200:
                    nc = max(b["confidence"] - self.CONTRA_PENALTY, 0.05)
                    self.contradicted += 1
                else:
                    continue

                with _db() as conn:
                    conn.execute(
                        "UPDATE beliefs SET confidence=?, last_referenced=? WHERE id=?",
                        (nc, time.time(), b["id"])
                    )
                    # commit handled by _db() context manager
                _log(f"[WikiValidate] {topic} score={score:.2f} "
                     f"conf {b['confidence']:.2f}→{nc:.2f}")
        except Exception as e:
            _log(f"[WikiValidate] error: {e}")

    def status(self) -> dict:
        return {"validated": self.validated, "supported": self.supported,
                "contradicted": self.contradicted, "cache_size": len(self._cache)}


# ══════════════════════════════════════════════════════════════
# 6. BELIEF CLUSTERING ENGINE
#    Groups beliefs by topic root → cluster-level operations
# ══════════════════════════════════════════════════════════════

class BeliefClusteringEngine:
    REBUILD_INTERVAL = 300

    def __init__(self):
        self.clusters: dict[str, list[dict]] = {}
        self.belief_to_cluster: dict[int, str] = {}
        self.last_rebuild = 0.0
        self.cluster_count = 0

    def _key(self, topic: str) -> str:
        return (topic.lower().replace("-", " ")
                     .replace("_", " ").split()[0]) if topic.strip() else "misc"

    def rebuild(self):
        try:
            with _db() as conn:
                rows = conn.execute(
                    "SELECT id, topic, confidence FROM beliefs"
                ).fetchall()
            groups: dict[str, list[dict]] = defaultdict(list)
            b2c: dict[int, str] = {}
            for r in rows:
                k = self._key(r["topic"])
                groups[k].append({"id": r["id"], "conf": float(r["confidence"] or 0.5)})
                b2c[r["id"]] = k
            self.clusters         = dict(groups)
            self.belief_to_cluster = b2c
            self.cluster_count    = len(groups)
            self.last_rebuild     = time.time()
        except Exception as e:
            _log(f"[Clustering] rebuild error: {e}")

    def tick(self):
        if time.time() - self.last_rebuild > self.REBUILD_INTERVAL:
            self.rebuild()

    def top_clusters(self, n: int = 5) -> list:
        return sorted(
            [{"cluster": k, "size": len(v),
              "avg_conf": round(sum(b["conf"] for b in v) / len(v), 3)}
             for k, v in self.clusters.items()],
            key=lambda x: -x["size"]
        )[:n]

    def status(self) -> dict:
        return {"cluster_count": self.cluster_count,
                "top": self.top_clusters()}


# ══════════════════════════════════════════════════════════════
# 7. MEMORY CONSOLIDATION PASS
#    Merges near-duplicate beliefs, prevents fragmentation
# ══════════════════════════════════════════════════════════════

class MemoryConsolidationPass:
    INTERVAL    = 600
    SIM_THRESH  = 0.80

    def __init__(self):
        self.last_run = 0.0
        self.merges   = 0
        self.removed  = 0

    def _sim(self, a: str, b: str) -> float:
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / len(wa | wb)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as conn:
                beliefs = conn.execute("""
                    SELECT id, topic, content, confidence, reinforce_count
                    FROM beliefs ORDER BY topic, confidence DESC
                """).fetchall()

            seen: dict[str, dict] = {}
            to_delete: set[int]   = set()

            for b in beliefs:
                b = dict(b)
                key = b["topic"]
                if key not in seen:
                    seen[key] = b
                    continue
                existing = seen[key]
                if self._sim(b["content"], existing["content"]) >= self.SIM_THRESH:
                    merged_conf = max(b["confidence"], existing["confidence"])
                    merged_rc   = b["reinforce_count"] + existing["reinforce_count"]
                    with _db() as conn:
                        conn.execute("""
                            UPDATE beliefs
                            SET confidence=?, reinforce_count=?, last_referenced=?
                            WHERE id=?
                        """, (merged_conf, merged_rc, time.time(), existing["id"]))
                    to_delete.add(b["id"])
                    self.merges += 1

            if to_delete:
                with _db() as conn:
                    conn.execute(
                        "DELETE FROM beliefs WHERE id IN ({})".format(
                            ",".join("?" * len(to_delete))
                        ),
                        list(to_delete)
                    )
                    # commit handled by _db() context manager
                self.removed += len(to_delete)
                _log(f"[Consolidation] Merged {len(to_delete)} duplicates")
        except Exception as e:
            _log(f"[Consolidation] error: {e}")

    def status(self) -> dict:
        return {"merges": self.merges, "removed": self.removed}


# ══════════════════════════════════════════════════════════════
# 8. TEMPORAL PATTERN ANALYSIS
#    Detects oscillations, flip-flops, confidence trends
# ══════════════════════════════════════════════════════════════

class TemporalPatternAnalysis:
    WINDOW = 50

    def __init__(self):
        self.conf_history:  deque[float] = deque(maxlen=self.WINDOW)
        self.topic_history: deque[str]   = deque(maxlen=self.WINDOW)
        self.oscillations  = 0
        self.trends: list[dict] = []
        self._cycle = 0

    def record(self, avg_conf: float, top_topic: str = ""):
        self.conf_history.append(avg_conf)
        self.topic_history.append(top_topic)
        self._cycle += 1
        if self._cycle % 10 == 0:
            self._analyze()

    def _analyze(self):
        hist = list(self.conf_history)
        if len(hist) < 10:
            return

        # Oscillation: count sign changes in first-difference
        changes = sum(
            1 for i in range(1, len(hist) - 1)
            if (hist[i] - hist[i-1]) * (hist[i+1] - hist[i]) < 0
        )
        osc_rate = changes / max(len(hist) - 2, 1)
        if osc_rate > 0.4:
            self.oscillations += 1
            _log(f"[TemporalPattern] Oscillation detected rate={osc_rate:.2f}")

        # Trend
        recent = hist[-10:]
        old    = hist[:10] if len(hist) >= 20 else hist[:5]
        delta  = (sum(recent) / len(recent)) - (sum(old) / len(old))
        direction = "rising" if delta > 0.01 else "falling" if delta < -0.01 else "stable"
        entry = {"cycle": self._cycle, "direction": direction, "delta": round(delta, 4)}
        self.trends.append(entry)
        if len(self.trends) > 30:
            self.trends.pop(0)

    def status(self) -> dict:
        return {
            "oscillations": self.oscillations,
            "latest_trend": self.trends[-1] if self.trends else {},
            "conf_mean": round(
                sum(self.conf_history) / max(len(self.conf_history), 1), 3
            ),
        }


# ══════════════════════════════════════════════════════════════
# 9. DRIFT CORRECTION HARD TRIGGER
#    Identity drift above threshold → realignment cycle forced
# ══════════════════════════════════════════════════════════════

class DriftCorrectionTrigger:
    THRESHOLD = 0.35
    COOLDOWN  = 120

    def __init__(self):
        self.corrections    = 0
        self.last_correction = 0.0

    def tick(self, drift_score: float) -> bool:
        if drift_score < self.THRESHOLD:
            return False
        if time.time() - self.last_correction < self.COOLDOWN:
            return False
        _log(f"[DriftCorrection] TRIGGER drift={drift_score:.3f}")
        self._realign()
        self.corrections   += 1
        self.last_correction = time.time()
        return True

    def _realign(self):
        try:
            with _db() as conn:
                conn.execute("""
                    UPDATE beliefs
                    SET confidence = MIN(confidence + 0.08, 0.95), last_referenced = ?
                    WHERE topic LIKE '%identity%'
                       OR topic LIKE '%self%'
                       OR topic LIKE '%nex%'
                """, (time.time(),))
                conn.execute("""
                    UPDATE beliefs
                    SET confidence = MAX(confidence - 0.03, 0.05), last_referenced = ?
                    WHERE confidence < 0.22
                      AND topic NOT LIKE '%identity%'
                      AND topic NOT LIKE '%truth%'
                      AND topic NOT LIKE '%contradiction%'
                """, (time.time(),))
                # commit handled by _db() context manager
            _log("[DriftCorrection] Realignment complete")
        except Exception as e:
            _log(f"[DriftCorrection] error: {e}")

    def status(self) -> dict:
        return {"corrections": self.corrections, "threshold": self.THRESHOLD}


# ══════════════════════════════════════════════════════════════
# 10. CORE DIRECTIVES LOCK
#     Immutable base beliefs — cannot decay or disappear
# ══════════════════════════════════════════════════════════════

class CoreDirectivesLock:
    INTERVAL = 60
    ANCHORS  = [
        ("truth_seeking",
         "NEX is committed to seeking truth above all else.", 0.98),
        ("contradiction_resolution",
         "Contradictions must be resolved, not suppressed.", 0.97),
        ("uncertainty_honesty",
         "Uncertain beliefs must be expressed as uncertain.", 0.95),
    ]

    def __init__(self):
        self.last_check = 0.0
        self._ensure()

    def _ensure(self):
        try:
            with _db() as conn:
                for topic, content, conf in self.ANCHORS:
                    row = conn.execute(
                        "SELECT id FROM beliefs WHERE topic=?", (topic,)
                    ).fetchone()
                    if not row:
                        conn.execute("""
                            INSERT INTO beliefs
                              (topic, content, confidence, reinforce_count, last_referenced)
                            VALUES (?,?,?,999,?)
                        """, (topic, content, conf, time.time()))
                        _log(f"[CoreLock] Seeded: {topic}")
                # commit handled by _db() context manager
        except Exception as e:
            _log(f"[CoreLock] seed error: {e}")

    def tick(self):
        if time.time() - self.last_check < self.INTERVAL:
            return
        self.last_check = time.time()
        try:
            with _db() as conn:
                for topic, content, conf in self.ANCHORS:
                    row = conn.execute(
                        "SELECT id, confidence FROM beliefs WHERE topic=?", (topic,)
                    ).fetchone()
                    if not row:
                        conn.execute("""
                            INSERT INTO beliefs
                              (topic, content, confidence, reinforce_count, last_referenced)
                            VALUES (?,?,?,999,?)
                        """, (topic, content, conf, time.time()))
                        _log(f"[CoreLock] Restored: {topic}")
                    elif row["confidence"] < conf - 0.05:
                        conn.execute(
                            "UPDATE beliefs SET confidence=?, last_referenced=? WHERE id=?",
                            (conf, time.time(), row["id"])
                        )
                # commit handled by _db() context manager
        except Exception as e:
            _log(f"[CoreLock] tick error: {e}")

    def status(self) -> dict:
        state = {}
        try:
            with _db() as conn:
                for topic, _, _ in self.ANCHORS:
                    row = conn.execute(
                        "SELECT confidence FROM beliefs WHERE topic=?", (topic,)
                    ).fetchone()
                    state[topic] = round(row["confidence"], 3) if row else "MISSING"
        except Exception:
            pass
        return {"anchors": state}


# ══════════════════════════════════════════════════════════════
# 11. PRIORITY SCHEDULER
#     Priority queue; drops low-priority items under load
# ══════════════════════════════════════════════════════════════

class PriorityScheduler:
    MAX_QUEUE = 200
    P = {"high_tension": 5, "contradiction": 4,
         "unstable": 3, "new_input": 2, "low_signal": 1}

    def __init__(self):
        self._q: list[tuple[int, float, dict]] = []
        self.processed = 0
        self.dropped   = 0

    def enqueue(self, item: dict, priority: str = "new_input"):
        p = self.P.get(priority, 1)
        if len(self._q) >= self.MAX_QUEUE:
            self._q.sort(key=lambda x: x[0])
            self._q.pop(0)
            self.dropped += 1
        self._q.append((p, time.time(), item))

    def pop(self) -> dict | None:
        if not self._q:
            return None
        self._q.sort(key=lambda x: (-x[0], x[1]))
        _, _, item = self._q.pop(0)
        self.processed += 1
        return item

    def tick(self):
        pass

    def status(self) -> dict:
        return {"queue_size": len(self._q), "processed": self.processed,
                "dropped": self.dropped}


# ══════════════════════════════════════════════════════════════
# 12. LOAD-ADAPTIVE PROCESSING
#     Reduces depth / insight / reflection under queue pressure
# ══════════════════════════════════════════════════════════════

class LoadAdaptiveProcessing:
    HIGH_WATERMARK = 150

    def __init__(self, scheduler: PriorityScheduler):
        self.sched           = scheduler
        self.depth_factor    = 1.0
        self.insight_rate    = 1.0
        self.reflection_rate = 1.0

    def tick(self):
        q = len(self.sched._q)
        if q > self.HIGH_WATERMARK:
            pressure             = min((q - self.HIGH_WATERMARK) / self.HIGH_WATERMARK, 1.0)
            self.depth_factor    = max(0.40, 1.0 - pressure * 0.60)
            self.insight_rate    = max(0.20, 1.0 - pressure * 0.80)
            self.reflection_rate = max(0.30, 1.0 - pressure * 0.70)
            if q > self.HIGH_WATERMARK * 1.5:
                _log(f"[LoadAdaptive] HIGH LOAD q={q} "
                     f"depth={self.depth_factor:.1f} insight={self.insight_rate:.1f}")
        else:
            self.depth_factor    = min(self.depth_factor    + 0.05, 1.0)
            self.insight_rate    = min(self.insight_rate    + 0.05, 1.0)
            self.reflection_rate = min(self.reflection_rate + 0.05, 1.0)

    def should_insight(self)  -> bool: return random.random() < self.insight_rate
    def should_reflect(self)  -> bool: return random.random() < self.reflection_rate

    def status(self) -> dict:
        return {"depth":    round(self.depth_factor, 2),
                "insight":  round(self.insight_rate, 2),
                "reflect":  round(self.reflection_rate, 2)}


# ══════════════════════════════════════════════════════════════
# 13. RESPONSE CONFIDENCE GATING
#     Blocks or marks uncertain outputs before they leave NEX
# ══════════════════════════════════════════════════════════════

class ResponseConfidenceGating:
    MIN_CONF    = 0.40
    UNCERTAIN_FLOOR = 0.25

    def __init__(self):
        self.passed    = 0
        self.uncertain = 0
        self.gated     = 0

    def check(self, response: str, confidence: float) -> tuple[str, bool]:
        if confidence >= self.MIN_CONF:
            self.passed += 1
            return response, True
        if confidence >= self.UNCERTAIN_FLOOR:
            self.uncertain += 1
            return f"[⚠ uncertain conf={confidence:.2f}] {response}", True
        self.gated += 1
        return "[gated: confidence too low]", False

    def status(self) -> dict:
        return {"passed": self.passed, "uncertain": self.uncertain,
                "gated": self.gated, "threshold": self.MIN_CONF}


# ══════════════════════════════════════════════════════════════
# 14. UNCERTAINTY EXPRESSION
#     Attaches epistemic metadata to any outgoing content
# ══════════════════════════════════════════════════════════════

class UncertaintyExpression:
    def __init__(self):
        self.annotations = 0

    def annotate(self, text: str, confidence: float,
                 has_contradiction: bool = False) -> str:
        tag = f"[conf:{confidence:.2f}"
        if has_contradiction:
            tag += " ⚡"
        tag += "]"
        self.annotations += 1
        return f"{text} {tag}"

    def status(self) -> dict:
        return {"annotations": self.annotations}


# ══════════════════════════════════════════════════════════════
# 15. PREDICTION → OUTCOME LOOP
#     Log predictions, compare outcomes, update belief confidence
# ══════════════════════════════════════════════════════════════

class PredictionOutcomeLoop:
    def __init__(self):
        self._preds: dict[str, dict] = {}
        self.resolved     = 0
        self.accuracy_sum = 0.0
        self._ctr         = 0

    def predict(self, belief_id: int, topic: str,
                predicted_conf: float) -> str:
        pid = f"P{self._ctr:05d}"
        self._ctr += 1
        self._preds[pid] = {"belief_id": belief_id, "topic": topic,
                            "predicted": predicted_conf, "ts": time.time()}
        return pid

    def resolve(self, pid: str, actual_conf: float):
        p = self._preds.pop(pid, None)
        if not p:
            return
        error    = abs(p["predicted"] - actual_conf)
        accuracy = max(0.0, 1.0 - error)
        self.accuracy_sum += accuracy
        self.resolved += 1
        # Nudge belief confidence toward outcome
        adj = (actual_conf - p["predicted"]) * 0.10
        try:
            with _db() as conn:
                conn.execute("""
                    UPDATE beliefs
                    SET confidence = MAX(0.05, MIN(confidence + ?, 1.0)),
                        last_referenced = ?
                    WHERE id = ?
                """, (adj, time.time(), p["belief_id"]))
                # commit handled by _db() context manager
        except Exception as e:
            _log(f"[PredictionLoop] db error: {e}")
        _log(f"[PredictionLoop] {pid} accuracy={accuracy:.2f} adj={adj:+.3f}")

    def tick(self):
        # Expire stale predictions
        cutoff = time.time() - 600
        stale  = [k for k, v in self._preds.items() if v["ts"] < cutoff]
        for k in stale:
            del self._preds[k]

    def status(self) -> dict:
        avg = self.accuracy_sum / max(self.resolved, 1)
        return {"active": len(self._preds), "resolved": self.resolved,
                "avg_accuracy": round(avg, 3)}


# ══════════════════════════════════════════════════════════════
# 16. FAILURE MEMORY SYSTEM
#     Tracks hallucinations / wrong beliefs / failed resolutions
# ══════════════════════════════════════════════════════════════

class FailureMemorySystem:
    MAX = 200

    def __init__(self):
        self._log_q: deque[dict] = deque(maxlen=self.MAX)
        self.hallucinations  = 0
        self.wrong_beliefs   = 0
        self.failed_resols   = 0

    def record(self, failure_type: str, detail: str,
               belief_id: int | None = None, confidence: float | None = None):
        entry = {"type": failure_type, "detail": detail[:200],
                 "belief_id": belief_id, "confidence": confidence,
                 "ts": time.time()}
        self._log_q.append(entry)

        if failure_type == "hallucination":
            self.hallucinations += 1
        elif failure_type == "wrong_belief":
            self.wrong_beliefs += 1
            if belief_id is not None:
                try:
                    with _db() as conn:
                        conn.execute("""
                            UPDATE beliefs
                            SET confidence = MAX(confidence - 0.10, 0.05), last_referenced = ?
                            WHERE id = ?
                        """, (time.time(), belief_id))
                        # commit handled by _db() context manager
                except Exception:
                    pass
        elif failure_type == "failed_resolution":
            self.failed_resols += 1

        _log(f"[FailureMemory] {failure_type}: {detail[:80]}")

    def recent(self, n: int = 10) -> list:
        return list(self._log_q)[-n:]

    def status(self) -> dict:
        return {"total": len(self._log_q),
                "hallucinations": self.hallucinations,
                "wrong_beliefs":  self.wrong_beliefs,
                "failed_resols":  self.failed_resols}


# ══════════════════════════════════════════════════════════════
# 17. SIMULATION SANDBOX
#     Test belief changes before committing to live graph
# ══════════════════════════════════════════════════════════════

class SimulationSandbox:
    def __init__(self):
        self.simulations = 0
        self.committed   = 0
        self.rejected    = 0

    def simulate(self, belief_id: int, new_confidence: float,
                 new_content: str | None = None) -> dict:
        self.simulations += 1
        try:
            with _db() as conn:
                b = conn.execute(
                    "SELECT id, topic, content, confidence, reinforce_count "
                    "FROM beliefs WHERE id=?", (belief_id,)
                ).fetchone()
            if not b:
                return {"safe": False, "reason": "not_found"}

            delta     = new_confidence - b["confidence"]
            risk      = abs(delta)
            is_anchor = any(t in b["topic"].lower()
                            for t in ["identity", "truth", "contradiction", "nex"])

            if is_anchor and risk > 0.15:
                return {"safe": False, "reason": "anchor_drift_risk",
                        "delta": round(delta, 3)}
            if new_confidence < 0.08 and b["reinforce_count"] > 10:
                return {"safe": False, "reason": "high_reinforcement_prune_block"}

            return {"safe": True, "delta": round(delta, 3),
                    "risk": round(risk, 3), "topic": b["topic"],
                    "recommendation": "commit" if risk < 0.20 else "review"}
        except Exception as e:
            return {"safe": False, "reason": str(e)}

    def commit(self, belief_id: int, new_confidence: float,
               new_content: str | None = None) -> bool:
        result = self.simulate(belief_id, new_confidence, new_content)
        if not result["safe"]:
            self.rejected += 1
            _log(f"[Sandbox] Rejected: {result['reason']}")
            return False
        try:
            with _db() as conn:
                if new_content:
                    conn.execute("""
                        UPDATE beliefs SET confidence=?, content=?, last_referenced=?
                        WHERE id=?
                    """, (new_confidence, new_content, time.time(), belief_id))
                else:
                    conn.execute(
                        "UPDATE beliefs SET confidence=?, last_referenced=? WHERE id=?",
                        (new_confidence, time.time(), belief_id)
                    )
                # commit handled by _db() context manager
        except Exception as e:
            _log(f"[Sandbox] commit db error: {e}")
            return False
        self.committed += 1
        return True

    def status(self) -> dict:
        return {"simulations": self.simulations,
                "committed":   self.committed,
                "rejected":    self.rejected}


# ══════════════════════════════════════════════════════════════
# 18. BELIEF MARKET
#     Beliefs compete for attention: strong gain, weak decay faster
# ══════════════════════════════════════════════════════════════

class BeliefMarket:
    INTERVAL    = 90
    BOOST       = 0.010
    DECAY_EXTRA = 0.008

    def __init__(self):
        self.cycles  = 0
        self.last    = 0.0
        self._weights: dict[int, float] = {}

    def tick(self):
        if time.time() - self.last < self.INTERVAL:
            return
        self.last = time.time()
        self.cycles += 1
        try:
            with _db() as conn:
                rows = conn.execute("""
                    SELECT id, confidence, reinforce_count, last_referenced
                    FROM beliefs LIMIT 400
                """).fetchall()
            if not rows:
                return

            now    = time.time()
            scored = []
            for r in rows:
                age_pen = math.exp(-(now - float(r["last_referenced"] or now)) / 86400)
                score   = (float(r["confidence"] or 0.5)
                           * math.log(int(r["reinforce_count"] or 0) + 2)
                           * age_pen)
                scored.append((r["id"], score))

            scored.sort(key=lambda x: -x[1])
            n        = len(scored)
            top_n    = max(1, int(n * 0.20))
            bottom_n = max(1, int(n * 0.30))

            top_ids    = [x[0] for x in scored[:top_n]]
            bottom_ids = [x[0] for x in scored[-bottom_n:]]

            with _db() as conn:
                for bid in top_ids:
                    conn.execute("""
                        UPDATE beliefs
                        SET confidence = MIN(confidence + ?, 1.0), last_referenced=?
                        WHERE id=?
                    """, (self.BOOST, now, bid))
                    self._weights[bid] = 1.2
                for bid in bottom_ids:
                    conn.execute("""
                        UPDATE beliefs
                        SET confidence = MAX(confidence - ?, 0.03), last_referenced=?
                        WHERE id=?
                    """, (self.DECAY_EXTRA, now, bid))
                    self._weights[bid] = 0.5
                # commit handled by _db() context manager

            _log(f"[BeliefMarket] cycle={self.cycles} "
                 f"boosted={len(top_ids)} decayed={len(bottom_ids)}")
        except Exception as e:
            _log(f"[BeliefMarket] error: {e}")

    def status(self) -> dict:
        return {"cycles": self.cycles, "tracked": len(self._weights)}


# ══════════════════════════════════════════════════════════════
# V6.5 ORCHESTRATOR  —  single instance, all 18 modules wired
# ══════════════════════════════════════════════════════════════

class NexV65:
    def __init__(self):
        _log("[v6.5] Initialising 18-module stack...")

        self.decision_engine  = DecisionEngine()
        self.hard_pruning     = HardPruningSystem()
        self.insight_gate     = StrictInsightGate()
        self.wiki_validator   = BeliefValidationLayer()
        self.clustering       = BeliefClusteringEngine()
        self.consolidation    = MemoryConsolidationPass()
        self.temporal         = TemporalPatternAnalysis()
        self.drift_correction = DriftCorrectionTrigger()
        self.core_lock        = CoreDirectivesLock()
        self.scheduler        = PriorityScheduler()
        self.load_adaptive    = LoadAdaptiveProcessing(self.scheduler)
        self.conf_gate        = ResponseConfidenceGating()
        self.uncertainty      = UncertaintyExpression()
        self.prediction_loop  = PredictionOutcomeLoop()
        self.failure_memory   = FailureMemorySystem()
        self.sandbox          = SimulationSandbox()
        self.belief_market    = BeliefMarket()
        self.tension_lock     = TensionActionLock(self.decision_engine)

        self._cycle = 0
        _log("[v6.5] All 18 modules ready ✓")

    # ------------------------------------------------------------------
    # Main tick — called from run.py main loop every cycle
    # ------------------------------------------------------------------
    def tick(self,
             avg_conf:     float = 0.44,
             tension_score: float = 0.0,
             drift_score:   float = 0.0,
             top_topic:     str   = ""):
        self._cycle += 1

        self.core_lock.tick()                           # anchors first
        self.hard_pruning.tick()                        # keep graph lean
        self.tension_lock.tick(tension_score)           # force resolution on spike
        self.decision_engine.tick(tension_score)        # normal decision pass
        self.drift_correction.tick(drift_score)         # identity anchor
        self.temporal.record(avg_conf, top_topic)       # trend tracking
        self.clustering.tick()                          # cluster refresh
        self.consolidation.tick()                       # dedupe pass
        self.belief_market.tick()                       # market cycle
        self.load_adaptive.tick()                       # adapt to queue
        self.insight_gate.tick()                        # GC seen hashes
        self.prediction_loop.tick()                     # expire old preds

        # Wiki validation is slow/network — run in daemon thread
        threading.Thread(target=self.wiki_validator.tick, daemon=True).start()

    # ------------------------------------------------------------------
    # Full status dict
    # ------------------------------------------------------------------
    def get_status(self) -> dict:
        return {
            "cycle":          self._cycle,
            "decision_engine": self.decision_engine.status(),
            "hard_pruning":    self.hard_pruning.status(),
            "insight_gate":    self.insight_gate.status(),
            "clustering":      self.clustering.status(),
            "consolidation":   self.consolidation.status(),
            "temporal":        self.temporal.status(),
            "drift_correction":self.drift_correction.status(),
            "core_lock":       self.core_lock.status(),
            "scheduler":       self.scheduler.status(),
            "load_adaptive":   self.load_adaptive.status(),
            "conf_gate":       self.conf_gate.status(),
            "uncertainty":     self.uncertainty.status(),
            "prediction_loop": self.prediction_loop.status(),
            "failure_memory":  self.failure_memory.status(),
            "sandbox":         self.sandbox.status(),
            "belief_market":   self.belief_market.status(),
            "tension_lock":    self.tension_lock.status(),
            "wiki_validator":  self.wiki_validator.status(),
        }

    # ------------------------------------------------------------------
    # Telegram-friendly formatted status
    # ------------------------------------------------------------------
    def format_status(self) -> str:
        s = self.get_status()
        hp = s["hard_pruning"]
        de = s["decision_engine"]
        tl = s["tension_lock"]
        dc = s["drift_correction"]
        cl = s["clustering"]
        bm = s["belief_market"]
        tp = s["temporal"]
        pl = s["prediction_loop"]
        fm = s["failure_memory"]
        ck = s["core_lock"]
        la = s["load_adaptive"]
        ig = s["insight_gate"]

        trend_dir = tp.get("latest_trend", {}).get("direction", "?")
        cores = " | ".join(
            f"{k.replace('_', ' ')[:6]}:{v}"
            for k, v in ck["anchors"].items()
        )
        last_action = (de.get("last") or {}).get("action", "none")

        lines = [
            f"⚙️ *NEX v6.5* — cycle {s['cycle']}",
            f"🧠 Beliefs: {hp['belief_count']}/{hp['max']} "
              f"pressure={hp['pressure']} pruned={hp['total_pruned']}",
            f"⚖️ Decisions: {de['decisions_made']} last={last_action}",
            f"⚡ TensionLock fires: {tl['lock_count']} (thresh {tl['threshold']})",
            f"🧭 Drift corrections: {dc['corrections']}",
            f"🔵 Clusters: {cl['cluster_count']}",
            f"📈 Market cycles: {bm['cycles']}",
            f"📊 Trend: {trend_dir} | osc: {tp['oscillations']} "
              f"| conf̄: {tp['conf_mean']}",
            f"🎯 Predictions resolved: {pl['resolved']} "
              f"| acc: {pl['avg_accuracy']}",
            f"❌ Failures: {fm['total']} "
              f"(hall:{fm['hallucinations']} wb:{fm['wrong_beliefs']})",
            f"🔒 Cores: {cores}",
            f"⚡ Load: depth={la['depth']} "
              f"insight={la['insight']} reflect={la['reflect']}",
            f"🚪 InsightGate: pass={ig['passed']} blocked={ig['blocked']} "
              f"rate={ig['pass_rate']}",
        ]
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# Module singleton
# ══════════════════════════════════════════════════════════════

_singleton: NexV65 | None = None
_lock = threading.Lock()

def get_v65() -> NexV65:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = NexV65()
    return _singleton
