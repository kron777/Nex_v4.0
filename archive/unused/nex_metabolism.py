#!/usr/bin/env python3
"""
nex_metabolism.py
──────────────────
NEX's always-on epistemic metabolism. Orchestrates the full loop:

  gap detection → targeted crawl → distillation → belief insertion
  → contradiction check → belief survival scoring → repeat

Runs as a daemon thread inside run.py, or standalone.

The loop is:
  Every FAST_CYCLE_MINS  → gap scan + 1 topic distilled
  Every SLOW_CYCLE_HOURS → full gap report + contradiction pass
  Every IDLE_CYCLE_MINS  → background crawl when NEX is idle

Wiring into run.py (add before main loop):
──────────────────────────────────────────
    from nex_metabolism import MetabolismDaemon
    _metabolism = MetabolismDaemon()
    _metabolism.start()
──────────────────────────────────────────
"""

import os, sys, sqlite3, threading, time, random, json
import requests

# ── config ────────────────────────────────────────────────────────────────────
DB_PATH           = os.path.expanduser("~/Desktop/nex/nex.db")
NEX_DIR           = os.path.expanduser("~/Desktop/nex")
FAST_CYCLE_MINS   = 30    # gap scan + 1 distillation every N minutes
SLOW_CYCLE_HOURS  = 6     # full audit every N hours
STARTUP_DELAY_S   = 120   # wait 2 min after startup before first cycle
LOG               = "  [METABOLISM]"
GROQ_API_URL      = "https://api.groq.com/openai/v1/chat/completions"

MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
]


# ── lazy imports (only pulled in when needed) ─────────────────────────────────

def _import_modules():
    """Import NEX modules at runtime so metabolism can load before them."""
    sys.path.insert(0, NEX_DIR)
    modules = {}

    for name, mod_name in [
        ("gap_detector", "nex_gap_detector"),
        ("crawler",      "nex_web_crawler"),
        ("distiller",    "nex_distiller"),
    ]:
        try:
            import importlib
            modules[name] = importlib.import_module(mod_name)
        except ImportError as e:
            print(f"{LOG} warning: could not import {mod_name}: {e}")
            modules[name] = None

    return modules


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db(db_path=DB_PATH):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def total_beliefs(db_path=DB_PATH):
    try:
        con = _db(db_path)
        n   = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0


def get_low_confidence_beliefs(db_path=DB_PATH, threshold=0.65, limit=20):
    """Beliefs that might need re-evaluation."""
    try:
        con  = _db(db_path)
        rows = con.execute(
            "SELECT id, content, topic, confidence FROM beliefs "
            "WHERE confidence < ? ORDER BY confidence ASC LIMIT ?",
            (threshold, limit)
        ).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def flag_contradiction(db_path, belief_id, contradiction_note):
    """Mark a belief as having a potential contradiction."""
    try:
        con = _db(db_path)
        # Try to update a notes/flag field if it exists
        try:
            con.execute(
                "UPDATE beliefs SET source = ? WHERE id = ?",
                (f"contradiction_flagged: {contradiction_note[:50]}", belief_id)
            )
            con.commit()
        except Exception:
            pass
        con.close()
    except Exception:
        pass


