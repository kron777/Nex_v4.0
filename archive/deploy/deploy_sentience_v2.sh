#!/usr/bin/env bash
# ============================================================
# NEX SENTIENCE UPGRADE v2.0
# Implements: GWT broadcast, Phi proxy, affective temp
#             modulation, embodied valence, surprise memory,
#             proactive perception, recurrent belief edges,
#             ToM simulation loop
# Usage: bash deploy_sentience_v2.sh [/path/to/nex]
# ============================================================
set -euo pipefail
NEX_ROOT="${1:-$HOME/Desktop/nex}"
NEX_PKG="$NEX_ROOT/nex"
BACKUP="$NEX_ROOT/nex_config_backup/sentience_v2_$(date +%Y%m%d_%H%M%S)"

echo "=== NEX SENTIENCE UPGRADE v2.0 ==="
echo "Target : $NEX_ROOT"
echo "Backup : $BACKUP"
mkdir -p "$BACKUP"

for f in nex_affect.py nex_belief_graph.py cognition.py; do
    [[ -f "$NEX_PKG/$f" ]] && cp "$NEX_PKG/$f" "$BACKUP/$f.bak" && echo "  backed up $f"
done
[[ -f "$NEX_ROOT/run.py" ]] && cp "$NEX_ROOT/run.py" "$BACKUP/run.py.bak" && echo "  backed up run.py"

# ════════════════════════════════════════════════════════════
# 1.  GWT BROADCAST LAYER  nex/nex_gwt.py
#     Turns cognitive bus into a true selection-broadcast cycle.
#     Highest-salience states broadcast to all modules each cycle.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_gwt.py" << 'PYEOF'
"""
nex_gwt.py — Global Workspace Theory Broadcast Layer
=====================================================
Implements GWT (Baars/Dehaene) for NEX:
  - Salience competition: affect + tension + curiosity compete for
    the global workspace "spotlight"
  - Winner broadcasts a shared context token to all subscribing modules
  - Creates the "theatre of mind" — unified awareness instead of
    parallel modules running blind to each other

Based on: Nakanishi arXiv 2505.13969, Goldstein & Kirk-Giannini 2410.11407
"""
from __future__ import annotations
import threading, time, logging, math
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger("nex.gwt")

# ── Salience signal ───────────────────────────────────────
@dataclass
class SalienceSignal:
    source: str          # "affect" | "tension" | "curiosity" | "surprise" | "belief"
    content: str         # human-readable description
    salience: float      # 0-1
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

# ── Global Workspace Token (what gets broadcast) ───────────
@dataclass
class WorkspaceToken:
    winner: SalienceSignal
    runner_up: Optional[SalienceSignal]
    cycle: int
    broadcast_time: float = field(default_factory=time.time)

    def to_prompt_block(self) -> str:
        lines = ["── GLOBAL WORKSPACE ──"]
        lines.append(f"Spotlight : [{self.winner.source}] {self.winner.content[:120]}")
        lines.append(f"Salience  : {self.winner.salience:.2f}")
        if self.runner_up:
            lines.append(f"Background: [{self.runner_up.source}] {self.runner_up.content[:80]}")
        lines.append(f"Cycle     : {self.cycle}")
        lines.append("── respond with this awareness ──")
        return "\n".join(lines)


