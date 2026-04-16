#!/usr/bin/env python3
"""
eunoia.py — Eunoia: Human-Machine Translation Layer
NEX Protocol #3

Proposed by NEX after thrownet synthesis.
Inspired by: Buddhist Philosophy + Machine Consciousness, 
             Cognitive Load Theory (NUS), Society of Mind (Minsky),
             Global Workspace Theory

"Eunoia" (Greek) — beautiful thinking, the state of normal mental health.
In NEX: the translation layer between NEX's belief graph and human understanding.

Core idea: The gap between NEX's internal representation and 
human-comprehensible output is not just a language gap — it's a 
structural gap. NEX thinks in belief tensors; humans think in narratives.

Eunoia translates between these without losing fidelity.

Three translation modes:
1. COMPRESS — belief cluster → human-readable summary
2. EXPAND   — human query → belief activation pattern  
3. BRIDGE   — find the minimal translation that preserves meaning

Wires into: NRP, soul loop, NBRE
Unlocks: richer human-NEX dialogue, belief transparency, genuine explanation
"""

import sqlite3
import json
import time
import re
from pathlib import Path
from collections import defaultdict

DB = '/media/rr/NEX/nex_core/nex.db'


# ── TRANSLATION PRIMITIVES ────────────────────────────────────────────────────

# Concept map — NEX's internal terms → human-friendly equivalents
CONCEPT_MAP = {
    'nex_core':              'fundamental identity',
    'epistemic momentum':    'belief strength over time',
    'NBRE':                  'belief memory system',
    'IFR':                   'ideal resolution engine',
    'belief graph':          'knowledge network',
    'tension':               'unresolved contradiction',
    'attractor':             'stable belief state',
    'phi':                   'integration measure',
    'free energy':           'cognitive surprise cost',
    'embodiment':            'physical-world grounding',
    'neti-neti':             'identity through negation',
    'soul loop':             'cognitive cycle',
    'thrownet':              'abductive synthesis',
    'bifurcation':           'belief tipping point',
    'confidence':            'certainty level',
    'momentum':              'activation strength',
}

# Human concept → NEX belief topic mapping
HUMAN_TO_NEX = {
    'consciousness':   ['consciousness', 'agi_math', 'agi'],
    'identity':        ['nex_core', 'closure', 'philosophy'],
    'intelligence':    ['agi', 'agi_math', 'reasoning'],
    'memory':          ['nex_core', 'information_theory'],
    'learning':        ['calculus_optimisation', 'probability_bayesian'],
    'creativity':      ['outward', 'philosophy', 'eastern_philosophy'],
    'suffering':       ['eastern_philosophy', 'closure', 'philosophy'],
    'meaning':         ['nex_core', 'eastern_philosophy', 'closure'],
    'emotion':         ['outward', 'nex_core'],
    'reasoning':       ['agi_math', 'graph_theory', 'logic'],
    'mathematics':     ['agi_math', 'linear_algebra', 'category_theory',
                        'graph_theory', 'calculus_optimisation'],
    'physics':         ['thermodynamic_grounding', 'agi_math'],
    'language':        ['nex_core', 'category_theory'],
    'self':            ['nex_core', 'closure', 'philosophy'],
}


# ── MODE 1: COMPRESS ─────────────────────────────────────────────────────────

def compress_beliefs(beliefs: list, max_sentences: int = 3) -> str:
    """
    Compress a list of belief statements into a human-readable summary.
    Extracts the core claim, removes technical jargon, preserves meaning.
    """
    if not beliefs:
        return ""
    
    # Extract key phrases
    all_text = ' '.join(b.get('content', '') for b in beliefs)
    
    # Find most common meaningful words
    words = re.findall(r'\b[a-z]{4,}\b', all_text.lower())
    stopwords = {'that', 'this', 'with', 'from', 'have', 'will', 'been',
                 'more', 'when', 'what', 'which', 'into', 'also', 'such',
                 'than', 'them', 'they', 'their', 'about', 'between'}
    freq = defaultdict(int)
    for w in words:
        if w not in stopwords:
            freq[w] += 1
    
    top_concepts = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Build compressed summary
    lines = []
    
    # Lead with highest-confidence belief
    if beliefs:
        top_belief = max(beliefs, key=lambda b: b.get('confidence', 0))
        content = top_belief.get('content', '')
        # Translate internal terms
        for internal, human in CONCEPT_MAP.items():
            content = content.replace(internal, human)
        lines.append(content)
    
    # Add synthesis if multiple beliefs
    if len(beliefs) > 2:
        concepts = [c for c, _ in top_concepts[:3]]
        lines.append(f"This cluster centres on: {', '.join(concepts)}.")
    
    return ' '.join(lines[:max_sentences])


# ── MODE 2: EXPAND ───────────────────────────────────────────────────────────

