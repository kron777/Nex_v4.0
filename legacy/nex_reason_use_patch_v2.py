#!/usr/bin/env python3
"""
nex_reason_use_patch_v2.py — Wire use_count feedback into nex_reason.py
Targets exact line content from live file.
Run once: python3 nex_reason_use_patch_v2.py
"""
from pathlib import Path

path = Path("~/Desktop/nex/nex_reason.py").expanduser()
src  = path.read_text()

if "_increment_use_counts" in src:
    print("Already patched.")
    exit(0)

# ── Insert helper function before public API section ──────────────────────────
MARKER = "# ── public API ────────────────────────────────────────────────────"

NEW_FUNC = '''# ── use_count feedback ───────────────────────────────────────────────────────
def _increment_use_counts(belief_ids: list):
    """
    Increment use_count for every belief retrieved during reason().
    Feeds the use_freq component of nex_belief_quality.score_belief().
    Runs fire-and-forget in a background thread.
    """
    if not belief_ids or not DB_PATH.exists():
        return
    def _write():
        try:
            con = _db()
            for bid in belief_ids:
                try:
                    con.execute(
                        "UPDATE beliefs SET use_count = COALESCE(use_count, 0) + 1 WHERE id = ?",
                        (bid,)
                    )
                except Exception:
                    pass
            con.commit()
            con.close()
        except Exception:
            pass
    threading.Thread(target=_write, daemon=True, name="use-count-update").start()


'''

if MARKER not in src:
    print(f"ERROR: public API marker not found")
    exit(1)

src = src.replace(MARKER, NEW_FUNC + MARKER, 1)

# ── Patch reason() to call _increment_use_counts ──────────────────────────────
# Target line 443: "    matched_tensions = _match_tensions(query, tensions)"
OLD = "    matched_tensions = _match_tensions(query, tensions)"
NEW = """    # Increment use_count for retrieved beliefs (feeds quality scorer)
    _used_ids = [b["id"] for b in supporting + opposing if "id" in b]
    if _used_ids:
        _increment_use_counts(_used_ids)

    matched_tensions = _match_tensions(query, tensions)"""

if OLD not in src:
    print("ERROR: matched_tensions line not found")
    exit(1)

src = src.replace(OLD, NEW, 1)

path.write_text(src)
print("PATCHED — nex_reason.py now increments use_count on retrieved beliefs")
print("  Threading: fire-and-forget, zero latency impact on replies")