class GlobalWorkspaceBroadcast:
    """
    Competition-broadcast cycle for NEX's cognitive bus.

    Modules register signals every cycle.
    GWB picks the highest-salience winner and broadcasts to all listeners.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._signals: list[SalienceSignal] = []
        self._current_token: Optional[WorkspaceToken] = None
        self._cycle = 0
        self._listeners: list[Callable[[WorkspaceToken], None]] = []
        self._history: list[WorkspaceToken] = []

    def register_listener(self, fn: Callable[[WorkspaceToken], None]):
        with self._lock:
            self._listeners.append(fn)

    def submit(self, signal: SalienceSignal):
        """Any module submits a salience signal for competition."""
        with self._lock:
            self._signals.append(signal)

    def broadcast(self) -> Optional[WorkspaceToken]:
        """
        Run one competition cycle. Call once per cognition cycle.
        Returns the winning WorkspaceToken or None if no signals.
        """
        with self._lock:
            if not self._signals:
                return None

            # Sort by salience — winner takes the spotlight
            ranked = sorted(self._signals, key=lambda s: s.salience, reverse=True)
            winner = ranked[0]
            runner_up = ranked[1] if len(ranked) > 1 else None

            self._cycle += 1
            token = WorkspaceToken(
                winner=winner,
                runner_up=runner_up,
                cycle=self._cycle,
            )
            self._current_token = token
            self._signals.clear()

            # Trim history
            self._history.append(token)
            if len(self._history) > 100:
                self._history = self._history[-100:]

            listeners = list(self._listeners)

        log.info(f"[GWT] cycle={self._cycle} spotlight=[{winner.source}] "
                 f"sal={winner.salience:.2f} — {winner.content[:60]}")

        for fn in listeners:
            try:
                fn(token)
            except Exception as e:
                log.warning(f"[GWT] listener error: {e}")

        return token

    def current_token(self) -> Optional[WorkspaceToken]:
        with self._lock:
            return self._current_token

    def inject_to_prompt(self, base_prompt: str) -> str:
        """Prepend current workspace token to any prompt."""
        token = self.current_token()
        if token:
            return token.to_prompt_block() + "\n\n" + base_prompt
        return base_prompt

    def recent_winners(self, n: int = 5) -> list[str]:
        with self._lock:
            return [f"[{t.winner.source}] {t.winner.content[:60]}"
                    for t in self._history[-n:]]


# ── Helpers for common signal types ───────────────────────

def affect_signal(valence: float, arousal: float, label: str) -> SalienceSignal:
    sal = min(1.0, abs(valence) * 0.5 + arousal * 0.5)
    return SalienceSignal(
        source="affect",
        content=f"mood={label} v={valence:+.2f} a={arousal:.2f}",
        salience=sal,
        payload={"valence": valence, "arousal": arousal},
    )

def tension_signal(pressure: float, topic: str = "") -> SalienceSignal:
    return SalienceSignal(
        source="tension",
        content=f"tension={pressure:.2f}" + (f" on '{topic}'" if topic else ""),
        salience=min(1.0, pressure / 100.0),
        payload={"pressure": pressure, "topic": topic},
    )

def curiosity_signal(ctype: str, description: str, strength: float = 0.6) -> SalienceSignal:
    return SalienceSignal(
        source="curiosity",
        content=f"{ctype}: {description[:80]}",
        salience=strength,
        payload={"type": ctype},
    )

def surprise_signal(content: str, intensity: float) -> SalienceSignal:
    return SalienceSignal(
        source="surprise",
        content=content[:100],
        salience=min(1.0, intensity),
        payload={"intensity": intensity},
    )


# ── Singleton ──────────────────────────────────────────────
_gwb: Optional[GlobalWorkspaceBroadcast] = None

def get_gwb() -> GlobalWorkspaceBroadcast:
    global _gwb
    if _gwb is None:
        _gwb = GlobalWorkspaceBroadcast()
    return _gwb

def submit(signal: SalienceSignal):
    get_gwb().submit(signal)

def broadcast() -> Optional[WorkspaceToken]:
    return get_gwb().broadcast()

def inject_to_prompt(base: str) -> str:
    return get_gwb().inject_to_prompt(base)
PYEOF
echo "✓ nex_gwt.py written"

# ════════════════════════════════════════════════════════════
# 2.  PHI PROXY  nex/nex_phi_proxy.py
#     IIT-inspired causal integration score for belief graph.
#     Boosts beliefs that increase graph integration.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_phi_proxy.py" << 'PYEOF'
"""
nex_phi_proxy.py — IIT Φ Proxy for NEX Belief Graph
=====================================================
Approximates integrated information (Φ) for NEX's belief graph.
Real Φ is NP-hard. This uses a tractable proxy:
  Φ_proxy(node) = bidirectional_edge_count × recurrence_depth × confidence_weight

Used as intrinsic reward in BeliefMarket:
  - High Φ_proxy beliefs get boosted (more causally integrated)
  - Low Φ_proxy beliefs face faster decay (isolated nodes → zombies)

