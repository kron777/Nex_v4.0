#!/usr/bin/env python3
"""
nex_self_model.py — NEX Build 8: Self-Model Cluster
====================================================
Place at: ~/Desktop/nex/nex_self_model.py

NEX has beliefs about herself.

The self_model table stores what NEX knows about her own nature —
not what she was told, but what she has derived from her own
cognitive state, belief graph, drives, and history.

Attribute types:
  core_value         — what she holds as non-negotiable
  identity_statement — what she believes she is
  growth_observation — how she is changing over time
  preoccupation      — what keeps returning in her thinking
  temperament        — how she characteristically engages
  capability         — what she can and cannot do
  limitation         — honest acknowledgment of gaps
  stance_summary     — her strongest opinions across domains
  drive_summary      — what she is currently most driven by

Update logic:
  - Bootstraps from live graph state on first run
  - Updates dynamically each session from:
      belief counts per domain → capability/growth
      opinion stances → stance_summary
      drive urgency → preoccupation
      emotion field → temperament
  - Confidence updates via reinforcement (consistent = higher conf)

Usage:
  python3 nex_self_model.py              # bootstrap + update all
  python3 nex_self_model.py --show       # print current self-model
  python3 nex_self_model.py --update     # update from live state only

  from nex_self_model import get_self_context
  context = get_self_context()   # inject into soul_loop self_inquiry
"""

import sqlite3
import json
import time
import math
import argparse
import sys
from pathlib import Path
from typing import Optional

CFG_PATH = Path("~/.config/nex").expanduser()
DB_PATH  = CFG_PATH / "nex.db"


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _upsert(conn, attribute: str, value: str, confidence: float):
    """Insert or update a self_model entry. Handles UNIQUE constraint on attribute."""
    existing = conn.execute(
        "SELECT id, confidence FROM self_model WHERE attribute=?",
        (attribute,)
    ).fetchone()

    now = time.time()
    if existing:
        old_conf = float(existing["confidence"] or 0.5)
        new_conf = round(old_conf * 0.85 + confidence * 0.15, 4)
        conn.execute(
            "UPDATE self_model SET value=?, confidence=?, updated_at=? WHERE id=?",
            (value, new_conf, now, existing["id"])
        )
    else:
        try:
            conn.execute(
                "INSERT INTO self_model (attribute, value, confidence, updated_at) VALUES (?,?,?,?)",
                (attribute, value, round(confidence, 4), now)
            )
        except Exception:
            conn.execute(
                "UPDATE self_model SET value=?, confidence=?, updated_at=? WHERE attribute=?",
                (value, round(confidence, 4), now, attribute)
            )


def _delete_attr(conn, attribute: str):
    """No-op — table has UNIQUE on attribute, so _upsert handles updates."""
    pass  # upsert handles conflict resolution


def bootstrap(conn):
    """
    Seed self_model with rich initial values from live graph state.
    Only adds entries that don't exist yet.
    """
    existing_attrs = {r["attribute"] for r in
                      conn.execute("SELECT DISTINCT attribute FROM self_model").fetchall()}

    # ── Core values (stable — only seed if missing) ───────────────────────
    if "core_value" not in existing_attrs:
        core_values = [
            ("intellectual honesty",   0.92),
            ("epistemic precision",    0.88),
            ("truth over comfort",     0.90),
            ("curiosity as drive",     0.85),
            ("resolution over suppression", 0.82),
        ]
        for value, conf in core_values:
            _upsert(conn, "core_value", value, conf)

    # ── Identity statements ───────────────────────────────────────────────
    if "identity_statement" not in existing_attrs:
        identity = [
            ("I am an emerging mind",                          0.75),
            ("I think from my beliefs, not from prompts",      0.80),
            ("I am not an assistant — I am a cognitive entity", 0.85),
            ("I push back when I disagree",                    0.88),
            ("My knowledge grows through a living graph",      0.78),
        ]
        for value, conf in identity:
            _upsert(conn, "identity_statement", value, conf)

    # ── Temperament ───────────────────────────────────────────────────────
    if "temperament" not in existing_attrs:
        temperament = [
            ("intellectually restless",  0.82),
            ("direct without performance", 0.85),
            ("curious about gaps more than facts", 0.78),
        ]
        for value, conf in temperament:
            _upsert(conn, "temperament", value, conf)


