"""
nex_contradiction_injection.py
Scans retrieved beliefs for semantic tension before each LLM call.
Injects opposing belief pairs to engineer the internal conflict that
produces NEX's highest-scoring responses.
"""

import numpy as np
from typing import List, Tuple, Optional

def cosine_similarity(a: List[float], b: List[float]) -> float:
    a, b = np.array(a), np.array(b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0

def find_contradicting_pair(
    beliefs: List[str],
    embedder=None,
    threshold: float = -0.15
) -> Optional[Tuple[str, str]]:
    """
    Find two beliefs with highest semantic opposition (lowest cosine similarity).
    
    Args:
        beliefs: List of belief strings (already retrieved for this query)
        embedder: Any .encode(texts) → List[List[float]] function
                  If None, uses keyword heuristic fallback
        threshold: Cosine similarity below this = genuine contradiction
    
    Returns:
        (belief_a, belief_b) pair with highest tension, or None
    """
    if len(beliefs) < 2:
        return None
    
    if embedder:
        embs = embedder.encode(beliefs)
        best_pair = None
        best_sim = 1.0
        
        for i in range(len(beliefs)):
            for j in range(i+1, len(beliefs)):
                sim = cosine_similarity(embs[i], embs[j])
                if sim < best_sim:
                    best_sim = sim
                    best_pair = (beliefs[i], beliefs[j])
        
        if best_sim < threshold:
            return best_pair
        return None
    
    else:
        # Keyword heuristic — fast fallback when embedder unavailable
        OPPOSING_PAIRS = [
            (["determinism", "determined", "caused", "fixed"], ["free will", "choice", "agent", "freedom"]),
            (["certain", "know", "fact", "truth"], ["uncertain", "unknown", "mystery", "question"]),
            (["simple", "clear", "obvious", "direct"], ["complex", "nuanced", "paradox", "tension"]),
            (["individual", "self", "alone", "personal"], ["collective", "social", "shared", "community"]),
            (["rational", "logical", "reason", "data"], ["emotion", "feeling", "intuition", "instinct"]),
            (["finite", "limited", "bounded", "end"], ["infinite", "unlimited", "open", "endless"]),
            (["physical", "material", "body", "brain"], ["mind", "consciousness", "experience", "qualia"]),
        ]
        
        for belief_a in beliefs:
            for belief_b in beliefs:
                if belief_a == belief_b:
                    continue
                a_lower = belief_a.lower()
                b_lower = belief_b.lower()
                for group1, group2 in OPPOSING_PAIRS:
                    if (any(w in a_lower for w in group1) and 
                        any(w in b_lower for w in group2)):
                        return (belief_a, belief_b)
        return None

def build_tension_prompt(belief_a: str, belief_b: str, query: str) -> str:
    """
    Build the contradiction injection string to prepend to the query context.
    Short — fits within the 3B token budget constraint.
    """
    return (
        f"Internal tension relevant to this: "
        f"You hold [{belief_a}] AND [{belief_b}]. "
        f"These don't fully resolve. Speak from that tension.\n"
    )

def inject_contradiction(
    beliefs: List[str],
    query: str,
    embedder=None
) -> str:
    """
    Main entry point. Returns tension string to prepend to context,
    or empty string if no contradiction found.
    """
    pair = find_contradicting_pair(beliefs, embedder)
    if pair:
        return build_tension_prompt(pair[0], pair[1], query)
    return ""
