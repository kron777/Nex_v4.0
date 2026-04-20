"""
nex_upgrades.py — NEX Critical Upgrades U1–U12
Drop this in ~/Desktop/nex/nex/ and import from orchestrator or run.py
"""
import sqlite3, time, logging
from pathlib import Path

DB_PATH = Path.home() / ".config/nex/nex.db"
log = logging.getLogger("nex.upgrades")

# ── U3: active topic vector ───────────────────────────────────────────────────
_active_topic: str | None = None
_topic_set_cycle: int = 0
TOPIC_DECAY_CYCLES = 10  # topic expires after N cycles of no reinforcement

def set_active_topic(topic: str, cycle: int):
    global _active_topic, _topic_set_cycle
    _active_topic = topic
    _topic_set_cycle = cycle
    log.info(f"[U3] Active topic set: '{topic}' cycle={cycle}")

def get_active_topic(current_cycle: int):
    if _active_topic and (current_cycle - _topic_set_cycle) < TOPIC_DECAY_CYCLES:
        return _active_topic
    return None

def u3_topic_alignment_penalty(content: str, confidence: float, current_cycle: int) -> float:
    """Reduce confidence of off-topic incoming beliefs by 20%."""
    topic = get_active_topic(current_cycle)
    if not topic:
        return confidence
    if topic.lower() in content.lower():
        return confidence
    penalized = round(confidence * 0.80, 4)
    log.info(f"[U3] Off-topic penalty: {confidence:.3f}→{penalized:.3f}")
    return penalized

def u3_drift_check(db_path=None, current_cycle: int = 0) -> bool:
    """Returns True if top ingested topic last 10 cycles != active topic."""
    topic = get_active_topic(current_cycle)
    if not topic:
        return False
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    row = conn.execute("""
        SELECT topic, COUNT(*) as ct FROM beliefs
        WHERE last_used_cycle >= ?
        GROUP BY topic ORDER BY ct DESC LIMIT 1
    """, (max(0, current_cycle - 10),)).fetchone()
    conn.close()
    if row and row["topic"] != topic:
        log.warning(f"[U3] DRIFT detected — dominant='{row['topic']}' active='{topic}'")
        return True
    return False


