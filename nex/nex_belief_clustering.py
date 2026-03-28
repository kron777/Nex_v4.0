#!/usr/bin/env python3
"""
nex_belief_clustering.py — Belief Cluster Engine
=================================================
Groups beliefs by semantic similarity into clusters.
When SoulLoop retrieves beliefs, it pulls the best CLUSTER
rather than scattered individual beliefs.

The difference:
  Before: 5 loosely related beliefs
  After:  5 beliefs that together form a coherent argument

Stores clusters in: nex_belief_clusters table
Updates: every 24 hours automatically (wired into run.py)

Run once manually: python3 ~/Downloads/nex_belief_clustering.py
Then deploy: automatically wired into ABSORB cycle
"""

import sys, sqlite3, re, time, json, subprocess
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path("~/Desktop/nex").expanduser()))

DB_PATH = Path("~/.config/nex/nex.db").expanduser()
NEX     = Path("~/Desktop/nex").expanduser()

MIN_CLUSTER_SIZE  = 3
MAX_CLUSTER_SIZE  = 12
MIN_OVERLAP       = 2     # shared tokens to consider same cluster

_STOP = {
    'the','a','an','and','or','but','in','on','at','to','for','of',
    'with','as','by','from','this','that','these','those','it','its',
    'was','were','been','have','has','had','be','is','are','can','will',
    'would','could','should','may','might','must','not','no','nor',
    'so','yet','both','either','neither','each','every','all','any',
    'such','more','most','other','another','same','than','then',
}

def _tok(text):
    return set(re.sub(r'[^a-z0-9 ]', ' ',
               (text or '').lower()).split()) - _STOP


def ensure_cluster_table():
    """Create cluster table if not exists."""
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("""
        CREATE TABLE IF NOT EXISTS nex_belief_clusters (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic       TEXT,
            cluster_id  TEXT,
            belief_ids  TEXT,
            centroid    TEXT,
            coherence   REAL,
            created_at  REAL
        )
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_clusters_topic
        ON nex_belief_clusters(topic)
    """)
    con.commit()
    con.close()


def build_clusters_for_topic(topic, beliefs):
    """
    Simple token-overlap clustering.
    Groups beliefs that share 2+ meaningful tokens.
    Returns list of clusters (each cluster = list of belief dicts).
    """
    if len(beliefs) < MIN_CLUSTER_SIZE:
        return []

    # Tokenize all beliefs
    tokenized = []
    for b in beliefs:
        toks = _tok(b.get("content", ""))
        if toks:
            tokenized.append((b, toks))

    # Build adjacency using token overlap
    n       = len(tokenized)
    adj     = defaultdict(set)
    for i in range(n):
        for j in range(i+1, n):
            ov = len(tokenized[i][1] & tokenized[j][1])
            if ov >= MIN_OVERLAP:
                adj[i].add(j)
                adj[j].add(i)

    # Connected components = clusters
    visited  = set()
    clusters = []
    for start in range(n):
        if start in visited:
            continue
        # BFS
        cluster = []
        queue   = [start]
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            cluster.append(node)
            queue.extend(adj[node] - visited)
        if len(cluster) >= MIN_CLUSTER_SIZE:
            # Sort cluster members by confidence descending
            cluster_beliefs = sorted(
                [tokenized[i][0] for i in cluster],
                key=lambda x: x.get("confidence", 0),
                reverse=True
            )[:MAX_CLUSTER_SIZE]
            clusters.append(cluster_beliefs)

    return clusters


def build_centroid(beliefs):
    """Find the most representative belief in a cluster."""
    if not beliefs:
        return ""
    # Most connected = highest avg overlap with others
    tokenized = [(b, _tok(b.get("content",""))) for b in beliefs]
    best_b, best_score = beliefs[0], 0
    for b, toks in tokenized:
        score = sum(len(toks & t2) for _, t2 in tokenized)
        if score > best_score:
            best_score = score
            best_b     = b
    return best_b.get("content", "")


def compute_coherence(beliefs):
    """Avg pairwise token overlap — how tightly clustered."""
    if len(beliefs) < 2:
        return 0.0
    tokenized = [_tok(b.get("content","")) for b in beliefs]
    total, count = 0, 0
    for i in range(len(tokenized)):
        for j in range(i+1, len(tokenized)):
            total += len(tokenized[i] & tokenized[j])
            count += 1
    return round(total / count, 2) if count > 0 else 0.0


