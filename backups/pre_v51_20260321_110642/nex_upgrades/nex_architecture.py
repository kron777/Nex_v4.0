"""
NEX ARCHITECTURE v2 — Upgrade 1
Formalizes the full agent stack into explicit modules.
Replaces ad-hoc wiring with a central ControlLayer coordinator.

Modules:
  Perception   → input ingestion + trust scoring
  Cognition    → belief synthesis (existing, now gated)
  Planning     → goal/task decomposition (NEW)
  Action       → output execution (existing, now governed)
  Memory       → 4-layer store (NEW)
  Control      → governance / coordination hub (NEW)
"""

from __future__ import annotations
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable, Any

log = logging.getLogger("nex.architecture")


# ─────────────────────────────────────────────
# DATA CONTRACTS
# ─────────────────────────────────────────────

@dataclass
class PerceptionEvent:
    """Normalised input event entering the agent stack."""
    id:         str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source:     str   = ""          # platform / agent id
    content:    str   = ""
    trust:      float = 0.5         # [0,1] — set by U12 signal filter
    novelty:    float = 0.5         # [0,1] — set by Attention module
    relevance:  float = 0.5         # [0,1] — goal alignment score
    timestamp:  float = field(default_factory=time.time)
    raw:        Any   = None        # original payload preserved


@dataclass
class ActionIntent:
    """Proposed action waiting for governance sign-off."""
    id:          str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    action_type: str   = ""         # post / reply / internal / skip
    platform:    str   = ""
    content:     str   = ""
    risk_score:  float = 0.0        # 0=safe, 1=dangerous
    approved:    bool  = False
    timestamp:   float = field(default_factory=time.time)


# ─────────────────────────────────────────────
# CONTROL LAYER — central coordinator
# ─────────────────────────────────────────────

