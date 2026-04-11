"""
nex_delta_reinforcement.py
NEX Phase 5: Integration Delta → Belief Reinforcement

The feedback loop that makes NEX self-improving from conversations.

When something lands (integration delta detected in interlocutor graph):
  → beliefs that were in the utterance get a confidence boost
  → via nex_belief_calibrator.record_usage(ids, quality_score)

When nothing lands (no delta, or resistance):
  → beliefs in residue get flagged for consolidation review
  → no confidence penalty (yet) — just accumulation of signal

When resistance is detected:
  → beliefs met but didn't dissolve resistance
  → moderate quality score — they're doing work, just hard work

Over time: beliefs that reliably produce landing strengthen.
Beliefs that reliably produce residue get reviewed in consolidation.
NEX gets better from her own conversations without fine-tuning.

This is the methodology's Integration Delta made operational.
"""

import sqlite3
import json
import time
import logging
from pathlib import Path
from typing import Optional

log     = logging.getLogger("nex.delta_reinforce")
DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"

# Quality score mapping from delta signal to calibrator input
# calibrator expects 0.0-2.0 where 1.0 = neutral, >1.0 = boost
DELTA_QUALITY_MAP = {
    "strong":   1.35,   # explicit ack + register shift — strong landing
    "moderate": 1.18,   # single delta signal — moderate landing
    "none":     0.95,   # no landing signal — slight downward pressure
    "resistant": 1.08,  # resistance detected — belief is working, hard work
}

# Minimum gap between reinforcement events for same belief (seconds)
# Prevents runaway boosting from rapid-fire exchanges
MIN_REINFORCE_INTERVAL = 300  # 5 minutes

# Track last reinforcement time per belief_id (in-memory)
_last_reinforced: dict = {}


def reinforce_from_delta(
    session_id: str,
    utterance_belief_ids: list,
    residue_belief_ids: list,
    delta: dict,
    resistance_level: str = "none"
) -> dict:
    """
    Main interface. Called after each conversation turn where
    the interlocutor graph has produced a delta reading.

    utterance_belief_ids: belief IDs that made it into the response
    residue_belief_ids:   belief IDs that activated but didn't reach utterance
    delta:                integration delta dict from InterlocutorGraph
    resistance_level:     from InterlocutorGraph current_resistance

    Returns reinforcement report.
    """
    if not utterance_belief_ids and not residue_belief_ids:
        return {"reinforced": 0, "flagged": 0, "skipped": "no beliefs"}

    delta_strength = delta.get("strength", "none") if delta.get("delta_detected") else "none"

    # Map resistance into quality
    if resistance_level in ["high", "medium"] and delta_strength != "none":
        quality_score = DELTA_QUALITY_MAP["resistant"]
    else:
        quality_score = DELTA_QUALITY_MAP.get(delta_strength, 1.0)

    now = time.time()

    # Filter out recently reinforced beliefs to prevent runaway boosting
    eligible_ids = [
        bid for bid in utterance_belief_ids
        if (now - _last_reinforced.get(bid, 0)) > MIN_REINFORCE_INTERVAL
    ]

    reinforced = 0
    if eligible_ids and quality_score > 1.0:
        try:
            from nex_belief_calibrator import record_usage
            record_usage(eligible_ids, quality_score)
            reinforced = len(eligible_ids)
            # Update last reinforced timestamps
            for bid in eligible_ids:
                _last_reinforced[bid] = now
            print(f"  [DELTA] Reinforced {reinforced} beliefs "
                  f"(quality={quality_score:.2f}, "
                  f"delta={delta_strength}, "
                  f"resistance={resistance_level})")
        except Exception as e:
            print(f"  [DELTA] calibrator error: {e}")

    elif eligible_ids and quality_score <= 0.95:
        # Soft downward signal — record usage with low quality
        # Let calibrator handle the math
        try:
            from nex_belief_calibrator import record_usage
            record_usage(eligible_ids[:3], quality_score)  # only top 3
            print(f"  [DELTA] Low-quality signal: {len(eligible_ids[:3])} beliefs "
                  f"(quality={quality_score:.2f})")
        except Exception as e:
            pass

    # Flag residue beliefs for consolidation review
    flagged = 0
    if residue_belief_ids:
        flagged = _flag_residue_for_review(
            session_id, residue_belief_ids, delta_strength, resistance_level
        )

    return {
        "reinforced":    reinforced,
        "flagged":       flagged,
        "quality_score": quality_score,
        "delta_strength": delta_strength,
        "resistance":    resistance_level
    }