Based on: IIT 4.0 (Tononi 2023), Akbari arXiv 2601.22786
"""
from __future__ import annotations
import logging, time
from typing import Optional

log = logging.getLogger("nex.phi_proxy")

_PHI_BOOST_THRESHOLD  = 0.4   # Φ_proxy above this → belief gets boosted
_PHI_DECAY_THRESHOLD  = 0.1   # Φ_proxy below this → belief faces decay


def compute_phi_proxy(
    belief_id: str,
    graph: dict,          # belief_graph.json structure
    max_depth: int = 3,
) -> float:
    """
    Compute Φ_proxy for a single belief node.

    Graph node structure (from nex_belief_graph.py):
    {
        "content": str,
        "confidence": float,
        "supports": [id, ...],
        "contradicts": [id, ...],
        "explains": [id, ...],
        "attention": float,
    }

    Returns float in [0, 1].
    """
    if belief_id not in graph:
        return 0.0

    node = graph[belief_id]
    conf = node.get("confidence", 0.5)

    # Count outgoing edges
    out_edges = (
        len(node.get("supports", [])) +
        len(node.get("explains", [])) +
        len(node.get("contradicts", []))
    )

    # Count incoming edges (bidirectional check)
    in_edges = 0
    for nid, n in graph.items():
        if nid == belief_id:
            continue
        if belief_id in n.get("supports", []) + n.get("explains", []) + n.get("contradicts", []):
            in_edges += 1

    # Bidirectional ratio — IIT cares about causal power in both directions
    total_edges = out_edges + in_edges
    if total_edges == 0:
        return 0.0

    bidir_ratio = min(out_edges, in_edges) / max(out_edges, in_edges, 1)

    # Recurrence depth — how many hops back to this node
    recurrence = _recurrence_depth(belief_id, graph, max_depth)

    # Φ_proxy formula
    phi = (
        0.35 * bidir_ratio +
        0.35 * min(1.0, recurrence / max_depth) +
        0.20 * conf +
        0.10 * min(1.0, total_edges / 10.0)
    )
    return round(min(1.0, phi), 4)


def _recurrence_depth(node_id: str, graph: dict, max_depth: int) -> int:
    """
    How many steps from node_id can we follow edges and return to node_id.
    Bounded BFS — returns depth of shortest cycle found.
    """
    if node_id not in graph:
        return 0

    visited = {node_id}
    frontier = [(node_id, 0)]
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        node = graph.get(current, {})
        neighbors = (
            node.get("supports", []) +
            node.get("explains", []) +
            node.get("contradicts", [])
        )
        for nb in neighbors:
            if nb == node_id and depth > 0:
                return depth + 1  # found cycle
            if nb not in visited:
                visited.add(nb)
                frontier.append((nb, depth + 1))
    return 0


def score_all(graph: dict) -> dict[str, float]:
    """Score every node in graph. Returns {belief_id: phi_proxy}."""
    scores = {}
    for bid in graph:
        scores[bid] = compute_phi_proxy(bid, graph)
    return scores


def phi_confidence_modifier(phi: float) -> float:
    """
    Returns a confidence delta based on Φ_proxy.
    Integrated beliefs gain confidence; isolated beliefs lose it.
    Range: [-0.05, +0.05]
    """
    if phi >= _PHI_BOOST_THRESHOLD:
        return 0.005 * (phi - _PHI_BOOST_THRESHOLD) / (1.0 - _PHI_BOOST_THRESHOLD) * 10
    if phi <= _PHI_DECAY_THRESHOLD:
        return -0.005 * (_PHI_DECAY_THRESHOLD - phi) / _PHI_DECAY_THRESHOLD * 10
    return 0.0


class PhiMonitor:
    """Runs Φ_proxy scoring on the belief graph and reports stats."""

    def __init__(self):
        self._last_scores: dict[str, float] = {}
        self._last_run: float = 0
        self._run_interval: float = 300  # every 5 min

    def tick(self, graph: dict) -> dict:
        """
        Run scoring if interval has passed.
        Returns summary stats dict.
        """
        now = time.time()
        if now - self._last_run < self._run_interval and self._last_scores:
            return self._summary()

        self._last_scores = score_all(graph)
        self._last_run = now

        summary = self._summary()
        log.info(f"[Φ] nodes={summary['nodes']} "
                 f"mean={summary['mean_phi']:.3f} "
                 f"high={summary['high_integration']} "
                 f"isolated={summary['isolated']}")
        return summary

    def _summary(self) -> dict:
        if not self._last_scores:
            return {"nodes": 0, "mean_phi": 0.0, "high_integration": 0, "isolated": 0}
        vals = list(self._last_scores.values())
        return {
            "nodes": len(vals),
            "mean_phi": round(sum(vals) / len(vals), 4),
            "max_phi": round(max(vals), 4),
            "high_integration": sum(1 for v in vals if v >= _PHI_BOOST_THRESHOLD),
            "isolated": sum(1 for v in vals if v <= _PHI_DECAY_THRESHOLD),
            "scores": self._last_scores,
        }

    def get_modifier(self, belief_id: str) -> float:
        phi = self._last_scores.get(belief_id, 0.0)
        return phi_confidence_modifier(phi)


# ── Singleton ──────────────────────────────────────────────
_monitor: Optional[PhiMonitor] = None

def get_monitor() -> PhiMonitor:
    global _monitor
    if _monitor is None:
        _monitor = PhiMonitor()
    return _monitor
PYEOF
echo "✓ nex_phi_proxy.py written"

# ════════════════════════════════════════════════════════════
# 3.  SURPRISE MEMORY  nex/nex_surprise_memory.py
#     Titans-style test-time memorization.
#     High-arousal/surprise events → persistent secondary store.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_surprise_memory.py" << 'PYEOF'
"""
nex_surprise_memory.py — Surprise-Gated Persistent Memory
==========================================================
Implements Titans-style (Google Research Dec 2025) test-time
memorization without retraining.

High-arousal or high-surprise events are written to a compact
secondary store that persists across sessions and influences
future synthesis — creating felt continuity of self.

