#!/usr/bin/env python3
"""
nex_drive_lifecycle.py  —  Drive Urgency Lifecycle
================================================================
NEX v1.0 — Build 5

Drives have urgency that BUILDS when neglected, FADES when satisfied.
Makes NEX's motivation dynamic. She genuinely wants things.
She becomes restless when drives are unsatisfied.

Extends nex_drives.py — reads the same nex_drives.json file,
adds urgency state on top without touching the base intensity.

Urgency vs Intensity:
    intensity  — base drive strength (stable, changes slowly with beliefs)
    urgency    — dynamic pressure (builds over time, drops when satisfied)
    effective  — intensity * urgency_multiplier  (what the loop actually uses)

Urgency lifecycle:
    NEGLECT:   Each cycle a drive goes unengaged → urgency += NEGLECT_RATE
    SATISFY:   Drive topic ingested / curiosity gap filled → urgency *= DECAY_FACTOR
    SPIKE:     Contradiction or gap detected in drive domain → urgency += SPIKE_AMOUNT
    CAP:       urgency capped at 1.0, floor at 0.1

Urgency state persists in ~/.config/nex/drive_urgency.json between restarts.

Drive state influences template class selection in the voice layer:
    urgency > 0.8  → ASSERT or CHALLENGE templates
    urgency > 0.6  → WONDER or OBSERVE templates
    urgency < 0.3  → REFLECT templates (settled, resting)

CLI:
    python3 nex_drive_lifecycle.py --status        # print all drive urgencies
    python3 nex_drive_lifecycle.py --tick           # run one neglect tick
    python3 nex_drive_lifecycle.py --satisfy <id>  # mark drive as satisfied
    python3 nex_drive_lifecycle.py --spike <id>    # spike a drive (gap found)
"""

import argparse
import json
import logging
import time
from pathlib import Path

log = logging.getLogger("nex.drives")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

CFG_PATH       = Path("~/.config/nex").expanduser()
DRIVES_PATH    = CFG_PATH / "nex_drives.json"
URGENCY_PATH   = CFG_PATH / "drive_urgency.json"
DB_PATH        = CFG_PATH / "nex.db"

# ── Lifecycle constants ───────────────────────────────────────────────────────

NEGLECT_RATE   = 0.04    # urgency added per cycle when drive unengaged
DECAY_FACTOR   = 0.65    # urgency multiplied by this when satisfied
SPIKE_AMOUNT   = 0.20    # urgency added on contradiction / gap detection
URGENCY_FLOOR  = 0.10    # minimum urgency (drives never fully go quiet)
URGENCY_CAP    = 1.00    # maximum urgency

# Template class thresholds
ASSERT_THRESH  = 0.80
WONDER_THRESH  = 0.60
REFLECT_THRESH = 0.30

# ── Drive file I/O ────────────────────────────────────────────────────────────

def _load_drives() -> list[dict]:
    """Load drives from nex_drives.json. Returns empty list if not found."""
    if not DRIVES_PATH.exists():
        log.warning(f"nex_drives.json not found at {DRIVES_PATH}")
        return []
    try:
        data = json.loads(DRIVES_PATH.read_text())
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Some versions wrap in {"primary": [...], "secondary": [...]}
            drives = []
            for key in ("primary", "secondary", "active", "drives"):
                if key in data and isinstance(data[key], list):
                    drives.extend(data[key])
            return drives
    except Exception as e:
        log.error(f"Failed to load drives: {e}")
    return []


def _load_urgency() -> dict:
    """Load persisted urgency state. Returns {} if not found."""
    if not URGENCY_PATH.exists():
        return {}
    try:
        return json.loads(URGENCY_PATH.read_text())
    except Exception:
        return {}


def _save_urgency(state: dict):
    try:
        URGENCY_PATH.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log.error(f"Failed to save urgency state: {e}")


# ── Urgency initialisation ────────────────────────────────────────────────────

def _init_urgency(drives: list[dict], state: dict) -> dict:
    """
    Ensure every drive has an urgency entry.
    New drives start at their base intensity (feels natural — urgency
    reflects how long since the drive was satisfied).
    """
    for drive in drives:
        did = drive.get("id") or drive.get("label", "unknown")
        if did not in state:
            state[did] = {
                "urgency":      drive.get("intensity", 0.5),
                "last_tick":    time.time(),
                "last_satisfied": 0.0,
                "satisfy_count": 0,
                "spike_count":  0,
            }
    return state


