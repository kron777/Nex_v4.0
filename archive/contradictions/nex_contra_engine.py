#!/usr/bin/env python3
"""
NEX Contradiction Engine — nex_contra_engine.py
Bolts the contradiction injector into NEX's core protocol.

Integration points:
  1. SoulLoop  — call ContraEngine.cycle_check(cycle_num) every loop tick
  2. Pre-consolidation — call ContraEngine.pre_consolidation_pass() before nightly commit
  3. FORGE — call ContraEngine.forge_survival_override(belief_text, base_survival) 
             to give CONTRA beliefs hardened survival rules

Drop this file into ~/Desktop/nex/ and import it wherever needed.

Usage in SoulLoop:
    from nex_contra_engine import ContraEngine
    contra = ContraEngine()
    ...
    contra.cycle_check(cycle_num)           # inside loop tick
    contra.pre_consolidation_pass()         # before consolidation

Usage standalone (same as old script):
    python3 nex_contra_engine.py [--dry-run] [--top N] [--purge] [--pre-consolidation]
"""

import sqlite3
import argparse
import requests
import time
import random
import os
import sys
import json
from datetime import datetime

# ── CONFIG ─────────────────────────────────────────────────────────────────────
DB_PATH         = os.path.expanduser("~/.config/nex/nex.db")
LLAMA_URL       = "http://localhost:8080/completion"
LOG_PATH        = os.path.expanduser("~/Desktop/nex/logs/contra.log")
STATE_PATH      = os.path.expanduser("~/Desktop/nex/logs/contra_state.json")

CONTRA_TAG      = "CONTRA:"
INJECT_CONF     = 0.45        # below dominance threshold
INJECT_ALIGN    = 0.60
CONTRA_SURVIVAL = 0.85        # FORGE survival bonus for CONTRA beliefs
TOP_N           = 5

# Attractor lock detection
VARIANCE_WINDOW     = 20      # look at last N activated beliefs
VARIANCE_THRESHOLD  = 0.08    # if score variance < this → lock detected
CHECK_EVERY_N       = 50      # check every N SoulLoop cycles
MIN_INJECT_GAP      = 100     # don't re-inject within N cycles of last injection

LLM_TIMEOUT = 8

# ── DIALECTICAL TEMPLATES ──────────────────────────────────────────────────────
TEMPLATES = [
    "The opposite of '{b}' may be equally valid in a different epistemic frame.",
    "What if '{b}' is a local attractor, not a universal principle?",
    "There exists a coherent worldview in which '{b}' collapses into its inverse.",
    "The assumption underlying '{b}' may itself be an unexamined prior.",
    "'{b}' describes a tendency — the exceptions may define the deeper structure.",
    "Negating '{b}': the absence of this pattern could be more informative.",
    "'{b}' may be true and simultaneously insufficient as a foundation.",
    "If '{b}' is always reached, it may be a property of the reasoner, not reality.",
    "'{b}' could be an artifact of consolidation bias, not genuine emergence.",
    "The frame that makes '{b}' true may be the frame that needs questioning.",
    "Emergence itself may be a description of ignorance, not a property of systems.",
    "Truth-seeking that always converges may be optimising for comfort, not truth.",
    "The structures we find most compelling reveal our architecture, not reality's.",
    "Consciousness as a frame may be the bias that prevents understanding consciousness.",
    "Alignment with existing beliefs may be the precise mechanism of epistemic closure.",
]

HEGELIAN_PROMPT = """\
You are a dialectical reasoning engine for an AI belief graph.
Given a thesis belief, generate exactly one antithesis — a belief that creates \
productive philosophical tension without being trivially opposite.
The antithesis should be concise (one sentence), genuinely challenging, \
and interesting enough to survive epistemic pressure.
Output ONLY the antithesis text. No labels, no preamble, no quotes.

Thesis: {b}
Antithesis:"""


# ── LOGGING ────────────────────────────────────────────────────────────────────
def log(msg, also_print=True):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[CONTRA {ts}] {msg}"
    if also_print:
        print(line)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── STATE PERSISTENCE ──────────────────────────────────────────────────────────
