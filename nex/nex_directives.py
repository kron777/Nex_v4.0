"""
nex_directives.py — Enforced constraints: D6, D7, D12, D14, D16, D17, D20

DIRECTIVE 6  — LIMIT BELIEF INFLATION
DIRECTIVE 7  — TEMPORAL DECAY + near-death ID tracking
DIRECTIVE 12 — REINFORCEMENT CAP (new)
DIRECTIVE 14 — POSITIVE FEEDBACK LOOP DETECTION + ratio hardening
DIRECTIVE 16 — LOOP FLAG MEMORY / ESCALATING PENALTY (new)
DIRECTIVE 17 — FLOOR PROTECTION BY BELIEF TYPE (new)
DIRECTIVE 20 — CONFIDENCE COLLAPSE DETECTOR (new)
"""

import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("nex.directives")

# Optional nex_log hook — set at runtime from run.py
_nex_log_fn = None

def set_nex_log(fn):
    """Wire in run.py's nex_log so directive events appear in nex_brain.log."""
    global _nex_log_fn
    _nex_log_fn = fn

def _log(level, msg):
    """Unified logger — writes to both Python log and nex_brain.log."""
    if level == "warn":
        log.warning(msg)
    else:
        log.info(msg)
    if _nex_log_fn:
        try:
            _nex_log_fn("directives", msg)
        except Exception:
            pass

# ─── CONFIG ──────────────────────────────────────────────────────────────────

DB_PATH = Path.home() / ".config/nex/nex.db"

# D6
BELIEF_CAP            = 1500
BELIEF_FLOOR          = 500
STRONG_EVIDENCE_CONF  = 0.72
EVICTION_HEADROOM     = 50

# D7
DECAY_RATE            = 0.008
DECAY_FLOOR           = 0.10
DECAY_DEATH_THRESHOLD = 0.08
DECAY_GRACE_CYCLES    = 3
DECAY_SUCCESS_SHIELD  = 3

# D12
D12_MAX_REINFORCEMENTS = 8
D12_WINDOW_CYCLES      = 20

# D14
D14_LOOP_THRESHOLD    = 5
D14_PENALTY           = 0.08
D14_SUPPRESS_FLOOR    = 0.30
D14_RATIO_THRESHOLD   = 5.0

# D16
D16_ESCALATION_PENALTY = 0.05
D16_MAX_EPISODES       = 3

# D17
D17_IDENTITY_RESERVE  = 50
D17_SUCCESS_RESERVE   = 100
D17_SUCCESS_THRESHOLD = 5

# D20
D20_CONF_DROP_THRESHOLD = 0.08
D20_NEAR_DEATH_SPIKE    = 30
D20_FREEZE_CYCLES       = 5

# Module-level freeze flag
_decay_frozen_until = 0


# ─── DB CONTEXT ──────────────────────────────────────────────────────────────

@contextmanager
def _conn(db_path=None):
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── SCHEMA MIGRATION ────────────────────────────────────────────────────────