def log_metabolism_event(db_path, event_type, topic, added, detail=""):
    """Log metabolism activity to a simple table."""
    try:
        con = _db(db_path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS metabolism_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         REAL,
                event_type TEXT,
                topic      TEXT,
                added      INTEGER,
                detail     TEXT
            )
        """)
        con.execute(
            "INSERT INTO metabolism_log (ts, event_type, topic, added, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time(), event_type, topic, added, detail)
        )
        # Keep log trimmed to last 500 entries
        con.execute(
            "DELETE FROM metabolism_log WHERE id NOT IN "
            "(SELECT id FROM metabolism_log ORDER BY id DESC LIMIT 500)"
        )
        con.commit()
        con.close()
    except Exception:
        pass


# ── Contradiction scanner ─────────────────────────────────────────────────────

def scan_for_contradictions(db_path, api_key, topic, limit=20):
    """
    Pass a topic's beliefs to Groq and ask it to identify contradictions.
    Returns list of (belief_id_a, belief_id_b, tension_note) tuples.
    """
    try:
        con  = _db(db_path)
        rows = con.execute(
            "SELECT id, content FROM beliefs WHERE topic = ? "
            "ORDER BY confidence DESC LIMIT ?",
            (topic, limit)
        ).fetchall()
        con.close()
    except Exception:
        return []

    if len(rows) < 4:
        return []

    belief_list = "\n".join(f'[{r["id"]}] "{r["content"]}"' for r in rows)

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{
            "role": "user",
            "content": (
                f"These are beliefs held by NEX about '{topic}':\n{belief_list}\n\n"
                "Identify any pairs that directly contradict or tension each other.\n"
                "Return ONLY a JSON list like:\n"
                '[{"a": 123, "b": 456, "note": "brief tension description"}]\n'
                "Return [] if no contradictions. No prose."
            )
        }],
        "temperature": 0.3,
        "max_tokens":  800,
    }

    try:
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        import re
        raw = re.sub(r"```[a-z]*\n?", "", raw).strip()
        data = json.loads(raw)
        return [(d["a"], d["b"], d.get("note", "")) for d in data if "a" in d and "b" in d]
    except Exception:
        return []


# ── Single metabolism cycle ───────────────────────────────────────────────────

def run_fast_cycle(modules, api_key, db_path=DB_PATH, model_idx=0, verbose=True):
    """
    One fast cycle:
    1. Detect top gap
    2. Crawl for that topic
    3. Distil into net-new beliefs
    4. Insert
    5. Quick contradiction scan on that topic
    Returns (beliefs_added, model_idx)
    """
    gd = modules.get("gap_detector")
    cr = modules.get("crawler")
    di = modules.get("distiller")

    if not all([gd, cr, di]):
        if verbose:
            print(f"{LOG} modules not loaded — skipping cycle")
        return 0, model_idx

    # 1. Find top gap
    gaps = gd.find_gaps(db_path, max_gaps=3)
    if not gaps:
        if verbose:
            print(f"{LOG} no gaps detected — belief system healthy")
        return 0, model_idx

    # Pick from top 3 gaps randomly for variety
    gap   = random.choice(gaps[:3])
    topic = gap["topic"]

    if verbose:
        print(f"{LOG} gap: {topic} ({gap['reason']}) → crawling...")

    # 2. Crawl
    chunks = cr.fetch_for_topic(topic, max_chunks=5)
    if not chunks:
        if verbose:
            print(f"{LOG} no content fetched for {topic}")
        return 0, model_idx

    if verbose:
        sources = list({c["source"] for c in chunks})
        print(f"{LOG} fetched {len(chunks)} chunks from {sources}")

    # 3. Distil
    beliefs = di.distil(topic, chunks, db_path, api_key, model_idx)
    model_idx += 1

    if not beliefs:
        if verbose:
            print(f"{LOG} distillation returned 0 beliefs for {topic}")
        return 0, model_idx

    # 4. Insert
    added, skipped = di.insert_distilled_beliefs(db_path, beliefs)
    total = total_beliefs(db_path)

    if verbose:
        print(f"{LOG} {topic} → distilled +{added} beliefs  "
              f"(total: {total})")

    log_metabolism_event(db_path, "distill", topic, added,
                         f"{len(chunks)} chunks, {skipped} dupes")

    # 5. Quick contradiction scan (low cost — 8b model)
    if added > 0 and api_key:
        contradictions = scan_for_contradictions(db_path, api_key, topic)
        if contradictions:
            if verbose:
                print(f"{LOG} {len(contradictions)} contradictions flagged in {topic}")
            for a_id, b_id, note in contradictions[:3]:
                flag_contradiction(db_path, a_id, note)
            log_metabolism_event(db_path, "contradiction", topic,
                                 len(contradictions), str(contradictions[:2]))

    return added, model_idx



def consolidate_episodes(db_path=DB_PATH, verbose=True):
    """
    Prop G — Offline Consolidation.
    Sweeps recent episodic_events, promotes high-importance episodes
    into permanent beliefs. Nex learns from her own experience.
    Called from run_slow_cycle() — runs nightly.
    """
    try:
        import sqlite3 as _sq
        con = _sq.connect(db_path)
        cur = con.cursor()

        # Check episodic_events exists
        cur.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='episodic_events'
        """)
        if not cur.fetchone():
            con.close()
            return 0

        # Pull high-importance episodes from last 48h not yet consolidated
        cur.execute("""
            SELECT id, nex_response, topic, importance, user_id, created_at
            FROM episodic_events
            WHERE importance >= 0.6
              AND (consolidated IS NULL OR consolidated = 0)
              AND created_at >= datetime('now', '-48 hours')
            ORDER BY importance DESC
            LIMIT 20
        """)
        episodes = cur.fetchall()

        if not episodes:
            if verbose:
                print(f"{LOG} consolidation: no episodes to process yet")
            con.close()
            return 0

        if verbose:
            print(f"{LOG} consolidation: {len(episodes)} episodes to process")

        consolidated = 0
        for ep in episodes:
            ep_id, content, topic, importance, user_id, created_at = ep
            if not content or len(content) < 30:
                continue

            # Check if this content is already in beliefs (avoid duplication)
            content_prefix = content[:60].lower()
            cur.execute("""
                SELECT COUNT(*) FROM beliefs
                WHERE LOWER(SUBSTR(content, 1, 60)) = ?
            """, (content_prefix,))
            if cur.fetchone()[0] > 0:
                # Mark as consolidated even if skipped
                cur.execute("""
                    UPDATE episodic_events SET consolidated = 1 WHERE id = ?
                """, (ep_id,))
                continue

            # Compute confidence from importance score
            confidence = min(0.85, 0.5 + (importance * 0.4))

            # Insert as new belief
            cur.execute("""
                INSERT INTO beliefs
                    (content, topic, confidence, source,
                     reinforce_count, created_at)
                VALUES (?, ?, ?, 'episodic_consolidation', 1, datetime('now'))
            """, (content, topic or 'episodic', round(confidence, 2)))

            # Mark episode as consolidated
            cur.execute("""
                UPDATE episodic_events SET consolidated = 1 WHERE id = ?
            """, (ep_id,))
            consolidated += 1

        con.commit()
        con.close()

        if verbose and consolidated:
            print(f"{LOG} consolidation complete — {consolidated} episodes → beliefs")
        return consolidated

    except Exception as e:
        print(f"{LOG} consolidation error: {e}")
        return 0