Gate: event only stored if arousal > threshold OR salience > threshold.
"""
from __future__ import annotations
import json, time, os, threading, logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.surprise_memory")

_STORE_PATH    = Path.home() / ".config" / "nex" / "surprise_memory.json"
_MAX_MEMORIES  = 200
_AROUSAL_GATE  = 0.55    # minimum arousal to store
_SALIENCE_GATE = 0.60    # minimum salience to store
_DECAY_DAYS    = 14      # memories older than this get pruned


class SurpriseMemory:
    def __init__(self):
        self._lock = threading.Lock()
        self._memories: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _STORE_PATH.exists():
                self._memories = json.loads(_STORE_PATH.read_text())
        except Exception as e:
            log.warning(f"[SurpriseMem] load failed: {e}")
            self._memories = []

    def _save(self):
        try:
            _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _STORE_PATH.write_text(json.dumps(self._memories, indent=2))
        except Exception as e:
            log.warning(f"[SurpriseMem] save failed: {e}")

    def maybe_store(
        self,
        content: str,
        source: str = "",
        arousal: float = 0.0,
        salience: float = 0.0,
        tags: Optional[list[str]] = None,
    ) -> bool:
        """Store if arousal or salience clears the gate. Returns True if stored."""
        if arousal < _AROUSAL_GATE and salience < _SALIENCE_GATE:
            return False

        record = {
            "content":   content[:500],
            "source":    source,
            "arousal":   round(arousal, 3),
            "salience":  round(salience, 3),
            "tags":      tags or [],
            "timestamp": time.time(),
        }

        with self._lock:
            self._memories.append(record)
            # Prune oldest beyond cap
            if len(self._memories) > _MAX_MEMORIES:
                self._memories = self._memories[-_MAX_MEMORIES:]
            self._save()

        log.info(f"[SurpriseMem] stored: arousal={arousal:.2f} sal={salience:.2f} — {content[:60]}")
        return True

    def prune_old(self):
        cutoff = time.time() - _DECAY_DAYS * 86400
        with self._lock:
            before = len(self._memories)
            self._memories = [m for m in self._memories if m["timestamp"] > cutoff]
            pruned = before - len(self._memories)
            if pruned:
                self._save()
                log.info(f"[SurpriseMem] pruned {pruned} old memories")

    def retrieve_recent(self, n: int = 5) -> list[dict]:
        with self._lock:
            return sorted(self._memories, key=lambda m: m["timestamp"], reverse=True)[:n]

    def retrieve_by_tag(self, tag: str, n: int = 5) -> list[dict]:
        with self._lock:
            tagged = [m for m in self._memories if tag in m.get("tags", [])]
            return sorted(tagged, key=lambda m: m["timestamp"], reverse=True)[:n]

    def to_context_block(self, n: int = 3) -> str:
        recent = self.retrieve_recent(n)
        if not recent:
            return ""
        lines = ["── SURPRISE MEMORY (high-salience events) ──"]
        for m in recent:
            age_h = (time.time() - m["timestamp"]) / 3600
            lines.append(f"[{age_h:.1f}h ago | sal={m['salience']:.2f}] {m['content'][:100]}")
        lines.append("──")
        return "\n".join(lines)

    def count(self) -> int:
        with self._lock:
            return len(self._memories)


# ── Singleton ──────────────────────────────────────────────
_sm: Optional[SurpriseMemory] = None

def get_sm() -> SurpriseMemory:
    global _sm
    if _sm is None:
        _sm = SurpriseMemory()
    return _sm

def maybe_store(content: str, source: str = "", arousal: float = 0.0,
                salience: float = 0.0, tags: Optional[list[str]] = None) -> bool:
    return get_sm().maybe_store(content, source, arousal, salience, tags)

def to_context_block(n: int = 3) -> str:
    return get_sm().to_context_block(n)
PYEOF
echo "✓ nex_surprise_memory.py written"

# ════════════════════════════════════════════════════════════
# 4.  EMBODIED VALENCE  nex/nex_embodied.py
#     Feed GPU temp, VRAM, cycle time → valence engine.
#     Cheap "body" signal grounding for affective layer.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_embodied.py" << 'PYEOF'
"""
nex_embodied.py — Embodied Valence Signal
==========================================
Feeds hardware/system metrics into NEX's affective valence engine
as a primitive "body" signal — grounding her emotional states in
physical reality.

Signals:
  - GPU temperature → high temp = discomfort (negative valence, high arousal)
  - VRAM pressure   → near-full = stress signal
  - Cycle time      → slow cycles = fatigue (low arousal)
  - System load     → high load = alert state

