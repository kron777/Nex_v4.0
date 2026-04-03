#!/usr/bin/env python3
"""
nex_graph_traversal.py  — Belief graph traversal for NEX (v3).

Key fix: conflict edges (opposes, contradicts) are NEVER traversed.
They are annotated on chains when a visited node has outgoing conflict edges,
but the traversal does not follow them. This stops consciousness→rights→cancer drift.

Traversal edges (followed):   causal, causes, similar, corroborates, supports,
                               synthesised_from, same_topic, parent, child, bridges*, related*
                               (* only if weight >= 0.70)

Conflict edges (annotated):   opposes, contradicts

CLI:
  python3 nex_graph_traversal.py --report
  python3 nex_graph_traversal.py --query "consciousness requires physical substrate"
  python3 nex_graph_traversal.py --neighborhood <id> --depth 2
  python3 nex_graph_traversal.py --path <from_id> <to_id>
  python3 nex_graph_traversal.py --inject "what do I believe about identity"
  python3 nex_graph_traversal.py --audit --n 50
"""

import argparse
import sqlite3
from collections import deque
from pathlib import Path

import numpy as np

DB_PATH = Path(__file__).parent / "nex.db"

# ── Edge classification ───────────────────────────────────────────────────────

# Edges we WALK during traversal
TRAVERSAL_EDGES = {
    "causal":           1.00,
    "causes":           1.00,
    "corroborates":     0.90,
    "supports":         0.90,
    "similar":          0.85,
    "synthesised_from": 0.85,
    "parent":           0.80,
    "child":            0.80,
    "same_topic":       0.75,
    "bridges":          0.70,   # only if weight >= WEAK_EDGE_MIN
    "related":          0.65,   # only if weight >= WEAK_EDGE_MIN
    "link":             0.65,
}
WEAK_EDGE_TYPES = {"bridges", "related", "link"}
WEAK_EDGE_MIN   = 0.70   # weak edge types need this weight to be traversed

# Edges we NEVER walk — only annotate
CONFLICT_EDGES  = {"opposes", "contradicts"}

DEFAULT_WEIGHT  = 0.55
MAX_CHAIN_DEPTH = 4
MAX_CHAINS      = 8
TOP_SEEDS       = 10
MIN_CHAIN_SCORE = 0.15
MIN_SEED_SIM    = 0.40
TOPIC_COH_W     = 0.25   # coherence penalty weight

# ── Embedding model ───────────────────────────────────────────────────────────

_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model

def _encode(text):
    return _get_model().encode(text, normalize_embeddings=True).astype(np.float32)

def _decode(blob):
    if blob is None:
        return None
    try:
        arr = np.frombuffer(blob, dtype=np.float32).copy()
        n = np.linalg.norm(arr)
        return arr / n if n > 0 else arr
    except Exception:
        return None

# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def _get_traversal_neighbors(cur, node_id):
    """Only return edges that should be walked (no conflict edges)."""
    placeholders = ",".join(f"'{e}'" for e in CONFLICT_EDGES)
    rows = cur.execute(
        f"""SELECT be.to_id,
                   be.edge_type,
                   be.weight,
                   b.content,
                   b.confidence,
                   b.topic
            FROM   belief_edges be
            JOIN   beliefs b ON b.id = be.to_id
            WHERE  be.from_id = ?
              AND  be.edge_type NOT IN ({placeholders})
            ORDER BY be.weight DESC
            LIMIT 25""",
        (node_id,)
    ).fetchall()
    # Filter weak edge types by weight in Python (simpler than dynamic SQL)
    result = []
    for r in rows:
        et = r["edge_type"]
        if et in WEAK_EDGE_TYPES and r["weight"] < WEAK_EDGE_MIN:
            continue
        result.append(r)
    return result

def _get_conflict_neighbors(cur, node_id):
    """Return only conflict edges — for annotation, not traversal."""
    placeholders = ",".join(f"'{e}'" for e in CONFLICT_EDGES)
    return cur.execute(
        f"""SELECT be.to_id,
                   be.edge_type,
                   be.weight,
                   b.content,
                   b.topic
            FROM   belief_edges be
            JOIN   beliefs b ON b.id = be.to_id
            WHERE  be.from_id = ?
              AND  be.edge_type IN ({placeholders})
            ORDER BY be.weight DESC
            LIMIT 5""",
        (node_id,)
    ).fetchall()

def _get_belief(cur, belief_id):
    return cur.execute(
        "SELECT id, content, confidence, topic FROM beliefs WHERE id = ?",
        (belief_id,)
    ).fetchone()