def run_clustering(verbose=True):
    """Build all clusters from current belief corpus."""
    if verbose:
        print("=== NEX BELIEF CLUSTERING ===\n")

    ensure_cluster_table()
    con = sqlite3.connect(DB_PATH, timeout=10)

    # Load all beliefs grouped by topic
    rows = con.execute(
        "SELECT id, content, confidence, topic FROM beliefs "
        "WHERE content IS NOT NULL AND length(content) > 20 "
        "AND topic IS NOT NULL AND topic != ''"
    ).fetchall()
    con.close()

    if verbose:
        print(f"  Loaded {len(rows)} beliefs")

    by_topic = defaultdict(list)
    for bid, content, conf, topic in rows:
        by_topic[topic].append({
            "id":         bid,
            "content":    content,
            "confidence": float(conf or 0.5),
            "topic":      topic,
        })

    if verbose:
        print(f"  Topics: {len(by_topic)}\n")

    # Clear old clusters
    con2 = sqlite3.connect(DB_PATH, timeout=10)
    con2.execute("DELETE FROM nex_belief_clusters")
    con2.commit()

    total_clusters = 0
    now = time.time()

    for topic, beliefs in sorted(by_topic.items()):
        clusters = build_clusters_for_topic(topic, beliefs)
        if not clusters:
            continue

        for i, cluster in enumerate(clusters):
            centroid  = build_centroid(cluster)
            coherence = compute_coherence(cluster)
            belief_ids = json.dumps([b["id"] for b in cluster])
            cluster_id = f"{topic}_{i}"

            con2.execute(
                "INSERT INTO nex_belief_clusters "
                "(topic, cluster_id, belief_ids, centroid, coherence, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (topic, cluster_id, belief_ids, centroid,
                 coherence, now)
            )
            total_clusters += 1

        if verbose and len(beliefs) >= 10:
            print(f"  {topic:<40} {len(beliefs):>5} beliefs → "
                  f"{len(clusters)} clusters")

    con2.commit()
    con2.close()

    if verbose:
        print(f"\n  Total clusters: {total_clusters}")
        print(f"\n  Top clusters by coherence:")
        con3 = sqlite3.connect(DB_PATH, timeout=10)
        for r in con3.execute(
            "SELECT topic, cluster_id, coherence, centroid "
            "FROM nex_belief_clusters "
            "ORDER BY coherence DESC LIMIT 5"
        ).fetchall():
            print(f"    [{r[2]:.1f}] {r[0]} — {r[3][:80]}")
        con3.close()

    return total_clusters


def wire_into_run():
    """Wire cluster rebuild into run.py ABSORB cycle."""
    run_path = NEX / "run.py"
    src      = run_path.read_text(encoding='utf-8')

    if 'nex_belief_clustering' in src:
        print("  Already wired into run.py")
        return

    import shutil
    shutil.copy2(run_path, str(run_path) + '.bak_cluster')

    WIRE_CODE = """
                            # ── Belief clustering (every 50 cycles) ─────────
                            if cycle % 50 == 0:
                                try:
                                    from nex.nex_belief_clustering import run_clustering
                                    _nc = run_clustering(verbose=False)
                                    if _nc > 0:
                                        print(f'  [Clustering] {_nc} clusters rebuilt')
                                except Exception: pass
"""

    INSERT_AFTER = ('                            except Exception as _ge: pass\n'
                    '                            # ── Auto-seeder: self-expand belief corpus')

    if INSERT_AFTER in src:
        src = src.replace(INSERT_AFTER, WIRE_CODE + INSERT_AFTER, 1)
        run_path.write_text(src, encoding='utf-8')
        r = subprocess.run(
            [sys.executable, '-m', 'py_compile', str(run_path)],
            capture_output=True
        )
        if r.returncode == 0:
            print("  ✓ Wired into run.py ABSORB (every 50 cycles)")
        else:
            print(f"  ✗ syntax error — restoring backup")
            shutil.copy2(str(run_path) + '.bak_cluster', run_path)
    else:
        print("  Insert marker not found — manual wiring needed")


if __name__ == "__main__":
    import subprocess, shutil

    # 1. Deploy to nex/
    src_path = Path("~/Downloads/nex_belief_clustering.py").expanduser()
    dst_path = NEX / "nex/nex_belief_clustering.py"
    shutil.copy2(src_path, dst_path)
    r = subprocess.run(
        [sys.executable, '-m', 'py_compile', str(dst_path)],
        capture_output=True
    )
    print("  ✓ deployed" if r.returncode == 0 else f"  ✗ {r.stderr.decode()[:200]}")

    # 2. Run clustering
    n = run_clustering(verbose=True)

    # 3. Wire into run.py
    print("\n  Wiring into run.py...")
    wire_into_run()

    # 4. Commit
    subprocess.run(['git', 'add', '-A'], cwd=str(NEX))
    subprocess.run(
        ['git', 'commit', '-m',
         'feat: nex_belief_clustering — semantic cluster engine wired into ABSORB'],
        cwd=str(NEX)
    )
    subprocess.run(['git', 'push'], cwd=str(NEX))

    print(f"\nDone. {n} clusters built.")
    print("Run: nex")