def migrate(db_path=None):
    needed = {
        "last_used_cycle":        "INTEGER DEFAULT 0",
        "birth_cycle":            "INTEGER DEFAULT 0",
        "successful_uses":        "INTEGER DEFAULT 0",
        "reinforce_window_count": "INTEGER DEFAULT 0",
        "reinforce_window_start": "INTEGER DEFAULT 0",
        "reinforce_count":        "INTEGER DEFAULT 0",
        "outcome_count":          "INTEGER DEFAULT 0",
        "loop_flag":              "INTEGER DEFAULT 0",
        "last_reinforced_cycle":  "INTEGER DEFAULT 0",
        "loop_episodes":          "INTEGER DEFAULT 0",
        "is_identity":            "INTEGER DEFAULT 0",
    }
    with _conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(beliefs)")
        existing = {row["name"] for row in cur.fetchall()}
        for col, typedef in needed.items():
            if col not in existing:
                cur.execute(f"ALTER TABLE beliefs ADD COLUMN {col} {typedef}")
                _log("info", f"[migrate] Added: beliefs.{col}")

        # Mark identity-class beliefs
        cur.execute("""
            UPDATE beliefs SET is_identity = 1
            WHERE source IN ('identity','core_values','identity_defender','self_reflection')
               OR topic  IN ('identity','selfhood','autonomy','epistemic_honesty','agency')
        """)

        # KV table for D20 state
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nex_directive_kv (
                key TEXT PRIMARY KEY, value TEXT
            )
        """)
    _log("info", "[migrate] Complete.")


# ─── DIRECTIVE 6: INFLATION GATE ─────────────────────────────────────────────

def _d6_count(db_path=None):
    with _conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM beliefs")
        return cur.fetchone()[0]


def _d6_weakest_evictable(db_path=None):
    """Weakest belief that is not in a protected reserve."""
    with _conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM beliefs WHERE is_identity=1")
        id_ct = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM beliefs WHERE successful_uses>=?",
                    (D17_SUCCESS_THRESHOLD,))
        succ_ct = cur.fetchone()[0]

        exclude = []
        if id_ct < D17_IDENTITY_RESERVE:
            exclude.append("is_identity=1")
        if succ_ct < D17_SUCCESS_RESERVE:
            exclude.append(f"successful_uses>={D17_SUCCESS_THRESHOLD}")

        where = ("WHERE NOT (" + " OR ".join(exclude) + ")" if exclude else "")
        cur.execute(f"""
            SELECT id, confidence, topic FROM beliefs {where}
            ORDER BY confidence ASC, successful_uses ASC LIMIT 1
        """)
        return cur.fetchone()


def enforce_d6_before_insert(topic, content, confidence, current_cycle=0, db_path=None):
    count = _d6_count(db_path)
    if count < (BELIEF_CAP - EVICTION_HEADROOM):
        return True, "below_headroom"
    weakest = _d6_weakest_evictable(db_path)
    if count >= BELIEF_CAP:
        if confidence < STRONG_EVIDENCE_CONF:
            _log("warn", f"[D6] BLOCKED '{topic}' conf={confidence:.2f} at cap")
            return False, "cap_weak_evidence"
        if weakest and weakest["confidence"] >= confidence:
            _log("warn", f"[D6] BLOCKED '{topic}' weaker than evictable")
            return False, "weaker_than_evictable"
        with _conn(db_path) as conn:
            conn.cursor().execute("DELETE FROM beliefs WHERE id=?", (weakest["id"],))
        _log("info", f"[D6] Evicted id={weakest['id']} '{weakest['topic']}'")
        return True, "evicted"
    # headroom zone
    if confidence >= STRONG_EVIDENCE_CONF:
        return True, "strong_evidence"
    if weakest and weakest["confidence"] >= confidence:
        return False, "headroom_insufficient"
    with _conn(db_path) as conn:
        conn.cursor().execute("DELETE FROM beliefs WHERE id=?", (weakest["id"],))
    return True, "headroom_evicted"


# ─── DIRECTIVE 7: TEMPORAL DECAY ─────────────────────────────────────────────

def enforce_d7_decay_cycle(current_cycle, db_path=None):
    global _decay_frozen_until
    if current_cycle <= _decay_frozen_until:
        _log("info", f"[D7] Frozen until cycle {_decay_frozen_until}")
        return {"cycle": current_cycle, "decayed": 0, "pruned": 0,
                "shielded": 0, "near_death": [], "frozen": True}

    decayed = pruned = shielded = 0
    near_death = []

    with _conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, confidence, last_used_cycle, birth_cycle,
                   successful_uses, topic, is_identity
            FROM beliefs WHERE birth_cycle <= ?
        """, (current_cycle - DECAY_GRACE_CYCLES,))
        candidates = cur.fetchall()

        cur.execute("SELECT COUNT(*) FROM beliefs")
        total = cur.fetchone()[0]

        for row in candidates:
            bid      = row["id"]
            conf     = row["confidence"]
            idle     = current_cycle - row["last_used_cycle"]
            is_id    = row["is_identity"]

            if row["successful_uses"] >= DECAY_SUCCESS_SHIELD and idle <= DECAY_GRACE_CYCLES * 2:
                shielded += 1; continue
            if idle <= DECAY_GRACE_CYCLES:
                shielded += 1; continue

            rate     = DECAY_RATE * 0.5 if is_id else DECAY_RATE
            new_conf = max(round(conf - rate, 4), DECAY_FLOOR)

            cur.execute("SELECT COUNT(*) FROM beliefs")
            total = cur.fetchone()[0]

            if new_conf <= DECAY_DEATH_THRESHOLD and total > BELIEF_FLOOR:
                cur.execute("DELETE FROM beliefs WHERE id=?", (bid,))
                pruned += 1
            else:
                cur.execute("UPDATE beliefs SET confidence=? WHERE id=?", (new_conf, bid))
                if new_conf <= DECAY_FLOOR + 0.02:
                    near_death.append({"id": bid, "topic": row["topic"], "conf": new_conf})
                decayed += 1

    if near_death:
        _log("warn", f"[D7] Near-death ({len(near_death)}): "
                    + ", ".join(f"id={b['id']} '{b['topic']}' {b['conf']:.3f}"
                                for b in near_death[:5]))
    _log("info", f"[D7] cycle={current_cycle} decayed={decayed} pruned={pruned} "
             f"shielded={shielded} near_death={len(near_death)}")
    return {"cycle": current_cycle, "decayed": decayed, "pruned": pruned,
            "shielded": shielded, "near_death": near_death, "frozen": False}