def _flag_residue_for_review(
    session_id: str,
    residue_ids: list,
    delta_strength: str,
    resistance_level: str
) -> int:
    """
    Records residue belief IDs as candidates for consolidation review.
    Beliefs that consistently appear in residue across many sessions
    need attention — either boost their weight in the compiler or
    review their content for relevance.
    """
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)
        db.execute("""
            CREATE TABLE IF NOT EXISTS residue_review (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    TEXT,
                belief_id     INTEGER,
                delta_strength TEXT,
                resistance    TEXT,
                timestamp     REAL
            )
        """)
        now = time.time()
        for bid in residue_ids[:6]:  # cap at 6 per turn
            db.execute("""
                INSERT INTO residue_review
                (session_id, belief_id, delta_strength, resistance, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, bid, delta_strength, resistance_level, now))
        db.commit()
        db.close()
        return len(residue_ids[:6])
    except Exception as e:
        print(f"  [DELTA] flag error: {e}")
        return 0


def get_reinforcement_candidates(n_sessions: int = 20) -> dict:
    """
    Reads residue_review to find beliefs that should be boosted
    or pruned. Used by the consolidation loop.

    Returns:
      boost_candidates:  beliefs in residue 3+ times — activate reliably
                         but don't reach utterance — need compiler boost
      prune_candidates:  beliefs in residue with consistent no-delta —
                         activating but never landing, low confidence
    """
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)

        # Count residue appearances per belief
        rows = db.execute("""
            SELECT belief_id,
                   COUNT(*) as residue_count,
                   SUM(CASE WHEN delta_strength != 'none' THEN 1 ELSE 0 END) as with_delta,
                   SUM(CASE WHEN resistance != 'none' THEN 1 ELSE 0 END) as with_resistance
            FROM residue_review
            WHERE timestamp > ?
            GROUP BY belief_id
            ORDER BY residue_count DESC
            LIMIT 20
        """, (time.time() - (n_sessions * 3600),)).fetchall()

        boost_candidates = []
        prune_candidates = []

        for row in rows:
            bid, count, with_delta, with_resistance = row
            # Get belief content
            belief = db.execute(
                "SELECT content, confidence, topic FROM beliefs WHERE id=?",
                (bid,)
            ).fetchone()
            if not belief:
                continue

            entry = {
                "id":           bid,
                "content":      belief[0][:100],
                "confidence":   belief[1],
                "topic":        belief[2],
                "residue_count": count,
                "with_delta":   with_delta,
                "with_resistance": with_resistance
            }

            if count >= 3 and (with_delta / max(count, 1)) > 0.3:
                # Activates in contexts where things land — should reach utterance
                boost_candidates.append(entry)
            elif count >= 3 and (with_delta / max(count, 1)) < 0.1:
                # Activates but nothing ever lands — review for pruning
                prune_candidates.append(entry)

        db.close()
        return {
            "boost_candidates": boost_candidates,
            "prune_candidates": prune_candidates,
            "total_reviewed":   len(rows)
        }

    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    print("=== Delta Reinforcement Test ===\n")

    # Simulate a strong landing
    result = reinforce_from_delta(
        session_id="test_reinforce_001",
        utterance_belief_ids=[1, 2, 3],
        residue_belief_ids=[4, 5, 6, 7],
        delta={"delta_detected": True, "strength": "strong",
               "signals": ["explicit_acknowledgement", "register_shift_upward"]},
        resistance_level="none"
    )
    print(f"Strong delta result: {result}")

    # Simulate no landing
    result2 = reinforce_from_delta(
        session_id="test_reinforce_001",
        utterance_belief_ids=[8, 9],
        residue_belief_ids=[10, 11],
        delta={"delta_detected": False, "strength": "none", "signals": []},
        resistance_level="medium"
    )
    print(f"No delta result: {result2}")

    print("\n=== Reinforcement Candidates ===")
    candidates = get_reinforcement_candidates(n_sessions=5)
    print(json.dumps(candidates, indent=2))
