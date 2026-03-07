import numpy as np
from dataclasses import dataclass


@dataclass
class CuriosityState:
    curiosity: float
    top_domain: str
    goal: str
    novelty_pressure: float
    targets: list
    active_hyps: list
    emergent_goal: str


class CuriosityEngine:

    def __init__(self):
        self.last_state = None


    def evaluate(self, belief_field, report, pred_error, tick):

        curiosity = float(np.linalg.norm(pred_error))

        top_domain = "unknown"
        try:
            top_domain = belief_field.domains[0].name
        except Exception:
            pass

        goal = "explore"
        novelty_pressure = curiosity

        targets = []
        active_hyps = []

        emergent_goal = goal

        state = CuriosityState(
            curiosity,
            top_domain,
            goal,
            novelty_pressure,
            targets,
            active_hyps,
            emergent_goal
        )

        self.last_state = state

        return state
