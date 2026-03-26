"""
attractor_map.py — Nex Attractor Cartography System
Doctrine: CXLII-CXLVIII (v14)
"""
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class Attractor:
    id: int
    tick_discovered: int
    vectors: np.ndarray
    coherence: float
    stability_duration: int
    visits: int
    last_visit_tick: int
    concept_cluster: Optional[int] = None


@dataclass
class AttractorTransition:
    tick: int
    from_id: int
    to_id: int
    coherence: float


@dataclass
class ConceptCluster:
    id: int
    attractor_ids: List[int]
    centroid: np.ndarray
    formation_tick: int


@dataclass
class DiscoveryEvent:
    tick: int
    attractor_id: int
    coherence_gain: float
    error_reduction: float
    description: str


class AttractorMap:
    VARIANCE_WINDOW    = 15
    VARIANCE_THRESHOLD = 0.08
    COSINE_MATCH       = 0.92
    DISCOVERY_DELTA    = 0.05
    MAX_ATTRACTORS     = 50
    CONCEPT_SIMILARITY = 0.80

    def __init__(self):
        self.attractors:  List[Attractor]          = []
        self.transitions: List[AttractorTransition] = []
        self.concepts:    List[ConceptCluster]     = []
        self.discoveries: List[DiscoveryEvent]     = []
        self.trajectory:  List[int]                = []
        self._vbuf: List[np.ndarray] = []
        self._current:   Optional[int] = None
        self._stability: int   = 0
        self._prev_coh:  float = 0.0
        self._prev_err:  float = 1.0
        self._next_id:   int   = 0

    def update(self, belief_field, coherence: float, pred_error: float, tick: int) -> Optional[int]:
        vectors = belief_field.get_vectors()
        flat    = vectors.flatten()

        if self._vbuf and len(self._vbuf[-1]) != len(flat):
            self._vbuf.clear()
        self._vbuf.append(flat)
        if len(self._vbuf) > self.VARIANCE_WINDOW:
            self._vbuf.pop(0)

        near_id = None
        if len(self._vbuf) == self.VARIANCE_WINDOW:
            variance = float(np.mean(np.var(np.vstack(self._vbuf), axis=0)))
            if variance < self.VARIANCE_THRESHOLD:
                near_id = self._match_or_create(vectors, flat, coherence, pred_error, tick)

        if near_id is not None and near_id == self._current:
            self._stability += 1
            a = self._get(near_id)
            if a:
                a.stability_duration = self._stability
                a.last_visit_tick    = tick
        elif near_id is not None:
            if self._current is not None and self._current != near_id:
                self.transitions.append(AttractorTransition(tick, self._current, near_id, coherence))
            self._current   = near_id
            self._stability = 1
            if not self.trajectory or self.trajectory[-1] != near_id:
                self.trajectory.append(near_id)
        else:
            self._current   = None
            self._stability = 0

        self._prev_coh = coherence
        self._prev_err = pred_error
        # ── GWT: submit attractor salience signal ─────────
        if near_id is not None:
            try:
                from nex_gwt import get_gwb as _gwb_am, SalienceSignal as _SS_am
                attr = self._get(near_id)
                if attr:
                    sal = min(1.0, 0.4 + coherence * 0.4 + attr.visits * 0.02)
                    _gwb_am().submit(_SS_am(
                        source="attractor",
                        content=f"A{near_id} stability={self._stability} visits={attr.visits} coh={coherence:.3f}",
                        salience=sal,
                        payload={"attractor_id": near_id, "coherence": coherence},
                    ))
            except Exception:
                pass
        # ─────────────────────────────────────────────────
        return near_id

    def _match_or_create(self, vectors, flat, coherence, pred_error, tick) -> int:
        for attr in self.attractors:
            af = attr.vectors.flatten()
            n  = min(len(flat), len(af))
            na, nb = np.linalg.norm(flat[:n]), np.linalg.norm(af[:n])
            if na > 0 and nb > 0:
                if float(np.dot(flat[:n], af[:n]) / (na * nb)) >= self.COSINE_MATCH:
                    attr.visits += 1
                    return attr.id

        if len(self.attractors) >= self.MAX_ATTRACTORS:
            self.attractors.sort(key=lambda a: a.visits)
            self.attractors.pop(0)

        a = Attractor(self._next_id, tick, vectors.copy(), coherence, 1, 1, tick)
        self.attractors.append(a)
        self._next_id += 1

        coh_gain   = coherence - self._prev_coh
        err_reduce = self._prev_err - pred_error
        if (coh_gain > self.DISCOVERY_DELTA or err_reduce > 0.1) and len(self.attractors) > 1:
            self.discoveries.append(DiscoveryEvent(
                tick, a.id, round(coh_gain, 4), round(err_reduce, 4),
                f"A{a.id} discovered: C={coherence:.3f} (+{coh_gain:.3f}), err_reduce={err_reduce:.3f}"
            ))

        self._update_concepts(a)
        return a.id

    def _update_concepts(self, new_attr: Attractor):
        flat_new = new_attr.vectors.flatten()
        for concept in self.concepts:
            n  = min(len(flat_new), len(concept.centroid))
            na = np.linalg.norm(flat_new[:n])
            nc = np.linalg.norm(concept.centroid[:n])
            if na > 0 and nc > 0:
                sim = float(np.dot(flat_new[:n], concept.centroid[:n]) / (na * nc))
                if sim >= self.CONCEPT_SIMILARITY:
                    concept.attractor_ids.append(new_attr.id)
                    new_attr.concept_cluster = concept.id
                    members  = [a.vectors.flatten() for a in self.attractors if a.id in concept.attractor_ids]
                    min_len  = min(len(m) for m in members)
                    concept.centroid = np.mean([m[:min_len] for m in members], axis=0)
                    return
        cid = len(self.concepts)
        self.concepts.append(ConceptCluster(cid, [new_attr.id], flat_new.copy(), new_attr.tick_discovered))
        new_attr.concept_cluster = cid

    def _get(self, aid: int) -> Optional[Attractor]:
        for a in self.attractors:
            if a.id == aid:
                return a
        return None

    def nearest(self, vectors: np.ndarray, k=3) -> List[Dict]:
        flat = vectors.flatten()
        sims = []
        for a in self.attractors:
            af = a.vectors.flatten()
            n  = min(len(flat), len(af))
            na, nb = np.linalg.norm(flat[:n]), np.linalg.norm(af[:n])
            sim = float(np.dot(flat[:n], af[:n]) / (na * nb)) if na > 0 and nb > 0 else 0.0
            sims.append((sim, a))
        sims.sort(reverse=True)
        return [{"id": a.id, "sim": round(s, 4), "coherence": a.coherence,
                 "visits": a.visits, "stability": a.stability_duration}
                for s, a in sims[:k]]


    def distill_knowledge(self) -> list:
        '''
        CLIX: Compress frequently-visited attractors into concept summaries.
        Returns list of distilled concepts.
        '''
        # Find attractors visited > 3 times
        frequent = [a for a in self.attractors if a.visits >= 3]
        if not frequent:
            return []
        distilled = []
        for concept in self.concepts:
            members = [a for a in frequent if a.id in concept.attractor_ids]
            if len(members) < 2:
                continue
            # Centroid of frequent members
            vecs   = [m.vectors.flatten() for m in members]
            min_l  = min(len(v) for v in vecs)
            centroid = np.mean([v[:min_l] for v in vecs], axis=0)
            total_visits = sum(m.visits for m in members)
            mean_coh     = float(np.mean([m.coherence for m in members]))
            distilled.append({
                'concept_id':    concept.id,
                'members':       len(members),
                'total_visits':  total_visits,
                'mean_coherence':round(mean_coh, 4),
                'centroid_norm': round(float(np.linalg.norm(centroid)), 4),
                'formation_tick':concept.formation_tick,
            })
        # Update concept centroids with distilled knowledge
        for concept in self.concepts:
            members = [a for a in self.attractors if a.id in concept.attractor_ids and a.visits >= 3]
            if len(members) >= 2:
                vecs = [m.vectors.flatten() for m in members]
                min_l = min(len(v) for v in vecs)
                concept.centroid = np.mean([v[:min_l] for v in vecs], axis=0)
        return distilled
    def summary(self) -> Dict:
        return {
            "attractors":        len(self.attractors),
            "concepts":          len(self.concepts),
            "transitions":       len(self.transitions),
            "discoveries":       len(self.discoveries),
            "trajectory_length": len(self.trajectory),
"distilled_concepts":  len(self.distill_knowledge()),
            "current":           self._current,
            "stability":         self._stability,
            "recent_discoveries":[d.description for d in self.discoveries[-3:]],
        }