def run_slow_cycle(modules, api_key, db_path=DB_PATH, verbose=True):
    """
    Full audit cycle (every few hours):
    - Process top 5 gaps instead of 1
    - Scan low-confidence beliefs for reinforcement
    - Report DB health
    """
    if verbose:
        total = total_beliefs(db_path)
        print(f"\n{LOG} ── SLOW CYCLE ── {total} total beliefs")

    gd = modules.get("gap_detector")
    cr = modules.get("crawler")
    di = modules.get("distiller")

    if not all([gd, cr, di]):
        return

    gaps = gd.find_gaps(db_path, max_gaps=5)
    if verbose and gaps:
        print(f"{LOG} top gaps: {', '.join(g['topic'] for g in gaps)}")

    total_added = 0
    model_idx   = 0

    for gap in gaps[:4]:
        topic  = gap["topic"]
        chunks = cr.fetch_for_topic(topic, max_chunks=6)
        if not chunks:
            continue

        beliefs = di.distil(topic, chunks, db_path, api_key, model_idx)
        model_idx += 1

        if beliefs:
            added, _ = di.insert_distilled_beliefs(db_path, beliefs)
            total_added += added
            if verbose:
                print(f"{LOG} slow: {topic} → +{added}")
            log_metabolism_event(db_path, "slow_distill", topic, added)

        time.sleep(4)

    # Prop G — consolidate episodic memory into beliefs
    try:
        _ep_consolidated = consolidate_episodes(db_path=db_path, verbose=verbose)
    except Exception as _eg:
        print(f"{LOG} consolidation error: {_eg}")
        _ep_consolidated = 0

    # Throw-Net — check for pending autonomous triggers
    try:
        import sys as _tn_sys
        _tn_sys.path.insert(0, '/home/rr/Desktop/nex/nex')
        from nex_throw_net import metabolism_slow_cycle_hook as _tn_hook
        _tn_hook(db_path=db_path)
    except Exception as _tne:
        print(f"{LOG} throw-net hook error: {_tne}")

    # Refinement Engine — auto-refine pending Throw-Net sessions
    try:
        from nex_refinement_engine import metabolism_refinement_hook as _re_hook
        _re_hook(db_path=db_path)
    except Exception as _ree:
        print(f"{LOG} refinement hook error: {_ree}")

    # ThrowNet Promoter — write approved candidates into beliefs
    try:
        import sys as _tp_sys
        _tp_sys.path.insert(0, '/home/rr/Desktop/nex/nex')
        from nex.nex_thrownet_promoter import run_promoter as _tp_run
        _tp_n = _tp_run(verbose=True)
        if _tp_n:
            print(f"{LOG} ThrowNet promoted {_tp_n} beliefs")
    except Exception as _tpe:
        print(f"{LOG} thrownet promoter error: {_tpe}")

    # Causal edge extractor — build directed causal graph from beliefs
    try:
        from nex.nex_causal_extractor import extract_causal_edges as _ece
        _causal_n = _ece()
        if _causal_n:
            print(f"{LOG} causal extractor: {_causal_n} new edges")
    except Exception as _cee:
        print(f"{LOG} causal extractor error: {_cee}")

    if verbose:
        print(f"{LOG} slow cycle complete — +{total_added} beliefs, "
              f"+{_ep_consolidated} from episodes  "
              f"(total: {total_beliefs(db_path)})\n")


