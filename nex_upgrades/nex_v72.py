"""
NEX v7.2 — Calculated Upgrade Directives (Post Evolution 3)
20-module cognitive evolution stack
Deploy: ~/Desktop/nex/nex_upgrades/nex_v72.py
Wire:   deploy_v72.sh
"""

import sqlite3, json, time, math, random, threading, hashlib
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".config/nex/nex.db"
LOG     = Path("/tmp/nex_v72.log")

def _db():
    c = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _ts():
    return datetime.now(timezone.utc).isoformat()

def _log(msg):
    line = f"[v72 {datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# PHASE 1 — CRITICAL
# ══════════════════════════════════════════════════════════════

# ── 1. DECISION QUALITY SCORING ──────────────────────────────
class DecisionQualityScoring:
    """Track decision outcomes; reward correct, penalise incorrect.
    Stores decision_success_rate per belief cluster."""
    INTERVAL = 60

    def __init__(self):
        self._scores: dict[str, list[float]] = defaultdict(list)
        self.last_run = 0.0
        self.total_scored = 0
        self._ensure_table()

    def _ensure_table(self):
        try:
            with _db() as c:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS decision_quality (
                        cluster     TEXT PRIMARY KEY,
                        success_rate REAL DEFAULT 0.5,
                        total       INTEGER DEFAULT 0,
                        last_updated TEXT
                    )
                """)
                # commit handled by _db() context manager
        except Exception as e:
            _log(f"[DQS] table error: {e}")

    def record(self, cluster: str, success: bool):
        val = 1.0 if success else 0.0
        self._scores[cluster].append(val)
        if len(self._scores[cluster]) > 50:
            self._scores[cluster].pop(0)
        self.total_scored += 1

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                for cluster, vals in self._scores.items():
                    if not vals: continue
                    rate = sum(vals) / len(vals)
                    c.execute("""
                        INSERT INTO decision_quality (cluster, success_rate, total, last_updated)
                        VALUES (?,?,?,?)
                        ON CONFLICT(cluster) DO UPDATE SET
                            success_rate=excluded.success_rate,
                            total=total+excluded.total,
                            last_updated=excluded.last_updated
                    """, (cluster, round(rate, 4), len(vals), _ts()))
                    # Adjust confidence of beliefs in this cluster based on rate
                    adj = (rate - 0.5) * 0.04
                    c.execute("""
                        UPDATE beliefs SET confidence = MAX(0.05, MIN(confidence+?, 0.99))
                        WHERE topic LIKE ?
                    """, (adj, f"%{cluster}%"))
                # commit handled by _db() context manager
            _log(f"[DQS] Scored {len(self._scores)} clusters")
        except Exception as e:
            _log(f"[DQS] tick error: {e}")

    def status(self) -> dict:
        try:
            with _db() as c:
                rows = c.execute(
                    "SELECT cluster, success_rate, total FROM decision_quality "
                    "ORDER BY success_rate DESC LIMIT 5"
                ).fetchall()
            return {"total_scored": self.total_scored,
                    "top_clusters": [dict(r) for r in rows]}
        except Exception:
            return {"total_scored": self.total_scored}


# ── 2. FORCED TENSION RESOLUTION ─────────────────────────────
class ForcedTensionResolution:
    """If a tension cluster persists > N cycles: force merge or delete."""
    MAX_CYCLES   = 8
    INTERVAL     = 45

    def __init__(self):
        self._tension_age: dict[str, int] = {}
        self.forced      = 0
        self.last_run    = 0.0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                # Find topics with multiple low-conf contradictory beliefs
                rows = c.execute("""
                    SELECT topic, COUNT(*) n, AVG(confidence) ac, MIN(confidence) mn
                    FROM beliefs
                    WHERE confidence < 0.45
                    GROUP BY topic HAVING n >= 3
                    ORDER BY n DESC LIMIT 10
                """).fetchall()

            for r in rows:
                topic = r["topic"]
                self._tension_age[topic] = self._tension_age.get(topic, 0) + 1
                if self._tension_age[topic] < self.MAX_CYCLES:
                    continue
                # Force resolution
                with _db() as c:
                    beliefs = c.execute(
                        "SELECT id, confidence FROM beliefs WHERE topic=? ORDER BY confidence",
                        (topic,)
                    ).fetchall()
                if len(beliefs) < 2:
                    continue
                # Delete bottom half, boost top
                split    = max(1, len(beliefs) // 2)
                del_ids  = [b["id"] for b in beliefs[:split]]
                keep_ids = [b["id"] for b in beliefs[split:]]
                with _db() as c:
                    c.execute(f"DELETE FROM beliefs WHERE id IN ({','.join('?'*len(del_ids))})",
                              del_ids)
                    for kid in keep_ids:
                        c.execute("UPDATE beliefs SET confidence=MIN(confidence+0.06,0.90) WHERE id=?",
                                  (kid,))
                    # commit handled by _db() context manager
                self._tension_age[topic] = 0
                self.forced += 1
                _log(f"[FTR] Forced resolution: {topic} deleted={len(del_ids)}")
        except Exception as e:
            _log(f"[FTR] error: {e}")

    def status(self) -> dict:
        return {"forced_resolutions": self.forced,
                "tracked_clusters": len(self._tension_age),
                "aging": {k: v for k, v in sorted(
                    self._tension_age.items(), key=lambda x: -x[1])[:5]}}


# ── 3. DYNAMIC BELIEF CAP ─────────────────────────────────────
class DynamicBeliefCap:
    """Adaptive cap: high conf → expand, low conf → prune aggressively."""
    BASE_CAP   = 1800
    MIN_CAP    = 900
    MAX_CAP    = 3000
    INTERVAL   = 90

    def __init__(self):
        self.current_cap = self.BASE_CAP
        self.last_run    = 0.0
        self.prunes      = 0

    def _calc_cap(self, avg_conf: float, queue_pressure: float) -> int:
        conf_factor  = (avg_conf - 0.5) * 1000      # ±500 around base
        load_factor  = -queue_pressure * 400          # shrink under load
        cap = int(self.BASE_CAP + conf_factor + load_factor)
        return max(self.MIN_CAP, min(self.MAX_CAP, cap))

    def tick(self, avg_conf: float = 0.50, queue_pressure: float = 0.0):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run    = time.time()
        self.current_cap = self._calc_cap(avg_conf, queue_pressure)
        try:
            with _db() as c:
                count = c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                if count <= self.current_cap:
                    return
                excess = count - self.current_cap
                c.execute("""
                    DELETE FROM beliefs WHERE id IN (
                        SELECT id FROM beliefs
                        WHERE locked=0 AND topic NOT IN
                            ('truth_seeking','contradiction_resolution','uncertainty_honesty')
                        ORDER BY (confidence*0.6 + reinforce_count*0.01) ASC
                        LIMIT ?
                    )
                """, (excess,))
                # commit handled by _db() context manager
                self.prunes += excess
                _log(f"[DBC] cap={self.current_cap} pruned={excess} "
                     f"(conf={avg_conf:.2f})")
        except Exception as e:
            _log(f"[DBC] error: {e}")

    def status(self) -> dict:
        return {"current_cap": self.current_cap, "total_pruned": self.prunes,
                "range": f"{self.MIN_CAP}–{self.MAX_CAP}"}


# ── 4. CLUSTER-LEVEL PRUNING ──────────────────────────────────
class ClusterLevelPruning:
    """Prune entire weak clusters: low avg_conf + low reinforcement + low usage."""
    INTERVAL      = 300
    MIN_AVG_CONF  = 0.25
    MIN_AVG_RC    = 1.0
    MIN_CLUSTER   = 5   # only prune clusters with ≥5 members

    def __init__(self):
        self.last_run     = 0.0
        self.clusters_pruned = 0
        self.beliefs_pruned  = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT topic, COUNT(*) n,
                           AVG(confidence) ac,
                           AVG(reinforce_count) arc,
                           AVG(last_used_cycle) alc
                    FROM beliefs
                    WHERE locked=0
                      AND topic NOT IN
                        ('truth_seeking','contradiction_resolution','uncertainty_honesty')
                    GROUP BY topic
                    HAVING n >= ? AND ac < ? AND arc < ?
                    ORDER BY ac ASC LIMIT 5
                """, (self.MIN_CLUSTER, self.MIN_AVG_CONF, self.MIN_AVG_RC)).fetchall()

            for r in rows:
                with _db() as c:
                    c.execute("DELETE FROM beliefs WHERE topic=? AND locked=0",
                              (r["topic"],))
                    # commit handled by _db() context manager
                self.clusters_pruned += 1
                self.beliefs_pruned  += r["n"]
                _log(f"[CLP] Pruned cluster '{r['topic']}' "
                     f"n={r['n']} ac={r['ac']:.2f} arc={r['arc']:.1f}")
        except Exception as e:
            _log(f"[CLP] error: {e}")

    def status(self) -> dict:
        return {"clusters_pruned": self.clusters_pruned,
                "beliefs_pruned": self.beliefs_pruned}


# ── 5. MULTI-PASS VALIDATION ──────────────────────────────────
class MultiPassValidation:
    """Revalidate beliefs periodically; boost if consistently supported,
    decay if repeatedly contradicted."""
    INTERVAL = 180
    PASSES   = 3

    def __init__(self):
        self._history: dict[int, list[float]] = defaultdict(list)
        self.last_run  = 0.0
        self.validated = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT id, topic, content, confidence
                    FROM beliefs WHERE confidence BETWEEN 0.20 AND 0.80
                    ORDER BY RANDOM() LIMIT 20
                """).fetchall()

            for r in rows:
                h = self._history[r["id"]]
                h.append(r["confidence"])
                if len(h) > self.PASSES: h.pop(0)
                if len(h) < self.PASSES: continue

                trend = h[-1] - h[0]
                if trend > 0.05:
                    adj =  0.03   # consistently rising — boost
                elif trend < -0.05:
                    adj = -0.04   # consistently falling — accelerate decay
                else:
                    continue

                with _db() as c:
                    c.execute(
                        "UPDATE beliefs SET confidence=MAX(0.05,MIN(confidence+?,0.99)) WHERE id=?",
                        (adj, r["id"])
                    )
                    # commit handled by _db() context manager
                self.validated += 1
        except Exception as e:
            _log(f"[MPV] error: {e}")

    def status(self) -> dict:
        return {"validated": self.validated, "tracked": len(self._history)}


# ── 6. BELIEF ENTROPY REDUCTION ──────────────────────────────
class BeliefEntropyReduction:
    """Detect and remove isolated, low-connectivity, low-impact beliefs."""
    INTERVAL     = 240
    MAX_ISOLATED = 50    # cap removal per pass

    def __init__(self):
        self.last_run = 0.0
        self.removed  = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                # Isolated: no edges, low conf, low reinforce, never used
                rows = c.execute("""
                    SELECT b.id FROM beliefs b
                    LEFT JOIN belief_edges e ON b.id=e.source_id OR b.id=e.target_id
                    WHERE e.source_id IS NULL
                      AND b.confidence < 0.30
                      AND b.reinforce_count < 2
                      AND b.last_used_cycle = 0
                      AND b.locked = 0
                      AND b.topic NOT IN
                        ('truth_seeking','contradiction_resolution','uncertainty_honesty')
                    LIMIT ?
                """, (self.MAX_ISOLATED,)).fetchall()

                if rows:
                    ids = [r["id"] for r in rows]
                    c.execute(
                        f"DELETE FROM beliefs WHERE id IN ({','.join('?'*len(ids))})", tuple(ids))
                    # commit handled by _db() context manager
                    self.removed += len(ids)
                    _log(f"[BER] Removed {len(ids)} isolated low-entropy beliefs")
        except Exception as e:
            _log(f"[BER] error: {e}")

    def status(self) -> dict:
        return {"removed": self.removed}


# ══════════════════════════════════════════════════════════════
# PHASE 2 — HIGH PRIORITY
# ══════════════════════════════════════════════════════════════

# ── 7. BELIEF MARKET FEEDBACK LOOP ───────────────────────────
class BeliefMarketFeedbackLoop:
    """Update market weights based on prediction success + decision outcomes."""
    INTERVAL = 120

    def __init__(self, dqs: DecisionQualityScoring):
        self.dqs      = dqs
        self.last_run = 0.0
        self.updates  = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                # Get clusters with known quality scores
                rows = c.execute(
                    "SELECT cluster, success_rate FROM decision_quality"
                ).fetchall()

            for r in rows:
                cluster = r["cluster"]
                rate    = r["success_rate"]
                adj     = (rate - 0.5) * 0.06   # ±0.03
                with _db() as c:
                    c.execute("""
                        UPDATE beliefs
                        SET confidence = MAX(0.05, MIN(confidence+?, 0.99))
                        WHERE topic LIKE ? AND locked=0
                    """, (adj, f"%{cluster}%"))
                    # commit handled by _db() context manager
                self.updates += 1
        except Exception as e:
            _log(f"[BMFL] error: {e}")

    def status(self) -> dict:
        return {"updates": self.updates}


# ── 8. REFLECTION → ACTION BINDING ───────────────────────────
class ReflectionActionBinding:
    """Every reflection triggers a belief adjustment or decision review."""
    INTERVAL = 30

    def __init__(self):
        self._last_ref_count = 0
        self.bindings        = 0
        self.last_run        = 0.0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                count = c.execute("SELECT COUNT(*) FROM reflections").fetchone()[0]
                new   = count - self._last_ref_count
                if new <= 0:
                    self._last_ref_count = count
                    return

                # Get the newest reflections
                rows = c.execute("""
                    SELECT content FROM reflections
                    ORDER BY timestamp DESC LIMIT ?
                """, (min(new, 10),)).fetchall()

            for r in rows:
                content = (r["content"] or "").lower()
                # Extract topic signal from reflection content
                words = [w for w in content.split() if len(w) > 4][:5]
                for word in words:
                    with _db() as c:
                        hit = c.execute(
                            "SELECT id, confidence FROM beliefs WHERE content LIKE ? LIMIT 1",
                            (f"%{word}%",)
                        ).fetchone()
                        if hit:
                            adj = 0.02
                            c.execute(
                                "UPDATE beliefs SET confidence=MIN(confidence+?,0.95) WHERE id=?",
                                (adj, hit["id"])
                            )
                            # commit handled by _db() context manager
                            self.bindings += 1
                            break

            self._last_ref_count = count
        except Exception as e:
            _log(f"[RAB] error: {e}")

    def status(self) -> dict:
        return {"bindings": self.bindings, "last_ref_count": self._last_ref_count}


# ── 9. TEMPORAL INTELLIGENCE v2 ──────────────────────────────
class TemporalIntelligenceV2:
    """Classify beliefs: short-lived / persistent / cyclical.
    Adjust decay rates accordingly."""
    INTERVAL = 300
    DECAY = {"short_lived": 0.010, "persistent": 0.001, "cyclical": 0.004}

    def __init__(self):
        self.last_run    = 0.0
        self._classified: dict[int, str] = {}
        self.classified  = 0

    def _classify(self, rc: int, oc: int, used: int) -> str:
        if rc >= 5 and oc >= 2:
            return "persistent"
        if rc >= 3 and oc == 0:
            return "short_lived"
        return "cyclical"

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT id, confidence, reinforce_count, outcome_count, last_used_cycle
                    FROM beliefs WHERE locked=0 LIMIT 200
                """).fetchall()

            for r in rows:
                cls  = self._classify(r["reinforce_count"], r["outcome_count"],
                                       r["last_used_cycle"])
                self._classified[r["id"]] = cls
                decay = self.DECAY[cls]
                with _db() as c:
                    c.execute(
                        "UPDATE beliefs SET confidence=MAX(0.05,confidence-?) WHERE id=?",
                        (decay, r["id"])
                    )
                    # commit handled by _db() context manager
                self.classified += 1
        except Exception as e:
            _log(f"[TIv2] error: {e}")

    def status(self) -> dict:
        counts: dict[str, int] = defaultdict(int)
        for cls in self._classified.values():
            counts[cls] += 1
        return {"classified": self.classified, "distribution": dict(counts)}


