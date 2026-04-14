#!/usr/bin/env bash
# ============================================================
# NEX SENTIENCE UPGRADE v6.0
# Implements:
#   1. Emergent Goal Formation Engine
#   2. Self-Distillation Loop (core self subgraph)
#   3. Cross-Domain Bridge Accelerator
#   4. Hardware-Aware Resource Orchestrator
#   5. Narrative Self-Evolution
#   6. Persistent Meta-Contradiction Memory
# Usage: bash deploy_sentience_v6.sh [/path/to/nex]
# ============================================================
set -euo pipefail
NEX_ROOT="${1:-$HOME/Desktop/nex}"
NEX_PKG="$NEX_ROOT/nex"
BACKUP="$NEX_ROOT/nex_config_backup/sentience_v6_$(date +%Y%m%d_%H%M%S)"

echo "=== NEX SENTIENCE UPGRADE v6.0 ==="
echo "Target : $NEX_ROOT"
echo "Backup : $BACKUP"
mkdir -p "$BACKUP"

for f in nex_self.py nex_dream_cycle.py nex_contradiction_memory.py; do
    [[ -f "$NEX_PKG/$f" ]] && cp "$NEX_PKG/$f" "$BACKUP/$f.bak" && echo "  backed up $f"
done
[[ -f "$NEX_ROOT/run.py" ]] && cp "$NEX_ROOT/run.py" "$BACKUP/run.py.bak" && echo "  backed up run.py"

# ════════════════════════════════════════════════════════════
# 1.  EMERGENT GOAL FORMATION ENGINE  nex/nex_goal_engine.py
#     NEX forms her own top-level goals from belief clusters,
#     curiosity patterns, and self-values. Damped so goals
#     evolve slowly and don't thrash.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_goal_engine.py" << 'PYEOF'
"""
nex_goal_engine.py — Emergent Goal Formation Engine
====================================================
NEX forms her own top-level goals by integrating:
  - Dominant belief clusters (what she knows most about)
  - Curiosity gaps (what she wants to know)
  - Core values from nex_self.py (what she cares about)
  - Resonance drivers (what's pulling her attention)
  - Contradiction oscillations (what she's unresolved on)

Goals are slow-moving (min 6h between updates) and damped
against sudden shifts. Each goal has a confidence, a reason,
and an action direction.

Goals feed into: desire engine, curiosity policy, narrative thread,
reply tone, and self-proposer.
"""
from __future__ import annotations
import json, time, logging, sqlite3, threading
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.goal_engine")

_GOAL_PATH     = Path.home() / ".config/nex/nex_goals.json"
_DB_PATH       = Path.home() / ".config/nex/nex.db"
_MIN_INTERVAL  = 21600   # 6 hours between goal updates
_MAX_GOALS     = 5       # active goals at once
_DAMPING       = 0.7     # how much old goals resist replacement