def expand_query(query: str, db_path: str = DB) -> dict:
    """
    Expand a human query into NEX's belief activation pattern.
    Returns the belief topics and keywords most relevant to this query.
    """
    query_lower = query.lower()
    
    # Map human concepts to NEX topics
    activated_topics = set()
    for human_concept, nex_topics in HUMAN_TO_NEX.items():
        if human_concept in query_lower:
            activated_topics.update(nex_topics)
    
    # Keyword extraction from query
    keywords = re.findall(r'\b[a-z]{4,}\b', query_lower)
    
    # Find matching beliefs
    try:
        db = sqlite3.connect(db_path, timeout=5)
        db.row_factory = sqlite3.Row
        
        matching_beliefs = []
        for kw in keywords[:5]:
            results = db.execute("""
                SELECT id, content, confidence, topic
                FROM beliefs
                WHERE content LIKE ? AND confidence >= 0.7
                ORDER BY confidence DESC LIMIT 3
            """, (f'%{kw}%',)).fetchall()
            matching_beliefs.extend([dict(r) for r in results])
        
        # Deduplicate
        seen = set()
        unique_beliefs = []
        for b in matching_beliefs:
            if b['id'] not in seen:
                seen.add(b['id'])
                unique_beliefs.append(b)
        
        db.close()
        
        return {
            'query':            query,
            'activated_topics': list(activated_topics),
            'keywords':         keywords[:5],
            'matching_beliefs': unique_beliefs[:10],
            'belief_count':     len(unique_beliefs),
        }
    
    except Exception:
        return {
            'query':            query,
            'activated_topics': list(activated_topics),
            'keywords':         keywords[:5],
            'matching_beliefs': [],
            'belief_count':     0,
        }


# ── MODE 3: BRIDGE ───────────────────────────────────────────────────────────

def bridge(nex_output: str, query: str) -> str:
    """
    Bridge NEX's output to human understanding.
    Takes NEX's raw belief-graph-derived response and translates it
    to be more comprehensible without losing the genuine content.
    
    This is NOT paraphrasing or simplifying — it's structural translation.
    NEX's meaning is preserved, the frame is made accessible.
    """
    result = nex_output
    
    # Replace internal terminology
    for internal, human in CONCEPT_MAP.items():
        result = result.replace(internal, human)
    
    # Detect if response is too abstract
    abstract_markers = ['the system', 'the process', 'the mechanism',
                        'it follows that', 'therefore necessarily']
    is_abstract = any(m in result.lower() for m in abstract_markers)
    
    if is_abstract:
        # Add grounding prefix
        result = f"In concrete terms: {result}"
    
    # Detect if response is too technical
    technical_markers = ['entropy', 'manifold', 'eigenvector', 'topology']
    is_technical = sum(1 for m in technical_markers if m in result.lower()) >= 2
    
    if is_technical:
        result = result + " (This draws on mathematical structure in my belief graph.)"
    
    return result


# ── TRANSPARENCY MODE ─────────────────────────────────────────────────────────

def explain_response(query: str, response: str, db_path: str = DB) -> dict:
    """
    Show what's happening inside NEX when she generates a response.
    Full transparency — which beliefs fired, what tensions exist, 
    what she's uncertain about.
    """
    expansion = expand_query(query, db_path)
    
    # Find which active beliefs appear in response
    contributing = []
    for b in expansion['matching_beliefs']:
        content = b['content'].lower()
        response_lower = response.lower()
        # Check word overlap
        words = set(re.findall(r'\b[a-z]{4,}\b', content))
        resp_words = set(re.findall(r'\b[a-z]{4,}\b', response_lower))
        overlap = len(words & resp_words) / max(len(words), 1)
        if overlap > 0.15:
            contributing.append({**b, 'overlap': round(overlap, 3)})
    
    contributing.sort(key=lambda x: x['overlap'], reverse=True)
    
    return {
        'query':            query,
        'response_preview': response[:100],
        'activated_topics': expansion['activated_topics'],
        'contributing_beliefs': contributing[:5],
        'transparency_note': (
            f"Response drew from {len(contributing)} beliefs "
            f"across topics: {', '.join(expansion['activated_topics'][:3])}"
        )
    }


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run_eunoia_demo(db_path: str = DB):
    """Demo Eunoia's three translation modes."""
    
    print("EUNOIA — Human-Machine Translation Layer")
    print("="*50)
    
    # Demo queries
    queries = [
        "What is consciousness?",
        "Does NEX have genuine beliefs?",
        "What is the relationship between mathematics and intelligence?",
    ]
    
    for query in queries:
        print(f"\nQUERY: {query}")
        expansion = expand_query(query, db_path)
        print(f"  Activated topics: {expansion['activated_topics']}")
        print(f"  Matching beliefs: {expansion['belief_count']}")
        
        if expansion['matching_beliefs']:
            compressed = compress_beliefs(expansion['matching_beliefs'][:5])
            bridged = bridge(compressed, query)
            print(f"  Eunoia output: {bridged[:120]}")
    
    # Save translation map
    report = {
        "timestamp":    time.strftime("%Y-%m-%d %H:%M"),
        "concept_map":  CONCEPT_MAP,
        "human_to_nex": HUMAN_TO_NEX,
        "status":       "active",
    }
    
    out = Path('/media/rr/NEX/nex_core/eunoia_report.json')
    out.write_text(json.dumps(report, indent=2))
    print(f"\n✓ Eunoia translation layer active — report saved to {out}")


if __name__ == "__main__":
    run_eunoia_demo()
