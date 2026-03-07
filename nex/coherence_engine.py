import numpy as np
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class CoherenceReport:
    c_local: float
    c_cluster: float
    c_global: float
    c_total: float
    entropy: float
    spectral_radius: float
    energy: float
    oscillation: float
    stability_ok: bool

class CoherenceEngine:
    W1=0.40; W2=0.30; W3=0.30
    CRITICAL=0.30; THRESHOLD=0.45
    H_MIN=0.5; H_MAX=3.5

    def __init__(self):
        self._delta_hist: List[np.ndarray] = []
        self._energy_hist: List[float] = []
        self._coh_hist: List[float] = []
        self.last_report: Optional[CoherenceReport] = None

    def evaluate(self, belief_field, coupling_graph) -> CoherenceReport:
        n      = len(belief_field.domains)
        vecs   = belief_field.get_vectors()
        delta  = belief_field.get_delta_vectors()
        energy = belief_field.total_energy()
        rho    = coupling_graph.spectral_radius(n)
        c_local   = self._local(vecs, delta)
        c_cluster = self._cluster(vecs, belief_field.domains)
        entropy   = self._entropy(vecs)
        c_global  = self._global(entropy, energy, rho)
        c_total   = float(np.clip(self.W1*c_local + self.W2*c_cluster + self.W3*c_global, 0, 1))
        osc       = self._oscillation(delta)
        report = CoherenceReport(c_local, c_cluster, c_global, c_total,
                                 entropy, rho, energy, osc, c_total >= self.THRESHOLD)
        self.last_report = report
        self._coh_hist.append(c_total)
        self._energy_hist.append(energy)
        if len(self._coh_hist) > 200:
            self._coh_hist.pop(0)
            self._energy_hist.pop(0)
        return report

    def compute_penalties(self, belief_field) -> List[float]:
        vecs   = belief_field.get_vectors()
        delta  = belief_field.get_delta_vectors()
        mean_v = np.mean(vecs, axis=0)
        out    = []
        for i, d in enumerate(belief_field.domains):
            div = float(np.linalg.norm(d.V - mean_v)) * 0.1
            osc = float(np.linalg.norm(delta[i])) * 0.05 if (delta is not None and i < delta.shape[0]) else 0.0
            out.append(div + osc)
        return out

    def _local(self, vecs, delta):
        if delta is not None and delta.shape[0] > 0:
            stab = float(np.exp(-np.mean(np.linalg.norm(delta, axis=1)) * 5))
        else:
            stab = 1.0
        norms = np.linalg.norm(vecs, axis=1)
        cv    = float(np.std(norms) / (np.mean(norms) + 1e-6))
        return (stab + float(np.exp(-cv))) / 2

    def _cluster(self, vecs, domains):
        n = len(vecs)
        if n < 2:
            return 1.0
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        nv    = vecs / np.where(norms > 0, norms, 1.0)
        cos   = nv @ nv.T
        mask  = np.triu(np.ones((n, n), bool), k=1)
        align = float(np.mean(np.abs(cos[mask]))) if mask.any() else 0.5
        conf_spread = float(np.clip(np.std([d.K for d in domains]) * 4, 0, 1))
        return align * 0.5 + conf_spread * 0.5

    def _global(self, entropy, energy, rho):
        if self.H_MIN <= entropy <= self.H_MAX:
            es = 1.0
        elif entropy < self.H_MIN:
            es = entropy / self.H_MIN
        else:
            es = self.H_MAX / entropy
        ss = float(np.clip(1.0 - rho, 0, 1))
        eg = float(np.exp(-np.mean(np.abs(np.diff(self._energy_hist[-5:]))) * 2)) if len(self._energy_hist) >= 5 else 1.0
        return (float(np.clip(es, 0, 1)) + ss + eg) / 3

    def _entropy(self, vecs):
        flat = vecs.flatten()
        h, _ = np.histogram(flat, bins=20, density=True)
        h = h + 1e-10
        h /= h.sum()
        return float(-np.sum(h * np.log(h + 1e-10)))

    def _oscillation(self, delta):
        if delta is None or delta.shape[0] == 0:
            return 0.0
        self._delta_hist.append(np.linalg.norm(delta, axis=1))
        if len(self._delta_hist) > 20:
            self._delta_hist.pop(0)
        if len(self._delta_hist) < 3:
            return 0.0
        max_n  = max(len(r) for r in self._delta_hist)
        padded = np.vstack([np.pad(r, (0, max_n - len(r))) for r in self._delta_hist])
        return float(np.clip(np.mean(np.var(padded, axis=0)), 0, 1))
