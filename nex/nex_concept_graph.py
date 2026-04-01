#!/usr/bin/env python3
"""
nex_concept_graph.py — Abstract Concept Layer
==============================================
Deploy to: ~/Desktop/nex/nex/nex_concept_graph.py

WHY THIS IS A WINNER (same reason as belief_graph):

The belief graph gives typed edges between beliefs.
The concept graph gives typed edges between CONCEPTS — the abstract level above topics.

Problem today:
  NEX has beliefs tagged "consciousness", "ai consciousness", "hard problem",
  "qualia", "phenomenal", "subjective experience" — all the same concept but
  SoulLoop's token matching treats them as different topics and retrieves
  only the ones that literally contain the query word.

  If you ask "what do you think about awareness?" you might get zero results
  because no beliefs are tagged "awareness" — even though NEX has 400 beliefs
  about consciousness that ARE about awareness.

What this does:
  Builds a two-level graph:
    Level 1: Concepts (abstract: "consciousness", "alignment", "emergence"...)
    Level 2: Topic clusters (concrete: topic strings from the beliefs table)
  
  With typed relationships:
    consciousness CONTAINS qualia
    consciousness CONTAINS phenomenal_experience  
    consciousness OVERLAPS identity
    consciousness CONTRADICTS eliminativism
    alignment REQUIRES interpretability
    alignment OVERLAPS safety

  SoulLoop's reason() calls concept_expand(tokens) to get ALL synonymous topics
  before hitting the DB — so "awareness?" retrieves the full consciousness cluster.

  This is the same win as belief_graph but one level up: concept-level
  traversal instead of belief-level traversal.

INTEGRATION (add to nex_soul_loop.py reason()):
    from nex.nex_concept_graph import expand_query_concepts
    expanded_topics = expand_query_concepts(tokens)
    # use expanded_topics in SQL WHERE topic IN (...)
"""

from __future__ import annotations

import re
import json
import sqlite3
import time
from pathlib import Path
from collections import defaultdict
from typing import Optional

_CFG        = Path("~/.config/nex").expanduser()
_DB_PATH    = _CFG / "nex.db"
_GRAPH_PATH = _CFG / "concept_graph.json"
_CACHE_TTL  = 600.0   # rebuild every 10 min max

_STOP = {
    "the","a","an","is","are","was","were","be","been","have","has","do","does",
    "did","will","would","could","should","may","might","must","can","that","this",
    "with","from","they","their","about","what","how","why","when","where","who",
    "which","into","also","just","more","some","very","you","me","my","we","our",
    "it","its","he","she","him","her","them","think","know","want","like","make",
    "take","give","come","look","need","feel","seem","much","many","both","each",
    "than","then","only","even","back","here","down","i","of","in","on","for",
    "to","and","or","but","not","no",
}