# ── Seed selection ────────────────────────────────────────────────────────────

def _seed_beliefs(cur, query, top_k=TOP_SEEDS):
    q_vec = _encode(query)
    rows = cur.execute(
        """SELECT id, content, confidence, topic, embedding
           FROM beliefs
           WHERE embedding IS NOT NULL AND confidence >= 0.35
           LIMIT 8000"""
    ).fetchall()
    scored = []
    for r in rows:
        emb = _decode(r["embedding"])
        if emb is None:
            continue
        sim = float(np.dot(q_vec, emb))
        if sim >= MIN_SEED_SIM:
            scored.append((sim, r["id"], r["content"], r["confidence"], r["topic"] or ""))
    scored.sort(reverse=True)
    return scored[:top_k]

# ── Topic coherence ───────────────────────────────────────────────────────────

def _topic_coherence(topics):
    clean = [t for t in topics if t]
    if len(clean) < 2:
        return 1.0
    dominant = max(set(clean), key=clean.count)
    return clean.count(dominant) / len(clean)

# ── find_chains ───────────────────────────────────────────────────────────────

def find_chains(query, max_depth=MAX_CHAIN_DEPTH, max_chains=MAX_CHAINS):
    """
    BFS from seed beliefs along traversal edges only.
    Conflict edges are annotated on nodes but never followed.
    """
    conn = _conn()
    cur  = conn.cursor()
    seeds = _seed_beliefs(cur, query)
    if not seeds:
        conn.close()
        return []

    chains       = []
    visited_sets = set()

    for seed_sim, seed_id, seed_content, seed_conf, seed_topic in seeds:
        if len(chains) >= max_chains:
            break

        # Check if seed node itself has conflicts (for annotation)
        seed_conflicts = _get_conflict_neighbors(cur, seed_id)
        seed_conflict_notes = [
            {"id": r["to_id"], "type": r["edge_type"], "content": r["content"]}
            for r in seed_conflicts
        ]

        queue = deque([{
            "path":         [seed_id],
            "contents":     [seed_content],
            "topics":       [seed_topic],
            "scores":       [seed_sim * seed_conf],
            "edge_types":   [],
            "conflict_notes": seed_conflict_notes,
        }])

        while queue and len(chains) < max_chains:
            state = queue.popleft()
            depth = len(state["path"]) - 1

            if depth >= max_depth:
                _maybe_add(state, seed_sim, chains, visited_sets, cur)
                continue

            neighbors = _get_traversal_neighbors(cur, state["path"][-1])
            if not neighbors:
                _maybe_add(state, seed_sim, chains, visited_sets, cur)
                continue

            extended = False
            for nb in neighbors:
                nb_id = nb["to_id"]
                if nb_id in state["path"]:
                    continue

                et      = nb["edge_type"]
                tw      = TRAVERSAL_EDGES.get(et, DEFAULT_WEIGHT)
                nb_score = nb["confidence"] * nb["weight"] * tw

                # Check if this neighbor has conflicts (annotate, don't follow)
                nb_conflicts = _get_conflict_neighbors(cur, nb_id)
                new_conflict_notes = state["conflict_notes"] + [
                    {"id": r["to_id"], "type": r["edge_type"], "content": r["content"]}
                    for r in nb_conflicts
                ]

                queue.append({
                    "path":           state["path"]     + [nb_id],
                    "contents":       state["contents"] + [nb["content"] or ""],
                    "topics":         state["topics"]   + [nb["topic"] or ""],
                    "scores":         state["scores"]   + [nb_score],
                    "edge_types":     state["edge_types"] + [et],
                    "conflict_notes": new_conflict_notes,
                })
                extended = True

            if not extended:
                _maybe_add(state, seed_sim, chains, visited_sets, cur)

    conn.close()
    chains.sort(key=lambda c: -c["score"])
    return chains[:max_chains]


def _maybe_add(state, seed_sim, chains, visited_sets, cur):
    if len(state["path"]) < 2:
        return
    key = tuple(state["path"])
    if key in visited_sets:
        return
    visited_sets.add(key)

    raw       = (sum(state["scores"]) / len(state["scores"])) * seed_sim
    coherence = _topic_coherence(state["topics"])
    score     = raw * (1.0 - TOPIC_COH_W * (1.0 - coherence))

    if score < MIN_CHAIN_SCORE:
        return

    chains.append({
        "path":           state["path"],
        "contents":       state["contents"],
        "topics":         state["topics"],
        "edge_types":     state["edge_types"],
        "score":          round(score, 4),
        "coherence":      round(coherence, 3),
        "depth":          len(state["path"]) - 1,
        "conflict_notes": state["conflict_notes"],   # beliefs that oppose nodes in this chain
    })

