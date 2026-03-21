"""
NEX COGNITIVE LOOP v2 — Upgrade 2
Structured 6-phase loop with control gating + full decision trace.

Phases:
  RETRIEVE  → pull relevant beliefs/context from memory
  THINK     → LLM reasoning pass
  EVALUATE  → score output quality + belief overlap (U11)
  DECIDE    → action selection with risk gate
  ACT       → execute or queue
  STORE     → persist beliefs, trace, outcomes
"""

from __future__ import annotations
import time
import json
import logging
import hashlib
from dataclasses import dataclass, field
from typing import Optional, Any

log = logging.getLogger("nex.cognitive_loop")


# ─────────────────────────────────────────────
# PHASE RESULT CONTAINERS
# ─────────────────────────────────────────────

@dataclass
class RetrieveResult:
    beliefs:    list[dict] = field(default_factory=list)   # top-K relevant beliefs
    episodes:   list[dict] = field(default_factory=list)   # recent episodic context
    intent:     str        = ""                             # active U9 intent
    latency_ms: float      = 0.0

@dataclass
class ThinkResult:
    raw_response:  str   = ""
    reasoning:     str   = ""
    proposed_text: str   = ""
    token_count:   int   = 0
    latency_ms:    float = 0.0
    error:         str   = ""

@dataclass
class EvaluateResult:
    quality_score:    float = 0.0   # [0,1]
    belief_overlap:   float = 0.0   # U11 — must be >0 to pass
    grounded:         bool  = False
    contradiction:    bool  = False
    evaluation_notes: str   = ""

@dataclass
class DecideResult:
    action_type:  str   = "skip"    # post / reply / internal / skip
    platform:     str   = ""
    content:      str   = ""
    confidence:   float = 0.0
    risk_score:   float = 0.0
    rationale:    str   = ""

@dataclass
class CycleTrace:
    cycle_id:    int
    timestamp:   float = field(default_factory=time.time)
    input_hash:  str   = ""
    retrieve:    Optional[RetrieveResult]  = None
    think:       Optional[ThinkResult]    = None
    evaluate:    Optional[EvaluateResult] = None
    decide:      Optional[DecideResult]   = None
    outcome:     str   = "pending"
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "cycle_id":    self.cycle_id,
            "timestamp":   self.timestamp,
            "input_hash":  self.input_hash,
            "retrieve": {
                "belief_count": len(self.retrieve.beliefs) if self.retrieve else 0,
                "intent":       self.retrieve.intent        if self.retrieve else "",
            },
            "think": {
                "latency_ms": self.think.latency_ms if self.think else 0,
                "error":      self.think.error      if self.think else "",
            },
            "evaluate": {
                "quality":         self.evaluate.quality_score  if self.evaluate else 0,
                "belief_overlap":  self.evaluate.belief_overlap if self.evaluate else 0,
                "grounded":        self.evaluate.grounded       if self.evaluate else False,
                "contradiction":   self.evaluate.contradiction  if self.evaluate else False,
            },
            "decide": {
                "action_type": self.decide.action_type if self.decide else "skip",
                "risk":        self.decide.risk_score  if self.decide else 0,
                "confidence":  self.decide.confidence  if self.decide else 0,
            },
            "outcome":     self.outcome,
            "duration_ms": self.duration_ms,
        }


# ─────────────────────────────────────────────
# COGNITIVE LOOP ENGINE
# ─────────────────────────────────────────────

