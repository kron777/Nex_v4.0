#!/usr/bin/env python3
"""
theory_x_catalogue.py — Strike log viewer and resonance analyzer.

Usage:
    python3 theory_x_catalogue.py                 # summary
    python3 theory_x_catalogue.py --recent 10     # last N strikes
    python3 theory_x_catalogue.py --type self_probe  # filter by type
    python3 theory_x_catalogue.py --show <id>     # full detail of one strike
"""

import sys
import sqlite3
import json
import pathlib

DB = pathlib.Path.home() / "Desktop/nex/nex.db"


def summary():
    c = sqlite3.connect(str(DB))
    c.execute("PRAGMA busy_timeout=30000")
    total = c.execute("SELECT COUNT(*) FROM strike_log").fetchone()[0]
    print(f"=== strike catalogue — {total} total ===")
    print()
    if total == 0:
        print("(no strikes logged yet)")
        c.close()
        return
    print("by strike_type:")
    for row in c.execute("""
        SELECT strike_type, COUNT(*), AVG(resonance_score_tentative)
        FROM strike_log
        GROUP BY strike_type
        ORDER BY COUNT(*) DESC
    """):
        avg = row[2] if row[2] is not None else 0.0
        print(f"  {row[0]:<20}{row[1]:>5}  avg_resonance={avg:.2f}")
    print()
    print("by signature:")
    for row in c.execute("""
        SELECT resonance_signature, COUNT(*)
        FROM strike_log
        WHERE resonance_signature IS NOT NULL
        GROUP BY resonance_signature
        ORDER BY COUNT(*) DESC
    """):
        print(f"  {row[0]:<20}{row[1]:>5}")
    print()
    print("annotated (observer_notes present):")
    annotated = c.execute("SELECT COUNT(*) FROM strike_log WHERE observer_notes IS NOT NULL AND observer_notes != ''").fetchone()[0]
    print(f"  {annotated}/{total}")
    c.close()


def recent(n):
    c = sqlite3.connect(str(DB))
    rows = c.execute("""
        SELECT id, strike_type, substr(stimulus_text,1,40),
               response_word_count, resonance_score_tentative,
               resonance_signature, timestamp
        FROM strike_log
        ORDER BY id DESC
        LIMIT ?
    """, (n,)).fetchall()
    print(f"=== last {len(rows)} strikes ===")
    print(f"{'ID':<5}{'TYPE':<18}{'STIMULUS':<42}{'WC':<5}{'SCORE':<7}{'SIG':<18}")
    for r in rows:
        stim = str(r[2] or '(no stim)')[:40]
        score = r[4] if r[4] is not None else 0.0
        sig = r[5] or '(unannotated)'
        wc = r[3] or 0
        print(f"{r[0]:<5}{r[1]:<18}{stim:<42}{wc:<5}{score:.2f}  {sig:<18}")
    c.close()


def filter_type(t):
    c = sqlite3.connect(str(DB))
    rows = c.execute("""
        SELECT id, timestamp, substr(response_raw,1,200), resonance_score_tentative, resonance_signature
        FROM strike_log WHERE strike_type=?
        ORDER BY id DESC
    """, (t,)).fetchall()
    print(f"=== strikes of type {t} — {len(rows)} total ===")
    for r in rows:
        score = r[3] if r[3] is not None else 0.0
        sig = r[4] or '(unannotated)'
        print(f"\n[{r[0]}] {r[1]} — score={score:.2f} sig={sig}")
        print(f"  response: {r[2]}")
    c.close()


def show(strike_id):
    c = sqlite3.connect(str(DB))
    cur = c.execute("SELECT * FROM strike_log WHERE id=?", (strike_id,))
    r = cur.fetchone()
    if not r:
        print(f"no strike with id={strike_id}")
        return
    cols = [d[0] for d in cur.description]
    print(f"=== strike {strike_id} ===")
    for col, val in zip(cols, r):
        if col.endswith("_json") and val:
            try:
                obj = json.loads(val)
                print(f"{col}:")
                for k, v in obj.items():
                    print(f"  {k}: {v}")
            except Exception:
                print(f"{col}: {val}")
        elif col == "response_raw":
            print(f"{col}:")
            print(f"  {val}")
        elif col == "observer_notes" and val:
            print(f"{col}:")
            for line in str(val).split("\n"):
                print(f"  {line}")
        else:
            print(f"{col}: {val}")
    c.close()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        summary()
    elif sys.argv[1] == "--recent":
        recent(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    elif sys.argv[1] == "--type":
        filter_type(sys.argv[2])
    elif sys.argv[1] == "--show":
        show(int(sys.argv[2]))
    else:
        print(__doc__)
