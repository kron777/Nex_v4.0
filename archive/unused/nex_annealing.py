#!/usr/bin/env python3
"""
nex_annealing.py — NEX Belief Field Annealing Engine v1.0
==========================================================
Continuously improves belief graph coherence through simulated annealing.
Runs overnight. No GPU needed — pure graph math on CPU.

Annealing cycle:
  1. Heat       — activate random belief clusters, surface tensions
  2. Propagate  — tensions spread through edges
  3. Cool       — surviving beliefs gain confidence, contradicted ones decay
  4. Crystallise — coherent clusters synthesise new core beliefs

Each cycle makes the graph slightly more coherent.
All subsystems that depend on the graph improve simultaneously.

Run:
  python3 nex_annealing.py --cycles 10     # run 10 annealing cycles
  python3 nex_annealing.py --overnight     # run until 06:00
  python3 nex_annealing.py --single        # run one cycle, show results
"""

import sqlite3
import re
import math
import time
import random
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"

# Annealing parameters
INITIAL_TEMPERATURE  = 1.0    # starting heat
COOLING_RATE         = 0.92   # temperature * this per cycle
MIN_TEMPERATURE      = 0.05   # stop when cooled to this
CLUSTER_SIZE         = 20     # beliefs per annealing cluster
CONFIDENCE_BOOST     = 0.015  # boost for beliefs that survive tension
CONFIDENCE_DECAY     = 0.012  # decay for beliefs that lose tension
CRYSTALLISE_THRESHOLD = 0.65  # avg confidence to trigger crystallisation
MAX_CRYSTAL_LENGTH   = 200    # max chars for crystallised belief


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def tokenize(text: str) -> set:
    stop = {"the","and","or","but","for","with","this","that","what","how",
            "are","you","do","does","can","will","would","should","about"}
    words = set(re.findall(r'\b\w{3,}\b', text.lower()))
    return words - stop


def tension_score(a: str, b: str) -> float:
    TENSION_SIGNALS = [
        ("increase","decrease"), ("support","undermine"), ("enhance","reduce"),
        ("certain","uncertain"), ("proven","disputed"), ("benefit","harm"),
        ("always","never"), ("effective","ineffective"), ("safe","dangerous"),
        ("positive","negative"), ("true","false"),
    ]
    score = 0.0
    al, bl = a.lower(), b.lower()
    for w1, w2 in TENSION_SIGNALS:
        if (w1 in al and w2 in bl) or (w2 in al and w1 in bl):
            score += 0.2
    if ("not " in al) != ("not " in bl): score += 0.1
    return min(1.0, score)


def jaccard(a: str, b: str) -> float:
    wa, wb = tokenize(a), tokenize(b)
    if not wa or not wb: return 0.0
    return len(wa & wb) / len(wa | wb)


