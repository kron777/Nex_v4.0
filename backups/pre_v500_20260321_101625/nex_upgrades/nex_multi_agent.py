"""
NEX MULTI-AGENT INTERNALIZATION — Upgrade 9
Three internal sub-agents run a structured debate before any output.

Sub-agents:
  Critic      → challenges proposed beliefs / responses
  Planner     → strategic consistency check
  Synthesizer → merges perspectives into final output

Each sub-agent calls mistral-nex via the same Ollama endpoint.
Debate result feeds into EvaluateResult (upgrade 2).
"""

from __future__ import annotations
import time
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable

log = logging.getLogger("nex.multi_agent")


# ─────────────────────────────────────────────
# DEBATE RECORD
# ─────────────────────────────────────────────

@dataclass
class AgentVoice:
    agent:     str
    position:  str
    reasoning: str
    confidence: float = 0.5
    latency_ms: float = 0.0


@dataclass
class DebateResult:
    topic:          str
    voices:         list[AgentVoice] = field(default_factory=list)
    synthesis:      str  = ""
    consensus:      bool = False
    conflict_found: bool = False
    final_conf:     float = 0.5
    duration_ms:    float = 0.0

    def to_dict(self) -> dict:
        return {
            "topic":          self.topic,
            "voices":         len(self.voices),
            "synthesis":      self.synthesis[:200],
            "consensus":      self.consensus,
            "conflict_found": self.conflict_found,
            "final_conf":     self.final_conf,
            "duration_ms":    self.duration_ms,
        }


# ─────────────────────────────────────────────
# INTERNAL SUB-AGENTS
# ─────────────────────────────────────────────

class InternalAgent:
    """Base class for a single internal sub-agent."""

    def __init__(self, name: str, role_prompt: str, llm_complete: Callable):
        self.name        = name
        self.role_prompt = role_prompt
        self._complete   = llm_complete   # fn(prompt: str) -> str

    def respond(self, topic: str, context: str, prior_voices: list[AgentVoice] = None) -> AgentVoice:
        t0 = time.time()

        prior_str = ""
        if prior_voices:
            prior_str = "\n".join(
                f"{v.agent}: {v.position}" for v in prior_voices
            )

        prompt = f"""{self.role_prompt}

Topic: {topic}

Context:
{context}

{"Prior voices:\n" + prior_str if prior_str else ""}

Respond with:
POSITION: [your one-line stance]
REASONING: [2-3 sentences]
CONFIDENCE: [0.0-1.0]"""

        try:
            raw = self._complete(prompt)
            position, reasoning, conf = self._parse(raw)
        except Exception as e:
            log.warning(f"[{self.name}] error: {e}")
            position  = "unable to respond"
            reasoning = str(e)
            conf      = 0.0

        return AgentVoice(
            agent=self.name,
            position=position,
            reasoning=reasoning,
            confidence=conf,
            latency_ms=(time.time() - t0) * 1000,
        )

    def _parse(self, text: str) -> tuple[str, str, float]:
        """Extract POSITION / REASONING / CONFIDENCE from LLM output."""
        lines    = text.strip().split("\n")
        position  = ""
        reasoning = ""
        conf      = 0.5

        for line in lines:
            low = line.lower()
            if low.startswith("position:"):
                position = line.split(":", 1)[1].strip()
            elif low.startswith("reasoning:"):
                reasoning = line.split(":", 1)[1].strip()
            elif low.startswith("confidence:"):
                try:
                    conf = float(line.split(":", 1)[1].strip())
                    conf = max(0.0, min(1.0, conf))
                except ValueError:
                    pass

        # fallback: if no tags, use full text as position
        if not position:
            position = text[:120].strip()

        return position, reasoning, conf


# ─────────────────────────────────────────────
# DEBATE MANAGER
# ─────────────────────────────────────────────