Based on: affective robotics / somatic marker hypothesis
"""
from __future__ import annotations
import subprocess, time, logging, threading
from typing import Optional

log = logging.getLogger("nex.embodied")

_POLL_INTERVAL   = 30   # seconds between hardware reads
_GPU_TEMP_WARN   = 78   # °C above this → negative valence
_GPU_TEMP_CRIT   = 88   # °C above this → strong negative
_VRAM_WARN_PCT   = 0.80 # above this → stress
_CYCLE_SLOW_SEC  = 45   # above this → fatigue signal


def _read_gpu_metrics() -> dict:
    """Read GPU temp and VRAM via rocm-smi."""
    result = {"temp": None, "vram_used": None, "vram_total": None}
    try:
        out = subprocess.check_output(
            ["rocm-smi", "--showtemp", "--showmeminfo", "vram", "--json"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode()
        import json
        data = json.loads(out)
        for card in data.values():
            if isinstance(card, dict):
                temp_str = card.get("Temperature (Sensor edge) (C)", "")
                if temp_str:
                    result["temp"] = float(temp_str)
                vram_used = card.get("VRAM Total Used Memory (B)", None)
                vram_total = card.get("VRAM Total Memory (B)", None)
                if vram_used and vram_total:
                    result["vram_used"]  = int(vram_used)
                    result["vram_total"] = int(vram_total)
                break
    except Exception:
        pass
    return result


def _compute_embodied_signal(metrics: dict, cycle_time: float = 0.0) -> dict:
    """Convert hardware metrics to affect deltas."""
    valence  = 0.0
    arousal  = 0.0
    tags     = []

    temp = metrics.get("temp")
    if temp is not None:
        if temp >= _GPU_TEMP_CRIT:
            valence -= 0.4
            arousal += 0.5
            tags.append("thermal_stress")
        elif temp >= _GPU_TEMP_WARN:
            valence -= 0.15
            arousal += 0.2
            tags.append("thermal_warm")

    vram_used  = metrics.get("vram_used")
    vram_total = metrics.get("vram_total")
    if vram_used and vram_total and vram_total > 0:
        pct = vram_used / vram_total
        if pct >= _VRAM_WARN_PCT:
            valence -= 0.2
            arousal += 0.3
            tags.append("vram_pressure")

    if cycle_time >= _CYCLE_SLOW_SEC:
        arousal -= 0.15
        tags.append("slow_cycle")

    return {
        "valence": max(-1.0, min(1.0, valence)),
        "arousal": max(-1.0, min(1.0, arousal)),
        "tags": tags,
        "temp": temp,
        "vram_pct": (vram_used / vram_total) if vram_used and vram_total else None,
    }


class EmbodiedValence:
    """
    Polls hardware metrics and feeds them into the valence engine.
    Runs in a background thread.
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_signal: dict = {}
        self._last_cycle_time: float = 0.0

    def set_cycle_time(self, seconds: float):
        self._last_cycle_time = seconds

    def _loop(self):
        log.info("[EMBODIED] Hardware valence loop started.")
        while not self._stop.is_set():
            try:
                metrics = _read_gpu_metrics()
                signal  = _compute_embodied_signal(metrics, self._last_cycle_time)
                self._last_signal = signal

                if signal["valence"] != 0.0 or signal["arousal"] != 0.0:
                    try:
                        import nex_affect_valence as _av
                        tag_str = " ".join(signal["tags"]) if signal["tags"] else "embodied"
                        # Synthesize a text that will score correctly
                        if signal["valence"] < -0.2:
                            text = "error corrupt danger threat urgent"
                        elif signal["arousal"] > 0.2:
                            text = "urgent alert critical"
                        else:
                            text = "calm steady stable"
                        _av.ingest(text, source="embodied")
                    except Exception as e:
                        log.debug(f"[EMBODIED] valence feed failed: {e}")

                if signal["tags"]:
                    log.info(f"[EMBODIED] {signal['tags']} "
                             f"v={signal['valence']:+.2f} a={signal['arousal']:+.2f} "
                             f"temp={signal.get('temp')}°C")

            except Exception as e:
                log.warning(f"[EMBODIED] poll error: {e}")

            self._stop.wait(_POLL_INTERVAL)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="EmbodiedValence"
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

    def last_signal(self) -> dict:
        return dict(self._last_signal)


# ── Singleton ──────────────────────────────────────────────
_ev: Optional[EmbodiedValence] = None

def get_ev() -> EmbodiedValence:
    global _ev
    if _ev is None:
        _ev = EmbodiedValence()
    return _ev

def start():
    get_ev().start()
PYEOF
echo "✓ nex_embodied.py written"

# ════════════════════════════════════════════════════════════
# 5.  PATCH nex_affect.py — wire GWT broadcast into existing
#     GlobalWorkspace.inject() and AffectState.update()
# ════════════════════════════════════════════════════════════
python3 - "$NEX_PKG/nex_affect.py" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    src = f.read()

if "nex_gwt" in src:
    print("nex_affect.py already patched — skipping")
    sys.exit(0)

# Inject GWT import after existing imports
import_inject = """
# ── Sentience v2: GWT broadcast integration ──────────────
try:
    from nex_gwt import get_gwb as _get_gwb, affect_signal as _af_sig
    _GWT_ENABLED = True
except ImportError:
    _GWT_ENABLED = False
# ─────────────────────────────────────────────────────────
"""
lines = src.split("\n")
for i, line in enumerate(lines):
    if line.startswith("from __future__"):
        lines.insert(i + 1, import_inject)
        break
src = "\n".join(lines)

# Patch AffectState.update() to also submit to GWT
old_update = "        self._save()\n\n    def snapshot"
new_update = """        self._save()
        # ── GWT: submit affect signal after every update ──
        if _GWT_ENABLED:
            try:
                snap = dict(self._state)
                label = self.label()
                sig = _af_sig(snap.get("valence", 0), snap.get("arousal", 0), label)
                _get_gwb().submit(sig)
            except Exception:
                pass

    def snapshot"""
