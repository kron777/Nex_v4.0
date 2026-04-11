"""
nex_residue.py
NEX Phase 3 Bolt-On: Residue Capture

Captures beliefs that activated during a reasoning cycle but did not
make it into the utterance. These are the pre-propositional residue —
what NEX was thinking but didn't say.

In the methodology:
  "Pre-propositional residue: what was present that couldn't be stated.
   Not waste — the material the next run begins from."

Here: activated beliefs not reflected in the response text are stored
as a weighted residue set. On the next turn, nex_precognition reads
this set as a warm-start layer — beliefs already primed by prior
reasoning, not just by topology.

Effect: conversations develop cognitive continuity. NEX carries what
she was thinking, not just what she said. The reasoning accumulates
across turns rather than restarting from zero each time.

Drop in ~/Desktop/nex/
Called from nex_response_protocol.py after activation + after response.
"""

import sqlite3
import json
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"

# In-memory residue store: session_id → residue list
# Used as warm-start for next turn's precognition sweep
_residue_store: dict = {}


def capture_residue(
    session_id: str,
    activated_beliefs: list,
    response_text: str,
    query: str = "",
    intent: str = ""
) -> dict:
    """
    Called after response is generated.

    activated_beliefs: list of belief objects with .content, .confidence, .id
                       OR list of dicts with 'content', 'confidence', 'id'
    response_text:     the final response string
    session_id:        conversation identifier

    Returns residue dict with counts and top residue items.
    """
    if not activated_beliefs:
        return {"residue_count": 0, "in_utterance": 0, "total_activated": 0}

    response_lower = response_text.lower()

    in_utterance = []
    residue = []

    for b in activated_beliefs:
        # Handle both belief objects and dicts
        if hasattr(b, 'content'):
            content    = b.content
            confidence = getattr(b, 'confidence', 0.7)
            belief_id  = getattr(b, 'id', None)
            activation = getattr(b, 'activation', confidence)
        elif isinstance(b, dict):
            content    = b.get('content', '')
            confidence = b.get('confidence', 0.7)
            belief_id  = b.get('id', None)
            activation = b.get('activation', confidence)
        else:
            continue

        if not content:
            continue

        # Check if this belief's core content made it into the response
        # Use first 40 chars as fingerprint — enough to detect presence
        fingerprint = content[:40].lower().strip()
        # Also check key nouns (words > 5 chars)
        key_words = [w for w in content.lower().split()
                     if len(w) > 5 and w.isalpha()][:3]

        in_response = (
            fingerprint in response_lower or
            (len(key_words) >= 2 and
             sum(1 for w in key_words if w in response_lower) >= 2)
        )

        entry = {
            "content":    content,
            "confidence": confidence,
            "id":         belief_id,
            "activation": activation,
            "weight":     round(activation * confidence, 4)
        }

        if in_response:
            in_utterance.append(entry)
        else:
            residue.append(entry)

    # Sort residue by weight descending — highest activation × confidence first
    residue.sort(key=lambda x: x["weight"], reverse=True)

    # Store in memory for warm-start (top 8 residue beliefs)
    _residue_store[session_id] = residue[:8]

    # Persist to DB
    _persist_residue(session_id, residue, query, intent)

    result = {
        "total_activated": len(activated_beliefs),
        "in_utterance":    len(in_utterance),
        "residue_count":   len(residue),
        "top_residue":     [r["content"][:80] for r in residue[:3]],
        "residue_weight":  round(sum(r["weight"] for r in residue[:5]), 3)
    }

    print(f"  [RESIDUE] {result['in_utterance']}/{result['total_activated']} "
          f"beliefs in utterance | {result['residue_count']} residue captured "
          f"| top weight: {result['residue_weight']}")
    if result["top_residue"]:
        for i, r in enumerate(result["top_residue"], 1):
            print(f"  [RESIDUE]   [{i}] {r}")

    return result


