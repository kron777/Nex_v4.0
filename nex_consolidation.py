"""
nex_consolidation.py
NEX Phase 6: Consolidation Loop

Runs every N conversations. Reads the accumulated signal from
phases 1-5 and updates the belief graph accordingly.

This is the methodology's Consolidation Phase made operational:
  "Read Landing Fields as a separate pass. What patterns in what
   lands and what doesn't? What recipient states, timing conditions,
   format choices correlate with Integration Delta?"

Schedule: every 10 conversations (configurable).
Can also be run manually for immediate consolidation.

What it does:
  1. Reads belief_residue table — chronic residue patterns
  2. Reads residue_review table — boost/prune candidates
  3. Reads interlocutor_graphs table — ZPD and reception patterns
  4. Applies belief confidence adjustments via calibrator
  5. Writes consolidation report to DB
  6. Logs terrain audit — how has the problem space shifted?

Run manually:
  python3 ~/Desktop/nex/nex_consolidation.py

Or import and call run_consolidation() from a scheduler.
"""

import sqlite3
import json
import time
import logging
from pathlib import Path
from datetime import datetime

log     = logging.getLogger("nex.consolidation")
DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"

# Thresholds
CHRONIC_RESIDUE_THRESHOLD = 3   # appearances in residue before action
BOOST_MULTIPLIER          = 1.12  # confidence boost for boost candidates
CONSOLIDATION_INTERVAL    = 10   # conversations between consolidations
MIN_CONVERSATIONS_FOR_RUN = 5    # don't consolidate with too little data


def _conversation_count_since_last(db: sqlite3.Connection) -> int:
    """Count conversations since last consolidation."""
    try:
        last = db.execute("""
            SELECT MAX(timestamp) FROM consolidation_log
        """).fetchone()[0] or 0

        count = db.execute("""
            SELECT COUNT(DISTINCT session_id)
            FROM interlocutor_graphs
            WHERE updated_at > ?
        """, (last,)).fetchone()[0] or 0
        return count
    except Exception:
        return 0