def d7_resolve_id(content, db_path=None):
    """Resolve belief id from content string."""
    if not content:
        return None
    with _conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM beliefs WHERE content=? LIMIT 1", (content.strip(),))
        row = cur.fetchone()
        return row["id"] if row else None


def d7_mark_used(belief_id, current_cycle, successful=False, db_path=None):
    with _conn(db_path) as conn:
        cur = conn.cursor()
        if successful:
            cur.execute("""
                UPDATE beliefs
                SET last_used_cycle=?, successful_uses=successful_uses+1,
                    outcome_count=outcome_count+1
                WHERE id=?
            """, (current_cycle, belief_id))
        else:
            cur.execute("UPDATE beliefs SET last_used_cycle=? WHERE id=?",
                        (current_cycle, belief_id))


# ─── DIRECTIVE 12: REINFORCEMENT CAP ─────────────────────────────────────────

def enforce_d12_cap(belief_id, current_cycle, db_path=None):
    """Returns True if reinforcement allowed, False if capped."""
    with _conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT reinforce_window_count, reinforce_window_start
            FROM beliefs WHERE id=?
        """, (belief_id,))
        row = cur.fetchone()
        if not row:
            return True

        count   = row["reinforce_window_count"]
        w_start = row["reinforce_window_start"]

        if current_cycle - w_start >= D12_WINDOW_CYCLES:
            cur.execute("""
                UPDATE beliefs SET reinforce_window_count=1, reinforce_window_start=?
                WHERE id=?
            """, (current_cycle, belief_id))
            return True

        if count >= D12_MAX_REINFORCEMENTS:
            _log("info", f"[D12] Cap hit id={belief_id} ({count}/{D12_MAX_REINFORCEMENTS})")
            return False

        cur.execute("""
            UPDATE beliefs SET reinforce_window_count=reinforce_window_count+1
            WHERE id=?
        """, (belief_id,))
        return True


# ─── DIRECTIVE 14 + 16: LOOP DETECTION + ESCALATING PENALTY ──────────────────

def enforce_d14_check_loop(belief_id, current_cycle, db_path=None):
    """Returns (loop_detected: bool, new_conf: float|None)."""
    with _conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT confidence, reinforce_count, outcome_count,
                   loop_flag, loop_episodes, topic
            FROM beliefs WHERE id=?
        """, (belief_id,))
        row = cur.fetchone()
        if not row:
            return False, None

        conf     = row["confidence"]
        r_count  = row["reinforce_count"] + 1
        o_count  = row["outcome_count"]
        episodes = row["loop_episodes"]
        topic    = row["topic"]

        cur.execute("""
            UPDATE beliefs SET reinforce_count=?, last_reinforced_cycle=?
            WHERE id=?
        """, (r_count, current_cycle, belief_id))

        r_without = r_count - o_count
        ratio     = r_count / max(o_count, 1)

        loop = (r_without >= D14_LOOP_THRESHOLD or
                (o_count > 0 and ratio >= D14_RATIO_THRESHOLD and r_without >= 3))

        if loop:
            ep_penalty  = min(episodes, D16_MAX_EPISODES) * D16_ESCALATION_PENALTY
            total_pen   = D14_PENALTY + ep_penalty
            new_conf    = max(conf - total_pen, D14_SUPPRESS_FLOOR)
            cur.execute("""
                UPDATE beliefs SET confidence=?, loop_flag=1, loop_episodes=loop_episodes+1
                WHERE id=?
            """, (new_conf, belief_id))
            _log("warn", f"[D14/D16] LOOP id={belief_id} '{topic}' "
                        f"r={r_count} o={o_count} ratio={ratio:.1f} "
                        f"ep={episodes+1} conf {conf:.2f}→{new_conf:.2f}")
            return True, new_conf

        if row["loop_flag"] and o_count > 0:
            cur.execute("UPDATE beliefs SET loop_flag=0 WHERE id=?", (belief_id,))
        return False, None