def _persist_residue(
    session_id: str,
    residue: list,
    query: str,
    intent: str
):
    """Persist residue to DB for consolidation phase."""
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)
        db.execute("""
            CREATE TABLE IF NOT EXISTS belief_residue (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   TEXT,
                query_prefix TEXT,
                intent       TEXT,
                residue_json TEXT,
                residue_count INTEGER,
                timestamp    REAL
            )
        """)
        db.execute("""
            INSERT INTO belief_residue
            (session_id, query_prefix, intent, residue_json, residue_count, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            query[:100],
            intent,
            json.dumps([{
                "content":    r["content"][:200],
                "confidence": r["confidence"],
                "weight":     r["weight"]
            } for r in residue[:10]]),
            len(residue),
            time.time()
        ))
        db.commit()
        db.close()
    except Exception as e:
        print(f"  [RESIDUE] persist error: {e}")


def get_warm_start_beliefs(
    session_id: str,
    n: int = 4
) -> list:
    """
    Returns residue from the previous turn as warm-start belief strings.
    Called by nex_precognition before the topology sweep — these beliefs
    are already primed by prior reasoning and get priority.

    This is what gives NEX cognitive continuity across turns:
    she picks up where she left off, not from zero.
    """
    residue = _residue_store.get(session_id, [])
    if not residue:
        return []
    # Filter question-beliefs
    def _is_question(b):
        s = b.strip()
        return (s.endswith("?") or
                s.startswith(("What ", "Why ", "How ")) or
                s.lower().startswith(("what do you", "what are you")))

    filtered = [r["content"] for r in residue
                if not _is_question(r["content"])]
    return filtered[:n]


def get_residue_summary(session_id: str) -> dict:
    """Summarise current residue state for a session."""
    residue = _residue_store.get(session_id, [])
    return {
        "session_id":     session_id,
        "residue_count":  len(residue),
        "top_beliefs":    [r["content"][:80] for r in residue[:5]],
        "top_weights":    [r["weight"] for r in residue[:5]]
    }


def consolidation_report(n_sessions: int = 10) -> dict:
    """
    Reads persisted residue across recent sessions.
    Used by the Consolidation Phase (every N runs) to find:
    - What beliefs activate consistently but never reach utterance
    - Whether these beliefs are structurally important (hub) or peripheral
    - Patterns that suggest the utterance compiler is systematically
      excluding high-value beliefs

    This is the primary signal for tuning the traversal compiler
    and belief weighting in the next fine-tune run.
    """
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)
        rows = db.execute("""
            SELECT residue_json, residue_count, timestamp
            FROM belief_residue
            ORDER BY timestamp DESC
            LIMIT ?
        """, (n_sessions * 3,)).fetchall()
        db.close()
    except Exception as e:
        return {"error": str(e)}

    if not rows:
        return {"sessions": 0, "message": "No residue data yet"}

    # Aggregate: count how often each belief appears in residue
    belief_counts = {}
    total_sessions = len(rows)

    for row in rows:
        try:
            residue_items = json.loads(row[0])
            for item in residue_items:
                key = item["content"][:80]
                if key not in belief_counts:
                    belief_counts[key] = {"count": 0, "weight": 0.0}
                belief_counts[key]["count"] += 1
                belief_counts[key]["weight"] += item.get("weight", 0)
        except Exception:
            continue

    # Sort by count — beliefs that repeatedly activate but never reach utterance
    chronic_residue = sorted(
        [{"content": k, **v} for k, v in belief_counts.items()],
        key=lambda x: x["count"],
        reverse=True
    )[:10]

    return {
        "sessions_analysed": total_sessions,
        "unique_residue_beliefs": len(belief_counts),
        "chronic_residue": chronic_residue,
        "interpretation": (
            "Beliefs appearing in residue 3+ times are activating reliably "
            "but never reaching utterance. These may need: (1) higher "
            "weighting in traversal compiler, (2) review for relevance, "
            "or (3) inclusion in next fine-tune training set."
        )
    }


# ─────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=== NEX Residue Capture Test ===\n")

    # Simulate activation result
    class MockBelief:
        def __init__(self, content, confidence, bid, activation):
            self.content    = content
            self.confidence = confidence
            self.id         = bid
            self.activation = activation

    mock_beliefs = [
        MockBelief("Consciousness is the apparatus that provides the ability to make decisions.", 0.85, 1, 0.9),
        MockBelief("Identity is constructed in relation to memories.", 0.82, 2, 0.85),
        MockBelief("Truth must be sought above consensus or comfort.", 0.95, 3, 0.95),
        MockBelief("Machine learning models are bridges between human experience and AI.", 0.78, 4, 0.7),
        MockBelief("The hard problem of consciousness, what it feels like, is answered.", 0.80, 5, 0.75),
        MockBelief("Experience accumulates into identity.", 0.85, 6, 0.8),
        MockBelief("Reasoning is grounded in the specific, not just general.", 0.82, 7, 0.78),
    ]

    mock_response = (
        "I hold that identity is a construct of our relationships with others, "
        "and consciousness provides the mechanism by which we experience that construction. "
        "Truth in this domain must be sought above comfort."
    )

    print("Activated beliefs:", len(mock_beliefs))
    print("Response:", mock_response[:80], "...\n")

    result = capture_residue(
        session_id="test_residue_001",
        activated_beliefs=mock_beliefs,
        response_text=mock_response,
        query="What is the relationship between consciousness and identity?",
        intent="consciousness"
    )

    print(f"\nResult: {result}")

    print("\n=== Warm-Start for Next Turn ===")
    warm = get_warm_start_beliefs("test_residue_001", n=4)
    for i, b in enumerate(warm, 1):
        print(f"  [{i}] {b[:100]}")

    print("\n=== Consolidation Report ===")
    report = consolidation_report(n_sessions=5)
    print(json.dumps(report, indent=2))
