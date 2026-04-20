"""nex_db_gatekeeper.py v3 — hardened against writer starvation.

Changes from v2:
- LOCK_TIMEOUT_S × LOCK_RETRY_ATTEMPTS bounded acquire (vs unbounded blocking)
- _LOCK_OWNER tracking with re-entrant depth counter
- TimeoutError on persistent contention (with diagnostic SQL + holder tid)
- Watchdog thread logs warnings when lock held >30s
- Caller interface unchanged: write either succeeds or raises (no hidden retries)
"""

import sqlite3
import threading
import logging
import re
import time

__all__ = ['install', 'STATS', 'LOCK_TIMEOUT_S', 'LOCK_RETRY_ATTEMPTS']
log = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────
LOCK_TIMEOUT_S = 10           # per-attempt wait before retry
LOCK_RETRY_ATTEMPTS = 3       # total attempts before raising TimeoutError
LOCK_RETRY_SLEEP_S = 0.1      # back-off between attempts
WATCHDOG_INTERVAL_S = 10      # how often watchdog wakes
WATCHDOG_WARN_THRESHOLD_S = 30  # only log if held longer than this

# ── Lock + owner tracking ────────────────────────────────────────────
_WRITE_LOCK = threading.RLock()
_LOCK_OWNER = {'tid': None, 'sql': None, 'acquired_at': None, 'depth': 0}
_LOCK_OWNER_LOCK = threading.Lock()  # protects _LOCK_OWNER metadata only

STATS = {
    'connections_created': 0,
    'writes_serialized': 0,
    'reads_passed_through': 0,
    'lock_waits_total_ms': 0.0,
    'max_lock_wait_ms': 0.0,
    'lock_timeouts': 0,
    'watchdog_warnings': 0,
}

_WRITE_RE = re.compile(
    r'^\s*(?:/\*.*?\*/\s*|--[^\n]*\n\s*)*'
    r'(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|TRUNCATE|BEGIN|COMMIT|ROLLBACK|VACUUM|REINDEX|ANALYZE)',
    re.IGNORECASE | re.DOTALL
)

def _is_write(sql):
    if not isinstance(sql, str):
        return False
    return bool(_WRITE_RE.match(sql))

def _track_wait(t0):
    elapsed_ms = (time.perf_counter() - t0) * 1000
    STATS['lock_waits_total_ms'] += elapsed_ms
    if elapsed_ms > STATS['max_lock_wait_ms']:
        STATS['max_lock_wait_ms'] = elapsed_ms


# ── Acquire / release with bounded retry + owner tracking ────────────
def _acquire_write_lock(sql):
    """Acquire _WRITE_LOCK with bounded retry. Raises TimeoutError on persistent contention."""
    tid = threading.get_ident()
    for attempt in range(LOCK_RETRY_ATTEMPTS):
        if _WRITE_LOCK.acquire(timeout=LOCK_TIMEOUT_S):
            with _LOCK_OWNER_LOCK:
                if _LOCK_OWNER['tid'] == tid and _LOCK_OWNER['depth'] > 0:
                    # Re-entrant acquisition by same thread — bump depth, preserve original metadata
                    _LOCK_OWNER['depth'] += 1
                else:
                    _LOCK_OWNER['tid'] = tid
                    _LOCK_OWNER['sql'] = sql[:80] if sql else None
                    _LOCK_OWNER['acquired_at'] = time.time()
                    _LOCK_OWNER['depth'] = 1
            return
        if attempt < LOCK_RETRY_ATTEMPTS - 1:
            time.sleep(LOCK_RETRY_SLEEP_S)

    # All attempts failed — gather diagnostic and raise
    with _LOCK_OWNER_LOCK:
        holder_tid = _LOCK_OWNER.get('tid')
        holder_sql = _LOCK_OWNER.get('sql')
        holder_acquired_at = _LOCK_OWNER.get('acquired_at')
    held_for = (time.time() - holder_acquired_at) if holder_acquired_at else None
    STATS['lock_timeouts'] += 1
    raise TimeoutError(
        f"gatekeeper: write lock unavailable after "
        f"{LOCK_RETRY_ATTEMPTS}x{LOCK_TIMEOUT_S}s. "
        f"holder tid={holder_tid} sql={holder_sql!r} held_for={held_for}s. "
        f"attempted sql={(sql[:80] if sql else None)!r}"
    )


def _release_write_lock():
    """Release _WRITE_LOCK. Decrements depth; clears owner only when fully released."""
    with _LOCK_OWNER_LOCK:
        if _LOCK_OWNER['depth'] > 1:
            _LOCK_OWNER['depth'] -= 1
        else:
            _LOCK_OWNER['tid'] = None
            _LOCK_OWNER['sql'] = None
            _LOCK_OWNER['acquired_at'] = None
            _LOCK_OWNER['depth'] = 0
    _WRITE_LOCK.release()


