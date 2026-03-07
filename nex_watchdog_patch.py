"""
nex_watchdog_patch.py
Singleton enforcement — prevents duplicate Telegram bot instances
which cause the "Conflict: terminated by other getUpdates" error.
"""
import os, sys, atexit

LOCK_FILE = "/tmp/nex_telegram.lock"

def enforce_singleton():
    """Kill any previous instance and claim the lock."""
    # Kill previous instance if lock exists
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            if old_pid != os.getpid():
                try:
                    os.kill(old_pid, 9)
                except ProcessLookupError:
                    pass  # already dead
        except Exception:
            pass

    # Write our PID
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))

    # Clean up on exit
    atexit.register(_release_lock)

def _release_lock():
    try:
        os.remove(LOCK_FILE)
    except Exception:
        pass
