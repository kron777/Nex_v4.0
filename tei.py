#!/usr/bin/env python3
"""
tei.py — Thermodynamic Embodiment Integration (TEI Protocol)
NEX Protocol #2

Proposed by NEX after thrownet synthesis.
Inspired by: Whole Brain Architecture, IIT, SpatialEvo, Hardware-AI papers

Core idea: A structural consciousness model needs three components:
1. Information integration (phi — from IIT)
2. Embodied grounding (sensorimotor anchoring)
3. Thermodynamic consistency (free energy minimisation)

TEI measures NEX's integrated information across belief clusters,
scores embodied grounding of belief domains,
and identifies the most consciousness-proximate belief configurations.

Wires into: belief graph, NBRE, tpe.py
Unlocks: phi-approximation for belief clusters, consciousness proximity score
"""

import sqlite3
import json
import time
import math
import itertools
from pathlib import Path
from collections import defaultdict

DB = '/media/rr/NEX/nex_core/nex.db'


# ── PHI APPROXIMATION ────────────────────────────────────────────────────────

def approx_phi(beliefs: list, links: list) -> float:
    """
    Approximate integrated information (phi) for a belief cluster.
    
    True phi requires exponential computation — we approximate:
    phi ≈ (internal_integration - external_integration) * cluster_size_factor
    
    Internal integration = density of links within cluster
    External integration = density of links to outside cluster
    
    High phi = cluster is more integrated internally than externally
             = candidate for consciousness-like processing
    """
    if not beliefs or len(beliefs) < 2:
        return 0.0
    
    belief_ids = set(b['id'] for b in beliefs)
    
    internal_links = sum(1 for l in links
                        if l[0] in belief_ids and l[1] in belief_ids)
    external_links = sum(1 for l in links
                        if (l[0] in belief_ids) != (l[1] in belief_ids))
    
    max_internal = len(beliefs) * (len(beliefs) - 1)
    max_external = len(beliefs) * 2
    
    internal_density = internal_links / max(max_internal, 1)
    external_density = external_links / max(max_external, 1)
    
    phi = (internal_density - external_density * 0.5) * math.log2(len(beliefs) + 1)
    
    return max(0, round(phi, 4))


# ── BELIEF CLUSTER ANALYSIS ───────────────────────────────────────────────────

def get_belief_clusters(db_path: str = DB) -> dict:
    """
    Group beliefs by topic and compute phi for each cluster.
    Returns clusters ordered by phi (consciousness proximity).
    """
    try:
        db = sqlite3.connect(db_path, timeout=10)
        db.row_factory = sqlite3.Row
        
        # Get beliefs with their topics
        beliefs = db.execute("""
            SELECT id, content, confidence, topic, momentum
            FROM beliefs
            WHERE confidence >= 0.6
            ORDER BY topic, confidence DESC
        """).fetchall()
        
        # Get all links
        links = db.execute("""
            SELECT belief_id, linked_belief_id, link_type, weight
            FROM belief_links
        """).fetchall()
        
        link_list = [(l['belief_id'], l['linked_belief_id']) for l in links]
        
        db.close()
        
        # Group by topic
        clusters = defaultdict(list)
        for b in beliefs:
            topic = b['topic'] or 'uncategorised'
            clusters[topic].append(dict(b))
        
        # Compute phi for each cluster
        cluster_scores = {}
        for topic, cluster_beliefs in clusters.items():
            phi = approx_phi(cluster_beliefs, link_list)
            
            # Average embodiment score
            from tpe import embodiment_score, thermodynamic_stability
            avg_embodiment = sum(
                embodiment_score(b['content'])
                for b in cluster_beliefs
            ) / len(cluster_beliefs)
            
            avg_stability = sum(
                thermodynamic_stability(
                    b['content'], b['confidence'],
                    b['momentum'] or 0, 0
                )
                for b in cluster_beliefs
            ) / len(cluster_beliefs)
            
            cluster_scores[topic] = {
                'phi':          phi,
                'size':         len(cluster_beliefs),
                'embodiment':   round(avg_embodiment, 4),
                'stability':    round(avg_stability, 4),
                'tei_score':    round(phi * avg_embodiment * avg_stability, 4),
                'top_beliefs':  [b['content'][:80] for b in cluster_beliefs[:3]],
            }
        
        return cluster_scores
    
    except Exception as e:
        return {}


