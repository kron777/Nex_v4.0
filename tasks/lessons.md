# NEX Project Lessons
*Patterns learned the hard way. Read at session start.*

## Wiring & live-process gotchas
- Confirm what the live process actually imports before editing.
  Check `pgrep -af python | grep nex_api` and trace imports.
- /home/rr/Desktop/nex → /media/rr/NEX/nex_core (symlink, same
  inodes). But /home/rr/Desktop/nex5 is a SEPARATE project.
- HUD chat endpoint runs from /home/rr/Desktop/nex5/gui/server.py
  (port 8765), NOT nex_core/nex_api.py (port 7823).

## Validation discipline
- Synthetic/mocked tests are NOT verification. Send real request
  through actual UI before claiming "wiring complete."
- Restart live process to activate code changes — Python caches
  imports.

## SQLite write-lock (A.2-D pattern)
- All write-site sqlite3.connect calls need isolation_level=None.
- Audit:
    grep -rn "sqlite3.connect(" --include="*.py" \
      /media/rr/NEX/nex_core/ | grep -v isolation_level=None
- Multi-statement atomic writes: nex_db_gatekeeper.transaction()

## FocalSet smoothing
- First-appearance vs subsequent: with max_delta clamp, first
  appearance must seed at raw value (not clamp from 0).

## Git hygiene
- `git status` before assuming committed.