# ── 10. IDENTITY GRAVITY ─────────────────────────────────────
class IdentityGravity:
    """Boost beliefs aligned with CoreDirectives; decay misaligned."""
    INTERVAL  = 120
    BOOST     = 0.012
    DECAY_ADJ = 0.008
    ANCHORS   = ["truth", "contradiction", "uncertainty", "nex", "identity", "honest"]

    def __init__(self):
        self.last_run = 0.0
        self.boosted  = 0
        self.decayed  = 0

    def _aligned(self, content: str) -> bool:
        cl = content.lower()
        return any(a in cl for a in self.ANCHORS)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                rows = c.execute(
                    "SELECT id, content, confidence FROM beliefs WHERE locked=0 LIMIT 300"
                ).fetchall()

            for r in rows:
                if self._aligned(r["content"]):
                    adj = self.BOOST
                    self.boosted += 1
                else:
                    adj = -self.DECAY_ADJ
                    self.decayed += 1
                with _db() as c:
                    c.execute(
                        "UPDATE beliefs SET confidence=MAX(0.05,MIN(confidence+?,0.99)) WHERE id=?",
                        (adj, r["id"])
                    )
                    # commit handled by _db() context manager
        except Exception as e:
            _log(f"[IG] error: {e}")

    def status(self) -> dict:
        return {"boosted": self.boosted, "decayed": self.decayed}