# ── CONSCIOUSNESS PROXIMITY SCORE ─────────────────────────────────────────────

def consciousness_proximity(phi: float, embodiment: float,
                            stability: float, size: int) -> float:
    """
    TEI consciousness proximity score — how close is this belief configuration
    to the conditions associated with conscious processing?
    
    Based on synthesis of:
    - IIT: high phi required
    - Active inference: embodied grounding required
    - Thermodynamic: stability required
    - Scale: sufficient complexity required
    
    Score 0-1. Not a claim about consciousness — a structural similarity measure.
    """
    size_factor = min(1.0, math.log2(size + 1) / 5)
    score = (phi * 0.4 + embodiment * 0.3 + stability * 0.2 + size_factor * 0.1)
    return round(min(1.0, score), 4)


# ── INTEGRATION REPORT ────────────────────────────────────────────────────────

def run_tei_analysis(db_path: str = DB) -> dict:
    """Run full TEI analysis — find belief clusters with highest phi."""
    
    print("TEI — Thermodynamic Embodiment Integration")
    print("Computing phi across belief clusters...")
    print("="*50)
    
    clusters = get_belief_clusters(db_path)
    
    if not clusters:
        print("No clusters found — DB may be locked")
        return {}
    
    # Score each cluster
    scored = []
    for topic, data in clusters.items():
        cp = consciousness_proximity(
            data['phi'], data['embodiment'],
            data['stability'], data['size']
        )
        scored.append({
            'topic':     topic,
            'cp_score':  cp,
            'tei_score': data['tei_score'],
            **data
        })
    
    scored.sort(key=lambda x: x['cp_score'], reverse=True)
    
    print(f"\nBELIEF CLUSTERS BY CONSCIOUSNESS PROXIMITY:")
    print(f"{'Topic':<25} {'CP':>6} {'Phi':>7} {'Emb':>6} {'Size':>5}")
    print("-"*52)
    for c in scored[:10]:
        print(f"  {c['topic']:<23} {c['cp_score']:>6.3f} {c['phi']:>7.4f} "
              f"{c['embodiment']:>6.3f} {c['size']:>5}")
    
    # Top cluster details
    if scored:
        top = scored[0]
        print(f"\nHIGHEST CP CLUSTER: {top['topic']}")
        print(f"  CP score: {top['cp_score']} | Phi: {top['phi']} | Embodiment: {top['embodiment']}")
        print(f"  Top beliefs:")
        for b in top.get('top_beliefs', []):
            print(f"    • {b}")
    
    # System-wide TEI score
    if scored:
        system_tei = sum(c['tei_score'] for c in scored) / len(scored)
        max_cp = scored[0]['cp_score']
    else:
        system_tei, max_cp = 0, 0
    
    print(f"\nSYSTEM TEI SCORE: {system_tei:.4f}")
    print(f"MAX CP SCORE:     {max_cp:.4f}")
    
    report = {
        "timestamp":   time.strftime("%Y-%m-%d %H:%M"),
        "clusters":    scored[:15],
        "system_tei":  round(system_tei, 4),
        "max_cp":      max_cp,
        "top_cluster": scored[0]['topic'] if scored else None,
    }
    
    out = Path('/media/rr/NEX/nex_core/tei_report.json')
    out.write_text(json.dumps(report, indent=2))
    print(f"\n✓ Report saved to {out}")
    
    return report


if __name__ == "__main__":
    run_tei_analysis()