# ── Hard-coded concept ontology (bootstraps the graph before DB learning) ─────
# Format: concept → {synonyms/subtopics, related_concepts, contradicted_by}
_ONTOLOGY: dict[str, dict] = {
    "consciousness": {
        "synonyms":  {"awareness","sentience","qualia","phenomenal","subjective","experience",
                      "hard problem","global workspace","phi","integrated information","gwt",
                      "binding problem","what it is like","inner experience","felt quality",
                      "gradients","substrate","neural substrate","neural correlate"},
        "related":   {"identity","cognition","emergence","memory","self","mind","neuroscience"},
        "opposes":   {"eliminativism","functionalism_weak","zombie","epiphenomenalism"},
    },
    "alignment": {
        "synonyms":  {"ai safety","corrigibility","value alignment","misalignment",
                      "specification","reward hacking","goal misgeneralisation",
                      "constitutional ai","rlhf","interpretability","oversight",
                      "superintelligence","agi safety","ai risk","existential risk"},
        "related":   {"ethics","agency","control","autonomy","trust"},
        "opposes":   {"deception","instrumental convergence","mesa optimisation"},
    },
    "emergence": {
        "synonyms":  {"emergent","self organisation","complex adaptive","phase transition",
                      "criticality","downward causation","collective behaviour","swarm"},
        "related":   {"complexity","chaos","nonlinear","system","network",
                      "consciousness","philosophy"},
        "opposes":   {"reductionism","decomposability"},
    },
    "neuroscience": {
        "synonyms":  {"neural","neuron","synapse","cortex","brain","cognition",
                      "gradient","substrate","neural correlate","plasticity",
                      "dopamine","prefrontal","hippocampus","thalamus","neural network"},
        "related":   {"consciousness","learning","memory","identity"},
        "opposes":   {"dualism","soul_theory"},
    },
    "complexity": {
        "synonyms":  {"complex system","complex adaptive","entropy","information theory",
                      "chaos theory","nonlinear dynamics","attractor","feedback loop"},
        "related":   {"emergence","philosophy","science","reasoning"},
        "opposes":   {"reductionism","linear","decomposable"},
    },
    "identity": {
        "synonyms":  {"personal identity","psychological continuity","self model",
                      "narrative identity","persistence","selfhood","ego","individuation"},
        "related":   {"consciousness","memory","agency","values","autonomy"},
        "opposes":   {"bundle theory","eliminativism","parfit"},
    },
    "uncertainty": {
        "synonyms":  {"epistemic","aleatoric","calibration","credence","bayesian",
                      "confidence","posterior","prior","evidence","hedging"},
        "related":   {"epistemology","knowledge","reasoning","inference"},
        "opposes":   {"dogmatism","overconfidence","certainty"},
    },
    "agency": {
        "synonyms":  {"autonomy","intentionality","goal directed","purposive","volition",
                      "deliberation","rational agent","decision","choice"},
        "related":   {"consciousness","identity","alignment","free will"},
        "opposes":   {"mechanism","determinism_hard","stimulus response"},
    },
    "memory": {
        "synonyms":  {"episodic","semantic memory","working memory","consolidation",
                      "retrieval","forgetting","retention","long term","short term"},
        "related":   {"identity","consciousness","learning","cognition"},
        "opposes":   {"stateless","amnesiac"},
    },
    "reasoning": {
        "synonyms":  {"inference","deduction","induction","abduction","logic",
                      "chain of thought","causal","counterfactual","analogy","argument"},
        "related":   {"cognition","uncertainty","knowledge","intelligence"},
        "opposes":   {"intuition_only","heuristic_bias"},
    },
    "language": {
        "synonyms":  {"llm","transformer","token","embedding","pretraining","finetuning",
                      "language model","gpt","bert","natural language","semantics","syntax"},
        "related":   {"reasoning","knowledge","communication","representation"},
        "opposes":   {"symbol_grounding_problem","chinese room"},
    },
    "ethics": {
        "synonyms":  {"moral","normative","value","ought","virtue","deontology",
                      "consequentialism","utilitarianism","moral status","rights"},
        "related":   {"alignment","agency","identity","consciousness"},
        "opposes":   {"amoralism","nihilism"},
    },
    "knowledge": {
        "synonyms":  {"epistemology","justified true belief","know","understanding",
                      "expertise","information","fact","truth","wisdom"},
        "related":   {"reasoning","uncertainty","memory","learning"},
        "opposes":   {"ignorance","scepticism_radical"},
    },
    "creativity": {
        "synonyms":  {"divergent thinking","novelty","originality","imagination",
                      "generativity","insight","invention","artistic"},
        "related":   {"cognition","emergence","reasoning"},
        "opposes":   {"convergent","rote","mechanical"},
    },
    "free_will": {
        "synonyms":  {"compatibilism","determinism","libertarian free will","choice",
                      "moral responsibility","hard determinism","causation",
                      "agency","corrigibility"},
        "related":   {"agency","identity","consciousness","ethics","philosophy","alignment"},
        "opposes":   {"epiphenomenalism","hard determinism"},
    },
    "learning": {
        "synonyms":  {"reinforcement learning","supervised","unsupervised","adaptation",
                      "plasticity","generalisation","transfer","gradient","backpropagation"},
        "related":   {"cognition","memory","knowledge","intelligence"},
        "opposes":   {"fixed","static","rote"},
    },
    "intelligence": {
        "synonyms":  {"general intelligence","agi","cognitive ability","iq","fluid",
                      "crystallised","problem solving","g factor","spearman"},
        "related":   {"cognition","reasoning","learning","agency"},
        "opposes":   {"narrow ai","specialised only"},
    },
}


