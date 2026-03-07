"""
simulation_engine.py — Nex Simulation Engine
Doctrine ref: XXXVI (Predictive Coherence), LXXVIII (Self-Generated Internal Environments)

Simulates candidate belief updates before committing them.
If predicted coherence would drop below threshold, the update is dampened.
"""
import numpy as np
from typing import Optional
from dataclasses import dataclass


@dataclass
class SimResult:
    predicted_coherence: float
    update_accepted: bool
    damping_factor: float
    reason: str


class SimulationEngine:
    """
    Doctrine XXXVI process:
      1. Generate candidate update ΔV
      2. Simulate system state at t+1
      3. Estimate predicted coherence
      4. Accept or reject / dampen update
    """
    COHERENCE_FLOOR = 0.35   # if predicted C drops below this, dampen
    MAX_DAMPING     = 0.3    # minimum factor to retain (never zero)

    def __init__(self):
        self.accepted  = 0
        self.dampened  = 0
        self.last_result: Optional[SimResult] = None

    def evaluate_update(self, belief_field, delta_vectors: np.ndarray,
                        coherence_engine, coupling_graph) -> SimResult:
        """
        Simulate applying delta_vectors and estimate resulting coherence.
        Returns SimResult with damping_factor to apply to the real update.
        """
        domains = belief_field.domains
        n       = min(len(domains), delta_vectors.shape[0])

        # ── Simulate future vectors ───────────────────────────────────
        future_vectors = belief_field.get_vectors().copy()
        future_vectors[:n] += delta_vectors[:n]

        # ── Estimate local coherence on simulated state ───────────────
        # C_local = 1 - mean(|ΔV|) normalised
        delta_norms = np.linalg.norm(delta_vectors[:n], axis=1)
        predicted_c_local = float(np.exp(-np.mean(delta_norms) * 3))

        # ── Estimate cluster coherence ────────────────────────────────
        norms = np.linalg.norm(future_vectors, axis=1, keepdims=True)
        nv    = future_vectors / np.where(norms > 0, norms, 1.0)
        cos   = nv @ nv.T
        n_v   = future_vectors.shape[0]
        mask  = np.triu(np.ones((n_v, n_v), bool), k=1)
        predicted_c_cluster = float(np.mean(np.abs(cos[mask]))) if mask.any() else 0.5

        # ── Simple spectral estimate stays same (no full recompute) ───
        predicted_c_global = coherence_engine.last_report.c_global if coherence_engine.last_report else 0.6

        predicted_c = (0.40 * predicted_c_global
                       + 0.30 * predicted_c_cluster
                       + 0.30 * predicted_c_local)
        predicted_c = float(np.clip(predicted_c, 0, 1))

        # ── Decide: accept or dampen ──────────────────────────────────
        current_c = coherence_engine.last_report.c_total if coherence_engine.last_report else 0.5

        if predicted_c >= self.COHERENCE_FLOOR:
            self.accepted += 1
            result = SimResult(predicted_c, True, 1.0, "accepted")
        else:
            # Dampen proportionally to how far below floor we'd go
            deficit = self.COHERENCE_FLOOR - predicted_c
            damping = float(np.clip(1.0 - deficit * 2.0, self.MAX_DAMPING, 1.0))
            self.dampened += 1
            result = SimResult(predicted_c, False, damping,
                               f"dampened(pred={predicted_c:.3f}<{self.COHERENCE_FLOOR})")

        self.last_result = result
        return result

    def stats(self) -> dict:
        total = self.accepted + self.dampened
        return {
            "accepted":  self.accepted,
            "dampened":  self.dampened,
            "dampen_rate": round(self.dampened / total, 3) if total > 0 else 0,
        }
