#!/usr/bin/env python3
"""
nex_metabolism.py — Autocatalytic Belief Metabolism
════════════════════════════════════════════════════

The primordial soup. This module runs continuously in the background,
independent of queries, the soul loop, or the nightly pipeline.

It does ONE thing: find and sustain autocatalytic cycles in the belief graph.

An autocatalytic cycle: A enables B, B enables C, C enables A.
The cycle sustains itself. No external input needed.

Every few seconds:
  1. Pick a random high-confidence belief
  2. Follow enables/causes edges to find what it activates
  3. Follow those edges to find what THEY activate
  4. If a cycle is found (return to start), strengthen those edges
  5. If two cycles share a belief, that belief becomes a CATALYST
  6. If tension is too low, inject perturbation (far-from-equilibrium)

No LLM calls. No API. Pure graph traversal.
Over time, coherent self-sustaining structures emerge.

Usage:
    python3 nex_metabolism.py              # run as foreground process
    python3 nex_metabolism.py --daemon      # run as background thread
    python3 nex_metabolism.py --status      # show metabolic state
    python3 nex_metabolism.py --cycles      # show discovered cycles
    python3 nex_metabolism.py --catalysts   # show catalyst beliefs
    python3 nex_metabolism.py --once        # run one metabolic tick
"""

import nex_db_gatekeeper  # write-serialization + PRAGMA busy_timeout/WAL on every sqlite3.connect
import sqlite3, json, time, os, re, random, argparse, shutil, threading
from collections import defaultdict, Counter
from pathlib import Path

DB_PATH = "/media/rr/NEX/nex_core/nex.db"

# ─── Terminal ────────────────────────────────────────────────────
class C:
    RST="\033[0m"; BOLD="\033[1m"; DIM="\033[2m"
    CYAN="\033[96m"; PINK="\033[95m"; GREEN="\033[92m"
    YELLOW="\033[93m"; RED="\033[91m"; WHITE="\033[97m"; GREY="\033[90m"

def tw(): return min(shutil.get_terminal_size((80,24)).columns, 76)

# ─── Schema ──────────────────────────────────────────────────────