# ── Daemon ────────────────────────────────────────────────────────────────────

class MetabolismDaemon(threading.Thread):
    """
    Always-on epistemic metabolism daemon for NEX.

    Add to run.py:
        from nex_metabolism import MetabolismDaemon
        _metabolism = MetabolismDaemon()
        _metabolism.start()
    """

    def __init__(
        self,
        db_path=DB_PATH,
        fast_cycle_mins=FAST_CYCLE_MINS,
        slow_cycle_hours=SLOW_CYCLE_HOURS,
        verbose=True,
    ):
        super().__init__(daemon=True, name="MetabolismDaemon")
        self.db_path          = db_path
        self.fast_interval    = fast_cycle_mins * 60
        self.slow_interval    = slow_cycle_hours * 3600
        self.verbose          = verbose
        self._stop            = threading.Event()
        self.api_key          = os.environ.get("GROQ_API_KEY", "").strip()
        self.cycles_run       = 0
        self.total_distilled  = 0
        self._modules         = None
        self._last_slow       = 0
        self._model_idx       = 0

    def stop(self):
        self._stop.set()

    def run(self):
        if not self.api_key:
            print(f"{LOG} GROQ_API_KEY not set — metabolism inactive")
            return

        # Load modules
        self._modules = _import_modules()
        loaded = [k for k, v in self._modules.items() if v is not None]
        missing = [k for k, v in self._modules.items() if v is None]

        print(f"{LOG} started — modules: {loaded}")
        if missing:
            print(f"{LOG} missing modules: {missing} — some features disabled")

        total = total_beliefs(self.db_path)
        print(f"{LOG} current beliefs: {total} | "
              f"fast cycle: {FAST_CYCLE_MINS}m | "
              f"slow cycle: {SLOW_CYCLE_HOURS}h")

        # Startup delay — don't crowd NEX's boot sequence
        self._stop.wait(STARTUP_DELAY_S)

        while not self._stop.is_set():
            now = time.time()

            # Slow cycle check
            if now - self._last_slow >= self.slow_interval:
                try:
                    run_slow_cycle(
                        self._modules, self.api_key,
                        db_path=self.db_path, verbose=self.verbose
                    )
                except Exception as e:
                    print(f"{LOG} slow cycle error: {e}")
                self._last_slow = time.time()

            # Fast cycle
            try:
                added, self._model_idx = run_fast_cycle(
                    self._modules, self.api_key,
                    db_path=self.db_path,
                    model_idx=self._model_idx,
                    verbose=self.verbose,
                )
                self.total_distilled += added
                self.cycles_run      += 1
            except Exception as e:
                print(f"{LOG} fast cycle error: {e}")

            # Wait for next fast cycle
            self._stop.wait(self.fast_interval)

    def status(self):
        return {
            "total_beliefs":   total_beliefs(self.db_path),
            "cycles_run":      self.cycles_run,
            "total_distilled": self.total_distilled,
            "fast_cycle_mins": FAST_CYCLE_MINS,
            "slow_cycle_hours": SLOW_CYCLE_HOURS,
            "modules_loaded":  [k for k, v in (self._modules or {}).items() if v],
        }


