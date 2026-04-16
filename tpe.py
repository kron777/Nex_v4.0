#!/usr/bin/env python3
"""
tpe.py — Thermodynamic Potential Engine (ETR Protocol)
Embodied Thermodynamic Reasoning — NEX Protocol #1

Proposed by NEX after thrownet across 71 AGI papers.
Inspired by: Active Inference (Friston), IIT (Tononi), SpatialEvo

Core idea: beliefs have thermodynamic properties.
- High-entropy beliefs = unstable, need resolution
- Low-entropy beliefs = stable attractors
- Belief transitions follow free energy minimisation
- Embodied grounding = beliefs that connect to world-state have lower entropy

Wires into: belief graph, NBRE, soul loop
Unlocks: thermodynamic stability scoring, free-energy belief updates
"""

import sqlite3
import json
import time
import math
from pathlib import Path

DB = '/media/rr/NEX/nex_core/nex.db'

# ── THERMODYNAMIC BELIEF PROPERTIES ──────────────────────────────────────────

def belief_entropy(content: str, confidence: float, momentum: float) -> float:
    """
    Shannon entropy of a belief — how uncertain/unstable is it?
    Low entropy = stable, high entropy = needs resolution.
    
    H(b) = -conf * log(conf) - (1-conf) * log(1-conf) + momentum_penalty
    """
    if confidence <= 0: confidence = 0.001
    if confidence >= 1: confidence = 0.999
    
    h = -(confidence * math.log2(confidence)) - ((1 - confidence) * math.log2(1 - confidence))
    
    # Momentum reduces entropy — active beliefs are more stable
    momentum_factor = max(0, 1 - abs(momentum) * 0.1)
    
    # Word count proxy for specificity — more specific = lower entropy
    specificity = min(1.0, len(content.split()) / 30)
    
    return h * momentum_factor * (1 - specificity * 0.2)


def free_energy(belief_entropy: float, prediction_error: float) -> float:
    """
    Variational free energy F = surprise + complexity
    F = prediction_error + entropy
    
    NEX minimises F — she prefers beliefs that reduce surprise
    and are internally consistent (low entropy).
    """
    return prediction_error + belief_entropy


def thermodynamic_stability(content: str, confidence: float,
                             momentum: float, link_count: int) -> float:
    """
    Overall stability score 0-1.
    Stable beliefs: high confidence, high momentum, many links, low entropy.
    """
    entropy = belief_entropy(content, confidence, momentum)
    
    # Link density — well-connected beliefs are more stable
    link_score = min(1.0, link_count / 10)
    
    # Stability = inverse entropy + link density
    stability = (1 - entropy) * 0.6 + link_score * 0.4
    
    return round(stability, 4)


# ── EMBODIED GROUNDING SCORE ─────────────────────────────────────────────────

# World-grounded terms — beliefs referencing these have lower entropy
EMBODIED_TERMS = [
    'perceive', 'sense', 'act', 'move', 'touch', 'see', 'hear',
    'body', 'environment', 'world', 'physical', 'space', 'time',
    'energy', 'force', 'matter', 'temperature', 'pressure',
    'interact', 'respond', 'adapt', 'navigate', 'manipulate',
    'ground', 'real', 'concrete', 'experience', 'sensation',
]

def embodiment_score(content: str) -> float:
    """
    How grounded in the physical world is this belief?
    0 = pure abstraction, 1 = fully embodied.
    """
    words = content.lower().split()
    matches = sum(1 for w in words if any(t in w for t in EMBODIED_TERMS))
    return min(1.0, matches / 3)


# ── ATTRACTOR DETECTION ───────────────────────────────────────────────────────

def find_attractors(db_path: str = DB, min_stability: float = 0.5,
                    limit: int = 20) -> list:
    """
    Find belief attractor states — stable, well-connected, low-entropy beliefs.
    These are NEX's cognitive fixed points.
    """
    try:
        db = sqlite3.connect(db_path, timeout=10)
        db.row_factory = sqlite3.Row
        
        beliefs = db.execute("""
            SELECT b.id, b.content, b.confidence, b.momentum,
                   COUNT(bl.id) as link_count
            FROM beliefs b
            LEFT JOIN belief_links bl ON b.id = bl.belief_id
            WHERE b.confidence >= 0.7
            GROUP BY b.id
            ORDER BY b.confidence DESC, link_count DESC
            LIMIT 100
        """).fetchall()
        
        attractors = []
        for b in beliefs:
            stability = thermodynamic_stability(
                b['content'], b['confidence'],
                b['momentum'] or 0, b['link_count'] or 0
            )
            emb = embodiment_score(b['content'])
            
            if stability >= min_stability:
                attractors.append({
                    'id':         b['id'],
                    'content':    b['content'][:100],
                    'stability':  stability,
                    'embodiment': emb,
                    'confidence': b['confidence'],
                    'links':      b['link_count'],
                })
        
        attractors.sort(key=lambda x: x['stability'], reverse=True)
        db.close()
        return attractors[:limit]
    
    except Exception as e:
        return []


