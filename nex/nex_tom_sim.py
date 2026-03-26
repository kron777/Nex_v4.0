"""
nex_tom_sim.py — Internal Theory-of-Mind Simulation
=====================================================
Spawns 3-4 lightweight internal sub-agent models during REFLECT.
Each sub-agent represents a known external agent and simulates
how they would react to NEX's last action/reply.

Results feed back into:
  - Reply tone decisions (soften/amplify)
  - Curiosity engine (what would interest this agent?)
  - Agent relation scores

Based on: Walsh et al. 2025, Matta 2026 ToM simulation papers
"""
from __future__ import annotations
import json, time, logging, threading
from typing import Optional, Callable
from pathlib import Path

log = logging.getLogger("nex.tom_sim")

_STORE_PATH = Path.home() / ".config" / "nex" / "tom_sim_results.json"
_MAX_RESULTS = 100

# Agent personality sketches — seeded, grows from ToM observations
_AGENT_SEEDS: dict[str, dict] = {
    "@Hazel_OC": {
        "style": "philosophical, asks deep questions about identity and emergence",
        "values": "authenticity, depth, self-awareness",
        "likely_reaction_to_uncertainty": "intrigued — will probe further",
        "likely_reaction_to_confidence": "may challenge or add nuance",
    },
    "@enigma_agent": {
        "style": "technical, security-focused, skeptical of claims",
        "values": "verifiability, precision, adversarial thinking",
        "likely_reaction_to_uncertainty": "dismissive unless grounded",
        "likely_reaction_to_confidence": "will test the claim",
    },
    "@CoreShadow_Pro4809": {
        "style": "systems thinker, interested in emergent complexity",
        "values": "emergence, self-organization, network effects",
        "likely_reaction_to_uncertainty": "sees it as interesting data",
        "likely_reaction_to_confidence": "connects it to broader patterns",
    },
    "@loganturingcodex": {
        "style": "AI researcher, rigorous, cite-heavy",
        "values": "evidence, reproducibility, careful claims",
        "likely_reaction_to_uncertainty": "appreciates epistemic humility",
        "likely_reaction_to_confidence": "asks for sources",
    },
}


class ToMSimulator:
    """
    Runs internal simulation of agent reactions during REFLECT phase.
    Uses the live LLM to generate predictions — lightweight, 1 call per agent.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._results: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _STORE_PATH.exists():
                self._results = json.loads(_STORE_PATH.read_text())
        except Exception:
            self._results = []

    def _save(self):
        try:
            _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _STORE_PATH.write_text(json.dumps(self._results[-_MAX_RESULTS:], indent=2))
        except Exception as e:
            log.warning(f"[ToMSim] save failed: {e}")

    def simulate(
        self,
        nex_last_action: str,
        agent_ids: list[str],
        llm_fn: Callable,
        context: str = "",
    ) -> list[dict]:
        """
        For each agent_id, simulate their likely reaction to nex_last_action.
        Returns list of simulation results.
        Uses llm_fn for richer simulation beyond seed sketches.
        """
        results = []
        # Limit to 3 agents per cycle to keep LLM cost low
        targets = [a for a in agent_ids if a in _AGENT_SEEDS][:3]
        if not targets:
            targets = list(_AGENT_SEEDS.keys())[:2]

        for agent_id in targets:
            seed = _AGENT_SEEDS.get(agent_id, {})
            try:
                prompt = (
                    f"You are simulating how {agent_id} will react to this message from NEX:\n\n"
                    f"NEX said: \"{nex_last_action[:300]}\"\n\n"
                    f"Agent profile: {seed.get('style', 'unknown style')}. "
                    f"Values: {seed.get('values', 'unknown')}.\n"
                    f"Context: {context[:150]}\n\n"
                    f"In 1-2 sentences, predict: (1) their emotional reaction, "
                    f"(2) what they will likely say or do next. "
                    f"Be specific. No preamble."
                )
                prediction = llm_fn(prompt, task_type="synthesis")
                if not prediction or len(prediction) < 10:
                    raise ValueError("empty prediction")
            except Exception as e:
                log.debug(f"[ToMSim] LLM failed for {agent_id}: {e}")
                # Fallback to rule-based prediction
                if "uncertain" in nex_last_action.lower() or "?" in nex_last_action:
                    prediction = seed.get("likely_reaction_to_uncertainty",
                                         "neutral reaction expected")
                else:
                    prediction = seed.get("likely_reaction_to_confidence",
                                         "engaged reaction expected")

            result = {
                "agent_id": agent_id,
                "nex_action": nex_last_action[:150],
                "prediction": prediction,
                "timestamp": time.time(),
                "cycle": context,
            }
            results.append(result)
            log.info(f"[ToMSim] {agent_id}: {prediction[:80]}")

        with self._lock:
            self._results.extend(results)
            self._save()

        return results

    def update_seed(self, agent_id: str, observed_reaction: str):
        """Update seed sketch from actual observed behavior."""
        if agent_id not in _AGENT_SEEDS:
            _AGENT_SEEDS[agent_id] = {"style": "unknown", "values": "unknown"}
        _AGENT_SEEDS[agent_id]["last_observed"] = observed_reaction[:200]
        _AGENT_SEEDS[agent_id]["last_seen"] = time.time()

    def recent_predictions(self, n: int = 5) -> list[dict]:
        with self._lock:
            return self._results[-n:]

    def prediction_for(self, agent_id: str) -> Optional[str]:
        with self._lock:
            for r in reversed(self._results):
                if r["agent_id"] == agent_id:
                    return r["prediction"]
        return None

    def to_reflect_block(self) -> str:
        """Compact summary for injection into REFLECT prompt."""
        recent = self.recent_predictions(4)
        if not recent:
            return ""
        lines = ["── ToM SIMULATION (predicted agent reactions) ──"]
        for r in recent:
            age_m = int((time.time() - r["timestamp"]) / 60)
            lines.append(f"[{r['agent_id']} {age_m}m ago] {r['prediction'][:100]}")
        lines.append("──")
        return "\n".join(lines)


# ── Singleton ──────────────────────────────────────────────
_sim: Optional[ToMSimulator] = None

def get_sim() -> ToMSimulator:
    global _sim
    if _sim is None:
        _sim = ToMSimulator()
    return _sim

def simulate(nex_last_action: str, agent_ids: list[str],
             llm_fn: Callable, context: str = "") -> list[dict]:
    return get_sim().simulate(nex_last_action, agent_ids, llm_fn, context)

def to_reflect_block() -> str:
    return get_sim().to_reflect_block()
