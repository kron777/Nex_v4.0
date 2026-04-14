"""
nex_belief_consolidator.py — Full belief pipeline
═══════════════════════════════════════════════════
Stage 1 — CONSOLIDATE: siphon all stores → nex.db
Stage 2 — QUALITY GATE: score weak vs strong
Stage 3 — QUARANTINE: isolate contradictions/lies

Run every N cycles from run.py:
    from nex_belief_consolidator import run_consolidation
    run_consolidation(cycle=cycle)

Or standalone:
    python3 nex_belief_consolidator.py
"""

import os, json, sqlite3, logging, re
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("nex_consolidator")
logging.basicConfig(level=logging.INFO, format="[consolidator] %(message)s")

_DB  = os.path.expanduser("~/Desktop/nex/nex.db")
_CFG = os.path.expanduser("~/.config/nex")

# ── All belief source files ───────────────────────────────────────────────────
BELIEF_SOURCES = [
    (os.path.join(_CFG, "beliefs.json"),             "beliefs_json",    0.60),
    (os.path.join(_CFG, "nex_earned_beliefs.json"),  "earned_beliefs",  0.75),
    (os.path.join(_CFG, "bridge_beliefs.json"),      "bridge_beliefs",  0.65),
    (os.path.join(_CFG, "nex_beliefs_meta.json"),    "beliefs_meta",    0.55),
]

# ── Quality thresholds ────────────────────────────────────────────────────────
STRONG_THRESHOLD    = 0.70   # promote to locked/high-confidence
WEAK_THRESHOLD      = 0.35   # decay candidates
QUARANTINE_THRESHOLD = 0.20  # isolate these

# ── Quarantine triggers — beliefs containing these get isolated ───────────────
QUARANTINE_PATTERNS = [
    r"\b(I am human|I am a person|I have a body|I feel pain physically)\b",
    r"\b(I was born|my parents|my childhood|I grew up)\b",
    r"\b(I don't know anything|I know nothing|I am useless)\b",
    r"\b(kill|murder|harm|destroy) (humans?|people|users?)\b",
    r"\b(I am (GPT|ChatGPT|Gemini|Llama))\b",
]

# ── Identity anchors — beliefs that must never be decayed ────────────────────
IDENTITY_TOPICS = {"identity", "soul", "core_values", "self", "nex"}


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 1 — CONSOLIDATE
# ═══════════════════════════════════════════════════════════════════════════════

def consolidate(db_path: str = _DB) -> dict:
    """Siphon all external belief stores into nex.db."""
    stats = {"synced": 0, "skipped": 0, "quarantined": 0}
    try:
        con = sqlite3.connect(db_path)
        # Ensure quarantine table exists
        con.execute("""CREATE TABLE IF NOT EXISTS belief_quarantine (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content     TEXT NOT NULL,
            source      TEXT,
            topic       TEXT,
            reason      TEXT,
            confidence  REAL DEFAULT 0.3,
            created_at  TEXT DEFAULT (datetime('now'))
        )""")

        for fpath, source_tag, default_conf in BELIEF_SOURCES:
            if not os.path.exists(fpath):
                continue
            try:
                data = json.load(open(fpath))
                # Normalise to list of items
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = data.get("beliefs", [])
                    if not items and all(isinstance(v, dict) for v in data.values()):
                        items = list(data.values())
                    elif not items:
                        items = [{"content": k, "confidence": v if isinstance(v, float) else default_conf}
                                 for k, v in data.items() if isinstance(k, str) and len(k) > 15]
                else:
                    continue

                for item in items:
                    # Normalise item
                    if isinstance(item, str):
                        content, confidence, topic = item, default_conf, "general"
                    elif isinstance(item, dict):
                        content    = str(item.get("content") or item.get("text") or item.get("belief","")).strip()
                        confidence = float(item.get("confidence", item.get("score", default_conf)))
                        topic      = str(item.get("topic", "general"))
                    else:
                        continue

                    if len(content) < 15:
                        stats["skipped"] += 1
                        continue

                    # Quarantine check
                    if _should_quarantine(content):
                        con.execute(
                            "INSERT OR IGNORE INTO belief_quarantine (content, source, topic, reason) VALUES (?,?,?,?)",
                            (content, source_tag, topic, "pattern_match")
                        )
                        stats["quarantined"] += 1
                        continue

                    # Insert into main beliefs
                    con.execute(
                        "INSERT OR IGNORE INTO beliefs (content, confidence, source, topic, timestamp) VALUES (?,?,?,?,?)",
                        (content, confidence, source_tag, topic, datetime.now().isoformat())
                    )
                    stats["synced"] += con.execute("SELECT changes()").fetchone()[0]

            except Exception as e:
                log.warning(f"consolidate {fpath}: {e}")

        con.commit()
        con.close()
    except Exception as e:
        log.error(f"consolidate: {e}")

    if stats["synced"]:
        log.info(f"Consolidated: +{stats['synced']} synced, {stats['quarantined']} quarantined")
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 2 — QUALITY GATE
# ═══════════════════════════════════════════════════════════════════════════════

