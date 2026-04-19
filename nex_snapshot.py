"""
nex_snapshot.py — create a consistent read-only snapshot of nex.db for experiments.

Uses sqlite3's online backup API, which copies a transactionally-consistent view
even while other processes write to the source. Output file is NOT a symlink — it
is a byte copy, so the live brain's subsequent writes do not affect it.

Usage:
  python3 nex_snapshot.py                           # snapshot to default path
  python3 nex_snapshot.py --out /tmp/nex_frozen.db  # custom path
  NEX_BELIEFS_DB=/home/rr/Desktop/nex/nex_snapshot.db python3 nex_fountain_harness.py ...

Also exposes describe_snapshot() for harnesses to log snapshot freshness at
experiment start — prevents accidental stale-snapshot experiments.
"""

from __future__ import annotations
import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

DEFAULT_SRC = Path(os.path.expanduser("~/Desktop/nex/nex.db"))
DEFAULT_DST = Path(os.path.expanduser("~/Desktop/nex/nex_snapshot.db"))


def snapshot(src: Path = DEFAULT_SRC, dst: Path = DEFAULT_DST) -> dict:
    if not src.exists():
        raise FileNotFoundError(f"source DB not found: {src}")
    # Remove stale snapshot (and any leftover -shm/-wal from a prior crash)
    for suffix in ("", "-shm", "-wal"):
        p = dst.with_name(dst.name + suffix)
        if p.exists():
            p.unlink()

    t0 = time.time()
    # Open source read-only via URI to avoid acquiring a write lock
    src_uri = f"file:{src}?mode=ro"
    src_conn = sqlite3.connect(src_uri, uri=True, timeout=300)
    src_conn.execute("PRAGMA busy_timeout=300000")
    dst_conn = sqlite3.connect(str(dst), timeout=300)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    dt = time.time() - t0
    size = dst.stat().st_size

    # Integrity check
    check = sqlite3.connect(str(dst), timeout=30)
    try:
        n = check.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        integrity = check.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        check.close()

    return {
        "src": str(src),
        "dst": str(dst),
        "bytes": size,
        "beliefs": n,
        "integrity": integrity,
        "seconds": round(dt, 2),
        "snapshot_time": datetime.now().isoformat(),
    }


def describe_snapshot(path: Optional[str] = None) -> dict:
    """
    Return {'path', 'exists', 'mtime', 'age_sec', 'beliefs'} for a snapshot DB.
    If path is None, checks the NEX_BELIEFS_DB env var. Used by harnesses at
    experiment start for freshness logging.
    """
    p = Path(path or os.environ.get("NEX_BELIEFS_DB") or "")
    out = {"path": str(p), "exists": False}
    if not p or not p.exists():
        return out
    out["exists"] = True
    st = p.stat()
    out["mtime"] = datetime.fromtimestamp(st.st_mtime).isoformat()
    out["age_sec"] = round(time.time() - st.st_mtime, 1)
    try:
        conn = sqlite3.connect(str(p), timeout=10)
        try:
            out["beliefs"] = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        finally:
            conn.close()
    except Exception as e:
        out["beliefs_error"] = str(e)[:200]
    return out


def log_snapshot_freshness(logger=None) -> None:
    """Print snapshot freshness if NEX_BELIEFS_DB is set. Safe no-op otherwise."""
    if not os.environ.get("NEX_BELIEFS_DB"):
        return
    d = describe_snapshot()
    msg = (f"snapshot in use: path={d.get('path')} "
           f"mtime={d.get('mtime','?')} age={d.get('age_sec','?')}s "
           f"beliefs={d.get('beliefs','?')}")
    if logger is not None:
        logger.info(msg)
    else:
        print(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--out", default=str(DEFAULT_DST))
    args = ap.parse_args()
    result = snapshot(Path(args.src), Path(args.out))
    print("snapshot complete:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    if result["integrity"] != "ok":
        print("WARNING: integrity check did not return 'ok'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
