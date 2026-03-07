import numpy as np

class WorldInterface:
    # CLVII multi-resolution
    def __init__(self, dim=10, world_clock_period=10, seed=None):
        self.dim    = dim
        self.period = world_clock_period
        self._obs_history = []
        self.rng    = np.random.default_rng(seed)
        self.rule_W = self.rng.standard_normal((dim, dim)) * 0.3
        self.rule_b = self.rng.standard_normal(dim) * 0.1
        self.noise_std   = 0.1
        self.min_interval= 50
        self.last_shift  = -50
        self.shift_base  = 0.01
        self.stability_p = 0.0
        self.tick        = 0

    def observe(self):
        raw   = self.rng.standard_normal(self.dim)
        noise = self.rng.standard_normal(self.dim) * self.noise_std
        return np.tanh(raw @ self.rule_W + self.rule_b) + noise

    def advance(self, tick, nex_stable=False):
        self.tick = tick
        if tick > 0 and tick % self.period == 0:
            self._world_tick(nex_stable)

    def _world_tick(self, nex_stable):
        self.rule_W = np.clip(self.rule_W + self.rng.standard_normal(self.rule_W.shape)*0.01, -2, 2)
        self.noise_std = float(np.clip(self.noise_std + self.rng.standard_normal()*0.005, 0.02, 0.5))
        self.stability_p = min(self.stability_p+0.05,1.0) if nex_stable else max(self.stability_p-0.02,0.0)
        if self.tick - self.last_shift >= self.min_interval:
            if self.rng.random() < self.shift_base + 0.15*self.stability_p:
                self._shift()

    def _shift(self):
        self.rule_W  = self.rng.standard_normal(self.rule_W.shape)*0.4
        self.rule_b  = self.rng.standard_normal(self.dim)*0.2
        self.stability_p = 0.0
        self.last_shift  = self.tick

    def observe_multi(self) -> dict:
        '''
        CLVII: Multi-resolution world observation.
        W1 — raw sensory vector
        W2 — symbolic layer (normalised topic hash)
        W3 — temporal layer (trend: current - rolling mean)
        '''
        w1 = self.observe()  # raw
        # W2: symbolic — normalised hash fingerprint
        w2 = np.abs(np.fft.rfft(w1)[:len(w1)].real)
        w2 = w2 / (np.linalg.norm(w2) + 1e-8)
        # W3: temporal trend — diff from short rolling mean
        self._obs_history.append(w1)
        if len(self._obs_history) > 20:
            self._obs_history.pop(0)
        if len(self._obs_history) >= 5:
            rolling_mean = np.mean(self._obs_history[-5:], axis=0)
            w3 = w1 - rolling_mean
        else:
            w3 = np.zeros_like(w1)
        return {'W1': w1, 'W2': w2[:len(w1)], 'W3': w3}