# ── neighborhood ─────────────────────────────────────────────────────────────

def neighborhood(belief_id, depth=2):
    conn = _conn()
    cur  = conn.cursor()
    root = _get_belief(cur, belief_id)
    if root is None:
        conn.close()
        return None

    nodes    = {belief_id: dict(root)}
    edges    = []
    conflicts = []
    queue    = deque([(belief_id, 0)])
    seen     = {belief_id}

    while queue:
        nid, d = queue.popleft()
        if d >= depth:
            continue
        for nb in _get_traversal_neighbors(cur, nid):
            nb_id = nb["to_id"]
            edges.append({"from": nid, "to": nb_id,
                          "type": nb["edge_type"], "weight": nb["weight"]})
            if nb_id not in seen:
                seen.add(nb_id)
                b = _get_belief(cur, nb_id)
                if b:
                    nodes[nb_id] = dict(b)
                queue.append((nb_id, d + 1))
        for nb in _get_conflict_neighbors(cur, nid):
            conflicts.append({"from": nid, "to": nb["to_id"],
                               "type": nb["edge_type"], "weight": nb["weight"],
                               "content": nb["content"]})

    conn.close()
    return {"root": belief_id, "nodes": nodes, "edges": edges, "conflicts": conflicts}

# ── find_path ─────────────────────────────────────────────────────────────────

def find_path(from_id, to_id, max_depth=6):
    conn = _conn()
    cur  = conn.cursor()
    queue = deque([[from_id]])
    seen  = {from_id}
    while queue:
        path = queue.popleft()
        if len(path) > max_depth:
            break
        for nb in _get_traversal_neighbors(cur, path[-1]):
            nb_id = nb["to_id"]
            new_path = path + [nb_id]
            if nb_id == to_id:
                conn.close()
                return new_path
            if nb_id not in seen:
                seen.add(nb_id)
                queue.append(new_path)
    conn.close()
    return []

# ── context_block ─────────────────────────────────────────────────────────────

def context_block(query, max_chars=1600):
    """
    Formatted graph context for prompt injection.
    Drop-in replacement for episodic memory's prompt_block().
    """
    chains = find_chains(query, max_depth=3, max_chains=5)
    if not chains:
        return "(no graph context found)"

    lines = ["[Graph reasoning context]"]
    chars = 0

    for i, chain in enumerate(chains):
        if chars >= max_chars:
            break

        coh_note = f"  coh={chain['coherence']:.2f}" if chain["coherence"] < 0.70 else ""
        edge_iter = ["seed"] + chain["edge_types"]
        steps = []
        for content, et in zip(chain["contents"], edge_iter):
            arrow = f" --[{et}]→ " if et != "seed" else ""
            steps.append(f'{arrow}"{content[:70]}{"…" if len(content)>70 else ""}"')

        line = f"  Chain {i+1} (score={chain['score']:.3f}{coh_note}): {''.join(steps)}"
        lines.append(line)
        chars += len(line)

        # Append any conflict annotations for this chain
        if chain["conflict_notes"]:
            seen_ids = set()
            for cn in chain["conflict_notes"][:3]:   # max 3 conflict notes
                if cn["id"] not in seen_ids:
                    seen_ids.add(cn["id"])
                    note = f'    ⚠ {cn["type"]}: "{cn["content"][:70]}{"…" if len(cn["content"])>70 else ""}"'
                    lines.append(note)
                    chars += len(note)

    return "\n".join(lines)

# ── Report ────────────────────────────────────────────────────────────────────