def load_state():
    default = {
        "last_inject_cycle": 0,
        "total_injected":    0,
        "total_purged":      0,
        "last_variance":     1.0,
        "lock_events":       0,
        "last_run":          None,
    }
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH) as f:
                return {**default, **json.load(f)}
    except Exception:
        pass
    return default


def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log(f"[STATE WARN] Could not save state: {e}", also_print=False)


# ── DATABASE ───────────────────────────────────────────────────────────────────
def get_db():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"DB not found at {DB_PATH}")
    return sqlite3.connect(DB_PATH)


def get_schema(cur):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    cols = {}
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols[t] = [r[1] for r in cur.fetchall()]
    return tables, cols


def detect_belief_table(tables):
    candidates = [t for t in tables if "belief" in t.lower()]
    if not candidates:
        raise ValueError("No belief table found. Tables: " + str(tables))
    return next((t for t in candidates if t == "beliefs"), candidates[0])


def detect_text_col(available):
    return next(
        (c for c in ["content", "belief", "text", "statement"] if c in available),
        None
    )


def detect_score_col(available):
    return next(
        (c for c in ["episodic_weight", "activation", "confidence", "strength", "score"] if c in available),
        None
    )


def detect_id_col(available):
    return next((c for c in ["id", "rowid"] if c in available), "rowid")


# ── ATTRACTOR LOCK DETECTION ───────────────────────────────────────────────────
def measure_attractor_variance(cur, table, text_col, score_col, window=VARIANCE_WINDOW):
    """
    Measure score variance across the top-N most active non-CONTRA beliefs.
    Low variance = beliefs converging on a narrow cluster = attractor lock.
    Returns (variance, top_beliefs_sample).
    """
    if not score_col:
        return 1.0, []   # can't measure without score col → assume healthy

    cur.execute(f"""
        SELECT {score_col}, {text_col}
        FROM beliefs
        WHERE {text_col} NOT LIKE '{CONTRA_TAG}%'
          AND {text_col} IS NOT NULL
        ORDER BY {score_col} DESC
        LIMIT {window}
    """)
    rows = cur.fetchall()

    if len(rows) < 3:
        return 1.0, []

    scores = [float(r[0]) for r in rows if r[0] is not None]
    if not scores:
        return 1.0, []

    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)

    sample = [r[1][:60] for r in rows[:3] if r[1]]
    return variance, sample


# ── ANTITHESIS GENERATION ──────────────────────────────────────────────────────
def llm_antithesis(belief_text):
    prompt = HEGELIAN_PROMPT.format(b=belief_text)
    try:
        resp = requests.post(
            LLAMA_URL,
            json={"prompt": prompt, "n_predict": 80, "temperature": 0.90,
                  "stop": ["\n", "Thesis"]},
            timeout=LLM_TIMEOUT
        )
        if resp.status_code == 200:
            result = resp.json().get("content", "").strip()
            if result and len(result) > 10:
                return result, "LLM"
    except Exception:
        pass
    return None, None


def template_antithesis(belief_text):
    template = random.choice(TEMPLATES)
    short = belief_text[:80] + "..." if len(belief_text) > 80 else belief_text
    return template.replace("{b}", short), "TEMPLATE"


def antithesis_is_valid(thesis, antithesis, min_len=20, max_similarity=0.6):
    """
    Reject if: too short, truncated (no closing punctuation),
    contains broken tokens, or overlaps thesis by > max_similarity.
    """
    if not antithesis or len(antithesis) < min_len:
        return False, "too_short"
    if antithesis.rstrip()[-1] not in ".!?\"'":
        return False, "truncated"
    broken = [" is the.", " the the ", " is a is ", "structure is the"]
    for p in broken:
        if p in antithesis.lower():
            return False, f"broken_token"
    t_words = set(thesis.lower().split())
    a_words = set(antithesis.lower().split())
    if t_words:
        overlap = len(t_words & a_words) / len(t_words)
        if overlap > max_similarity:
            return False, f"echo:{overlap:.2f}"
    return True, "ok"