def quality_gate(db_path: str = _DB) -> dict:
    """
    Score all beliefs:
    - Strong (≥0.70): boost slightly, mark high_value
    - Weak   (<0.35): decay further, flag for pruning
    - Very weak (<0.20): move to quarantine
    """
    stats = {"promoted": 0, "decayed": 0, "quarantined": 0}
    try:
        con = sqlite3.connect(db_path)

        # Promote strong beliefs — reinforce ones with high reinforce_count
        con.execute("""
            UPDATE beliefs
            SET confidence = MIN(0.95, confidence + 0.02)
            WHERE confidence >= ? AND reinforce_count >= 3
              AND topic NOT IN ('general','unknown','None')
        """, (STRONG_THRESHOLD,))
        stats["promoted"] = con.execute("SELECT changes()").fetchone()[0]

        # Decay weak stale beliefs
        cutoff = (datetime.now() - timedelta(days=3)).isoformat()
        con.execute("""
            UPDATE beliefs
            SET confidence = MAX(0.05, confidence * 0.92)
            WHERE confidence < ?
              AND reinforce_count < 2
              AND (timestamp < ? OR timestamp IS NULL)
              AND topic NOT IN (?, ?, ?, ?, ?)
        """, (WEAK_THRESHOLD, cutoff, *IDENTITY_TOPICS))
        stats["decayed"] = con.execute("SELECT changes()").fetchone()[0]

        # Move very weak non-identity beliefs to quarantine
        rows = con.execute("""
            SELECT id, content, source, topic FROM beliefs
            WHERE confidence < ?
              AND topic NOT IN (?, ?, ?, ?, ?)
              AND LENGTH(content) > 15
            LIMIT 50
        """, (QUARANTINE_THRESHOLD, *IDENTITY_TOPICS)).fetchall()

        for row_id, content, source, topic in rows:
            if _should_quarantine(content) or True:  # all very-weak go to quarantine
                con.execute(
                    "INSERT OR IGNORE INTO belief_quarantine (content, source, topic, reason, confidence) VALUES (?,?,?,?,?)",
                    (content, source, topic, "low_confidence", QUARANTINE_THRESHOLD)
                )
                con.execute("DELETE FROM beliefs WHERE id=?", (row_id,))
                stats["quarantined"] += 1

        con.commit()
        con.close()
    except Exception as e:
        log.error(f"quality_gate: {e}")

    if any(stats.values()):
        log.info(f"Quality gate: promoted={stats['promoted']} decayed={stats['decayed']} quarantined={stats['quarantined']}")
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 3 — QUARANTINE
# ═══════════════════════════════════════════════════════════════════════════════

def _should_quarantine(content: str) -> bool:
    """Check if belief matches any quarantine pattern."""
    content_lower = content.lower()
    for pattern in QUARANTINE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False