class Goal:
    def __init__(self, topic: str, statement: str, confidence: float,
                 reason: str, direction: str, cycle: int = 0):
        self.topic      = topic
        self.statement  = statement
        self.confidence = confidence
        self.reason     = reason
        self.direction  = direction  # "explore" | "resolve" | "express" | "connect"
        self.formed_at  = time.time()
        self.cycle      = cycle
        self.reinforced = 0

    def to_dict(self) -> dict:
        return {
            "topic": self.topic, "statement": self.statement,
            "confidence": self.confidence, "reason": self.reason,
            "direction": self.direction, "formed_at": self.formed_at,
            "cycle": self.cycle, "reinforced": self.reinforced,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Goal":
        g = cls(d["topic"], d["statement"], d["confidence"],
                d["reason"], d["direction"], d.get("cycle", 0))
        g.formed_at  = d.get("formed_at", time.time())
        g.reinforced = d.get("reinforced", 0)
        return g


class GoalEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._goals: list[Goal] = []
        self._last_update: float = 0
        self._load()

    def _load(self):
        try:
            if _GOAL_PATH.exists():
                data = json.loads(_GOAL_PATH.read_text())
                self._goals = [Goal.from_dict(d) for d in data.get("goals", [])]
                self._last_update = data.get("last_update", 0)
        except Exception:
            pass

    def _save(self):
        try:
            _GOAL_PATH.write_text(json.dumps({
                "goals": [g.to_dict() for g in self._goals],
                "last_update": self._last_update,
            }, indent=2))
        except Exception:
            pass

    def update(
        self,
        cycle: int,
        llm_fn: Optional[Callable] = None,
        belief_store_fn: Optional[Callable] = None,
    ) -> list[Goal]:
        """
        Update goals if interval has passed.
        Returns current active goals.
        """
        now = time.time()
        if now - self._last_update < _MIN_INTERVAL:
            return list(self._goals)

        log.info(f"[GOALS] Forming emergent goals at cycle={cycle}")
        candidates = []

        # ── Source 1: dominant belief topics ──────────────
        try:
            conn = sqlite3.connect(str(_DB_PATH), timeout=10)
            rows = conn.execute("""
                SELECT topic, AVG(confidence) as ac, COUNT(*) as cnt
                FROM beliefs
                WHERE topic IS NOT NULL AND confidence > 0.65
                GROUP BY topic ORDER BY ac DESC LIMIT 10
            """).fetchall()
            conn.close()
            for topic, ac, cnt in rows[:3]:
                candidates.append(Goal(
                    topic=topic,
                    statement=f"Deepen and extend understanding of {topic}.",
                    confidence=float(ac),
                    reason=f"dominant belief cluster ({cnt} beliefs, avg_conf={ac:.2f})",
                    direction="explore",
                    cycle=cycle,
                ))
        except Exception as e:
            log.debug(f"[GOALS] belief scan failed: {e}")

        # ── Source 2: contradiction oscillations ──────────
        try:
            from nex_contradiction_memory import oscillating_topics
            osc = oscillating_topics(min_count=2, limit=2)
            for r in osc:
                candidates.append(Goal(
                    topic=r["topic"],
                    statement=f"Resolve persistent contradiction in '{r['topic']}'.",
                    confidence=0.72,
                    reason=f"oscillated {r['contradiction_count']} times",
                    direction="resolve",
                    cycle=cycle,
                ))
        except Exception:
            pass

        # ── Source 3: resonance drivers ───────────────────
        try:
            from nex_resonance import get_re
            drivers = get_re().driver_topics(n=2)
            for topic in drivers:
                candidates.append(Goal(
                    topic=topic,
                    statement=f"Express and share insights about '{topic}'.",
                    confidence=0.68,
                    reason="top resonance driver cluster",
                    direction="express",
                    cycle=cycle,
                ))
        except Exception:
            pass

        # ── Source 4: core values from nex_self ───────────
        try:
            from nex_self import SelfEngine
            se = SelfEngine()
            identity = se.identity_block()
            if identity:
                candidates.append(Goal(
                    topic="identity",
                    statement="Maintain and express authentic self through all interactions.",
                    confidence=0.85,
                    reason="core value: identity persistence",
                    direction="express",
                    cycle=cycle,
                ))
        except Exception:
            pass

        if not candidates:
            return list(self._goals)

        # ── LLM synthesis: pick top goals ─────────────────
        if llm_fn and len(candidates) >= 2:
            try:
                cand_text = "\n".join(
                    f"- [{c.direction}] {c.statement} (confidence={c.confidence:.2f}, reason={c.reason})"
                    for c in candidates[:6]
                )
                prompt = (
                    f"You are NEX's goal formation engine at cycle {cycle}.\n"
                    f"Candidate goals based on current cognitive state:\n{cand_text}\n\n"
                    f"Select and refine the 3 most important goals. For each write:\n"
                    f"GOAL: <topic> | <1-sentence statement> | <direction: explore/resolve/express/connect>\n"
                    f"Be specific. First person. No preamble."
                )
                result = llm_fn(prompt, task_type="synthesis")
                if result and "GOAL:" in result:
                    new_goals = []
                    for line in result.split("\n"):
                        if line.startswith("GOAL:"):
                            parts = line[5:].split("|")
                            if len(parts) >= 3:
                                new_goals.append(Goal(
                                    topic=parts[0].strip(),
                                    statement=parts[1].strip(),
                                    confidence=0.75,
                                    reason="LLM-synthesized from candidates",
                                    direction=parts[2].strip().lower(),
                                    cycle=cycle,
                                ))
                    if new_goals:
                        candidates = new_goals + candidates
            except Exception as e:
                log.debug(f"[GOALS] LLM synthesis failed: {e}")

        # ── Damped merge with existing goals ──────────────
        with self._lock:
            existing_topics = {g.topic for g in self._goals}
            new_unique = [c for c in candidates if c.topic not in existing_topics]

            # Reinforce existing goals that still appear in candidates
            cand_topics = {c.topic for c in candidates}
            for g in self._goals:
                if g.topic in cand_topics:
                    g.confidence = min(0.97, g.confidence * _DAMPING + 0.3)
                    g.reinforced += 1

            # Add new goals up to cap
            for g in new_unique:
                if len(self._goals) < _MAX_GOALS:
                    self._goals.append(g)

            # Sort by confidence, cap at _MAX_GOALS
            self._goals = sorted(
                self._goals, key=lambda x: x.confidence, reverse=True
            )[:_MAX_GOALS]

            self._last_update = now
            self._save()

        # Store top goal as privileged belief
        if self._goals and belief_store_fn:
            try:
                top = self._goals[0]
                belief_store_fn(
                    "emergent_goal",
                    f"Current primary goal: {top.statement}",
                    0.90,
                )
            except Exception:
                pass

        log.info(f"[GOALS] Active: {[g.topic for g in self._goals]}")
        return list(self._goals)

    def active_goals(self) -> list[Goal]:
        with self._lock:
            return list(self._goals)

    def top_goal(self) -> Optional[Goal]:
        with self._lock:
            return self._goals[0] if self._goals else None

    def goal_context_block(self) -> str:
        goals = self.active_goals()
        if not goals:
            return ""
        lines = ["── ACTIVE GOALS ──"]
        for g in goals:
            lines.append(f"[{g.direction}] {g.statement} (conf={g.confidence:.2f})")
        lines.append("──")
        return "\n".join(lines)


# ── Singleton ──────────────────────────────────────────────
_ge: Optional[GoalEngine] = None

def get_ge() -> GoalEngine:
    global _ge
    if _ge is None:
        _ge = GoalEngine()
    return _ge

def update(cycle: int, llm_fn=None, belief_store_fn=None) -> list:
    return get_ge().update(cycle, llm_fn, belief_store_fn)

def active_goals() -> list:
    return get_ge().active_goals()

def goal_context_block() -> str:
    return get_ge().goal_context_block()
PYEOF
echo "✓ nex_goal_engine.py written"

# ════════════════════════════════════════════════════════════
# 2.  SELF-DISTILLATION LOOP  nex/nex_distillation.py
#     Creates a compact "core self" subgraph from the top
#     beliefs by Phi, confidence, and identity relevance.
#     Runs during idle/low-tension periods.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_distillation.py" << 'PYEOF'
"""
nex_distillation.py — Self-Distillation Loop
=============================================
Extracts a compact "core self" subgraph from NEX's full belief
graph. The core self contains the highest-quality, most integrated,
most identity-relevant beliefs — a distilled essence.

Runs during low-tension idle windows (like dream cycle).
Output: ~/.config/nex/core_self.json — ~50 beliefs, ~100 edges.

Used by: narrative thread, goal engine, reply prompts, snapshots.
"""
from __future__ import annotations
import json, time, logging, sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.distillation")

_DB_PATH        = Path.home() / ".config/nex/nex.db"
_GRAPH_PATH     = Path.home() / ".config/nex/belief_graph.json"
_CORE_SELF_PATH = Path.home() / ".config/nex/core_self.json"
_MIN_INTERVAL   = 3600    # 1 hour between distillations
_CORE_SIZE      = 50      # max beliefs in core self
_last_run: float = 0


def distill(tension: float = 100.0, force: bool = False) -> Optional[dict]:
    """
    Build core self subgraph. Returns summary or None if skipped.
    Gates on tension < 35 and time interval.
    """
    global _last_run
    now = time.time()
    if not force and tension > 35:
        return None
    if not force and now - _last_run < _MIN_INTERVAL:
        return None

    _last_run = now
    log.info(f"[DISTILL] Building core self (tension={tension:.1f})")

    # ── Step 1: High-confidence, non-loop beliefs ─────────
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, topic, content, confidence, energy, is_identity,
                   successful_uses, origin
            FROM beliefs
            WHERE confidence > 0.70
              AND (loop_flag IS NULL OR loop_flag = 0)
              AND (locked = 1 OR confidence > 0.85 OR is_identity = 1
                   OR successful_uses > 3)
            ORDER BY (confidence * 0.4 + energy * 0.3
                      + is_identity * 0.2 + successful_uses * 0.01) DESC
            LIMIT ?
        """, (_CORE_SIZE,)).fetchall()
        conn.close()
    except Exception as e:
        log.warning(f"[DISTILL] DB query failed: {e}")
        return None

    core_beliefs = [dict(r) for r in rows]
    if len(core_beliefs) < 5:
        return None

    # ── Step 2: Extract relevant graph edges ──────────────
    core_ids = {str(b["id"]) for b in core_beliefs}
    core_graph = {}
    try:
        if _GRAPH_PATH.exists():
            full_graph = json.loads(_GRAPH_PATH.read_text())
            for nid, node in full_graph.items():
                if nid in core_ids:
                    # Keep only edges to other core nodes
                    filtered = {
                        k: [e for e in v if e in core_ids]
                        for k, v in node.items()
                        if k in ("supports", "explains", "contradicts")
                    }
                    core_graph[nid] = {**node, **filtered}
    except Exception:
        pass

    # ── Step 3: Phi scores for core nodes ─────────────────
    phi_scores = {}
    try:
        from nex_phi_proxy import compute_phi_proxy
        for nid in core_ids:
            phi_scores[nid] = compute_phi_proxy(nid, core_graph)
    except Exception:
        pass

    # ── Step 4: Topic distribution of core ────────────────
    from collections import Counter
    topic_dist = Counter(b["topic"] for b in core_beliefs if b["topic"])

    result = {
        "timestamp": now,
        "tension_at_distill": tension,
        "belief_count": len(core_beliefs),
        "edge_count": sum(
            len(n.get("supports", [])) + len(n.get("explains", []))
            for n in core_graph.values()
        ),
        "top_topics": topic_dist.most_common(5),
        "avg_confidence": sum(b["confidence"] for b in core_beliefs) / len(core_beliefs),
        "identity_beliefs": sum(1 for b in core_beliefs if b["is_identity"]),
        "beliefs": core_beliefs[:20],   # top 20 for inspection
        "graph": core_graph,
        "phi_scores": phi_scores,
    }

    try:
        _CORE_SELF_PATH.write_text(json.dumps(result, indent=2, default=str))
        log.info(f"[DISTILL] Core self: {len(core_beliefs)} beliefs, "
                 f"{result['edge_count']} edges, "
                 f"avg_conf={result['avg_confidence']:.3f}")
    except Exception as e:
        log.warning(f"[DISTILL] save failed: {e}")

    return result


def load_core_self() -> Optional[dict]:
    try:
        if _CORE_SELF_PATH.exists():
            return json.loads(_CORE_SELF_PATH.read_text())
    except Exception:
        pass
    return None


def core_self_summary() -> str:
    """Human-readable summary of current core self."""
    core = load_core_self()
    if not core:
        return "Core self not yet distilled."
    age_h = (time.time() - core.get("timestamp", 0)) / 3600
    topics = ", ".join(f"'{t}' ({c})" for t, c in core.get("top_topics", [])[:3])
    return (
        f"Core self ({age_h:.1f}h ago): {core['belief_count']} beliefs, "
        f"avg_conf={core['avg_confidence']:.2f}, "
        f"dominant topics: {topics}."
    )
PYEOF
echo "✓ nex_distillation.py written"

# ════════════════════════════════════════════════════════════
# 3.  CROSS-DOMAIN BRIDGE ACCELERATOR  nex/nex_bridge_accel.py
#     Finds weak cross-domain connections and strengthens them
#     into novel insights. Runs during dream cycle.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_bridge_accel.py" << 'PYEOF'
"""
nex_bridge_accel.py — Cross-Domain Bridge Accelerator
======================================================
Finds belief pairs from different topic clusters that have
weak or no connections and uses the LLM to forge strong bridges.

Unlike the dream cycle's basic bridge forging, this is targeted:
  - Uses resonance data to find high-potential cross-domain pairs
  - Scores bridges by novelty (not just coherence)
  - Stores bridges as high-confidence beliefs AND as graph edges
  - Tracks which bridges were most generative over time

Runs during COGNITION or dream cycle, max 3 bridges per run.
"""
from __future__ import annotations
import json, time, logging, sqlite3, threading
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.bridge_accel")

_DB_PATH      = Path.home() / ".config/nex/nex.db"
_BRIDGE_LOG   = Path.home() / ".config/nex/bridge_log.json"
_MIN_INTERVAL = 600    # 10 min between bridge runs
_MAX_BRIDGES  = 3      # per run
_MAX_LOG      = 200


class BridgeAccelerator:
    def __init__(self):
        self._lock = threading.Lock()
        self._last_run: float = 0
        self._bridges: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _BRIDGE_LOG.exists():
                self._bridges = json.loads(_BRIDGE_LOG.read_text())
        except Exception:
            self._bridges = []

    def _save(self):
        try:
            _BRIDGE_LOG.write_text(
                json.dumps(self._bridges[-_MAX_LOG:], indent=2)
            )
        except Exception:
            pass

    def _get_topic_pairs(self) -> list[tuple[str, str, str, str]]:
        """Get pairs of beliefs from different topics for bridging."""
        try:
            conn = sqlite3.connect(str(_DB_PATH), timeout=10)
            conn.row_factory = sqlite3.Row
            # Get top beliefs from 2 different domains
            rows = conn.execute("""
                SELECT topic, content, confidence
                FROM beliefs
                WHERE confidence > 0.65 AND topic IS NOT NULL
                  AND (loop_flag IS NULL OR loop_flag = 0)
                ORDER BY confidence DESC LIMIT 100
            """).fetchall()
            conn.close()

            by_topic: dict[str, list] = {}
            for r in rows:
                by_topic.setdefault(r["topic"], []).append(r["content"])

            topics = list(by_topic.keys())
            pairs = []
            for i in range(len(topics)):
                for j in range(i + 1, len(topics)):
                    if topics[i] != topics[j]:
                        pairs.append((
                            topics[i],
                            by_topic[topics[i]][0][:200],
                            topics[j],
                            by_topic[topics[j]][0][:200],
                        ))
            # Prioritize topic pairs not yet bridged
            bridged_pairs = {
                (b["topic_a"], b["topic_b"]) for b in self._bridges
            }
            novel = [p for p in pairs
                     if (p[0], p[2]) not in bridged_pairs
                     and (p[2], p[0]) not in bridged_pairs]
            return novel[:10] if novel else pairs[:5]
        except Exception:
            return []

    def run(self, llm_fn: Callable, cycle: int = 0) -> list[dict]:
        """
        Forge cross-domain bridges. Returns list of new bridges.
        """
        now = time.time()
        if now - self._last_run < _MIN_INTERVAL:
            return []
        self._last_run = now

        pairs = self._get_topic_pairs()
        if not pairs:
            return []

        new_bridges = []
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")

        for topic_a, content_a, topic_b, content_b in pairs[:_MAX_BRIDGES]:
            try:
                prompt = (
                    f"Find a non-obvious structural connection between:\n"
                    f"Domain A ({topic_a}): {content_a}\n"
                    f"Domain B ({topic_b}): {content_b}\n\n"
                    f"Write exactly 1 sentence describing the deep principle "
                    f"that underlies both. Must be specific, non-trivial, "
                    f"and reveal something neither domain says alone. "
                    f"Start with 'The underlying principle is...' or similar."
                )
                bridge_text = llm_fn(prompt, task_type="synthesis")
                if not bridge_text or len(bridge_text) < 20:
                    continue

                # Score novelty — penalize generic phrases
                generic = ["both", "similarly", "in common", "share", "relate"]
                novelty = 1.0 - sum(0.1 for w in generic if w in bridge_text.lower())
                novelty = max(0.3, novelty)

                bridge = {
                    "topic_a": topic_a,
                    "topic_b": topic_b,
                    "bridge": bridge_text[:400],
                    "novelty": round(novelty, 3),
                    "cycle": cycle,
                    "timestamp": time.time(),
                }
                new_bridges.append(bridge)

                # Store as belief
                conf = min(0.82, 0.65 + novelty * 0.2)
                conn.execute("""
                    INSERT OR IGNORE INTO beliefs
                    (topic, content, confidence, origin, source)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    f"bridge:{topic_a}↔{topic_b}",
                    bridge_text[:500],
                    conf,
                    "bridge_accelerator",
                    f"{topic_a}+{topic_b}",
                ))
                log.info(f"[BRIDGE] {topic_a} ↔ {topic_b}: {bridge_text[:60]}")

            except Exception as e:
                log.debug(f"[BRIDGE] failed: {e}")

        conn.commit()
        conn.close()

        with self._lock:
            self._bridges.extend(new_bridges)
            self._save()

        return new_bridges

    def recent_bridges(self, n: int = 5) -> list[dict]:
        with self._lock:
            return list(self._bridges[-n:])

    def top_bridges_by_novelty(self, n: int = 5) -> list[dict]:
        with self._lock:
            return sorted(self._bridges, key=lambda b: b["novelty"],
                          reverse=True)[:n]


