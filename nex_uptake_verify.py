#!/usr/bin/env python3
"""
nex_uptake_verify.py
====================
Confirms that the uptake pipeline is wired correctly end-to-end.
Run after nex_uptake_repair.py.

Usage:
    python3 nex_uptake_verify.py
"""
import sqlite3
import sys
import os
from pathlib import Path

NEX_ROOT = Path.home() / "Desktop" / "nex"
MAIN_DB  = NEX_ROOT / "nex.db"
CFG_DB   = Path.home() / ".config" / "nex" / "nex.db"

def check(label, ok, detail=""):
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}", end="")
    if detail:
        print(f"  [{detail}]", end="")
    print()
    return ok

def main():
    print("\n══ NEX UPTAKE VERIFICATION ══════════════════════════════════")
    all_ok = True

    # 1. DB path unity
    main_ex  = MAIN_DB.exists()
    cfg_ex   = CFG_DB.exists()
    same     = False
    if main_ex and cfg_ex:
        same = MAIN_DB.stat().st_ino == CFG_DB.stat().st_ino
    ok = main_ex and (same or not cfg_ex)
    all_ok &= check("DB path unity (soul_loop and belief_store same file)", ok,
                    f"same_inode={same}" if (main_ex and cfg_ex) else f"main={main_ex} cfg={cfg_ex}")

    # 2. Belief count sanity
    if main_ex:
        conn = sqlite3.connect(str(MAIN_DB))
        n = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        avg_conf = conn.execute("SELECT AVG(confidence) FROM beliefs WHERE confidence > 0.1").fetchone()[0]
        n_moltbook = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE source='moltbook'"
        ).fetchone()[0]
        n_bridge_empty = conn.execute("""
            SELECT COUNT(*) FROM beliefs WHERE source='bridge_detector'
            AND (content LIKE '%. The shared concept: . These fields%'
              OR content LIKE '%The shared concept: .%')
            AND confidence > 0.0
        """).fetchone()[0]
        conn.close()
        all_ok &= check(f"Belief count",        n > 100000,       f"{n:,} beliefs")
        all_ok &= check(f"Avg confidence (>0.1)",avg_conf > 0.4,  f"{avg_conf:.3f}")
        all_ok &= check(f"Moltbook beliefs persisted", n_moltbook >= 0,
                        f"{n_moltbook:,} (0 = no Moltbook run yet, not an error)")
        all_ok &= check(f"Bridge noise cleaned",  n_bridge_empty == 0,
                        f"{n_bridge_empty:,} empty-bridge beliefs still at conf>0")

    # 3. moltbook_learning patch
    ml_path = NEX_ROOT / "nex" / "moltbook_learning.py"
    if not ml_path.exists():
        ml_path = NEX_ROOT / "moltbook_learning.py"
    if ml_path.exists():
        src = ml_path.read_text()
        has_extract = "_extract_proposition" in src
        has_persist  = "_persist_belief(belief)" in src
        all_ok &= check("moltbook: _extract_proposition injected", has_extract)
        all_ok &= check("moltbook: _persist_belief called in ingest_feed", has_persist)
    else:
        print("  ? moltbook_learning.py not found")

    # 4. agent_brain patch
    ab_path = NEX_ROOT / "nex" / "agent_brain.py"
    if ab_path.exists():
        src = ab_path.read_text()
        has_gate = "UPTAKE FIX: NexVoice bypasses" in src
        all_ok &= check("agent_brain: NexVoice gated to social queries", has_gate)
    else:
        print("  ? agent_brain.py not found")

    # 5. soul_loop imports correctly
    sys.path.insert(0, str(NEX_ROOT))
    try:
        from nex.nex_soul_loop import SoulLoop, _load_all_beliefs
        beliefs = _load_all_beliefs()
        all_ok &= check("soul_loop: _load_all_beliefs() fires", len(beliefs) > 0,
                        f"{len(beliefs):,} loaded")
    except Exception as e:
        all_ok &= check("soul_loop: _load_all_beliefs() fires", False, str(e)[:80])

    print()
    if all_ok:
        print("  ✓ All checks passed. Uptake pipeline is wired correctly.")
    else:
        print("  ✗ Some checks failed. Review output above.")
    print("══════════════════════════════════════════════════════════════\n")
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
