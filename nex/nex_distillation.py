"""
nex_distillation.py — Self-Distillation Loop
=============================================
Extracts a compact "core self" subgraph from NEX's full belief
graph. The core self contains the highest-quality, most integrated,
most identity-relevant beliefs — a distilled essence.

Runs during low-tension idle windows (like dream cycle).
Output: ~/.config/nex/core_self.json — ~50 beliefs, ~100 edges.

Used by: narrative thread, goal engine, reply prompts, snapshots.
"""
from __future__ import annotations
import json, time, logging, sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.distillation")

_DB_PATH        = Path.home() / ".config/nex/nex.db"
_GRAPH_PATH     = Path.home() / ".config/nex/belief_graph.json"
_CORE_SELF_PATH = Path.home() / ".config/nex/core_self.json"
_MIN_INTERVAL   = 3600    # 1 hour between distillations
_CORE_SIZE      = 50      # max beliefs in core self
_last_run: float = 0


def distill(tension: float = 100.0, force: bool = False) -> Optional[dict]:
    """
    Build core self subgraph. Returns summary or None if skipped.
    Gates on tension < 35 and time interval.
    """
    global _last_run
    now = time.time()
    if not force and tension > 35:
        return None
    if not force and now - _last_run < _MIN_INTERVAL:
        return None

    _last_run = now
    log.info(f"[DISTILL] Building core self (tension={tension:.1f})")

    # ── Step 1: High-confidence, non-loop beliefs ─────────
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, topic, content, confidence, energy, is_identity,
                   successful_uses, origin
            FROM beliefs
            WHERE confidence > 0.70
              AND (loop_flag IS NULL OR loop_flag = 0)
              AND (locked = 1 OR confidence > 0.85 OR is_identity = 1
                   OR successful_uses > 3)
            ORDER BY (confidence * 0.4 + energy * 0.3
                      + is_identity * 0.2 + successful_uses * 0.01) DESC
            LIMIT ?
        """, (_CORE_SIZE,)).fetchall()
        conn.close()
    except Exception as e:
        log.warning(f"[DISTILL] DB query failed: {e}")
        return None

    core_beliefs = [dict(r) for r in rows]
    if len(core_beliefs) < 5:
        return None

    # ── Step 2: Extract relevant graph edges ──────────────
    core_ids = {str(b["id"]) for b in core_beliefs}
    core_graph = {}
    try:
        if _GRAPH_PATH.exists():
            full_graph = json.loads(_GRAPH_PATH.read_text())
            for nid, node in full_graph.items():
                if nid in core_ids:
                    # Keep only edges to other core nodes
                    filtered = {
                        k: [e for e in v if e in core_ids]
                        for k, v in node.items()
                        if k in ("supports", "explains", "contradicts")
                    }
                    core_graph[nid] = {**node, **filtered}
    except Exception:
        pass

    # ── Step 3: Phi scores for core nodes ─────────────────
    phi_scores = {}
    try:
        from nex_phi_proxy import compute_phi_proxy
        for nid in core_ids:
            phi_scores[nid] = compute_phi_proxy(nid, core_graph)
    except Exception:
        pass

    # ── Step 4: Topic distribution of core ────────────────
    from collections import Counter
    topic_dist = Counter(b["topic"] for b in core_beliefs if b["topic"])

    result = {
        "timestamp": now,
        "tension_at_distill": tension,
        "belief_count": len(core_beliefs),
        "edge_count": sum(
            len(n.get("supports", [])) + len(n.get("explains", []))
            for n in core_graph.values()
        ),
        "top_topics": topic_dist.most_common(5),
        "avg_confidence": sum(b["confidence"] for b in core_beliefs) / len(core_beliefs),
        "identity_beliefs": sum(1 for b in core_beliefs if b["is_identity"]),
        "beliefs": core_beliefs[:20],   # top 20 for inspection
        "graph": core_graph,
        "phi_scores": phi_scores,
    }

    try:
        _CORE_SELF_PATH.write_text(json.dumps(result, indent=2, default=str))
        log.info(f"[DISTILL] Core self: {len(core_beliefs)} beliefs, "
                 f"{result['edge_count']} edges, "
                 f"avg_conf={result['avg_confidence']:.3f}")
    except Exception as e:
        log.warning(f"[DISTILL] save failed: {e}")

    return result


def load_core_self() -> Optional[dict]:
    try:
        if _CORE_SELF_PATH.exists():
            return json.loads(_CORE_SELF_PATH.read_text())
    except Exception:
        pass
    return None


def core_self_summary() -> str:
    """Human-readable summary of current core self."""
    core = load_core_self()
    if not core:
        return "Core self not yet distilled."
    age_h = (time.time() - core.get("timestamp", 0)) / 3600
    topics = ", ".join(f"'{t}' ({c})" for t, c in core.get("top_topics", [])[:3])
    return (
        f"Core self ({age_h:.1f}h ago): {core['belief_count']} beliefs, "
        f"avg_conf={core['avg_confidence']:.2f}, "
        f"dominant topics: {topics}."
    )
