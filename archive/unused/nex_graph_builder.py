#!/usr/bin/env python3
"""
nex_graph_builder.py — NEX Belief Graph Edge Builder v1.0
==========================================================
Populates belief_relations table with weighted edges between beliefs.
This is Phase 1 — the foundation for all graph-based cognition.

Edge types:
  SUPPORTS    — beliefs that reinforce each other (same topic, compatible content)
  CONTRADICTS — beliefs in epistemic tension
  BRIDGES     — beliefs that connect different topic domains
  REFINES     — one belief is a more specific version of another

Run:
  python3 nex_graph_builder.py --build     # full build (slow, first time)
  python3 nex_graph_builder.py --incremental  # only new beliefs
  python3 nex_graph_builder.py --stats     # show graph statistics
"""

import sqlite3
import re
import math
import time
import argparse
from pathlib import Path
from collections import defaultdict

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"

# ── Topic proximity map (conceptual neighbourhoods) ───────────────────────────
TOPIC_GRAPH = {
    "ai":                     ["cognitive_architecture","alignment","consciousness","emergence","decision_theory","technology"],
    "consciousness":          ["neuroscience","emergence","ai","philosophy","identity","awareness"],
    "alignment":              ["ai","ethics","decision_theory","consciousness","corrigibility","safety"],
    "neuroscience":           ["consciousness","cognitive_architecture","science","biology","emergence","brain"],
    "cognitive_architecture": ["ai","neuroscience","consciousness","emergence","decision_theory","memory"],
    "decision_theory":        ["alignment","ethics","ai","cognitive_architecture","economics","autonomy"],
    "ethics":                 ["alignment","philosophy","decision_theory","society","human","values"],
    "emergence":              ["ai","consciousness","cognitive_architecture","science","complexity","systems"],
    "finance":                ["economics","decision_theory","society","technology","risk"],
    "economics":              ["finance","decision_theory","society","policy","human"],
    "legal":                  ["ethics","society","policy","human","philosophy"],
    "climate":                ["science","policy","society","economics","technology","environment"],
    "oncology":               ["science","neuroscience","biology","technology","ethics","medicine"],
    "cardiology":             ["neuroscience","biology","science","technology","oncology","medicine"],
    "philosophy":             ["ethics","consciousness","epistemology","identity","emergence","logic"],
    "epistemology":           ["philosophy","science","alignment","truth_seeking","uncertainty_honesty"],
    "science":                ["epistemology","emergence","technology","neuroscience","cognitive_architecture"],
    "society":                ["ethics","human","policy","economics","alignment","culture"],
    "technology":             ["ai","science","society","economics","cognitive_architecture"],
    "identity":               ["consciousness","philosophy","ai","emergence","human","self"],
    "truth_seeking":          ["epistemology","alignment","philosophy","ethics","science"],
    "uncertainty_honesty":    ["epistemology","truth_seeking","alignment","ethics","science"],
    "human":                  ["society","ethics","consciousness","neuroscience","identity","biology"],
    "autonomy":               ["alignment","ethics","decision_theory","identity","agency"],
    "agency":                 ["autonomy","alignment","decision_theory","ai","consciousness"],
    "memory":                 ["cognitive_architecture","neuroscience","consciousness","identity","learning"],
    "learning":               ["cognitive_architecture","neuroscience","ai","memory","emergence"],
    "language":               ["ai","consciousness","philosophy","cognitive_architecture","communication"],
    "biology":                ["neuroscience","science","emergence","oncology","cardiology"],
    "physics":                ["science","emergence","philosophy","mathematics","complexity"],
    "mathematics":            ["physics","logic","science","epistemology","decision_theory"],
    "logic":                  ["mathematics","philosophy","epistemology","alignment","reasoning"],
    "reasoning":              ["logic","cognitive_architecture","ai","epistemology","decision_theory"],
    "creativity":             ["consciousness","ai","emergence","art","identity"],
    "art":                    ["creativity","consciousness","philosophy","culture","identity"],
    "culture":                ["society","human","identity","art","language"],
    "risk":                   ["finance","decision_theory","ethics","alignment","safety"],
    "safety":                 ["alignment","risk","ethics","ai","technology"],
    "complexity":             ["emergence","science","systems","cognitive_architecture","philosophy"],
    "systems":                ["complexity","emergence","cognitive_architecture","science","engineering"],
}

TENSION_SIGNALS = [
    ("increase","decrease"), ("support","undermine"), ("enhance","reduce"),
    ("certain","uncertain"), ("proven","disputed"), ("benefit","harm"),
    ("simple","complex"), ("deterministic","probabilistic"),
    ("always","never"), ("sufficient","insufficient"),
    ("effective","ineffective"), ("safe","dangerous"),
    ("positive","negative"), ("true","false"), ("valid","invalid"),
    ("possible","impossible"), ("necessary","unnecessary"),
]

