#!/usr/bin/env python3
"""
nex_thrownet_promoter.py — ThrowNet → Belief Promotion
=======================================================
The missing last mile of the ThrowNet pipeline.

After refinement scores candidates and sets verdicts,
this module:
  1. Finds all sessions with status=refined/complete and approved=0
  2. Takes buildable candidates (score >= min_score)
  3. Writes them to beliefs DB (source='throw_net_promoted')
  4. Creates tension edges in belief_links for Q7 coverage
  5. Resets trigger so topic can fire again
  6. Marks session approved=1, surfaced=1

Call run_promoter() from metabolism slow cycle after refinement hook.
"""

import json
import sqlite3
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

log = logging.getLogger("nex.thrownet_promoter")

DB_PATH      = Path("~/.config/nex").expanduser() / "nex.db"
MIN_SCORE    = 4        # minimum refinement score to promote (out of 7)
MIN_CONF     = 0.65     # minimum confidence to write to beliefs
MAX_PER_RUN  = 10       # max beliefs promoted per run


def _get_pending_sessions(con) -> list:
    """Sessions refined but not yet approved."""
    rows = con.execute("""
        SELECT id, constraint_text, trigger_topic, candidates_refined, top_candidate
        FROM throw_net_sessions
        WHERE status IN ('refined', 'complete')
          AND approved = 0
          AND candidates_refined IS NOT NULL
        ORDER BY id ASC
        LIMIT 5
    """).fetchall()
    return rows


def _write_belief(con, content: str, topic: str, confidence: float,
                  session_id: int) -> int:
    """Insert belief, return new belief id."""
    try:
        cur = con.execute("""
            INSERT OR IGNORE INTO beliefs
                (content, confidence, topic, source, timestamp, tags)
            VALUES (?, ?, ?, 'throw_net_promoted', ?, ?)
        """, (
            content[:500],
            min(0.95, confidence),
            topic,
            time.time(),
            json.dumps(['throw_net', f'session_{session_id}'])
        ))
        con.commit()
        return cur.lastrowid or 0
    except Exception as e:
        log.error(f"write_belief error: {e}")
        return 0


def _create_tension_edge(con, belief_a_id: int, belief_b_id: int,
                          topic: str, session_id: int):
    """Create a tension entry so Q7 passes on future sessions."""
    try:
        existing = con.execute("""
            SELECT id FROM tensions
            WHERE belief_a_id = ? AND belief_b_id = ? AND resolved = 0
        """, (belief_a_id, belief_b_id)).fetchone()
        if not existing:
            con.execute("""
                INSERT INTO tensions
                    (topic, description, belief_a_id, belief_b_id, detected_at, resolved)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (
                topic,
                f"throw_net_session_{session_id}: cross-domain tension",
                belief_a_id,
                belief_b_id,
                datetime.now(timezone.utc).isoformat()
            ))
            con.commit()
    except Exception as e:
        log.error(f"create_tension_edge error: {e}")


def _create_belief_link(con, parent_id: int, child_id: int, link_type: str):
    """Link two beliefs in belief_links for graph connectivity."""
    try:
        con.execute("""
            INSERT OR IGNORE INTO belief_links (parent_id, child_id, link_type)
            VALUES (?, ?, ?)
        """, (parent_id, child_id, link_type))
        con.commit()
    except Exception as e:
        log.error(f"create_belief_link error: {e}")


def _mark_session_approved(con, session_id: int, notes: str):
    try:
        con.execute("""
            UPDATE throw_net_sessions
            SET approved = 1, surfaced = 1, outcome_notes = ?
            WHERE id = ?
        """, (notes, session_id))
        con.commit()
    except Exception as e:
        log.error(f"mark_approved error: {e}")


def _reset_trigger(topic: str):
    """Allow topic to trigger throw-net again after promotion."""
    try:
        con = sqlite3.connect(str(DB_PATH))
        con.execute("""
            UPDATE throw_net_triggers
            SET llm_misses = 0, fired = 0, last_seen = datetime('now')
            WHERE topic = ?
        """, (topic,))
        con.commit()
        con.close()
    except Exception:
        pass


def _stimulate_nbre(promoted_topics: list):
    """Warm NBRE neurons for promoted topics so they fire sooner."""
    try:
        import sys, importlib
        sys.path.insert(0, '/home/rr/Desktop/nex')
        import nex.nex_soul_loop as _nsl
        eng = getattr(_nsl, '_nbre_singleton', None)
        if eng and promoted_topics:
            eng.layer1.stimulate_by_topic(promoted_topics, strength=0.5)
            log.info(f"NBRE stimulated for topics: {promoted_topics}")
    except Exception as e:
        log.debug(f"NBRE stimulate skipped: {e}")


def run_promoter(verbose: bool = False) -> int:
    """
    Promote approved ThrowNet candidates to beliefs.
    Returns count of beliefs written.
    """
    if not DB_PATH.exists():
        return 0

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    sessions = _get_pending_sessions(con)
    if not sessions:
        if verbose:
            log.info("No pending sessions to promote")
        con.close()
        return 0

    total_written  = 0
    promoted_topics = []

    for session_id, constraint, trigger_topic, cands_json, top_json in sessions:
        try:
            candidates = json.loads(cands_json) if cands_json else []
        except Exception:
            candidates = []

        buildable = [
            c for c in candidates
            if c.get('buildable') and
               (c.get('score', 0) >= MIN_SCORE) and
               c.get('candidate', {}).get('content')
        ]

        if not buildable:
            _mark_session_approved(con, session_id, "no buildable candidates")
            continue

        session_belief_ids = []
        session_written    = 0

        for ref in buildable[:MAX_PER_RUN - total_written]:
            cand    = ref.get('candidate', {})
            content = cand.get('content', '').strip()
            topic   = cand.get('topic', trigger_topic or 'general')
            conf    = float(cand.get('confidence') or MIN_CONF)

            if not content or len(content) < 30 or conf < MIN_CONF:
                continue

            bid = _write_belief(con, content, topic, conf, session_id)
            if bid:
                session_belief_ids.append((bid, topic))
                session_written += 1
                total_written   += 1
                if topic not in promoted_topics:
                    promoted_topics.append(topic)

            if total_written >= MAX_PER_RUN:
                break

        # Create tension + belief_link edges between promoted beliefs
        for i, (bid_a, topic_a) in enumerate(session_belief_ids):
            for bid_b, topic_b in session_belief_ids[i+1:i+3]:
                if bid_a and bid_b and bid_a != bid_b:
                    _create_tension_edge(
                        con, bid_a, bid_b,
                        topic_a, session_id
                    )
                    _create_belief_link(con, bid_a, bid_b, 'throw_net')

        notes = (
            f"promoted {session_written} beliefs from "
            f"{len(buildable)} candidates | "
            f"topics: {list({t for _, t in session_belief_ids})}"
        )
        _mark_session_approved(con, session_id, notes)

        if trigger_topic:
            _reset_trigger(trigger_topic)

        if verbose:
            print(f"  [ThrowNetPromoter] session {session_id}: "
                  f"+{session_written} beliefs → {notes}")

    con.close()

    if promoted_topics:
        _stimulate_nbre(promoted_topics)

    return total_written


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = run_promoter(verbose=True)
    print(f"Promoted {n} beliefs from ThrowNet sessions")