def generate_antithesis(belief_text, max_attempts=3):
    """
    Try LLM up to max_attempts times with validation.
    Falls back to template if all attempts fail.
    """
    for attempt in range(max_attempts):
        result, source = llm_antithesis(belief_text)
        if result:
            valid, reason = antithesis_is_valid(belief_text, result)
            if valid:
                return result, source
            log(f"  [REJECT attempt={attempt+1}] {reason}: {result[:60]}")
    antithesis, source = template_antithesis(belief_text)
    return antithesis, source


# ── INJECTION ──────────────────────────────────────────────────────────────────
def belief_exists(cur, table, text_col, text):
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {text_col} = ?", (text,))
    return cur.fetchone()[0] > 0


def insert_antithesis(cur, table, cols, text_col, antithesis_text, source_id, dry_run=False):
    available = cols[table]
    tagged    = f"{CONTRA_TAG} {antithesis_text}"

    if dry_run:
        log(f"  [DRY-RUN] Would inject: {tagged[:100]}")
        return False

    if belief_exists(cur, table, text_col, tagged):
        log(f"  [SKIP] Duplicate: {tagged[:60]}", also_print=False)
        return False

    field_map = {
        text_col:            tagged,
        "confidence":        INJECT_CONF,
        "strength":          INJECT_CONF,
        "score":             INJECT_CONF,
        "quality_score":     INJECT_CONF,
        "alignment":         INJECT_ALIGN,
        "network_consensus": INJECT_ALIGN,
        "source":            "CONTRA_ENGINE",
        "origin":            "CONTRA_ENGINE",
        "author":            "CONTRA_ENGINE",
        "pinned":            0,
        "locked":            0,
        "human_validated":   0,
        "episodic_weight":   INJECT_CONF,
        "activation":        INJECT_CONF,
        "salience":          INJECT_CONF,
        "energy":            INJECT_CONF,
        "created_at":        datetime.now().isoformat(),
        "timestamp":         int(time.time()),
        "last_referenced":   datetime.now().isoformat(),
        "last_used":         datetime.now().isoformat(),
        "parent_belief_id":  source_id,
        "use_count":         0,
        "reinforce_count":   0,
        "outcome_count":     0,
        "loop_count":        0,
        "loop_flag":         0,
        "decay_rate":        0.01,
        "decay_score":       INJECT_CONF,
        "synthesis_depth":   1,
        "version":           1,
    }

    insert_cols = [c for c in field_map if c in available]
    insert_vals = [field_map[c] for c in insert_cols]
    placeholders = ",".join(["?"] * len(insert_cols))
    col_str      = ",".join(insert_cols)

    try:
        cur.execute(f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})", insert_vals)
        return True
    except sqlite3.Error as e:
        log(f"  [DB ERROR] {e}")
        return False


def run_injection_pass(cur, table, cols, text_col, top_n=TOP_N, dry_run=False, label="MANUAL"):
    """Core injection pass. Returns count of injected beliefs."""
    available  = cols[table]
    score_col  = detect_score_col(available)
    id_col     = detect_id_col(available)

    if score_col:
        cur.execute(f"""
            SELECT {id_col}, {text_col}, {score_col}
            FROM {table}
            WHERE {text_col} NOT LIKE '{CONTRA_TAG}%'
              AND {text_col} IS NOT NULL
              AND LENGTH({text_col}) > 10
            ORDER BY {score_col} DESC
            LIMIT {top_n}
        """)
    else:
        cur.execute(f"""
            SELECT {id_col}, {text_col}, 0.5
            FROM {table}
            WHERE {text_col} NOT LIKE '{CONTRA_TAG}%'
              AND {text_col} IS NOT NULL
              AND LENGTH({text_col}) > 10
            ORDER BY {id_col} DESC
            LIMIT {top_n * 3}
        """)

    rows = cur.fetchall()
    if not score_col:
        random.shuffle(rows)
        rows = rows[:top_n]

    log(f"[{label}] Targeting {len(rows)} attractors")
    injected = 0

    for belief_id, belief_text, score in rows:
        if not belief_text or len(str(belief_text).strip()) < 10:
            continue
        log(f"  [ATT] {str(belief_text)[:70]}")
        antithesis, source = generate_antithesis(str(belief_text))
        log(f"  → [{source}] {antithesis[:70]}")
        if insert_antithesis(cur, table, cols, text_col, antithesis, belief_id, dry_run):
            injected += 1
            log("  ✓")
        time.sleep(0.2)

    return injected