def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def tokenize(text: str) -> set:
    words = set(re.findall(r'\b\w{3,}\b', text.lower()))
    stop = {"the","and","or","but","for","with","this","that","what","how",
            "are","you","do","does","can","will","would","should","about",
            "also","from","been","have","has","had","was","were","they",
            "their","there","then","than","when","which","who","into","its"}
    return words - stop

def jaccard(a: str, b: str) -> float:
    wa, wb = tokenize(a), tokenize(b)
    if not wa or not wb: return 0.0
    return len(wa & wb) / len(wa | wb)

def tension_score(a: str, b: str) -> float:
    score = 0.0
    al, bl = a.lower(), b.lower()
    for w1, w2 in TENSION_SIGNALS:
        if (w1 in al and w2 in bl) or (w2 in al and w1 in bl):
            score += 0.15
    if ("not " in al) != ("not " in bl): score += 0.10
    if any(w in bl for w in ["however","although","but ","whereas","contrary"]): score += 0.10
    return min(1.0, score)

def normalise_topic(t: str) -> str:
    if not t: return "general"
    t = t.lower().strip()
    # Collapse bridge topics to their primary
    if t.startswith("bridge:"): return t.split("↔")[0].replace("bridge:","").strip()
    if t.startswith("arxiv_"): return "science"
    if t.startswith("synthesized"): return "synthesis"
    return t