# ── U1: belief locking ────────────────────────────────────────────────────────
def u1_lock_top_beliefs(n: int = 30, db_path=None):
    """Lock top N beliefs by composite score. Run every 50 cycles."""
    import time as _t
    path = db_path or DB_PATH
    for _attempt in range(2):
        try:
            conn = sqlite3.connect(str(path), timeout=5, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("""
                UPDATE beliefs SET locked = CASE
                    WHEN id IN (
                        SELECT id FROM beliefs
                        ORDER BY (confidence * (successful_uses + 1)) DESC
                        LIMIT ?
                    ) THEN 1 ELSE locked END
            """, (n,))
            conn.commit()
            conn.close()
            log.info(f"[U1] Locked top {n} beliefs")
            return
        except sqlite3.OperationalError as _e:
            if "locked" in str(_e) and _attempt < 1:
                _t.sleep(1 + _attempt)
            else:
                log.warning(f"[U1] lock_top_beliefs failed after {_attempt+1} attempts: {_e}")
                try: conn.close()
                except: pass
                return

def u1_is_locked(belief_id: int, db_path=None) -> bool:
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    row = conn.execute("SELECT locked FROM beliefs WHERE id=?", (belief_id,)).fetchone()
    conn.close()
    return bool(row and row[0])


# ── U2: contradiction resolution ──────────────────────────────────────────────
def u2_run_contradiction_resolution(llm_fn, db_path=None, limit: int = 5):
    """
    Find belief pairs on same topic with confidence spread > 0.4.
    Call llm_fn(prompt)->str for resolution decision.
    Decisions: MERGE / OVERRIDE_A / OVERRIDE_B / SPLIT / UNCERTAINTY
    """
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS u2_reviewed (aid INTEGER, bid INTEGER, decision TEXT, reviewed_at REAL, PRIMARY KEY (aid,bid))")
    pairs = conn.execute("""
        SELECT a.id as aid, a.content as ac, a.confidence as aconf,
               b.id as bid, b.content as bc, b.confidence as bconf,
               a.topic
        FROM beliefs a JOIN beliefs b
          ON a.topic = b.topic AND a.id < b.id
         AND a.locked = 0 AND b.locked = 0 AND a.topic NOT IN ('identity','agency','theory_x','core','self_location','nex_core','vantage','self','consciousness')
        WHERE ABS(a.confidence - b.confidence) > 0.40
          AND NOT EXISTS (SELECT 1 FROM u2_reviewed r WHERE r.aid=a.id AND r.bid=b.id AND r.reviewed_at > strftime('%s','now')-604800)
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    resolved = 0
    for row in pairs:
        prompt = (
            f"Two NEX beliefs on topic '{row['topic']}' conflict:\n"
            f"A (conf={row['aconf']:.2f}): {row['ac']}\n"
            f"B (conf={row['bconf']:.2f}): {row['bc']}\n"
            f"Respond with ONE word: MERGE / OVERRIDE_A / OVERRIDE_B / UNCERTAINTY"
        )
        try:
            decision = llm_fn(prompt).strip().upper().split()[0]
            _u2_apply(row, decision, path)
            resolved += 1
        except Exception as e:
            log.warning(f"[U2] resolution error: {e}")
    if resolved:
        log.info(f"[U2] Resolved {resolved} contradictions")
    return resolved

def _u2_apply(row, decision: str, path):
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    try:
        if decision == "OVERRIDE_A":
            conn.execute("UPDATE beliefs SET confidence=MIN(confidence+0.05,0.95) WHERE id=?", (row["aid"],))
            conn.execute("UPDATE beliefs SET confidence=MAX(confidence-0.10,0.10) WHERE id=? AND locked=0", (row["bid"],))
        elif decision == "OVERRIDE_B":
            conn.execute("UPDATE beliefs SET confidence=MIN(confidence+0.05,0.95) WHERE id=?", (row["bid"],))
            conn.execute("UPDATE beliefs SET confidence=MAX(confidence-0.10,0.10) WHERE id=? AND locked=0", (row["aid"],))
        elif decision == "MERGE":
            avg = round((row["aconf"] + row["bconf"]) / 2, 4)
            conn.execute("UPDATE beliefs SET confidence=? WHERE id=?", (avg, row["aid"]))
            conn.execute("DELETE FROM beliefs WHERE id=? AND locked=0", (row["bid"],))
        elif decision == "UNCERTAINTY":
            conn.execute("UPDATE beliefs SET confidence=0.35 WHERE id IN (?,?) AND locked=0",
                         (row["aid"], row["bid"]))
        import time
        conn.execute("INSERT OR REPLACE INTO u2_reviewed (aid,bid,decision,reviewed_at) VALUES (?,?,?,?)", (row["aid"], row["bid"], decision, time.time()))
        conn.commit()
        log.info(f"[U2] {decision} on topic='{row['topic']}'")
    finally:
        conn.close()


# ── U4: cognition throttle ────────────────────────────────────────────────────
_reflection_pattern_counts: dict[str, int] = {}
_cycle_reflection_count: dict[int, int] = {}
MAX_REFLECTIONS_PER_CYCLE = 8
DIMINISHING_RETURN_THRESHOLD = 3  # same pattern N times → suppress

def u4_should_reflect(pattern_key: str, current_cycle: int) -> bool:
    """
    Returns True if this reflection is permitted.
    Blocks: >MAX_REFLECTIONS_PER_CYCLE total, or repeated pattern.
    """
    cycle_count = _cycle_reflection_count.get(current_cycle, 0)
    if cycle_count >= MAX_REFLECTIONS_PER_CYCLE:
        log.info(f"[U4] Cycle reflection cap hit ({cycle_count})")
        return False
    pat_count = _reflection_pattern_counts.get(pattern_key, 0)
    if pat_count >= DIMINISHING_RETURN_THRESHOLD:
        log.info(f"[U4] Diminishing return suppressed: '{pattern_key}' ({pat_count}x)")
        return False
    _cycle_reflection_count[current_cycle] = cycle_count + 1
    _reflection_pattern_counts[pattern_key] = pat_count + 1
    return True

def u4_reset_cycle(current_cycle: int):
    """Call at start of each cycle."""
    _cycle_reflection_count[current_cycle] = 0
    # Decay pattern memory every 10 cycles
    if current_cycle % 10 == 0:
        for k in list(_reflection_pattern_counts):
            _reflection_pattern_counts[k] = max(0, _reflection_pattern_counts[k] - 1)


# ── U5: confidence reweighting ────────────────────────────────────────────────
def u5_reweight_confidence(db_path=None, cycle: int = 0):
    """
    Gradually raise confidence for stable beliefs:
    - survived >20 cycles without contradiction flag
    - referenced from multiple sources
    Run every 10 cycles.
    """
    if cycle % 10 != 0:
        return 0
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    try:
        # Stable = old, not loop-flagged, used at least twice, not locked already
        conn.execute("""
            UPDATE beliefs
            SET confidence = MIN(confidence + 0.02, 0.90)
            WHERE loop_flag = 0
              AND locked = 0
              AND successful_uses >= 2
              AND birth_cycle <= ?
              AND confidence < 0.80
        """, (max(0, cycle - 20),))
        count = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        if count:
            log.info(f"[U5] Stability boost: {count} beliefs +0.02")
        return count
    finally:
        conn.close()


# ── U6: insight → belief pipeline ────────────────────────────────────────────
# Requires insights table — adds expires_at and belief_id FK
def u6_migrate_insights(db_path=None):
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS insights (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                content     TEXT NOT NULL,
                created_at  TEXT,
                expires_at  TEXT,
                belief_id   INTEGER DEFAULT NULL,
                attached    INTEGER DEFAULT 0
            )
        """)
        # Add columns if insights table existed already
        for col, typedef in [("expires_at","TEXT"), ("belief_id","INTEGER DEFAULT NULL"), ("attached","INTEGER DEFAULT 0")]:
            try:
                conn.execute(f"ALTER TABLE insights ADD COLUMN {col} {typedef}")
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()

def u6_add_insight(content: str, ttl_cycles: int = 20, db_path=None):
    """Add an insight with a TTL. Must attach to a belief or it expires."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute("""
        INSERT OR IGNORE INTO insights (content, created_at, expires_at, attached)
        VALUES (?, ?, ?, 0)
    """, (content.strip(), now, str(ttl_cycles)))
    conn.commit()
    conn.close()

def u6_attach_insight(insight_id: int, belief_id: int, db_path=None):
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.execute("UPDATE insights SET attached=1, belief_id=? WHERE id=?",
                 (belief_id, insight_id))
    conn.commit()
    conn.close()

def u6_prune_expired_insights(current_cycle: int, db_path=None):
    """Delete unattached insights past their TTL (ttl stored as cycle count in expires_at)."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, expires_at, created_at FROM insights WHERE attached=0").fetchall()
    pruned = 0
    for row in rows:
        try:
            ttl = int(row["expires_at"])
            # Use cycle-based expiry: if ttl cycles have passed since created_at row count
            # Simple proxy: expires_at as absolute cycle number
            if current_cycle >= ttl:
                conn.execute("DELETE FROM insights WHERE id=?", (row["id"],))
                pruned += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    if pruned:
        log.info(f"[U6] Pruned {pruned} expired unattached insights")
    return pruned


