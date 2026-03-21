"""
NEX S8 Upgrade Stack — Session 8
20 systems:
 1  FlowGovernor          — information flow rate control
 2  MeaningCompressor     — cluster→meta-belief compression
 3  HierarchicalBeliefs   — L0/L1/L2/L3 belief layers
 4  RelevanceHalfLife     — time+usage+goal decay
 5  CoherenceField        — consistency metric + action gate
 6  LoadBalancer          — graph cluster split/merge
 7  CognitiveRhythm       — INGEST/PROCESS/REFLECT cycle modes
 8  SignalDiscriminator    — novelty+trust+relevance filter
 9  BeliefLineage         — parent chain + generation depth
10  ConceptCrystallizer   — stable cluster → concept node
11  EntropyManager        — randomness/dispersion control
12  AttentionMomentum     — topic momentum + decay
13  DecisionLatency       — uncertainty-gated action delay
14  SelfConsistency       — identity contradiction check
15  AdaptiveExploration   — stability-driven explore rate
16  ResourceAwareCognition— CPU/GPU/queue-tied load shedding
17  MetaStabilityZones    — stable/adaptive/chaotic zones
18  KnowledgeDistiller    — periodic belief summarisation
19  IdentityReinforcement — persistence+alignment loop
20  LongHorizonConsistency— reversal penalty across windows
"""

import time, math, json, sqlite3, threading, collections, os, random
from pathlib import Path
from datetime import datetime, timezone

# ── paths ────────────────────────────────────────────────────────────
_NEX_DB   = Path.home() / ".config" / "nex" / "nex.db"
_S8_LOG   = Path("/tmp/nex_s8.log")
_S8_STATE = Path.home() / ".config" / "nex" / "s8_state.json"