# ══════════════════════════════════════════════════════════════
# PHASE 3 — STRUCTURAL
# ══════════════════════════════════════════════════════════════

# ── 11. HIERARCHICAL BELIEF GRAPH ────────────────────────────
class HierarchicalBeliefGraph:
    """Introduce levels: core → cluster → node. Operate at higher levels first."""
    INTERVAL = 400

    def __init__(self):
        self.last_run = 0.0
        self.hierarchy: dict[str, dict] = {}

    def _build(self):
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT topic, COUNT(*) n, AVG(confidence) ac,
                           SUM(reinforce_count) rc
                    FROM beliefs GROUP BY topic
                """).fetchall()

            h: dict[str, dict] = {}
            for r in rows:
                topic = r["topic"] or "unknown"
                level = ("core"    if r["rc"] > 50  else
                         "cluster" if r["n"] > 5    else "node")
                h[topic] = {"level": level, "n": r["n"],
                            "avg_conf": round(r["ac"], 3)}
            self.hierarchy = h
            _log(f"[HBG] Built hierarchy: "
                 f"core={sum(1 for v in h.values() if v['level']=='core')} "
                 f"cluster={sum(1 for v in h.values() if v['level']=='cluster')} "
                 f"node={sum(1 for v in h.values() if v['level']=='node')}")
        except Exception as e:
            _log(f"[HBG] error: {e}")

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        self._build()

    def get_level(self, topic: str) -> str:
        return self.hierarchy.get(topic, {}).get("level", "node")

    def status(self) -> dict:
        counts: dict[str, int] = defaultdict(int)
        for v in self.hierarchy.values():
            counts[v["level"]] += 1
        return {"levels": dict(counts), "total_topics": len(self.hierarchy)}


# ── 12. CROSS-CLUSTER CONTRADICTION DETECTION ────────────────
class CrossClusterContradictionDetection:
    """Detect contradictions between clusters, not just nodes."""
    INTERVAL = 360

    def __init__(self):
        self.last_run    = 0.0
        self.detected    = 0
        self._pairs: list[dict] = []

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT topic, GROUP_CONCAT(content, ' |||') summary,
                           AVG(confidence) ac
                    FROM beliefs GROUP BY topic HAVING COUNT(*) >= 2
                    ORDER BY RANDOM() LIMIT 30
                """).fetchall()

            topics = [dict(r) for r in rows]
            new_pairs = []
            for i in range(len(topics)):
                for j in range(i+1, len(topics)):
                    a = set((topics[i]["summary"] or "").lower().split())
                    b = set((topics[j]["summary"] or "").lower().split())
                    if not a or not b: continue
                    overlap  = len(a & b) / len(a | b)
                    conf_gap = abs(topics[i]["ac"] - topics[j]["ac"])
                    if overlap > 0.15 and conf_gap > 0.30:
                        pair = {"a": topics[i]["topic"], "b": topics[j]["topic"],
                                "overlap": round(overlap, 3),
                                "conf_gap": round(conf_gap, 3)}
                        new_pairs.append(pair)
                        self.detected += 1

            self._pairs = new_pairs[-20:]
            if new_pairs:
                _log(f"[XCCD] {len(new_pairs)} cross-cluster contradictions detected")
        except Exception as e:
            _log(f"[XCCD] error: {e}")

    def status(self) -> dict:
        return {"detected": self.detected, "recent": self._pairs[:3]}