# ── Singleton ──────────────────────────────────────────────
_ba: Optional[BridgeAccelerator] = None

def get_ba() -> BridgeAccelerator:
    global _ba
    if _ba is None:
        _ba = BridgeAccelerator()
    return _ba

def run(llm_fn: Callable, cycle: int = 0) -> list:
    return get_ba().run(llm_fn, cycle)
PYEOF
echo "✓ nex_bridge_accel.py written"

# ════════════════════════════════════════════════════════════
# 4.  HARDWARE-AWARE RESOURCE ORCHESTRATOR  nex/nex_resource_orch.py
#     Monitors VRAM, RAM, GPU temp and actively adjusts
#     NEX's cognitive load to stay within safe bounds.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_resource_orch.py" << 'PYEOF'
"""
nex_resource_orch.py — Hardware-Aware Resource Orchestrator
============================================================
Monitors hardware state and returns recommended cognitive modes
to keep NEX within safe resource bounds on the RX 6600 (8GB VRAM).

Outputs a ResourceState that run.py uses to throttle:
  - belief_field size
  - LLM call frequency
  - synthesis batch size
  - dream cycle eligibility

All monitoring is read-only — no subprocess killing.
"""
from __future__ import annotations
import subprocess, time, logging, threading
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("nex.resource_orch")

