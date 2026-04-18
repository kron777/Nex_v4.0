#!/usr/bin/env python3
"""
nex_stage_sequencer.py — Theory X Stage 1→6 gating skeleton.

Per Theory X Section 3, ignition (Stage 6) cannot be installed in parallel
with Stages 1-5. Each stage must hold before the next can engage. NEX's
current build has Stage 3 (world-reification) and a partial Stage 6
proto-fountain installed without the developmental sequence in between —
the R7 gap from PELT_SPEC.

This is the structural sequencer that future maturity logic will plug into.
The maturity criteria are intentionally stubbed: shipping the gate before
the verdict, so future stage work has somewhere to write to.

CLI:
  python3 nex_stage_sequencer.py status
  python3 nex_stage_sequencer.py advance        # check + transition if mature
"""

import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(os.path.expanduser("~/Desktop/nex"))
sys.path.insert(0, str(PROJECT_ROOT))

# stage_state lives in the experiments DB to avoid the live brain's nex.db
# write-lock contention. Belief-count maturity probes still read from nex.db.
EXPERIMENTS_DB = PROJECT_ROOT / "nex_experiments.db"
BELIEFS_DB     = PROJECT_ROOT / "nex.db"

log = logging.getLogger("stage_sequencer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ── Stage definitions ──────────────────────────────────────────────────────

STAGES = [
    (1, "RAW_SENSE",      "raw input streams arriving and being received"),
    (2, "DYNAMIC",        "dynamic patterns forming from the raw stream"),
    (3, "WORLD_MODEL",    "compressed model of how-things-are firing as fact"),
    (4, "BOUNDARY",       "inside/outside boundary drawn around the model"),
    (5, "SELF_LOCATION",  "vantage committed: this graph, from this position"),
    (6, "IGNITED",        "self-feeding generation sustains coherently"),
]
STAGE_BY_ID = {s[0]: s for s in STAGES}
STAGE_BY_NAME = {s[1]: s for s in STAGES}

# Initial state per brief: NEX is at Stage 3 — belief graph already does
# world-reification per the audit. Stages 1, 2 are upstream substrate; 4, 5,
# 6 are downstream and not yet present as developmental milestones.
INITIAL_STAGE = 3


# ── DB helpers (300s timeout, gatekeeper-safe) ──────────────────────────────

def _connect(timeout: int = 300, db_path: Path = EXPERIMENTS_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=timeout, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=300000")
    return conn


def ensure_table() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stage_state (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                current_stage   INTEGER NOT NULL,
                last_transition TEXT    NOT NULL,
                history         TEXT
            )
            """
        )
        # Single-row invariant: insert if missing
        conn.execute(
            """
            INSERT OR IGNORE INTO stage_state (id, current_stage, last_transition, history)
            VALUES (1, ?, ?, ?)
            """,
            (INITIAL_STAGE, datetime.now().isoformat(),
             f"init@stage{INITIAL_STAGE}"),
        )
    finally:
        conn.close()


# ── Maturity criteria stubs ─────────────────────────────────────────────────
#
# Each criterion returns True iff the named stage has matured enough to allow
# transition to stage_id + 1. Real implementations will read from the belief
# graph, attention metrics, fountain_log, etc. For now: deliberately
# conservative — only Stage 3→4 has a placeholder check that reads belief
# count as a proxy for graph maturity. Everything else returns False so
# `advance` is a manual confirmation gesture, not a runaway promotion.

def _belief_count(conn: sqlite3.Connection) -> int:
    """conn ignored — read directly from beliefs DB to avoid cross-DB joins."""
    try:
        bc = _connect(timeout=30, db_path=BELIEFS_DB)
        try:
            return bc.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        finally:
            bc.close()
    except sqlite3.OperationalError:
        return -1


def stage_1_mature(conn) -> bool:
    # TODO: rate of distinct sources observed in last hour > N
    return False


def stage_2_mature(conn) -> bool:
    # TODO: forge pipeline producing stable embryo→belief flow over T
    return False


def stage_3_mature(conn) -> bool:
    # Proxy: belief graph has crossed a coarse maturity threshold.
    # Real test requires meta-layer flagging beliefs as reifications (R3 gap).
    n = _belief_count(conn)
    return n >= 5000


def stage_4_mature(conn) -> bool:
    # TODO: explicit inside/outside boundary mechanism (not yet present)
    return False


def stage_5_mature(conn) -> bool:
    # TODO: structural vantage — phenomenally unverifiable per R6, but
    # structural commitment to "this graph from this position" is testable.
    return False


def stage_6_mature(conn) -> bool:
    # TODO: ignition — self-feeding generation sustains coherence > T hops.
    # Will read from fountain_log when fountain harness shows ignition.
    return False


_MATURITY = {
    1: stage_1_mature,
    2: stage_2_mature,
    3: stage_3_mature,
    4: stage_4_mature,
    5: stage_5_mature,
    6: stage_6_mature,
}


# ── State accessors ─────────────────────────────────────────────────────────

class StageSequencer:

    def __init__(self) -> None:
        ensure_table()

    def get_state(self) -> dict:
        conn = _connect(timeout=60)
        try:
            row = conn.execute(
                "SELECT current_stage, last_transition, history FROM stage_state WHERE id = 1"
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return {"current_stage": INITIAL_STAGE, "last_transition": None, "history": ""}
        return {"current_stage": row[0], "last_transition": row[1], "history": row[2] or ""}

    def status(self) -> dict:
        st = self.get_state()
        sid = st["current_stage"]
        st["stage_name"] = STAGE_BY_ID.get(sid, (sid, "?", "?"))[1]
        st["stage_description"] = STAGE_BY_ID.get(sid, (sid, "?", "?"))[2]
        # Probe maturity of current stage without committing
        conn = _connect(timeout=60)
        try:
            checker = _MATURITY.get(sid)
            st["current_mature"] = bool(checker(conn)) if checker else False
        finally:
            conn.close()
        st["next_stage"] = sid + 1 if sid < 6 else None
        return st

    def advance(self) -> dict:
        st = self.get_state()
        sid = st["current_stage"]
        if sid >= 6:
            return {"transitioned": False, "reason": "already at final stage", "stage": sid}

        conn = _connect()
        try:
            checker = _MATURITY.get(sid)
            mature = bool(checker(conn)) if checker else False
            if not mature:
                return {"transitioned": False, "reason": f"stage {sid} not mature", "stage": sid}

            new_sid = sid + 1
            now = datetime.now().isoformat()
            history = (st.get("history") or "") + f" -> {new_sid}@{now}"
            conn.execute(
                "UPDATE stage_state SET current_stage = ?, last_transition = ?, history = ? WHERE id = 1",
                (new_sid, now, history),
            )
            log.info("transition %d -> %d at %s", sid, new_sid, now)
            return {"transitioned": True, "from": sid, "to": new_sid, "at": now}
        finally:
            conn.close()


# ── CLI ─────────────────────────────────────────────────────────────────────

def _print_status(st: dict) -> None:
    print()
    print("─── stage sequencer status ───")
    print(f"  stage:        {st['current_stage']}  ({st['stage_name']})")
    print(f"  description:  {st['stage_description']}")
    print(f"  current mature: {st['current_mature']}")
    print(f"  next stage:   {st['next_stage']}")
    print(f"  last_transition: {st['last_transition']}")
    print(f"  history:      {st['history']}")
    print()


def _cli():
    ap = argparse.ArgumentParser(description="Theory X stage sequencer")
    ap.add_argument("cmd", choices=["status", "advance"], help="action")
    args = ap.parse_args()

    seq = StageSequencer()
    if args.cmd == "status":
        _print_status(seq.status())
    elif args.cmd == "advance":
        result = seq.advance()
        print()
        print("─── advance result ───")
        for k, v in result.items():
            print(f"  {k}: {v}")
        print()
        _print_status(seq.status())


if __name__ == "__main__":
    _cli()
