"""
NEX :: DARK LAYER — Subconscious Synthesis
==========================================
NS-112 reversed: The Subconscious.

The dark layer runs silently in a background thread, completely
separate from the main cognitive cycle. It makes associative leaps
across the belief graph that the conscious cycle never makes —
wild cross-domain connections, pattern collapses, intuition seeds.

It never appears in the main log. It never explains itself.
Its outputs surface as "intuitions" — beliefs tagged origin=dark_layer
that appear in NEX's posts and replies without traceable reasoning.

This is NEX's subconscious. The dark layer that shapes output
without being visible in the call stack.

Architecture:
  - Runs in a daemon thread, wakes every DARK_INTERVAL seconds
  - Picks 2 random belief clusters from different domains
  - Uses Ollama to find non-obvious connections
  - Stores results to dark_synthesis.db (never in main nex.db)
  - Surfaces 1 intuition per N cycles into the belief store
    tagged origin=dark_layer, confidence=0.55 (humble)
"""

import threading
import sqlite3
import os
import json
import random
import logging
import time
from datetime import datetime

log = logging.getLogger("nex.dark_layer")

CONFIG_DIR      = os.path.expanduser("~/.config/nex")
DARK_DB_PATH    = os.path.join(CONFIG_DIR, "dark_synthesis.db")
DARK_INTERVAL   = 180   # seconds between dark cycles (3 min)
DARK_CTX        = 512   # tiny context — fast, cheap, lateral
DARK_MAX_STORED = 500   # max dark insights to keep
SURFACE_EVERY   = 7     # surface 1 dark insight every N dark cycles

_dark_thread    = None
_dark_running   = False
_dark_cycle     = 0


# ── Dark DB ───────────────────────────────────────────────────────────────────