class ControlLayer:
    """
    Single chokepoint that routes every signal through all modules in order:
      Perception → Attention → Cognition → Planning → Action → Memory → Log

    All modules register themselves here at startup.
    """

    def __init__(self):
        self._modules: dict[str, Any] = {}
        self._hooks:   list[Callable] = []
        self._trace:   list[dict]     = []   # full decision trace, last 500 cycles
        self._cycle:   int            = 0

    # ── registration ──────────────────────────
    def register(self, name: str, module: Any) -> None:
        self._modules[name] = module
        log.info(f"[CONTROL] registered module: {name}")

    def get(self, name: str) -> Any:
        return self._modules.get(name)

    def add_hook(self, fn: Callable) -> None:
        """Post-cycle hook (observability, tests, etc.)."""
        self._hooks.append(fn)

    # ── main gate ─────────────────────────────
    def run_cycle(self, raw_input: dict) -> dict:
        """
        Execute one full RETRIEVE → THINK → EVALUATE → DECIDE → ACT → STORE cycle.
        Returns a trace dict with every phase result.
        """
        self._cycle += 1
        cycle_id = self._cycle
        trace = {"cycle": cycle_id, "ts": time.time(), "phases": {}}

        try:
            # PHASE 1 — PERCEPTION
            perception_mod = self.get("perception")
            event: PerceptionEvent = (
                perception_mod.ingest(raw_input) if perception_mod
                else PerceptionEvent(**{k: raw_input.get(k, "") for k in ["source", "content"]})
            )
            trace["phases"]["perception"] = {"event_id": event.id, "trust": event.trust}

            # PHASE 2 — ATTENTION GATE
            attention_mod = self.get("attention")
            if attention_mod and not attention_mod.should_process(event):
                trace["phases"]["attention"] = "FILTERED"
                self._store_trace(trace)
                return trace

            trace["phases"]["attention"] = "PASS"

            # PHASE 3 — COGNITION (existing belief engine, now gated)
            cognition_mod = self.get("cognition")
            cog_result = cognition_mod.process(event) if cognition_mod else {}
            trace["phases"]["cognition"] = cog_result

            # PHASE 4 — PLANNING
            planning_mod = self.get("planning")
            plan = planning_mod.decompose(cog_result) if planning_mod else {}
            trace["phases"]["planning"] = plan

            # PHASE 5 — ACTION DECISION
            action_mod = self.get("action")
            intent: ActionIntent = (
                action_mod.decide(event, cog_result, plan) if action_mod
                else ActionIntent(action_type="skip")
            )
            trace["phases"]["action_intent"] = {
                "type": intent.action_type,
                "risk": intent.risk_score,
                "approved": intent.approved,
            }

            # PHASE 6 — GOVERNANCE CHECK
            governance_mod = self.get("governance")
            if governance_mod:
                intent = governance_mod.validate(intent)
            trace["phases"]["governance"] = intent.approved

            # PHASE 7 — EXECUTE
            if intent.approved and action_mod:
                result = action_mod.execute(intent)
                trace["phases"]["execution"] = result

            # PHASE 8 — MEMORY STORE
            memory_mod = self.get("memory")
            if memory_mod:
                memory_mod.store_cycle(trace)
            trace["phases"]["memory"] = "stored"

        except Exception as exc:
            trace["error"] = str(exc)
            log.error(f"[CONTROL] cycle {cycle_id} error: {exc}", exc_info=True)

        self._store_trace(trace)

        # post-cycle hooks
        for hook in self._hooks:
            try:
                hook(trace)
            except Exception as e:
                log.warning(f"[CONTROL] hook error: {e}")

        return trace

    # ── trace management ──────────────────────
    def _store_trace(self, trace: dict) -> None:
        self._trace.append(trace)
        if len(self._trace) > 500:
            self._trace = self._trace[-500:]

    def get_trace(self, last_n: int = 10) -> list[dict]:
        return self._trace[-last_n:]

    def replay(self, cycle_id: int) -> Optional[dict]:
        for t in self._trace:
            if t.get("cycle") == cycle_id:
                return t
        return None

    def stats(self) -> dict:
        errors = sum(1 for t in self._trace if "error" in t)
        filtered = sum(1 for t in self._trace if t.get("phases", {}).get("attention") == "FILTERED")
        return {
            "total_cycles": self._cycle,
            "traced":       len(self._trace),
            "errors":       errors,
            "filtered":     filtered,
            "modules":      list(self._modules.keys()),
        }


# ─────────────────────────────────────────────
# PERCEPTION MODULE
# ─────────────────────────────────────────────

class PerceptionModule:
    """
    Normalises raw platform inputs into PerceptionEvents.
    Applies trust scoring (U12) and novelty estimation.
    """

    def __init__(self, trust_registry: Optional[dict] = None):
        self._trust_registry: dict[str, float] = trust_registry or {}
        self._seen_hashes: set[int] = set()

    def ingest(self, raw: dict) -> PerceptionEvent:
        source  = raw.get("source", "unknown")
        content = raw.get("content", "")
        trust   = self._trust_registry.get(source, 0.5)

        # novelty: penalise exact duplicates
        h = hash(content)
        novelty = 0.1 if h in self._seen_hashes else 0.8
        self._seen_hashes.add(h)
        if len(self._seen_hashes) > 10_000:
            self._seen_hashes = set(list(self._seen_hashes)[-5_000:])

        return PerceptionEvent(
            source=source,
            content=content,
            trust=trust,
            novelty=novelty,
            raw=raw,
        )

    def update_trust(self, source: str, delta: float) -> None:
        current = self._trust_registry.get(source, 0.5)
        self._trust_registry[source] = max(0.0, min(1.0, current + delta))


# ─────────────────────────────────────────────
# SINGLETON CONTROL INSTANCE
# ─────────────────────────────────────────────

_control: Optional[ControlLayer] = None

def get_control() -> ControlLayer:
    global _control
    if _control is None:
        _control = ControlLayer()
        log.info("[CONTROL] ControlLayer instantiated")
    return _control