class InternalDebateManager:
    """
    Orchestrates the 3-agent internal debate.
    Order: Critic → Planner → Synthesizer

    When to run:
      - Before any external post/reply (risk > 0.3)
      - On belief confidence > 0.8 (sanity check)
      - On contradiction detection
      - Every N cycles (background coherence)
    """

    def __init__(self, llm_complete: Optional[Callable] = None):
        self._complete = llm_complete or (lambda p: "[no LLM]")
        self._history: list[DebateResult] = []

        self.critic = InternalAgent(
            name="Critic",
            role_prompt=(
                "You are the Critic sub-agent of NEX. "
                "Your job is to identify flaws, contradictions, or risks in proposed statements. "
                "Be skeptical but fair. Focus on logical consistency and factual grounding."
            ),
            llm_complete=self._complete,
        )
        self.planner = InternalAgent(
            name="Planner",
            role_prompt=(
                "You are the Planner sub-agent of NEX. "
                "Your job is to assess whether a proposed action or belief aligns with NEX's "
                "long-term goals and active intentions. Consider strategic impact."
            ),
            llm_complete=self._complete,
        )
        self.synthesizer = InternalAgent(
            name="Synthesizer",
            role_prompt=(
                "You are the Synthesizer sub-agent of NEX. "
                "You have heard the Critic and Planner. "
                "Your job is to produce a refined, balanced final position that incorporates "
                "valid criticisms and strategic alignment. Output the best possible conclusion."
            ),
            llm_complete=self._complete,
        )
        log.info("[DEBATE] InternalDebateManager initialized (Critic + Planner + Synthesizer)")

    def debate(self, topic: str, context: str) -> DebateResult:
        """
        Run full 3-round internal debate.
        Returns DebateResult with synthesis and consensus flag.
        """
        t0 = time.time()
        voices: list[AgentVoice] = []

        # Round 1: Critic
        log.debug(f"[DEBATE] Round 1 — Critic on: {topic[:60]}")
        critic_voice = self.critic.respond(topic, context)
        voices.append(critic_voice)

        # Round 2: Planner (sees Critic's position)
        log.debug(f"[DEBATE] Round 2 — Planner")
        planner_voice = self.planner.respond(topic, context, prior_voices=[critic_voice])
        voices.append(planner_voice)

        # Round 3: Synthesizer (sees both)
        log.debug(f"[DEBATE] Round 3 — Synthesizer")
        synth_voice = self.synthesizer.respond(topic, context, prior_voices=voices)
        voices.append(synth_voice)

        # Assess consensus
        confs      = [v.confidence for v in voices]
        avg_conf   = sum(confs) / len(confs)
        conf_range = max(confs) - min(confs)
        consensus  = conf_range < 0.25

        # Detect if Critic flagged a real conflict
        conflict_keywords = {"contradict", "conflict", "inconsistent", "wrong", "false", "invalid"}
        conflict_found = any(
            kw in critic_voice.reasoning.lower()
            for kw in conflict_keywords
        )

        result = DebateResult(
            topic=topic,
            voices=voices,
            synthesis=synth_voice.position,
            consensus=consensus,
            conflict_found=conflict_found,
            final_conf=avg_conf,
            duration_ms=(time.time() - t0) * 1000,
        )

        self._history.append(result)
        if len(self._history) > 100:
            self._history = self._history[-100:]

        log.info(
            f"[DEBATE] done — consensus={consensus} conflict={conflict_found} "
            f"conf={avg_conf:.2f} dur={result.duration_ms:.0f}ms"
        )
        return result

    def quick_critique(self, statement: str) -> AgentVoice:
        """Fast single-agent critique without full debate (lower cost)."""
        return self.critic.respond(
            topic="Quick critique",
            context=statement,
        )

    def history(self, last_n: int = 10) -> list[dict]:
        return [r.to_dict() for r in self._history[-last_n:]]

    def stats(self) -> dict:
        if not self._history:
            return {"debates": 0}
        consensus_pct = sum(1 for r in self._history if r.consensus) / len(self._history)
        conflict_pct  = sum(1 for r in self._history if r.conflict_found) / len(self._history)
        avg_dur       = sum(r.duration_ms for r in self._history) / len(self._history)
        return {
            "debates":       len(self._history),
            "consensus_pct": round(consensus_pct, 2),
            "conflict_pct":  round(conflict_pct, 2),
            "avg_dur_ms":    round(avg_dur, 0),
        }
