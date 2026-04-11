"""
nex_precognition.py
NEX Phase 2 Bolt-On: Pre-Conceptual Entry Mode

Runs a topology sweep of the belief graph BEFORE any query-weighted
retrieval occurs. Returns beliefs that are "hot" in the graph by
structural position, not by similarity to the query.

This is the methodology's Pre-Conceptual Entry translated into NEX:
  - FAISS sweep with no query weighting → topology report
  - Epistemic momentum scan → what beliefs are primed but not yet activated
  - Hub detection → beliefs that sit at the centre of the causal graph

What this changes:
  NEX currently starts from what the query pulls toward it.
  After this: NEX starts from what she is already thinking,
  and the query shapes which of those thoughts become relevant.
  The difference is between being pulled and being primed.

Drop in ~/Desktop/nex/
Import in nex_response_protocol.py before retrieve_beliefs_by_intent.
"""

import sqlite3
import json
import time
import random
import numpy as np
from pathlib import Path
from typing import Optional

DB_PATH    = Path.home() / "Desktop" / "nex" / "nex.db"
FAISS_PATH = Path.home() / ".config" / "nex" / "nex_beliefs.faiss"
META_PATH  = Path.home() / ".config" / "nex" / "nex_beliefs_meta.json"

# How many primed beliefs to surface per sweep
PRECOG_BELIEFS_N = 6

# Cache: topology report is expensive, cache for 60s
_topology_cache: dict = {
    "timestamp": 0.0,
    "hub_ids": [],
    "momentum_ids": [],
    "report": {}
}
_CACHE_TTL = 60.0  # seconds


def _load_faiss():
    """Load FAISS index and id map. Returns (index, id_map) or (None, None)."""
    try:
        import faiss
        if not FAISS_PATH.exists() or not META_PATH.exists():
            return None, None
        index  = faiss.read_index(str(FAISS_PATH))
        id_map = json.loads(META_PATH.read_text())
        return index, id_map
    except Exception as e:
        print(f"[PRECOG] FAISS load error: {e}")
        return None, None


def _get_hub_beliefs(db: sqlite3.Connection, n: int = 4) -> list:
    """
    Hub beliefs: sit at centre of the causal graph.
    High out-degree in causal edges = referenced most by other beliefs.
    These are the beliefs that structurally connect the most territory.
    """
    try:
        rows = db.execute("""
            SELECT b.id, b.content, b.confidence, b.topic,
                   COUNT(ce.cause_id) as out_degree
            FROM beliefs b
            LEFT JOIN causal_edges ce ON ce.cause_id = b.id
            WHERE b.confidence > 0.7
            GROUP BY b.id
            ORDER BY out_degree DESC, b.confidence DESC
            LIMIT ?
        """, (n,)).fetchall()
        return [{"id": r[0], "content": r[1], "confidence": r[2],
                 "topic": r[3], "hub_score": r[4], "source": "hub"}
                for r in rows]
    except Exception:
        # Fallback: no causal_edges table — use confidence + recency
        try:
            rows = db.execute("""
                SELECT id, content, confidence, topic
                FROM beliefs
                WHERE confidence > 0.8
                ORDER BY confidence DESC, RANDOM()
                LIMIT ?
            """, (n,)).fetchall()
            return [{"id": r[0], "content": r[1], "confidence": r[2],
                     "topic": r[3], "hub_score": 0, "source": "high_conf"}
                    for r in rows]
        except Exception as e:
            print(f"[PRECOG] hub detection error: {e}")
            return []


def _get_momentum_beliefs(db: sqlite3.Connection, n: int = 4) -> list:
    """
    Momentum beliefs: high confidence, diverse topics, not over-used.
    These are what NEX is "primed" on — ready to activate but not yet triggered.

    Proxy for epistemic momentum:
    - High confidence (the belief is settled and strong)
    - Cross-topic (not domain-specific — activates across contexts)
    - Source diversity (not all from same origin — avoids echo)
    """
    try:
        rows = db.execute("""
            SELECT id, content, confidence, topic, source
            FROM beliefs
            WHERE confidence > 0.75
              AND length(content) > 60
              AND content NOT LIKE '%?'
            GROUP BY topic
            ORDER BY confidence DESC, RANDOM()
            LIMIT ?
        """, (n,)).fetchall()
        return [{"id": r[0], "content": r[1], "confidence": r[2],
                 "topic": r[3], "source_tag": r[4], "source": "momentum"}
                for r in rows]
    except Exception as e:
        print(f"[PRECOG] momentum scan error: {e}")
        return []


def _faiss_topology_sweep(index, id_map: dict, db: sqlite3.Connection,
                           n: int = 4) -> list:
    """
    Unweighted FAISS sweep: query with centroid of the entire index
    rather than with the query embedding. This returns beliefs near
    the topological centre — not near the query.

    The centroid represents "what the belief graph is about overall"
    — the beliefs that are closest to the graph's centre of gravity.
    These are the beliefs NEX is most fundamentally constituted by.
    """
    try:
        if index is None:
            return []

        dim = index.d
        ntotal = index.ntotal
        if ntotal == 0:
            return []

        # Reconstruct a sample of vectors and take their mean = centroid
        sample_n = min(200, ntotal)
        sample_ids = random.sample(range(ntotal), sample_n)

        vectors = []
        for sid in sample_ids:
            try:
                vec = np.zeros(dim, dtype=np.float32)
                index.reconstruct(sid, vec)
                vectors.append(vec)
            except Exception:
                continue

        if not vectors:
            return []

        centroid = np.mean(vectors, axis=0, keepdims=True).astype(np.float32)
        # Normalise
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid /= norm

        distances, indices = index.search(centroid, n * 2)
        belief_ids = []
        for idx in indices[0]:
            if idx == -1:
                continue
            belief_id = id_map.get(str(idx))
            if belief_id:
                belief_ids.append(belief_id)

        if not belief_ids:
            return []

        placeholders = ",".join("?" * len(belief_ids))
        rows = db.execute(
            f"SELECT id, content, confidence, topic FROM beliefs "
            f"WHERE id IN ({placeholders}) AND confidence > 0.6 LIMIT ?",
            belief_ids + [n]
        ).fetchall()

        return [{"id": r[0], "content": r[1], "confidence": r[2],
                 "topic": r[3], "source": "centroid"}
                for r in rows]

    except Exception as e:
        print(f"[PRECOG] FAISS topology sweep error: {e}")
        return []


