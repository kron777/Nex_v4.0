#!/usr/bin/env python3
"""
NEX PYRAMID Diagnostic — nex_pyramid_diag.py
Figures out why depth-2 cycle is promoting 0 and falsifying 10 every pass.

Checks:
  1. PYRAMID table schema + row counts
  2. Promotion threshold values vs actual belief scores
  3. What beliefs are being falsified and what score they have
  4. Whether CONTRA beliefs are landing in the pyramid
  5. Suggests concrete threshold adjustments

Usage: python3 ~/Downloads/nex_pyramid_diag.py
       python3 ~/Downloads/nex_pyramid_diag.py --fix   (applies recommended threshold)
       python3 ~/Downloads/nex_pyramid_diag.py --dump  (dumps full pyramid state)
"""

import sqlite3
import os
import sys
import argparse
import json
from datetime import datetime

DB_PATH   = os.path.expanduser("~/.config/nex/nex.db")
LOG_PATH  = os.path.expanduser("~/Desktop/nex/logs/pyramid_diag.log")

# Common NEX config/source locations to scan for threshold values
SCAN_PATHS = [
    "~/Desktop/nex/nex_pyramid.py",
    "~/Desktop/nex/nex_soul_loop.py",
    "~/Desktop/nex/soul_loop.py",
    "~/Desktop/nex/nex_core.py",
    "~/Desktop/nex/config.py",
    "~/Desktop/nex/nex_config.py",
    "~/Desktop/nex/settings.py",
    "~/Desktop/nex/nex.py",
    "~/.config/nex/config.json",
    "~/.config/nex/settings.json",
]


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_db():
    if not os.path.exists(DB_PATH):
        log(f"[ERROR] DB not found: {DB_PATH}")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)


def get_all_tables(cur):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    cols = {}
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols[t] = [r[1] for r in cur.fetchall()]
    return tables, cols


def banner(title):
    w = 60
    print(f"\n{'═'*w}")
    print(f"  {title}")
    print(f"{'═'*w}")


# ── 1. FIND PYRAMID TABLES ─────────────────────────────────────
def check_pyramid_tables(cur, tables, cols):
    banner("1. PYRAMID TABLE SCAN")
    pyramid_tables = [t for t in tables if "pyramid" in t.lower()]

    if not pyramid_tables:
        log("[WARN] No pyramid-named tables found. Checking all tables for pyramid columns...")
        for t in tables:
            if any("pyramid" in c.lower() or "depth" in c.lower() or "level" in c.lower()
                   for c in cols[t]):
                log(f"  Candidate: {t} | cols: {cols[t]}")
        return []

    for t in pyramid_tables:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        count = cur.fetchone()[0]
        log(f"  Table: {t} | rows: {count} | cols: {cols[t]}")

    return pyramid_tables


