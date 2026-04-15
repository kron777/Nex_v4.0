#!/usr/bin/env python3
"""
nex_terrain_audit.py — U9 Terrain Audit Protocol
=================================================
Reads thrownet_log.jsonl every 5 runs and produces a structured audit
of how the problem space has shifted. This is the V12 precondition.

Not "what should we build next" — "how has the landscape changed,
and what does that make possible or necessary?"

Usage:
    python3 nex_terrain_audit.py
    python3 nex_terrain_audit.py --force  # run regardless of run count
"""
import json, sqlite3, datetime, argparse
from pathlib import Path

TERRAIN_LOG  = Path.home() / "Desktop" / "thrownet_log.jsonl"
AUDIT_LOG    = Path.home() / "Desktop" / "terrain_audit_log.jsonl"
DB_PATH      = Path("/media/rr/NEX/nex_core/nex.db")
AUDIT_EVERY  = 5   # runs between audits


def load_terrain_log():
    if not TERRAIN_LOG.exists():
        return []
    entries = []
    with open(TERRAIN_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
    return entries


def load_audit_log():
    if not AUDIT_LOG.exists():
        return []
    entries = []
    with open(AUDIT_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
    return entries


def should_run(entries, force=False):
    if force:
        return True
    audits = load_audit_log()
    last_audited_run = audits[-1].get("run_count", 0) if audits else 0
    return len(entries) >= last_audited_run + AUDIT_EVERY


def read_live_state():
    state = {}
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=3)
        state["beliefs_total"]   = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        state["beliefs_locked"]  = db.execute("SELECT COUNT(*) FROM beliefs WHERE locked=1").fetchone()[0]
        state["beliefs_high"]    = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence>0.7").fetchone()[0]
        state["tensions"]        = db.execute("SELECT COUNT(*) FROM tensions WHERE resolved=0").fetchone()[0]
        state["wisdom_count"]    = db.execute("SELECT COUNT(*) FROM nex_wisdom").fetchone()[0]
        state["residue_total"]   = db.execute("SELECT COUNT(*) FROM nex_residue").fetchone()[0]
        state["interlocutor_sessions"] = db.execute(
            "SELECT COUNT(*) FROM interlocutor_graphs WHERE turn_count > 0"
        ).fetchone()[0]
        state["intentions_active"] = db.execute(
            "SELECT COUNT(*) FROM nex_intentions WHERE completed=0"
        ).fetchone()[0]
        # Top 5 new high-confidence beliefs
        state["new_high_conf"] = [
            r[0] for r in db.execute(
                "SELECT content FROM beliefs WHERE confidence > 0.85 "
                "ORDER BY rowid DESC LIMIT 5"
            ).fetchall()
        ]
        db.close()
    except Exception as e:
        state["error"] = str(e)
    return state


def compute_trajectory(entries):
    """Read arc of immediate upgrades — what kept appearing vs what resolved."""
    if len(entries) < 2:
        return {}

    # Count how many times each upgrade appeared in immediate list
    frequency = {}
    for e in entries:
        for u in e.get("upgrades_immediate", []):
            frequency[u] = frequency.get(u, 0) + 1

    # Belief trajectory
    beliefs = [e.get("belief_count", 0) for e in entries if e.get("belief_count")]
    tensions = [e.get("tensions", 0) for e in entries if e.get("tensions")]

    first, last = entries[0], entries[-1]
    belief_delta   = last.get("belief_count", 0) - first.get("belief_count", 0)
    tension_delta  = last.get("tensions", 0) - first.get("tensions", 0)

    # Phase detection
    recent_immediate = entries[-3:]
    all_empty = all(not e.get("upgrades_immediate") for e in recent_immediate)
    phase = "plateau — no immediate items" if all_empty else "active — immediate items present"

    # Rapid gain detection
    if len(beliefs) >= 3:
        recent_growth = beliefs[-1] - beliefs[-3]
        phase_detail = f"rapid-gain (+{recent_growth})" if recent_growth > 50 else "steady"
    else:
        phase_detail = "insufficient data"

    return {
        "belief_delta":    belief_delta,
        "tension_delta":   tension_delta,
        "upgrade_freq":    frequency,
        "phase":           phase,
        "phase_detail":    phase_detail,
        "runs_analysed":   len(entries),
        "first_ts":        first.get("ts"),
        "last_ts":         last.get("ts"),
    }


def what_opened(traj, live):
    """What became possible that wasn't before."""
    opened = []
    if traj.get("tension_delta", 0) < 0:
        opened.append(f"Tension resolution active — {abs(traj['tension_delta'])} resolved since first run")
    if live.get("wisdom_count", 0) > 0:
        opened.append(f"Wisdom distillation live — {live['wisdom_count']} principles extracted")
    if live.get("residue_total", 0) > 0:
        opened.append(f"Recurrent reasoning possible — {live['residue_total']} residue entries")
    if live.get("interlocutor_sessions", 0) >= 3:
        opened.append(f"Co-construction possible — {live['interlocutor_sessions']} interlocutor graphs")
    if not traj.get("upgrade_freq"):
        opened.append("Immediate list clear — architecture entering consolidation phase")
    return opened


def what_closed(traj):
    """What is no longer the frontier."""
    closed = []
    freq = traj.get("upgrade_freq", {})
    # Upgrades that appeared early but stopped appearing
    if "U1" in freq and freq["U1"] <= 2:
        closed.append("U1 tension wiring — resolved and no longer surfacing")
    if "U2" in freq and freq["U2"] <= 2:
        closed.append("U2 internet belief — quarantined")
    if "U3" in freq and freq["U3"] <= 3:
        closed.append("U3 residue capture — built, now landing")
    return closed


def format_audit(traj, live, entries):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L = []
    w = lambda s="": L.append(s)
    hr = lambda: L.append("═" * 72)

    hr()
    w(f"  NEX TERRAIN AUDIT")
    w(f"  Generated: {ts}")
    w(f"  Runs analysed: {traj['runs_analysed']} ({traj['first_ts']} → {traj['last_ts']})")
    hr()
    w()

    w("  BELIEF TRAJECTORY")
    w(f"    Total delta:    {'+' if traj['belief_delta'] >= 0 else ''}{traj['belief_delta']} beliefs")
    w(f"    Tension delta:  {'+' if traj['tension_delta'] >= 0 else ''}{traj['tension_delta']} unresolved")
    w(f"    Phase:          {traj['phase']}")
    w(f"    Growth rate:    {traj['phase_detail']}")
    w()

    w("  UPGRADE FREQUENCY (how many runs each appeared as immediate)")
    for u, count in sorted(traj["upgrade_freq"].items(), key=lambda x: -x[1]):
        bar = "█" * count
        w(f"    {u:<6} {bar} ({count})")
    if not traj["upgrade_freq"]:
        w("    No upgrades appeared as immediate — immediate list was empty throughout")
    w()

    w("  WHAT OPENED (new territory since first run)")
    opened = what_opened(traj, live)
    for o in opened:
        w(f"    + {o}")
    if not opened:
        w("    Nothing new — terrain stable")
    w()

    w("  WHAT CLOSED (no longer the frontier)")
    closed_items = what_closed(traj)
    for c in closed_items:
        w(f"    ✓ {c}")
    if not closed_items:
        w("    Nothing closed yet — all prior frontiers still active")
    w()

    w("  LIVE STATE (what this run is entering)")
    w(f"    beliefs_total:          {live.get('beliefs_total','?')}")
    w(f"    beliefs_high_conf:      {live.get('beliefs_high','?')}")
    w(f"    tensions_unresolved:    {live.get('tensions','?')}")
    w(f"    wisdom_principles:      {live.get('wisdom_count','?')}")
    w(f"    residue_entries:        {live.get('residue_total','?')}")
    w(f"    interlocutor_sessions:  {live.get('interlocutor_sessions','?')}")
    w(f"    intentions_active:      {live.get('intentions_active','?')}")
    w()

    w("  TOP 5 NEW HIGH-CONFIDENCE BELIEFS")
    for b in live.get("new_high_conf", []):
        w(f"    • {b[:90]}")
    w()

    w("  V12 READINESS")
    v12_conditions = [
        ("5+ runs logged",            traj["runs_analysed"] >= 5),
        ("Terrain delta non-zero",    traj["belief_delta"] != 0 or traj["tension_delta"] != 0),
        ("Residue accumulating",      live.get("residue_total", 0) > 0),
        ("Wisdom distilling",         live.get("wisdom_count", 0) > 0),
        ("Interlocutor graphs live",  live.get("interlocutor_sessions", 0) >= 3),
        ("Immediate list clearing",   not any(e.get("upgrades_immediate") for e in entries[-3:])),
    ]
    met = sum(1 for _, c in v12_conditions if c)
    for label, condition in v12_conditions:
        w(f"    {'✓' if condition else '✗'}  {label}")
    w()
    w(f"  V12 readiness: {met}/{len(v12_conditions)}")
    if met == len(v12_conditions):
        w("  *** V12 TRIGGER CONDITIONS MET — next thrownet run may produce V12 recognition ***")
    w()
    hr()
    return "\n".join(L)


def run_audit(force=False, verbose=True):
    entries = load_terrain_log()
    if not entries:
        print("[terrain_audit] No terrain log found")
        return 0

    if not should_run(entries, force):
        remaining = AUDIT_EVERY - (len(entries) % AUDIT_EVERY)
        if verbose:
            print(f"[terrain_audit] {remaining} more runs needed before next audit")
        return 0

    traj = compute_trajectory(entries)
    live = read_live_state()

    output = format_audit(traj, live, entries)
    if verbose:
        print(output)

    # Save audit
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path.home() / "Desktop" / f"terrain_{ts}.txt"
    out_path.write_text(output)
    print(f"[terrain_audit] → {out_path}")

    # Append to audit log
    audit_entry = {
        "ts":           ts,
        "run_count":    len(entries),
        "belief_delta": traj["belief_delta"],
        "tension_delta":traj["tension_delta"],
        "phase":        traj["phase"],
        "v12_met":      traj["runs_analysed"] >= 5 and live.get("residue_total",0) > 0,
    }
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(audit_entry) + "\n")

    return 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    run_audit(force=args.force, verbose=True)