def run_consolidation(force: bool = False) -> dict:
    """
    Main consolidation run.

    force=True: run regardless of conversation count.
    force=False: only run if enough conversations have accumulated.

    Returns consolidation report.
    """
    print("\n[CONSOLIDATION] Starting consolidation pass...")
    t0 = time.time()

    try:
        db = sqlite3.connect(str(DB_PATH), timeout=10)
        db.row_factory = sqlite3.Row

        # Check if enough data has accumulated
        if not force:
            conv_count = _conversation_count_since_last(db)
            if conv_count < MIN_CONVERSATIONS_FOR_RUN:
                db.close()
                print(f"[CONSOLIDATION] Skipped — only {conv_count} conversations "
                      f"since last run (need {MIN_CONVERSATIONS_FOR_RUN})")
                return {"skipped": True, "reason": f"only {conv_count} conversations"}

        report = {
            "timestamp":        time.time(),
            "datetime":         datetime.now().isoformat(),
            "belief_boosts":    [],
            "belief_flags":     [],
            "pattern_findings": [],
            "terrain_audit":    {},
            "actions_taken":    []
        }

        # ── PHASE A: Chronic residue analysis ────────────────────────────────
        print("[CONSOLIDATION] Phase A: chronic residue analysis...")
        try:
            from nex_delta_reinforcement import get_reinforcement_candidates
            candidates = get_reinforcement_candidates(n_sessions=50)

            boost_cands = candidates.get("boost_candidates", [])
            prune_cands = candidates.get("prune_candidates", [])

            # Boost beliefs that reliably activate in landing contexts
            # but don't reach utterance
            boosted = 0
            for cand in boost_cands[:10]:
                bid = cand["id"]
                old_conf = cand["confidence"]
                new_conf = min(0.97, old_conf * BOOST_MULTIPLIER)
                if new_conf > old_conf + 0.01:  # only if meaningful boost
                    db.execute(
                        "UPDATE beliefs SET confidence=? WHERE id=?",
                        (new_conf, bid)
                    )
                    report["belief_boosts"].append({
                        "id":      bid,
                        "content": cand["content"],
                        "old":     round(old_conf, 3),
                        "new":     round(new_conf, 3),
                        "reason":  f"chronic residue x{cand['residue_count']} "
                                   f"with {cand['with_delta']} delta events"
                    })
                    boosted += 1

            # Flag prune candidates — don't delete, just lower confidence
            flagged = 0
            for cand in prune_cands[:5]:
                bid = cand["id"]
                old_conf = cand["confidence"]
                # Soft reduction — 5% — flagged not deleted
                new_conf = max(0.50, old_conf * 0.95)
                if new_conf < old_conf - 0.01:
                    db.execute(
                        "UPDATE beliefs SET confidence=? WHERE id=?",
                        (new_conf, bid)
                    )
                    report["belief_flags"].append({
                        "id":      bid,
                        "content": cand["content"],
                        "old":     round(old_conf, 3),
                        "new":     round(new_conf, 3),
                        "reason":  "chronic residue, no landing signal"
                    })
                    flagged += 1

            report["actions_taken"].append(
                f"Phase A: {boosted} beliefs boosted, {flagged} beliefs flagged"
            )
            print(f"[CONSOLIDATION] Phase A: {boosted} boosted, {flagged} flagged")

        except Exception as e:
            print(f"[CONSOLIDATION] Phase A error: {e}")

        # ── PHASE B: Landing pattern analysis ────────────────────────────────
        print("[CONSOLIDATION] Phase B: landing pattern analysis...")
        try:
            # Read interlocutor graphs for ZPD and reception patterns
            graphs = db.execute("""
                SELECT state_json FROM interlocutor_graphs
                ORDER BY updated_at DESC LIMIT 50
            """).fetchall()

            zpd_counts   = {}
            mode_counts  = {}
            delta_counts = {"strong": 0, "moderate": 0, "none": 0}

            for row in graphs:
                try:
                    state = json.loads(row[0])
                    zpd = state.get("current_zpd", "")
                    mode = state.get("dominant_reception_mode", "")
                    deltas = state.get("integration_deltas", [])

                    if zpd:
                        zpd_counts[zpd] = zpd_counts.get(zpd, 0) + 1
                    if mode:
                        mode_counts[mode] = mode_counts.get(mode, 0) + 1
                    for d in deltas:
                        s = d.get("strength", "none")
                        delta_counts[s] = delta_counts.get(s, 0) + 1
                except Exception:
                    continue

            # Find dominant ZPD and reception mode
            dominant_zpd  = max(zpd_counts, key=zpd_counts.get) if zpd_counts else "unknown"
            dominant_mode = max(mode_counts, key=mode_counts.get) if mode_counts else "unknown"
            total_deltas  = sum(delta_counts.values())
            landing_rate  = (
                (delta_counts.get("strong", 0) + delta_counts.get("moderate", 0))
                / max(total_deltas, 1)
            )

            pattern = {
                "dominant_zpd":    dominant_zpd,
                "dominant_mode":   dominant_mode,
                "landing_rate":    round(landing_rate, 3),
                "delta_breakdown": delta_counts,
                "graphs_analysed": len(graphs)
            }
            report["pattern_findings"].append(pattern)
            print(f"[CONSOLIDATION] Phase B: landing_rate={landing_rate:.1%}, "
                  f"ZPD={dominant_zpd}, mode={dominant_mode}")

        except Exception as e:
            print(f"[CONSOLIDATION] Phase B error: {e}")

        # ── PHASE C: Terrain audit ────────────────────────────────────────────
        print("[CONSOLIDATION] Phase C: terrain audit...")
        try:
            # What topics are being asked about most?
            # What topics are producing the most/least landing?
            # session_history columns: id, session_id, role, content, ts
            # No intent column — use content keywords as proxy for topic
            topic_rows = db.execute("""
                SELECT session_id, COUNT(*) as count
                FROM session_history
                WHERE role='user'
                AND ts > ?
                GROUP BY session_id
                ORDER BY count DESC
                LIMIT 10
            """, (str(int(time.time() - 7 * 24 * 3600)),)).fetchall()

            active_topics = [(r[0][:30] if r[0] else 'unknown', r[1])
                             for r in topic_rows if r[0]]

            # What beliefs have been activated most recently?
            # (proxy: which beliefs appear in recent residue)
            recent_residue = db.execute("""
                SELECT residue_json FROM belief_residue
                ORDER BY timestamp DESC LIMIT 20
            """).fetchall()

            hot_beliefs = {}
            for row in recent_residue:
                try:
                    items = json.loads(row[0])
                    for item in items:
                        key = item["content"][:60]
                        hot_beliefs[key] = hot_beliefs.get(key, 0) + 1
                except Exception:
                    continue

            top_hot = sorted(hot_beliefs.items(), key=lambda x: x[1], reverse=True)[:5]

            report["terrain_audit"] = {
                "active_topics":    active_topics[:5],
                "hot_beliefs":      top_hot,
                "interpretation":   (
                    "These are the territories NEX is currently operating in most. "
                    "Phase 4 IFR targets should be weighted toward these domains. "
                    "Belief growth should prioritise hot_belief territories."
                )
            }
            print(f"[CONSOLIDATION] Phase C: {len(active_topics)} active topics, "
                  f"{len(top_hot)} hot beliefs identified")

        except Exception as e:
            print(f"[CONSOLIDATION] Phase C error: {e}")

        # ── LOG AND COMMIT ────────────────────────────────────────────────────
        db.commit()

        # Write consolidation log
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS consolidation_log (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    report    TEXT
                )
            """)
            db.execute(
                "INSERT INTO consolidation_log (timestamp, report) VALUES (?,?)",
                (time.time(), json.dumps(report))
            )
            db.commit()
        except Exception as e:
            print(f"[CONSOLIDATION] log error: {e}")

        db.close()

        report["latency_s"] = round(time.time() - t0, 2)
        print(f"\n[CONSOLIDATION] Complete in {report['latency_s']}s")
        print(f"[CONSOLIDATION] Actions: {report['actions_taken']}")
        return report

    except Exception as e:
        print(f"[CONSOLIDATION] Fatal error: {e}")
        return {"error": str(e)}


def should_consolidate(db_path=DB_PATH) -> bool:
    """
    Quick check: has enough accumulated since last consolidation?
    Called by nex_api.py on each chat request — lightweight.
    """
    try:
        db = sqlite3.connect(str(db_path), timeout=3)
        count = _conversation_count_since_last(db)
        db.close()
        return count >= CONSOLIDATION_INTERVAL
    except Exception:
        return False


def get_last_report(db_path=DB_PATH) -> dict:
    """Return the most recent consolidation report."""
    try:
        db = sqlite3.connect(str(db_path), timeout=3)
        row = db.execute("""
            SELECT report FROM consolidation_log
            ORDER BY timestamp DESC LIMIT 1
        """).fetchone()
        db.close()
        if row:
            return json.loads(row[0])
        return {"message": "No consolidation run yet"}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    report = run_consolidation(force=force)
    print("\n=== CONSOLIDATION REPORT ===")
    print(json.dumps(report, indent=2, default=str))
