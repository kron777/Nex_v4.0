import numpy as np
from dataclasses import dataclass


@dataclass
class SelfModelState:
    tick: int
    energy: float
    coherence: float
    velocity: float
    risk: float
    phase: str


class SelfModel:

    def __init__(self):

        self.phase = "Early"

        self.exploration_scale = 1.0
        self.plasticity_scale = 1.0
        self.coherence_pressure_scale = 1.0

        self._history = []
        self._last_state = None


    def phase_plasticity(self):

        mapping = {
            "Early": 1.0,
            "Consolidation": 0.6,
            "Recovery": 0.85
        }

        return mapping.get(self.phase, 0.8)


    def observe_state(self, report, beliefs, coupling, perf, tick):

        coherence = getattr(report, "c_total", 0.5)
        energy = getattr(report, "energy", 1.0)

        velocity = 0.0
        try:
            velocity = float(np.linalg.norm(beliefs.get_delta_vectors()))
        except Exception:
            pass

        risk = abs(velocity)

        state = SelfModelState(
            tick,
            energy,
            coherence,
            velocity,
            risk,
            self.phase
        )

        self._history.append(state)
        self._last_state = state

        if coherence < 0.3:
            self.phase = "Recovery"
        elif coherence < 0.6:
            self.phase = "Early"
        else:
            self.phase = "Consolidation"

        return state


    def latest_state(self):
        return self._last_state


    def current_phase(self):
        return self.phase


    def stability_protocol(self, belief_field):

        belief_field.plasticity_scale = max(
            0.4, belief_field.plasticity_scale * 0.9
        )

        belief_field.exploration_scale = max(
            0.4, belief_field.exploration_scale * 0.9
        )