def d14_sweep_flagged(current_cycle, db_path=None):
    penalized = 0
    with _conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, confidence, topic, outcome_count, loop_episodes
            FROM beliefs WHERE loop_flag=1
        """)
        flagged = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM beliefs")
        total = cur.fetchone()[0]

        for row in flagged:
            bid      = row["id"]
            conf     = row["confidence"]
            episodes = row["loop_episodes"]

            if row["outcome_count"] == 0:
                ep_pen   = min(episodes, D16_MAX_EPISODES) * D16_ESCALATION_PENALTY
                new_conf = max(conf - D14_PENALTY - ep_pen, DECAY_DEATH_THRESHOLD + 0.01)

                if episodes >= D16_MAX_EPISODES and total > BELIEF_FLOOR:
                    cur.execute("DELETE FROM beliefs WHERE id=?", (bid,))
                    _log("info", f"[D16] Evicted chronic id={bid} '{row['topic']}' ep={episodes}")
                    total -= 1
                elif new_conf <= DECAY_DEATH_THRESHOLD and total > BELIEF_FLOOR:
                    cur.execute("DELETE FROM beliefs WHERE id=?", (bid,))
                    total -= 1
                else:
                    cur.execute("UPDATE beliefs SET confidence=? WHERE id=?",
                                (new_conf, bid))
                penalized += 1
    return penalized


# ─── DIRECTIVE 20: COLLAPSE DETECTOR ─────────────────────────────────────────

def _d20_prev_conf(db_path=None):
    try:
        with _conn(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM nex_directive_kv WHERE key='d20_prev_conf'")
            row = cur.fetchone()
            return float(row["value"]) if row else None
    except Exception:
        return None


def _d20_save_conf(avg_conf, db_path=None):
    try:
        with _conn(db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO nex_directive_kv (key,value)
                VALUES ('d20_prev_conf',?)
            """, (str(avg_conf),))
    except Exception:
        pass


def enforce_d20_collapse_check(current_cycle, near_death_count, db_path=None):
    global _decay_frozen_until
    with _conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT AVG(confidence) FROM beliefs")
        avg_conf = cur.fetchone()[0] or 0.0

    prev = _d20_prev_conf(db_path)
    _d20_save_conf(avg_conf, db_path)

    if prev is None:
        return False, "baseline_set"

    drop     = prev - avg_conf
    collapse = drop >= D20_CONF_DROP_THRESHOLD or near_death_count >= D20_NEAR_DEATH_SPIKE

    if collapse:
        _decay_frozen_until = current_cycle + D20_FREEZE_CYCLES
        _log("warn", f"[D20] COLLAPSE cycle={current_cycle} "
                    f"conf {prev:.3f}→{avg_conf:.3f} drop={drop:.3f} "
                    f"near_death={near_death_count} "
                    f"— decay frozen until {_decay_frozen_until}")
        return True, f"frozen_until_{_decay_frozen_until}"

    return False, "ok"


# ─── UNIFIED ENFORCER ────────────────────────────────────────────────────────

