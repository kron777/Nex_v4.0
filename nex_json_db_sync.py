#!/usr/bin/env python3
"""
nex_json_db_sync.py
-------------------
Syncs NEX JSON flat-file data (reflections, agents) into the SQLite DB.
Safe to run multiple times — fully idempotent via content-hash deduplication.

Usage:
    python3 nex_json_db_sync.py [--dry-run] [--verbose]

Flags:
    --dry-run    Show what would be inserted without touching the DB
    --verbose    Print each record being processed
"""

import json
import sqlite3
import hashlib
import argparse
import sys
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

NEX_CONFIG_DIR = Path.home() / ".config" / "nex"
DB_PATH        = NEX_CONFIG_DIR / "nex.db"

# Common locations NEX stores JSON — extend if your setup differs
JSON_SEARCH_ROOTS = [
    Path.home() / "Desktop" / "nex",
    NEX_CONFIG_DIR,
    Path.home() / "Desktop" / "nex" / "data",
    Path.home() / "Desktop" / "nex" / "nex",
]

# Candidate filenames for each data type
REFLECTION_FILES = [
    "reflections.json", "nex_reflections.json",
    "reflection_log.json", "session_reflections.json",
]
AGENT_FILES = [
    "agents.json", "nex_agents.json",
    "agent_registry.json", "agent_state.json",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def find_json_file(candidates: list[str]) -> Path | None:
    for root in JSON_SEARCH_ROOTS:
        for name in candidates:
            p = root / name
            if p.exists():
                return p
    return None


def content_hash(record: dict) -> str:
    """Stable hash of record content for deduplication."""
    blob = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def inspect_schema(db: sqlite3.Connection, table: str) -> list[str]:
    rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def ensure_sync_hash_column(db: sqlite3.Connection, table: str):
    cols = inspect_schema(db, table)
    if "sync_hash" not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN sync_hash TEXT")
        db.commit()


def already_synced(db: sqlite3.Connection, table: str, h: str) -> bool:
    row = db.execute(
        f"SELECT 1 FROM {table} WHERE sync_hash = ?", (h,)
    ).fetchone()
    return row is not None


def now_iso() -> str:
    return datetime.now().isoformat()

# ── Schema bootstrappers ──────────────────────────────────────────────────────

REFLECTIONS_DDL = """
CREATE TABLE IF NOT EXISTS reflections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT NOT NULL,
    source      TEXT DEFAULT 'json_import',
    score       REAL DEFAULT 0.0,
    created_at  TEXT DEFAULT (datetime('now')),
    sync_hash   TEXT
)
"""

AGENTS_DDL = """
CREATE TABLE IF NOT EXISTS agents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    role        TEXT,
    state       TEXT,
    metadata    TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    sync_hash   TEXT
)
"""

def bootstrap_tables(db: sqlite3.Connection):
    db.execute(REFLECTIONS_DDL)
    db.execute(AGENTS_DDL)
    db.commit()

# ── Reflection normaliser ─────────────────────────────────────────────────────

def normalise_reflection(raw) -> dict | None:
    """
    Accepts many JSON shapes NEX might produce:
      - string                        → {content: str}
      - {"content": ..., ...}
      - {"text": ..., ...}
      - {"reflection": ..., ...}
      - {"thought": ..., ...}
      - {"message": ..., ...}
    Returns None if we can't extract meaningful text.
    """
    if isinstance(raw, str):
        text = raw.strip()
    elif isinstance(raw, dict):
        text = (
            raw.get("content")
            or raw.get("text")
            or raw.get("reflection")
            or raw.get("thought")
            or raw.get("message")
            or ""
        )
        text = str(text).strip()
    else:
        return None

    if len(text) < 5:
        return None

    score = 0.0
    if isinstance(raw, dict):
        score = float(raw.get("score") or raw.get("weight") or raw.get("confidence") or 0.0)

    created_at = now_iso()
    if isinstance(raw, dict):
        created_at = str(
            raw.get("created_at") or raw.get("timestamp") or raw.get("ts") or created_at
        )

    source = "json_import"
    if isinstance(raw, dict):
        source = str(raw.get("source") or raw.get("origin") or "json_import")

    return {
        "content":    text,
        "source":     source,
        "score":      score,
        "created_at": created_at,
    }

# ── Agent normaliser ──────────────────────────────────────────────────────────

def normalise_agent(raw) -> dict | None:
    """
    Accepts:
      - {"name": ..., "role": ..., "state": ..., ...}
      - {"id": ..., "type": ..., ...}
      - plain string (used as name)
    """
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            return None
        return {
            "name":       name,
            "role":       None,
            "state":      None,
            "metadata":   None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }

    if not isinstance(raw, dict):
        return None

    name = str(
        raw.get("name") or raw.get("agent_name") or raw.get("id") or raw.get("type") or ""
    ).strip()
    if not name:
        return None

    role = raw.get("role") or raw.get("task") or raw.get("purpose") or None
    state = raw.get("state") or raw.get("status") or None

    # Anything else goes into metadata
    skip = {"name", "agent_name", "id", "type", "role", "task", "purpose",
            "state", "status", "created_at", "updated_at", "timestamp"}
    extra = {k: v for k, v in raw.items() if k not in skip}
    metadata = json.dumps(extra) if extra else None

    ts = str(raw.get("created_at") or raw.get("timestamp") or now_iso())

    return {
        "name":       name,
        "role":       str(role) if role else None,
        "state":      str(state) if state else None,
        "metadata":   metadata,
        "created_at": ts,
        "updated_at": now_iso(),
    }

# ── Loaders ───────────────────────────────────────────────────────────────────

def load_json_records(path: Path) -> list:
    """Load JSON — handles list, dict-of-lists, or newline-delimited JSON."""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []

    # Try standard JSON first
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Might be {reflections: [...]} or just a single record
            for key in ("reflections", "agents", "records", "data", "items", "entries"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [data]
        return [data]
    except json.JSONDecodeError:
        pass

    # Newline-delimited JSON (JSONL)
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records

# ── Sync functions ────────────────────────────────────────────────────────────

def sync_reflections(
    db: sqlite3.Connection,
    path: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[int, int, int]:
    """Returns (found, inserted, skipped)."""
    records = load_json_records(path)
    found = len(records)
    inserted = skipped = 0

    for raw in records:
        norm = normalise_reflection(raw)
        if norm is None:
            skipped += 1
            continue

        h = content_hash(norm)
        if already_synced(db, "reflections", h):
            skipped += 1
            continue

        if verbose:
            preview = norm["content"][:80].replace("\n", " ")
            print(f"  [reflections] + {preview!r}")

        if not dry_run:
            db.execute(
                """INSERT INTO reflections (content, source, score, created_at, sync_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                (norm["content"], norm["source"], norm["score"], norm["created_at"], h),
            )
        inserted += 1

    if not dry_run:
        db.commit()

    return found, inserted, skipped


def sync_agents(
    db: sqlite3.Connection,
    path: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[int, int, int]:
    records = load_json_records(path)
    found = len(records)
    inserted = skipped = 0

    for raw in records:
        norm = normalise_agent(raw)
        if norm is None:
            skipped += 1
            continue

        h = content_hash(norm)
        if already_synced(db, "agents", h):
            skipped += 1
            continue

        if verbose:
            print(f"  [agents] + {norm['name']!r}  role={norm['role']}")

        if not dry_run:
            db.execute(
                """INSERT INTO agents (name, role, state, metadata, created_at, updated_at, sync_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    norm["name"], norm["role"], norm["state"],
                    norm["metadata"], norm["created_at"], norm["updated_at"], h,
                ),
            )
        inserted += 1

    if not dry_run:
        db.commit()

    return found, inserted, skipped

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NEX JSON → DB sync")
    parser.add_argument("--dry-run",  action="store_true", help="Preview only, no writes")
    parser.add_argument("--verbose",  action="store_true", help="Print each record")
    args = parser.parse_args()

    label = " [DRY RUN]" if args.dry_run else ""
    print(f"\n{'='*60}")
    print(f"  NEX JSON → DB Sync{label}")
    print(f"  DB: {DB_PATH}")
    print(f"{'='*60}\n")

    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        sys.exit(1)

    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")

    # Bootstrap tables + add sync_hash col if missing
    bootstrap_tables(db)

    # ── Print pre-sync state ──────────────────────────────────────────────────
    print("── Pre-sync DB state ──────────────────────────────────────")
    for table in ("reflections", "agents"):
        try:
            n = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {n}")
        except Exception as e:
            print(f"  {table}: ERROR — {e}")
    print()

    total_inserted = 0
    total_skipped  = 0

    # ── Reflections ───────────────────────────────────────────────────────────
    print("── Reflections ─────────────────────────────────────────────")
    ref_path = find_json_file(REFLECTION_FILES)
    if ref_path:
        print(f"  Source: {ref_path}")
        found, ins, skip = sync_reflections(db, ref_path, args.dry_run, args.verbose)
        print(f"  Found: {found}  |  Inserted: {ins}  |  Skipped (dup/invalid): {skip}")
        total_inserted += ins
        total_skipped  += skip
    else:
        print(f"  No reflection JSON found in searched locations:")
        for root in JSON_SEARCH_ROOTS:
            print(f"    {root}/{{{'|'.join(REFLECTION_FILES)}}}")
        print("  → Add the correct path to REFLECTION_FILES at top of script if needed.")
    print()

    # ── Agents ────────────────────────────────────────────────────────────────
    print("── Agents ───────────────────────────────────────────────────")
    agent_path = find_json_file(AGENT_FILES)
    if agent_path:
        print(f"  Source: {agent_path}")
        found, ins, skip = sync_agents(db, agent_path, args.dry_run, args.verbose)
        print(f"  Found: {found}  |  Inserted: {ins}  |  Skipped (dup/invalid): {skip}")
        total_inserted += ins
        total_skipped  += skip
    else:
        print(f"  No agent JSON found in searched locations.")
        print("  → Add the correct path to AGENT_FILES at top of script if needed.")
    print()

    # ── Post-sync state ───────────────────────────────────────────────────────
    print("── Post-sync DB state ──────────────────────────────────────")
    for table in ("reflections", "agents"):
        try:
            n = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {n}")
        except Exception as e:
            print(f"  {table}: ERROR — {e}")

    print()
    print(f"── Summary {'[DRY RUN] ' if args.dry_run else ''}──────────────────────────────────────────")
    print(f"  Total inserted : {total_inserted}")
    print(f"  Total skipped  : {total_skipped}")
    if args.dry_run:
        print("  No writes made — rerun without --dry-run to commit.")
    print()

    db.close()


if __name__ == "__main__":
    main()
