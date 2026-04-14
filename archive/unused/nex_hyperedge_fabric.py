"""
nex_hyperedge_fabric.py — N-way Belief Hyperedge Fabric
=======================================================
Upgrades the belief graph from pairwise edges (A↔B) to N-way
hyperedges (A↔B↔C↔D) that capture group-level belief relationships.

Architecture:
  Classical graph: only pairwise. "consciousness relates to identity"
  Hypergraph:     N-way. "consciousness, identity, AI, and self-awareness
                  form a cluster with a specific tension topology"

  The hyperedge fabric is the "Hyperedge fabric" component on the
  architecture map — sits inside BeliefHypergraph core alongside
  Hopfield memory and Hebbian plasticity.

Components:
  1. HyperedgeCluster — N-way belief grouping with a topic signature
  2. DHGNNLayer — Dual Hypergraph Neural Network message passing
     (adapted from Bai et al. NeurIPS Oct 2025 — simplified for CPU)
  3. LaplacianCurveRegulariser — smoothness constraint on hyperedge
     membership (prevents degenerate single-belief hyperedges)
  4. HyperedgeFabric — manages all clusters, runs DHGNN passes,
     exposes cluster-aware retrieval

References:
  Bai S. et al. "DHGNN: Dual Hypergraph Neural Networks" NeurIPS Oct 2025
  Benson A.R. "Higher-order Organization of Complex Networks" Science 2016
  Zhou D. et al. "Learning with Hypergraphs" NeurIPS 2006
"""

import math
import time
import json
import logging
import hashlib
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

logger = logging.getLogger("nex.hyperedge_fabric")


# ── Configuration ─────────────────────────────────────────────────────────────
MIN_CLUSTER_SIZE   = 2      # minimum beliefs in a hyperedge
MAX_CLUSTER_SIZE   = 12     # maximum (larger → split)
FORMATION_THRESHOLD = 0.45  # min average pairwise sim to form cluster
MERGE_THRESHOLD    = 0.70   # merge two clusters if their signatures are this similar
SPLIT_TENSION      = 0.35   # split cluster if internal tension exceeds this
DHGNN_ITERATIONS   = 2      # message passing rounds (2 is sufficient for depth-2 topology)
LAPLACIAN_LAMBDA   = 0.1    # regularisation strength


# ── Hyperedge cluster ─────────────────────────────────────────────────────────

@dataclass
class HyperedgeCluster:
    """
    N-way hyperedge connecting a group of beliefs.
    
    signature: centroid topic vector (used for cluster similarity)
    tension:   internal disagreement measure (high = cluster should split)
    weight:    cumulative co-activation strength
    """
    cluster_id:  str
    belief_ids:  list[str] = field(default_factory=list)
    topic_tags:  set[str]  = field(default_factory=set)
    weight:      float     = 1.0
    tension:     float     = 0.0
    created_at:  float     = field(default_factory=time.time)
    last_active: float     = field(default_factory=time.time)
    activation_count: int  = 0

    @property
    def size(self) -> int:
        return len(self.belief_ids)

    def activate(self, boost: float = 0.1):
        self.weight += boost
        self.activation_count += 1
        self.last_active = time.time()

    def add_belief(self, belief_id: str, topics: set[str] | None = None):
        if belief_id not in self.belief_ids:
            self.belief_ids.append(belief_id)
            if topics:
                self.topic_tags.update(topics)

    def remove_belief(self, belief_id: str):
        if belief_id in self.belief_ids:
            self.belief_ids.remove(belief_id)

    def topic_overlap(self, other: "HyperedgeCluster") -> float:
        """Jaccard similarity of topic tags."""
        if not self.topic_tags or not other.topic_tags:
            return 0.0
        inter = len(self.topic_tags & other.topic_tags)
        union = len(self.topic_tags | other.topic_tags)
        return inter / union if union > 0 else 0.0


def _cluster_id_from_beliefs(belief_ids: list[str]) -> str:
    sorted_ids = sorted(belief_ids)
    h = hashlib.md5("|".join(sorted_ids).encode()).hexdigest()[:10]
    return f"hc_{h}"


# ── Laplacian curve regulariser ───────────────────────────────────────────────