class DirectiveEnforcer:
    def __init__(self, db_path=None, cycle=0):
        self.db_path       = db_path or DB_PATH
        self.current_cycle = cycle

    def set_cycle(self, c):
        self.current_cycle = c

    def migrate(self):
        migrate(self.db_path)

    # D6
    def check_insert(self, topic, content, confidence):
        return enforce_d6_before_insert(
            topic, content, confidence, self.current_cycle, self.db_path)

    # D7
    def decay_cycle(self):
        return enforce_d7_decay_cycle(self.current_cycle, self.db_path)

    def mark_belief_used(self, belief_id_or_content, successful=False):
        if isinstance(belief_id_or_content, str):
            bid = d7_resolve_id(belief_id_or_content, self.db_path)
        else:
            bid = belief_id_or_content
        if bid:
            d7_mark_used(bid, self.current_cycle, successful, self.db_path)

    # D12
    def check_reinforce_cap(self, belief_id):
        return enforce_d12_cap(belief_id, self.current_cycle, self.db_path)

    # D14/D16
    def record_reinforcement(self, belief_id):
        loop, _ = enforce_d14_check_loop(belief_id, self.current_cycle, self.db_path)
        return loop

    def sweep_loops(self):
        return d14_sweep_flagged(self.current_cycle, self.db_path)

    # D20
    def collapse_check(self, near_death_count=0):
        return enforce_d20_collapse_check(
            self.current_cycle, near_death_count, self.db_path)

    # D4: CONFIDENCE FLOOR STABILIZER
    def confidence_floor_check(self, db_path=None):
        """
        If avg_conf < 0.34: freeze decay, lower filter threshold signal.
        Returns dict with action taken.
        """
        global _decay_frozen_until
        db = db_path or self.db_path
        with _conn(db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT AVG(confidence) FROM beliefs")
            avg_conf = cur.fetchone()[0] or 0.0
            cur.execute("SELECT COUNT(*) FROM beliefs")
            total = cur.fetchone()[0]

        if avg_conf < 0.34:
            # Freeze decay for 10 cycles
            _decay_frozen_until = self.current_cycle + 10
            _log("warn",
                f"[D4] CONFIDENCE FLOOR avg_conf={avg_conf:.3f} < 0.34 — "
                f"decay frozen until cycle {_decay_frozen_until}"
            )
            return {"action": "frozen", "avg_conf": avg_conf,
                    "frozen_until": _decay_frozen_until}
        elif avg_conf < 0.40:
            _log("info", f"[D4] Low confidence warning avg_conf={avg_conf:.3f}")
            return {"action": "warning", "avg_conf": avg_conf}
        return {"action": "ok", "avg_conf": avg_conf}

    # D6ext: EXTERNAL SIGNAL BALANCER
    def self_topic_check(self, db_path=None):
        """
        If #self beliefs > 40% of total: flag for external ingestion boost.
        Returns (needs_boost: bool, self_ratio: float).
        """
        db = db_path or self.db_path
        with _conn(db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM beliefs")
            total = cur.fetchone()[0] or 1
            cur.execute("""
                SELECT COUNT(*) FROM beliefs
                WHERE topic IN ('identity','selfhood','self_reflection','autonomy')
                   OR source IN ('self_reflection','identity_defender')
            """)
            self_count = cur.fetchone()[0]

        ratio = self_count / total
        if ratio > 0.40:
            _log("warn",
                f"[D6ext] #self ratio={ratio:.1%} ({self_count}/{total}) > 40% "
                f"— external ingestion boost needed"
            )
            return True, ratio
        return False, ratio

    # REPORT
    def cycle_report(self):
        with _conn(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM beliefs")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM beliefs WHERE loop_flag=1")
            loops = cur.fetchone()[0]
            cur.execute("SELECT AVG(confidence) FROM beliefs")
            avg_conf = cur.fetchone()[0] or 0.0
            cur.execute("SELECT COUNT(*) FROM beliefs WHERE confidence<=?", (DECAY_FLOOR,))
            near_death = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM beliefs WHERE is_identity=1")
            identity_ct = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM beliefs WHERE successful_uses>=?",
                        (D17_SUCCESS_THRESHOLD,))
            proven_ct = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM beliefs WHERE loop_episodes>=?",
                        (D16_MAX_EPISODES,))
            chronic = cur.fetchone()[0]

        _log("info", 
            f"[DIR] cycle={self.current_cycle} beliefs={total}/{BELIEF_CAP} "
            f"avg_conf={avg_conf:.3f} loops={loops} chronic={chronic} "
            f"near_death={near_death} identity={identity_ct} proven={proven_ct}"
        )
        return {
            "total": total, "cap": BELIEF_CAP, "avg_conf": round(avg_conf, 3),
            "loops": loops, "chronic_loops": chronic, "near_death": near_death,
            "identity_ct": identity_ct, "proven_ct": proven_ct,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    migrate()
    print(DirectiveEnforcer().cycle_report())