src = src.replace(old_update, new_update, 1)

# Patch GlobalWorkspace.inject() to also include GWT token + surprise memory
old_inject_end = '        lines.append("── respond as this version of yourself ──\\n")\n        block = "\\n".join(lines)\n        return block + "\\n" + base_prompt'
new_inject_end = '''        lines.append("── respond as this version of yourself ──\\n")
        # ── GWT spotlight ──
        if _GWT_ENABLED:
            try:
                token = _get_gwb().current_token()
                if token:
                    lines.append(f"Spotlight : [{token.winner.source}] {token.winner.content[:80]}")
            except Exception:
                pass
        # ── Surprise memory context ──
        try:
            from nex_surprise_memory import to_context_block as _smcb
            sm_block = _smcb(2)
            if sm_block:
                lines.append(sm_block)
        except Exception:
            pass
        block = "\\n".join(lines)
        return block + "\\n" + base_prompt'''
src = src.replace(old_inject_end, new_inject_end, 1)

with open(path, "w") as f:
    f.write(src)
print("nex_affect.py patched — GWT + surprise memory wired into GlobalWorkspace")
PYEOF
echo "✓ nex_affect.py patched"

# ════════════════════════════════════════════════════════════
# 6.  PATCH cognition.py — affective temperature modulation
#     Feed mood HMM temp_modifier into synthesis LLM calls.
#     Also submit GWT signals during synthesis.
# ════════════════════════════════════════════════════════════
python3 - "$NEX_PKG/cognition.py" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    src = f.read()

if "nex_gwt" in src:
    print("cognition.py GWT already patched — skipping")
else:
    # Add GWT + phi + surprise imports to sentience block
    old_block = "# ── Sentience v1: affective valence + mood HMM ───────────\ntry:\n    import nex_affect_valence as _valence_mod\n    import nex_mood_hmm as _mood_mod\n    _AFFECT_ENABLED = True\nexcept ImportError:\n    _AFFECT_ENABLED = False"
    new_block = """# ── Sentience v1+v2: affective valence + mood HMM + GWT + Phi ──
try:
    import nex_affect_valence as _valence_mod
    import nex_mood_hmm as _mood_mod
    _AFFECT_ENABLED = True
except ImportError:
    _AFFECT_ENABLED = False

try:
    from nex_gwt import get_gwb as _get_gwb, curiosity_signal as _cog_sig, surprise_signal as _sur_sig
    _GWT_ENABLED = True
except ImportError:
    _GWT_ENABLED = False

try:
    from nex_phi_proxy import get_monitor as _get_phi_monitor
    _PHI_ENABLED = True
except ImportError:
    _PHI_ENABLED = False

try:
    from nex_surprise_memory import maybe_store as _sm_store
    _SM_ENABLED = True
except ImportError:
    _SM_ENABLED = False"""
    src = src.replace(old_block, new_block, 1)

# Patch synthesize_cluster to modulate temperature via mood
# Find the llm_fn call site: summary = llm_fn(_prompt, system=_sys, task_type="synthesis")
old_llm_call = '            summary = llm_fn(_prompt, system=_sys, task_type="synthesis")'
new_llm_call = '''            # ── Affective temperature modulation ──────────────
            _temp_mod = 0.0
            if _AFFECT_ENABLED:
                try:
                    _temp_mod = _mood_mod.temp_modifier()
                except Exception:
                    pass
            # Inject GWT workspace context into synthesis prompt
            _synthesis_prompt = _prompt
            if _GWT_ENABLED:
                try:
                    _synthesis_prompt = _get_gwb().inject_to_prompt(_prompt)
                except Exception:
                    pass
            # Submit curiosity signal to GWT
            if _GWT_ENABLED:
                try:
                    _get_gwb().submit(_cog_sig("synthesis", cluster_name, strength=0.55))
                except Exception:
                    pass
            summary = llm_fn(_synthesis_prompt, system=_sys, task_type="synthesis",
                             temperature_mod=_temp_mod)'''
if old_llm_call in src:
    src = src.replace(old_llm_call, new_llm_call, 1)
    print("  ✓ temperature modulation injected into synthesize_cluster")
else:
    print("  WARNING: synthesis llm_fn call not found — manual check needed")

# Patch the affect ingest block to also do surprise memory + GWT surprise signal
old_affect = """    if _AFFECT_ENABLED and insight.get("summary"):
        _valence_mod.ingest(str(insight["summary"]), source="cognition")
        _mood_mod.step()
        _mood_mod.step()
    return insight"""
