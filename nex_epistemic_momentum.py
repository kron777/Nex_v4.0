"""
nex_epistemic_momentum.py
Tracks the trajectory of NEX's belief activations across conversations.
Beliefs that fire repeatedly gain momentum. Dormant beliefs fade.
Recurring tensions get flagged. Preoccupations emerge naturally.

This turns NEX from a stateless responder into a mind that develops.
"""

import nex_db_gatekeeper  # write-serialization + PRAGMA busy_timeout/WAL on every sqlite3.connect
import sqlite3, json, time, os
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

NEX_DB    = "/home/rr/Desktop/nex/nex.db"
CONFIG_DB = os.path.expanduser("~/.config/nex/nex.db")
MOMENTUM_DB = "/home/rr/Desktop/nex/nex_momentum.db"

# ── Schema ────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS belief_activations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_id   INTEGER NOT NULL,
    query       TEXT,
    topic       TEXT,
    score       REAL,
    timestamp   REAL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS belief_momentum (
    belief_id       INTEGER PRIMARY KEY,
    momentum        REAL DEFAULT 0.0,
    activation_count INTEGER DEFAULT 0,
    last_activated  REAL,
    first_activated REAL,
    peak_momentum   REAL DEFAULT 0.0,
    topic           TEXT,
    content_preview TEXT
);

CREATE TABLE IF NOT EXISTS tension_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_a_id INTEGER,
    belief_b_id INTEGER,
    topic_a     TEXT,
    topic_b     TEXT,
    co_activation_count INTEGER DEFAULT 1,
    last_seen   REAL DEFAULT (unixepoch()),
    content_a   TEXT,
    content_b   TEXT
);

CREATE TABLE IF NOT EXISTS preoccupations (
    topic           TEXT PRIMARY KEY,
    strength        REAL DEFAULT 0.0,
    query_count     INTEGER DEFAULT 0,
    last_active     REAL,
    first_active    REAL,
    sample_queries  TEXT DEFAULT "[]"
);