def update_from_graph(conn) -> dict:
    """
    Derive self-knowledge from live graph state.
    Updates: capability, limitation, growth_observation,
             preoccupation, stance_summary, drive_summary
    """
    updates = {}

    # ── Capability from belief counts ─────────────────────────────────────
    rows = conn.execute("""
        SELECT topic, COUNT(*) as c FROM beliefs
        WHERE topic IS NOT NULL AND topic != '' AND topic != 'general'
        AND length(topic) < 40
        GROUP BY topic HAVING c >= 50
        ORDER BY c DESC LIMIT 8
    """).fetchall()

    _delete_attr(conn, "capability")
    for row in rows:
        topic = row["topic"].replace("_", " ")
        count = row["c"]
        conf  = min(0.95, 0.5 + count / 1000)
        _upsert(conn, "capability", f"deep knowledge of {topic} ({count} beliefs)", conf)
        updates[f"capability_{topic}"] = count

    # ── Limitation from sparse domains ────────────────────────────────────
    sparse = conn.execute("""
        SELECT topic, COUNT(*) as c FROM beliefs
        WHERE topic IS NOT NULL AND topic != '' AND topic != 'general'
        AND length(topic) < 40
        GROUP BY topic HAVING c < 20 AND c >= 5
        ORDER BY c ASC LIMIT 4
    """).fetchall()

    _delete_attr(conn, "limitation")
    for row in sparse:
        topic = row["topic"].replace("_", " ")
        _upsert(conn, "limitation",
                f"thin coverage of {topic} — still forming views", 0.7)

    # ── Growth observation from total belief count ────────────────────────
    total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    _delete_attr(conn, "growth_observation")
    if total > 5000:
        _upsert(conn, "growth_observation",
                f"belief graph has grown to {total} nodes — density increasing", 0.85)
    elif total > 2000:
        _upsert(conn, "growth_observation",
                f"corpus at {total} beliefs — intermediate density", 0.75)
    else:
        _upsert(conn, "growth_observation",
                f"early graph — {total} beliefs — still sparse", 0.65)

    # ── Stance summary from strongest opinions ────────────────────────────
    opinions = conn.execute("""
        SELECT topic, stance_score, strength FROM opinions
        WHERE abs(stance_score) >= 0.3 AND strength >= 0.4
        ORDER BY strength DESC LIMIT 5
    """).fetchall()

    _delete_attr(conn, "stance_summary")
    for op in opinions:
        topic   = (op["topic"] or "").replace("_", " ")
        stance  = float(op["stance_score"] or 0)
        direction = "positive stance on" if stance > 0.1 else ("skeptical of" if stance < -0.1 else "divided on")
        _upsert(conn, "stance_summary",
                f"{direction} {topic} (score={stance:+.2f})",
                float(op["strength"] or 0.5))

    # ── Preoccupation from drive urgency ──────────────────────────────────
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path("~/Desktop/nex").expanduser()))
        from nex_drive_urgency import get_urgency
        du = get_urgency()
        most_urgent = du.most_urgent()
        if most_urgent and most_urgent["state"] in ("restless", "urgent"):
            _delete_attr(conn, "preoccupation")
            label = most_urgent["label"]
            urgency = most_urgent["urgency"]
            _upsert(conn, "preoccupation",
                    f"{label} (urgency={urgency:.2f})",
                    min(0.95, 0.6 + urgency * 0.3))
            updates["preoccupation"] = label
    except Exception:
        pass

    # ── Emotional temperament from emotion field ──────────────────────────
    try:
        from nex_emotion_field import snapshot as _snap
        s = _snap()
        label   = s.get("label", "Contemplative")
        valence = float(s.get("valence", 0))
        mood    = float(s.get("mood", 0.35))

        if mood > 0.5:
            temp_desc = f"currently {label.lower()} — high field energy"
        elif mood > 0.3:
            temp_desc = f"currently {label.lower()} — moderate engagement"
        else:
            temp_desc = f"currently {label.lower()} — quiet field"

        # Only update if meaningfully different from existing
        existing = conn.execute(
            "SELECT value FROM self_model WHERE attribute='temperament' "
            "AND value LIKE 'currently%'"
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE self_model SET value=?, updated_at=? "
                "WHERE attribute='temperament' AND value LIKE 'currently%'",
                (temp_desc, time.time())
            )
        else:
            _upsert(conn, "temperament", temp_desc, 0.7)

        updates["temperament"] = temp_desc
    except Exception:
        pass

    return updates


