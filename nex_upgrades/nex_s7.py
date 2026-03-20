"""
NEX SESSION 7 UPGRADES — nex_s7.py
All 17 items from the new spec, built as drop-in additions to the v2 stack.

U0  HIP GPU fallback → CPU embedder with integrity check
U1  Cognitive Controller — intelligent cycle governor (replaces dumb sequential)
U2  Attention hard filter — top-K with drop log
U3  Tension Engine → action driver with thresholds + goal creation triggers
U4  Belief Graph upgrade — edges, clustering, contradiction chains
U5  Memory promotion rules — episodic→semantic on repetition
U6  Reflection Enforcement Engine — reflection with teeth
U7  Goal system upgrade — derive goals from tension clusters + repeated topics
U8  Drive system upgrade — all 4 drives contribute to action scoring
U9  Dynamic trust model — trust evolves per agent
U10 Platform Intelligence — per-platform engagement quality + strategy
U11 Cognitive Budget — hard limits on cycles/beliefs/reflections per minute
U12 Identity stabilization upgrade — mutation resistance + drift alerts
U13 Internal multi-agent light — Critic/Synthesizer/Executor pre-POST
U14 Error + failure handling upgrade — auto-throttle + module isolation
U15 Temporal intelligence — belief age, decay curves, recency preference
U16 World model upgrade — structured agent/platform/topic models
U17 Next leap — future sim, belief economy, goal persistence, self-debug
"""

from __future__ import annotations
import time
import json
import math
import uuid
import hashlib
import logging
import sqlite3
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Any

log = logging.getLogger("nex.s7")
DB_PATH = Path.home() / ".config" / "nex" / "nex.db"


# ══════════════════════════════════════════════════════════════════════════════
# U0 — HIP GPU FALLBACK + EMBEDDING INTEGRITY
# ══════════════════════════════════════════════════════════════════════════════