# ── Core lifecycle operations ─────────────────────────────────────────────────

def tick_neglect(drives: list[dict], state: dict) -> dict:
    """
    One neglect tick — called each cognitive loop cycle.
    Every drive that wasn't satisfied this cycle gets more urgent.
    Drives that were satisfied get partial credit (reduced neglect).
    """
    now = time.time()
    for drive in drives:
        did = drive.get("id") or drive.get("label", "unknown")
        if did not in state:
            continue

        entry = state[did]
        time_since_satisfy = now - entry.get("last_satisfied", 0.0)

        # If satisfied within last 2 cycles (rough: 60s), apply reduced neglect
        if time_since_satisfy < 60:
            delta = NEGLECT_RATE * 0.2   # recently satisfied — low pressure
        else:
            delta = NEGLECT_RATE

        new_urgency = min(URGENCY_CAP, entry["urgency"] + delta)
        entry["urgency"]   = round(new_urgency, 4)
        entry["last_tick"] = now

    return state


def satisfy_drive(drive_id: str, state: dict, partial: bool = False) -> float:
    """
    Mark a drive as satisfied (topic ingested, gap filled, curiosity resolved).
    Returns new urgency value.

    partial=True: half decay (e.g. tangentially related content found)
    partial=False: full decay (e.g. directly relevant belief ingested)
    """
    if drive_id not in state:
        log.warning(f"satisfy_drive: unknown drive id '{drive_id}'")
        return 0.0

    entry   = state[drive_id]
    factor  = DECAY_FACTOR if not partial else (1.0 - (1.0 - DECAY_FACTOR) * 0.5)
    new_urg = max(URGENCY_FLOOR, entry["urgency"] * factor)

    entry["urgency"]       = round(new_urg, 4)
    entry["last_satisfied"] = time.time()
    entry["satisfy_count"] = entry.get("satisfy_count", 0) + 1

    log.debug(f"  [drives] satisfy '{drive_id}' → urgency {new_urg:.3f}")
    return new_urg


def spike_drive(drive_id: str, state: dict) -> float:
    """
    Spike a drive — contradiction or gap detected in this domain.
    NEX becomes restless about this topic.
    Returns new urgency value.
    """
    if drive_id not in state:
        log.warning(f"spike_drive: unknown drive id '{drive_id}'")
        return 0.0

    entry   = state[drive_id]
    new_urg = min(URGENCY_CAP, entry["urgency"] + SPIKE_AMOUNT)

    entry["urgency"]    = round(new_urg, 4)
    entry["spike_count"] = entry.get("spike_count", 0) + 1

    log.info(f"  [drives] spike '{drive_id}' → urgency {new_urg:.3f}")
    return new_urg


# ── Topic → drive matching ────────────────────────────────────────────────────

def match_drives_to_topic(topic: str, drives: list[dict]) -> list[str]:
    """
    Given a belief topic string, return IDs of drives this topic satisfies.
    Matching: drive tags against topic words (case-insensitive substring).
    """
    topic_lower = topic.lower()
    matched = []
    for drive in drives:
        did  = drive.get("id") or drive.get("label", "unknown")
        tags = drive.get("tags", [])
        for tag in tags:
            if tag.lower() in topic_lower or topic_lower in tag.lower():
                matched.append(did)
                break
    return matched


# ── Auto-satisfy from recent beliefs ─────────────────────────────────────────

def auto_satisfy_from_db(drives: list[dict], state: dict,
                          lookback_cycles: int = 1) -> dict:
    """
    Check beliefs ingested in recent cycles against drive tags.
    Satisfy matching drives automatically.
    Called once per loop cycle after ingestion.
    """
    import sqlite3
    try:
        con  = sqlite3.connect(str(DB_PATH))
        con.row_factory = sqlite3.Row
        # Beliefs created in last ~10 minutes (rough cycle window)
        rows = con.execute("""
            SELECT topic FROM beliefs
            WHERE timestamp >= datetime('now', '-10 minutes')
              AND topic IS NOT NULL
        """).fetchall()
        con.close()

        recent_topics = [r["topic"] for r in rows if r["topic"]]
        satisfied_ids = set()

        for topic in recent_topics:
            matched = match_drives_to_topic(topic, drives)
            for did in matched:
                if did not in satisfied_ids:
                    satisfy_drive(did, state, partial=False)
                    satisfied_ids.add(did)

    except Exception as e:
        log.warning(f"auto_satisfy_from_db failed: {e}")

    return state