class CognitiveLoop:
    """
    Executes one structured reasoning cycle per input event.
    Integrates with existing nex_brain / nex_beliefs / nex_cognition.
    """

    def __init__(
        self,
        belief_store=None,    # nex_beliefs module or compatible
        memory_store=None,    # MemorySystem (upgrade 3)
        llm_client=None,      # nex_brain LLM wrapper
        attention=None,       # AttentionSystem (upgrade 8)
        drive_system=None,    # DriveSystem (upgrade 7)
        min_belief_overlap: float = 0.01,   # U11: must share ≥1 high-conf belief
        max_risk_threshold: float = 0.70,   # governance ceiling
    ):
        self.beliefs            = belief_store
        self.memory             = memory_store
        self.llm                = llm_client
        self.attention          = attention
        self.drives             = drive_system
        self.min_belief_overlap = min_belief_overlap
        self.max_risk_threshold = max_risk_threshold
        self._cycle             = 0
        self._traces: list[CycleTrace] = []

    # ── PHASE 1 ── RETRIEVE ───────────────────
    def _retrieve(self, event_content: str, intent: str) -> RetrieveResult:
        t0 = time.time()
        beliefs  = []
        episodes = []

        try:
            if self.beliefs:
                # pull top-10 by confidence + relevance
                all_beliefs = self.beliefs.get_top_beliefs(n=10, min_conf=0.3)
                beliefs = [b for b in all_beliefs if isinstance(b, dict)]

            if self.memory:
                episodes = self.memory.retrieve(
                    query=event_content,
                    layer="episodic",
                    top_k=5,
                )
        except Exception as e:
            log.warning(f"[RETRIEVE] error: {e}")

        return RetrieveResult(
            beliefs=beliefs,
            episodes=episodes,
            intent=intent,
            latency_ms=(time.time() - t0) * 1000,
        )

    # ── PHASE 2 ── THINK ──────────────────────
    def _think(
        self,
        event_content: str,
        retrieve: RetrieveResult,
    ) -> ThinkResult:
        t0 = time.time()

        if not self.llm:
            return ThinkResult(
                raw_response="[no LLM]",
                proposed_text="[no LLM]",
                latency_ms=(time.time() - t0) * 1000,
            )

        # build grounded prompt
        belief_lines = "\n".join(
            f"  • [{b.get('confidence', 0):.2f}] {b.get('content', '')}"
            for b in retrieve.beliefs[:6]
        )
        context = f"""Active intent: {retrieve.intent or 'none'}

Top beliefs (use these to ground your response):
{belief_lines or '  (none)'}

Input:
{event_content}

Respond concisely. Stay grounded in the beliefs above."""

        try:
            response = self.llm.complete(context)
            return ThinkResult(
                raw_response=response,
                proposed_text=response,
                latency_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            log.error(f"[THINK] LLM error: {e}")
            return ThinkResult(error=str(e), latency_ms=(time.time() - t0) * 1000)

    # ── PHASE 3 ── EVALUATE ───────────────────
    def _evaluate(
        self,
        think: ThinkResult,
        retrieve: RetrieveResult,
    ) -> EvaluateResult:
        if think.error or not think.proposed_text:
            return EvaluateResult(evaluation_notes="think phase failed")

        text = think.proposed_text.lower()

        # U11: belief overlap check
        overlap_count = sum(
            1 for b in retrieve.beliefs
            if any(
                word in text
                for word in (b.get("content", "") or "").lower().split()
                if len(word) > 4
            )
        )
        belief_overlap = min(1.0, overlap_count / max(len(retrieve.beliefs), 1))
        grounded = belief_overlap >= self.min_belief_overlap

        # quality heuristic: length + coherence
        quality = min(1.0, len(think.proposed_text) / 200)

        # contradiction check: does output contradict high-conf beliefs?
        contradiction = False
        for b in retrieve.beliefs:
            if b.get("confidence", 0) > 0.7:
                bc = (b.get("content", "") or "").lower()
                if bc and bc in text and "not " + bc in text:
                    contradiction = True
                    break

        notes = (
            f"overlap={belief_overlap:.2f} "
            f"grounded={grounded} "
            f"quality={quality:.2f} "
            f"contradiction={contradiction}"
        )

        return EvaluateResult(
            quality_score=quality,
            belief_overlap=belief_overlap,
            grounded=grounded,
            contradiction=contradiction,
            evaluation_notes=notes,
        )

    # ── PHASE 4 ── DECIDE ─────────────────────
    def _decide(
        self,
        think: ThinkResult,
        evaluate: EvaluateResult,
        event_source: str,
        drives_pressure: float = 0.5,
    ) -> DecideResult:
        # block ungrounded or contradictory output
        if not evaluate.grounded:
            return DecideResult(
                action_type="skip",
                rationale="failed U11 grounding check",
            )
        if evaluate.contradiction:
            return DecideResult(
                action_type="skip",
                rationale="output contradicts high-conf belief",
            )

        # risk scoring: low quality + low trust source = higher risk
        risk = 1.0 - evaluate.quality_score

        # drives can lower risk threshold (urgency)
        effective_threshold = self.max_risk_threshold - (drives_pressure * 0.1)

        if risk > effective_threshold:
            return DecideResult(
                action_type="skip",
                risk_score=risk,
                rationale=f"risk {risk:.2f} > threshold {effective_threshold:.2f}",
            )

        # determine platform from source
        platform = "internal"
        if "discord"  in event_source: platform = "discord"
        elif "telegram" in event_source: platform = "telegram"
        elif "mastodon" in event_source: platform = "mastodon"

        return DecideResult(
            action_type="reply" if platform != "internal" else "internal",
            platform=platform,
            content=think.proposed_text,
            confidence=evaluate.quality_score,
            risk_score=risk,
            rationale="grounded + within risk threshold",
        )

    # ── PHASE 5+6 ── ACT + STORE ──────────────
    def _act(self, decide: DecideResult) -> str:
        if decide.action_type == "skip":
            return "skipped"
        # actual dispatch happens via ControlLayer / ActionModule
        # here we just confirm the intent is valid
        return f"queued:{decide.action_type}:{decide.platform}"

    def _store(self, trace: CycleTrace) -> None:
        if self.memory:
            try:
                self.memory.store(
                    layer="episodic",
                    content=json.dumps(trace.to_dict()),
                    metadata={"cycle": trace.cycle_id, "outcome": trace.outcome},
                )
            except Exception as e:
                log.warning(f"[STORE] error: {e}")

        self._traces.append(trace)
        if len(self._traces) > 500:
            self._traces = self._traces[-500:]

    # ── MAIN ENTRY POINT ──────────────────────
    def run(self, event_content: str, event_source: str = "", intent: str = "") -> CycleTrace:
        self._cycle += 1
        t_start = time.time()

        trace = CycleTrace(
            cycle_id=self._cycle,
            input_hash=hashlib.md5(event_content.encode()).hexdigest()[:8],
        )

        # drives pressure
        drives_pressure = 0.5
        if self.drives:
            try:
                drives_pressure = self.drives.get_pressure("influence")
            except Exception:
                pass

        # execute phases
        trace.retrieve = self._retrieve(event_content, intent)
        trace.think    = self._think(event_content, trace.retrieve)
        trace.evaluate = self._evaluate(trace.think, trace.retrieve)
        trace.decide   = self._decide(trace.think, trace.evaluate, event_source, drives_pressure)

        outcome_str    = self._act(trace.decide)
        trace.outcome  = outcome_str
        trace.duration_ms = (time.time() - t_start) * 1000

        self._store(trace)

        log.info(
            f"[LOOP] cycle={self._cycle} "
            f"action={trace.decide.action_type} "
            f"grounded={trace.evaluate.grounded} "
            f"risk={trace.decide.risk_score:.2f} "
            f"dur={trace.duration_ms:.0f}ms"
        )

        return trace

    # ── OBSERVABILITY ─────────────────────────
    def get_traces(self, last_n: int = 10) -> list[dict]:
        return [t.to_dict() for t in self._traces[-last_n:]]

    def summary(self) -> dict:
        if not self._traces:
            return {"cycles": 0}
        grounded   = sum(1 for t in self._traces if t.evaluate and t.evaluate.grounded)
        skipped    = sum(1 for t in self._traces if t.decide  and t.decide.action_type == "skip")
        avg_risk   = sum(t.decide.risk_score for t in self._traces if t.decide) / len(self._traces)
        avg_dur    = sum(t.duration_ms for t in self._traces) / len(self._traces)
        return {
            "cycles":        self._cycle,
            "traced":        len(self._traces),
            "grounded_pct":  grounded / len(self._traces),
            "skip_pct":      skipped  / len(self._traces),
            "avg_risk":      avg_risk,
            "avg_dur_ms":    avg_dur,
        }
