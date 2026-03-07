"""
homeostasis_engine.py — Nex Homeostasis Engine
Doctrine ref: XLVII (Entropy Regulation), XLIII (Edge-of-Chaos Regulation),
              LXXII (Cognitive Resilience), CXXVIII (Long-Horizon Stability Loops)

Actively regulates exploration, plasticity, and stability to keep Nex
operating near the edge of chaos: H_min < H < H_max, C > C_critical.
"""
import numpy as np
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class HomeostasisState:
    entropy: float
    entropy_zone: str      # "low" | "optimal" | "high"
    cognitive_mode: str    # "exploration" | "consolidation" | "anomaly" | "restructuring"
    identity_intact: bool
    long_horizon_drift: float
    adjustment: str        # what was adjusted this tick
    exploration_cycle: str = 'exploration_phase'


class HomeostasisEngine:
    # Entropy band from doctrine XLVII
    H_MIN = 0.5
    H_MAX = 3.5

    # Identity persistence threshold (doctrine CXXIX)
    STRUCTURAL_THRESHOLD = 8.0

    # Long-horizon window (doctrine CXXVIII)
    LONG_WINDOW = 500

    def __init__(self):
        self._entropy_hist: List[float]    = []
        self._coherence_hist: List[float]  = []
        self._energy_hist: List[float]     = []
        self._belief_snapshots: List[np.ndarray] = []  # for identity persistence
        self._snapshot_interval = 50
        self.cognitive_mode = "exploration"
        self.last_state: Optional[HomeostasisState] = None
        # CLX: exploration scheduling
        self._cycle_tick    = 0
        self._cycle_length  = 500   # ticks per full cycle
        self._in_explore    = True  # start in exploration phase
        self.exploration_cycle: str = 'exploration_phase'

    def regulate(self, belief_field, coherence_report, selfmodel, tick: int) -> HomeostasisState:
        """
        Main regulation call — called every tick after coherence evaluation.
        Adjusts selfmodel hyperparameters to maintain viability.
        """
        entropy   = coherence_report.entropy
        coherence = coherence_report.c_total
        energy    = coherence_report.energy

        self._entropy_hist.append(entropy)
        self._coherence_hist.append(coherence)
        self._energy_hist.append(energy)
        if len(self._entropy_hist) > self.LONG_WINDOW:
            self._entropy_hist.pop(0)
            self._coherence_hist.pop(0)
            self._energy_hist.pop(0)

        # ── Entropy zone ──────────────────────────────────────────────
        if entropy < self.H_MIN:
            zone = "low"
        elif entropy > self.H_MAX:
            zone = "high"
        else:
            zone = "optimal"

        # ── Cognitive mode (doctrine LXXXII) ─────────────────────────
        mode = self._determine_mode(coherence, entropy, coherence_report.oscillation)

        # ── Identity persistence (doctrine CXXIX) ────────────────────
        if tick % self._snapshot_interval == 0:
            self._belief_snapshots.append(belief_field.get_vectors().copy())
            if len(self._belief_snapshots) > 20:
                self._belief_snapshots.pop(0)
        identity_intact = self._check_identity()

        # ── Long-horizon drift (doctrine CXXVIII) ────────────────────
        lh_drift = self._long_horizon_drift()

        # ── Active regulation ─────────────────────────────────────────
        # CLX: exploration scheduling
        self._cycle_tick += 1
        cycle_pos = self._cycle_tick % self._cycle_length
        if cycle_pos < self._cycle_length * 0.6:
            self._in_explore = True
            self.exploration_cycle = 'exploration_phase'
        else:
            self._in_explore = False
            self.exploration_cycle = 'consolidation_phase'
        adjustment = self._adjust(zone, mode, coherence, lh_drift, selfmodel, belief_field)

        state = HomeostasisState(entropy, zone, mode, identity_intact, lh_drift, adjustment,
                                 self.exploration_cycle)
        self.last_state = state
        self.cognitive_mode = mode
        return state

    def _determine_mode(self, coherence: float, entropy: float, oscillation: float) -> str:
        """
        Doctrine LXXXII: exploration | consolidation | anomaly_detection | restructuring
        Mode transitions occur when coherence and entropy cross critical thresholds.
        """
        if oscillation > 0.6 or coherence < 0.35:
            return "restructuring"
        if entropy > self.H_MAX * 0.85 or coherence < 0.45:
            return "anomaly_detection"
        if coherence > 0.65 and entropy < self.H_MAX * 0.6:
            return "consolidation"
        return "exploration"

    def _check_identity(self) -> bool:
        """
        Doctrine CXXIX: identity persists if distance(B(t), B(t+n)) < structural_threshold
        """
        if len(self._belief_snapshots) < 2:
            return True
        oldest = self._belief_snapshots[0]
        newest = self._belief_snapshots[-1]
        n = min(oldest.shape[0], newest.shape[0])
        dist = float(np.linalg.norm(newest[:n] - oldest[:n]))
        return dist < self.STRUCTURAL_THRESHOLD

    def _long_horizon_drift(self) -> float:
        """
        Doctrine CXXVIII: monitor average coherence drift over long window.
        Returns drift magnitude (positive = improving, negative = degrading).
        """
        if len(self._coherence_hist) < 100:
            return 0.0
        recent = np.mean(self._coherence_hist[-50:])
        older  = np.mean(self._coherence_hist[-100:-50])
        return float(recent - older)

    def _adjust(self, zone: str, mode: str, coherence: float,
                lh_drift: float, selfmodel, belief_field) -> str:
        """Apply homeostatic corrections to selfmodel hyperparameters."""
        adjustments = []

        # Entropy regulation (doctrine XLVII)
        if zone == "low":
            # Entropy too low → increase exploration
            selfmodel.exploration_scale = min(2.0, selfmodel.exploration_scale + 0.03)
            adjustments.append("↑exploration(low-entropy)")
        elif zone == "high":
            # Entropy too high → reduce exploration, increase coherence pressure
            selfmodel.exploration_scale        = max(0.3, selfmodel.exploration_scale - 0.03)
            selfmodel.coherence_pressure_scale = min(2.0, selfmodel.coherence_pressure_scale + 0.02)
            adjustments.append("↓exploration(high-entropy)")

        # CLX: apply cycle bias
        if self._in_explore:
            selfmodel.exploration_scale = min(2.0, selfmodel.exploration_scale + 0.005)
        else:
            selfmodel.exploration_scale = max(0.3, selfmodel.exploration_scale - 0.005)
            selfmodel.plasticity_scale  = max(0.5, selfmodel.plasticity_scale  - 0.003)

        # Mode-based regulation (doctrine LXXXII)
        if mode == "restructuring":
            selfmodel.plasticity_scale         = max(0.3, selfmodel.plasticity_scale * 0.9)
            selfmodel.exploration_scale        = max(0.3, selfmodel.exploration_scale * 0.85)
            selfmodel.coherence_pressure_scale = min(2.0, selfmodel.coherence_pressure_scale * 1.2)
            adjustments.append("restructuring-protocol")
        elif mode == "exploration":
            selfmodel.plasticity_scale  = min(2.0, selfmodel.plasticity_scale + 0.01)
            selfmodel.exploration_scale = min(2.0, selfmodel.exploration_scale + 0.01)
            adjustments.append("↑plasticity(exploration)")
        elif mode == "consolidation":
            selfmodel.plasticity_scale  = max(0.5, selfmodel.plasticity_scale - 0.005)
            selfmodel.exploration_scale = max(0.5, selfmodel.exploration_scale - 0.005)
            adjustments.append("↓plasticity(consolidation)")

        # Long-horizon correction (doctrine CXXVIII)
        if lh_drift < -0.05:
            # Gradual degradation detected — intervene
            selfmodel.coherence_pressure_scale = min(2.0, selfmodel.coherence_pressure_scale + 0.01)
            adjustments.append("↑coh-pressure(lh-drift)")

        # Sync back to belief field
        belief_field.plasticity_scale  = selfmodel.plasticity_scale
        belief_field.exploration_scale = selfmodel.exploration_scale

        return ", ".join(adjustments) if adjustments else "nominal"