# ── U7: memory pruning ────────────────────────────────────────────────────────
def u7_compress_memory(db_path=None, target_floor: int = 500, cycle: int = 0):
    """
    Remove low-confidence, zero-use, non-locked beliefs above floor.
    More aggressive than nex_knowledge_filter — runs every 25 cycles.
    """
    if cycle % 25 != 0:
        return 0
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    try:
        conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()
        total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        if total <= target_floor:
            conn.close()
            return 0
        removable = total - target_floor
        conn.execute("""
            DELETE FROM beliefs WHERE id IN (
                SELECT id FROM beliefs
                WHERE locked = 0
                  AND successful_uses = 0
                  AND confidence < 0.35
                  AND is_identity = 0
                ORDER BY confidence ASC
                LIMIT ?
            )
        """, (removable,))
        removed = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        if removed:
            log.info(f"[U7] Memory compress: removed {removed} zero-use low-conf beliefs")
        return removed
    finally:
        conn.close()


# ── U8: directive priority stack ─────────────────────────────────────────────
DIRECTIVE_PRIORITY = {
    "D20": 1,   # collapse detector — critical
    "D6":  2,   # inflation gate — critical
    "D17": 3,   # floor protection — critical
    "D7":  4,   # temporal decay — important
    "D14": 5,   # loop detection — important
    "D16": 6,   # loop escalation — important
    "D12": 7,   # reinforce cap — passive
    "U1":  8,   # belief locking — passive
    "U3":  9,   # topic alignment — passive
}