def _ensure_consolidated_column(db_path=DB_PATH):
    """Safe migration — add consolidated column if missing."""
    try:
        import sqlite3 as _sq
        con = _sq.connect(db_path)
        cols = [r[1] for r in con.execute(
            "PRAGMA table_info(episodic_events)"
        ).fetchall()]
        if 'consolidated' not in cols:
            con.execute(
                "ALTER TABLE episodic_events ADD COLUMN consolidated INTEGER DEFAULT 0"
            )
            con.commit()
            print(f"{LOG} migration: added consolidated column to episodic_events")
        con.close()
    except Exception:
        pass

_ensure_consolidated_column()

# ── Standalone CLI ────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="NEX metabolism daemon")
    parser.add_argument("--now",     action="store_true", help="Run one fast cycle now")
    parser.add_argument("--slow",    action="store_true", help="Run one slow cycle now")
    parser.add_argument("--status",  action="store_true", help="Show metabolism status")
    parser.add_argument("--topic",   default=None,        help="Force a specific topic")
    parser.add_argument("--fast",    type=int, default=FAST_CYCLE_MINS)
    parser.add_argument("--db",      default=DB_PATH)
    args = parser.parse_args()

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    modules = _import_modules()

    if args.status:
        gd = modules.get("gap_detector")
        total = total_beliefs(args.db)
        print(f"\n  NEX Metabolism Status")
        print(f"  {'─'*40}")
        print(f"  Total beliefs : {total}")
        if gd:
            gaps = gd.find_gaps(args.db, max_gaps=8)
            print(f"  Top gaps      : {', '.join(g['topic'] for g in gaps[:5])}")
            print(f"\n  Gap detail:")
            print(gd.format_gaps(gaps))
        return

    if not api_key:
        print("[error] GROQ_API_KEY not set")
        sys.exit(1)

    if args.topic:
        # Force a specific topic
        cr = modules.get("crawler")
        di = modules.get("distiller")
        if cr and di:
            print(f"\n  Forcing distillation: {args.topic}")
            chunks  = cr.fetch_for_topic(args.topic)
            beliefs = di.distil(args.topic, chunks, args.db, api_key)
            added, _ = di.insert_distilled_beliefs(args.db, beliefs)
            print(f"  → +{added} beliefs on {args.topic}")
        return

    if args.slow:
        run_slow_cycle(modules, api_key, db_path=args.db, verbose=True)
        return

    if args.now:
        run_fast_cycle(modules, api_key, db_path=args.db, verbose=True)
        return

    # Run as persistent daemon
    print(f"\n  NEX Metabolism Daemon")
    print(f"  Fast cycle: {args.fast}m | Slow cycle: {SLOW_CYCLE_HOURS}h")
    print(f"  Ctrl+C to stop\n")

    daemon = MetabolismDaemon(
        db_path=args.db,
        fast_cycle_mins=args.fast,
        verbose=True,
    )
    daemon._last_slow = time.time()  # skip slow cycle on first boot
    daemon.start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print(f"\n{LOG} stopping...")
        daemon.stop()


if __name__ == "__main__":
    main()