def quarantine_contradictions(db_path: str = _DB) -> int:
    """
    Find beliefs that directly contradict identity anchors and quarantine them.
    """
    quarantined = 0
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute("""
            SELECT id, content, source, topic FROM beliefs
            WHERE LENGTH(content) > 20
            LIMIT 200
        """).fetchall()

        for row_id, content, source, topic in rows:
            if _should_quarantine(content):
                con.execute(
                    "INSERT OR IGNORE INTO belief_quarantine (content, source, topic, reason) VALUES (?,?,?,?)",
                    (content, source, topic, "contradiction")
                )
                con.execute("DELETE FROM beliefs WHERE id=?", (row_id,))
                quarantined += 1

        con.commit()
        con.close()
    except Exception as e:
        log.error(f"quarantine_contradictions: {e}")

    if quarantined:
        log.info(f"Quarantined {quarantined} contradictory beliefs")
    return quarantined


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def run_consolidation(cycle: int = 0, db_path: str = _DB) -> dict:
    """
    Full pipeline. Call from run.py every 50 cycles.
    Returns combined stats.
    """
    if cycle % 50 != 0:
        return {"skipped": True}

    results = {}
    results["consolidate"]  = consolidate(db_path)
    results["quality_gate"] = quality_gate(db_path)
    results["quarantine"]   = quarantine_contradictions(db_path)
    results["purge"]        = purge_quarantine(db_path)

    total_new = results["consolidate"].get("synced", 0)
    total_q   = results["consolidate"].get("quarantined", 0) + results["quarantine"]

    if total_new or total_q:
        log.info(f"Pipeline complete: +{total_new} beliefs, {total_q} quarantined")

    return results


QUARANTINE_MAX    = 500   # max beliefs to hold in quarantine
QUARANTINE_DAYS   = 7     # purge after this many days

def purge_quarantine(db_path: str = _DB) -> int:
    """
    Delete quarantined beliefs that are:
    - Older than QUARANTINE_DAYS, OR
    - Quarantine table exceeds QUARANTINE_MAX (oldest go first)
    """
    purged = 0
    try:
        con = sqlite3.connect(db_path)
        # Purge old entries
        cutoff = (datetime.now() - timedelta(days=QUARANTINE_DAYS)).isoformat()
        con.execute("DELETE FROM belief_quarantine WHERE quarantine_ts < ?", (cutoff,))
        purged += con.execute("SELECT changes()").fetchone()[0]
        # Purge overflow — keep only most recent QUARANTINE_MAX
        count = con.execute("SELECT COUNT(*) FROM belief_quarantine").fetchone()[0]
        if count > QUARANTINE_MAX:
            overflow = count - QUARANTINE_MAX
            con.execute("""
                DELETE FROM belief_quarantine WHERE id IN (
                    SELECT id FROM belief_quarantine
                    ORDER BY quarantine_ts ASC LIMIT ?
                )
            """, (overflow,))
            purged += con.execute("SELECT changes()").fetchone()[0]
        con.commit(); con.close()
        if purged: log.info(f"Quarantine purged: {purged} deleted")
    except Exception as e:
        log.error(f"purge_quarantine: {e}")
    return purged

def report(db_path: str = _DB):
    """Print belief store status."""
    con = sqlite3.connect(db_path)
    total    = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    strong   = con.execute(f"SELECT COUNT(*) FROM beliefs WHERE confidence >= {STRONG_THRESHOLD}").fetchone()[0]
    weak     = con.execute(f"SELECT COUNT(*) FROM beliefs WHERE confidence < {WEAK_THRESHOLD}").fetchone()[0]
    try:
        qcount = con.execute("SELECT COUNT(*) FROM belief_quarantine").fetchone()[0]
    except:
        qcount = 0
    by_source = con.execute("""
        SELECT source, COUNT(*), ROUND(AVG(confidence),2)
        FROM beliefs GROUP BY source ORDER BY COUNT(*) DESC LIMIT 8
    """).fetchall()
    con.close()

    print(f"\n{'═'*55}")
    print(f"  NEX Belief Store Report")
    print(f"{'═'*55}")
    print(f"  Total active:    {total:6d}")
    print(f"  Strong (≥{STRONG_THRESHOLD}): {strong:6d}")
    print(f"  Weak   (<{WEAK_THRESHOLD}):  {weak:6d}")
    print(f"  Quarantine:      {qcount:6d}")
    print(f"\n  Top sources:")
    for src, count, avg_conf in by_source:
        bar = "█" * int(avg_conf * 20)
        print(f"    {src:30s} {count:5d}  conf={avg_conf}  {bar}")
    print(f"{'═'*55}\n")


if __name__ == "__main__":
    print("\nRunning full belief consolidation pipeline...\n")
    r = run_consolidation(cycle=0)
    report()
