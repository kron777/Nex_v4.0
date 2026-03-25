"""
NEX :: BELIEF SURVIVAL DYNAMICS
================================
Implements belief energy — a second axis alongside confidence.

Energy decays passively each cycle.
Energy is boosted when a belief is used in a reply/synthesis.
When energy < kill_threshold → belief is deleted.
When energy is repeatedly high → confidence is amplified.

This runs alongside the existing decay_stale_beliefs() — they are
complementary. decay_stale_beliefs() weakens confidence over time;
this module can delete beliefs entirely and amplify survivors.

Schema migration: adds `energy` column to beliefs table if absent.
Safe to run on existing DBs.
"""

import sqlite3
import os
from datetime import datetime

CONFIG_DIR = os.path.expanduser("~/.config/nex")
DB_PATH    = os.path.join(CONFIG_DIR, "nex.db")

# ── Tunable constants ─────────────────────────────────────────────────────────
ENERGY_START        = 100.0   # energy given to a new belief
ENERGY_DECAY_PER_CYCLE = 0.15  # lost each cycle if not used
ENERGY_USE_BOOST    = 20.0    # gained when belief is referenced in output
ENERGY_KILL_THRESHOLD = 0.5  # safety: see MIN_BELIEF_FLOOR  # below this → belief is deleted
MIN_BELIEF_FLOOR      = 1000    # never kill beliefs if total below this
ENERGY_AMPLIFY_THRESHOLD = 70.0  # above this → confidence boosted
ENERGY_AMPLIFY_BOOST = 0.02   # confidence boost per cycle at high energy
ENERGY_MAX          = 120.0   # cap
HUMAN_VALIDATED_EXEMPT = True  # never kill human-validated beliefs


def _ensure_energy_column():
    """Add energy column to beliefs table if it doesn't exist yet."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()]
        if "energy" not in cols:
            conn.execute(f"ALTER TABLE beliefs ADD COLUMN energy REAL DEFAULT {ENERGY_START}")
            conn.execute(f"UPDATE beliefs SET energy = {ENERGY_START} WHERE energy IS NULL")
            conn.commit()
            print(f"  [BeliefSurvival] added energy column, initialised all beliefs to {ENERGY_START}")
    finally:
        conn.close()


def run_energy_cycle(verbose=False):
    """
    Main cycle call — call once per cognition cycle.
    1. Decay all belief energy by ENERGY_DECAY_PER_CYCLE
    2. Amplify confidence for high-energy beliefs
    3. Delete beliefs below kill threshold (unless human_validated)
    Returns dict with counts.
    """
    _ensure_energy_column()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    killed = 0
    amplified = 0
    decayed = 0

    try:
        # 1. Passive decay
        conn.execute("""
            UPDATE beliefs
            SET energy = MAX(energy - ?, 0)
            WHERE energy > 0
        """, (ENERGY_DECAY_PER_CYCLE,))
        decayed = conn.execute("SELECT changes()").fetchone()[0]

        # 2. Amplify high-energy beliefs — boost confidence
        conn.execute("""
            UPDATE beliefs
            SET confidence = MIN(confidence + ?, 0.97)
            WHERE energy >= ?
              AND confidence < 0.97
        """, (ENERGY_AMPLIFY_BOOST, ENERGY_AMPLIFY_THRESHOLD))
        amplified = conn.execute("SELECT changes()").fetchone()[0]

        # 3. Kill low-energy beliefs — respect minimum floor
        _total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        if _total <= MIN_BELIEF_FLOOR:
            if verbose:
                print(f"  [BeliefSurvival] floor protection: {_total} beliefs, kill skipped")
            conn.close()
            return {"decayed": decayed, "amplified": amplified, "killed": 0}
        kill_condition = "energy < ? AND energy IS NOT NULL"
        if HUMAN_VALIDATED_EXEMPT:
            kill_condition += " AND human_validated = 0"

        # Log what's being killed before deleting
        dying = conn.execute(f"""
            SELECT id, content, confidence, energy FROM beliefs
            WHERE {kill_condition}
            LIMIT 50
        """, (ENERGY_KILL_THRESHOLD,)).fetchall()

        if dying:
            ids = [r["id"] for r in dying]
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM beliefs WHERE id IN ({placeholders})", ids)
            killed = len(ids)
            if verbose:
                for r in dying[:5]:
                    print(f"  [BeliefSurvival] KILLED: [{r['energy']:.1f}E] {r['content'][:60]}")

        conn.commit()

    finally:
        conn.close()

    result = {"decayed": decayed, "amplified": amplified, "killed": killed}
    if verbose or killed > 0:
        print(f"  [BeliefSurvival] cycle: {decayed} decayed | {amplified} amplified | {killed} killed")
    return result


def boost_belief_energy(content, boost=None):
    """
    Call this whenever a belief is actually used in a reply or synthesis.
    Increases energy and reinforces confidence.
    """
    if not content:
        return
    boost = boost or ENERGY_USE_BOOST
    _ensure_energy_column()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            UPDATE beliefs
            SET energy         = MIN(energy + ?, ?),
                last_referenced = ?,
                decay_score     = MAX(decay_score - 1, 0)
            WHERE content = ?
        """, (boost, ENERGY_MAX, datetime.now().isoformat(), content.strip()))
        conn.commit()
    finally:
        conn.close()