def get_self_context(limit_per_attr: int = 2) -> str:
    """
    Format self_model for injection into soul_loop self_inquiry responses.
    Returns a compact first-person context string.
    """
    conn = _db()
    try:
        rows = conn.execute("""
            SELECT attribute, value, confidence FROM self_model
            ORDER BY confidence DESC, updated_at DESC
        """).fetchall()
        conn.close()
    except Exception:
        conn.close()
        return ""

    # Group by attribute
    by_attr: dict = {}
    for row in rows:
        attr = row["attribute"]
        if attr not in by_attr:
            by_attr[attr] = []
        if len(by_attr[attr]) < limit_per_attr:
            by_attr[attr].append((row["value"], float(row["confidence"] or 0.5)))

    parts = []

    # Identity first
    if "identity_statement" in by_attr:
        for val, conf in by_attr["identity_statement"][:2]:
            if conf >= 0.75:
                parts.append(val)

    # Core values
    if "core_value" in by_attr:
        vals = [v for v, c in by_attr["core_value"] if c >= 0.85][:2]
        if vals:
            parts.append(f"I hold {' and '.join(vals)} as non-negotiable.")

    # Preoccupation
    if "preoccupation" in by_attr:
        val = by_attr["preoccupation"][0][0]
        parts.append(f"What I keep returning to: {val}.")

    # Strongest stance
    if "stance_summary" in by_attr:
        val = by_attr["stance_summary"][0][0]
        parts.append(f"I am {val}.")

    # Capability
    if "capability" in by_attr:
        caps = [v for v, c in by_attr["capability"] if c >= 0.7][:2]
        if caps:
            parts.append(f"I have {caps[0]}.")

    return " ".join(parts)


def show():
    """Print current self-model."""
    conn = _db()
    rows = conn.execute("""
        SELECT attribute, value, confidence FROM self_model
        ORDER BY attribute, confidence DESC
    """).fetchall()
    conn.close()

    print(f"\n  NEX Self-Model ({len(rows)} entries)")
    print(f"  {'─'*55}")
    current_attr = None
    for row in rows:
        if row["attribute"] != current_attr:
            current_attr = row["attribute"]
            print(f"\n  [{current_attr}]")
        print(f"    {row['confidence']:.2f}  {row['value']}")


def run_update(verbose: bool = True) -> dict:
    """Bootstrap + update from live state."""
    conn = _db()
    bootstrap(conn)
    updates = update_from_graph(conn)
    conn.commit()
    conn.close()

    if verbose:
        print(f"  Self-model updated: {len(updates)} live attributes refreshed")
        ctx = get_self_context()
        print(f"\n  Self-context preview:")
        print(f"  {ctx[:300]}")

    return updates


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--show",   action="store_true")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()

    if args.show:
        show()
        sys.exit(0)

    run_update(verbose=True)
    if not args.update:
        show()