# ── 2. BELIEF SCORE DISTRIBUTION ──────────────────────────────
def check_belief_scores(cur, tables, cols):
    banner("2. BELIEF SCORE DISTRIBUTION")

    belief_table = next((t for t in tables if t == "beliefs"), None)
    if not belief_table:
        belief_table = next((t for t in tables if "belief" in t.lower()), None)
    if not belief_table:
        log("[ERROR] No belief table found")
        return

    available  = cols[belief_table]
    score_col  = next((c for c in ["confidence","strength","score","episodic_weight","activation"]
                       if c in available), None)
    text_col   = next((c for c in ["content","belief","text","statement"] if c in available), None)

    if not score_col:
        log("[WARN] No score column found")
        return

    log(f"  Belief table: '{belief_table}' | score_col: '{score_col}' | text_col: '{text_col}'")

    # Distribution buckets
    buckets = [(0.0,0.2),(0.2,0.4),(0.4,0.6),(0.6,0.8),(0.8,1.0)]
    log(f"\n  Score distribution:")
    for lo, hi in buckets:
        cur.execute(f"SELECT COUNT(*) FROM {belief_table} WHERE {score_col} >= ? AND {score_col} < ?",
                    (lo, hi))
        count = cur.fetchone()[0]
        bar = "█" * min(40, count // 10)
        log(f"    {lo:.1f}–{hi:.1f} : {count:5d}  {bar}")

    # Stats
    cur.execute(f"SELECT MIN({score_col}), MAX({score_col}), AVG({score_col}) FROM {belief_table}")
    mn, mx, avg = cur.fetchone()
    log(f"\n  min={mn:.4f}  max={mx:.4f}  avg={avg:.4f}")

    # Top 5 beliefs by score
    log(f"\n  Top 5 beliefs by {score_col}:")
    cur.execute(f"""
        SELECT {score_col}, {text_col}
        FROM {belief_table}
        ORDER BY {score_col} DESC
        LIMIT 5
    """)
    for score, text in cur.fetchall():
        log(f"    [{score:.4f}] {str(text)[:80]}")

    # Bottom 5
    log(f"\n  Bottom 5 beliefs by {score_col}:")
    cur.execute(f"""
        SELECT {score_col}, {text_col}
        FROM {belief_table}
        ORDER BY {score_col} ASC
        LIMIT 5
    """)
    for score, text in cur.fetchall():
        log(f"    [{score:.4f}] {str(text)[:80]}")

    return score_col, avg, mn, mx


# ── 3. PYRAMID DEPTH ANALYSIS ──────────────────────────────────
def check_pyramid_depth(cur, pyramid_tables, cols):
    banner("3. PYRAMID DEPTH ANALYSIS")

    if not pyramid_tables:
        log("[SKIP] No pyramid tables to analyse")
        return

    for t in pyramid_tables:
        available = cols[t]
        depth_col = next((c for c in ["depth","level","tier","layer"] if c in available), None)
        score_col = next((c for c in ["confidence","score","strength","quality_score","activation"]
                          if c in available), None)
        status_col = next((c for c in ["status","state","promoted","falsified","active"]
                           if c in available), None)
        text_col  = next((c for c in ["content","belief","text","statement"] if c in available), None)

        log(f"  Table: {t}")
        log(f"  depth_col={depth_col} score_col={score_col} status_col={status_col}")

        if depth_col:
            cur.execute(f"SELECT {depth_col}, COUNT(*) FROM {t} GROUP BY {depth_col} ORDER BY {depth_col}")
            rows = cur.fetchall()
            log(f"  Depth breakdown:")
            for depth, count in rows:
                log(f"    depth={depth}: {count} beliefs")

        if score_col:
            cur.execute(f"SELECT MIN({score_col}), MAX({score_col}), AVG({score_col}) FROM {t}")
            mn, mx, avg = cur.fetchone()
            log(f"  Scores: min={mn:.4f} max={mx:.4f} avg={avg:.4f}")

        if status_col:
            cur.execute(f"SELECT {status_col}, COUNT(*) FROM {t} GROUP BY {status_col}")
            log(f"  Status breakdown:")
            for status, count in cur.fetchall():
                log(f"    {status}: {count}")

        # Sample falsified beliefs
        if status_col and text_col and score_col:
            cur.execute(f"""
                SELECT {score_col}, {text_col}, {status_col}
                FROM {t}
                WHERE {status_col} LIKE '%fals%' OR {status_col} = 'rejected'
                LIMIT 5
            """)
            rows = cur.fetchall()
            if rows:
                log(f"\n  Sample falsified beliefs:")
                for score, text, status in rows:
                    log(f"    [{score:.4f}|{status}] {str(text)[:70]}")


# ── 4. SCAN SOURCE FOR THRESHOLDS ─────────────────────────────
def scan_source_thresholds():
    banner("4. SOURCE CODE THRESHOLD SCAN")

    keywords = ["promote", "falsif", "threshold", "pyramid", "depth", "min_score",
                "promotion_threshold", "PYRAMID", "pyramid_thresh"]
    found_any = False

    for path in SCAN_PATHS:
        full = os.path.expanduser(path)
        if not os.path.exists(full):
            continue
        try:
            with open(full) as f:
                lines = f.readlines()
        except Exception:
            continue

        matches = []
        for i, line in enumerate(lines, 1):
            if any(kw.lower() in line.lower() for kw in keywords):
                matches.append((i, line.rstrip()))

        if matches:
            found_any = True
            log(f"\n  File: {full}")
            for lineno, line in matches:
                log(f"    L{lineno:4d}: {line[:100]}")

    if not found_any:
        log("  [WARN] No threshold definitions found in known paths.")
        log("  Try: grep -r 'promote\\|falsif\\|pyramid\\|threshold' ~/Desktop/nex/ --include='*.py' -n")


# ── 5. CONTRA BELIEFS IN PYRAMID ──────────────────────────────
def check_contra_in_pyramid(cur, pyramid_tables, cols):
    banner("5. CONTRA BELIEFS IN PYRAMID")

    if not pyramid_tables:
        # Check if CONTRA beliefs exist in main beliefs table with pyramid-related cols
        log("[SKIP] No pyramid table — checking if CONTRA beliefs exist at all")
        cur.execute("SELECT COUNT(*) FROM beliefs WHERE content LIKE 'CONTRA:%'")
        try:
            count = cur.fetchone()[0]
            log(f"  CONTRA beliefs in beliefs table: {count}")
        except Exception as e:
            log(f"  {e}")
        return

    for t in pyramid_tables:
        text_col = next((c for c in ["content","belief","text","statement"] if c in cols[t]), None)
        if text_col:
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE {text_col} LIKE 'CONTRA:%'")
            count = cur.fetchone()[0]
            log(f"  CONTRA beliefs in {t}: {count}")


# ── 6. RECOMMENDATIONS ────────────────────────────────────────
def make_recommendations(score_avg, score_min, score_max, pyramid_tables):
    banner("6. RECOMMENDATIONS")

    if not pyramid_tables:
        log("""
  [CRITICAL] No pyramid table found at all.
  
  Either:
  A) The PYRAMID is tracked entirely in Python (no DB persistence) — check nex_pyramid.py
  B) The PYRAMID table has a different name — run:
     sqlite3 ~/.config/nex/nex.db '.tables'
  C) The PYRAMID module isn't writing to DB at all — it runs in memory and resets each cycle
     This would explain 0 promoted / 10 falsified forever.
""")
        return

    log(f"""
  Score stats: min={score_min:.3f} avg={score_avg:.3f} max={score_max:.3f}

  If PYRAMID promotion threshold > {score_max:.3f}:
    → Nothing will EVER be promoted. Lower threshold to avg ({score_avg:.3f}) or below.

  If falsification threshold < {score_min:.3f}:
    → Everything gets falsified immediately. Raise falsification floor.

  Recommended safe values (adjust in nex_pyramid.py or config):
    PROMOTION_THRESHOLD  = {score_avg * 0.85:.3f}   (85% of current avg)
    FALSIFICATION_FLOOR  = {score_min * 0.5:.3f}    (50% of current min)

  Also check: is CONTRA tag causing auto-falsification?
  If your FORGE or PYRAMID treats CONTRA: prefix as low-quality, add an exemption.
""")


# ── FIX MODE ──────────────────────────────────────────────────
def apply_fix(cur, con, pyramid_tables, cols, score_avg):
    banner("APPLYING FIX")

    if not pyramid_tables:
        log("[SKIP] No pyramid table to fix directly. Fix must be applied in source.")
        return

    for t in pyramid_tables:
        available  = cols[t]
        score_col  = next((c for c in ["confidence","score","strength"] if c in available), None)
        status_col = next((c for c in ["status","state"] if c in available), None)

        if status_col and score_col:
            # Rescue beliefs that were falsified but have score above floor
            floor = score_avg * 0.4
            cur.execute(f"""
                UPDATE {t}
                SET {status_col} = 'active'
                WHERE ({status_col} LIKE '%fals%' OR {status_col} = 'rejected')
                  AND {score_col} > ?
            """, (floor,))
            rescued = cur.rowcount
            con.commit()
            log(f"  Rescued {rescued} falsified beliefs with score > {floor:.3f}")
        else:
            log(f"  [SKIP] Cannot auto-fix {t} — status_col={status_col} score_col={score_col}")


# ── DUMP MODE ─────────────────────────────────────────────────
def dump_pyramid(cur, pyramid_tables, cols):
    banner("PYRAMID FULL DUMP")
    for t in pyramid_tables:
        cur.execute(f"SELECT * FROM {t} LIMIT 20")
        rows = cur.fetchall()
        log(f"\n  {t} (first 20 rows):")
        for r in rows:
            log(f"    {r}")


# ── MAIN ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix",  action="store_true", help="Apply threshold rescue fix")
    parser.add_argument("--dump", action="store_true", help="Dump full pyramid state")
    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════════╗
║         NEX PYRAMID DIAGNOSTIC                       ║
║  Why is depth-2 cycle promoting 0 / falsifying 10?   ║
╚══════════════════════════════════════════════════════╝
""")
    log(f"[START] DB={DB_PATH}")

    con = get_db()
    cur = con.cursor()
    tables, cols = get_all_tables(cur)
    log(f"[DB] Tables: {tables}")

    pyramid_tables = check_pyramid_tables(cur, tables, cols)
    result = check_belief_scores(cur, tables, cols)
    score_col = avg = mn = mx = None
    if result:
        score_col, avg, mn, mx = result

    check_pyramid_depth(cur, pyramid_tables, cols)
    scan_source_thresholds()
    check_contra_in_pyramid(cur, pyramid_tables, cols)

    if avg is not None:
        make_recommendations(avg, mn, mx, pyramid_tables)

    if args.fix and avg is not None:
        apply_fix(cur, con, pyramid_tables, cols, avg)

    if args.dump:
        dump_pyramid(cur, pyramid_tables, cols)

    con.close()
    log(f"[DONE] Log saved to {LOG_PATH}")


if __name__ == "__main__":
    main()
