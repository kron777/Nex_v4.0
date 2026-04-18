"""nex_db_gatekeeper.py v2 — subclass-based, Python 3.12 compatible."""

import sqlite3
import threading
import logging
import re
import time

__all__ = ['install', 'STATS']
log = logging.getLogger(__name__)

_WRITE_LOCK = threading.RLock()

STATS = {
    'connections_created': 0,
    'writes_serialized': 0,
    'reads_passed_through': 0,
    'lock_waits_total_ms': 0.0,
    'max_lock_wait_ms': 0.0,
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


class _GatedCursor(sqlite3.Cursor):
    def execute(self, sql, *args, **kwargs):
        if _is_write(sql):
            t0 = time.perf_counter()
            with _WRITE_LOCK:
                _track_wait(t0)
                STATS['writes_serialized'] += 1
                return super().execute(sql, *args, **kwargs)
        STATS['reads_passed_through'] += 1
        return super().execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        if _is_write(sql):
            t0 = time.perf_counter()
            with _WRITE_LOCK:
                _track_wait(t0)
                STATS['writes_serialized'] += 1
                return super().executemany(sql, *args, **kwargs)
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
            with _WRITE_LOCK:
                _track_wait(t0)
                STATS['writes_serialized'] += 1
                return super().execute(sql, *args, **kwargs)
        STATS['reads_passed_through'] += 1
        return super().execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        if _is_write(sql):
            t0 = time.perf_counter()
            with _WRITE_LOCK:
                _track_wait(t0)
                STATS['writes_serialized'] += 1
                return super().executemany(sql, *args, **kwargs)
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
    print("[nex_db_gatekeeper] v2 installed — writes serialized via process RLock")


install()