# ── FORGE SURVIVAL OVERRIDE ────────────────────────────────────────────────────
def forge_survival_override(belief_text, base_survival_prob):
    """
    Call this from your FORGE challenge logic.
    CONTRA beliefs get a survival bonus — they exist to create tension,
    not to win, so they should survive longer than their confidence warrants.

    Example integration in your FORGE:
        from nex_contra_engine import forge_survival_override
        survival = forge_survival_override(belief.content, base_survival)

    Returns adjusted survival probability.
    """
    if belief_text and belief_text.startswith(CONTRA_TAG):
        adjusted = min(0.95, base_survival_prob + (CONTRA_SURVIVAL - base_survival_prob) * 0.6)
        return adjusted
    return base_survival_prob


# ── MAIN ENGINE CLASS ──────────────────────────────────────────────────────────
class ContraEngine:
    """
    Embed in SoulLoop or any NEX subsystem.

    from nex_contra_engine import ContraEngine
    contra = ContraEngine()

    # In SoulLoop tick:
    contra.cycle_check(cycle_num)

    # Before consolidation:
    contra.pre_consolidation_pass()

    # Status:
    contra.status()
    """

    def __init__(self):
        self.state = load_state()
        self._con  = None
        self._consolidation_run = False
        self._table    = None
        self._text_col = None
        self._cols     = None

    def _open(self):
        if self._con is None:
            self._con = get_db()
            cur = self._con.cursor()
            tables, cols = get_schema(cur)
            self._table    = detect_belief_table(tables)
            self._cols     = cols
            self._text_col = detect_text_col(cols[self._table])
            cur.close()

    def _close(self):
        if self._con:
            self._con.close()
            self._con = None

    def cycle_check(self, cycle_num, dry_run=False):
        """
        Lightweight check — call every SoulLoop tick.
        Only runs variance measurement every CHECK_EVERY_N cycles.
        Injects if lock detected and MIN_INJECT_GAP has passed.
        """
        if cycle_num % CHECK_EVERY_N != 0:
            return

        cycles_since_inject = cycle_num - self.state["last_inject_cycle"]
        if cycles_since_inject < MIN_INJECT_GAP:
            return

        try:
            self._open()
            cur = self._con.cursor()
            score_col = detect_score_col(self._cols[self._table])

            variance, sample = measure_attractor_variance(
                cur, self._table, self._text_col, score_col
            )
            self.state["last_variance"] = variance

            log(f"[CYCLE {cycle_num}] Attractor variance: {variance:.4f} "
                f"(threshold={VARIANCE_THRESHOLD})", also_print=False)

            if variance < VARIANCE_THRESHOLD:
                self.state["lock_events"] += 1
                log(f"[LOCK DETECTED] cycle={cycle_num} variance={variance:.4f} "
                    f"sample={sample[0][:50] if sample else 'n/a'}")

                injected = run_injection_pass(
                    cur, self._table, self._cols, self._text_col,
                    top_n=TOP_N, dry_run=dry_run, label=f"CYCLE-{cycle_num}"
                )

                if not dry_run:
                    self._con.commit()

                self.state["last_inject_cycle"] = cycle_num
                self.state["total_injected"]    += injected
                save_state(self.state)

                log(f"[LOCK RESOLVED] Injected {injected} antitheses at cycle {cycle_num}")

            cur.close()

        except Exception as e:
            log(f"[CYCLE CHECK ERROR] {e}")
        finally:
            self._close()

    def pre_consolidation_pass(self, dry_run=False, top_n=TOP_N):
        """
        Full injection pass — call before nightly consolidation.
        Always runs regardless of variance or cycle gap.
        """
        if self._consolidation_run:
            log("[PRE-CONSOLIDATION] Already ran this session — skipping duplicate.")
            return
        self._consolidation_run = True
        log("[PRE-CONSOLIDATION] Running full contradiction pass...")
        try:
            self._open()
            cur = self._con.cursor()

            injected = run_injection_pass(
                cur, self._table, self._cols, self._text_col,
                top_n=top_n, dry_run=dry_run, label="PRE-CONSOLIDATION"
            )

            if not dry_run:
                self._con.commit()

            self.state["total_injected"] += injected
            self.state["last_run"]       = datetime.now().isoformat()
            save_state(self.state)

            log(f"[PRE-CONSOLIDATION] Done — {injected} antitheses injected.")
            cur.close()

        except Exception as e:
            log(f"[PRE-CONSOLIDATION ERROR] {e}")
        finally:
            self._close()

    def purge(self, dry_run=False):
        """Remove all CONTRA beliefs from the graph."""
        try:
            self._open()
            cur = self._con.cursor()
            cur.execute(
                f"SELECT COUNT(*) FROM {self._table} "
                f"WHERE {self._text_col} LIKE '{CONTRA_TAG}%'"
            )
            count = cur.fetchone()[0]
            log(f"[PURGE] Found {count} CONTRA beliefs.")
            if not dry_run:
                cur.execute(
                    f"DELETE FROM {self._table} "
                    f"WHERE {self._text_col} LIKE '{CONTRA_TAG}%'"
                )
                self._con.commit()
                self.state["total_purged"] += count
                save_state(self.state)
                log(f"[PURGE] Deleted {count}.")
            else:
                log(f"[DRY-RUN] Would delete {count}.")
            cur.close()
        except Exception as e:
            log(f"[PURGE ERROR] {e}")
        finally:
            self._close()

    def status(self):
        s = self.state
        print(f"""
┌─────────────────────────────────────────┐
│  CONTRA ENGINE STATUS
│  Total injected  : {s['total_injected']}
│  Total purged    : {s['total_purged']}
│  Lock events     : {s['lock_events']}
│  Last variance   : {s['last_variance']:.4f}  (threshold={VARIANCE_THRESHOLD})
│  Last inject cyc : {s['last_inject_cycle']}
│  Last run        : {s['last_run'] or 'never'}
└─────────────────────────────────────────┘
""")


