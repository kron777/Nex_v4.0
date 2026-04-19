"""
nex_path2_logger.py — instrumentation for PATH 2 (LLM-path) calls.

Writes one row per call_llm PATH-2 outcome to `path2_log` in
nex_experiments.db. Used by fountain harness, R6 probe, and live service
(when the experimental bypass flag is on) to characterise what the LLM
produces once PATH 1 is out of the way.

Safe to import even if path2_log doesn't exist yet — ensure_table() is
idempotent with a 300s busy_timeout.
"""

from __future__ import annotations
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex_path2")

EXPERIMENTS_DB = Path(os.path.expanduser("~/Desktop/nex/nex_experiments.db"))


def _connect(timeout: int = 300) -> sqlite3.Connection:
    conn = sqlite3.connect(str(EXPERIMENTS_DB), timeout=timeout)
    conn.execute("PRAGMA busy_timeout=300000")
    return conn


def ensure_table() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS path2_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT    NOT NULL,
                query           TEXT,
                query_clean     TEXT,
                belief_count    INTEGER,
                system_prompt   TEXT,
                response_raw    TEXT,
                response_words  INTEGER,
                latency_ms      INTEGER,
                llm_server_up   INTEGER,
                status          TEXT,
                error_detail    TEXT,
                source          TEXT,
                finish_reason   TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_path2_timestamp ON path2_log(timestamp)"
        )
        conn.commit()
    finally:
        conn.close()


def log_call(
    query: str = "",
    query_clean: str = "",
    belief_count: int = 0,
    system_prompt: str = "",
    response_raw: Optional[str] = None,
    latency_ms: int = 0,
    llm_server_up: int = 1,
    status: str = "success",
    error_detail: str = "",
    source: str = "ad_hoc",
    finish_reason: str = "",
) -> None:
    """
    Record one PATH 2 attempt. Never raises — instrumentation must not crash
    the reply engine. On DB error, logs and returns.
    """
    try:
        ensure_table()
    except Exception as e:
        log.warning("ensure_table failed: %s", e)
        return

    resp = response_raw if isinstance(response_raw, str) else ""
    words = len(resp.split()) if resp else 0

    try:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO path2_log
                  (timestamp, query, query_clean, belief_count, system_prompt,
                   response_raw, response_words, latency_ms, llm_server_up,
                   status, error_detail, source, finish_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(),
                    query[:4000] if query else "",
                    query_clean[:2000] if query_clean else "",
                    belief_count,
                    system_prompt[:4000] if system_prompt else "",
                    resp[:4000],
                    words,
                    latency_ms,
                    llm_server_up,
                    status,
                    error_detail[:1000] if error_detail else "",
                    source,
                    finish_reason or "",
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        log.warning("log_call write failed: %s", e)


if __name__ == "__main__":
    ensure_table()
    log_call(
        query="self-test",
        query_clean="self-test",
        belief_count=0,
        system_prompt="test",
        response_raw="(no response — self-test)",
        latency_ms=0,
        llm_server_up=0,
        status="bypass_off",
        source="ad_hoc",
    )
    conn = _connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM path2_log").fetchone()[0]
        print(f"path2_log rows: {n}")
        for r in conn.execute(
            "SELECT id, timestamp, status, source, substr(response_raw,1,40) "
            "FROM path2_log ORDER BY id DESC LIMIT 3"
        ).fetchall():
            print(" ", r)
    finally:
        conn.close()