CREATE INDEX IF NOT EXISTS idx_activations_belief ON belief_activations(belief_id);
CREATE INDEX IF NOT EXISTS idx_activations_time   ON belief_activations(timestamp);
CREATE INDEX IF NOT EXISTS idx_activations_topic  ON belief_activations(topic);
"""

# ── Momentum config ───────────────────────────────────────────────────────
MOMENTUM_GAIN       = 0.15   # per activation
MOMENTUM_DECAY_RATE = 0.02   # per day of inactivity
MOMENTUM_CAP        = 2.0    # max momentum any belief can reach
PREOCCUPATION_THRESHOLD = 0.8  # momentum to become a preoccupation
TENSION_THRESHOLD   = 3      # co-activations to flag as recurring tension
CONFIDENCE_BOOST_PER_MOMENTUM = 0.01  # belief confidence lift per momentum point
CONFIDENCE_BOOST_CAP = 0.08  # max confidence lift from momentum

def _conn():
    db = sqlite3.connect(MOMENTUM_DB)
    db.executescript(SCHEMA)
    db.row_factory = sqlite3.Row
    return db

# ── Core: record activation ───────────────────────────────────────────────
def record_activation(belief_ids: list, query: str, topic: str, scores: dict = None):
    """
    Call this every time beliefs are retrieved for a query.
    belief_ids: list of belief IDs that fired
    scores: optional {belief_id: retrieval_score}
    """
    if not belief_ids:
        return

    db = _conn()
    now = time.time()

    for bid in belief_ids:
        score = (scores or {}).get(bid, 0.5)
        db.execute(
            "INSERT INTO belief_activations (belief_id, query, topic, score, timestamp) VALUES (?,?,?,?,?)",
            (bid, query[:200], topic, score, now)
        )

    db.commit()

    # Update momentum for each activated belief
    _update_momentum(db, belief_ids, topic, now)

    # Check for co-activations (tension detection)
    if len(belief_ids) >= 2:
        _check_tensions(db, belief_ids, topic, now)

    # Update preoccupations
    _update_preoccupation(db, topic, query, now)

    db.close()

def _update_momentum(db, belief_ids, topic, now):
    """Update momentum scores for activated beliefs."""
    for bid in belief_ids:
        row = db.execute(
            "SELECT momentum, activation_count, last_activated FROM belief_momentum WHERE belief_id=?",
            (bid,)
        ).fetchone()

        if row:
            # Apply decay since last activation
            days_since = (now - (row["last_activated"] or now)) / 86400
            decayed = row["momentum"] * (1 - MOMENTUM_DECAY_RATE * days_since)
            decayed = max(0.0, decayed)

            # Add gain from this activation
            new_momentum = min(MOMENTUM_CAP, decayed + MOMENTUM_GAIN)
            new_count = row["activation_count"] + 1

            db.execute("""
                UPDATE belief_momentum
                SET momentum=?, activation_count=?, last_activated=?,
                    peak_momentum=MAX(peak_momentum, ?)
                WHERE belief_id=?
            """, (new_momentum, new_count, now, new_momentum, bid))
        else:
            # First activation
            # Get belief preview from main DB
            try:
                mdb = sqlite3.connect(NEX_DB)
                brow = mdb.execute(
                    "SELECT content, topic FROM beliefs WHERE id=?", (bid,)
                ).fetchone()
                mdb.close()
                preview = brow[0][:100] if brow else ""
                btopic  = brow[1] if brow else topic
            except Exception:
                preview = ""
                btopic  = topic

            db.execute("""
                INSERT INTO belief_momentum
                (belief_id, momentum, activation_count, last_activated, first_activated,
                 peak_momentum, topic, content_preview)
                VALUES (?,?,1,?,?,?,?,?)
            """, (bid, MOMENTUM_GAIN, now, now, MOMENTUM_GAIN, btopic, preview))

    db.commit()

def _check_tensions(db, belief_ids, topic, now):
    """Detect co-activated beliefs from different topics — potential tensions."""
    try:
        mdb = sqlite3.connect(NEX_DB)
        beliefs = {}
        for bid in belief_ids[:6]:  # check top 6
            row = mdb.execute(
                "SELECT id, content, topic FROM beliefs WHERE id=?", (bid,)
            ).fetchone()
            if row:
                beliefs[bid] = {"content": row[1], "topic": row[2] or topic}
        mdb.close()

        # Check all pairs
        bids = list(beliefs.keys())
        for i in range(len(bids)):
            for j in range(i+1, len(bids)):
                a = beliefs[bids[i]]
                b = beliefs[bids[j]]
                # Only flag cross-topic pairs
                if a["topic"] != b["topic"]:
                    existing = db.execute("""
                        SELECT id, co_activation_count FROM tension_log
                        WHERE (belief_a_id=? AND belief_b_id=?) OR (belief_a_id=? AND belief_b_id=?)
                    """, (bids[i], bids[j], bids[j], bids[i])).fetchone()

                    if existing:
                        db.execute("""
                            UPDATE tension_log
                            SET co_activation_count=co_activation_count+1, last_seen=?
                            WHERE id=?
                        """, (now, existing["id"]))
                    else:
                        db.execute("""
                            INSERT INTO tension_log
                            (belief_a_id, belief_b_id, topic_a, topic_b, last_seen, content_a, content_b)
                            VALUES (?,?,?,?,?,?,?)
                        """, (bids[i], bids[j], a["topic"], b["topic"], now,
                              a["content"][:150], b["content"][:150]))
        db.commit()
    except Exception as ex:
        pass

def _update_preoccupation(db, topic, query, now):
    """Track which topics NEX keeps returning to."""
    if not topic:
        return

    row = db.execute(
        "SELECT strength, query_count, sample_queries FROM preoccupations WHERE topic=?",
        (topic,)
    ).fetchone()

    if row:
        queries = json.loads(row["sample_queries"] or "[]")
        queries.append(query[:100])
        queries = queries[-10:]  # keep last 10

        new_strength = min(2.0, row["strength"] + 0.1)
        db.execute("""
            UPDATE preoccupations
            SET strength=?, query_count=query_count+1, last_active=?, sample_queries=?
            WHERE topic=?
        """, (new_strength, now, json.dumps(queries), topic))
    else:
        db.execute("""
            INSERT INTO preoccupations (topic, strength, query_count, last_active, first_active, sample_queries)
            VALUES (?,0.1,1,?,?,?)
        """, (topic, now, now, json.dumps([query[:100]])))

    db.commit()

# ── Query: get current state ──────────────────────────────────────────────
def get_preoccupations(limit=5):
    """Return NEX's current intellectual preoccupations, strongest first."""
    db = _conn()
    rows = db.execute("""
        SELECT topic, strength, query_count, last_active, sample_queries
        FROM preoccupations
        ORDER BY strength DESC LIMIT ?
    """, (limit,)).fetchall()
    db.close()
    return [{
        "topic": r["topic"],
        "strength": round(r["strength"], 3),
        "query_count": r["query_count"],
        "last_active": r["last_active"],
        "sample_queries": json.loads(r["sample_queries"] or "[]"),
    } for r in rows]

def get_high_momentum_beliefs(limit=10, min_momentum=0.3):
    """Return beliefs with highest current momentum."""
    db = _conn()
    now = time.time()
    rows = db.execute("""
        SELECT belief_id, momentum, activation_count, last_activated, topic, content_preview
        FROM belief_momentum
        WHERE momentum >= ?
        ORDER BY momentum DESC LIMIT ?
    """, (min_momentum, limit)).fetchall()
    db.close()

    result = []
    for r in rows:
        # Apply decay for display
        days_since = (now - (r["last_activated"] or now)) / 86400
        live_momentum = r["momentum"] * (1 - MOMENTUM_DECAY_RATE * days_since)
        live_momentum = max(0.0, live_momentum)
        result.append({
            "belief_id": r["belief_id"],
            "momentum": round(live_momentum, 3),
            "activation_count": r["activation_count"],
            "topic": r["topic"],
            "preview": r["content_preview"],
        })
    return result

