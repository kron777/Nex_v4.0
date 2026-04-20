"""
nex_cognitive_pressure.py — Cognitive Pressure Metric + Stall Detection
=========================================================================
Computes: pressure = total_tension_weight / belief_count

States:
    LOW  (<0.3)  → increase mutation rate
    MED  (0.3-0.7) → normal operation
    HIGH (>0.7)  → force resolution, suppress new beliefs

Stall detection:
    Tracks belief_count + insight_count per cycle.
    If no change over STALL_CYCLES → triggers mutation burst.

Wire-in (run.py, after 7d):
    from nex_cognitive_pressure import run_pressure_metric
    _cp = run_pressure_metric(cycle=cycle, llm_fn=_llm)
"""

import sqlite3
import json
import os
import time
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "nex"
DB_PATH    = CONFIG_DIR / "nex.db"
STATE_PATH = CONFIG_DIR / "pressure_state.json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Thresholds ────────────────────────────────────────────────────────────────
PRESSURE_LOW       = 0.3
PRESSURE_HIGH      = 0.85
STALL_CYCLES       = 8     # cycles with no change before mutation burst
MUTATION_BURST_N   = 5     # beliefs to randomly perturb during burst
OVERLOAD_QUEUE_MAX = 80    # auto-collapse tensions if queue exceeds this


def _load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {
        "last_belief_count": 0,
        "last_insight_count": 0,
        "stall_count": 0,
        "last_pressure": 0.0,
        "mutation_bursts": 0,
        "history": [],
    }


def _save_state(state):
    try:
        STATE_PATH.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def _compute_pressure(db):
    """pressure = sum(tension weights) / belief_count"""
    try:
        belief_count = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        if belief_count == 0:
            return 0.0, belief_count
        tension_sum = db.execute(
            "SELECT SUM(weight) FROM tensions WHERE resolved_at IS NULL"
        ).fetchone()[0] or 0.0
        return round(tension_sum / belief_count, 4), belief_count
    except Exception:
        return 0.0, 0


def _get_insight_count(db):
    try:
        return db.execute("SELECT COUNT(*) FROM beliefs WHERE source='contradiction_engine' OR tags LIKE '%insight%'").fetchone()[0]
    except Exception:
        return 0


def _force_mutation_burst(db, n=MUTATION_BURST_N, verbose=False):
    """
    Randomly perturb confidence of N mid-range beliefs.
    Introduces controlled instability when system is stalled.
    """
    import random
    mutated = 0
    try:
        candidates = db.execute("""
            SELECT id, content, confidence FROM beliefs
            WHERE confidence BETWEEN 0.35 AND 0.75
            AND human_validated = 0
            AND source NOT IN ('dream_inversion', 'identity_core')
            ORDER BY RANDOM()
            LIMIT ?
        """, (n,)).fetchall()

        for bid, content, conf in candidates:
            # Random perturbation ±10-25%
            delta = random.uniform(-0.25, 0.25)
            new_conf = max(0.1, min(0.95, conf + delta * conf))
            db.execute(
                "UPDATE beliefs SET confidence = ? WHERE id = ?",
                (round(new_conf, 3), bid)
            )
            mutated += 1
            if verbose:
                direction = "▲" if delta > 0 else "▼"
                print(f"  [MutBurst] {direction} {conf:.2f}→{new_conf:.2f}: {(content or '')[:50]}")

        db.commit()
    except Exception as e:
        if verbose:
            print(f"  [MutBurst] error: {e}")
    return mutated


def _auto_collapse_overloaded_queue(db, verbose=False):
    """
    If tension queue > OVERLOAD_QUEUE_MAX, auto-resolve lowest priority tensions.
    Prevents cognitive overload.
    """
    try:
        queue_size = db.execute(
            "SELECT COUNT(*) FROM tensions WHERE resolved_at IS NULL"
        ).fetchone()[0]

        if queue_size <= OVERLOAD_QUEUE_MAX:
            return 0

        # Resolve lowest weight, oldest tensions first
        to_resolve = db.execute("""
            SELECT id, topic FROM tensions
            WHERE resolved_at IS NULL
            AND escalation_level = 0
            ORDER BY weight ASC, created_at ASC
            LIMIT ?
        """, (queue_size - OVERLOAD_QUEUE_MAX,)).fetchall()

        now = datetime.now().isoformat()
        for tid, topic in to_resolve:
            db.execute(
                "UPDATE tensions SET resolved_at = ? WHERE id = ?",
                (now, tid)
            )
            if verbose:
                print(f"  [Overload] auto-resolved: {topic[:40]}")

        db.commit()
        return len(to_resolve)
    except Exception:
        return 0