def boost_belief_energy_by_id(belief_id, boost=None):
    """Boost by ID — faster when you have the ID already."""
    boost = boost or ENERGY_USE_BOOST
    _ensure_energy_column()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            UPDATE beliefs
            SET energy         = MIN(energy + ?, ?),
                last_referenced = ?
            WHERE id = ?
        """, (boost, ENERGY_MAX, datetime.now().isoformat(), belief_id))
        conn.commit()
    finally:
        conn.close()


def get_energy_stats():
    """Return summary stats about belief energy distribution."""
    _ensure_energy_column()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                AVG(energy) as avg_energy,
                MIN(energy) as min_energy,
                MAX(energy) as max_energy,
                SUM(CASE WHEN energy < ? THEN 1 ELSE 0 END) as dying,
                SUM(CASE WHEN energy >= ? THEN 1 ELSE 0 END) as thriving
            FROM beliefs
        """, (ENERGY_KILL_THRESHOLD * 2, ENERGY_AMPLIFY_THRESHOLD)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def initialise_energy_for_existing_beliefs():
    """
    One-time call to set energy based on existing confidence + recency.
    High-confidence old beliefs start with moderate energy.
    Recently referenced beliefs start with high energy.
    """
    _ensure_energy_column()
    conn = sqlite3.connect(DB_PATH)
    try:
        # Beliefs referenced in last 7 days: high energy
        conn.execute("""
            UPDATE beliefs
            SET energy = ?
            WHERE last_referenced >= datetime('now', '-7 days')
              AND (energy IS NULL OR energy = ?)
        """, (ENERGY_START, ENERGY_START))

        # Beliefs with confidence > 0.7: moderate-high energy
        conn.execute("""
            UPDATE beliefs
            SET energy = ?
            WHERE confidence >= 0.7
              AND (last_referenced < datetime('now', '-7 days') OR last_referenced IS NULL)
              AND (energy IS NULL OR energy = ?)
        """, (60.0, ENERGY_START))

        # Everything else: moderate energy
        conn.execute("""
            UPDATE beliefs
            SET energy = ?
            WHERE energy IS NULL OR energy = ?
        """, (40.0, ENERGY_START))

        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        print(f"  [BeliefSurvival] initialised energy for {total} existing beliefs")
    finally:
        conn.close()


if __name__ == "__main__":
    # Run a manual cycle with verbose output
    initialise_energy_for_existing_beliefs()
    stats = get_energy_stats()
    print(f"  Energy stats: {stats}")
    result = run_energy_cycle(verbose=True)
    print(f"  Cycle result: {result}")