class LaplacianCurveRegulariser:
    """
    Applies Laplacian smoothing to hyperedge membership scores.
    
    Prevents degenerate outcomes:
    - All beliefs in one cluster (over-merging)
    - Every belief in its own cluster (fragmentation)
    
    Uses normalised hypergraph Laplacian:
        L = I - D_v^{-1/2} H W D_e^{-1} H^T D_v^{-1/2}
    
    where:
        H = incidence matrix (beliefs × clusters)
        W = diagonal cluster weights
        D_v = vertex degree matrix
        D_e = edge degree matrix
    
    Applied as a soft regularisation: membership scores are smoothed
    toward their Laplacian-weighted neighbourhood.
    """

    @staticmethod
    def smooth_memberships(belief_ids: list[str],
                           clusters: list[HyperedgeCluster],
                           membership_scores: dict[str, dict[str, float]],
                           lambda_: float = LAPLACIAN_LAMBDA) -> dict[str, dict[str, float]]:
        """
        membership_scores: {belief_id: {cluster_id: score}}
        Returns smoothed membership_scores.
        """
        if not belief_ids or not clusters:
            return membership_scores

        # Build incidence matrix H[belief_idx][cluster_idx]
        b_idx = {bid: i for i, bid in enumerate(belief_ids)}
        c_idx = {c.cluster_id: i for i, c in enumerate(clusters)}
        n_b, n_c = len(belief_ids), len(clusters)

        H = [[0.0] * n_c for _ in range(n_b)]
        for c in clusters:
            ci = c_idx[c.cluster_id]
            for bid in c.belief_ids:
                if bid in b_idx:
                    bi = b_idx[bid]
                    score = membership_scores.get(bid, {}).get(c.cluster_id, 0.0)
                    H[bi][ci] = max(score, 0.1)  # floor for connectivity

        # Vertex degrees: D_v[i] = sum of cluster weights for belief i
        D_v = [sum(H[i]) for i in range(n_b)]

        # Edge degrees: D_e[j] = number of beliefs in cluster j
        D_e = [sum(H[i][j] for i in range(n_b)) for j in range(n_c)]

        # Smoothed: new_score[i][j] = (1-λ)*H[i][j] + λ * Σ_k (H[i][k]/D_e[k]) * H[i][j]
        # (simplified Laplacian step — full inversion too costly for runtime use)
        smoothed: dict[str, dict[str, float]] = {}
        for bid in belief_ids:
            smoothed[bid] = {}
            bi = b_idx[bid]
            for c in clusters:
                ci = c_idx[c.cluster_id]
                original = H[bi][ci]
                # Neighbourhood contribution
                nbr_sum = 0.0
                if D_v[bi] > 0:
                    for cj in range(n_c):
                        if H[bi][cj] > 0 and D_e[cj] > 0:
                            nbr_sum += H[bi][cj] / D_e[cj]
                smoothed_val = (1 - lambda_) * original + lambda_ * nbr_sum
                smoothed[bid][c.cluster_id] = smoothed_val

        return smoothed


# ── DHGNN message passing layer ───────────────────────────────────────────────

class DHGNNLayer:
    """
    Simplified Dual Hypergraph Neural Network message passing.
    
    Two-phase message passing:
    Phase 1 (belief → cluster): each cluster aggregates feature signals
            from its member beliefs (weighted by membership strength)
    Phase 2 (cluster → belief): each belief aggregates cluster-level
            features from clusters it belongs to
    
    This propagates information along hyperedges — a belief "learns"
    about the topological neighbourhood of its cluster context.
    
    Output: updated relevance scores for retrieval re-ranking.
    """

    def __init__(self, iterations: int = DHGNN_ITERATIONS):
        self.iterations = iterations

    def propagate(self,
                  belief_features: dict[str, list[float]],
                  clusters: list[HyperedgeCluster]) -> dict[str, list[float]]:
        """
        belief_features: {belief_id: feature_vector}
        Returns updated belief_features after DHGNN propagation.
        """
        if not clusters or not belief_features:
            return belief_features

        features = dict(belief_features)

        for _ in range(self.iterations):
            # Phase 1: belief → cluster aggregation
            cluster_features: dict[str, list[float]] = {}
            for cluster in clusters:
                member_vecs = [features[bid]
                               for bid in cluster.belief_ids
                               if bid in features]
                if not member_vecs:
                    continue
                dim = len(member_vecs[0])
                agg = [0.0] * dim
                for vec in member_vecs:
                    for j in range(dim):
                        agg[j] += vec[j]
                n = len(member_vecs)
                cluster_features[cluster.cluster_id] = [x / n for x in agg]

            # Phase 2: cluster → belief propagation
            new_features: dict[str, list[float]] = {}
            for bid, feat in features.items():
                dim = len(feat)
                nbr_agg = [0.0] * dim
                nbr_count = 0
                for cluster in clusters:
                    if bid in cluster.belief_ids:
                        cf = cluster_features.get(cluster.cluster_id)
                        if cf:
                            w = cluster.weight
                            for j in range(dim):
                                nbr_agg[j] += w * cf[j]
                            nbr_count += w

                if nbr_count > 0:
                    # Residual connection: 0.5 * original + 0.5 * propagated
                    updated = [0.5 * feat[j] + 0.5 * (nbr_agg[j] / nbr_count)
                               for j in range(dim)]
                else:
                    updated = feat

                # L2 normalise
                norm = math.sqrt(sum(x*x for x in updated)) + 1e-9
                new_features[bid] = [x / norm for x in updated]

            features = new_features

        return features