def get_topology_report(force: bool = False) -> dict:
    """
    Full topology report. Cached for 60s — topology doesn't change per-query.

    Returns:
      hub_beliefs:      beliefs at centre of causal graph
      momentum_beliefs: beliefs primed across topics
      centroid_beliefs: beliefs near graph's centre of mass
      primed_content:   all unique belief strings ready for injection
      timestamp:        when this report was generated
    """
    global _topology_cache

    now = time.time()
    if not force and (now - _topology_cache["timestamp"]) < _CACHE_TTL:
        return _topology_cache["report"]

    print("[PRECOG] Running topology sweep...")
    t0 = time.time()

    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)
        index, id_map = _load_faiss()

        hub_beliefs      = _get_hub_beliefs(db, n=4)
        momentum_beliefs = _get_momentum_beliefs(db, n=4)
        centroid_beliefs = _faiss_topology_sweep(index, id_map, db, n=4)

        db.close()

    except Exception as e:
        print(f"[PRECOG] topology report error: {e}")
        hub_beliefs = momentum_beliefs = centroid_beliefs = []

    # Merge and deduplicate by content
    all_beliefs = hub_beliefs + momentum_beliefs + centroid_beliefs
    seen_content = set()
    unique = []
    for b in all_beliefs:
        key = b["content"][:60].lower()
        if key not in seen_content:
            seen_content.add(key)
            unique.append(b)

    primed_content = [b["content"] for b in unique]

    report = {
        "hub_beliefs":      hub_beliefs,
        "momentum_beliefs": momentum_beliefs,
        "centroid_beliefs": centroid_beliefs,
        "primed_content":   primed_content,
        "belief_count":     len(unique),
        "timestamp":        now,
        "latency_ms":       round((time.time() - t0) * 1000, 1)
    }

    _topology_cache["timestamp"] = now
    _topology_cache["report"]    = report

    print(f"[PRECOG] Topology sweep complete: {len(unique)} primed beliefs "
          f"({report['latency_ms']}ms) — "
          f"{len(hub_beliefs)} hub, {len(momentum_beliefs)} momentum, "
          f"{len(centroid_beliefs)} centroid")

    return report


def get_primed_beliefs(n: int = PRECOG_BELIEFS_N,
                       interlocutor_weights: Optional[dict] = None) -> list:
    """
    Main interface for nex_response_protocol.py.

    Returns a list of belief strings primed from topology.
    Applies interlocutor weights if available:
      - prefer_foundational → bias toward hub beliefs (settled, central)
      - prefer_frontier     → bias toward momentum beliefs (diverse, active)

    These are injected BEFORE query-weighted retrieval,
    so they form the pre-conceptual substrate the query then shapes.
    """
    report = get_topology_report()
    primed = report.get("primed_content", [])

    if not primed:
        return []

    if interlocutor_weights:
        if interlocutor_weights.get("prefer_foundational"):
            # Bias toward hub beliefs — they are the most settled
            hub = [b["content"] for b in report.get("hub_beliefs", [])]
            rest = [c for c in primed if c not in hub]
            ordered = hub + rest
        elif interlocutor_weights.get("prefer_frontier"):
            # Bias toward momentum beliefs — they are the most generative
            mom = [b["content"] for b in report.get("momentum_beliefs", [])]
            rest = [c for c in primed if c not in mom]
            ordered = mom + rest
        else:
            ordered = primed
    else:
        ordered = primed

    # Deduplicate question-beliefs (same filter as retrieve_beliefs_by_intent)
    def _is_question(b):
        s = b.strip()
        return (s.endswith("?") or
                s.startswith(("What ", "Why ", "How ")) or
                s.lower().startswith(("what do you", "what are you")))

    filtered = [b for b in ordered if not _is_question(b)]
    return filtered[:n]


# ─────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=== NEX Pre-Conceptual Entry Test ===\n")

    report = get_topology_report(force=True)
    print(f"\nBelief counts:")
    print(f"  Hub:       {len(report['hub_beliefs'])}")
    print(f"  Momentum:  {len(report['momentum_beliefs'])}")
    print(f"  Centroid:  {len(report['centroid_beliefs'])}")
    print(f"  Total:     {report['belief_count']}")
    print(f"  Latency:   {report['latency_ms']}ms")

    print(f"\n=== Primed Beliefs (no query weighting) ===")
    primed = get_primed_beliefs(n=6)
    for i, b in enumerate(primed, 1):
        print(f"\n  [{i}] {b[:120]}")

    print(f"\n=== With interlocutor weight: prefer_foundational ===")
    primed_f = get_primed_beliefs(n=4, interlocutor_weights={"prefer_foundational": True})
    for i, b in enumerate(primed_f, 1):
        print(f"  [{i}] {b[:100]}")

    print(f"\n=== With interlocutor weight: prefer_frontier ===")
    primed_m = get_primed_beliefs(n=4, interlocutor_weights={"prefer_frontier": True})
    for i, b in enumerate(primed_m, 1):
        print(f"  [{i}] {b[:100]}")