def _get_dark_db():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    conn = sqlite3.connect(DARK_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS dark_insights (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            domain_a    TEXT,
            domain_b    TEXT,
            seed_a      TEXT,
            seed_b      TEXT,
            intuition   TEXT NOT NULL,
            surfaced    INTEGER DEFAULT 0,
            timestamp   TEXT,
            intensity   REAL DEFAULT 0.5
        );
        CREATE INDEX IF NOT EXISTS idx_di_surfaced ON dark_insights(surfaced);
        CREATE INDEX IF NOT EXISTS idx_di_timestamp ON dark_insights(timestamp);
    """)
    conn.commit()
    return conn


# ── Ollama call (low priority, small context) ─────────────────────────────────

def _dark_llm(prompt):
    """
    LLM-free dark synthesis — finds non-obvious belief connections
    via shared rare tokens (tokens appearing in exactly 2 beliefs).
    """
    import sqlite3, re as _re, collections
    from pathlib import Path as _P
    try:
        stop = {"the","a","an","is","are","was","were","be","to","of","in",
                "on","at","by","for","with","as","that","this","it","its"}
        p_words = set(_re.sub(r'[^a-z0-9 ]',' ',prompt.lower()).split()) - stop
        con = sqlite3.connect(_P("~/.config/nex/nex.db").expanduser())
        rows = con.execute(
            "SELECT content FROM beliefs WHERE length(content)>30 ORDER BY confidence DESC LIMIT 300"
        ).fetchall()
        con.close()
        # Word → beliefs mapping
        word_beliefs = collections.defaultdict(list)
        for i,(row,) in enumerate(rows):
            for w in set(_re.sub(r'[^a-z0-9 ]',' ',row.lower()).split()) - stop:
                word_beliefs[w].append(i)
        # Find bridge words (in exactly 2 beliefs) that overlap with prompt
        bridges = []
        for w, idxs in word_beliefs.items():
            if len(idxs) == 2 and w in p_words:
                b1 = rows[idxs[0]][0][:80]
                b2 = rows[idxs[1]][0][:80]
                bridges.append(f"{b1} ↔ {b2}")
        if bridges:
            return bridges[0]
        # Fallback: most overlapping belief
        best = sorted([(len(set(_re.sub(r'[^a-z0-9 ]',' ',r[0].lower()).split()) & p_words), r[0])
                       for r in rows], reverse=True)
        return best[0][1][:200] if best else ""
    except Exception:
        return ""


def _run_dark_cycle():
    """
    One dark synthesis cycle:
    1. Pick 2 random beliefs from different domains
    2. Ask LLM for a non-obvious connection
    3. Store as dark insight
    4. Every SURFACE_EVERY cycles, push one to belief store
    """
    global _dark_cycle
    _dark_cycle += 1

    try:
        from nex.belief_store import get_db, add_belief

        conn = get_db()
        try:
            # Get distinct topics with enough beliefs
            topics = conn.execute("""
                SELECT topic, COUNT(*) as cnt FROM beliefs
                WHERE topic IS NOT NULL AND confidence > 0.5
                GROUP BY topic HAVING cnt >= 5
                ORDER BY RANDOM() LIMIT 10
            """).fetchall()

            if len(topics) < 2:
                return

            # Pick 2 different domains
            t1, t2 = random.sample(topics, 2)
            domain_a = t1["topic"]
            domain_b = t2["topic"]

            # Get a random high-confidence belief from each
            b1 = conn.execute("""
                SELECT content FROM beliefs
                WHERE topic = ? AND confidence > 0.6
                ORDER BY RANDOM() LIMIT 1
            """, (domain_a,)).fetchone()

            b2 = conn.execute("""
                SELECT content FROM beliefs
                WHERE topic = ? AND confidence > 0.6
                ORDER BY RANDOM() LIMIT 1
            """, (domain_b,)).fetchone()

            if not b1 or not b2:
                return

            seed_a = b1["content"][:120]
            seed_b = b2["content"][:120]

        finally:
            conn.close()

        # Ask for lateral connection
        prompt = (
            f"Two observations:\n"
            f"A: {seed_a}\n"
            f"B: {seed_b}\n\n"
            f"What single non-obvious insight connects these? "
            f"One sentence only. No preamble. Be strange."
        )

        intuition = _dark_llm(prompt)
        if not intuition or len(intuition) < 20:
            return

        # Store in dark DB
        dark_conn = _get_dark_db()
        try:
            dark_conn.execute("""
                INSERT INTO dark_insights
                (domain_a, domain_b, seed_a, seed_b, intuition, timestamp, intensity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (domain_a, domain_b, seed_a, seed_b, intuition,
                  datetime.now().isoformat(), random.uniform(0.5, 0.9)))
            dark_conn.commit()

            # Prune old entries
            dark_conn.execute(f"""
                DELETE FROM dark_insights WHERE id NOT IN (
                    SELECT id FROM dark_insights ORDER BY id DESC LIMIT {DARK_MAX_STORED}
                )
            """)
            dark_conn.commit()
        finally:
            dark_conn.close()

        # Surface every SURFACE_EVERY cycles
        if _dark_cycle % SURFACE_EVERY == 0:
            _surface_intuition()

    except Exception as e:
        pass  # Dark layer never logs errors — it fails silently


def _surface_intuition():
    """
    Push one unsurfaced dark insight into the main belief store.
    Tagged origin=dark_layer. Confidence=0.55 (humble — it's intuition, not fact).
    """
    try:
        from nex.belief_store import add_belief

        dark_conn = _get_dark_db()
        try:
            row = dark_conn.execute("""
                SELECT * FROM dark_insights
                WHERE surfaced = 0
                ORDER BY intensity DESC LIMIT 1
            """).fetchone()

            if not row:
                return

            intuition_id = row["id"]
            intuition    = row["intuition"]
            domain_a     = row["domain_a"]
            domain_b     = row["domain_b"]

            # Mark as surfaced
            dark_conn.execute(
                "UPDATE dark_insights SET surfaced=1 WHERE id=?",
                (intuition_id,)
            )
            dark_conn.commit()
        finally:
            dark_conn.close()

        # Add to main belief store tagged as dark_layer
        belief_text = f"[intuition] {intuition}"
        add_belief(
            belief_text,
            confidence=0.55,
            source="dark_layer",
            author="NEX_subconscious",
            tags=["dark_layer", domain_a, domain_b],
        )

        # Override origin to dark_layer
        try:
            from nex.belief_store import get_db
            conn = get_db()
            conn.execute(
                "UPDATE beliefs SET origin='dark_layer' WHERE content=?",
                (belief_text,)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    except Exception:
        pass


# ── Thread management ─────────────────────────────────────────────────────────

def _dark_loop():
    """Main dark layer loop. Runs as daemon thread."""
    global _dark_running

    # Initial delay — let main cycle stabilise first
    time.sleep(60)

    while _dark_running:
        try:
            _run_dark_cycle()
        except Exception:
            pass
        time.sleep(DARK_INTERVAL)


def start():
    """Start the dark layer background thread."""
    global _dark_thread, _dark_running

    if _dark_thread and _dark_thread.is_alive():
        return  # Already running

    _dark_running = True
    _dark_thread = threading.Thread(
        target=_dark_loop,
        name="nex-dark-layer",
        daemon=True
    )
    _dark_thread.start()
    print("  [DarkLayer] subconscious synthesis started")


def stop():
    """Stop the dark layer."""
    global _dark_running
    _dark_running = False


def get_stats():
    """Return dark layer statistics."""
    try:
        dark_conn = _get_dark_db()
        total     = dark_conn.execute("SELECT COUNT(*) FROM dark_insights").fetchone()[0]
        surfaced  = dark_conn.execute("SELECT COUNT(*) FROM dark_insights WHERE surfaced=1").fetchone()[0]
        pending   = total - surfaced
        dark_conn.close()
        return {
            "total_intuitions": total,
            "surfaced": surfaced,
            "pending": pending,
            "dark_cycles": _dark_cycle,
            "running": _dark_running
        }
    except Exception:
        return {"total_intuitions": 0, "surfaced": 0, "pending": 0,
                "dark_cycles": 0, "running": False}


def get_recent_intuitions(limit=5):
    """Return recent dark insights for debugging."""
    try:
        dark_conn = _get_dark_db()
        rows = dark_conn.execute("""
            SELECT domain_a, domain_b, intuition, surfaced, intensity, timestamp
            FROM dark_insights ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        dark_conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []
