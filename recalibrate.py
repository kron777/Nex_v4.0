#!/usr/bin/env python3
"""
recalibrate.py — One-time belief confidence recalibration for NEX
Run once: python3 recalibrate.py

Lowers all belief confidence scores above 0.82 (old inflated values).
New formula target: realistic 0.20-0.60 range.
"""
import sqlite3, os, json

DB_PATH = os.path.expanduser("~/.config/nex/nex_data/nex.db")
BELIEFS_CACHE = os.path.expanduser("~/.config/nex/beliefs.json")

print("╔══════════════════════════════════════╗")
print("║   NEX Belief Recalibration Script    ║")
print("╚══════════════════════════════════════╝\n")

# ── SQLite DB ──────────────────────────────────────────────────
db = sqlite3.connect(DB_PATH)

before = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence > 0.82").fetchone()[0]
total  = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
print(f"  Total beliefs in DB : {total}")
print(f"  Beliefs above 0.82  : {before}  (will be recalibrated)\n")

db.execute("UPDATE beliefs SET confidence = ROUND(confidence * 0.55, 4) WHERE confidence > 0.82")
db.commit()

after = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence > 0.82").fetchone()[0]
avg   = db.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0]
print(f"  ✓ Recalibrated. Beliefs still above 0.82 : {after}")
print(f"  ✓ New average confidence                 : {avg:.3f}\n")
db.close()

# ── beliefs.json cache ─────────────────────────────────────────
if os.path.exists(BELIEFS_CACHE):
    try:
        data = json.load(open(BELIEFS_CACHE))
        changed = 0
        for b in data:
            if isinstance(b, dict) and b.get("confidence", 0) > 0.82:
                b["confidence"] = round(b["confidence"] * 0.55, 4)
                changed += 1
        json.dump(data, open(BELIEFS_CACHE, "w"))
        print(f"  ✓ beliefs.json cache updated — {changed} entries recalibrated")
    except Exception as e:
        print(f"  ✗ beliefs.json cache error: {e}")

print("\nDone. Restart NEX for changes to take effect.")
print("  nex\n")