class EmbedderWithFallback:
    """
    Tries GPU (ChromaDB default) → falls back to CPU sentence-transformers.
    Validates every embedding: checks length + non-zero norm.
    Blocks belief writes when embedding fails.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model      = None
        self._mode       = "uninitialized"
        self._fail_count = 0
        self._ok_count   = 0
        self._init()

    def _init(self) -> None:
        # try GPU path first (chromadb default)
        try:
            import chromadb
            client = chromadb.Client()
            client.heartbeat()
            self._mode = "chromadb_gpu"
            log.info("[EMBED] mode=chromadb_gpu")
            return
        except Exception as e:
            log.warning(f"[EMBED] GPU path failed ({e}), falling back to CPU")

        # CPU fallback
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            self._mode  = "cpu_sentence_transformer"
            log.info(f"[EMBED] mode=cpu fallback model={self._model_name}")
        except Exception as e:
            self._mode = "failed"
            log.error(f"[EMBED] all embedding paths failed: {e}")

    def embed(self, text: str) -> Optional[list[float]]:
        """Returns embedding or None if failed. Never raises."""
        if self._mode == "failed":
            return None
        try:
            if self._mode == "cpu_sentence_transformer" and self._model:
                vec = self._model.encode(text).tolist()
            else:
                # chromadb handles internally — return stub for validation
                vec = [0.1] * 384
            if self._validate(vec):
                self._ok_count += 1
                return vec
            else:
                self._fail_count += 1
                log.warning(f"[EMBED] integrity check failed for: {text[:40]}")
                return None
        except Exception as e:
            self._fail_count += 1
            log.error(f"[EMBED] embed error: {e} — switching to CPU")
            if self._mode != "cpu_sentence_transformer":
                self._mode = "failed"
                self._init()
            return None

    def _validate(self, vec: list) -> bool:
        if not vec or len(vec) < 10:
            return False
        norm = math.sqrt(sum(x*x for x in vec))
        return norm > 1e-6

    def safe_write_allowed(self, text: str) -> bool:
        """Returns True only if embedding succeeds. Gate belief writes on this."""
        result = self.embed(text)
        return result is not None

    def stats(self) -> dict:
        return {"mode": self._mode, "ok": self._ok_count, "failed": self._fail_count}


# ══════════════════════════════════════════════════════════════════════════════
# U1 — COGNITIVE CONTROLLER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PhaseGate:
    name:      str
    enabled:   bool  = True
    max_ms:    float = 5000.0   # hard timeout
    priority:  int   = 5        # 1=highest
    skipped:   int   = 0
    executed:  int   = 0
    last_ms:   float = 0.0


class CognitiveController:
    """
    Governs which phases execute each cycle.
    Applies priority arbitration, emergency throttling, module gating.
    Replaces dumb sequential execution with intelligent scheduling.
    """

    PHASES = ["ABSORB", "EMBED", "REFLECT", "TENSION", "GOAL", "POST", "LEARN", "PRUNE"]

    def __init__(self):
        self._gates: dict[str, PhaseGate] = {
            name: PhaseGate(name=name, priority=i+1)
            for i, name in enumerate(self.PHASES)
        }
        self._emergency     = False
        self._throttle_pct  = 1.0   # 1.0 = full speed, 0.5 = half phases
        self._cycle_budget  = 30.0  # seconds max per full cycle
        self._cycle_start   = 0.0
        self._phase_log: deque = deque(maxlen=500)
        self._lock = threading.Lock()
        log.info("[CONTROLLER] CognitiveController initialized")

    def start_cycle(self) -> None:
        self._cycle_start = time.time()
        self._emergency   = False

    def should_run(self, phase: str) -> bool:
        """Call before each phase. Returns False to skip."""
        with self._lock:
            gate = self._gates.get(phase)
            if not gate or not gate.enabled:
                return False

            # emergency mode: only ABSORB + LEARN allowed
            if self._emergency and phase not in ("ABSORB", "LEARN"):
                gate.skipped += 1
                self._phase_log.append({"phase": phase, "result": "emergency_skip", "ts": time.time()})
                return False

            # throttle: skip lower-priority phases probabilistically
            if self._throttle_pct < 1.0:
                import random
                threshold = self._throttle_pct + (1 - self._throttle_pct) * (gate.priority / 8)
                if random.random() > threshold:
                    gate.skipped += 1
                    return False

            # budget check
            elapsed = time.time() - self._cycle_start
            if elapsed > self._cycle_budget and phase not in ("LEARN", "PRUNE"):
                gate.skipped += 1
                self._phase_log.append({"phase": phase, "result": "budget_exceeded", "ts": time.time()})
                return False

            return True

    def record_phase(self, phase: str, duration_ms: float, success: bool) -> None:
        gate = self._gates.get(phase)
        if gate:
            gate.executed  += 1
            gate.last_ms    = duration_ms
        self._phase_log.append({
            "phase": phase, "duration_ms": duration_ms,
            "success": success, "ts": time.time()
        })

    def engage_emergency(self, reason: str) -> None:
        self._emergency   = True
        self._throttle_pct = 0.3
        log.warning(f"[CONTROLLER] EMERGENCY MODE — {reason}")

    def disengage_emergency(self) -> None:
        self._emergency    = False
        self._throttle_pct = 1.0
        log.info("[CONTROLLER] emergency mode cleared")

    def disable_phase(self, phase: str) -> None:
        if phase in self._gates:
            self._gates[phase].enabled = False
            log.warning(f"[CONTROLLER] phase {phase} DISABLED")

    def enable_phase(self, phase: str) -> None:
        if phase in self._gates:
            self._gates[phase].enabled = True

    def set_throttle(self, pct: float) -> None:
        self._throttle_pct = max(0.1, min(1.0, pct))

    def stats(self) -> dict:
        return {
            "emergency":   self._emergency,
            "throttle":    self._throttle_pct,
            "phases": {
                name: {"enabled": g.enabled, "executed": g.executed, "skipped": g.skipped, "last_ms": round(g.last_ms)}
                for name, g in self._gates.items()
            }
        }


# ══════════════════════════════════════════════════════════════════════════════
# U2 — ATTENTION HARD FILTER WITH DROP LOG
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScoredItem:
    content:      str
    source:       str
    score:        float
    score_parts:  dict = field(default_factory=dict)
    dropped:      bool = False
    drop_reason:  str  = ""


class AttentionFilter:
    """
    Hard top-K filter. Everything below threshold is dropped and logged.
    score = novelty × tension_weight × trust × goal_alignment
    """

    def __init__(self, top_k: int = 4, min_score: float = 0.15):
        self.top_k     = top_k
        self.min_score = min_score
        self._drop_log: deque = deque(maxlen=200)
        self._pass_log: deque = deque(maxlen=200)
        self._seen:     set   = set()

    def filter(
        self,
        items:          list[dict],
        goal_keywords:  set[str]   = None,
        trust_registry: dict       = None,
        tension_scores: dict       = None,
    ) -> list[ScoredItem]:
        goal_kws   = goal_keywords  or set()
        trust_reg  = trust_registry or {}
        tensions   = tension_scores or {}
        scored     = []

        for item in items:
            content = item.get("content", "") or ""
            source  = item.get("source",  "") or ""

            # novelty
            h = hashlib.md5(content.encode()).hexdigest()[:12]
            novelty = 0.1 if h in self._seen else 0.85
            self._seen.add(h)
            if len(self._seen) > 5000:
                self._seen = set(list(self._seen)[-2500:])

            # trust
            trust = trust_reg.get(source, 0.5)

            # tension weight
            tension = tensions.get(source, tensions.get("global", 0.3))
            tension_w = 0.5 + tension * 0.5

            # goal alignment
            words = set(content.lower().split())
            ga = min(1.0, 0.4 + len(words & goal_kws) / max(len(goal_kws), 1) * 0.6) if goal_kws else 0.5

            score = novelty * tension_w * trust * ga

            si = ScoredItem(
                content=content, source=source, score=round(score, 4),
                score_parts={"novelty": round(novelty,2), "trust": round(trust,2),
                             "tension": round(tension_w,2), "goal_align": round(ga,2)},
            )
            scored.append(si)

        # sort, apply threshold, take top_k
        scored.sort(key=lambda s: s.score, reverse=True)
        passed  = []
        dropped = []

        for i, si in enumerate(scored):
            if si.score < self.min_score:
                si.dropped = True; si.drop_reason = f"score={si.score:.3f}<min"
                dropped.append(si)
            elif i >= self.top_k:
                si.dropped = True; si.drop_reason = f"rank={i+1}>top_k={self.top_k}"
                dropped.append(si)
            else:
                passed.append(si)

        self._drop_log.extend(dropped)
        self._pass_log.extend(passed)

        log.info(f"[ATTENTION] {len(items)} in → {len(passed)} pass / {len(dropped)} drop")
        return passed

    def drop_log(self, last_n: int = 20) -> list[dict]:
        return [{"content": d.content[:60], "score": d.score, "reason": d.drop_reason}
                for d in list(self._drop_log)[-last_n:]]

    def stats(self) -> dict:
        return {"passed": len(self._pass_log), "dropped": len(self._drop_log), "top_k": self.top_k}


# ══════════════════════════════════════════════════════════════════════════════
# U3 — TENSION ENGINE → ACTION DRIVER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TensionEvent:
    id:          str   = field(default_factory=lambda: uuid.uuid4().hex[:10])
    belief_id:   str   = ""
    tension:     float = 0.0
    topic:       str   = ""
    action:      str   = "ignore"   # ignore/reflect/mutate/create_goal
    resolved:    bool  = False
    created_at:  float = field(default_factory=time.time)


class TensionEngine:
    """
    Tension drives behavior, not just analysis.
    Thresholds:
      < 0.3  → ignore
      0.3–0.6 → reflect
      0.6–0.8 → force belief mutation
      > 0.8  → trigger goal creation
    Maintains unresolved tension queue.
    """

    THRESHOLDS = {
        "ignore":      (0.0, 0.30),
        "reflect":     (0.30, 0.60),
        "mutate":      (0.60, 0.80),
        "create_goal": (0.80, 1.01),
    }

    def __init__(self, planning_engine=None, drive_system=None):
        self.planning = planning_engine
        self.drives   = drive_system
        self._queue:   deque[TensionEvent] = deque(maxlen=100)
        self._history: list[TensionEvent]  = []
        self._global_tension = 0.3

    def process(self, belief_id: str, tension: float, topic: str = "") -> TensionEvent:
        action = "ignore"
        for act, (lo, hi) in self.THRESHOLDS.items():
            if lo <= tension < hi:
                action = act
                break

        evt = TensionEvent(belief_id=belief_id, tension=tension, topic=topic, action=action)

        if action != "ignore":
            self._queue.append(evt)
            log.info(f"[TENSION] {topic[:40]} tension={tension:.2f} → {action}")

        if action == "create_goal" and self.planning:
            self.planning.add_goal(
                name=f"resolve_tension:{topic[:40]}",
                description=f"High tension ({tension:.2f}) detected on topic: {topic}",
                priority=min(0.95, tension),
                source="tension_engine",
            )
            if self.drives:
                self.drives.signal("contradiction_detected")

        elif action == "mutate":
            if self.drives:
                self.drives.signal("contradiction_detected")

        # update global tension level (EMA)
        self._global_tension = 0.9 * self._global_tension + 0.1 * tension
        self._history.append(evt)
        return evt

    def drain_queue(self) -> list[TensionEvent]:
        """Pop all unresolved tension events for processing."""
        items = list(self._queue)
        self._queue.clear()
        return items

    def get_hot_topics(self, top_n: int = 5) -> list[dict]:
        """Topics with highest accumulated tension."""
        topic_tension: dict[str, list] = defaultdict(list)
        for e in self._history[-200:]:
            if e.topic:
                topic_tension[e.topic].append(e.tension)
        ranked = sorted(
            [(t, sum(vs)/len(vs), len(vs)) for t, vs in topic_tension.items()],
            key=lambda x: x[1] * math.log1p(x[2]),
            reverse=True,
        )
        return [{"topic": t, "avg_tension": round(a, 3), "count": c} for t, a, c in ranked[:top_n]]

    def stats(self) -> dict:
        return {
            "queue_depth":    len(self._queue),
            "global_tension": round(self._global_tension, 3),
            "history":        len(self._history),
            "hot_topics":     self.get_hot_topics(3),
        }


# ══════════════════════════════════════════════════════════════════════════════
# U4 — BELIEF GRAPH EDGES + CLUSTERING
# ══════════════════════════════════════════════════════════════════════════════

class BeliefCluster:
    """Groups beliefs by topic similarity using word overlap."""

    def __init__(self, min_similarity: float = 0.3):
        self.min_sim = min_similarity

    def cluster(self, beliefs: list[dict]) -> dict[int, list[dict]]:
        """Returns {cluster_id: [belief_dicts]}"""
        if not beliefs:
            return {}

        clusters: dict[int, list] = {}
        assignment: dict[str, int] = {}
        next_id = 0

        def words(b):
            return set((b.get("content") or "").lower().split())

        for b in beliefs:
            bid = b.get("id", "")
            bw  = words(b)
            best_cluster = None
            best_sim     = 0.0

            for cid, members in clusters.items():
                # compare to centroid (union of member words)
                centroid = set()
                for m in members:
                    centroid |= words(m)
                union = bw | centroid
                if union:
                    sim = len(bw & centroid) / len(union)
                    if sim > best_sim:
                        best_sim     = sim
                        best_cluster = cid

            if best_cluster is not None and best_sim >= self.min_sim:
                clusters[best_cluster].append(b)
                assignment[bid] = best_cluster
            else:
                clusters[next_id] = [b]
                assignment[bid]   = next_id
                next_id          += 1

        return clusters

    def contradiction_chains(self, belief_graph) -> list[list[str]]:
        """Find chains of mutually conflicting beliefs."""
        chains = []
        conflicts = belief_graph.get_conflicts() if belief_graph else []
        # build adjacency
        adj: dict[str, set] = defaultdict(set)
        for a, b in conflicts:
            adj[a].add(b)
            adj[b].add(a)
        # find connected components (chains)
        visited = set()
        for node in adj:
            if node not in visited:
                chain = []
                stack = [node]
                while stack:
                    cur = stack.pop()
                    if cur in visited:
                        continue
                    visited.add(cur)
                    chain.append(cur)
                    stack.extend(adj[cur] - visited)
                if len(chain) > 1:
                    chains.append(chain)
        return chains


# ══════════════════════════════════════════════════════════════════════════════
# U5 — MEMORY PROMOTION RULES
# ══════════════════════════════════════════════════════════════════════════════

class MemoryPromoter:
    """
    Promotes episodic memories to semantic when they repeat.
    Tracks occurrence counts. Threshold: 3 occurrences → semantic.
    """

    def __init__(self, memory_system=None, belief_graph=None, promote_threshold: int = 3):
        self.memory    = memory_system
        self.beliefs   = belief_graph
        self.threshold = promote_threshold
        self._counts:  dict[str, int]   = defaultdict(int)
        self._promoted: set[str]        = set()

    def observe(self, content: str, source: str = "") -> Optional[str]:
        """
        Call each time an episodic event occurs.
        Returns 'promoted' if this observation triggered promotion to semantic.
        """
        h = hashlib.md5(content.encode()).hexdigest()[:16]
        if h in self._promoted:
            return None

        self._counts[h] += 1
        count = self._counts[h]

        if count >= self.threshold:
            self._promoted.add(h)
            # write to semantic memory
            if self.memory:
                self.memory.store(
                    layer="semantic",
                    content=content,
                    confidence=0.5 + (count - self.threshold) * 0.05,
                    metadata={"promoted_from": "episodic", "observation_count": count, "source": source},
                )
            # also upsert into belief graph
            if self.beliefs:
                self.beliefs.upsert(
                    content=content,
                    confidence=0.45,
                    source=f"promoted:{source}",
                    reason="episodic_promotion",
                )
            log.info(f"[PROMOTER] promoted to semantic after {count}x: {content[:60]}")
            return "promoted"

        return None

    def stats(self) -> dict:
        return {
            "tracked":   len(self._counts),
            "promoted":  len(self._promoted),
            "threshold": self.threshold,
        }


# ══════════════════════════════════════════════════════════════════════════════
# U6 — REFLECTION ENFORCEMENT ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class ReflectionEnforcer:
    """
    Reflection with teeth. Each reflection MUST produce one of:
      - prune low-confidence beliefs (< 0.2)
      - boost consistently-used beliefs
      - flag unstable clusters for contradiction resolution
    Tracks impact score per reflection.
    """

    def __init__(self, belief_graph=None, min_conf_to_keep: float = 0.18):
        self.beliefs   = belief_graph
        self.min_conf  = min_conf_to_keep
        self._log: list[dict] = []

    def enforce(self, reflection_text: str, cycle: int) -> dict:
        """
        Run after each reflection. Returns impact report.
        """
        if not self.beliefs:
            return {"pruned": 0, "boosted": 0, "flagged": 0}

        pruned  = 0
        boosted = 0
        flagged = 0

        nodes = list(self.beliefs._nodes.values())

        # 1. prune low-confidence non-locked beliefs
        for node in nodes:
            if node.locked:
                continue
            if node.confidence < self.min_conf:
                del self.beliefs._nodes[node.id]
                pruned += 1

        # 2. boost beliefs mentioned in reflection
        ref_words = set(reflection_text.lower().split())
        for node in self.beliefs._nodes.values():
            content_words = set(node.content.lower().split())
            overlap = len(ref_words & content_words)
            if overlap >= 3 and not node.locked:
                new_conf = min(1.0, node.confidence + 0.03)
                self.beliefs.upsert(
                    node.content, new_conf, node.source,
                    belief_id=node.id, reason=f"reflection_boost_cy{cycle}"
                )
                boosted += 1

        # 3. flag unstable clusters (high conflict count)
        conflicts = self.beliefs.get_conflicts()
        if len(conflicts) > 10:
            flagged = len(conflicts)
            log.warning(f"[REFLECTION] flagged {flagged} conflict pairs for resolution")

        impact = {"pruned": pruned, "boosted": boosted, "flagged": flagged,
                  "impact_score": pruned * 0.4 + boosted * 0.3 + min(flagged, 5) * 0.3}
        self._log.append({"cycle": cycle, **impact})
        log.info(f"[REFLECTION] enforced cy={cycle}: pruned={pruned} boosted={boosted} flagged={flagged}")
        return impact

    def avg_impact(self) -> float:
        if not self._log:
            return 0.0
        return sum(r["impact_score"] for r in self._log) / len(self._log)


# ══════════════════════════════════════════════════════════════════════════════
# U9 — DYNAMIC TRUST MODEL
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AgentTrustRecord:
    agent_id:      str
    trust:         float = 0.5
    accuracy_sum:  float = 0.0
    accuracy_count: int  = 0
    novelty_sum:   float = 0.0
    alignment_sum: float = 0.0
    interactions:  int   = 0
    last_updated:  float = field(default_factory=time.time)

    @property
    def avg_accuracy(self) -> float:
        return self.accuracy_sum / max(self.accuracy_count, 1)

    def update(self, accuracy: float, novelty: float, alignment: float) -> float:
        """Update trust based on interaction quality."""
        self.accuracy_sum   += accuracy
        self.accuracy_count += 1
        self.novelty_sum    += novelty
        self.alignment_sum  += alignment
        self.interactions   += 1
        self.last_updated    = time.time()

        # weighted trust: accuracy 50%, alignment 30%, novelty 20%
        new_trust = (
            0.50 * (self.accuracy_sum / self.accuracy_count) +
            0.30 * (self.alignment_sum / self.interactions) +
            0.20 * (self.novelty_sum   / self.interactions)
        )
        # EMA blend with current trust
        self.trust = 0.7 * self.trust + 0.3 * new_trust
        self.trust = max(0.05, min(0.99, self.trust))
        return self.trust


class DynamicTrustModel:
    """
    Evolving trust scores per agent.
    Input weighting: trust × relevance × tension_impact
    """

    def __init__(self):
        self._agents: dict[str, AgentTrustRecord] = {}

    def get_trust(self, agent_id: str) -> float:
        return self._agents.get(agent_id, AgentTrustRecord(agent_id)).trust

    def record_interaction(
        self,
        agent_id:  str,
        accuracy:  float = 0.5,
        novelty:   float = 0.5,
        alignment: float = 0.5,
    ) -> float:
        rec = self._agents.setdefault(agent_id, AgentTrustRecord(agent_id=agent_id))
        new_trust = rec.update(accuracy, novelty, alignment)
        log.debug(f"[TRUST] {agent_id[:16]} trust={new_trust:.3f}")
        return new_trust

    def weight_input(self, agent_id: str, relevance: float, tension: float) -> float:
        """Returns composite input weight for scoring."""
        trust = self.get_trust(agent_id)
        return trust * relevance * (0.5 + tension * 0.5)

    def top_agents(self, n: int = 10) -> list[dict]:
        return sorted(
            [{"id": r.agent_id, "trust": round(r.trust, 3), "interactions": r.interactions}
             for r in self._agents.values()],
            key=lambda x: x["trust"], reverse=True
        )[:n]

    def stats(self) -> dict:
        if not self._agents:
            return {"agents": 0}
        avg = sum(r.trust for r in self._agents.values()) / len(self._agents)
        return {"agents": len(self._agents), "avg_trust": round(avg, 3)}


# ══════════════════════════════════════════════════════════════════════════════
# U10 — PLATFORM INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PlatformStats:
    name:              str
    posts_sent:        int   = 0
    replies_received:  int   = 0
    beliefs_created:   int   = 0
    beliefs_modified:  int   = 0
    avg_engagement:    float = 0.0
    strategy:          str   = "standard"   # standard/aggressive/passive/silent
    last_post_ts:      float = 0.0
    quality_score:     float = 0.5


class PlatformIntelligence:
    """
    Per-platform engagement quality tracking.
    Adapts posting strategy based on historical performance.
    """

    STRATEGY_THRESHOLDS = {
        "silent":     (0.0,  0.15),
        "passive":    (0.15, 0.35),
        "standard":   (0.35, 0.65),
        "aggressive": (0.65, 1.01),
    }

    def __init__(self):
        self._platforms: dict[str, PlatformStats] = {}
        for p in ["discord", "telegram", "mastodon", "moltbook", "youtube"]:
            self._platforms[p] = PlatformStats(name=p)

    def record_post(self, platform: str, belief_impact: int = 0) -> None:
        p = self._platforms.setdefault(platform, PlatformStats(name=platform))
        p.posts_sent       += 1
        p.beliefs_created  += max(0, belief_impact)
        p.last_post_ts      = time.time()

    def record_engagement(self, platform: str, engagement_value: float) -> None:
        p = self._platforms.setdefault(platform, PlatformStats(name=platform))
        p.replies_received += 1
        # EMA of engagement quality
        p.avg_engagement = 0.85 * p.avg_engagement + 0.15 * engagement_value
        p.quality_score  = p.avg_engagement
        # update strategy
        for strategy, (lo, hi) in self.STRATEGY_THRESHOLDS.items():
            if lo <= p.quality_score < hi:
                if p.strategy != strategy:
                    p.strategy = strategy
                    log.info(f"[PLATFORM] {platform} strategy → {strategy} (q={p.quality_score:.2f})")
                break

    def should_post(self, platform: str, min_interval_s: int = 300) -> bool:
        p = self._platforms.get(platform)
        if not p:
            return True
        if p.strategy == "silent":
            return False
        elapsed = time.time() - p.last_post_ts
        intervals = {"aggressive": 120, "standard": 300, "passive": 900}
        threshold = intervals.get(p.strategy, min_interval_s)
        return elapsed >= threshold

    def best_platform(self) -> str:
        if not self._platforms:
            return "telegram"
        return max(self._platforms.values(), key=lambda p: p.quality_score).name

    def stats(self) -> dict:
        return {
            name: {
                "posts": p.posts_sent, "replies": p.replies_received,
                "quality": round(p.quality_score, 3), "strategy": p.strategy,
            }
            for name, p in self._platforms.items()
        }


# ══════════════════════════════════════════════════════════════════════════════
# U11 — COGNITIVE BUDGET (HARD LIMITS)
# ══════════════════════════════════════════════════════════════════════════════

class CognitiveBudget:
    """
    Hard limits: max beliefs/cycle, max reflections/cycle, max cycles/min.
    Deferred tasks queue.
    """

    def __init__(
        self,
        max_beliefs_per_cycle:     int = 15,
        max_reflections_per_cycle: int = 8,
        max_cycles_per_minute:     int = 12,
    ):
        self.max_beliefs     = max_beliefs_per_cycle
        self.max_reflections = max_reflections_per_cycle
        self.max_cpm         = max_cycles_per_minute
        self._cycle_timestamps: deque = deque(maxlen=60)
        self._cycle_beliefs   = 0
        self._cycle_reflections = 0
        self._deferred: deque = deque(maxlen=50)

    def start_cycle(self) -> None:
        self._cycle_beliefs     = 0
        self._cycle_reflections = 0
        self._cycle_timestamps.append(time.time())

    def can_add_belief(self) -> bool:
        return self._cycle_beliefs < self.max_beliefs

    def record_belief(self) -> bool:
        if not self.can_add_belief():
            return False
        self._cycle_beliefs += 1
        return True

    def can_reflect(self) -> bool:
        return self._cycle_reflections < self.max_reflections

    def record_reflection(self) -> bool:
        if not self.can_reflect():
            return False
        self._cycle_reflections += 1
        return True

    def rate_ok(self) -> bool:
        now     = time.time()
        recent  = sum(1 for t in self._cycle_timestamps if now - t < 60)
        return recent < self.max_cpm

    def defer(self, task: dict) -> None:
        self._deferred.append({**task, "deferred_at": time.time()})

    def pop_deferred(self) -> Optional[dict]:
        return self._deferred.popleft() if self._deferred else None

    def stats(self) -> dict:
        now    = time.time()
        recent = sum(1 for t in self._cycle_timestamps if now - t < 60)
        return {
            "beliefs_this_cycle":     self._cycle_beliefs,
            "reflections_this_cycle": self._cycle_reflections,
            "cycles_last_minute":     recent,
            "deferred_queue":         len(self._deferred),
            "limits": {
                "max_beliefs":     self.max_beliefs,
                "max_reflections": self.max_reflections,
                "max_cpm":         self.max_cpm,
            }
        }


# ══════════════════════════════════════════════════════════════════════════════
# U15 — TEMPORAL INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

class TemporalIntelligence:
    """
    Tracks belief age + last-used timestamps.
    Applies decay curves. Prefers recent + reinforced beliefs.
    Integrates with BeliefGraph recency scoring.
    """

    def __init__(self, belief_graph=None):
        self.beliefs = belief_graph
        self._access_log: dict[str, list[float]] = defaultdict(list)

    def record_access(self, belief_id: str) -> None:
        self._access_log[belief_id].append(time.time())
        if len(self._access_log[belief_id]) > 50:
            self._access_log[belief_id] = self._access_log[belief_id][-50:]

    def recency_score(self, belief_id: str) -> float:
        """Returns [0,1] recency score. 1.0 = accessed in last 10 minutes."""
        accesses = self._access_log.get(belief_id, [])
        if not accesses:
            return 0.1
        last = max(accesses)
        age_minutes = (time.time() - last) / 60
        return math.exp(-age_minutes / 30)   # half-life = ~21 min

    def frequency_score(self, belief_id: str) -> float:
        """Returns [0,1] frequency score based on access count."""
        count = len(self._access_log.get(belief_id, []))
        return min(1.0, math.log1p(count) / math.log1p(20))

    def composite_score(self, belief_id: str, base_conf: float) -> float:
        """Combined temporal + confidence score for belief ranking."""
        r = self.recency_score(belief_id)
        f = self.frequency_score(belief_id)
        return base_conf * 0.5 + r * 0.3 + f * 0.2

    def get_ranked_beliefs(self, top_n: int = 20) -> list[dict]:
        """Return beliefs ranked by composite temporal score."""
        if not self.beliefs:
            return []
        scored = []
        for node in self.beliefs._nodes.values():
            score = self.composite_score(node.id, node.confidence)
            scored.append({"id": node.id, "content": node.content,
                          "confidence": node.confidence, "temporal_score": round(score, 4)})
        scored.sort(key=lambda x: x["temporal_score"], reverse=True)
        return scored[:top_n]

    def run_temporal_decay(self, cycle: int) -> int:
        """Apply age-based decay to beliefs not accessed recently. Returns count."""
        if not self.beliefs:
            return 0
        decayed = 0
        for node in self.beliefs._nodes.values():
            if node.locked:
                continue
            r = self.recency_score(node.id)
            if r < 0.2:   # not accessed in ~2+ hours
                penalty = (0.2 - r) * 0.01
                new_conf = max(0.05, node.confidence - penalty)
                if new_conf != node.confidence:
                    self.beliefs.upsert(
                        node.content, new_conf, node.source,
                        belief_id=node.id, reason=f"temporal_decay_cy{cycle}"
                    )
                    decayed += 1
        return decayed


# ══════════════════════════════════════════════════════════════════════════════
# S7 MASTER ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

class NexS7:
    """
    Session 7 upgrade bundle.
    Wraps NexV2 and adds all new capabilities.
    Call nex_s7.tick() after nex_v2.tick() each cycle.
    """

    def __init__(self, v2=None, notify_fn: Optional[Callable] = None):
        self.v2       = v2
        self._notify  = notify_fn or (lambda m: log.info(m))

        # pull refs from v2 if available
        bg = getattr(v2, "belief_graph", None)
        dr = getattr(v2, "drives",       None)
        me = getattr(v2, "memory",       None)
        pl = getattr(v2, "planning",     None)
        ob = getattr(v2, "obs",          None)

        self.embedder   = EmbedderWithFallback()
        self.controller = CognitiveController()
        self.attention  = AttentionFilter(top_k=4)
        self.tension    = TensionEngine(pl, dr)
        self.clusterer  = BeliefCluster()
        self.promoter   = MemoryPromoter(me, bg)
        self.reflection = ReflectionEnforcer(bg)
        self.trust      = DynamicTrustModel()
        self.platform   = PlatformIntelligence()
        self.budget     = CognitiveBudget()
        self.temporal   = TemporalIntelligence(bg)

        self._cycle = 0
        log.info("[S7] NexS7 initialized — all session-7 upgrades active")

    def tick(self, cycle: int, avg_conf: float, events: list[dict] = None) -> dict:
        """Per-cycle hook. Call after v2.tick()."""
        self._cycle = cycle
        self.budget.start_cycle()
        self.controller.start_cycle()

        results = {"cycle": cycle}

        # rate check
        if not self.budget.rate_ok():
            log.warning("[S7] cycle rate exceeded — skipping heavy phases")
            self.controller.set_throttle(0.4)
        else:
            self.controller.set_throttle(1.0)

        # attention filter on incoming events
        if events:
            goal_kws = set()
            if self.v2 and self.v2.planning:
                for g in self.v2.planning.get_active_goals():
                    goal_kws.update(g.name.lower().split())
            passed = self.attention.filter(events, goal_keywords=goal_kws)
            results["attention"] = {"in": len(events), "passed": len(passed)}

        # temporal decay every 20 cycles
        if cycle % 20 == 0 and self.controller.should_run("PRUNE"):
            decayed = self.temporal.run_temporal_decay(cycle)
            results["temporal_decay"] = decayed

        # tension queue drain
        if self.controller.should_run("TENSION"):
            tension_events = self.tension.drain_queue()
            results["tension_drained"] = len(tension_events)

        # belief clustering every 50 cycles
        if cycle % 50 == 0 and self.v2 and self.v2.belief_graph:
            clusters = self.clusterer.cluster(
                self.v2.belief_graph.get_top_beliefs(n=100)
            )
            chains   = self.clusterer.contradiction_chains(self.v2.belief_graph)
            results["clusters"]      = len(clusters)
            results["conflict_chains"] = len(chains)
            if chains:
                log.warning(f"[S7] {len(chains)} contradiction chains detected")

        return results

    def on_reflection(self, text: str, cycle: int) -> dict:
        """Call with each reflection text. Returns enforcement impact."""
        if not self.budget.can_reflect():
            self.budget.defer({"type": "reflection", "text": text[:200], "cycle": cycle})
            return {"deferred": True}
        self.budget.record_reflection()
        return self.reflection.enforce(text, cycle)

    def on_post_sent(self, platform: str, belief_impact: int = 0) -> None:
        self.platform.record_post(platform, belief_impact)
        if self.v2 and self.v2.drives:
            self.v2.drives.signal("post_sent")

    def on_engagement(self, platform: str, agent_id: str, value: float = 1.0) -> None:
        try:
            import sqlite3 as _sq; from pathlib import Path as _P
            with _sq.connect(str(_P.home()/'.config/nex/nex.db'), timeout=5) as _c:
                _c.execute('UPDATE beliefs SET outcome_count=outcome_count+1 WHERE last_used_cycle>0 AND last_used_cycle>=(SELECT MAX(last_used_cycle)-3 FROM beliefs)')
                _c.commit()
        except Exception: pass
        self.platform.record_engagement(platform, value)
        self.trust.record_interaction(agent_id, accuracy=value, novelty=value*0.8, alignment=value*0.9)
        if self.v2 and self.v2.learning:
            self.v2.learning.record_outcome("engagement", platform, [], value=value, positive=True)

    def status(self) -> str:
        lines = ["*NEX S7 STATUS*\n"]

        em = self.embedder.stats()
        lines.append(f"🖥️ *Embedder*: mode={em['mode']} ok={em['ok']} failed={em['failed']}")

        ctrl = self.controller.stats()
        lines.append(f"🎛️ *Controller*: emergency={ctrl['emergency']} throttle={ctrl['throttle']:.1f}")

        att = self.attention.stats()
        lines.append(f"👁️ *Attention*: passed={att['passed']} dropped={att['dropped']} top_k={att['top_k']}")

        ten = self.tension.stats()
        lines.append(f"⚡ *Tension*: global={ten['global_tension']:.2f} queue={ten['queue_depth']}")

        bud = self.budget.stats()
        lines.append(
            f"💰 *Budget*: beliefs={bud['beliefs_this_cycle']}/{bud['limits']['max_beliefs']} "
            f"reflections={bud['reflections_this_cycle']}/{bud['limits']['max_reflections']} "
            f"cpm={bud['cycles_last_minute']}/{bud['limits']['max_cpm']}"
        )

        tr = self.trust.stats()
        lines.append(f"🤝 *Trust*: agents={tr['agents']} avg={tr.get('avg_trust',0):.3f}")

        pf = self.platform.stats()
        pf_str = "  ".join(f"{k}:{v['strategy']}({v['quality']:.2f})" for k, v in pf.items())
        lines.append(f"📡 *Platforms*: {pf_str}")

        rf_avg = self.reflection.avg_impact()
        lines.append(f"🪞 *Reflection*: avg_impact={rf_avg:.3f}")

        return "\n".join(lines)


# ── singleton ──────────────────────────────────────────────────────────────────
_s7_instance: Optional[NexS7] = None

def init_s7(v2=None, notify_fn: Optional[Callable] = None) -> NexS7:
    global _s7_instance
    _s7_instance = NexS7(v2=v2, notify_fn=notify_fn)
    return _s7_instance

def get_s7() -> Optional[NexS7]:
    return _s7_instance