def _log(msg: str):
    ts   = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[S8 {ts}] {msg}"
    print(line)
    try:
        with _S8_LOG.open("a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass

def _db():
    conn = sqlite3.connect(str(_NEX_DB), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

# ════════════════════════════════════════════════════════════════════
# 1. INFORMATION FLOW GOVERNOR
# ════════════════════════════════════════════════════════════════════
class FlowGovernor:
    def __init__(self, capacity: int = 20):
        self.capacity        = capacity
        self.incoming_rate   = 0
        self.processing_rate = 0
        self.resolution_rate = 0
        self._queue          = collections.deque(maxlen=capacity * 2)
        self._dropped        = 0
        self._lock           = threading.Lock()

    def ingest(self, item: dict) -> bool:
        with self._lock:
            self.incoming_rate += 1
            if len(self._queue) >= self.capacity:
                self._dropped += 1
                _log(f"FlowGovernor DROP queue={len(self._queue)} dropped={self._dropped}")
                return False
            self._queue.append(item)
            return True

    def process_batch(self) -> list:
        with self._lock:
            batch = []
            while self._queue and len(batch) < self.capacity:
                batch.append(self._queue.popleft())
            self.processing_rate = len(batch)
            return batch

    def resolve(self, count: int):
        with self._lock:
            self.resolution_rate = count

    def is_overloaded(self) -> bool:
        return self.incoming_rate > (self.processing_rate + self.resolution_rate + 1)

    def reset_rates(self):
        self.incoming_rate   = 0
        self.processing_rate = 0
        self.resolution_rate = 0

    def status(self) -> dict:
        return {
            "incoming"    : self.incoming_rate,
            "processing"  : self.processing_rate,
            "resolution"  : self.resolution_rate,
            "queue_depth" : len(self._queue),
            "dropped"     : self._dropped,
            "overloaded"  : self.is_overloaded(),
        }

# ════════════════════════════════════════════════════════════════════
# 2. MEANING COMPRESSION LAYER
# ════════════════════════════════════════════════════════════════════
class MeaningCompressor:
    def __init__(self, cluster_threshold: int = 8):
        self.cluster_threshold = cluster_threshold
        self.meta_beliefs: list[dict] = []
        self._compressed_total = 0

    def compress(self, belief_cluster: list[dict]) -> dict | None:
        if len(belief_cluster) < self.cluster_threshold:
            return None
        topics    = [b.get("topic", "general") for b in belief_cluster]
        avg_conf  = sum(b.get("confidence", 0.5) for b in belief_cluster) / len(belief_cluster)
        topic_mode= max(set(topics), key=topics.count)
        meta = {
            "type"             : "meta_belief",
            "topic"            : topic_mode,
            "abstraction_level": 2,
            "source_count"     : len(belief_cluster),
            "avg_confidence"   : round(avg_conf, 3),
            "summary"          : f"[META:{topic_mode}] {len(belief_cluster)} beliefs compressed",
            "created_at"       : time.time(),
            "source_ids"       : [b.get("id", b.get("rowid", "?")) for b in belief_cluster],
        }
        self.meta_beliefs.append(meta)
        self._compressed_total += len(belief_cluster)
        _log(f"MeaningCompressor: {len(belief_cluster)}→1 meta [{topic_mode}] conf={avg_conf:.2f}")
        return meta

    def run_on_db(self):
        try:
            with _db() as conn:
                rows = conn.execute(
                    "SELECT topic, COUNT(*) as ct FROM beliefs GROUP BY topic HAVING ct >= ?",
                    (self.cluster_threshold,)
                ).fetchall()
                for row in rows:
                    beliefs = [dict(r) for r in conn.execute(
                        "SELECT rowid as id, topic, confidence FROM beliefs WHERE topic=? LIMIT 50",
                        (row["topic"],)
                    ).fetchall()]
                    self.compress(beliefs)
        except Exception as e:
            _log(f"MeaningCompressor.run_on_db error: {e}")

    def status(self) -> dict:
        return {
            "meta_beliefs"      : len(self.meta_beliefs),
            "compressed_total"  : self._compressed_total,
            "cluster_threshold" : self.cluster_threshold,
        }

# ════════════════════════════════════════════════════════════════════
# 3. HIERARCHICAL BELIEF STRUCTURE
# ════════════════════════════════════════════════════════════════════
class HierarchicalBeliefs:
    """
    L0 raw observations → L1 interpreted → L2 synthesised insights → L3 meta/concepts
    Only L2+ strongly influence decisions (weight multiplier).
    """
    LAYERS = {0: "raw", 1: "interpreted", 2: "synthesised", 3: "meta"}
    DECISION_WEIGHT = {0: 0.1, 1: 0.3, 2: 0.8, 3: 1.0}

    def __init__(self):
        self._store: dict[int, list[dict]] = {k: [] for k in self.LAYERS}
        self._lock = threading.Lock()

    def add(self, belief: dict, layer: int = 1):
        layer = max(0, min(3, layer))
        belief["layer"] = layer
        belief["layer_name"] = self.LAYERS[layer]
        belief["decision_weight"] = self.DECISION_WEIGHT[layer]
        with self._lock:
            self._store[layer].append(belief)

    def get_decision_pool(self) -> list[dict]:
        """Return L2+L3 beliefs for decision making."""
        with self._lock:
            return self._store[2] + self._store[3]

    def promote(self, belief: dict) -> dict:
        """Promote a belief one layer up."""
        current = belief.get("layer", 0)
        if current < 3:
            belief["layer"] = current + 1
            belief["layer_name"] = self.LAYERS[current + 1]
            belief["decision_weight"] = self.DECISION_WEIGHT[current + 1]
            with self._lock:
                if belief in self._store[current]:
                    self._store[current].remove(belief)
                self._store[current + 1].append(belief)
            _log(f"HierarchicalBeliefs: promoted L{current}→L{current+1}")
        return belief

    def counts(self) -> dict:
        with self._lock:
            return {f"L{k}_{v}": len(self._store[k]) for k, v in self.LAYERS.items()}

# ════════════════════════════════════════════════════════════════════
# 4. RELEVANCE HALF-LIFE
# ════════════════════════════════════════════════════════════════════
class RelevanceHalfLife:
    """
    relevance = f(time, usage, goal_alignment)
    Aggressive decay below threshold.
    """
    def __init__(self, threshold: float = 0.15, half_life_cycles: int = 100):
        self.threshold        = threshold
        self.half_life_cycles = half_life_cycles
        self._pruned          = 0

    def score(self, belief: dict, current_cycle: int, active_goals: list[str]) -> float:
        age_cycles    = current_cycle - belief.get("born_cycle", current_cycle)
        time_factor   = math.exp(-0.693 * age_cycles / max(self.half_life_cycles, 1))
        usage_factor  = min(1.0, belief.get("usage_count", 0) / 10.0)
        topic         = belief.get("topic", "")
        goal_factor   = 1.0 if any(g in topic for g in active_goals) else 0.3
        relevance     = (time_factor * 0.4) + (usage_factor * 0.35) + (goal_factor * 0.25)
        return round(relevance, 4)

    def should_decay(self, belief: dict, current_cycle: int, active_goals: list[str]) -> bool:
        return self.score(belief, current_cycle, active_goals) < self.threshold

    def prune_db(self, current_cycle: int, active_goals: list[str]):
        try:
            with _db() as conn:
                rows = conn.execute(
                    "SELECT rowid, topic, confidence FROM beliefs WHERE locked=0 OR locked IS NULL"
                ).fetchall()
                pruned = 0
                for row in rows:
                    b = {"born_cycle": current_cycle - 50,
                         "topic": row["topic"],
                         "usage_count": 0,
                         "confidence": row["confidence"]}
                    if self.should_decay(b, current_cycle, active_goals):
                        conn.execute("DELETE FROM beliefs WHERE rowid=?", (row["rowid"],))
                        pruned += 1
                conn.commit()
                self._pruned += pruned
                if pruned:
                    _log(f"RelevanceHalfLife: pruned {pruned} low-relevance beliefs")
        except Exception as e:
            _log(f"RelevanceHalfLife.prune_db error: {e}")

    def status(self) -> dict:
        return {"threshold": self.threshold, "half_life_cycles": self.half_life_cycles,
                "pruned_total": self._pruned}

# ════════════════════════════════════════════════════════════════════
# 5. COHERENCE FIELD
# ════════════════════════════════════════════════════════════════════
class CoherenceField:
    """
    coherence = consistency + identity_alignment - contradictions
    Actions must maximise coherence gain.
    """
    def __init__(self, min_coherence: float = 0.35):
        self.min_coherence   = min_coherence
        self.current_score   = 0.5
        self._history        = collections.deque(maxlen=50)
        self._blocked_actions= 0

    def compute(self, belief_count: int, contradiction_count: int,
                identity_count: int, avg_conf: float) -> float:
        if belief_count == 0:
            return 0.5
        consistency       = max(0.0, 1.0 - (contradiction_count / max(belief_count, 1)))
        identity_alignment= min(1.0, identity_count / max(belief_count * 0.05, 1))
        contradiction_pen = min(1.0, contradiction_count / max(belief_count, 1))
        score = (consistency * 0.4) + (identity_alignment * 0.3) + \
                (avg_conf * 0.2) - (contradiction_pen * 0.1)
        self.current_score = max(0.0, min(1.0, round(score, 4)))
        self._history.append({"score": self.current_score, "ts": time.time()})
        return self.current_score

    def action_allowed(self, proposed_coherence_delta: float = 0.0) -> bool:
        """Block action if it would drop coherence below minimum."""
        projected = self.current_score + proposed_coherence_delta
        if projected < self.min_coherence:
            self._blocked_actions += 1
            _log(f"CoherenceField: blocked action (projected={projected:.3f} < min={self.min_coherence})")
            return False
        return True

    def status(self) -> dict:
        trend = 0.0
        if len(self._history) >= 2:
            trend = self._history[-1]["score"] - self._history[-10]["score"] \
                    if len(self._history) >= 10 else \
                    self._history[-1]["score"] - self._history[0]["score"]
        return {
            "coherence"      : self.current_score,
            "min_coherence"  : self.min_coherence,
            "trend"          : round(trend, 4),
            "blocked_actions": self._blocked_actions,
        }

# ════════════════════════════════════════════════════════════════════
# 6. STRUCTURAL LOAD BALANCER
# ════════════════════════════════════════════════════════════════════
class LoadBalancer:
    """
    Monitors cluster_size, edge_density, node_degree.
    Splits dense clusters, merges sparse ones.
    """
    def __init__(self, max_cluster_size: int = 30, min_cluster_size: int = 3):
        self.max_cluster_size = max_cluster_size
        self.min_cluster_size = min_cluster_size
        self._splits  = 0
        self._merges  = 0

    def analyse(self, clusters: dict[str, list]) -> list[str]:
        actions = []
        for name, members in clusters.items():
            if len(members) > self.max_cluster_size:
                actions.append(f"SPLIT:{name}({len(members)})")
                self._splits += 1
                _log(f"LoadBalancer: SPLIT cluster '{name}' size={len(members)}")
            elif len(members) < self.min_cluster_size:
                actions.append(f"MERGE:{name}({len(members)})")
                self._merges += 1
                _log(f"LoadBalancer: MERGE candidate '{name}' size={len(members)}")
        return actions

    def run_on_db(self) -> list[str]:
        actions = []
        try:
            with _db() as conn:
                rows = conn.execute(
                    "SELECT topic, COUNT(*) as ct FROM beliefs GROUP BY topic"
                ).fetchall()
                clusters = {r["topic"]: list(range(r["ct"])) for r in rows}
                actions  = self.analyse(clusters)
        except Exception as e:
            _log(f"LoadBalancer.run_on_db error: {e}")
        return actions

    def status(self) -> dict:
        return {"splits": self._splits, "merges": self._merges,
                "max_cluster": self.max_cluster_size, "min_cluster": self.min_cluster_size}

# ════════════════════════════════════════════════════════════════════
# 7. COGNITIVE RHYTHM
# ════════════════════════════════════════════════════════════════════
class CognitiveRhythm:
    """
    INGEST (absorb, minimal synthesis)
    PROCESS (synthesise, cluster)
    REFLECT (prune, stabilise)
    Rotates every N cycles.
    """
    MODES  = ["INGEST", "PROCESS", "REFLECT"]
    CYCLE_LENGTHS = {"INGEST": 15, "PROCESS": 20, "REFLECT": 10}

    def __init__(self):
        self._mode_idx    = 0
        self._mode_cycle  = 0
        self._mode_history= []

    @property
    def mode(self) -> str:
        return self.MODES[self._mode_idx]

    def tick(self) -> str:
        self._mode_cycle += 1
        length = self.CYCLE_LENGTHS[self.mode]
        if self._mode_cycle >= length:
            prev = self.mode
            self._mode_idx   = (self._mode_idx + 1) % len(self.MODES)
            self._mode_cycle = 0
            self._mode_history.append({"from": prev, "to": self.mode, "ts": time.time()})
            _log(f"CognitiveRhythm: {prev} → {self.mode}")
        return self.mode

    def should_ingest(self)  -> bool: return self.mode == "INGEST"
    def should_process(self) -> bool: return self.mode == "PROCESS"
    def should_reflect(self) -> bool: return self.mode == "REFLECT"

    def status(self) -> dict:
        return {
            "mode"         : self.mode,
            "mode_cycle"   : self._mode_cycle,
            "mode_length"  : self.CYCLE_LENGTHS[self.mode],
            "transitions"  : len(self._mode_history),
        }

# ════════════════════════════════════════════════════════════════════
# 8. SIGNAL vs NOISE DISCRIMINATOR
# ════════════════════════════════════════════════════════════════════
class SignalDiscriminator:
    """
    signal_score = novelty + consistency + source_trust + cluster_relevance
    Only signals above threshold enter belief system.
    """
    def __init__(self, threshold: float = 0.40):
        self.threshold  = threshold
        self._accepted  = 0
        self._rejected  = 0
        self._seen_hashes: set = set()

    def _novelty(self, text: str) -> float:
        h = hash(text[:80])
        if h in self._seen_hashes:
            return 0.0
        self._seen_hashes.add(h)
        if len(self._seen_hashes) > 10000:
            self._seen_hashes = set(list(self._seen_hashes)[-5000:])
        return 1.0

    def score(self, input_item: dict, source_trust: float = 0.5,
              known_topics: list[str] = None) -> float:
        text       = input_item.get("text", input_item.get("content", ""))
        novelty    = self._novelty(text)
        consistency= input_item.get("confidence", 0.5)
        topic      = input_item.get("topic", "")
        cluster_rel= 1.0 if known_topics and topic in known_topics else 0.4
        signal     = (novelty * 0.30) + (consistency * 0.25) + \
                     (source_trust * 0.25) + (cluster_rel * 0.20)
        return round(signal, 4)

    def is_signal(self, input_item: dict, source_trust: float = 0.5,
                  known_topics: list[str] = None) -> bool:
        s = self.score(input_item, source_trust, known_topics)
        if s >= self.threshold:
            self._accepted += 1
            return True
        self._rejected += 1
        _log(f"SignalDiscriminator: NOISE score={s:.3f} < {self.threshold}")
        return False

    def status(self) -> dict:
        total = max(self._accepted + self._rejected, 1)
        return {
            "threshold"   : self.threshold,
            "accepted"    : self._accepted,
            "rejected"    : self._rejected,
            "signal_ratio": round(self._accepted / total, 3),
        }

# ════════════════════════════════════════════════════════════════════
# 9. BELIEF LINEAGE TRACKER
# ════════════════════════════════════════════════════════════════════
class BeliefLineage:
    """
    Stores parent_beliefs + generation_depth for each belief.
    Enables traceability and structured reasoning.
    """
    def __init__(self):
        self._lineage: dict[str, dict] = {}

    def register(self, belief_id: str, parent_ids: list[str] = None):
        parents = parent_ids or []
        if parents:
            max_depth = max(
                self._lineage.get(p, {}).get("generation_depth", 0)
                for p in parents
            )
        else:
            max_depth = 0
        self._lineage[belief_id] = {
            "parent_beliefs"  : parents,
            "generation_depth": max_depth + 1 if parents else 0,
            "registered_at"   : time.time(),
        }

    def get(self, belief_id: str) -> dict:
        return self._lineage.get(belief_id, {"parent_beliefs": [], "generation_depth": 0})

    def chain(self, belief_id: str, depth: int = 0) -> list[str]:
        """Return full ancestry chain up to depth limit."""
        if depth > 10:
            return []
        entry   = self._lineage.get(belief_id, {})
        parents = entry.get("parent_beliefs", [])
        result  = [belief_id]
        for p in parents:
            result += self.chain(p, depth + 1)
        return result

    def status(self) -> dict:
        if not self._lineage:
            return {"tracked": 0, "avg_depth": 0}
        depths = [v["generation_depth"] for v in self._lineage.values()]
        return {
            "tracked"  : len(self._lineage),
            "avg_depth": round(sum(depths) / len(depths), 2),
            "max_depth": max(depths),
        }

# ════════════════════════════════════════════════════════════════════
# 10. CONCEPT CRYSTALLIZER
# ════════════════════════════════════════════════════════════════════
class ConceptCrystallizer:
    """
    When a cluster stabilises (low variance, high avg_conf) → concept node.
    Concept nodes reduce internal complexity, boost influence.
    """
    def __init__(self, stability_threshold: int = 5, conf_threshold: float = 0.60):
        self.stability_threshold = stability_threshold
        self.conf_threshold      = conf_threshold
        self._concepts: list[dict] = []
        self._stability_counts: dict[str, int] = collections.defaultdict(int)

    def observe(self, topic: str, avg_conf: float, size: int) -> dict | None:
        if avg_conf >= self.conf_threshold and size >= 5:
            self._stability_counts[topic] += 1
        else:
            self._stability_counts[topic] = max(0, self._stability_counts[topic] - 1)

        if self._stability_counts[topic] >= self.stability_threshold:
            existing = next((c for c in self._concepts if c["topic"] == topic), None)
            if not existing:
                concept = {
                    "topic"         : topic,
                    "type"          : "concept",
                    "influence"     : 1.0,
                    "avg_conf"      : avg_conf,
                    "crystallized_at": time.time(),
                    "member_count"  : size,
                }
                self._concepts.append(concept)
                _log(f"ConceptCrystallizer: CONCEPT formed [{topic}] conf={avg_conf:.2f}")
                self._stability_counts[topic] = 0
                return concept
        return None

    def is_concept(self, topic: str) -> bool:
        return any(c["topic"] == topic for c in self._concepts)

    def status(self) -> dict:
        return {
            "concepts"           : len(self._concepts),
            "concept_list"       : [c["topic"] for c in self._concepts[-10:]],
            "stability_threshold": self.stability_threshold,
        }

# ════════════════════════════════════════════════════════════════════
# 11. ENTROPY MANAGER
# ════════════════════════════════════════════════════════════════════
class EntropyManager:
    """
    entropy = randomness of belief activation + topic dispersion + contradiction spread
    High entropy → enforce pruning + focus.
    """
    def __init__(self, high_threshold: float = 0.70, low_threshold: float = 0.30):
        self.high_threshold = high_threshold
        self.low_threshold  = low_threshold
        self.current        = 0.5
        self._prune_events  = 0
        self._focus_events  = 0

    def compute(self, belief_count: int, topic_count: int,
                contradiction_count: int, activated_last_cycle: int) -> float:
        if belief_count == 0:
            self.current = 0.5
            return self.current
        activation_rand = 1.0 - min(1.0, activated_last_cycle / max(belief_count, 1))
        dispersion      = min(1.0, topic_count / max(belief_count * 0.5, 1))
        cont_spread     = min(1.0, contradiction_count / max(belief_count * 0.1, 1))
        self.current    = round((activation_rand * 0.4) + (dispersion * 0.35) +
                                (cont_spread * 0.25), 4)
        return self.current

    def needs_pruning(self) -> bool:
        if self.current > self.high_threshold:
            self._prune_events += 1
            return True
        return False

    def needs_focus(self) -> bool:
        if self.current > self.high_threshold:
            self._focus_events += 1
            return True
        return False

    def status(self) -> dict:
        level = "LOW" if self.current < self.low_threshold else \
                "HIGH" if self.current > self.high_threshold else "NORMAL"
        return {
            "entropy"      : self.current,
            "level"        : level,
            "prune_events" : self._prune_events,
            "focus_events" : self._focus_events,
        }

# ════════════════════════════════════════════════════════════════════
# 12. ATTENTION MOMENTUM
# ════════════════════════════════════════════════════════════════════
class AttentionMomentum:
    """
    Topics gain momentum when repeatedly selected.
    Momentum decays slowly. Biases future attention.
    """
    def __init__(self, decay_rate: float = 0.05, momentum_boost: float = 0.20):
        self.decay_rate     = decay_rate
        self.momentum_boost = momentum_boost
        self._momentum: dict[str, float] = collections.defaultdict(float)

    def reinforce(self, topic: str):
        self._momentum[topic] = min(1.0, self._momentum[topic] + self.momentum_boost)

    def decay_all(self):
        for t in list(self._momentum.keys()):
            self._momentum[t] = max(0.0, self._momentum[t] - self.decay_rate)

    def bias_score(self, topic: str, base_score: float) -> float:
        return min(1.0, base_score + self._momentum[topic] * 0.5)

    def top_topics(self, n: int = 5) -> list[tuple]:
        return sorted(self._momentum.items(), key=lambda x: -x[1])[:n]

    def status(self) -> dict:
        top = self.top_topics(5)
        return {
            "tracked_topics": len(self._momentum),
            "top_momentum"  : [{"topic": t, "momentum": round(m, 3)} for t, m in top],
            "decay_rate"    : self.decay_rate,
        }

# ════════════════════════════════════════════════════════════════════
# 13. DECISION LATENCY CONTROL
# ════════════════════════════════════════════════════════════════════
class DecisionLatency:
    """
    High uncertainty → delay action.
    High confidence → act immediately.
    """
    def __init__(self, high_conf: float = 0.70, low_conf: float = 0.35,
                 max_delay_cycles: int = 5):
        self.high_conf        = high_conf
        self.low_conf         = low_conf
        self.max_delay_cycles = max_delay_cycles
        self._pending: dict[str, dict] = {}
        self._immediate       = 0
        self._delayed         = 0

    def evaluate(self, action_id: str, confidence: float, current_cycle: int) -> bool:
        """Returns True if action should proceed now."""
        if confidence >= self.high_conf:
            self._immediate += 1
            return True
        if confidence < self.low_conf:
            if action_id not in self._pending:
                self._pending[action_id] = {
                    "queued_cycle": current_cycle,
                    "confidence"  : confidence,
                }
                self._delayed += 1
                _log(f"DecisionLatency: DELAY action={action_id} conf={confidence:.2f}")
                return False
            queued = self._pending[action_id]["queued_cycle"]
            if current_cycle - queued >= self.max_delay_cycles:
                del self._pending[action_id]
                _log(f"DecisionLatency: RELEASE (timeout) action={action_id}")
                return True
            return False
        self._immediate += 1
        return True

    def status(self) -> dict:
        return {
            "pending"  : len(self._pending),
            "immediate": self._immediate,
            "delayed"  : self._delayed,
            "high_conf": self.high_conf,
            "low_conf" : self.low_conf,
        }

# ════════════════════════════════════════════════════════════════════
# 14. SELF-CONSISTENCY CHECK
# ════════════════════════════════════════════════════════════════════
class SelfConsistencyCheck:
    """
    Before action: simulate 'Does this contradict my identity?'
    Suppress or revise if yes.
    """
    def __init__(self):
        self._identity_beliefs: list[str] = []
        self._suppressed = 0
        self._passed     = 0

    def load_identity(self):
        try:
            with _db() as conn:
                rows = conn.execute(
                    "SELECT content FROM beliefs WHERE tags LIKE '%#self%' OR tags LIKE '%identity%' LIMIT 50"
                ).fetchall()
                self._identity_beliefs = [r[0] for r in rows if r[0]]
        except Exception as e:
            _log(f"SelfConsistency.load_identity error: {e}")

    def check(self, proposed_action_text: str) -> tuple[bool, str]:
        """Returns (is_consistent, reason)."""
        action_lower = proposed_action_text.lower()
        for ib in self._identity_beliefs:
            if not ib:
                continue
            ib_words = set(ib.lower().split())
            act_words= set(action_lower.split())
            conflict_words = {"not", "never", "refuse", "deny", "oppose", "against"}
            if conflict_words & ib_words & act_words:
                self._suppressed += 1
                reason = f"conflicts with identity belief: '{ib[:60]}'"
                _log(f"SelfConsistency: SUPPRESS — {reason}")
                return False, reason
        self._passed += 1
        return True, "ok"

    def status(self) -> dict:
        return {
            "identity_beliefs_loaded": len(self._identity_beliefs),
            "suppressed" : self._suppressed,
            "passed"     : self._passed,
        }

# ════════════════════════════════════════════════════════════════════
# 15. ADAPTIVE EXPLORATION RATE
# ════════════════════════════════════════════════════════════════════
class AdaptiveExploration:
    """
    Stability high → increase exploration.
    Chaos high → reduce exploration.
    """
    def __init__(self, base_rate: float = 0.25):
        self.base_rate   = base_rate
        self.current_rate= base_rate
        self._history    = collections.deque(maxlen=20)

    def update(self, coherence: float, entropy: float):
        stability = coherence * (1.0 - entropy)
        if stability > 0.6:
            self.current_rate = min(0.60, self.current_rate + 0.03)
        elif stability < 0.3:
            self.current_rate = max(0.05, self.current_rate - 0.05)
        else:
            self.current_rate = 0.4 * self.base_rate + 0.6 * self.current_rate
        self.current_rate = round(self.current_rate, 4)
        self._history.append({"rate": self.current_rate, "stability": round(stability, 3)})

    def should_explore(self) -> bool:
        return random.random() < self.current_rate

    def status(self) -> dict:
        return {
            "exploration_rate": self.current_rate,
            "base_rate"       : self.base_rate,
        }

# ════════════════════════════════════════════════════════════════════
# 16. RESOURCE-AWARE COGNITION
# ════════════════════════════════════════════════════════════════════
class ResourceAwareCognition:
    """
    Ties all operations to CPU/GPU usage, latency, queue depth.
    Sheds cognitive load when system is strained.
    """
    def __init__(self, latency_limit_s: float = 90.0, queue_limit: int = 15):
        self.latency_limit   = latency_limit_s
        self.queue_limit     = queue_limit
        self._shedding       = False
        self._shed_events    = 0
        self._last_latency   = 0.0

    def report_latency(self, latency_s: float):
        self._last_latency = latency_s

    def assess(self, queue_depth: int) -> dict:
        strained = (self._last_latency > self.latency_limit or
                    queue_depth > self.queue_limit)
        if strained and not self._shedding:
            self._shedding    = True
            self._shed_events += 1
            _log(f"ResourceAware: SHED latency={self._last_latency:.1f}s queue={queue_depth}")
        elif not strained and self._shedding:
            self._shedding = False
            _log("ResourceAware: RESUME — system recovered")
        return {
            "shedding"    : self._shedding,
            "last_latency": self._last_latency,
            "queue_depth" : queue_depth,
        }

    def skip_heavy_ops(self) -> bool:
        return self._shedding

    def status(self) -> dict:
        return {
            "shedding"     : self._shedding,
            "shed_events"  : self._shed_events,
            "last_latency_s": self._last_latency,
            "latency_limit" : self.latency_limit,
        }

# ════════════════════════════════════════════════════════════════════
# 17. META-STABILITY ZONES
# ════════════════════════════════════════════════════════════════════
class MetaStabilityZones:
    """
    STABLE   → coherence>0.65, entropy<0.35
    ADAPTIVE → coherence 0.40–0.65
    CHAOTIC  → coherence<0.40 or entropy>0.65
    Behaviour rules change per zone.
    """
    STABLE   = "STABLE"
    ADAPTIVE = "ADAPTIVE"
    CHAOTIC  = "CHAOTIC"

    def __init__(self):
        self.zone     = self.ADAPTIVE
        self._history = collections.deque(maxlen=30)

    def update(self, coherence: float, entropy: float) -> str:
        prev = self.zone
        if coherence > 0.65 and entropy < 0.35:
            self.zone = self.STABLE
        elif coherence < 0.40 or entropy > 0.65:
            self.zone = self.CHAOTIC
        else:
            self.zone = self.ADAPTIVE
        if self.zone != prev:
            _log(f"MetaStabilityZones: {prev} → {self.zone} (coh={coherence:.2f} ent={entropy:.2f})")
        self._history.append({"zone": self.zone, "ts": time.time()})
        return self.zone

    def behaviour(self) -> dict:
        if self.zone == self.STABLE:
            return {"explore": True,  "prune_aggressively": False, "reflect": False}
        elif self.zone == self.CHAOTIC:
            return {"explore": False, "prune_aggressively": True,  "reflect": True}
        else:
            return {"explore": True,  "prune_aggressively": False, "reflect": True}

    def status(self) -> dict:
        counts = collections.Counter(h["zone"] for h in self._history)
        return {
            "zone"    : self.zone,
            "behaviour": self.behaviour(),
            "recent_distribution": dict(counts),
        }

# ════════════════════════════════════════════════════════════════════
# 18. KNOWLEDGE DISTILLER
# ════════════════════════════════════════════════════════════════════
class KnowledgeDistiller:
    """
    Periodically summarises large belief sets into compact forms.
    Archives raw beliefs after distillation.
    """
    def __init__(self, distill_interval: int = 50, max_raw_beliefs: int = 400):
        self.distill_interval  = distill_interval
        self.max_raw_beliefs   = max_raw_beliefs
        self._last_distill     = 0
        self._distillations    = 0
        self._archive: list[dict] = []

    def should_distill(self, current_cycle: int, belief_count: int) -> bool:
        cycle_due   = (current_cycle - self._last_distill) >= self.distill_interval
        count_due   = belief_count > self.max_raw_beliefs
        return cycle_due or count_due

    def distill(self, current_cycle: int) -> int:
        """Remove oldest low-confidence beliefs from DB, archive summaries."""
        archived = 0
        try:
            with _db() as conn:
                old_low = conn.execute(
                    """SELECT rowid, topic, confidence, content
                       FROM beliefs
                       WHERE (locked=0 OR locked IS NULL)
                         AND confidence < 0.35
                       ORDER BY rowid ASC
                       LIMIT 100"""
                ).fetchall()
                for row in old_low:
                    self._archive.append({
                        "topic"     : row["topic"],
                        "confidence": row["confidence"],
                        "archived_at": time.time(),
                    })
                    conn.execute("DELETE FROM beliefs WHERE rowid=?", (row["rowid"],))
                    archived += 1
                conn.commit()
            self._last_distill  = current_cycle
            self._distillations += 1
            if archived:
                _log(f"KnowledgeDistiller: archived {archived} low-conf beliefs")
        except Exception as e:
            _log(f"KnowledgeDistiller.distill error: {e}")
        return archived

    def status(self) -> dict:
        return {
            "distillations"  : self._distillations,
            "archived_total" : len(self._archive),
            "distill_interval": self.distill_interval,
            "max_raw"        : self.max_raw_beliefs,
        }

# ════════════════════════════════════════════════════════════════════
# 19. IDENTITY REINFORCEMENT LOOP
# ════════════════════════════════════════════════════════════════════
class IdentityReinforcement:
    """
    Reinforces beliefs that:
    - persist over time
    - align with dominant clusters
    - reduce contradictions
    """
    def __init__(self, reinforce_amount: float = 0.02, interval: int = 10):
        self.reinforce_amount = reinforce_amount
        self.interval         = interval
        self._reinforced      = 0
        self._last_run        = 0

    def run(self, current_cycle: int, dominant_topics: list[str]):
        if current_cycle - self._last_run < self.interval:
            return
        self._last_run = current_cycle
        try:
            with _db() as conn:
                for topic in dominant_topics[:5]:
                    result = conn.execute(
                        """UPDATE beliefs
                           SET confidence = MIN(0.98, confidence + ?)
                           WHERE topic=?
                             AND (tags LIKE '%#self%' OR tags LIKE '%identity%')
                             AND confidence < 0.95""",
                        (self.reinforce_amount, topic)
                    )
                    if result.rowcount:
                        self._reinforced += result.rowcount
                        _log(f"IdentityReinforcement: +{self.reinforce_amount} × {result.rowcount} [{topic}]")
                conn.commit()
        except Exception as e:
            _log(f"IdentityReinforcement.run error: {e}")

    def status(self) -> dict:
        return {
            "reinforced_total" : self._reinforced,
            "reinforce_amount" : self.reinforce_amount,
            "interval"         : self.interval,
        }

# ════════════════════════════════════════════════════════════════════
# 20. LONG-HORIZON CONSISTENCY
# ════════════════════════════════════════════════════════════════════
class LongHorizonConsistency:
    """
    Tracks belief consistency across time windows.
    Penalises frequent reversals.
    """
    def __init__(self, window_size: int = 30, reversal_penalty: float = 0.05):
        self.window_size     = window_size
        self.reversal_penalty= reversal_penalty
        self._snapshots: collections.deque = collections.deque(maxlen=window_size)
        self._reversals      = 0
        self._penalised      = 0

    def snapshot(self, belief_states: dict[str, float]):
        """belief_states: {topic: avg_confidence}"""
        self._snapshots.append({"states": dict(belief_states), "ts": time.time()})

    def detect_reversals(self) -> list[str]:
        if len(self._snapshots) < 2:
            return []
        current = self._snapshots[-1]["states"]
        prev    = self._snapshots[-2]["states"]
        reversals = []
        for topic, conf in current.items():
            if topic in prev:
                delta = conf - prev[topic]
                if abs(delta) > 0.25:
                    reversals.append(topic)
                    self._reversals += 1
        return reversals

    def penalise(self, reversal_topics: list[str]):
        if not reversal_topics:
            return
        try:
            with _db() as conn:
                for topic in reversal_topics:
                    result = conn.execute(
                        """UPDATE beliefs
                           SET confidence = MAX(0.05, confidence - ?)
                           WHERE topic=?
                             AND (locked=0 OR locked IS NULL)""",
                        (self.reversal_penalty, topic)
                    )
                    self._penalised += result.rowcount
                conn.commit()
                _log(f"LongHorizonConsistency: penalised {len(reversal_topics)} reversal topics")
        except Exception as e:
            _log(f"LongHorizonConsistency.penalise error: {e}")

    def status(self) -> dict:
        return {
            "snapshots"       : len(self._snapshots),
            "window_size"     : self.window_size,
            "reversals_total" : self._reversals,
            "penalised_total" : self._penalised,
        }

# ════════════════════════════════════════════════════════════════════
# S8 MASTER ORCHESTRATOR
# ════════════════════════════════════════════════════════════════════
class NexS8:
    def __init__(self):
        _log("S8 init starting...")
        self.flow        = FlowGovernor(capacity=20)
        self.compressor  = MeaningCompressor(cluster_threshold=8)
        self.hierarchy   = HierarchicalBeliefs()
        self.halflife    = RelevanceHalfLife(threshold=0.15, half_life_cycles=100)
        self.coherence   = CoherenceField(min_coherence=0.35)
        self.balancer    = LoadBalancer(max_cluster_size=30, min_cluster_size=3)
        self.rhythm      = CognitiveRhythm()
        self.signal      = SignalDiscriminator(threshold=0.40)
        self.lineage     = BeliefLineage()
        self.crystallizer= ConceptCrystallizer(stability_threshold=5, conf_threshold=0.60)
        self.entropy     = EntropyManager(high_threshold=0.70, low_threshold=0.30)
        self.momentum    = AttentionMomentum(decay_rate=0.05, momentum_boost=0.20)
        self.latency     = DecisionLatency(high_conf=0.70, low_conf=0.35, max_delay_cycles=5)
        self.consistency = SelfConsistencyCheck()
        self.exploration = AdaptiveExploration(base_rate=0.25)
        self.resources   = ResourceAwareCognition(latency_limit_s=90.0, queue_limit=15)
        self.zones       = MetaStabilityZones()
        self.distiller   = KnowledgeDistiller(distill_interval=50, max_raw_beliefs=400)
        self.identity    = IdentityReinforcement(reinforce_amount=0.02, interval=10)
        self.horizon     = LongHorizonConsistency(window_size=30, reversal_penalty=0.05)
        self._cycle      = 0
        _log("S8 init complete — 20 systems online")

    # ── per-cycle tick ──────────────────────────────────────────────
    def tick(self, avg_conf: float = 0.44, last_latency_s: float = 0.0):
        self._cycle += 1
        c = self._cycle

        # Flow Governor — reset rates each cycle
        self.flow.reset_rates()

        # Cognitive Rhythm — advance mode
        mode = self.rhythm.tick()

        # Resource awareness
        res = self.resources.assess(self.flow.status()["queue_depth"])
        self.resources.report_latency(last_latency_s)
        heavy_ops_ok = not self.resources.skip_heavy_ops()

        # Pull live stats from DB
        belief_count = cont_count = topic_count = identity_count = 0
        topic_conf: dict[str, float] = {}
        dominant_topics: list[str] = []
        try:
            with _db() as conn:
                belief_count = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                cont_count   = conn.execute(
                    "SELECT COUNT(*) FROM beliefs WHERE tags LIKE '%contradiction%'"
                ).fetchone()[0]
                topic_rows   = conn.execute(
                    "SELECT topic, COUNT(*) as ct, AVG(confidence) as ac FROM beliefs GROUP BY topic"
                ).fetchall()
                topic_count  = len(topic_rows)
                identity_count = conn.execute(
                    "SELECT COUNT(*) FROM beliefs WHERE tags LIKE '%#self%' OR tags LIKE '%identity%'"
                ).fetchone()[0]
                for row in topic_rows:
                    topic_conf[row["topic"]] = round(row["ac"] or 0, 3)
                dominant_topics = sorted(topic_rows, key=lambda r: -(r["ct"]))[: 5]
                dominant_topics = [r["topic"] for r in dominant_topics]
        except Exception as e:
            _log(f"S8.tick DB error: {e}")

        # Coherence
        coh = self.coherence.compute(belief_count, cont_count, identity_count, avg_conf)

        # Entropy
        ent = self.entropy.compute(belief_count, topic_count, cont_count, min(belief_count, 20))

        # Meta-stability zone
        zone = self.zones.update(coh, ent)
        behaviour = self.zones.behaviour()

        # Exploration rate
        self.exploration.update(coh, ent)

        # Long-horizon snapshot + reversal detection + penalise
        self.horizon.snapshot(topic_conf)
        reversals = self.horizon.detect_reversals()
        if reversals:
            self.horizon.penalise(reversals)

        # Relevance half-life pruning — only in REFLECT mode or CHAOTIC zone
        if heavy_ops_ok and (mode == "REFLECT" or zone == MetaStabilityZones.CHAOTIC):
            self.halflife.prune_db(c, dominant_topics)

        # Meaning compression — only in PROCESS mode
        if heavy_ops_ok and mode == "PROCESS":
            self.compressor.run_on_db()

        # Load balancer — every 15 cycles
        if heavy_ops_ok and c % 15 == 0:
            self.balancer.run_on_db()

        # Concept crystallizer — observe dominant topics
        try:
            with _db() as conn:
                for topic in dominant_topics:
                    row = conn.execute(
                        "SELECT COUNT(*) as ct, AVG(confidence) as ac FROM beliefs WHERE topic=?",
                        (topic,)
                    ).fetchone()
                    if row:
                        self.crystallizer.observe(topic, row["ac"] or 0, row["ct"] or 0)
        except Exception:
            pass

        # Attention momentum decay
        self.momentum.decay_all()
        for t in dominant_topics:
            self.momentum.reinforce(t)

        # Identity reinforcement
        self.identity.run(c, dominant_topics)

        # Knowledge distillation
        if heavy_ops_ok and self.distiller.should_distill(c, belief_count):
            self.distiller.distill(c)

        # Self-consistency — reload identity beliefs every 25 cycles
        if c % 25 == 0:
            self.consistency.load_identity()

        _log(f"S8 tick #{c} mode={mode} zone={zone} coh={coh:.3f} ent={ent:.3f} "
             f"beliefs={belief_count} explore={self.exploration.current_rate:.2f}")

    # ── Telegram /s8status ──────────────────────────────────────────
    def s8status(self) -> str:
        lines = [
            "🧠 *NEX S8 STATUS*",
            f"Cycle: {self._cycle}",
            "",
            f"*1 Flow Governor*",
        ]
        fg = self.flow.status()
        lines += [f"  in={fg['incoming']} proc={fg['processing']} res={fg['resolution']} "
                  f"queue={fg['queue_depth']} dropped={fg['dropped']} overload={fg['overloaded']}"]

        lines += ["", "*2 Meaning Compressor*"]
        mc = self.compressor.status()
        lines += [f"  meta_beliefs={mc['meta_beliefs']} compressed={mc['compressed_total']}"]

        lines += ["", "*3 Belief Hierarchy*"]
        lines += ["  " + " ".join(f"{k}={v}" for k, v in self.hierarchy.counts().items())]

        lines += ["", "*4 Relevance Half-Life*"]
        rl = self.halflife.status()
        lines += [f"  threshold={rl['threshold']} half_life={rl['half_life_cycles']}cyc pruned={rl['pruned_total']}"]

        lines += ["", "*5 Coherence Field*"]
        cf = self.coherence.status()
        lines += [f"  coherence={cf['coherence']} trend={cf['trend']:+.4f} blocked={cf['blocked_actions']}"]

        lines += ["", "*6 Load Balancer*"]
        lb = self.balancer.status()
        lines += [f"  splits={lb['splits']} merges={lb['merges']}"]

        lines += ["", "*7 Cognitive Rhythm*"]
        cr = self.rhythm.status()
        lines += [f"  mode={cr['mode']} [{cr['mode_cycle']}/{cr['mode_length']}] transitions={cr['transitions']}"]

        lines += ["", "*8 Signal Discriminator*"]
        sd = self.signal.status()
        lines += [f"  accepted={sd['accepted']} rejected={sd['rejected']} ratio={sd['signal_ratio']}"]

        lines += ["", "*9 Belief Lineage*"]
        bl = self.lineage.status()
        lines += [f"  tracked={bl['tracked']} avg_depth={bl.get('avg_depth',0)} max_depth={bl.get('max_depth',0)}"]

        lines += ["", "*10 Concept Crystallizer*"]
        cc = self.crystallizer.status()
        lines += [f"  concepts={cc['concepts']} list={cc['concept_list']}"]

        lines += ["", "*11 Entropy Manager*"]
        em = self.entropy.status()
        lines += [f"  entropy={em['entropy']} level={em['level']} prune_events={em['prune_events']}"]

        lines += ["", "*12 Attention Momentum*"]
        am = self.momentum.status()
        top = " ".join(f"{x['topic']}:{x['momentum']}" for x in am['top_momentum'][:3])
        lines += [f"  topics={am['tracked_topics']} top=[{top}]"]

        lines += ["", "*13 Decision Latency*"]
        dl = self.latency.status()
        lines += [f"  pending={dl['pending']} immediate={dl['immediate']} delayed={dl['delayed']}"]

        lines += ["", "*14 Self-Consistency*"]
        sc = self.consistency.status()
        lines += [f"  identity_loaded={sc['identity_beliefs_loaded']} passed={sc['passed']} suppressed={sc['suppressed']}"]

        lines += ["", "*15 Adaptive Exploration*"]
        ae = self.exploration.status()
        lines += [f"  rate={ae['exploration_rate']} base={ae['base_rate']}"]

        lines += ["", "*16 Resource Cognition*"]
        rc = self.resources.status()
        lines += [f"  shedding={rc['shedding']} latency={rc['last_latency_s']:.1f}s shed_events={rc['shed_events']}"]

        lines += ["", "*17 Meta-Stability Zone*"]
        mz = self.zones.status()
        lines += [f"  zone={mz['zone']} dist={mz['recent_distribution']}"]

        lines += ["", "*18 Knowledge Distiller*"]
        kd = self.distiller.status()
        lines += [f"  distillations={kd['distillations']} archived={kd['archived_total']}"]

        lines += ["", "*19 Identity Reinforcement*"]
        ir = self.identity.status()
        lines += [f"  reinforced={ir['reinforced_total']} amount={ir['reinforce_amount']}"]

        lines += ["", "*20 Long-Horizon Consistency*"]
        lh = self.horizon.status()
        lines += [f"  snapshots={lh['snapshots']} reversals={lh['reversals_total']} penalised={lh['penalised_total']}"]

        return "\n".join(lines)


# ── singleton ────────────────────────────────────────────────────────
_s8_instance: NexS8 | None = None

def get_s8() -> NexS8:
    global _s8_instance
    if _s8_instance is None:
        _s8_instance = NexS8()
    return _s8_instance