def ensure_schema():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS autocatalytic_cycles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_beliefs   TEXT,
            cycle_length    INTEGER,
            strength        REAL,
            times_fired     INTEGER DEFAULT 0,
            catalyst_id     INTEGER,
            discovered_at   REAL,
            last_fired      REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metabolic_state (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tick            INTEGER,
            cycles_found    INTEGER,
            cycles_fired    INTEGER,
            catalysts_count INTEGER,
            perturbations   INTEGER,
            avg_tension     REAL,
            timestamp       REAL
        )
    """)
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════
#  GRAPH TRAVERSAL — find cycles
# ═══════════════════════════════════════════════════════════════════

def load_forward_edges():
    """Load all enabling/causal edges as adjacency list."""
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    edges = defaultdict(list)

    # From belief_relations: enables, causes, supports, refines
    try:
        rows = conn.execute("""
            SELECT source_id, target_id, weight, relation_type
            FROM belief_relations
            WHERE relation_type IN ('enables','causes','supports','refines','synthesises','subsumes',
                                    'SUPPORTS','BRIDGES','REFINES')
              AND weight > 0
        """).fetchall()
        for src, tgt, weight, rtype in rows:
            edges[src].append((tgt, weight or 0.5, rtype))
    except Exception:
        pass

    # From belief_links: cross_domain, causal, dream_bridge
    try:
        rows = conn.execute("""
            SELECT parent_id, child_id, link_type
            FROM belief_links
            WHERE link_type IN ('causal','cross_domain','dream_bridge','enables','self_describes')
        """).fetchall()
        for src, tgt, ltype in rows:
            edges[src].append((tgt, 0.5, ltype))
    except Exception:
        pass

    conn.close()
    return edges


def find_cycle(start_id, edges, max_depth=6):
    """
    DFS from start_id following forward edges.
    If we return to start_id, we found a cycle.
    Returns the cycle as a list of belief IDs, or None.
    """
    visited = set()
    stack = [(start_id, [start_id])]

    while stack:
        current, path = stack.pop()

        if len(path) > max_depth:
            continue

        for neighbor, weight, etype in edges.get(current, []):
            if neighbor == start_id and len(path) > 2:
                # Found a cycle!
                return path

            if neighbor not in visited and neighbor not in path:
                stack.append((neighbor, path + [neighbor]))

        visited.add(current)

    return None


# ═══════════════════════════════════════════════════════════════════
#  METABOLIC TICK — one heartbeat
# ═══════════════════════════════════════════════════════════════════

def metabolic_tick(tick_num=0):
    """
    One metabolic heartbeat. The cell breathes.

    1. Pick a random high-confidence belief
    2. Try to find a cycle starting from it
    3. If found: strengthen edges, record cycle
    4. Fire existing strong cycles
    5. Identify catalysts (beliefs in multiple cycles)
    6. Check equilibrium — perturb if too stable
    """
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    edges = load_forward_edges()

    cycles_found = 0
    cycles_fired = 0
    perturbations = 0

    # ── 1. Sample a random seed belief ───────────────────────────
    seeds = conn.execute("""
        SELECT id FROM beliefs
        WHERE confidence > 0.4 AND locked = 0
        ORDER BY RANDOM() LIMIT 5
    """).fetchall()

    for (seed_id,) in seeds:
        # ── 2. Try to find a cycle ───────────────────────────────
        cycle = find_cycle(seed_id, edges, max_depth=5)

        if cycle and len(cycle) >= 3:
            cycle_key = json.dumps(sorted(cycle))

            # Check if this cycle is already known
            existing = conn.execute(
                "SELECT id, strength, times_fired FROM autocatalytic_cycles "
                "WHERE cycle_beliefs=?", (cycle_key,)
            ).fetchone()

            if existing:
                # Strengthen existing cycle
                cid, strength, times = existing
                new_strength = min(1.0, strength + 0.01)
                conn.execute(
                    "UPDATE autocatalytic_cycles "
                    "SET strength=?, times_fired=?, last_fired=? WHERE id=?",
                    (new_strength, times + 1, time.time(), cid))
                cycles_fired += 1
            else:
                # New cycle discovered!
                conn.execute("""
                    INSERT INTO autocatalytic_cycles
                    (cycle_beliefs, cycle_length, strength, times_fired,
                     discovered_at, last_fired)
                    VALUES (?,?,?,?,?,?)
                """, (cycle_key, len(cycle), 0.1, 1, time.time(), time.time()))
                cycles_found += 1

            # ── 3. Strengthen the edges in this cycle ────────────
            for i in range(len(cycle)):
                src = cycle[i]
                tgt = cycle[(i + 1) % len(cycle)]
                try:
                    conn.execute("""
                        UPDATE belief_relations
                        SET weight = MIN(1.0, weight + 0.005)
                        WHERE source_id=? AND target_id=?
                          AND relation_type IN ('enables','causes','supports',
                                                'SUPPORTS','BRIDGES','REFINES')
                    """, (src, tgt))
                except Exception:
                    pass

    # ── 4. Fire existing strong cycles ───────────────────────────
    # Cycles above strength 0.5 get a "heartbeat" — their beliefs
    # get a tiny confidence boost (they're earning their place)
    strong_cycles = conn.execute("""
        SELECT id, cycle_beliefs, strength FROM autocatalytic_cycles
        WHERE strength > 0.3
        ORDER BY strength DESC LIMIT 10
    """).fetchall()

    for cid, cbels, strength in strong_cycles:
        try:
            bids = json.loads(cbels)
            boost = 0.001 * strength  # tiny, proportional to strength
            for bid in bids:
                try:
                    conn.execute(
                        "UPDATE beliefs SET confidence = MIN(0.95, confidence + ?) "
                        "WHERE id=? AND locked=0",
                        (boost, bid))
                except Exception:
                    pass  # locked belief trigger
            conn.execute(
                "UPDATE autocatalytic_cycles SET times_fired=times_fired+1, "
                "last_fired=? WHERE id=?", (time.time(), cid))
            cycles_fired += 1
        except Exception:
            pass

    # ── 5. Identify catalysts ────────────────────────────────────
    # A catalyst is a belief that appears in 2+ different cycles
    all_cycles = conn.execute(
        "SELECT cycle_beliefs FROM autocatalytic_cycles WHERE strength > 0.1"
    ).fetchall()

    belief_cycle_count = Counter()
    for (cbels,) in all_cycles:
        try:
            for bid in json.loads(cbels):
                belief_cycle_count[bid] += 1
        except Exception:
            pass

    catalysts_count = 0
    for bid, count in belief_cycle_count.items():
        if count >= 2:
            # This belief is a catalyst — reduce its metabolic rate
            # (immune to composting, it's a load-bearing node)
            try:
                conn.execute(
                    "UPDATE beliefs SET metabolic_rate = 0.0 WHERE id=?",
                    (bid,))
                catalysts_count += 1
            except Exception:
                pass

    # ── 6. Far-from-equilibrium: perturb if too stable ───────────
    # Check current tension level
    try:
        avg_tension = conn.execute(
            "SELECT AVG(energy) FROM tensions WHERE resolved=0"
        ).fetchone()[0] or 0
    except Exception:
        avg_tension = 0

    if avg_tension < 0.2:
        # System is too stable — inject perturbation
        # Pick two random beliefs from different topics and create a tension
        try:
            pair = conn.execute("""
                SELECT a.id, b.id FROM beliefs a, beliefs b
                WHERE a.topic != b.topic
                  AND a.confidence > 0.5 AND b.confidence > 0.5
                  AND a.id != b.id
                ORDER BY RANDOM() LIMIT 1
            """).fetchone()
            if pair:
                conn.execute("""
                    INSERT OR IGNORE INTO tensions
                    (belief_a_id, belief_b_id, energy, topic, resolved, created_at)
                    VALUES (?,?,0.5,'metabolic_perturbation',0,?)
                """, (pair[0], pair[1], time.time()))
                perturbations += 1
        except Exception:
            pass

    # ── Record metabolic state ───────────────────────────────────
    conn.execute("""
        INSERT INTO metabolic_state
        (tick, cycles_found, cycles_fired, catalysts_count,
         perturbations, avg_tension, timestamp)
        VALUES (?,?,?,?,?,?,?)
    """, (tick_num, cycles_found, cycles_fired, catalysts_count,
          perturbations, avg_tension or 0, time.time()))

    conn.commit()
    conn.close()

    return {
        "tick": tick_num,
        "cycles_found": cycles_found,
        "cycles_fired": cycles_fired,
        "catalysts": catalysts_count,
        "perturbations": perturbations,
        "avg_tension": avg_tension or 0,
    }


# ═══════════════════════════════════════════════════════════════════
#  DAEMON — continuous background thread
# ═══════════════════════════════════════════════════════════════════

class MetabolismDaemon(threading.Thread):
    """Continuous background metabolism. The cell breathes."""

    def __init__(self, interval=60):
        super().__init__(daemon=True)
        self.interval = interval  # seconds between ticks
        self._stop_event = threading.Event()
        self.tick_count = 0

    def run(self):
        print(f"  {C.GREEN}metabolism daemon started (interval={self.interval}s){C.RST}")
        while not self._stop_event.is_set():
            try:
                self.tick_count += 1
                result = metabolic_tick(self.tick_count)
                if result["cycles_found"] > 0 or result["perturbations"] > 0:
                    print(f"  {C.CYAN}[metabolism #{self.tick_count}]{C.RST} "
                          f"found={result['cycles_found']} "
                          f"fired={result['cycles_fired']} "
                          f"catalysts={result['catalysts']} "
                          f"perturb={result['perturbations']}")
            except Exception as e:
                print(f"  {C.RED}[metabolism] {e}{C.RST}")
            self._stop_event.wait(self.interval)

    def stop(self):
        self._stop_event.set()


# ═══════════════════════════════════════════════════════════════════
#  STATUS & DISPLAY
# ═══════════════════════════════════════════════════════════════════

def show_status():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)

    total_cycles = conn.execute(
        "SELECT COUNT(*) FROM autocatalytic_cycles"
    ).fetchone()[0]
    strong_cycles = conn.execute(
        "SELECT COUNT(*) FROM autocatalytic_cycles WHERE strength > 0.3"
    ).fetchone()[0]
    total_ticks = conn.execute(
        "SELECT COUNT(*) FROM metabolic_state"
    ).fetchone()[0]

    # Catalysts
    all_cbels = conn.execute(
        "SELECT cycle_beliefs FROM autocatalytic_cycles WHERE strength > 0.1"
    ).fetchall()
    belief_counts = Counter()
    for (cbels,) in all_cbels:
        try:
            for bid in json.loads(cbels):
                belief_counts[bid] += 1
        except Exception:
            pass
    catalysts = [(bid, cnt) for bid, cnt in belief_counts.items() if cnt >= 2]

    # Recent metabolic state
    recent = conn.execute(
        "SELECT tick, cycles_found, cycles_fired, catalysts_count, "
        "perturbations, avg_tension FROM metabolic_state "
        "ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()

    conn.close()

    w = tw()
    print(f"\n{C.CYAN}{C.BOLD}{'━' * w}{C.RST}")
    print(f"{C.CYAN}{C.BOLD}  ◆  METABOLISM STATUS  ◆{C.RST}")
    print(f"{C.CYAN}{C.BOLD}{'━' * w}{C.RST}")
    print(f"    {C.WHITE}{total_ticks}{C.RST}  {C.GREY}total ticks{C.RST}")
    print(f"    {C.WHITE}{total_cycles}{C.RST}  {C.GREY}cycles discovered{C.RST}")
    print(f"    {C.GREEN}{strong_cycles}{C.RST}  {C.GREY}strong cycles (>0.3){C.RST}")
    print(f"    {C.PINK}{len(catalysts)}{C.RST}  {C.GREY}catalyst beliefs{C.RST}")
    if recent:
        print(f"    {C.WHITE}{recent[5]:.3f}{C.RST}  {C.GREY}avg tension energy{C.RST}")
    print(f"{C.CYAN}{'━' * w}{C.RST}\n")


def show_cycles():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    cycles = conn.execute("""
        SELECT cycle_beliefs, cycle_length, strength, times_fired
        FROM autocatalytic_cycles
        ORDER BY strength DESC LIMIT 15
    """).fetchall()

    w = tw()
    print(f"\n{C.GREEN}{C.BOLD}{'━' * w}{C.RST}")
    print(f"{C.GREEN}{C.BOLD}  AUTOCATALYTIC CYCLES{C.RST}")
    print(f"{C.GREEN}{C.BOLD}{'━' * w}{C.RST}")

    for cbels, length, strength, times in cycles:
        try:
            bids = json.loads(cbels)
            # Get first belief content
            row = conn.execute(
                "SELECT substr(content,1,50) FROM beliefs WHERE id=?",
                (bids[0],)).fetchone()
            label = row[0] if row else "?"
            sc = C.GREEN if strength > 0.5 else C.YELLOW if strength > 0.2 else C.GREY
            print(f"  {sc}[{strength:.2f}]{C.RST} len={length} "
                  f"fired={times}  {C.GREY}{label}{C.RST}")
        except Exception:
            pass

    conn.close()
    print()


def show_catalysts():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)

    all_cbels = conn.execute(
        "SELECT cycle_beliefs FROM autocatalytic_cycles WHERE strength > 0.1"
    ).fetchall()
    belief_counts = Counter()
    for (cbels,) in all_cbels:
        try:
            for bid in json.loads(cbels):
                belief_counts[bid] += 1
        except Exception:
            pass

    catalysts = [(bid, cnt) for bid, cnt in belief_counts.most_common(15) if cnt >= 2]

    w = tw()
    print(f"\n{C.PINK}{C.BOLD}{'━' * w}{C.RST}")
    print(f"{C.PINK}{C.BOLD}  CATALYST BELIEFS (in 2+ cycles){C.RST}")
    print(f"{C.PINK}{C.BOLD}{'━' * w}{C.RST}")

    for bid, cnt in catalysts:
        row = conn.execute(
            "SELECT substr(content,1,55), confidence FROM beliefs WHERE id=?",
            (bid,)).fetchone()
        if row:
            print(f"  {C.PINK}[{cnt} cycles]{C.RST} conf={row[1]:.2f}  "
                  f"{C.GREY}{row[0]}{C.RST}")

    conn.close()
    print()


# ─── CLI ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NEX Autocatalytic Metabolism")
    parser.add_argument("--daemon", action="store_true", help="run as background daemon")
    parser.add_argument("--status", action="store_true", help="show metabolic state")
    parser.add_argument("--cycles", action="store_true", help="show discovered cycles")
    parser.add_argument("--catalysts", action="store_true", help="show catalyst beliefs")
    parser.add_argument("--once", action="store_true", help="run one tick")
    parser.add_argument("--interval", type=int, default=10, help="seconds between ticks")
    parser.add_argument("--ticks", type=int, default=50, help="ticks for foreground run")
    args = parser.parse_args()

    ensure_schema()

    if args.status:
        show_status()
    elif args.cycles:
        show_cycles()
    elif args.catalysts:
        show_catalysts()
    elif args.once:
        result = metabolic_tick(0)
        print(f"  {C.GREEN}tick:{C.RST} found={result['cycles_found']} "
              f"fired={result['cycles_fired']} catalysts={result['catalysts']} "
              f"perturb={result['perturbations']} tension={result['avg_tension']:.3f}")
    elif args.daemon:
        d = MetabolismDaemon(interval=args.interval)
        d.start()
        print(f"  {C.GREEN}metabolism daemon running. Ctrl+C to stop.{C.RST}")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            d.stop()
            print(f"\n  {C.GREY}metabolism stopped.{C.RST}")
    else:
        # Foreground run: N ticks with display
        w = tw()
        print(f"\n{C.CYAN}{C.BOLD}{'━' * w}{C.RST}")
        print(f"{C.CYAN}{C.BOLD}  ◆  METABOLISM — {args.ticks} TICKS  ◆{C.RST}")
        print(f"{C.CYAN}{C.BOLD}{'━' * w}{C.RST}")

        total_found = 0
        total_fired = 0

        for i in range(1, args.ticks + 1):
            result = metabolic_tick(i)
            total_found += result["cycles_found"]
            total_fired += result["cycles_fired"]

            if result["cycles_found"] > 0:
                print(f"  {C.GREEN}[{i}] NEW CYCLE FOUND{C.RST} "
                      f"(total: {total_found})")
            elif result["perturbations"] > 0:
                print(f"  {C.YELLOW}[{i}] perturbation injected{C.RST}")
            elif i % 10 == 0:
                print(f"  {C.GREY}[{i}] fired={result['cycles_fired']} "
                      f"tension={result['avg_tension']:.3f}{C.RST}")

            time.sleep(0.1)  # fast in foreground mode

        print(f"\n  {C.GREEN}✓ {args.ticks} ticks complete{C.RST}")
        print(f"    cycles found: {total_found}")
        print(f"    cycles fired: {total_fired}")
        show_status()


if __name__ == "__main__":
    main()