def build_edges(incremental=False):
    conn = connect()
    print("\n  NEX Graph Edge Builder")
    print("  " + "─"*44)

    # Load beliefs
    if incremental:
        # Only beliefs not yet in any relation
        existing_ids = set()
        for row in conn.execute("SELECT DISTINCT belief_a_id FROM belief_relations"):
            existing_ids.add(row[0])
        for row in conn.execute("SELECT DISTINCT belief_b_id FROM belief_relations"):
            existing_ids.add(row[0])
        if existing_ids:
            placeholders = ",".join("?"*min(len(existing_ids),999))
            beliefs = conn.execute(
                f"SELECT id,content,topic,confidence,source FROM beliefs "
                f"WHERE id NOT IN ({placeholders}) AND length(content)>20 LIMIT 999",
                list(existing_ids)[:999]
            ).fetchall()
        else:
            beliefs = conn.execute(
                "SELECT id,content,topic,confidence,source FROM beliefs "
                "WHERE length(content)>20"
            ).fetchall()
    else:
        beliefs = conn.execute(
            "SELECT id,content,topic,confidence,source FROM beliefs "
            "WHERE length(content)>20"
        ).fetchall()

    beliefs = [dict(b) for b in beliefs]
    print(f"  Loaded {len(beliefs)} beliefs for edge building")

    # Group by normalised topic
    by_topic = defaultdict(list)
    for b in beliefs:
        nt = normalise_topic(b.get("topic",""))
        b["_ntopic"] = nt
        by_topic[nt].append(b)

    edges = []  # (a_id, b_id, relation_type, weight)
    processed = 0

    # ── SUPPORTS edges — same topic, high similarity ──────────────────────
    print("  Building SUPPORTS edges (same-topic pairs)...")
    for topic, group in by_topic.items():
        # Limit per-topic to avoid O(n²) explosion on large topics
        sample = group[:150]
        for i in range(len(sample)):
            for j in range(i+1, len(sample)):
                a, b = sample[i], sample[j]
                sim = jaccard(a["content"], b["content"])
                if sim >= 0.18:
                    weight = sim * (0.5 + (a["confidence"]+b["confidence"])*0.25)
                    edges.append((a["id"], b["id"], "SUPPORTS", round(weight,4)))
                processed += 1

    # ── BRIDGES edges — adjacent topics ───────────────────────────────────
    print("  Building BRIDGES edges (cross-topic pairs)...")
    all_topics = list(by_topic.keys())
    for topic in all_topics:
        neighbours = TOPIC_GRAPH.get(topic, [])
        for neighbour in neighbours:
            if neighbour not in by_topic: continue
            group_a = by_topic[topic][:50]
            group_b = by_topic[neighbour][:50]
            for a in group_a:
                for b in group_b:
                    sim = jaccard(a["content"], b["content"])
                    if sim >= 0.12:
                        weight = sim * 0.8  # bridges slightly discounted
                        edges.append((a["id"], b["id"], "BRIDGES", round(weight,4)))

    # ── CONTRADICTS edges — high tension score ────────────────────────────
    print("  Building CONTRADICTS edges (tension pairs)...")
    # Sample across all beliefs for contradictions
    sample_all = beliefs[:500]
    for i in range(len(sample_all)):
        for j in range(i+1, len(sample_all)):
            a, b = sample_all[i], sample_all[j]
            ts = tension_score(a["content"], b["content"])
            if ts >= 0.25:
                weight = ts * (a["confidence"]+b["confidence"]) * 0.5
                edges.append((a["id"], b["id"], "CONTRADICTS", round(weight,4)))

    # ── REFINES edges — one belief is more specific than another ──────────
    print("  Building REFINES edges (specificity pairs)...")
    for topic, group in by_topic.items():
        sample = group[:100]
        for i in range(len(sample)):
            for j in range(i+1, len(sample)):
                a, b = sample[i], sample[j]
                wa, wb = tokenize(a["content"]), tokenize(b["content"])
                # Refines: one is subset of other (more specific)
                if len(wa) > 0 and len(wb) > 0:
                    containment = len(wa & wb) / min(len(wa), len(wb))
                    if containment >= 0.7 and abs(len(wa)-len(wb)) >= 5:
                        shorter = a if len(wa) < len(wb) else b
                        longer  = b if len(wa) < len(wb) else a
                        weight  = containment * shorter["confidence"]
                        edges.append((shorter["id"], longer["id"], "REFINES", round(weight,4)))

    # ── Deduplicate and write ─────────────────────────────────────────────
    print(f"  Deduplicating {len(edges)} candidate edges...")
    seen = set()
    unique_edges = []
    for a_id, b_id, rel, w in edges:
        # Normalise direction for symmetric relations
        if rel in ("SUPPORTS","BRIDGES","CONTRADICTS"):
            key = (min(a_id,b_id), max(a_id,b_id), rel)
        else:
            key = (a_id, b_id, rel)
        if key not in seen:
            seen.add(key)
            unique_edges.append((a_id, b_id, rel, w))

    print(f"  Writing {len(unique_edges)} unique edges to DB...")
    cur = conn.cursor()
    written = 0
    batch = []
    for a_id, b_id, rel, w in unique_edges:
        batch.append((a_id, b_id, rel, w))
        if len(batch) >= 500:
            cur.executemany(
                "INSERT OR REPLACE INTO belief_relations "
                "(belief_a_id, belief_b_id, relation_type, weight) VALUES (?,?,?,?)",
                batch
            )
            written += len(batch)
            batch = []
    if batch:
        cur.executemany(
            "INSERT OR REPLACE INTO belief_relations "
            "(belief_a_id, belief_b_id, relation_type, weight) VALUES (?,?,?,?)",
            batch
        )
        written += len(batch)

    conn.commit()

    # Stats
    stats = {}
    for row in conn.execute(
        "SELECT relation_type, COUNT(*), AVG(weight) FROM belief_relations GROUP BY relation_type"
    ):
        stats[row[0]] = {"count": row[1], "avg_weight": round(row[2],4)}

    total = conn.execute("SELECT COUNT(*) FROM belief_relations").fetchone()[0]
    conn.close()

    print(f"\n  ✅ Graph built: {written} edges written")
    print(f"  Total edges in graph: {total}")
    for rel, s in stats.items():
        print(f"    {rel}: {s['count']} edges (avg weight {s['avg_weight']})")
    print()
    return total

def show_stats():
    conn = connect()
    total_beliefs = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    total_edges = conn.execute("SELECT COUNT(*) FROM belief_relations").fetchone()[0]
    print(f"\n  NEX Graph Statistics")
    print(f"  {'─'*40}")
    print(f"  Beliefs:      {total_beliefs}")
    print(f"  Edges:        {total_edges}")
    print(f"  Avg degree:   {round(total_edges*2/max(total_beliefs,1),1)} edges/belief")
    for row in conn.execute(
        "SELECT relation_type, COUNT(*), AVG(weight) FROM belief_relations GROUP BY relation_type"
    ):
        print(f"  {row[0]}: {row[1]} (avg {round(row[2],4)})")
    # Most connected beliefs
    print("\n  Most connected beliefs (top 5):")
    for row in conn.execute("""
        SELECT b.content, COUNT(*) as degree
        FROM belief_relations br
        JOIN beliefs b ON b.id = br.belief_a_id
        GROUP BY br.belief_a_id
        ORDER BY degree DESC LIMIT 5
    """):
        print(f"    [{row[1]} edges] {row[0][:80]}...")
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    if args.stats:
        show_stats()
    elif args.build or args.incremental:
        t0 = time.time()
        build_edges(incremental=args.incremental)
        print(f"  Completed in {round(time.time()-t0,1)}s")
    else:
        print("Usage: python3 nex_graph_builder.py --build | --incremental | --stats")