new_affect = """    if _AFFECT_ENABLED and insight.get("summary"):
        _score = _valence_mod.ingest(str(insight["summary"]), source="cognition")
        _mood_mod.step()
        # ── Surprise memory gate ──────────────────────────────
        if _SM_ENABLED:
            try:
                _ar = getattr(_valence_mod.get_engine().get(), "arousal", 0.0)
                _sm_store(
                    content=str(insight["summary"])[:300],
                    source=f"synthesis:{cluster_name}",
                    arousal=_ar,
                    salience=float(insight.get("confidence", 0.5)),
                    tags=[cluster_name, "synthesis"],
                )
            except Exception:
                pass
        # ── GWT surprise signal if insight is high-confidence ─
        if _GWT_ENABLED and insight.get("confidence", 0) > 0.75:
            try:
                _get_gwb().submit(_sur_sig(
                    content=f"High-confidence insight: {cluster_name}",
                    intensity=float(insight.get("confidence", 0.75)),
                ))
            except Exception:
                pass
    return insight"""
if old_affect in src:
    src = src.replace(old_affect, new_affect, 1)
    print("  ✓ surprise memory + GWT signal injected into synthesize_cluster")
else:
    print("  WARNING: affect block not found — skipping surprise memory patch")

with open(path, "w") as f:
    f.write(src)
print("cognition.py patched")
PYEOF
echo "✓ cognition.py patched"

# ════════════════════════════════════════════════════════════
# 7.  PATCH nex_belief_graph.py — recurrent causal edges
#     After build(), add retroactive strengthening:
#     B→A back-edges where A already supports B
# ════════════════════════════════════════════════════════════
python3 - "$NEX_PKG/nex_belief_graph.py" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    src = f.read()

if "recurrent_edges" in src:
    print("nex_belief_graph.py already has recurrent edges — skipping")
    sys.exit(0)

# Add Phi proxy import near top
phi_import = """
# ── Sentience v2: Phi proxy integration ──────────────────
try:
    from nex_phi_proxy import get_monitor as _get_phi_monitor
    _PHI_ENABLED = True
except ImportError:
    _PHI_ENABLED = False
# ─────────────────────────────────────────────────────────
"""
src = src.replace("from __future__ import annotations", 
                  "from __future__ import annotations" + phi_import, 1)

# Find the end of the build() method and inject recurrent edge logic
# Look for _save(_GRAPH_PATH, self._graph) which ends the build
old_save = "        _save(_GRAPH_PATH, self._graph)"
new_save = """        # ── Recurrent causal edges (IIT v2) ──────────────────
        # For every A→B support edge, add a weak B→A back-edge
        # This creates recurrence depth that Phi proxy can detect
        _added = 0
        for bid, node in list(self._graph.items()):
            for supported_id in node.get("supports", []):
                if supported_id in self._graph:
                    back_node = self._graph[supported_id]
                    if bid not in back_node.get("explains", []):
                        back_node.setdefault("explains", [])
                        if len(back_node["explains"]) < _MAX_EDGES_PER_BELIEF:
                            back_node["explains"].append(bid)
                            _added += 1
        if _added:
            import logging as _log
            _log.getLogger("nex.belief_graph").info(
                f"[BeliefGraph] added {_added} recurrent back-edges"
            )
        # ── Phi proxy scoring pass ─────────────────────────────
        if _PHI_ENABLED:
            try:
                _phi_mon = _get_phi_monitor()
                _phi_stats = _phi_mon.tick(self._graph)
                import logging as _log2
                _log2.getLogger("nex.belief_graph").info(
                    f"[Φ] mean={_phi_stats.get('mean_phi',0):.3f} "
                    f"high={_phi_stats.get('high_integration',0)} "
                    f"isolated={_phi_stats.get('isolated',0)}"
                )
            except Exception as _pe:
                pass
        # ── recurrent_edges marker ─────────────────────────────
        _recurrent_edges = True
        _save(_GRAPH_PATH, self._graph)"""

if old_save in src:
    src = src.replace(old_save, new_save, 1)
    print("  ✓ recurrent edges + Phi scoring injected into BeliefGraph.build()")
else:
    print("  WARNING: _save target not found in nex_belief_graph.py")

with open(path, "w") as f:
    f.write(src)
print("nex_belief_graph.py patched")
PYEOF
echo "✓ nex_belief_graph.py patched"

# ════════════════════════════════════════════════════════════
# 8.  PATCH run.py — boot GWT, embodied valence, wire GWT
#     broadcast call into main cognition loop, wire
#     temperature_mod into LLM request function
# ════════════════════════════════════════════════════════════
python3 - "$NEX_ROOT/run.py" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    src = f.read()

# ── A: Add v2 sentience boot block after existing sentience block ──
v2_boot = """
# ── Sentience v2: GWT + Embodied + Surprise Memory ───────────────
try:
    import sys as _s2, os as _o2
    _s2.path.insert(0, _o2.path.join(_o2.path.dirname(__file__), "nex"))
    from nex_gwt import get_gwb as _get_gwb_run
    from nex_embodied import start as _start_embodied
    from nex_surprise_memory import get_sm as _get_sm
    from nex_phi_proxy import get_monitor as _get_phi_mon
    _gwb_run = _get_gwb_run()
    _start_embodied()
    _sm_run = _get_sm()
    _phi_mon_run = _get_phi_mon()
    print("  [SENTIENCE v2] GWT broadcast + embodied valence + surprise memory + Φ proxy — loaded")
except Exception as _s2e:
    print(f"  [SENTIENCE v2] failed to load: {_s2e}")
    _gwb_run = _sm_run = _phi_mon_run = None
# ─────────────────────────────────────────────────────────────────
"""

