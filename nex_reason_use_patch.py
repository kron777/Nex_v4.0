#!/usr/bin/env python3
"""
Patch nex_reason.py to increment use_count on retrieved beliefs.
Run once: python3 nex_reason_use_patch.py
"""
from pathlib import Path
import re

path = Path("~/Desktop/nex/nex_reason.py").expanduser()
src  = path.read_text()

# Check if patch already applied
if "_increment_use_counts" in src:
    print("Already patched.")
    exit(0)

# The function to add — increments use_count for retrieved belief IDs
new_func = '''
# ── use_count feedback ────────────────────────────────────────────────────────
def _increment_use_counts(belief_ids: list):
    """
    Increment use_count for every belief retrieved during a reason() call.
    This feeds the use_freq component of nex_belief_quality.score_belief().
    Fire-and-forget in a background thread to avoid blocking.
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

# Insert before the public API section
insert_marker = "# ── public API ────────────────────────────────────────────────────────────"
if insert_marker not in src:
    print(f"ERROR: marker not found — check nex_reason.py manually")
    exit(1)

src = src.replace(insert_marker, new_func + insert_marker)

# Now patch the reason() function to call _increment_use_counts after retrieval
# Find where supporting beliefs are finalised and add the call
old_call = '''    matched_tensions = _match_tensions(query, tensions)'''
new_call = '''    # Increment use_count for all retrieved beliefs (feeds quality scorer)
    _used_ids = [b["id"] for b in supporting + opposing if "id" in b]
    if _used_ids:
        _increment_use_counts(_used_ids)

    matched_tensions = _match_tensions(query, tensions)'''

if old_call not in src:
    print("ERROR: reason() call site not found — patch manually")
    print("Add _increment_use_counts([b['id'] for b in supporting+opposing if 'id' in b])")
    print("before the matched_tensions line in reason()")
    exit(1)

src = src.replace(old_call, new_call)
path.write_text(src)
print("PATCHED — nex_reason.py now increments use_count on retrieved beliefs")
print("  Every reason() call will update use_count for supporting + opposing beliefs")
print("  This feeds the use_freq component of the quality scorer")