# ── Watchdog ──────────────────────────────────────────────────────────
def _watchdog_loop():
    """Periodic check — log warning if lock held >threshold; opportunistic WAL truncate when idle.

    Runs every WATCHDOG_INTERVAL_S seconds. Two responsibilities:
      1. If a writer holds the lock longer than WATCHDOG_WARN_THRESHOLD_S, log it.
      2. Every 6 intervals (~60s), if NO writer is active, issue
         PRAGMA wal_checkpoint(TRUNCATE) to reclaim cosmetic WAL file space.
         Skipped silently when a holder is active (don't compete with a live writer).
    """
    checkpoint_counter = 0
    while True:
        try:
            time.sleep(WATCHDOG_INTERVAL_S)
            with _LOCK_OWNER_LOCK:
                holder_tid = _LOCK_OWNER.get('tid')
                holder_acquired_at = _LOCK_OWNER.get('acquired_at')
                holder_sql = _LOCK_OWNER.get('sql')

            # Warn-if-held check (no-op when no holder)
            if holder_tid is not None and holder_acquired_at is not None:
                held = time.time() - holder_acquired_at
                if held > WATCHDOG_WARN_THRESHOLD_S:
                    STATS['watchdog_warnings'] += 1
                    log.warning(
                        f"[gatekeeper watchdog] write lock held {held:.1f}s "
                        f"by tid={holder_tid} sql={holder_sql!r}"
                    )

            # Opportunistic WAL truncate every 6 intervals (~60s) when idle.
            checkpoint_counter += 1
            if checkpoint_counter >= 6:
                checkpoint_counter = 0
                if holder_tid is None:
                    try:
                        import os
                        db_path = os.path.expanduser("~/Desktop/nex/nex.db")
                        conn = sqlite3.connect(db_path, timeout=2)
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                        conn.close()
                    except Exception as e:
                        log.debug(f"[gatekeeper watchdog] checkpoint skip: {e}")
        except Exception as e:
            log.exception(f"[gatekeeper watchdog] internal error: {e}")


# ── Subclassed connection / cursor ────────────────────────────────────
class _GatedCursor(sqlite3.Cursor):
    def execute(self, sql, *args, **kwargs):
        if _is_write(sql):
            t0 = time.perf_counter()
            _acquire_write_lock(sql)
            try:
                _track_wait(t0)
                STATS['writes_serialized'] += 1
                return super().execute(sql, *args, **kwargs)
            finally:
                _release_write_lock()
        STATS['reads_passed_through'] += 1
        return super().execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        if _is_write(sql):
            t0 = time.perf_counter()
            _acquire_write_lock(sql)
            try:
                _track_wait(t0)
                STATS['writes_serialized'] += 1
                return super().executemany(sql, *args, **kwargs)
            finally:
                _release_write_lock()
        STATS['reads_passed_through'] += 1
        return super().executemany(sql, *args, **kwargs)


class _GatedConnection(sqlite3.Connection):
    def cursor(self, *args, **kwargs):
        if args or 'factory' in kwargs:
            return super().cursor(*args, **kwargs)
        return super().cursor(_GatedCursor)

    def execute(self, sql, *args, **kwargs):
        if _is_write(sql):
            t0 = time.perf_counter()
            _acquire_write_lock(sql)
            try:
                _track_wait(t0)
                STATS['writes_serialized'] += 1
                return super().execute(sql, *args, **kwargs)
            finally:
                _release_write_lock()
        STATS['reads_passed_through'] += 1
        return super().execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        if _is_write(sql):
            t0 = time.perf_counter()
            _acquire_write_lock(sql)
            try:
                _track_wait(t0)
                STATS['writes_serialized'] += 1
                return super().executemany(sql, *args, **kwargs)
            finally:
                _release_write_lock()
        STATS['reads_passed_through'] += 1
        return super().executemany(sql, *args, **kwargs)


def install():
    if getattr(sqlite3, '_gatekept', False):
        return
    real_connect = sqlite3.connect
    sqlite3._real_connect = real_connect

    def gatekept_connect(*args, **kwargs):
        STATS['connections_created'] += 1
        if 'factory' not in kwargs:
            kwargs['factory'] = _GatedConnection
        conn = real_connect(*args, **kwargs)
        try:
            conn.execute("PRAGMA busy_timeout=60000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception as e:
            log.warning("gatekeeper: PRAGMA setup failed: %s", e)
        return conn

    sqlite3.connect = gatekept_connect
    sqlite3._gatekept = True

    # Watchdog uses log.warning — relies on logging being configured by caller.
    # If no handlers are set, Python's lastResort handler still emits to stderr at WARNING level.
    _wd = threading.Thread(target=_watchdog_loop, daemon=True, name='gatekeeper-watchdog')
    _wd.start()

    _logging_status = (
        "logging configured" if logging.getLogger().hasHandlers()
        else "logging not configured (lastResort stderr)"
    )
    print(
        f"[nex_db_gatekeeper] v3 installed — bounded acquire "
        f"({LOCK_RETRY_ATTEMPTS}x{LOCK_TIMEOUT_S}s) + owner tracking + watchdog ({_logging_status})"
    )


install()