# ── Auto-spike from contradiction/gap tables ──────────────────────────────────

def auto_spike_from_db(drives: list[dict], state: dict) -> dict:
    """
    Check contradiction_pairs and curiosity_gaps tables for recent entries.
    Spike drives whose tags match the topics involved.
    """
    import sqlite3
    try:
        con  = sqlite3.connect(str(DB_PATH))
        con.row_factory = sqlite3.Row

        # Recent unresolved curiosity gaps
        gap_rows = con.execute("""
            SELECT topic FROM curiosity_gaps
            WHERE filled = 0
              AND detected_at >= unixepoch('now') - 600
        """).fetchall()

        spiked_ids = set()
        for row in gap_rows:
            topic   = row["topic"] or ""
            matched = match_drives_to_topic(topic, drives)
            for did in matched:
                if did not in spiked_ids:
                    spike_drive(did, state)
                    spiked_ids.add(did)

        con.close()
    except Exception as e:
        log.warning(f"auto_spike_from_db failed: {e}")

    return state


# ── Effective drive pressure ──────────────────────────────────────────────────

def get_effective_pressure(drives: list[dict], state: dict) -> list[dict]:
    """
    Return all drives with computed effective pressure.
    effective = base_intensity * urgency_multiplier

    urgency_multiplier:
        urgency 0.0–0.3 → multiplier 0.5  (settled)
        urgency 0.3–0.6 → multiplier 1.0  (normal)
        urgency 0.6–0.8 → multiplier 1.5  (elevated)
        urgency 0.8–1.0 → multiplier 2.0  (restless)

    Sorted by effective pressure descending — highest pressure drive first.
    Used by run.py to prioritise which topic NEX focuses on this cycle.
    """
    result = []
    for drive in drives:
        did       = drive.get("id") or drive.get("label", "unknown")
        entry     = state.get(did, {})
        urgency   = entry.get("urgency", drive.get("intensity", 0.5))
        intensity = drive.get("intensity", 0.5)

        if urgency >= 0.8:
            mult = 2.0
        elif urgency >= 0.6:
            mult = 1.5
        elif urgency >= 0.3:
            mult = 1.0
        else:
            mult = 0.5

        effective = round(min(1.0, intensity * mult / 2.0), 4)

        result.append({
            "id":          did,
            "label":       drive.get("label", did),
            "tags":        drive.get("tags", []),
            "intensity":   intensity,
            "urgency":     round(urgency, 4),
            "effective":   effective,
            "template_class": _template_class(urgency),
        })

    result.sort(key=lambda x: x["effective"], reverse=True)
    return result


def _template_class(urgency: float) -> str:
    """Map urgency level to voice template class."""
    if urgency >= ASSERT_THRESH:
        return "ASSERT"
    elif urgency >= WONDER_THRESH:
        return "WONDER"
    elif urgency <= REFLECT_THRESH:
        return "REFLECT"
    else:
        return "OBSERVE"


def get_top_drive(drives: list[dict], state: dict) -> dict | None:
    """Return the single highest-pressure drive. Used by voice layer."""
    pressures = get_effective_pressure(drives, state)
    return pressures[0] if pressures else None


# ── Full lifecycle cycle ──────────────────────────────────────────────────────