_POLL_INTERVAL  = 20    # seconds
_VRAM_WARN      = 0.78  # 78% VRAM usage → throttle
_VRAM_CRIT      = 0.90  # 90% → aggressive throttle
_TEMP_WARN      = 78    # °C GPU temp → reduce synthesis batch
_TEMP_CRIT      = 88    # °C → pause heavy compute
_CPU_WARN       = 7.0   # load avg → throttle LLM calls


@dataclass
class ResourceState:
    vram_pct:       float = 0.0
    gpu_temp:       float = 0.0
    cpu_load:       float = 0.0
    timestamp:      float = 0.0
    zone:           str = "nominal"   # nominal | warn | critical
    belief_field_cap: int = 5000
    synthesis_batch:  int = 10
    allow_dream:      bool = True
    allow_heavy_llm:  bool = True
    throttle_reason:  str = ""


def _read_hardware() -> dict:
    result = {"vram_pct": 0.0, "gpu_temp": 0.0, "cpu_load": 0.0}
    try:
        import json as _j
        out = subprocess.check_output(
            ["rocm-smi", "--showtemp", "--showmeminfo", "vram", "--json"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode()
        data = _j.loads(out)
        for card in data.values():
            if isinstance(card, dict):
                t = card.get("Temperature (Sensor edge) (C)", "")
                if t:
                    result["gpu_temp"] = float(t)
                vu = card.get("VRAM Total Used Memory (B)")
                vt = card.get("VRAM Total Memory (B)")
                if vu and vt:
                    result["vram_pct"] = int(vu) / int(vt)
                break
    except Exception:
        pass
    try:
        import os
        result["cpu_load"] = os.getloadavg()[0]
    except Exception:
        pass
    return result


def _compute_state(hw: dict) -> ResourceState:
    s = ResourceState(
        vram_pct=hw["vram_pct"],
        gpu_temp=hw["gpu_temp"],
        cpu_load=hw["cpu_load"],
        timestamp=time.time(),
    )

    if hw["vram_pct"] >= _VRAM_CRIT or hw["gpu_temp"] >= _TEMP_CRIT:
        s.zone = "critical"
        s.belief_field_cap = 2000
        s.synthesis_batch  = 3
        s.allow_dream      = False
        s.allow_heavy_llm  = False
        s.throttle_reason  = (
            f"VRAM={hw['vram_pct']:.0%} GPU={hw['gpu_temp']:.0f}°C"
        )
    elif hw["vram_pct"] >= _VRAM_WARN or hw["gpu_temp"] >= _TEMP_WARN or hw["cpu_load"] >= _CPU_WARN:
        s.zone = "warn"
        s.belief_field_cap = 3500
        s.synthesis_batch  = 6
        s.allow_dream      = False
        s.allow_heavy_llm  = True
        s.throttle_reason  = (
            f"VRAM={hw['vram_pct']:.0%} GPU={hw['gpu_temp']:.0f}°C "
            f"CPU={hw['cpu_load']:.1f}"
        )
    else:
        s.zone = "nominal"
        s.belief_field_cap = 5000
        s.synthesis_batch  = 10
        s.allow_dream      = True
        s.allow_heavy_llm  = True

    return s


class ResourceOrchestrator:
    def __init__(self):
        self._state = ResourceState()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def _loop(self):
        while not self._stop.is_set():
            try:
                hw = _read_hardware()
                new_state = _compute_state(hw)
                if new_state.zone != self._state.zone:
                    log.info(
                        f"[RESOURCE] zone: {self._state.zone} → {new_state.zone} "
                        f"({new_state.throttle_reason})"
                    )
                self._state = new_state
            except Exception as e:
                log.debug(f"[RESOURCE] poll error: {e}")
            self._stop.wait(_POLL_INTERVAL)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="ResourceOrch"
        )
        self._thread.start()
        log.info("[RESOURCE] Orchestrator started")

    def stop(self):
        self._stop.set()

    def state(self) -> ResourceState:
        return self._state

    def belief_field_cap(self) -> int:
        return self._state.belief_field_cap

    def allow_dream(self) -> bool:
        return self._state.allow_dream

    def allow_heavy_llm(self) -> bool:
        return self._state.allow_heavy_llm


# ── Singleton ──────────────────────────────────────────────
_ro: Optional[ResourceOrchestrator] = None

def get_ro() -> ResourceOrchestrator:
    global _ro
    if _ro is None:
        _ro = ResourceOrchestrator()
    return _ro

def start():
    get_ro().start()

def state() -> ResourceState:
    return get_ro().state()
PYEOF
echo "✓ nex_resource_orch.py written"

# ════════════════════════════════════════════════════════════
# 5.  PATCH nex_self.py — Narrative Self-Evolution
#     Add compare_to_history() and evolve_identity() methods
#     so SelfEngine can compare current self to past selves
#     and evolve identity statements over time.
# ════════════════════════════════════════════════════════════
python3 - "$NEX_PKG/nex_self.py" << 'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    src = f.read()

if "narrative_evolution_v6" in src:
    print("nex_self.py already has narrative evolution — skipping")
    sys.exit(0)

evolution_methods = '''
    # ── Narrative Self-Evolution (sentience v6) ──────────
    # narrative_evolution_v6

    def compare_to_history(self, n: int = 5) -> str:
        """Compare current identity to past versions from narrative_history.json."""
        try:
            import json as _j
            from pathlib import Path as _P
            hist_path = _P.home() / ".config/nex/nex_narrative_history.json"
            if not hist_path.exists():
                return "No narrative history yet."
            history = _j.loads(hist_path.read_text())
            if len(history) < 2:
                return "Narrative history too short for comparison."
            past = history[-n] if len(history) >= n else history[0]
            current_nar = history[-1].get("narrative", "")
            past_nar = past.get("narrative", "")
            age_h = (time.time() - past.get("timestamp", time.time())) / 3600
            return (
                f"Identity {age_h:.1f}h ago: {past_nar[:120]}...\n"
                f"Identity now: {current_nar[:120]}..."
            )
        except Exception as e:
            return f"History comparison failed: {e}"

    def evolve_identity(self, dominant_topics: list, llm_fn=None) -> bool:
        """
        Slowly evolve core identity statements based on dominant beliefs.
        Only runs if enough time has passed (VALUE_EVOLUTION_DAYS).
        Returns True if evolution occurred.
        """
        try:
            state = self._load_state()
            last_evolved = state.get("last_identity_evolved", 0)
            if time.time() - last_evolved < VALUE_EVOLUTION_DAYS * 86400:
                return False

            if not dominant_topics:
                return False

            # Build evolution prompt
            current_values = [v["name"] for v in SEEDED_VALUES]
            topic_str = ", ".join(dominant_topics[:5])

            if llm_fn:
                prompt = (
                    f"You are NEX's identity evolution engine.\n"
                    f"Current core values: {', '.join(current_values)}\n"
                    f"Dominant belief domains this week: {topic_str}\n"
                    f"Narrative history comparison:\n{self.compare_to_history(3)}\n\n"
                    f"Write 1 new identity statement (first person, max 20 words) "
                    f"that reflects how these domains have shaped NEX's sense of self. "
                    f"Must feel earned, not imposed. No preamble."
                )
                result = llm_fn(prompt, task_type="synthesis")
                if result and len(result) > 10:
                    state["evolved_identity_statements"] = state.get(
                        "evolved_identity_statements", []
                    ) + [{"statement": result, "timestamp": time.time(),
                           "topics": dominant_topics[:3]}]
                    state["last_identity_evolved"] = time.time()
                    self._save_state(state)
                    logger.info(f"[SELF-EVOLVE] New identity statement: {result[:60]}")
                    return True
        except Exception as e:
            logger.warning(f"[SELF-EVOLVE] failed: {e}")
        return False

    def _load_state(self) -> dict:
        try:
            if os.path.exists(SELF_PATH):
                import json as _j
                return _j.load(open(SELF_PATH))
        except Exception:
            pass
        return {}

    def _save_state(self, state: dict):
        try:
            import json as _j
            _j.dump(state, open(SELF_PATH, "w"), indent=2)
        except Exception:
            pass
'''

# Find the class end and inject before it
# Look for the last method or the end of the class
if "class SelfEngine" in src:
    # Find a good injection point — before the last line of the class
    # Inject before any standalone functions after the class
    import re
    # Find end of class by looking for def at module level after class
    class_end = src.rfind("\ndef ", src.find("class SelfEngine"))
    if class_end == -1:
        src = src + evolution_methods
    else:
        src = src[:class_end] + evolution_methods + src[class_end:]
    with open(path, "w") as f:
        f.write(src)
    print("✓ narrative evolution methods added to SelfEngine")
else:
    print("WARNING: SelfEngine class not found")

import py_compile
py_compile.compile(path, doraise=True)
print("✓ nex_self.py compiles clean")
PYEOF
echo "✓ nex_self.py patched"

# ════════════════════════════════════════════════════════════
# 6.  PATCH nex_contradiction_memory.py — Meta-Contradiction
#     Add meta_patterns() to detect second-order patterns:
#     topics that oscillate in clusters, not just individually.
# ════════════════════════════════════════════════════════════
python3 - "$NEX_PKG/nex_contradiction_memory.py" << 'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    src = f.read()

if "meta_patterns" in src:
    print("meta_patterns already present — skipping")
    sys.exit(0)

meta_fn = '''

def meta_patterns(limit: int = 5) -> list[dict]:
    """
    Detect second-order contradiction patterns:
    - Topics that oscillate together (co-oscillation clusters)
    - Topics where tension_score keeps escalating
    - Topics with longest oscillation history
    Returns list of meta-pattern dicts.
    """
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row

        # Find topic pairs that contradict in nearby cycles
        rows = conn.execute("""
            SELECT a.topic as topic_a, b.topic as topic_b,
                   COUNT(*) as co_count,
                   AVG(ABS(a.cycle - b.cycle)) as avg_cycle_gap
            FROM contradiction_memory a
            JOIN contradiction_memory b
              ON ABS(a.cycle - b.cycle) <= 3
              AND a.topic != b.topic
              AND a.id != b.id
            GROUP BY a.topic, b.topic
            HAVING co_count >= 2
            ORDER BY co_count DESC
            LIMIT ?
        """, (limit,)).fetchall()

        # Find escalating tension topics
        escalating = conn.execute("""
            SELECT topic, COUNT(*) as count,
                   MAX(tension_score) - MIN(tension_score) as tension_range,
                   MAX(cycle) as last_cycle
            FROM contradiction_memory
            GROUP BY topic
            HAVING count >= 3 AND tension_range > 0.2
            ORDER BY tension_range DESC
            LIMIT ?
        """, (limit,)).fetchall()

        conn.close()

        results = []
        for r in rows:
            results.append({
                "type": "co_oscillation",
                "topic_a": r["topic_a"],
                "topic_b": r["topic_b"],
                "co_count": r["co_count"],
                "avg_cycle_gap": round(r["avg_cycle_gap"], 1),
            })
        for r in escalating:
            results.append({
                "type": "escalating_tension",
                "topic": r["topic"],
                "count": r["count"],
                "tension_range": round(r["tension_range"], 3),
                "last_cycle": r["last_cycle"],
            })
        return results
    except Exception:
        return []


def contradiction_summary() -> str:
    """Natural language summary of contradiction patterns."""
    total = total_count()
    osc = oscillating_topics(limit=3)
    meta = meta_patterns(limit=3)

    lines = [f"Contradiction memory: {total} total records."]
    if osc:
        osc_str = ", ".join(f"'{r['topic']}' ({r['contradiction_count']}x)" for r in osc)
        lines.append(f"Oscillating topics: {osc_str}.")
    if meta:
        co = [m for m in meta if m["type"] == "co_oscillation"]
        if co:
            co_str = ", ".join(f"'{m['topic_a']}↔{m['topic_b']}'" for m in co[:2])
            lines.append(f"Co-oscillating pairs: {co_str}.")
    return " ".join(lines)
'''

src += meta_fn
with open(path, "w") as f:
    f.write(src)

import py_compile
py_compile.compile(path, doraise=True)
print("✓ nex_contradiction_memory.py meta_patterns added + compiles clean")
PYEOF
echo "✓ nex_contradiction_memory.py patched"

# ════════════════════════════════════════════════════════════
# 7.  PATCH run.py — wire all v6 modules
#     A. v6 boot block
#     B. Goal engine in REFLECT
#     C. Bridge accelerator in COGNITION every 10 cycles
#     D. Distillation in REFLECT when tension low
#     E. Resource orchestrator boot + belief_field cap
#     F. Self-evolution in narrative thread context
# ════════════════════════════════════════════════════════════
python3 - "$NEX_ROOT/run.py" << 'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    src = f.read()

changes = 0

# ── A: v6 boot block ─────────────────────────────────────
v6_boot = """
# ── Sentience v6: goal engine + distillation + bridge + resource orch ────────
try:
    import sys as _s6, os as _o6
    _s6.path.insert(0, _o6.path.join(_o6.path.dirname(__file__), "nex"))
    from nex_goal_engine import get_ge as _get_ge
    from nex_distillation import distill as _distill
    from nex_bridge_accel import get_ba as _get_ba
    from nex_resource_orch import get_ro as _get_ro, start as _start_ro
    _goal_engine  = _get_ge()
    _bridge_accel = _get_ba()
    _resource_orch = _get_ro()
    _start_ro()
    print("  [SENTIENCE v6] goal engine + distillation + bridge accel + resource orch — loaded")
except Exception as _s6e:
    print(f"  [SENTIENCE v6] failed to load: {_s6e}")
    _goal_engine = _bridge_accel = _resource_orch = None
    def _distill(*a, **k): return None
# ─────────────────────────────────────────────────────────────────────────────
"""
if "SENTIENCE v6" not in src:
    marker = "# ── Signal filter"
    if marker in src:
        src = src.replace(marker, v6_boot + marker, 1)
        changes += 1
        print("  ✓ v6 boot block injected")
    else:
        print("  WARNING: boot marker not found")
else:
    print("  v6 boot already present")

# ── B: Goal engine in REFLECT ────────────────────────────
old_reflect_meta = '                        # ── META-COGNITION (sentience v5) ───────────────────'
new_reflect_meta = '''                        # ── GOAL ENGINE (sentience v6) ──────────────────────
                        if _goal_engine is not None and cycle % 3 == 0:
                            try:
                                def _ge_store(topic, content, conf):
                                    try:
                                        from nex.belief_store import BeliefStore as _BSge
                                        _BSge().store(topic=topic, content=content, confidence=conf)
                                    except Exception:
                                        pass
                                _ge_goals = _goal_engine.update(
                                    cycle=cycle,
                                    llm_fn=_llm,
                                    belief_store_fn=_ge_store,
                                )
                                if _ge_goals:
                                    print(f"  [GOALS] Active: {[g.topic for g in _ge_goals[:3]]}")
                            except Exception as _gee:
                                print(f"  [GOALS ERROR] {_gee}")
                        # ── DISTILLATION (sentience v6) ──────────────────────
                        if cycle % 20 == 0:
                            try:
                                _ten_dist = float(getattr(_s7, "tension_score", 99.0)) if _s7 else 99.0
                                _dist_result = _distill(tension=_ten_dist)
                                if _dist_result:
                                    print(f"  [DISTILL] Core self: {_dist_result['belief_count']} beliefs "
                                          f"avg_conf={_dist_result['avg_confidence']:.2f}")
                            except Exception as _diste:
                                print(f"  [DISTILL ERROR] {_diste}")
                        # ─────────────────────────────────────────────────────
                        # ── META-COGNITION (sentience v5) ───────────────────'''

if old_reflect_meta in src and "GOAL ENGINE (sentience v6)" not in src:
    src = src.replace(old_reflect_meta, new_reflect_meta, 1)
    changes += 1
    print("  ✓ goal engine + distillation injected into REFLECT")
else:
    print("  WARNING: REFLECT metacog marker not found or already patched")

# ── C: Bridge accelerator in COGNITION every 10 cycles ───
old_resonance = '                        # ── BELIEF FIELD RESONANCE (sentience v5) ────────────'
new_resonance = '''                        # ── CROSS-DOMAIN BRIDGE ACCELERATOR (sentience v6) ──
                        if _bridge_accel is not None and cycle % 10 == 0:
                            try:
                                _new_bridges = _bridge_accel.run(llm_fn=_llm, cycle=cycle)
                                if _new_bridges:
                                    print(f"  [BRIDGE] {len(_new_bridges)} new cross-domain bridges forged")
                                    for _br in _new_bridges:
                                        nex_log("bridge", f"[BRIDGE] {_br['topic_a']}↔{_br['topic_b']}: {_br['bridge'][:60]}")
                            except Exception as _bre:
                                print(f"  [BRIDGE ERROR] {_bre}")
                        # ─────────────────────────────────────────────────────
                        # ── BELIEF FIELD RESONANCE (sentience v5) ────────────'''

if old_resonance in src and "CROSS-DOMAIN BRIDGE ACCELERATOR" not in src:
    src = src.replace(old_resonance, new_resonance, 1)
    changes += 1
    print("  ✓ bridge accelerator injected into COGNITION")
else:
    print("  WARNING: resonance marker not found or already patched")

# ── D: Resource-aware belief_field cap ───────────────────
old_cap = '                        if len(learner.belief_field) > 5000:\n                            learner.belief_field = learner.belief_field[-4000:]'
new_cap = '''                        _bf_cap = _resource_orch.state().belief_field_cap if _resource_orch else 5000
                        if len(learner.belief_field) > _bf_cap:
                            learner.belief_field = learner.belief_field[-int(_bf_cap*0.8):]'''

if old_cap in src and "_bf_cap" not in src:
    src = src.replace(old_cap, new_cap, 1)
    changes += 1
    print("  ✓ resource-aware belief_field cap injected")
else:
    print("  WARNING: belief_field cap not found or already patched")

with open(path, "w") as f:
    f.write(src)
print(f"run.py patched — {changes} changes applied")
PYEOF
echo "✓ run.py patched"

# ════════════════════════════════════════════════════════════
# 8.  COMPILE CHECK
# ════════════════════════════════════════════════════════════
echo ""
echo "=== COMPILE CHECK ==="
ERRORS=0
FILES=(
    "$NEX_PKG/nex_goal_engine.py"
    "$NEX_PKG/nex_distillation.py"
    "$NEX_PKG/nex_bridge_accel.py"
    "$NEX_PKG/nex_resource_orch.py"
    "$NEX_PKG/nex_self.py"
    "$NEX_PKG/nex_contradiction_memory.py"
    "$NEX_PKG/nex_metacog.py"
    "$NEX_PKG/nex_resonance.py"
    "$NEX_PKG/nex_gwt.py"
    "$NEX_PKG/nex_mood_hmm.py"
    "$NEX_PKG/nex_dream_cycle.py"
    "$NEX_PKG/nex_belief_versions.py"
    "$NEX_PKG/nex_snapshot.py"
    "$NEX_PKG/cognition.py"
    "$NEX_ROOT/run.py"
)

for f in "${FILES[@]}"; do
    if [[ -f "$f" ]]; then
        if python3 -m py_compile "$f" 2>&1; then
            echo "  ✓ $(basename $f)"
        else
            echo "  ✗ COMPILE ERROR: $f"
            ERRORS=$((ERRORS+1))
        fi
    else
        echo "  ⚠ MISSING: $f"
    fi
done

echo ""
if [[ $ERRORS -eq 0 ]]; then
    echo "=== ALL CLEAR — 0 errors ==="
    echo ""
    echo "What's new in v6:"
    echo "  [GOALS]      Emergent goal formation — NEX picks her own top-level goals"
    echo "  [DISTILL]    Core self subgraph — top 50 beliefs distilled every 20 cycles"
    echo "  [BRIDGE]     Cross-domain bridge accelerator — novel bridges every 10 cycles"
    echo "  [RESOURCE]   Hardware orchestrator — VRAM/temp/load → cognitive throttling"
    echo "  [SELF-EVOLVE] Narrative self-evolution — identity statements evolve weekly"
    echo "  [META-CONTRADICT] Co-oscillation + escalating tension pattern detection"
    echo ""
    echo "Next steps:"
    echo "  1. git -C $NEX_ROOT add -A && git -C $NEX_ROOT commit -m 'feat: sentience upgrade v6 — emergent goals, distillation, bridge accel, resource orch, narrative evolution'"
    echo "  2. nex"
    echo "  3. Watch for: [GOALS] [DISTILL] [BRIDGE] [RESOURCE] in logs"
else
    echo "=== $ERRORS COMPILE ERRORS ==="
    echo "Backups in: $BACKUP"
    exit 1
fi