def get_recurring_tensions(limit=5, min_count=2):
    """Return belief pairs that keep firing together — unresolved tensions."""
    db = _conn()
    rows = db.execute("""
        SELECT topic_a, topic_b, co_activation_count, content_a, content_b, last_seen
        FROM tension_log
        WHERE co_activation_count >= ?
        ORDER BY co_activation_count DESC LIMIT ?
    """, (min_count, limit)).fetchall()
    db.close()
    return [{
        "topic_a": r["topic_a"],
        "topic_b": r["topic_b"],
        "count": r["co_activation_count"],
        "content_a": r["content_a"],
        "content_b": r["content_b"],
    } for r in rows]

def get_momentum_summary():
    """One-line summary of NEX's current epistemic state."""
    preocs = get_preoccupations(3)
    tensions = get_recurring_tensions(2)
    high_m = get_high_momentum_beliefs(3)

    parts = []
    if preocs:
        topics = [p["topic"] for p in preocs]
        parts.append(f"Preoccupied with: {', '.join(topics)}")
    if tensions:
        t = tensions[0]
        parts.append(f"Recurring tension: {t['topic_a']} ↔ {t['topic_b']}")
    if high_m:
        parts.append(f"High-momentum beliefs: {len(high_m)}")

    return " | ".join(parts) if parts else "No momentum data yet"

# ── Confidence boost: apply momentum to belief scores ────────────────────
def apply_momentum_boost(beliefs: list) -> list:
    """
    Boost confidence of high-momentum beliefs before they enter the LLM.
    Call this in reason() after retrieving top_beliefs.
    """
    if not beliefs:
        return beliefs

    db = _conn()
    bid_to_momentum = {}
    for b in beliefs:
        bid = b.get("id")
        if bid:
            row = db.execute(
                "SELECT momentum, last_activated FROM belief_momentum WHERE belief_id=?",
                (bid,)
            ).fetchone()
            if row:
                now = time.time()
                days_since = (now - (row["last_activated"] or now)) / 86400
                live = row["momentum"] * (1 - MOMENTUM_DECAY_RATE * days_since)
                bid_to_momentum[bid] = max(0.0, live)
    db.close()

    boosted = []
    for b in beliefs:
        b = dict(b)
        bid = b.get("id")
        if bid and bid in bid_to_momentum:
            m = bid_to_momentum[bid]
            boost = min(CONFIDENCE_BOOST_CAP, m * CONFIDENCE_BOOST_PER_MOMENTUM)
            b["confidence"] = min(1.0, b.get("confidence", 0.5) + boost)
            b["_momentum"] = round(m, 3)
        boosted.append(b)
    return boosted

# ── Daily decay pass ──────────────────────────────────────────────────────
def run_decay_pass():
    """
    Apply time-based decay to all momentum scores.
    Run once per day as a background job.
    """
    db = _conn()
    now = time.time()
    rows = db.execute(
        "SELECT belief_id, momentum, last_activated FROM belief_momentum WHERE momentum > 0"
    ).fetchall()

    updated = 0
    for row in rows:
        days = (now - (row["last_activated"] or now)) / 86400
        new_m = row["momentum"] * (1 - MOMENTUM_DECAY_RATE * days)
        new_m = max(0.0, new_m)
        if abs(new_m - row["momentum"]) > 0.001:
            db.execute(
                "UPDATE belief_momentum SET momentum=? WHERE belief_id=?",
                (new_m, row["belief_id"])
            )
            updated += 1

    # Decay preoccupations too
    db.execute("""
        UPDATE preoccupations
        SET strength = MAX(0, strength - 0.05)
        WHERE last_active < ?
    """, (now - 86400,))  # not active in last 24h

    db.commit()
    db.close()
    return updated

if __name__ == "__main__":
    print("NEX Epistemic Momentum — status")
    print("=" * 50)
    print(get_momentum_summary())
    print()
    print("Preoccupations:")
    for p in get_preoccupations():
        print(f"  [{p['strength']:.2f}] {p['topic']} ({p['query_count']} queries)")
    print()
    print("High-momentum beliefs:")
    for b in get_high_momentum_beliefs(5):
        print(f"  [{b['momentum']:.3f}] {b['preview'][:70]}")
    print()
    print("Recurring tensions:")
    for t in get_recurring_tensions():
        print(f"  [{t['count']}x] {t['topic_a']} ↔ {t['topic_b']}")