def run_drive_cycle(verbose: bool = False) -> dict:
    """
    Full drive lifecycle pass. Called each loop cycle from run.py.

    1. Load drives + urgency state
    2. Tick neglect (all drives get slightly more urgent)
    3. Auto-satisfy from recent DB beliefs
    4. Auto-spike from recent contradictions/gaps
    5. Save updated urgency state
    6. Return effective pressures

    Returns summary dict.
    """
    drives  = _load_drives()
    if not drives:
        log.warning("[drives] No drives loaded — check nex_drives.json")
        return {"drives_loaded": 0}

    state   = _load_urgency()
    state   = _init_urgency(drives, state)

    # Lifecycle steps
    state   = tick_neglect(drives, state)
    state   = auto_satisfy_from_db(drives, state)
    state   = auto_spike_from_db(drives, state)

    _save_urgency(state)

    pressures = get_effective_pressure(drives, state)

    if verbose:
        print(f"\n  {'DRIVE':<35} {'URGENCY':>8}  {'EFFECTIVE':>9}  {'TEMPLATE':<10}")
        print(f"  {'─'*35} {'─'*8}  {'─'*9}  {'─'*10}")
        for p in pressures:
            bar_w   = 12
            filled  = int(p["urgency"] * bar_w)
            bar     = "█" * filled + "░" * (bar_w - filled)
            print(
                f"  {p['label'][:35]:<35} "
                f"{bar}  "
                f"{p['urgency']:>5.3f}  "
                f"{p['effective']:>9.3f}  "
                f"{p['template_class']:<10}"
            )

    stats = {
        "drives_loaded":   len(drives),
        "urgency_state":   {did: round(s["urgency"], 3)
                            for did, s in state.items()},
        "top_drive":       pressures[0]["id"] if pressures else None,
        "top_template":    pressures[0]["template_class"] if pressures else None,
        "pressures":       pressures,
    }

    log.info(
        f"[drives] top={stats['top_drive']} "
        f"urgency={pressures[0]['urgency']:.3f} "
        f"template={stats['top_template']}"
    )
    return stats


# ── Public API (used by run.py and voice layer) ───────────────────────────────

def get_drive_state() -> dict:
    """
    Lightweight read — no tick, no DB queries.
    Returns current effective pressures for use by voice/template layer.
    """
    drives = _load_drives()
    state  = _load_urgency()
    state  = _init_urgency(drives, state)
    return {
        "pressures":   get_effective_pressure(drives, state),
        "top_drive":   get_top_drive(drives, state),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="NEX v1.0 — Drive Lifecycle (Build 5)"
    )
    ap.add_argument("--status",  action="store_true", help="Show current drive urgencies")
    ap.add_argument("--tick",    action="store_true", help="Run one neglect tick")
    ap.add_argument("--satisfy", type=str,            help="Mark drive ID as satisfied")
    ap.add_argument("--spike",   type=str,            help="Spike a drive (gap/contradiction)")
    ap.add_argument("--run",     action="store_true", help="Full lifecycle cycle")
    args = ap.parse_args()

    drives = _load_drives()
    if not drives:
        print(f"  No drives found at {DRIVES_PATH}")
        print("  Run nex_drives.py first to initialise drive state.")
        return

    state = _load_urgency()
    state = _init_urgency(drives, state)

    if args.satisfy:
        new_urg = satisfy_drive(args.satisfy, state)
        _save_urgency(state)
        print(f"  Drive '{args.satisfy}' satisfied → urgency now {new_urg:.3f}")
        return

    if args.spike:
        new_urg = spike_drive(args.spike, state)
        _save_urgency(state)
        print(f"  Drive '{args.spike}' spiked → urgency now {new_urg:.3f}")
        return

    if args.tick:
        state = tick_neglect(drives, state)
        _save_urgency(state)
        print("  Neglect tick applied.")

    if args.run:
        print("\nRunning drive lifecycle cycle ...\n")
        stats = run_drive_cycle(verbose=True)
        print(f"\n  Drives loaded:  {stats['drives_loaded']}")
        print(f"  Top drive:      {stats['top_drive']}")
        print(f"  Template class: {stats['top_template']}")
        print(f"\n[✓] Build 5 — drive lifecycle running.\n")
        return

    if args.status or not any([args.satisfy, args.spike, args.tick, args.run]):
        pressures = get_effective_pressure(drives, state)
        print(f"\n  {'DRIVE ID':<32} {'URGENCY':>8}  {'EFFECTIVE':>9}  {'CLASS':<10}")
        print(f"  {'─'*32} {'─'*8}  {'─'*9}  {'─'*10}")
        for p in pressures:
            bar_w  = 12
            filled = int(p["urgency"] * bar_w)
            bar    = "█" * filled + "░" * (bar_w - filled)
            print(
                f"  {p['id'][:32]:<32} "
                f"{bar}  "
                f"{p['urgency']:>5.3f}  "
                f"{p['effective']:>9.3f}  "
                f"{p['template_class']:<10}"
            )
        if pressures:
            print(f"\n  Top drive: {pressures[0]['id']}  "
                  f"(urgency={pressures[0]['urgency']:.3f}, "
                  f"template={pressures[0]['template_class']})")
        print()


if __name__ == "__main__":
    main()
