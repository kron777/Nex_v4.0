"""
nex_graph_export.py
Export NEX belief graph as JSON for visualization.
Outputs nodes (beliefs) and edges (relations) for D3/Gephi/Cytoscape.
"""
import sqlite3, json, logging
from pathlib import Path
from collections import defaultdict

log     = logging.getLogger("nex.graph_export")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
OUT_DIR = Path.home() / "Desktop/nex/exports"

def export_graph(min_conf=0.7, max_nodes=500, topic_filter=None) -> dict:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # Get high-confidence beliefs as nodes
    q = """SELECT id, content, topic, confidence, source
           FROM beliefs WHERE confidence >= ? """
    params = [min_conf]
    if topic_filter:
        q += " AND topic=?"
        params.append(topic_filter)
    q += " ORDER BY confidence DESC LIMIT ?"
    params.append(max_nodes)

    rows = db.execute(q, params).fetchall()
    nodes = []
    node_ids = set()
    for r in rows:
        nodes.append({
            "id": r["id"],
            "label": r["content"][:80],
            "topic": r["topic"],
            "confidence": round(r["confidence"], 3),
            "source": r["source"]
        })
        node_ids.add(r["id"])

    # Get edges between those nodes
    edges = []
    try:
        edge_rows = db.execute("""
            SELECT source_id, target_id, weight, relation_type
            FROM belief_relations
            WHERE source_id IN ({}) AND target_id IN ({})
            ORDER BY weight DESC LIMIT 2000
        """.format(','.join('?'*len(node_ids)),
                   ','.join('?'*len(node_ids))),
            list(node_ids) + list(node_ids)).fetchall()

        for e in edge_rows:
            edges.append({
                "source": e["source_id"],
                "target": e["target_id"],
                "weight": round(e["weight"], 3),
                "type": e["relation_type"] if "relation_type" in e.keys() else "related"
            })
    except Exception as ex:
        log.debug(f"No belief_relations table or error: {ex}")

    # Topic distribution
    topic_counts = defaultdict(int)
    for n in nodes:
        topic_counts[n["topic"]] += 1

    db.close()

    graph = {
        "meta": {
            "nodes": len(nodes),
            "edges": len(edges),
            "min_confidence": min_conf,
            "topics": dict(sorted(topic_counts.items(), key=lambda x: -x[1])[:15])
        },
        "nodes": nodes,
        "edges": edges
    }
    return graph

def export_to_file(min_conf=0.7, max_nodes=500):
    OUT_DIR.mkdir(exist_ok=True)
    graph = export_graph(min_conf=min_conf, max_nodes=max_nodes)
    out = OUT_DIR / "belief_graph.json"
    out.write_text(json.dumps(graph, indent=2))
    print(f"Exported: {out}")
    print(f"  Nodes: {graph['meta']['nodes']}")
    print(f"  Edges: {graph['meta']['edges']}")
    print(f"  Top topics: {list(graph['meta']['topics'].items())[:5]}")
    return out

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    export_to_file()