def anneal_cycle(conn, temperature: float, cycle_num: int) -> dict:
    """Run one annealing cycle. Returns stats dict."""
    stats = {
        "cycle": cycle_num,
        "temperature": round(temperature, 3),
        "boosted": 0,
        "decayed": 0,
        "crystallised": 0,
        "clusters": 0,
    }

    # Load a random sample of beliefs weighted by topic diversity
    topics = [r[0] for r in conn.execute(
        "SELECT topic, COUNT(*) as n FROM beliefs WHERE topic IS NOT NULL "
        "GROUP BY topic HAVING n >= 3 ORDER BY RANDOM() LIMIT 50"
    ).fetchall()]
    topics = [t[0] for t in topics] if topics and isinstance(topics[0], tuple) else topics

    if not topics:
        return stats

    # Pick random topic clusters to anneal
    n_clusters = max(3, int(temperature * 8))
    selected_topics = random.sample(topics, min(n_clusters, len(topics)))

    for topic in selected_topics:
        # Load beliefs for this topic
        beliefs = conn.execute(
            "SELECT id, content, confidence, topic FROM beliefs "
            "WHERE topic = ? AND length(content) > 20 "
            "ORDER BY RANDOM() LIMIT ?",
            (topic, CLUSTER_SIZE)
        ).fetchall()
        beliefs = [dict(b) for b in beliefs]

        if len(beliefs) < 2:
            continue

        stats["clusters"] += 1

        # Find tensions within cluster
        tensions = []
        supports = []
        for i in range(len(beliefs)):
            for j in range(i+1, len(beliefs)):
                a, b = beliefs[i], beliefs[j]
                ts = tension_score(a["content"], b["content"])
                sim = jaccard(a["content"], b["content"])
                if ts >= 0.2:
                    tensions.append((a, b, ts))
                elif sim >= 0.15:
                    supports.append((a, b, sim))

        # Heat phase — high temperature = more random updates
        noise = random.random() * temperature * 0.1

        # Cool phase — resolve tensions
        tension_losers = set()
        for a, b, ts in tensions:
            # Higher confidence belief "wins" the tension
            winner = a if a["confidence"] >= b["confidence"] else b
            loser  = b if winner["id"] == a["id"] else a
            tension_losers.add(loser["id"])

            # Boost winner
            new_conf = min(0.99, winner["confidence"] + CONFIDENCE_BOOST * ts + noise)
            conn.execute("UPDATE beliefs SET confidence=? WHERE id=?",
                        (round(new_conf,4), winner["id"]))
            stats["boosted"] += 1

            # Decay loser (proportional to temperature — hot = more decay)
            decay = CONFIDENCE_DECAY * ts * temperature
            new_conf = max(0.10, loser["confidence"] - decay)
            conn.execute("UPDATE beliefs SET confidence=? WHERE id=?",
                        (round(new_conf,4), loser["id"]))
            stats["decayed"] += 1

        # Boost supported beliefs (mutual reinforcement)
        for a, b, sim in supports:
            for belief in (a, b):
                boost = CONFIDENCE_BOOST * sim * 0.5
                new_conf = min(0.99, belief["confidence"] + boost + noise)
                conn.execute("UPDATE beliefs SET confidence=? WHERE id=?",
                            (round(new_conf,4), belief["id"]))
            stats["boosted"] += 2

        # Crystallisation — if cluster is highly coherent, synthesise
        avg_conf = sum(b["confidence"] for b in beliefs) / len(beliefs)
        if (avg_conf >= CRYSTALLISE_THRESHOLD and
                len(supports) >= 3 and
                len(tensions) == 0 and
                random.random() < 0.15):  # 15% chance to crystallise

            # Build crystal from common words in top beliefs
            top = sorted(beliefs, key=lambda x: x["confidence"], reverse=True)[:3]
            common_words = tokenize(top[0]["content"])
            for b in top[1:]:
                common_words &= tokenize(b["content"])

            if len(common_words) >= 4:
                # Find the belief that best represents the cluster
                best = top[0]
                crystal_content = best["content"][:MAX_CRYSTAL_LENGTH]

                # Check not duplicate
                exists = conn.execute(
                    "SELECT COUNT(*) FROM beliefs WHERE content = ?",
                    (crystal_content,)
                ).fetchone()[0]

                if not exists:
                    conn.execute(
                        "INSERT OR IGNORE INTO beliefs (topic, content, confidence, source, origin) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (topic, crystal_content, 0.82,
                         "annealing_crystal", "annealing")
                    )
                    stats["crystallised"] += 1

    conn.commit()
    # Run contradiction detection after each anneal cycle
    try:
        import sys as _sys
        _sys.path.insert(0, "/home/rr/Desktop/nex")
        from nex_contradiction_detector import run as _detect
        r = _detect(dry_run=False)
        stats["contradictions_resolved"] = len(r) if isinstance(r, list) else 0
    except Exception:
        pass
    return stats


def run_annealing(n_cycles: int = 10, overnight: bool = False):
    conn = connect()
    temperature = INITIAL_TEMPERATURE
    cycle = 0
    total_stats = {"boosted": 0, "decayed": 0, "crystallised": 0, "clusters": 0}

    print(f"\n  NEX Belief Field Annealing")
    print(f"  {'─'*44}")
    print(f"  Mode: {'overnight' if overnight else f'{n_cycles} cycles'}")
    print(f"  Initial temperature: {temperature}")
    print()

    start_time = time.time()

    while True:
        if overnight:
            hour = datetime.now().hour
            if False:  # window check disabled for manual runs — scheduler handles timing
                print(f"\n  Overnight window ended at {datetime.now().strftime('%H:%M')}")
                break
        else:
            if cycle >= n_cycles:
                break

        if temperature < MIN_TEMPERATURE:
            print(f"  Fully cooled at cycle {cycle}")
            break

        cycle += 1
        stats = anneal_cycle(conn, temperature, cycle)
        temperature *= COOLING_RATE

        for k in ("boosted","decayed","crystallised","clusters"):
            total_stats[k] += stats[k]

        if cycle % 5 == 0 or not overnight:
            elapsed = round(time.time() - start_time, 1)
            print(f"  Cycle {cycle:3d} | T={stats['temperature']:.3f} | "
                  f"clusters={stats['clusters']} | "
                  f"+{stats['boosted']} boosted | "
                  f"-{stats['decayed']} decayed | "
                  f"✦{stats['crystallised']} crystals | "
                  f"{elapsed}s")

        time.sleep(0.1)  # prevent DB hammering

    conn.close()
    elapsed = round(time.time() - start_time, 1)
    print(f"\n  ✅ Annealing complete: {cycle} cycles in {elapsed}s")
    print(f"  Total: +{total_stats['boosted']} boosted | "
          f"-{total_stats['decayed']} decayed | "
          f"✦{total_stats['crystallised']} crystals")
    print()
    return total_stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--overnight", action="store_true")
    parser.add_argument("--single", action="store_true")
    args = parser.parse_args()

    if args.single:
        run_annealing(n_cycles=1)
    elif args.overnight:
        run_annealing(overnight=True)
    else:
        run_annealing(n_cycles=args.cycles)
