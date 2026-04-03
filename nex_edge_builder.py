#!/usr/bin/env python3
"""
nex_edge_builder.py — Populate belief_edges from existing beliefs.

Mines the 20k+ beliefs using:
  1. Embedding cosine similarity   → 'similar' / 'related' edges
  2. Keyword contradiction patterns → 'contradicts' edges
  3. belief_relations table data   → imported as edges
  4. belief_links table data       → imported as edges

Run modes:
  python3 nex_edge_builder.py --dry-run          # show stats, write nothing
  python3 nex_edge_builder.py --build            # full build (slow, thorough)
  python3 nex_edge_builder.py --build --batch 500 # process N beliefs per run
  python3 nex_edge_builder.py --import-existing  # just pull belief_relations + belief_links
  python3 nex_edge_builder.py --status           # show current edge counts
"""

import argparse
import sqlite3
import time
import struct
import numpy as np
from pathlib import Path

DB_PATH = Path(__file__).parent / "nex.db"

# ── Thresholds ────────────────────────────────────────────────────────────────
SIM_CAUSAL       = 0.82   # very close → 'causal'
SIM_SIMILAR      = 0.70   # close      → 'similar'
SIM_RELATED      = 0.55   # moderate   → 'related'
SIM_MIN          = 0.55   # below this → skip
MAX_EDGES_PER_NODE = 12   # cap fan-out per belief

CONTRADICTION_PAIRS = [
    (["not ", "no ", "never ", "cannot ", "doesn't ", "isn't ", "aren't ", "without "],
     []),   # negation present vs absent — handled in code
]

NEGATION_WORDS = {"not", "no", "never", "cannot", "doesn't", "isn't",
                  "aren't", "without", "impossible", "false", "wrong",
                  "disagree", "reject", "deny", "untrue"}

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def decode_embedding(blob):
    if blob is None:
        return None
    try:
        arr = np.frombuffer(blob, dtype=np.float32)
        if arr.size == 0:
            return None
        norm = np.linalg.norm(arr)
        return arr / norm if norm > 0 else arr
    except Exception:
        return None


def cosine(a, b):
    return float(np.dot(a, b))   # already unit-normalised


# ── Edge detection ────────────────────────────────────────────────────────────

def infer_edge_type(sim, content_a, content_b):
    """Return (edge_type, weight) for a pair."""
    words_a = set(content_a.lower().split())
    words_b = set(content_b.lower().split())

    neg_a = bool(words_a & NEGATION_WORDS)
    neg_b = bool(words_b & NEGATION_WORDS)

    # High similarity but one negates → contradiction
    if sim >= SIM_SIMILAR and (neg_a ^ neg_b):
        return "contradicts", round(sim * 0.9, 4)

    if sim >= SIM_CAUSAL:
        return "causal", round(sim, 4)
    if sim >= SIM_SIMILAR:
        return "similar", round(sim, 4)
    return "related", round(sim, 4)


# ── Import existing relations ─────────────────────────────────────────────────