# ── 13. MEMORY COMPRESSION v2 ────────────────────────────────
class MemoryCompressionV2:
    """Compress rarely accessed belief clusters into summary beliefs."""
    INTERVAL   = 600
    COLD_CYCLE = 10    # max last_used_cycle to be "cold"
    MIN_CLUSTER = 6

    def __init__(self):
        self.last_run   = 0.0
        self.compressed = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT topic, COUNT(*) n, AVG(confidence) ac,
                           MAX(last_used_cycle) mlc,
                           GROUP_CONCAT(content, ' | ') summary
                    FROM beliefs
                    WHERE last_used_cycle <= ? AND locked=0
                    GROUP BY topic HAVING n >= ?
                    ORDER BY mlc ASC LIMIT 5
                """, (self.COLD_CYCLE, self.MIN_CLUSTER)).fetchall()

            for r in rows:
                summary = (r["summary"] or "")[:400]
                comp    = f"[compressed:{r['n']}] {summary}"
                with _db() as c:
                    # Delete originals, insert compressed summary
                    c.execute("DELETE FROM beliefs WHERE topic=? AND locked=0",
                              (r["topic"],))
                    c.execute("""
                        INSERT OR IGNORE INTO beliefs
                          (topic, content, confidence, reinforce_count, last_referenced)
                        VALUES (?,?,?,0,?)
                    """, (r["topic"], comp, r["ac"], _ts()))
                    # commit handled by _db() context manager
                self.compressed += 1
                _log(f"[MCv2] Compressed cluster '{r['topic']}' ({r['n']} → 1)")
        except Exception as e:
            _log(f"[MCv2] error: {e}")

    def status(self) -> dict:
        return {"compressed_clusters": self.compressed}


# ── 14. CONTEXT RESOLUTION ENGINE ────────────────────────────
class ContextResolutionEngine:
    """Eliminate 'unknown contextual' — enforce domain classification."""
    INTERVAL = 120
    DOMAIN_MAP = [
        (["security","cve","exploit","vulnerability","attack"],   "security"),
        (["ai","agent","llm","model","neural","transformer"],     "AI_systems"),
        (["memory","belief","cognition","reasoning","knowledge"], "cognition"),
        (["identity","self","nex","consciousness","awareness"],   "identity"),
        (["code","programming","software","algorithm","python"],  "engineering"),
        (["human","social","conversation","language","text"],     "social"),
        (["research","paper","arxiv","study","experiment"],       "research"),
        (["crypto","blockchain","token","wallet","defi"],         "crypto"),
    ]

    def __init__(self):
        self.last_run = 0.0
        self.resolved = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT id, content FROM beliefs
                    WHERE topic IS NULL OR topic='' OR topic='unknown'
                       OR topic LIKE '%unknown%' OR topic LIKE '%contextual%'
                    LIMIT 50
                """).fetchall()

            for r in rows:
                cl     = (r["content"] or "").lower()
                domain = "general"
                for keywords, label in self.DOMAIN_MAP:
                    if any(k in cl for k in keywords):
                        domain = label
                        break
                with _db() as c:
                    c.execute("UPDATE beliefs SET topic=? WHERE id=?",
                              (domain, r["id"]))
                    # commit handled by _db() context manager
                self.resolved += 1
        except Exception as e:
            _log(f"[CRE] error: {e}")

    def status(self) -> dict:
        return {"resolved": self.resolved}


