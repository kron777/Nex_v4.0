import numpy as np

class CouplingGraph:
    def __init__(self, n_domains, rng=None):
        self.rng = rng or np.random.default_rng()
        self.n   = n_domains
        self.M   = self.rng.standard_normal((n_domains, n_domains)) * 0.05
        np.fill_diagonal(self.M, 0.0)
        self._constrain(n_domains)
        self.coupling_lr = 0.005

    def compute_influences(self, belief_field):
        domains = belief_field.domains
        n = len(domains)
        self._ensure(n)
        out = []
        for i in range(n):
            inf = np.zeros(belief_field.belief_dim)
            for j in range(n):
                if i != j:
                    d = domains[j]
                    inf += d.norm * d.K * self.M[i, j] * d.V
            out.append(inf)
        return out

    def update(self, belief_field, perf_delta=0.0):
        n = len(belief_field.domains)
        self._ensure(n)
        acts = np.array([d.norm for d in belief_field.domains])
        outer = np.outer(acts, acts)
        np.fill_diagonal(outer, 0.0)
        self.M[:n, :n] += self.coupling_lr * outer * 0.01
        row_norms = np.linalg.norm(self.M[:n, :n], axis=1, keepdims=True)
        row_norms = np.where(row_norms > 0, row_norms, 1.0)
        self.M[:n, :n] = self.M[:n, :n] / row_norms * 0.5
        self._constrain(n)

    def spectral_radius(self, n=None):
        n = n or self.n
        try:
            return float(np.max(np.abs(np.linalg.eigvals(self.M[:n, :n]))))
        except Exception:
            return 0.0

    def coupling_norm(self, n=None):
        n = n or self.n
        return float(np.linalg.norm(self.M[:n, :n]))

    def _constrain(self, n):
        rho = self.spectral_radius(n)
        if rho >= 1.0:
            self.M[:n, :n] *= 0.95 / rho

    def _ensure(self, n):
        if n > self.M.shape[0]:
            old = self.M.copy()
            self.M = np.zeros((n, n))
            s = old.shape[0]
            self.M[:s, :s] = old
            for i in range(s, n):
                for j in range(n):
                    if i != j:
                        v = self.rng.standard_normal() * 0.02
                        self.M[i, j] = v
                        self.M[j, i] = v
            self.n = n