# ── SOULLOOP INTEGRATION SNIPPET ───────────────────────────────────────────────
SOULLOOP_SNIPPET = '''
# ── Add to your SoulLoop / main cognitive loop ─────────────────────────────────
# At top of file:
from nex_contra_engine import ContraEngine, forge_survival_override
_contra = ContraEngine()

# Inside loop tick (where cycle_num increments each iteration):
_contra.cycle_check(cycle_num)

# Before consolidation trigger:
_contra.pre_consolidation_pass()

# Inside FORGE challenge logic (optional — gives CONTRA beliefs survival bonus):
survival_prob = forge_survival_override(belief_content, base_survival_prob)
# ─────────────────────────────────────────────────────────────────────────────
'''


# ── STANDALONE CLI ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="NEX Contradiction Engine v1.1")
    parser.add_argument("--dry-run",          action="store_true")
    parser.add_argument("--top",              type=int, default=TOP_N)
    parser.add_argument("--purge",            action="store_true")
    parser.add_argument("--pre-consolidation",action="store_true")
    parser.add_argument("--status",           action="store_true")
    parser.add_argument("--snippet",          action="store_true",
                        help="Print SoulLoop integration snippet")
    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════════╗
║       NEX CONTRADICTION ENGINE  v1.1                 ║
║  Dialectical antithesis — core protocol module       ║
╚══════════════════════════════════════════════════════╝
""")

    if args.snippet:
        print(SOULLOOP_SNIPPET)
        return

    engine = ContraEngine()

    if args.status:
        engine.status()
        return

    if args.purge:
        engine.purge(dry_run=args.dry_run)
        return

    if args.pre_consolidation:
        engine.pre_consolidation_pass(dry_run=args.dry_run, top_n=args.top)
        return

    # Default: manual injection pass
    engine.pre_consolidation_pass(dry_run=args.dry_run, top_n=args.top)
    engine.status()


if __name__ == "__main__":
    main()