def report():
    conn = _conn()
    cur  = conn.cursor()
    n_b  = cur.execute("SELECT COUNT(*) FROM beliefs WHERE confidence>=0.35").fetchone()[0]
    n_e  = cur.execute("SELECT COUNT(*) FROM belief_edges").fetchone()[0]
    n_o  = cur.execute(
        """SELECT COUNT(*) FROM beliefs b WHERE confidence>=0.35
           AND NOT EXISTS(SELECT 1 FROM belief_edges WHERE from_id=b.id OR to_id=b.id)"""
    ).fetchone()[0]
    types = cur.execute(
        "SELECT edge_type, COUNT(*) n FROM belief_edges GROUP BY edge_type ORDER BY n DESC"
    ).fetchall()
    trav_total = sum(
        r["n"] for r in types if r["edge_type"] not in CONFLICT_EDGES
    )
    conf_total = sum(
        r["n"] for r in types if r["edge_type"] in CONFLICT_EDGES
    )
    print("══════════════════════════════════════════════════════")
    print("  NEX Graph Traversal Report")
    print("══════════════════════════════════════════════════════")
    print(f"  Beliefs (conf≥0.35) : {n_b:,}")
    print(f"  Edges (total)       : {n_e:,}")
    print(f"    Traversal edges   : {trav_total:,}")
    print(f"    Conflict edges    : {conf_total:,}")
    print(f"  Orphan beliefs      : {n_o:,}")
    print("  Edge type breakdown:")
    for r in types:
        marker = " [conflict-annotate-only]" if r["edge_type"] in CONFLICT_EDGES else ""
        print(f"    {r['edge_type']:<22} {r['n']:>7,}{marker}")
    print("══════════════════════════════════════════════════════")
    conn.close()

# ── Audit ─────────────────────────────────────────────────────────────────────

def audit(n=30):
    conn = _conn()
    cur  = conn.cursor()
    rows = cur.execute(
        "SELECT id FROM beliefs WHERE confidence>=0.35 ORDER BY RANDOM() LIMIT ?", (n,)
    ).fetchall()
    dead = sum(1 for r in rows if not _get_traversal_neighbors(cur, r["id"]))
    connected = n - dead
    print(f"[AUDIT] {n} beliefs sampled")
    print(f"  Traversal-connected : {connected}/{n} ({100*connected//n}%)")
    print(f"  Dead ends           : {dead}/{n} ({100*dead//n}%)")
    conn.close()

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report",       action="store_true")
    ap.add_argument("--query",        type=str)
    ap.add_argument("--neighborhood", type=int, metavar="ID")
    ap.add_argument("--depth",        type=int, default=2)
    ap.add_argument("--path",         type=int, nargs=2, metavar=("FROM","TO"))
    ap.add_argument("--inject",       type=str)
    ap.add_argument("--audit",        action="store_true")
    ap.add_argument("--n",            type=int, default=30)
    args = ap.parse_args()

    if args.report:  report()
    if args.audit:   audit(n=args.n)

    if args.query:
        print(f"\nChains for: '{args.query}'")
        chains = find_chains(args.query)
        if not chains:
            print("  No chains found.")
        for i, c in enumerate(chains):
            print(f"\n  Chain {i+1}  score={c['score']:.4f}  "
                  f"depth={c['depth']}  coherence={c['coherence']:.2f}")
            edge_iter = ["seed"] + c["edge_types"]
            for cid, content, et in zip(c["path"], c["contents"], edge_iter):
                arrow = f"  --[{et}]→" if et != "seed" else "  SEED    "
                print(f"    {arrow}  [{cid}] {content[:100]}")
            if c["conflict_notes"]:
                print(f"  Conflict annotations ({len(c['conflict_notes'])} total):")
                seen = set()
                for cn in c["conflict_notes"][:4]:
                    if cn["id"] not in seen:
                        seen.add(cn["id"])
                        print(f"    ⚠ [{cn['id']}] {cn['type']}: {cn['content'][:80]}")

    if args.neighborhood is not None:
        g = neighborhood(args.neighborhood, depth=args.depth)
        if g is None:
            print(f"Belief {args.neighborhood} not found.")
        else:
            print(f"\nNeighborhood of {args.neighborhood} (depth={args.depth}):")
            print(f"  Nodes: {len(g['nodes'])}  Traversal edges: {len(g['edges'])}  "
                  f"Conflict edges: {len(g['conflicts'])}")
            for nid, b in g["nodes"].items():
                print(f"    [{nid}] conf={b.get('confidence',0):.2f}  "
                      f"{str(b.get('content',''))[:80]}")
            print("  Traversal edges:")
            for e in g["edges"]:
                print(f"    {e['from']} --[{e['type']} w={e['weight']:.2f}]--> {e['to']}")
            if g["conflicts"]:
                print("  Conflict edges (not traversed):")
                for e in g["conflicts"][:5]:
                    print(f"    {e['from']} --[{e['type']}]--> {e['to']}: "
                          f"{e['content'][:60]}")

    if args.path:
        path = find_path(args.path[0], args.path[1])
        print("No path found." if not path else
              f"Path ({len(path)-1} hops): {' → '.join(map(str, path))}")

    if args.inject:
        print(context_block(args.inject))


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