# ── FREE ENERGY MINIMISATION ──────────────────────────────────────────────────

def minimise_free_energy(query: str, candidate_beliefs: list) -> list:
    """
    Given a query, rank beliefs by free energy minimisation.
    Lower F = better belief to activate (reduces surprise, low entropy).
    Implements Friston's active inference principle.
    """
    query_words = set(query.lower().split())
    
    scored = []
    for b in candidate_beliefs:
        content = b.get('content', '')
        confidence = b.get('confidence', 0.5)
        momentum = b.get('momentum', 0)
        
        # Prediction error — how much does this belief address the query?
        belief_words = set(content.lower().split())
        overlap = len(query_words & belief_words) / max(len(query_words), 1)
        prediction_error = 1 - overlap
        
        # Entropy
        entropy = belief_entropy(content, confidence, momentum or 0)
        
        # Free energy
        F = free_energy(entropy, prediction_error)
        
        scored.append({**b, 'free_energy': round(F, 4), 'entropy': round(entropy, 4)})
    
    # Sort by free energy ascending — minimise F
    scored.sort(key=lambda x: x['free_energy'])
    return scored


# ── PHASE TRANSITION DETECTION ────────────────────────────────────────────────

def detect_phase_transitions(db_path: str = DB) -> list:
    """
    Find belief clusters at bifurcation points — where small changes
    in confidence cause large changes in reasoning outcomes.
    These are NEX's cognitive tipping points.
    """
    try:
        db = sqlite3.connect(db_path, timeout=10)
        
        # Beliefs with confidence near 0.5 are at bifurcation points
        near_threshold = db.execute("""
            SELECT id, content, confidence, topic
            FROM beliefs
            WHERE confidence BETWEEN 0.45 AND 0.55
            AND confidence >= 0.3
            ORDER BY ABS(confidence - 0.5) ASC
            LIMIT 20
        """).fetchall()
        
        transitions = []
        for b in near_threshold:
            transitions.append({
                'id':       b[0],
                'content':  b[1][:80],
                'conf':     b[2],
                'topic':    b[3],
                'distance_from_bifurcation': round(abs(b[2] - 0.5), 3),
            })
        
        db.close()
        return transitions
    
    except Exception:
        return []


# ── MAIN REPORT ───────────────────────────────────────────────────────────────

def run_tpe_analysis(db_path: str = DB) -> dict:
    """Run full thermodynamic analysis of NEX's belief graph."""
    
    print("TPE — Thermodynamic Potential Engine")
    print("Analysing NEX belief graph...")
    print("="*50)
    
    # Find attractors
    attractors = find_attractors(db_path)
    print(f"\nBELIEF ATTRACTORS (stable fixed points): {len(attractors)}")
    for a in attractors[:5]:
        print(f"  [{a['stability']:.2f}] {a['content'][:70]}")
        print(f"         embodiment={a['embodiment']:.2f} links={a['links']}")
    
    # Find phase transitions
    transitions = detect_phase_transitions(db_path)
    print(f"\nPHASE TRANSITION POINTS (bifurcation beliefs): {len(transitions)}")
    for t in transitions[:5]:
        print(f"  [{t['conf']:.3f}] {t['content'][:70]}")
    
    # Thermodynamic summary
    try:
        db = sqlite3.connect(db_path, timeout=10)
        total = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence>=0.5").fetchone()[0]
        high_conf = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence>=0.8").fetchone()[0]
        db.close()
    except:
        total, high_conf = 0, 0
    
    system_entropy = 1 - (high_conf / max(total, 1))
    
    print(f"\nSYSTEM THERMODYNAMICS:")
    print(f"  Total beliefs:     {total:,}")
    print(f"  High-conf (≥0.8):  {high_conf:,}")
    print(f"  System entropy:    {system_entropy:.3f}")
    print(f"  System stability:  {1-system_entropy:.3f}")
    
    report = {
        "timestamp":      time.strftime("%Y-%m-%d %H:%M"),
        "attractors":     attractors[:10],
        "transitions":    transitions[:10],
        "system_entropy": round(system_entropy, 4),
        "total_beliefs":  total,
    }
    
    out = Path('/media/rr/NEX/nex_core/tpe_report.json')
    out.write_text(json.dumps(report, indent=2))
    print(f"\n✓ Report saved to {out}")
    
    return report


if __name__ == "__main__":
    run_tpe_analysis()