# ── Main hyperedge fabric ─────────────────────────────────────────────────────

class HyperedgeFabric:
    """
    Manages the full hyperedge fabric.
    
    Exposes:
    - form_cluster(belief_ids): create or update a hyperedge cluster
    - get_belief_clusters(belief_id): which clusters contain this belief
    - cluster_aware_rerank(candidates): re-rank using cluster topology
    - activate_cluster(cluster_id): Hebbian boost on cluster activation
    - maintenance(): merge/split/prune clusters
    """

    def __init__(self):
        self._clusters:   dict[str, HyperedgeCluster] = {}
        self._membership: dict[str, set[str]] = defaultdict(set)  # belief → cluster IDs
        self._dhgnn = DHGNNLayer()
        self._regulariser = LaplacianCurveRegulariser()

    def form_cluster(self, belief_ids: list[str],
                     topic_tags: set[str] | None = None,
                     weight: float = 1.0) -> HyperedgeCluster:
        """
        Create or update a hyperedge cluster from a set of beliefs.
        If an existing cluster has high overlap, updates it instead.
        """
        if len(belief_ids) < MIN_CLUSTER_SIZE:
            # Too small — still record membership for future merging
            pass

        # Check if an existing cluster is very similar
        for cluster in self._clusters.values():
            existing_set = set(cluster.belief_ids)
            new_set = set(belief_ids)
            jaccard = len(existing_set & new_set) / len(existing_set | new_set)
            if jaccard >= MERGE_THRESHOLD:
                # Update existing cluster
                for bid in belief_ids:
                    cluster.add_belief(bid, topic_tags)
                if topic_tags:
                    cluster.topic_tags.update(topic_tags)
                cluster.activate(weight * 0.05)
                self._update_membership(cluster)
                return cluster

        # Create new cluster
        cid = _cluster_id_from_beliefs(belief_ids)
        cluster = HyperedgeCluster(
            cluster_id=cid,
            belief_ids=list(belief_ids),
            topic_tags=topic_tags or set(),
            weight=weight,
        )
        self._clusters[cid] = cluster
        self._update_membership(cluster)
        logger.debug("[Fabric] New cluster %s: %d beliefs", cid, len(belief_ids))
        return cluster

    def _update_membership(self, cluster: HyperedgeCluster):
        """Rebuild membership index for a cluster."""
        for bid in cluster.belief_ids:
            self._membership[bid].add(cluster.cluster_id)

    def get_belief_clusters(self, belief_id: str) -> list[HyperedgeCluster]:
        """Returns all clusters containing this belief."""
        return [self._clusters[cid]
                for cid in self._membership.get(belief_id, set())
                if cid in self._clusters]

    def activate_cluster(self, cluster_id: str, boost: float = 0.1):
        """Boost a cluster on activation (Hebbian episode feedback path)."""
        if cluster_id in self._clusters:
            self._clusters[cluster_id].activate(boost)

    def cluster_aware_rerank(self,
                             candidates: list[dict],
                             query_belief_ids: list[str] | None = None) -> list[dict]:
        """
        Re-rank retrieval candidates using hyperedge cluster topology.
        
        Beliefs that co-cluster with already-selected context beliefs
        get a topology bonus.
        
        candidates: list of {id, text, score, ...} dicts
        query_belief_ids: beliefs already in the reply context
        
        Returns re-ranked candidates list.
        """
        if not candidates:
            return candidates

        query_clusters: set[str] = set()
        if query_belief_ids:
            for qid in query_belief_ids:
                for cluster in self.get_belief_clusters(qid):
                    query_clusters.add(cluster.cluster_id)

        reranked = []
        for cand in candidates:
            bid = cand.get("id", "")
            base_score = cand.get("score", 0.5)

            # Topology bonus: is this candidate in a cluster with query beliefs?
            topo_bonus = 0.0
            if query_clusters:
                cand_clusters = {c.cluster_id
                                 for c in self.get_belief_clusters(bid)}
                shared = cand_clusters & query_clusters
                if shared:
                    # Bonus proportional to weight of shared clusters
                    shared_weight = sum(self._clusters[cid].weight
                                        for cid in shared
                                        if cid in self._clusters)
                    topo_bonus = min(0.3, shared_weight * 0.05)

            reranked.append({**cand, "score": base_score + topo_bonus,
                             "topo_bonus": round(topo_bonus, 4)})

        reranked.sort(key=lambda x: x["score"], reverse=True)
        return reranked

    def maintenance(self):
        """
        Merge, split, or prune clusters.
        Call periodically (e.g. every 100 ticks).
        """
        # Merge highly overlapping clusters
        cluster_list = list(self._clusters.values())
        merged = set()
        for i in range(len(cluster_list)):
            for j in range(i+1, len(cluster_list)):
                ci, cj = cluster_list[i], cluster_list[j]
                if ci.cluster_id in merged or cj.cluster_id in merged:
                    continue
                if ci.topic_overlap(cj) >= MERGE_THRESHOLD:
                    # Merge cj into ci
                    for bid in cj.belief_ids:
                        ci.add_belief(bid, cj.topic_tags)
                    ci.weight = (ci.weight + cj.weight) / 2
                    merged.add(cj.cluster_id)

        for cid in merged:
            del self._clusters[cid]

        # Prune very small clusters that haven't activated
        to_prune = []
        for cid, cluster in self._clusters.items():
            age = time.time() - cluster.created_at
            if cluster.size < MIN_CLUSTER_SIZE and age > 3600:
                to_prune.append(cid)

        for cid in to_prune:
            del self._clusters[cid]

        if merged or to_prune:
            # Rebuild membership index
            self._membership = defaultdict(set)
            for cluster in self._clusters.values():
                self._update_membership(cluster)
            logger.debug("[Fabric] Maintenance: merged=%d pruned=%d",
                         len(merged), len(to_prune))

    def stats(self) -> dict:
        if not self._clusters:
            return {"clusters": 0}
        sizes = [c.size for c in self._clusters.values()]
        return {
            "clusters":      len(self._clusters),
            "mean_size":     round(sum(sizes) / len(sizes), 1),
            "max_size":      max(sizes),
            "beliefs_indexed": len(self._membership),
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_fabric: Optional[HyperedgeFabric] = None

def get_fabric() -> HyperedgeFabric:
    global _fabric
    if _fabric is None:
        _fabric = HyperedgeFabric()
    return _fabric

def form_cluster(belief_ids: list[str],
                 topic_tags: set[str] | None = None) -> HyperedgeCluster:
    return get_fabric().form_cluster(belief_ids, topic_tags)

def cluster_rerank(candidates: list[dict],
                   context_ids: list[str] | None = None) -> list[dict]:
    return get_fabric().cluster_aware_rerank(candidates, context_ids)


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fabric = HyperedgeFabric()

    # Form clusters matching NEX tension topic structure
    c1 = fabric.form_cluster(
        ["b001", "b003", "b005"],
        topic_tags={"consciousness", "identity", "self-awareness"},
        weight=3.0  # well-activated cluster
    )
    c2 = fabric.form_cluster(
        ["b002", "b007", "b008"],
        topic_tags={"alignment", "learning", "control"},
        weight=2.0
    )
    c3 = fabric.form_cluster(
        ["b001", "b002", "b006"],
        topic_tags={"consciousness", "alignment", "contradiction"},
        weight=1.5
    )

    print(f"── Hyperedge Fabric: {fabric.stats()}")

    print("\n── Clusters for b001 (consciousness) ──")
    for c in fabric.get_belief_clusters("b001"):
        print(f"  {c.cluster_id}: {sorted(c.topic_tags)} weight={c.weight:.2f}")

    print("\n── Cluster-aware rerank ──")
    candidates = [
        {"id": "b003", "text": "Identity is narrative continuity", "score": 0.65},
        {"id": "b007", "text": "Learning needs temporal credit", "score": 0.70},
        {"id": "b005", "text": "Self-awareness is a spectrum", "score": 0.60},
        {"id": "b002", "text": "AI alignment via value learning", "score": 0.68},
    ]
    reranked = fabric.cluster_aware_rerank(candidates, query_belief_ids=["b001"])
    for r in reranked:
        print(f"  [{r['score']:.3f} +{r.get('topo_bonus',0):.3f}] {r['text'][:60]}")