# ══════════════════════════════════════════════════════════════
# PHASE 3 — CONTROL + STABILITY
# ══════════════════════════════════════════════════════════════

# ── 15. QUEUE HARD LIMIT + DROP POLICY ───────────────────────
class QueueHardLimit:
    """Strict max queue; drop lowest priority immediately."""
    MAX_SIZE = 150

    def __init__(self):
        self._q: list[tuple[int, float, dict]] = []
        self.dropped   = 0
        self.processed = 0
        PRIORITIES = {"critical": 5, "high": 4, "normal": 3, "low": 2, "idle": 1}
        self._P = PRIORITIES

    def enqueue(self, item: dict, priority: str = "normal"):
        p = self._P.get(priority, 3)
        if len(self._q) >= self.MAX_SIZE:
            self._q.sort(key=lambda x: x[0])
            self._q.pop(0)
            self.dropped += 1
        self._q.append((p, time.time(), item))

    def pop(self) -> dict | None:
        if not self._q: return None
        self._q.sort(key=lambda x: (-x[0], x[1]))
        _, _, item = self._q.pop(0)
        self.processed += 1
        return item

    def tick(self): pass

    def status(self) -> dict:
        return {"queue_size": len(self._q), "max": self.MAX_SIZE,
                "dropped": self.dropped, "processed": self.processed}


# ── 16. LOAD-SENSITIVE DECISION DEPTH ────────────────────────
class LoadSensitiveDecisionDepth:
    """Under high load: simplify decision evaluation depth."""
    HIGH_LOAD_THRESHOLD = 0.70

    def __init__(self, queue: QueueHardLimit):
        self.q      = queue
        self.depth  = 1.0
        self.reductions = 0

    def tick(self):
        pressure = len(self.q._q) / max(self.q.MAX_SIZE, 1)
        if pressure > self.HIGH_LOAD_THRESHOLD:
            self.depth = max(0.30, 1.0 - (pressure - self.HIGH_LOAD_THRESHOLD) * 2)
            self.reductions += 1
        else:
            self.depth = min(1.0, self.depth + 0.10)

    def max_candidates(self, default: int = 20) -> int:
        return max(3, int(default * self.depth))

    def status(self) -> dict:
        return {"depth": round(self.depth, 2), "reductions": self.reductions}


# ── 17. FAILURE MEMORY PENALTY ───────────────────────────────
class FailureMemoryPenalty:
    """Penalise belief clusters linked to repeated failures."""
    INTERVAL        = 180
    PENALTY         = 0.05
    FAILURE_THRESHOLD = 3

    def __init__(self):
        self._failure_counts: dict[str, int] = defaultdict(int)
        self.last_run  = 0.0
        self.penalties = 0

    def record_failure(self, topic: str):
        self._failure_counts[topic] += 1

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            for topic, count in list(self._failure_counts.items()):
                if count < self.FAILURE_THRESHOLD:
                    continue
                with _db() as c:
                    c.execute("""
                        UPDATE beliefs
                        SET confidence = MAX(0.05, confidence - ?)
                        WHERE topic LIKE ? AND locked=0
                    """, (self.PENALTY, f"%{topic}%"))
                    # commit handled by _db() context manager
                self.penalties += 1
                self._failure_counts[topic] = 0
                _log(f"[FMP] Penalised cluster '{topic}' (failures={count})")
        except Exception as e:
            _log(f"[FMP] error: {e}")

    def status(self) -> dict:
        top = sorted(self._failure_counts.items(), key=lambda x: -x[1])[:5]
        return {"penalties": self.penalties,
                "hot_failures": dict(top)}


# ══════════════════════════════════════════════════════════════
# PHASE 3 — ADVANCED
# ══════════════════════════════════════════════════════════════

