#!/usr/bin/env python3
"""
patch_tension_intake.py — caps tension intake + fixes nex_v72.py location
Run from ~/Desktop/nex/: python3 patch_tension_intake.py
"""
import sqlite3, shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent

# ── 1. Copy nex_v72.py to correct location ────────────────────
src_v72  = ROOT / "nex_v72.py"
dest_v72 = ROOT / "nex_upgrades" / "nex_v72.py"

if src_v72.exists():
    shutil.copy2(src_v72, dest_v72)
    print(f"✓ nex_v72.py copied → nex_upgrades/nex_v72.py")
elif dest_v72.exists():
    print("✓ nex_upgrades/nex_v72.py already in place")
else:
    print("✗ nex_v72.py not found in either location")

# ── 2. Patch nex_tension_pressure.py — add intake cap ─────────
F   = ROOT / "nex_tension_pressure.py"
BAK = ROOT / "nex_tension_pressure.py.bak2"
assert F.exists(), "nex_tension_pressure.py not found"

src = F.read_text()
BAK.write_text(src)

# Add MAX_NEW_TENSIONS_PER_CYCLE constant after MAX_DREAM_QUEUE
ANCHOR_CONST = "MAX_DREAM_QUEUE = 25  # max items in dream priority queue"
INSERT_CONST = (
    "MAX_DREAM_QUEUE = 25  # max items in dream priority queue\n"
    "MAX_NEW_TENSIONS_PER_CYCLE = 5   # max new tension inserts per cycle\n"
)

if "MAX_NEW_TENSIONS_PER_CYCLE" in src:
    print("✓ MAX_NEW_TENSIONS_PER_CYCLE already present")
elif ANCHOR_CONST in src:
    src = src.replace(ANCHOR_CONST, INSERT_CONST, 1)
    print("✓ Added MAX_NEW_TENSIONS_PER_CYCLE = 5")
else:
    print("✗ Constant anchor not found — adding at top of thresholds block")
    FALLBACK = "ESCALATE_AFTER = 20"
    if FALLBACK in src:
        src = src.replace(
            FALLBACK,
            "MAX_NEW_TENSIONS_PER_CYCLE = 5   # max new tension inserts per cycle\n"
            + FALLBACK, 1
        )
        print("✓ Added MAX_NEW_TENSIONS_PER_CYCLE via fallback anchor")

# Patch _ensure_tension_schema to add intake counter column
ANCHOR_SCHEMA = "        if not exists:\n            conn.execute(\"\"\"\n                CREATE TABLE IF NOT EXISTS tensions ("
INSERT_SCHEMA = (
    "        if not exists:\n"
    "            conn.execute(\"\"\"\n"
    "                CREATE TABLE IF NOT EXISTS tensions ("
)
# Already exists — skip, just patch run_pressure_cycle to cap inserts

# Patch run_pressure_cycle: add intake cap before increment
ANCHOR_CYCLE = (
    "        # Increment cycle_count for all unresolved tensions\n"
    "        conn.execute(\"\"\"\n"
    "            UPDATE tensions\n"
    "            SET cycle_count = cycle_count + 1\n"
    "            WHERE resolved_at IS NULL\n"
    "        \"\"\")"
)
INSERT_CYCLE = (
    "        # Cap: auto-resolve excess tensions above hard limit before incrementing\n"
    "        _q_now = conn.execute(\n"
    "            \"SELECT COUNT(*) FROM tensions WHERE resolved_at IS NULL\"\n"
    "        ).fetchone()[0]\n"
    "        if _q_now > 60:\n"
    "            _excess = _q_now - 60\n"
    "            conn.execute(\"\"\"\n"
    "                UPDATE tensions SET resolved_at = datetime('now')\n"
    "                WHERE id IN (\n"
    "                    SELECT id FROM tensions\n"
    "                    WHERE resolved_at IS NULL AND escalation_level = 0\n"
    "                    ORDER BY weight ASC, rowid ASC\n"
    "                    LIMIT ?\n"
    "                )\n"
    "            \"\"\", (_excess,))\n"
    "            if verbose:\n"
    "                print(f\"  [TensionPressure] auto-trimmed {_excess} excess tensions\")\n"
    "        # Increment cycle_count for all unresolved tensions\n"
    "        conn.execute(\"\"\"\n"
    "            UPDATE tensions\n"
    "            SET cycle_count = cycle_count + 1\n"
    "            WHERE resolved_at IS NULL\n"
    "        \"\"\")"
)

if "auto-trimmed" in src:
    print("✓ Intake cap already patched in run_pressure_cycle")
elif ANCHOR_CYCLE in src:
    src = src.replace(ANCHOR_CYCLE, INSERT_CYCLE, 1)
    print("✓ Intake cap added to run_pressure_cycle (hard limit=60)")
else:
    print("✗ Cycle anchor not found — manual patch needed")

F.write_text(src)

# ── 3. Drain DB again to 50 ───────────────────────────────────
DB = Path.home() / ".config" / "nex" / "nex.db"
if DB.exists():
    conn = sqlite3.connect(str(DB))
    now  = datetime.now().isoformat()
    before = conn.execute("SELECT COUNT(*) FROM tensions WHERE resolved_at IS NULL").fetchone()[0]
    if before > 50:
        excess = before - 50
        conn.execute("""
            UPDATE tensions SET resolved_at = ?
            WHERE id IN (
                SELECT id FROM tensions
                WHERE resolved_at IS NULL AND escalation_level = 0
                ORDER BY weight ASC, rowid ASC
                LIMIT ?
            )
        """, (now, excess))
        conn.execute("""
            UPDATE tensions SET cycle_count=0, escalation_level=0, is_paradox=0
            WHERE resolved_at IS NULL
        """)
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM tensions WHERE resolved_at IS NULL").fetchone()[0]
        print(f"✓ DB: {before} → {after} unresolved tensions")
    else:
        conn.execute("UPDATE tensions SET cycle_count=0 WHERE resolved_at IS NULL")
        conn.commit()
        print(f"✓ DB: {before} tensions, cycle counts reset")
    conn.close()

print("\n✓ Done. Restart NEX.")