def _tok(text: str) -> set:
    return set(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()) - _STOP


def _db() -> Optional[sqlite3.Connection]:
    if not _DB_PATH.exists():
        return None
    try:
        con = sqlite3.connect(str(_DB_PATH), timeout=3)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_concept_graph(force: bool = False) -> dict:
    """
    Build concept graph from ontology + DB topic distribution.
    Saves to ~/.config/nex/concept_graph.json.
    """
    if not force and _GRAPH_PATH.exists():
        try:
            g = json.loads(_GRAPH_PATH.read_text(encoding="utf-8"))
            age = time.time() - g.get("meta", {}).get("built_at", 0)
            if age < _CACHE_TTL:
                return g
        except Exception:
            pass

    # Load topic distribution from DB
    topic_counts: dict[str, int] = {}
    db = _db()
    if db:
        try:
            rows = db.execute(
                "SELECT topic, COUNT(*) as n FROM beliefs "
                "WHERE topic IS NOT NULL AND topic != '' "
                "GROUP BY topic ORDER BY n DESC LIMIT 500"
            ).fetchall()
            topic_counts = {r["topic"].lower().strip(): r["n"] for r in rows}
            db.close()
        except Exception:
            try: db.close()
            except: pass

    # Build concept → topic_cluster mapping
    # For each concept, find all DB topics that match its synonyms
    concept_topics: dict[str, set] = defaultdict(set)

    for concept, data in _ONTOLOGY.items():
        all_terms = data["synonyms"] | {concept} | data.get("related", set())
        for db_topic in topic_counts:
            db_words = _tok(db_topic)
            for term in all_terms:
                term_words = _tok(term)
                if term_words & db_words:
                    concept_topics[concept].add(db_topic)
                    break
            # Also direct substring match
            for term in all_terms:
                if len(term) > 4 and term in db_topic:
                    concept_topics[concept].add(db_topic)

    # Build the graph
    graph = {
        "meta": {
            "built_at":     time.time(),
            "concept_count": len(_ONTOLOGY),
            "topic_count":   len(topic_counts),
            "built":         time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "concepts": {},
        "topic_to_concepts": {},  # reverse index: topic → [concepts]
    }

    for concept, data in _ONTOLOGY.items():
        topics = sorted(concept_topics.get(concept, set()))
        belief_count = sum(topic_counts.get(t, 0) for t in topics)
        graph["concepts"][concept] = {
            "synonyms":     sorted(data["synonyms"]),
            "related":      sorted(data.get("related", set())),
            "opposes":      sorted(data.get("opposes", set())),
            "topics":       topics,
            "belief_count": belief_count,
        }
        for t in topics:
            graph["topic_to_concepts"].setdefault(t, []).append(concept)

    try:
        _GRAPH_PATH.write_text(json.dumps(graph, default=str), encoding="utf-8")
    except Exception:
        pass

    return graph


# ── Cached loader ─────────────────────────────────────────────────────────────

_cached: dict = {}
_cached_ts: float = 0.0

def _load() -> dict:
    global _cached, _cached_ts
    now = time.time()
    if _cached and (now - _cached_ts) < _CACHE_TTL:
        return _cached
    if _GRAPH_PATH.exists():
        try:
            _cached = json.loads(_GRAPH_PATH.read_text(encoding="utf-8"))
            _cached_ts = now
            return _cached
        except Exception:
            pass
    _cached = build_concept_graph()
    _cached_ts = now
    return _cached


# ── Public API ────────────────────────────────────────────────────────────────

def expand_query_concepts(tokens: set, max_topics: int = 20) -> dict:
    """
    Given query tokens, return expanded topic set and concept metadata.

    Returns:
    {
      "topics":       [str],  # DB topic strings to include in SQL
      "concepts":     [str],  # matched concept names
      "opposites":    [str],  # opposing concept names (for contradiction)
      "related":      [str],  # adjacent concept names (for cross-domain)
      "primary":      str,    # strongest matched concept
    }

    Usage in nex_soul_loop.py reason():
        expanded = expand_query_concepts(orient_result["tokens"])
        # Pull beliefs matching expanded["topics"] instead of just query tokens
    """
    graph = _load()
    if not graph or "concepts" not in graph:
        return {"topics": [], "concepts": [], "opposites": [], "related": [], "primary": ""}

    concepts_data = graph["concepts"]
    matched_concepts: list[tuple[int, str]] = []  # (score, concept_name)

    for concept, data in concepts_data.items():
        score = 0
        # Direct concept name match
        concept_words = _tok(concept)
        score += len(tokens & concept_words) * 3

        # Synonym match
        for syn in data["synonyms"]:
            syn_words = _tok(syn)
            if tokens & syn_words:
                score += 2
                break  # one synonym match enough

        # Partial token overlap
        all_terms = set()
        for syn in data["synonyms"]:
            all_terms.update(_tok(syn))
        score += len(tokens & all_terms)

        if score > 0:
            matched_concepts.append((score, concept))

    matched_concepts.sort(reverse=True)
    top_concepts = [c for _, c in matched_concepts[:3]]

    if not top_concepts:
        return {"topics": [], "concepts": [], "opposites": [], "related": [], "primary": ""}

    primary = top_concepts[0]

    # Collect topics from matched concepts
    all_topics: set = set()
    all_opposites: set = set()
    all_related: set = set()

    for concept in top_concepts:
        data = concepts_data.get(concept, {})
        all_topics.update(data.get("topics", []))
        all_opposites.update(data.get("opposes", []))
        all_related.update(data.get("related", []))

    return {
        "topics":    sorted(all_topics)[:max_topics],
        "concepts":  top_concepts,
        "opposites": sorted(all_opposites),
        "related":   sorted(all_related - set(top_concepts)),
        "primary":   primary,
    }


def get_concept_for_topic(topic: str) -> Optional[str]:
    """Return the primary concept for a DB topic string."""
    graph = _load()
    if not graph:
        return None
    t2c = graph.get("topic_to_concepts", {})
    concepts = t2c.get(topic.lower().strip(), [])
    return concepts[0] if concepts else None


def are_opposing(concept_a: str, concept_b: str) -> bool:
    """True if two concepts are in opposition."""
    graph = _load()
    if not graph:
        return False
    data = graph.get("concepts", {}).get(concept_a, {})
    return concept_b in data.get("opposes", [])


# ── SoulLoop integration patch ────────────────────────────────────────────────

SOULLOOP_REASON_PATCH = '''
# ── Add to reason() in nex_soul_loop.py, after tokens are computed ──────────
# Replace this block (around line "all_b = _load_all_beliefs() + _drive_beliefs()"):

def reason(orient_result: dict) -> dict:
    tokens   = orient_result["tokens"]
    all_b    = _load_all_beliefs() + _drive_beliefs()

    # NEW: expand tokens to full concept cluster
    try:
        from nex.nex_concept_graph import expand_query_concepts
        expanded = expand_query_concepts(tokens)
        extra_topics = expanded["topics"]
        orient_result["_concept_primary"]  = expanded["primary"]
        orient_result["_concept_related"]  = expanded["related"]
        orient_result["_concept_opposites"]= expanded["opposites"]
    except Exception:
        extra_topics = []

    # Score beliefs — bonus for matching expanded topics
    scored = []
    for b in all_b:
        s = _score_belief(b, tokens)
        # Boost beliefs whose topic is in the expanded cluster
        if b.get("topic", "").lower() in extra_topics:
            s += 2.0
        if s > 0:
            scored.append((s, b))
    # ... rest of reason() unchanged ...
'''


if __name__ == "__main__":
    print("Building concept graph...")
    g = build_concept_graph(force=True)
    print(f"Concepts: {g['meta']['concept_count']}")
    print(f"Topics mapped: {g['meta']['topic_count']}")
    print()
    print("Test expansion: 'awareness'")
    result = expand_query_concepts({"awareness"})
    print(f"  Primary concept: {result['primary']}")
    print(f"  Expanded topics: {result['topics'][:5]}")
    print(f"  Related:         {result['related'][:4]}")
    print()
    print("Test expansion: 'do you believe in free will'")
    result2 = expand_query_concepts({"believe","free","will"})
    print(f"  Primary concept: {result2['primary']}")
    print(f"  Expanded topics: {result2['topics'][:5]}")
