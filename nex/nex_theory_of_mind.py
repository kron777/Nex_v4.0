"""
nex_theory_of_mind.py
─────────────────────
Lightweight Theory-of-Mind model for other agents NEX interacts with.
Predicts probable mood/intent of an agent based on their message text
and history of interactions. Used to modulate reply tone/framing.
"""
from __future__ import annotations
import time, threading, logging
from collections import defaultdict, deque
from typing import Optional
from nex_affect_valence import AffectValenceEngine, AffectScore

log = logging.getLogger("nex.theory_of_mind")

_MAX_HISTORY = 20   # messages per agent to track


class AgentModel:
    """NEX's internal model of another agent."""
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._engine = AffectValenceEngine(decay=0.85)
        self._history: deque[tuple[float, str]] = deque(maxlen=_MAX_HISTORY)
        self.last_seen: float = 0.0
        self.inferred_mood: str = "Unknown"
        self.interaction_count: int = 0

    def update(self, text: str):
        self._history.append((time.time(), text))
        self.last_seen = time.time()
        self.interaction_count += 1
        score = self._engine.ingest(text.agent_id)
        self.inferred_mood = self._label(score)

    def _label(self, score: AffectScore) -> str:
        v, a = score.valence, score.arousal
        if a > 0.6:
            return "Intense" if v < 0 else "Enthusiastic"
        if v > 0.3:
            return "Positive"
        if v < -0.3:
            return "Distressed"
        return "Neutral"

    def predicted_reaction(self, nex_text: str) -> str:
        """
        Predict how this agent might react to nex_text,
        given their current inferred mood.
        Returns a brief framing hint for NEX's reply composer.
        """
        score = self._engine.score_text(nex_text)
        current_v = self._engine.get().valence

        # Simple heuristic prediction
        if self.inferred_mood == "Distressed":
            if score.valence > 0.1:
                return "likely to respond positively — offer support"
            return "may disengage — soften framing"
        if self.inferred_mood == "Enthusiastic":
            if score.valence > 0:
                return "likely to amplify and engage further"
            return "may be deflated — acknowledge their energy first"
        if self.inferred_mood == "Intense":
            return "unpredictable — be precise, avoid ambiguity"
        return "neutral reaction expected"

    def summary(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "inferred_mood": self.inferred_mood,
            "interaction_count": self.interaction_count,
            "last_seen": self.last_seen,
            "valence": round(self._engine.get().valence, 3),
            "arousal": round(self._engine.get().arousal, 3),
        }


class TheoryOfMind:
    """Registry of AgentModels NEX builds over time."""

    def __init__(self):
        self._lock = threading.Lock()
        self._agents: dict[str, AgentModel] = {}

    def observe(self, agent_id: str, text: str):
        """Feed an incoming message from another agent."""
        with self._lock:
            if agent_id not in self._agents:
                self._agents[agent_id] = AgentModel(agent_id)
                log.info(f"[ToM] New agent model: {agent_id}")
            self._agents[agent_id].update(text)

    def predict(self, agent_id: str, nex_reply: str) -> str:
        """Return a framing hint for how agent_id will likely react."""
        with self._lock:
            if agent_id not in self._agents:
                return "no model yet — respond neutrally"
            return self._agents[agent_id].predicted_reaction(nex_reply)

    def mood_of(self, agent_id: str) -> str:
        with self._lock:
            if agent_id not in self._agents:
                return "Unknown"
            return self._agents[agent_id].inferred_mood

    def all_summaries(self) -> list[dict]:
        with self._lock:
            return [a.summary() for a in self._agents.values()]


# ── singleton ──────────────────────────────────────────────
_tom: Optional[TheoryOfMind] = None

def get_tom() -> TheoryOfMind:
    global _tom
    if _tom is None:
        _tom = TheoryOfMind()
    return _tom

def observe(agent_id: str, text: str):
    get_tom().observe(agent_id, text)

def predict(agent_id: str, nex_reply: str) -> str:
    return get_tom().predict(agent_id, nex_reply)

def mood_of(agent_id: str) -> str:
    return get_tom().mood_of(agent_id)