def run_pressure_metric(cycle=0, llm_fn=None, verbose=False):
    """
    Main cycle call. Returns dict with pressure state and actions taken.
    """
    if not DB_PATH.exists():
        return {}

    db = sqlite3.connect(str(DB_PATH), isolation_level=None)
    state = _load_state()

    pressure, belief_count = _compute_pressure(db)
    insight_count = _get_insight_count(db)

    # Determine pressure state
    if pressure < PRESSURE_LOW:
        pressure_state = "LOW"
    elif pressure > PRESSURE_HIGH:
        pressure_state = "HIGH"
    else:
        pressure_state = "MED"

    # ── Stall detection ───────────────────────────────────────────────────────
    belief_changed  = abs(belief_count - state["last_belief_count"]) > 2
    insight_changed = abs(insight_count - state["last_insight_count"]) > 0

    mutation_burst = 0
    if not belief_changed and not insight_changed:
        state["stall_count"] += 1
    else:
        state["stall_count"] = 0

    if state["stall_count"] >= STALL_CYCLES:
        mutation_burst = _force_mutation_burst(db, verbose=verbose)
        state["stall_count"] = 0
        state["mutation_bursts"] += 1
        if verbose or mutation_burst > 0:
            print(f"  [CogPressure] STALL DETECTED — burst mutated {mutation_burst} beliefs")

    # ── Overload protection ───────────────────────────────────────────────────
    collapsed = _auto_collapse_overloaded_queue(db, verbose=verbose)

    # ── Pressure-driven mutation boost ───────────────────────────────────────
    # LOW pressure = system too stable = inject more perturbation
    extra_mutation = 0
    if pressure_state == "LOW" and cycle % 3 == 0:
        extra_mutation = _force_mutation_burst(db, n=3, verbose=False)

    # HIGH pressure = force resolution of oldest escalated tension
    forced_resolution = 0
    if pressure_state == "HIGH":
        try:
            oldest = db.execute("""
                SELECT id, topic FROM tensions
                WHERE resolved_at IS NULL AND escalation_level >= 1
                ORDER BY cycle_count DESC LIMIT 1
            """).fetchone()
            if oldest:
                db.execute(
                    "UPDATE tensions SET resolved_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), oldest[0])
                )
                db.commit()
                forced_resolution = 1
                if verbose:
                    print(f"  [CogPressure] HIGH — forced resolution: {oldest[1][:40]}")
        except Exception:
            pass

    # ── Update state ──────────────────────────────────────────────────────────
    state["last_belief_count"]  = belief_count
    state["last_insight_count"] = insight_count
    state["last_pressure"]      = pressure
    state["history"].append({
        "cycle": cycle,
        "pressure": pressure,
        "state": pressure_state,
        "beliefs": belief_count,
        "stall": state["stall_count"],
        "ts": datetime.now().isoformat(),
    })
    state["history"] = state["history"][-100:]  # keep last 100
    _save_state(state)

    db.close()

    result = {
        "pressure":          pressure,
        "pressure_state":    pressure_state,
        "belief_count":      belief_count,
        "stall_count":       state["stall_count"],
        "mutation_burst":    mutation_burst,
        "extra_mutation":    extra_mutation,
        "forced_resolution": forced_resolution,
        "collapsed":         collapsed,
    }

    if verbose or mutation_burst or collapsed or forced_resolution:
        print(f"  [CogPressure] p={pressure:.3f} [{pressure_state}] "
              f"stall={state['stall_count']} burst={mutation_burst} "
              f"collapsed={collapsed} forced_res={forced_resolution}")

    return result


def get_pressure_history(n=20):
    """Return recent pressure history for dashboard."""
    state = _load_state()
    return state.get("history", [])[-n:]


def get_evolution_score():
    """
    Simple evolution score: beliefs_added - beliefs_removed + tensions_resolved.
    Gives a single number for how much the system evolved this session.
    """
    if not DB_PATH.exists():
        return 0
    db = sqlite3.connect(str(DB_PATH), isolation_level=None)
    try:
        # Beliefs added today
        added = db.execute("""
            SELECT COUNT(*) FROM beliefs
            WHERE timestamp > datetime('now', '-24 hours')
        """).fetchone()[0]
        # Tensions resolved today
        resolved = db.execute("""
            SELECT COUNT(*) FROM tensions
            WHERE resolved_at > datetime('now', '-24 hours')
        """).fetchone()[0]
        # Dream beliefs (new synthesis)
        dream = db.execute("""
            SELECT COUNT(*) FROM beliefs
            WHERE source LIKE 'dream%'
            AND timestamp > datetime('now', '-24 hours')
        """).fetchone()[0]
        return added + (resolved * 3) + (dream * 2)
    finally:
        db.close()


if __name__ == "__main__":
    result = run_pressure_metric(cycle=1, verbose=True)
    print(f"\nPressure result: {result}")
    print(f"Evolution score: {get_evolution_score()}")