def u8_get_active_directives(max_rank: int = 7) -> list[str]:
    """Return directives at or above max_rank (lower = higher priority)."""
    return [d for d, r in sorted(DIRECTIVE_PRIORITY.items(), key=lambda x: x[1])
            if r <= max_rank]


# ── U9: intent layer ──────────────────────────────────────────────────────────
_current_intent: dict = {}

def u9_set_intent(intent: str, cycle: int, duration: int = 5):
    global _current_intent
    _current_intent = {"intent": intent, "set_at": cycle, "duration": duration}
    log.info(f"[U9] Intent set: '{intent}' for {duration} cycles")

def u9_get_intent(current_cycle: int) -> str | None:
    if not _current_intent:
        return None
    elapsed = current_cycle - _current_intent.get("set_at", 0)
    if elapsed > _current_intent.get("duration", 5):
        return None
    return _current_intent.get("intent")

def u9_intent_score(content: str, current_cycle: int) -> float:
    """Returns 0.0–1.0 alignment score with current intent."""
    intent = u9_get_intent(current_cycle)
    if not intent:
        return 0.5  # neutral
    words = set(intent.lower().split())
    content_words = set(content.lower().split())
    overlap = len(words & content_words)
    return min(1.0, 0.5 + (overlap / max(len(words), 1)) * 0.5)


# ── U10: stability guardrails ─────────────────────────────────────────────────
def u10_stability_check(db_path=None, current_cycle: int = 0) -> dict:
    """
    Checks instability signals. Returns action dict.
    Triggers fallback mode if multiple signals fire simultaneously.
    """
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    avg_conf = conn.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0] or 0
    loop_count = conn.execute("SELECT COUNT(*) FROM beliefs WHERE loop_flag=1").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    conn.close()

    signals = []
    if avg_conf < 0.33:
        signals.append("low_avg_conf")
    if loop_count > 10:
        signals.append("excessive_loops")
    drift = u3_drift_check(path, current_cycle)
    if drift:
        signals.append("topic_drift")

    if len(signals) >= 2:
        log.warning(f"[U10] INSTABILITY signals={signals} — fallback mode")
        return {"mode": "fallback", "signals": signals,
                "action": "reduce_cognition_reinforce_core"}
    return {"mode": "stable", "signals": signals}


# ── U11: output grounding check ───────────────────────────────────────────────
def u11_ground_output(response: str, db_path=None, min_overlap: int = 1) -> bool:
    """
    Returns True if response content overlaps with at least min_overlap
    high-confidence beliefs. Flags abstract drift if False.
    """
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    top = conn.execute("""
        SELECT content FROM beliefs
        WHERE confidence > 0.60 ORDER BY confidence DESC LIMIT 50
    """).fetchall()
    conn.close()
    response_words = set(response.lower().split())
    hits = 0
    for row in top:
        belief_words = set(row["content"].lower().split())
        if len(response_words & belief_words) >= 3:
            hits += 1
        if hits >= min_overlap:
            return True
    log.warning(f"[U11] Output not grounded — overlap hits={hits}")
    return False


# ── U12: social signal filtering ─────────────────────────────────────────────
_agent_accuracy: dict[str, float] = {}  # agent_id → rolling accuracy 0–1

def u12_record_agent_signal(agent_id: str, content: str, was_accurate: bool):
    prev = _agent_accuracy.get(agent_id, 0.5)
    # Exponential moving average
    _agent_accuracy[agent_id] = round(prev * 0.85 + (1.0 if was_accurate else 0.0) * 0.15, 4)
    log.info(f"[U12] Agent '{agent_id}' accuracy → {_agent_accuracy[agent_id]:.3f}")

def u12_weight_agent_input(agent_id: str, confidence: float) -> float:
    """Scale incoming confidence by agent's track record."""
    acc = _agent_accuracy.get(agent_id, 0.5)
    weighted = round(confidence * acc * 2, 4)  # acc=1.0 → no change, acc=0.5 → halved
    weighted = max(0.10, min(weighted, 0.95))
    log.info(f"[U12] Agent '{agent_id}' input weighted: {confidence:.3f}→{weighted:.3f}")
    return weighted

def u12_get_agent_scores() -> dict:
    return dict(sorted(_agent_accuracy.items(), key=lambda x: -x[1]))