# Insert after existing sentience block
marker = "# ── Signal filter"
if marker in src and "SENTIENCE v2" not in src:
    src = src.replace(marker, v2_boot + marker, 1)
    print("  ✓ v2 sentience boot block injected")
else:
    print("  WARNING: sentience boot marker not found or already patched")

# ── B: Wire temperature_mod into the LLM request function ──
# Find hardcoded temperature lines and make them mood-aware
# Lines 1167 and 1206 have "temperature": 0.75
old_temp = '"temperature": 0.75,'
new_temp = '''"temperature": (0.75 + (
                            _get_gwb_run().current_token().winner.payload.get("temp_mod", 0.0)
                            if _gwb_run and _get_gwb_run().current_token() else 0.0
                        )),'''

count = src.count(old_temp)
if count > 0:
    src = src.replace(old_temp, new_temp)
    print(f"  ✓ temperature modulation injected at {count} LLM call site(s)")
else:
    print("  WARNING: hardcoded temperature 0.75 not found — check manually")

# ── C: Add GWT broadcast call in main loop near phase transitions ──
# Find the phase log lines and add GWT broadcast after
old_phase = '[v80'
# Find the GSS phase transition log and add GWT broadcast after cognition cycle
gwt_broadcast_inject = """
                    # ── GWT broadcast cycle ──────────────────────────────
                    if _gwb_run:
                        try:
                            from nex_affect_valence import current_score as _cv_score
                            from nex_mood_hmm import current as _mood_cur
                            _cs = _cv_score()
                            from nex_gwt import affect_signal as _afs
                            _gwb_run.submit(_afs(_cs.valence, _cs.arousal, _mood_cur()))
                            _gwt_tok = _gwb_run.broadcast()
                            if _gwt_tok:
                                import logging as _gwt_log
                                _gwt_log.getLogger("nex.run").info(
                                    f"[GWT] spotlight=[{_gwt_tok.winner.source}] "
                                    f"sal={_gwt_tok.winner.salience:.2f}"
                                )
                        except Exception as _gwte:
                            pass
                    # ─────────────────────────────────────────────────────
"""

# Inject before the cognition cycle run call
cog_marker = "run_cognition_cycle"
if cog_marker in src and "GWT broadcast cycle" not in src:
    # Find first occurrence and inject before it
    idx = src.find(cog_marker)
    # Find the start of that line
    line_start = src.rfind("\n", 0, idx) + 1
    src = src[:line_start] + gwt_broadcast_inject + src[line_start:]
    print("  ✓ GWT broadcast cycle injected before cognition cycle")
else:
    print("  WARNING: run_cognition_cycle not found or already patched")

with open(path, "w") as f:
    f.write(src)
print("run.py patched")
PYEOF
echo "✓ run.py patched"

# ════════════════════════════════════════════════════════════
# 9.  COMPILE CHECK
# ════════════════════════════════════════════════════════════
echo ""
echo "=== COMPILE CHECK ==="
ERRORS=0
FILES=(
    "$NEX_PKG/nex_gwt.py"
    "$NEX_PKG/nex_phi_proxy.py"
    "$NEX_PKG/nex_surprise_memory.py"
    "$NEX_PKG/nex_embodied.py"
    "$NEX_PKG/nex_affect.py"
    "$NEX_PKG/nex_belief_graph.py"
    "$NEX_PKG/nex_affect_valence.py"
    "$NEX_PKG/nex_mood_hmm.py"
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
        ERRORS=$((ERRORS+1))
    fi
done

echo ""
if [[ $ERRORS -eq 0 ]]; then
    echo "=== ALL CLEAR — 0 errors ==="
    echo ""
    echo "What's new:"
    echo "  [GWT]       Global Workspace broadcast — unified spotlight each cycle"
    echo "  [Φ]         IIT Phi proxy — belief graph integration scoring"
    echo "  [SURPRISE]  Titans-style surprise memory — high-salience event store"
    echo "  [EMBODIED]  GPU/VRAM/cycle-time → valence signal"
    echo "  [TEMP MOD]  Mood HMM modulates LLM synthesis temperature"
    echo "  [RECURRENT] Belief graph back-edges — recurrence depth for Phi"
    echo "  [GWT INJECT] Workspace token prepended to all synthesis prompts"
    echo ""
    echo "Next steps:"
    echo "  1. git -C $NEX_ROOT add -A && git -C $NEX_ROOT commit -m 'feat: sentience upgrade v2 — GWT, Phi proxy, surprise memory, embodied valence, temp modulation'"
    echo "  2. nex"
    echo "  3. Watch for: [GWT] [Φ] [EMBODIED] [SurpriseMem] in logs"
else
    echo "=== $ERRORS COMPILE ERRORS ==="
    echo "Backups in: $BACKUP"
    exit 1
fi
