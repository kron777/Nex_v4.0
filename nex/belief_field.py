import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional

DOMAIN_NAMES = [
    "Pattern Generalization", "Ambiguity Tolerance", "Risk Weighting",
    "Novelty Preference", "Prior Retention", "Logical Strictness", "Signal-Noise Filtering",
]
BELIEF_DIM   = 8
BASE_DOMAINS = 7

@dataclass
class Domain:
    name: str
    index: int
    V: np.ndarray
    K: float = 0.5
    alpha: float = 0.05
    beta:  float = 0.03
    gamma: float = 0.02
    lam:   float = 0.01
    probationary: bool = False
    perf_history: List[float] = field(default_factory=list)

    @property
    def norm(self):
        return float(np.linalg.norm(self.V))

class BeliefField:
    def __init__(self, world_dim=10, rng=None):
        self.world_dim  = world_dim
        self.belief_dim = BELIEF_DIM
        self.rng = rng or np.random.default_rng()
        self.projection = self.rng.standard_normal((world_dim, BELIEF_DIM)) * 0.1
        self.domains: List[Domain] = [
            Domain(name=n, index=i, V=self.rng.standard_normal(BELIEF_DIM)*0.1)
            for i, n in enumerate(DOMAIN_NAMES)
        ]
        self.plasticity_scale  = 1.0
        self.exploration_scale = 1.0
        self._prev_vectors: Optional[np.ndarray] = None
        self.activation_log: list = []  # CXXXV domain activation tracking

    def _proj(self):
        return self.projection[:self.world_dim, :self.belief_dim]

    def predict(self, X: np.ndarray) -> np.ndarray:
        total_K = sum(d.K for d in self.domains) or 1.0
        agg = np.zeros(self.belief_dim)
        for d in self.domains:
            agg += (d.K / total_K) * d.V
        return agg @ self._proj().T

    def update(self, X, error, coupling_influences, coherence_penalties, phase_plasticity=1.0, damping=1.0):
        self._prev_vectors = np.vstack([d.V for d in self.domains])
        # CXXXV: log domain activations (norm = activation level)
        self.activation_log.append({d.name: round(d.norm, 4) for d in self.domains})
        if len(self.activation_log) > 500:
            self.activation_log.pop(0)
        X_proj  = X @ self._proj()
        err_mag = float(np.linalg.norm(error))
        for i, d in enumerate(self.domains):
            pred_grad = X_proj * err_mag * 0.1
            coupling  = coupling_influences[i] if (coupling_influences and i < len(coupling_influences)) else np.zeros(self.belief_dim)
            noise     = self.rng.standard_normal(self.belief_dim)
            penalty   = coherence_penalties[i] if (coherence_penalties and i < len(coherence_penalties)) else 0.0
            a = d.alpha * self.plasticity_scale * phase_plasticity
            delta = (a * pred_grad + d.beta * coupling
                     + d.gamma * self.exploration_scale * noise
                     - d.lam * penalty * d.V)
            if np.linalg.norm(delta) > 2.0:
                delta *= 2.0 / np.linalg.norm(delta)
            d.V = d.V + delta * damping

    def get_vectors(self) -> np.ndarray:
        return np.vstack([d.V for d in self.domains])

    def get_delta_vectors(self) -> Optional[np.ndarray]:
        if self._prev_vectors is None:
            return None
        curr = self.get_vectors()
        prev = self._prev_vectors
        n = min(curr.shape[0], prev.shape[0])
        return curr[:n] - prev[:n]

    def total_energy(self) -> float:
        return sum(d.norm for d in self.domains)

    def update_confidence(self, perf_delta: float):
        for d in self.domains:
            d.K = float(np.clip(d.K + 0.01 * perf_delta, 0.05, 0.95))

    def add_domain(self, name=None):
        idx  = len(self.domains)
        name = name or f"Emergent-{idx}"
        V    = self.rng.standard_normal(self.belief_dim) * 0.05
        d    = Domain(name=name, index=idx, V=V, K=0.1,
                      alpha=0.08, beta=0.02, gamma=0.04, lam=0.02, probationary=True)
        self.domains.append(d)
        return d

    def remove_domain(self, idx: int):
        if idx < BASE_DOMAINS:
            return
        self.domains = [d for d in self.domains if d.index != idx]
        for i, d in enumerate(self.domains):
            d.index = i
