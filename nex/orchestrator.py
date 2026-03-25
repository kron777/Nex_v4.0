"""
orchestrator.py  —  Nex Orchestrator  (Doctrine v12)
"""
import numpy as np
from typing import Optional
from .belief_field        import BeliefField
from .coupling_graph      import CouplingGraph
from .coherence_engine    import CoherenceEngine
from .self_model          import SelfModel
from .memory_system       import MemorySystem
from .world_interface     import WorldInterface
from .homeostasis_engine  import HomeostasisEngine
from .curiosity_engine    import CuriosityEngine
from .simulation_engine   import SimulationEngine
from .attractor_map       import AttractorMap
try:
    from nex.nex_upgrades import (
        u1_lock_top_beliefs,
        u2_run_contradiction_resolution,
        u4_reset_cycle, u4_should_reflect,
        u9_get_intent,
        u10_stability_check,
        u11_ground_output,
        u8_get_active_directives,
    )
    _UPG = True
except Exception as _ue:
    _UPG = False
    print(f"  [UPGRADES] not loaded: {_ue}")



class Orchestrator:
    def __init__(self, seed=None):
        self.rng        = np.random.default_rng(seed)
        self.world      = WorldInterface(seed=seed)
        self.beliefs    = BeliefField(rng=self.rng)
        self.coupling   = CouplingGraph(len(self.beliefs.domains), rng=self.rng)
        self.coh_eng    = CoherenceEngine()
        self.selfmod    = SelfModel()
        self.memory     = MemorySystem()
        self.homeo      = HomeostasisEngine()
        self.curiosity  = CuriosityEngine()
        self.simulator  = SimulationEngine()
        self.attr_map   = AttractorMap()
        # CXL: developmental metrics
        self._dev_metrics = {'coherence_traj': [], 'entropy_traj': [],
                             'belief_variance': [], 'coupling_density': [],
                             'attractor_stability': []}
        self.tick       = 0
        self._last_perf = 0.5
        self._perf_history = []
        self._attractors   = []
        self._near_attractor = None
        # CLXI: intelligence progress metrics
        self._progress = {
            'attractor_count_history': [],
            'concept_count_history':   [],
            'pred_error_history':      [],
            'activation_diversity':    [],
            'structural_changes':      [],  # CLXII
        }
        # CLXII: safe development guardrails
        self._DOMAIN_CAP   = 20     # hard cap on domains
        self._ENERGY_CAP   = 50000  # log warning above this

    def step(self) -> dict:
        X          = self.world.observe()
        pred       = self.beliefs.predict(X)
        error      = X - pred
        pred_error = float(np.linalg.norm(error))
        perf       = float(1.0 / (1.0 + pred_error))
        perf_delta = perf - self._last_perf
        self._last_perf = perf
        self._perf_history.append(perf)
        if len(self._perf_history) > 500:
            self._perf_history.pop(0)

        coupling_influences = self.coupling.compute_influences(self.beliefs)
        coh_penalties       = self.coh_eng.compute_penalties(self.beliefs)
        phase_plast         = self.selfmod.phase_plasticity()

        # Predictive coherence simulation before committing update
        delta_vectors = self._compute_delta(X, error, coupling_influences, coh_penalties, phase_plast)
        sim_result    = self.simulator.evaluate_update(self.beliefs, delta_vectors, self.coh_eng, self.coupling)

        self.beliefs.update(X, error, coupling_influences, coh_penalties, phase_plast,
                            damping=sim_result.damping_factor)
        self.beliefs.update_confidence(perf_delta)
        self.coupling.update(self.beliefs, perf_delta)

        report      = self.coh_eng.evaluate(self.beliefs, self.coupling)
        homeo_state = self.homeo.regulate(self.beliefs, report, self.selfmod, self.tick)
        curi_state  = self.curiosity.evaluate(self.beliefs, report, pred_error, self.tick)
        sm_state    = self.selfmod.observe_state(report, self.beliefs, self.coupling, perf, self.tick)

        self.beliefs.plasticity_scale  = self.selfmod.plasticity_scale
        self.beliefs.exploration_scale = self.selfmod.exploration_scale

        if report.c_total < self.coh_eng.CRITICAL:
            self.selfmod.stability_protocol(self.beliefs)

        # Full attractor cartography (CXLII-CXLVIII)
        attractor_id = self.attr_map.update(self.beliefs, report.c_total, pred_error, self.tick)
        # CXL: developmental metrics
        self._update_dev_metrics(report)
        self._update_progress(pred_error)

        act_pattern = self.beliefs.activation_log[-1] if self.beliefs.activation_log else None
        self.memory.store_tick(
            self.tick, X, pred_error, report.c_total,
            report.energy, sm_state.phase, self.beliefs.get_vectors(),
            emergent_goal=curi_state.emergent_goal,
            cognitive_mode=homeo_state.cognitive_mode,
            identity_intact=homeo_state.identity_intact,
            activation_pattern=act_pattern,
            attractor_id=attractor_id,
        )

        self._manage_domains(pred_error, report, sm_state.phase)

        stable = (report.c_total > 0.6 and len(self._perf_history) > 20
                  and np.std(self._perf_history[-20:]) < 0.05)
        self.world.advance(self.tick, nex_stable=stable)
        self.tick += 1

        # ── NEX UPGRADES: per-cycle hooks ─────────────────────
        if _UPG:
            u4_reset_cycle(self.tick)
            if self.tick % 50 == 0:
                u1_lock_top_beliefs(n=30)
            if self.tick % 53 == 0:  # staggered — avoids DB contention with u1
                try:
                    u2_run_contradiction_resolution(
                        lambda p: self._llm_resolve(p), limit=3
                    )
                except Exception:
                    pass
            _stab = u10_stability_check(current_cycle=self.tick)
            if _stab["mode"] == "fallback":
                import logging as _lg
                _lg.getLogger("nex.orchestrator").warning(
                    f"[U10] Fallback mode: {_stab['signals']}")
        # ─────────────────────────────────────────────────────
        return {
            "tick": self.tick, "perf": round(perf,4),
            "pred_error": round(pred_error,4), "coherence": round(report.c_total,4),
            "energy": round(report.energy,4), "phase": sm_state.phase,
            "domains": len(self.beliefs.domains),
            "cognitive_mode": homeo_state.cognitive_mode,
            "emergent_goal": curi_state.emergent_goal,
            "identity_intact": homeo_state.identity_intact,
        }

    def run(self, n_ticks: int):
        for _ in range(n_ticks):
            self.step()

    def _compute_delta(self, X, error, coupling_influences, coherence_penalties, phase_plasticity):
        proj    = self.beliefs.projection
        X_proj  = X @ proj
        err_mag = float(np.linalg.norm(error))
        deltas  = []
        for i, d in enumerate(self.beliefs.domains):
            pred_grad = X_proj * err_mag * 0.1
            coupling  = coupling_influences[i] if (coupling_influences and i < len(coupling_influences)) else np.zeros(self.beliefs.belief_dim)
            noise     = self.rng.standard_normal(self.beliefs.belief_dim)
            penalty   = coherence_penalties[i] if (coherence_penalties and i < len(coherence_penalties)) else 0.0
            a = d.alpha * self.beliefs.plasticity_scale * phase_plasticity
            delta = (a*pred_grad + d.beta*coupling + d.gamma*self.beliefs.exploration_scale*noise - d.lam*penalty*d.V)
            mag = np.linalg.norm(delta)
            if mag > 2.0:
                delta *= 2.0/mag
            deltas.append(delta)
        return np.vstack(deltas) if deltas else np.zeros((1, self.beliefs.belief_dim))

    def _detect_attractor(self, report, pred_error):
        if report.c_total < 0.65 or pred_error > 0.3:
            self._near_attractor = None
            return
        current = self.beliefs.get_vectors()
        for i, attr in enumerate(self._attractors):
            n = min(current.shape[0], attr["vectors"].shape[0])
            dist = float(np.linalg.norm(current[:n] - attr["vectors"][:n]))
            if dist < 0.5:
                attr["visits"] += 1
                self._near_attractor = i
                return
        if len(self._attractors) < 20:
            self._attractors.append({"tick": self.tick, "vectors": current.copy(),
                                     "coherence": report.c_total, "visits": 1})
            self._near_attractor = len(self._attractors) - 1


    def _update_dev_metrics(self, report):
        m = self._dev_metrics
        m['coherence_traj'].append(report.c_total)
        m['entropy_traj'].append(report.entropy)
        vecs = self.beliefs.get_vectors()
        m['belief_variance'].append(float(np.mean(np.var(vecs, axis=0))))
        m['coupling_density'].append(self.coupling.coupling_norm(len(self.beliefs.domains)))
        a = self.attr_map
        m['attractor_stability'].append(a._stability)
        for k in m:
            if len(m[k]) > 1000: m[k].pop(0)


    def _update_progress(self, pred_error: float):
        p = self._progress
        am = self.attr_map
        p['attractor_count_history'].append(len(am.attractors))
        p['concept_count_history'].append(len(am.concepts))
        p['pred_error_history'].append(pred_error)
        # Activation diversity: entropy of domain norms
        norms = np.array([d.norm for d in self.beliefs.domains])
        norms = norms / (norms.sum() + 1e-8)
        diversity = float(-np.sum(norms * np.log(norms + 1e-10)))
        p['activation_diversity'].append(diversity)
        for k in p:
            if isinstance(p[k], list) and len(p[k]) > 2000:
                p[k].pop(0)
        # CLXII: safety guardrails
        if len(self.beliefs.domains) > self._DOMAIN_CAP:
            while len(self.beliefs.domains) > self._DOMAIN_CAP:
                to_prune = sorted([d for d in self.beliefs.domains if d.probationary], key=lambda d: d.K)
                if to_prune: self.beliefs.remove_domain(to_prune[0].index)
                else: break
        if self.beliefs.total_energy() > self._ENERGY_CAP:
            p['structural_changes'].append({'tick': self.tick, 'event': 'energy_cap_hit',
                                             'energy': round(self.beliefs.total_energy(), 2)})

    def _manage_domains(self, pred_error, report, phase):
        n = len(self.beliefs.domains)
        if (pred_error > 1.5 and report.c_total > 0.45
                and phase in ("Consolidation","Mature","Recursive") and n < 14):
            if self.rng.random() < 0.02:
                self.beliefs.add_domain()
        for d in list(self.beliefs.domains):
            if not d.probationary:
                continue
            if d.K < 0.12 and self.tick % 50 == 0:
                if self.coupling.coupling_norm(n) < 0.05:
                    self.beliefs.remove_domain(d.index)

    def _llm_resolve(self, prompt: str) -> str:
        """U2 contradiction resolution via Ollama."""
        try:
            import urllib.request, json as _j
            payload = _j.dumps({
                "model": "mistral-nex",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 10,
                "stream": False
            }).encode()
            req = urllib.request.Request(
                "http://localhost:8080/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            resp = _j.loads(urllib.request.urlopen(req, timeout=30).read())
            return resp["choices"][0]["message"]["content"].strip()
        except Exception:
            return "UNCERTAINTY"

    def status(self) -> dict:
        report    = self.coh_eng.last_report
        sm        = self.selfmod.latest_state()
        homeo     = self.homeo.last_state
        curi      = self.curiosity.last_state
        sim_stats = self.simulator.stats()
        return {
            "tick": self.tick, "phase": self.selfmod.current_phase(),
            "domains": len(self.beliefs.domains),
            "energy": round(self.beliefs.total_energy(),4),
            "coherence": round(report.c_total if report else 0,4),
            "c_local": round(report.c_local if report else 0,4),
            "c_cluster": round(report.c_cluster if report else 0,4),
            "c_global": round(report.c_global if report else 0,4),
            "spectral_r": round(self.coupling.spectral_radius(len(self.beliefs.domains)),4),
            "plasticity": round(self.selfmod.plasticity_scale,4),
            "exploration": round(self.selfmod.exploration_scale,4),
"cognitive_mode":   homeo.cognitive_mode if homeo else 'unknown',
            "exploration_cycle": homeo.exploration_cycle if homeo else 'exploration_phase',
            "entropy": round(report.entropy if report else 0,4),
            "entropy_zone": homeo.entropy_zone if homeo else "unknown",
            "identity_intact": homeo.identity_intact if homeo else True,
            "lh_drift": round(homeo.long_horizon_drift if homeo else 0,4),
            "emergent_goal": curi.emergent_goal if curi else "none",
            "top_curious": curi.top_domain if curi else "none",
            "novelty_pressure": round(curi.novelty_pressure if curi else 0,4),
            "attractors": len(self._attractors),
            "near_attractor": self._near_attractor,
            "sim_dampen_rate": sim_stats["dampen_rate"],
            "memory": self.memory.summary(),
            "perf_recent": round(float(np.mean(self._perf_history[-20:])) if self._perf_history else 0,4),
            "domain_list": [{"name":d.name,"K":round(d.K,3),"norm":round(d.norm,3),"probationary":d.probationary}
                            for d in self.beliefs.domains],
            "active_directives": u8_get_active_directives() if _UPG else [],
            "active_intent": u9_get_intent(self.tick) if _UPG else None,
            "stability": u10_stability_check(current_cycle=self.tick)["mode"] if _UPG else "unknown",
        }
