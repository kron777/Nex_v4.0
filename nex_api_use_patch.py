#!/usr/bin/env python3
"""
nex_api_use_patch.py — Wire reason() use_count feedback into /api/chat
Patches nex_api.py to call reason() after every chat reply and
increment use_count on retrieved beliefs.
Run once: python3 nex_api_use_patch.py
"""
from pathlib import Path

path = Path("~/Desktop/nex/nex_api.py").expanduser()
src  = path.read_text()

if "_fire_use_count_feedback" in src:
    print("Already patched.")
    exit(0)

# ── Add helper near the top of the chat route section ─────────────────────────
# Find the @app.route("/api/chat") line and insert before it
CHAT_MARKER = '@app.route("/api/chat", methods=["POST"])'
if CHAT_MARKER not in src:
    print("ERROR: /api/chat route not found")
    exit(1)

HELPER = '''
def _fire_use_count_feedback(query: str):
    """
    Call reason() in background after a chat reply to increment use_count
    on retrieved beliefs. Zero latency impact — fully async.
    """
    import threading
    def _run():
        try:
            from nex_reason import reason as _reason
            _reason(query, debug=False)   # use_count incremented inside reason()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True, name="use-feedback").start()


'''

src = src.replace(CHAT_MARKER, HELPER + CHAT_MARKER, 1)

# ── Wire into the chat route — fire after append_session_history ──────────────
# Target the line where NEX response is appended to history
OLD = '    # Append NEX response to history\n    append_session_history(session_id, "nex", result["response"])'
NEW = '    # Append NEX response to history\n    append_session_history(session_id, "nex", result["response"])\n\n    # Fire use_count feedback asynchronously (feeds quality scorer)\n    _fire_use_count_feedback(query)'

if OLD not in src:
    # Try alternative whitespace
    OLD = '    append_session_history(session_id, "nex", result["response"])\n\n    # Update session domain'
    NEW = '    append_session_history(session_id, "nex", result["response"])\n\n    # Fire use_count feedback asynchronously (feeds quality scorer)\n    _fire_use_count_feedback(query)\n\n    # Update session domain'

if OLD not in src:
    print("ERROR: append_session_history target not found — patch manually")
    print('Add _fire_use_count_feedback(query) after the append_session_history(session_id, "nex", ...) line in the chat route')
    exit(1)

src = src.replace(OLD, NEW, 1)
path.write_text(src)
print("PATCHED — /api/chat now fires use_count feedback after every reply")
print("  reason() called async, zero latency impact")
print("  Beliefs retrieved per query will have use_count incremented")