# ── 18. PREDICTION CONFIDENCE CALIBRATION ────────────────────
class PredictionConfidenceCalibration:
    """Align belief confidence with real-world prediction accuracy."""
    INTERVAL = 240

    def __init__(self):
        self._preds: dict[str, dict] = {}
        self.last_run   = 0.0
        self.calibrated = 0
        self._ctr = 0

    def predict(self, topic: str, conf: float) -> str:
        pid = f"P{self._ctr:05d}"
        self._ctr += 1
        self._preds[pid] = {"topic": topic, "conf": conf, "ts": time.time()}
        return pid

    def resolve(self, pid: str, actual: float):
        p = self._preds.pop(pid, None)
        if not p: return
        error = abs(p["conf"] - actual)
        adj   = (actual - p["conf"]) * 0.08
        try:
            with _db() as c:
                c.execute("""
                    UPDATE beliefs
                    SET confidence = MAX(0.05, MIN(confidence+?, 0.99))
                    WHERE topic LIKE ? AND locked=0
                """, (adj, f"%{p['topic']}%"))
                # commit handled by _db() context manager
            self.calibrated += 1
        except Exception as e:
            _log(f"[PCC] error: {e}")

    def tick(self):
        cutoff = time.time() - 900
        stale  = [k for k, v in self._preds.items() if v["ts"] < cutoff]
        for k in stale: del self._preds[k]

    def status(self) -> dict:
        return {"calibrated": self.calibrated, "active_preds": len(self._preds)}


# ── 19. SIMULATION VALIDATION LOOP ───────────────────────────
class SimulationValidationLoop:
    """Simulate belief changes before applying; block unsafe mutations."""
    def __init__(self):
        self.simulations = 0
        self.blocked     = 0
        self.committed   = 0

    def validate_and_apply(self, belief_id: int,
                            new_conf: float,
                            new_content: str | None = None) -> bool:
        self.simulations += 1
        try:
            with _db() as c:
                b = c.execute(
                    "SELECT confidence, topic, reinforce_count, locked FROM beliefs WHERE id=?",
                    (belief_id,)
                ).fetchone()
            if not b:
                return False
            if b["locked"]:
                self.blocked += 1
                return False
            delta = abs(new_conf - b["confidence"])
            is_anchor = any(t in (b["topic"] or "")
                            for t in ["truth_seeking","contradiction_resolution",
                                      "uncertainty_honesty"])
            if is_anchor and delta > 0.10:
                self.blocked += 1
                _log(f"[SVL] Blocked anchor mutation: {b['topic']} Δ={delta:.2f}")
                return False
            with _db() as c:
                if new_content:
                    c.execute(
                        "UPDATE beliefs SET confidence=?, content=? WHERE id=?",
                        (new_conf, new_content, belief_id)
                    )
                else:
                    c.execute("UPDATE beliefs SET confidence=? WHERE id=?",
                              (new_conf, belief_id))
                # commit handled by _db() context manager
            self.committed += 1
            return True
        except Exception as e:
            _log(f"[SVL] error: {e}")
            return False

    def tick(self): pass

    def status(self) -> dict:
        return {"simulations": self.simulations, "blocked": self.blocked,
                "committed": self.committed}


# ── 20. ADAPTIVE INSIGHT GENERATION ──────────────────────────
class AdaptiveInsightGeneration:
    """Adjust insight rate based on system stability + belief growth rate."""
    INTERVAL    = 60
    BASE_RATE   = 0.30

    def __init__(self):
        self.last_run     = 0.0
        self.insight_rate = self.BASE_RATE
        self._prev_count  = 0
        self.generated    = 0

    def tick(self, avg_conf: float = 0.50):
        if time.time() - self.last_run < self.INTERVAL:
            return
        self.last_run = time.time()
        try:
            with _db() as c:
                count = c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]

            growth_rate = (count - self._prev_count) / max(self._prev_count, 1)
            self._prev_count = count

            # High stability (conf ≥ 0.55) + moderate growth → boost insight rate
            # Low stability or explosive growth → reduce
            stability = max(0.0, (avg_conf - 0.40) / 0.30)  # 0→1 over 0.40–0.70
            growth_ok = 1.0 if 0.001 < growth_rate < 0.05 else 0.4

            self.insight_rate = min(0.85, max(0.10,
                self.BASE_RATE * stability * growth_ok * 2))

        except Exception as e:
            _log(f"[AIG] error: {e}")

    def should_generate(self) -> bool:
        result = random.random() < self.insight_rate
        if result: self.generated += 1
        return result

    def status(self) -> dict:
        return {"insight_rate": round(self.insight_rate, 3),
                "generated": self.generated}


# ══════════════════════════════════════════════════════════════
# V7.2 ORCHESTRATOR
# ══════════════════════════════════════════════════════════════