def import_existing(conn):
    cur = conn.cursor()
    inserted = 0
    skipped  = 0

    # belief_relations (source_id, target_id, weight, relation_type)
    rows = cur.execute(
        "SELECT source_id, target_id, weight, relation_type FROM belief_relations"
    ).fetchall()
    for r in rows:
        try:
            cur.execute(
                """INSERT OR IGNORE INTO belief_edges (from_id, to_id, edge_type, weight, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (r["source_id"], r["target_id"],
                 r["relation_type"] or "similar",
                 r["weight"] or 0.5,
                 time.time())
            )
            inserted += cur.rowcount
        except Exception:
            skipped += 1

    # belief_links (parent_id, child_id, link_type)
    rows = cur.execute(
        "SELECT parent_id, child_id, link_type FROM belief_links"
    ).fetchall()
    for r in rows:
        try:
            cur.execute(
                """INSERT OR IGNORE INTO belief_edges (from_id, to_id, edge_type, weight, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (r["parent_id"], r["child_id"],
                 r["link_type"] or "related",
                 0.6,
                 time.time())
            )
            inserted += cur.rowcount
        except Exception:
            skipped += 1

    conn.commit()
    print(f"[import-existing] inserted={inserted}  skipped/duplicate={skipped}")
    return inserted


# ── Main embedding-based build ────────────────────────────────────────────────

def build_edges(batch_size=500, dry_run=False, offset=0):
    conn = get_conn()
    cur  = conn.cursor()

    # Load beliefs with embeddings
    print("Loading beliefs with embeddings…")
    rows = cur.execute(
        """SELECT id, content, confidence, embedding
           FROM beliefs
           WHERE embedding IS NOT NULL AND confidence >= 0.35
           LIMIT ? OFFSET ?""",
        (batch_size, offset)
    ).fetchall()

    if not rows:
        print("No beliefs found in this batch (offset={offset}).")
        return 0

    ids       = []
    contents  = []
    confs     = []
    embs      = []

    for r in rows:
        emb = decode_embedding(r["embedding"])
        if emb is None:
            continue
        ids.append(r["id"])
        contents.append(r["content"] or "")
        confs.append(r["confidence"])
        embs.append(emb)

    n = len(ids)
    print(f"Loaded {n} beliefs with valid embeddings (offset={offset})")

    if n == 0:
        print("No valid embeddings found. Beliefs may not have been embedded yet.")
        print("Run the embedder first, then re-run this script.")
        return 0

    # Build matrix
    E = np.stack(embs, axis=0)   # (n, dim)
    S = E @ E.T                  # cosine similarity matrix

    edges = []   # (from_id, to_id, edge_type, weight)

    for i in range(n):
        sims = S[i].copy()
        sims[i] = 0.0   # no self-loops

        # Get top-k by similarity above threshold
        candidates = np.where(sims >= SIM_MIN)[0]
        if len(candidates) == 0:
            continue

        # Sort descending, cap fan-out
        candidates = candidates[np.argsort(-sims[candidates])][:MAX_EDGES_PER_NODE]

        for j in candidates:
            sim = float(sims[j])
            etype, weight = infer_edge_type(sim, contents[i], contents[j])
            edges.append((ids[i], ids[j], etype, weight))

    print(f"Generated {len(edges)} candidate edges")

    if dry_run:
        # Show sample
        type_counts = {}
        for e in edges:
            type_counts[e[2]] = type_counts.get(e[2], 0) + 1
        print("\n[DRY RUN — nothing written]")
        print("Edge type breakdown:")
        for k, v in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  {k:<15} {v}")
        return len(edges)

    # Write to DB
    now = time.time()
    inserted = 0
    for from_id, to_id, etype, weight in edges:
        try:
            cur.execute(
                """INSERT OR IGNORE INTO belief_edges (from_id, to_id, edge_type, weight, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (from_id, to_id, etype, weight, now)
            )
            inserted += cur.rowcount
        except Exception:
            pass

    conn.commit()
    conn.close()
    print(f"Inserted {inserted} new edges into belief_edges")
    return inserted


# ── Status report ─────────────────────────────────────────────────────────────

def status():
    conn = get_conn()
    cur  = conn.cursor()

    total_beliefs = cur.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    with_emb      = cur.execute(
        "SELECT COUNT(*) FROM beliefs WHERE embedding IS NOT NULL"
    ).fetchone()[0]
    total_edges   = cur.execute("SELECT COUNT(*) FROM belief_edges").fetchone()[0]
    orphans       = cur.execute(
        """SELECT COUNT(*) FROM beliefs b
           WHERE NOT EXISTS (SELECT 1 FROM belief_edges WHERE from_id=b.id OR to_id=b.id)
           AND confidence >= 0.35"""
    ).fetchone()[0]

    type_rows = cur.execute(
        "SELECT edge_type, COUNT(*) as n FROM belief_edges GROUP BY edge_type ORDER BY n DESC"
    ).fetchall()

    br_count = cur.execute("SELECT COUNT(*) FROM belief_relations").fetchone()[0]
    bl_count = cur.execute("SELECT COUNT(*) FROM belief_links").fetchone()[0]

    print("══════════════════════════════════════════════════")
    print("  NEX Edge Builder Status")
    print("══════════════════════════════════════════════════")
    print(f"  Total beliefs        : {total_beliefs:,}")
    print(f"  Beliefs w/ embedding : {with_emb:,}")
    print(f"  belief_edges rows    : {total_edges:,}")
    print(f"  belief_relations rows: {br_count:,}")
    print(f"  belief_links rows    : {bl_count:,}")
    print(f"  Orphan beliefs (≥0.35 conf): {orphans:,}")
    if type_rows:
        print("\n  Edge types:")
        for r in type_rows:
            print(f"    {r['edge_type']:<15} {r['n']:,}")
    print("══════════════════════════════════════════════════")

    conn.close()


# ── Patch traversal module ────────────────────────────────────────────────────

TRAVERSAL_PATH = Path(__file__).parent / "nex_graph_traversal.py"

CORRECT_QUERY = """    cur.execute(\"\"\"
        SELECT be.to_id   AS target_id,
               be.edge_type,
               be.weight,
               b.content,
               b.confidence
        FROM   belief_edges be
        JOIN   beliefs b ON b.id = be.to_id
        WHERE  be.from_id = ?
        ORDER BY be.weight DESC
    \"\"\", (node_id,))"""

OLD_PATTERNS = [
    # Pattern the original module likely used (edges table)
    'FROM   edges',
    'FROM edges',
    # Wrong column names
    'source_id',
    'target_id',
]


def patch_traversal():
    """
    Check if nex_graph_traversal.py uses wrong table/column names and report.
    We can't auto-patch without seeing the file, but we print what to fix.
    """
    if not TRAVERSAL_PATH.exists():
        print("nex_graph_traversal.py not found — skipping patch check.")
        return

    src = TRAVERSAL_PATH.read_text()
    issues = []

    if "belief_edges" not in src:
        issues.append("• Does not reference 'belief_edges' table")
    if "from_id" not in src:
        issues.append("• Does not use 'from_id' column (belief_edges uses from_id/to_id)")
    if "to_id" not in src:
        issues.append("• Does not use 'to_id' column")

    if issues:
        print("\n[PATCH NEEDED] nex_graph_traversal.py has schema mismatches:")
        for i in issues:
            print(i)
        print("\nThe correct edge query for belief_edges is:")
        print(CORRECT_QUERY)
        print("\nRun: python3 nex_edge_builder.py --patch")
    else:
        print("[OK] nex_graph_traversal.py already references correct schema.")


def do_patch():
    """Rewrite the edge-fetch SQL in nex_graph_traversal.py to use belief_edges."""
    if not TRAVERSAL_PATH.exists():
        print("nex_graph_traversal.py not found.")
        return

    src = TRAVERSAL_PATH.read_text()
    original = src

    # Replace any SELECT from wrong tables with correct one
    import re

    # Pattern: any SQL fetching edges — replace the whole FROM clause area
    # We'll do a targeted replacement of the edge-fetch query block
    bad_patterns = [
        # Old 'edges' table
        (r"FROM\s+edges\b", "FROM   belief_edges be"),
        # Wrong column: source_id → from_id
        (r"\bsource_id\b", "from_id"),
        # Wrong join alias
        (r"FROM\s+belief_edges\s+WHERE\s+source_id", 
         "FROM   belief_edges be\n        JOIN   beliefs b ON b.id = be.to_id\n        WHERE  be.from_id"),
    ]

    for pattern, replacement in bad_patterns:
        src = re.sub(pattern, replacement, src)

    if src == original:
        print("[patch] No changes needed — schema already correct OR pattern not found.")
        print("        Run --status to verify edges are populating correctly.")
        return

    backup = TRAVERSAL_PATH.with_suffix(".py.bak")
    backup.write_text(original)
    TRAVERSAL_PATH.write_text(src)
    print(f"[patch] Patched {TRAVERSAL_PATH.name}  (backup → {backup.name})")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="NEX Edge Builder")
    ap.add_argument("--status",          action="store_true", help="Show edge/belief counts")
    ap.add_argument("--dry-run",         action="store_true", help="Analyse without writing")
    ap.add_argument("--build",           action="store_true", help="Build edges from embeddings")
    ap.add_argument("--import-existing", action="store_true", help="Import belief_relations + belief_links")
    ap.add_argument("--patch",           action="store_true", help="Patch nex_graph_traversal.py schema")
    ap.add_argument("--check-patch",     action="store_true", help="Check if traversal needs patching")
    ap.add_argument("--batch",  type=int, default=500,  help="Beliefs per batch (default 500)")
    ap.add_argument("--offset", type=int, default=0,    help="Offset into beliefs table")
    ap.add_argument("--all",             action="store_true",
                    help="Build edges for ALL beliefs (slow — runs batches until done)")
    args = ap.parse_args()

    if args.status or not any([args.dry_run, args.build, args.import_existing,
                                args.patch, args.check_patch]):
        status()

    if args.import_existing:
        conn = get_conn()
        import_existing(conn)
        conn.close()
        status()

    if args.dry_run:
        build_edges(batch_size=args.batch, dry_run=True, offset=args.offset)

    if args.build:
        if args.all:
            offset = args.offset
            total  = 0
            while True:
                n = build_edges(batch_size=args.batch, dry_run=False, offset=offset)
                if n == 0:
                    break
                total  += n
                offset += args.batch
                print(f"  → cumulative edges inserted: {total:,}  next offset: {offset}")
            print(f"\nDone. Total edges inserted: {total:,}")
        else:
            build_edges(batch_size=args.batch, dry_run=False, offset=args.offset)
        status()

    if args.check_patch:
        patch_traversal()

    if args.patch:
        do_patch()


if __name__ == "__main__":
    main()