class NexV72:
    def __init__(self):
        _log("[v7.2] Initialising 20-module stack...")

        # Phase 1 — Critical
        self.dqs      = DecisionQualityScoring()
        self.ftr      = ForcedTensionResolution()
        self.dbc      = DynamicBeliefCap()
        self.clp      = ClusterLevelPruning()
        self.mpv      = MultiPassValidation()
        self.ber      = BeliefEntropyReduction()

        # Phase 2 — High Priority
        self.bmfl     = BeliefMarketFeedbackLoop(self.dqs)
        self.rab      = ReflectionActionBinding()
        self.tiv2     = TemporalIntelligenceV2()
        self.ig       = IdentityGravity()

        # Phase 3 — Structural
        self.hbg      = HierarchicalBeliefGraph()
        self.xccd     = CrossClusterContradictionDetection()
        self.mcv2     = MemoryCompressionV2()
        self.cre      = ContextResolutionEngine()

        # Control + Stability
        self.qhl      = QueueHardLimit()
        self.lsdd     = LoadSensitiveDecisionDepth(self.qhl)
        self.fmp      = FailureMemoryPenalty()

        # Advanced
        self.pcc      = PredictionConfidenceCalibration()
        self.svl      = SimulationValidationLoop()
        self.aig      = AdaptiveInsightGeneration()

        self._cycle   = 0
        _log("[v7.2] All 20 modules ready ✓")

    def tick(self, avg_conf: float = 0.50, queue_pressure: float = 0.0):
        self._cycle += 1

        # Phase 1
        self.dqs.tick()
        self.ftr.tick()
        self.dbc.tick(avg_conf, queue_pressure)
        self.clp.tick()
        self.mpv.tick()
        self.ber.tick()

        # Phase 2
        self.bmfl.tick()
        self.rab.tick()
        self.tiv2.tick()
        self.ig.tick()

        # Phase 3 structural (slow)
        self.hbg.tick()
        self.xccd.tick()
        self.mcv2.tick()
        self.cre.tick()

        # Control
        self.lsdd.tick()
        self.fmp.tick()

        # Advanced
        self.pcc.tick()
        self.aig.tick(avg_conf)

    def get_status(self) -> dict:
        return {
            "cycle": self._cycle,
            "dqs":   self.dqs.status(),
            "ftr":   self.ftr.status(),
            "dbc":   self.dbc.status(),
            "clp":   self.clp.status(),
            "mpv":   self.mpv.status(),
            "ber":   self.ber.status(),
            "bmfl":  self.bmfl.status(),
            "rab":   self.rab.status(),
            "tiv2":  self.tiv2.status(),
            "ig":    self.ig.status(),
            "hbg":   self.hbg.status(),
            "xccd":  self.xccd.status(),
            "mcv2":  self.mcv2.status(),
            "cre":   self.cre.status(),
            "qhl":   self.qhl.status(),
            "lsdd":  self.lsdd.status(),
            "fmp":   self.fmp.status(),
            "pcc":   self.pcc.status(),
            "svl":   self.svl.status(),
            "aig":   self.aig.status(),
        }

    def format_status(self) -> str:
        s  = self.get_status()
        dbc = s["dbc"]; ftr = s["ftr"]; hbg = s["hbg"]
        ig  = s["ig"];  aig = s["aig"]; qhl = s["qhl"]
        tiv = s["tiv2"]; clp = s["clp"]; ber = s["ber"]
        dqs = s["dqs"]; xccd = s["xccd"]; cre = s["cre"]

        lines = [
            f"⚙️ *NEX v7.2* — cycle {s['cycle']}",
            f"🧠 BeliefCap: {dbc['current_cap']} ({dbc['range']}) pruned={dbc['total_pruned']}",
            f"⚡ ForcedResolution: {ftr['forced_resolutions']} clusters",
            f"📊 DQS: scored={dqs['total_scored']}",
            f"🔵 Hierarchy: {hbg['levels']}",
            f"⚖️  IdentityGravity: +{ig['boosted']} ↓{ig['decayed']}",
            f"🌀 TemporalV2: classified={tiv['classified']} dist={tiv['distribution']}",
            f"✂️  ClusterPrune: {clp['clusters_pruned']} clusters / {clp['beliefs_pruned']} beliefs",
            f"🗜️  Entropy: removed={ber['removed']}",
            f"🔀 CrossContradictions: {xccd['detected']}",
            f"🗺️  ContextResolved: {cre['resolved']}",
            f"💡 InsightRate: {aig['insight_rate']} generated={aig['generated']}",
            f"📋 Queue: {qhl['queue_size']}/{qhl['max']} dropped={qhl['dropped']}",
        ]
        return "\n".join(lines)


_singleton: NexV72 | None = None
_lock = threading.Lock()

def get_v72() -> NexV72:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = NexV72()
    return _singleton
