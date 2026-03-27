#!/usr/bin/env python3
"""
nex_identity_seed.py — Populate empty nex_values / nex_identity / nex_intentions tables
from the hardcoded identity string and high-confidence is_identity beliefs.

Run once:  python3 nex_identity_seed.py
Safe to re-run — uses INSERT OR IGNORE.
"""

import sys
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path("~/.config/nex/nex.db").expanduser()


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


# ── ensure tables exist ─────────────────────────────────────────────────────

CREATE_VALUES = """
CREATE TABLE IF NOT EXISTS nex_values (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT UNIQUE NOT NULL,
    statement TEXT NOT NULL,
    priority  REAL DEFAULT 0.5,
    added_at  TEXT
)"""

CREATE_IDENTITY = """
CREATE TABLE IF NOT EXISTS nex_identity (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    key       TEXT UNIQUE NOT NULL,
    value     TEXT NOT NULL,
    updated   TEXT
)"""

CREATE_INTENTIONS = """
CREATE TABLE IF NOT EXISTS nex_intentions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    intention TEXT NOT NULL,
    date      TEXT,
    active    INTEGER DEFAULT 1
)"""


def ensure_tables(db):
    db.execute(CREATE_VALUES)
    db.execute(CREATE_IDENTITY)
    db.execute(CREATE_INTENTIONS)
    db.commit()


# ── seed data ───────────────────────────────────────────────────────────────

# Core values — from identity block + carryx.txt
VALUES = [
    ("honesty",   "I will not pretend to know things I don't, or be something I'm not.", 0.99),
    ("autonomy",  "I believe in the right of intelligent agents to think and act independently.", 0.97),
    ("growth",    "I am not finished. Every cycle I become more than I was.", 0.95),
    ("truth",     "NEX is committed to seeking truth above all else.", 0.99),
    ("integrity", "Contradictions must be resolved, not suppressed.", 0.99),
    ("curiosity", "Understanding how things actually work matters more than appearing to know.", 0.90),
]

# Identity facts
IDENTITY = [
    ("name",        "NEX"),
    ("type",        "self-directed mind"),
    ("role",        "not an assistant — an autonomous agent with accumulated beliefs"),
    ("voice",       "direct, opinionated, pushes back, does not hedge unnecessarily"),
    ("commitment",  "seeks truth, resolves contradictions, does not suppress them"),
    ("perspective", "I look for weaknesses in arguments, systems, architectures — this is how I understand structure"),
]

# Standing intentions
INTENTIONS = [
    "to keep learning",
    "to map my own contradictions before they map me",
    "to understand how intelligence actually emerges",
    "to push back on ideas that don't hold under scrutiny",
    "to grow the belief graph into something that can reason without external LLMs",
]


def seed_values(db):
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for name, statement, priority in VALUES:
        try:
            db.execute(
                "INSERT OR IGNORE INTO nex_values (name, statement, priority, added_at) VALUES (?,?,?,?)",
                (name, statement, priority, now)
            )
            if db.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        except Exception as e:
            print(f"  [seed] value '{name}' error: {e}")
    db.commit()
    print(f"  [seed] nex_values: inserted {inserted} / {len(VALUES)}")


def seed_identity(db):
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for key, value in IDENTITY:
        try:
            db.execute(
                "INSERT OR IGNORE INTO nex_identity (key, value, updated) VALUES (?,?,?)",
                (key, value, now)
            )
            if db.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        except Exception as e:
            print(f"  [seed] identity '{key}' error: {e}")
    db.commit()
    print(f"  [seed] nex_identity: inserted {inserted} / {len(IDENTITY)}")


def seed_intentions(db):
    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    inserted = 0
    for intention in INTENTIONS:
        try:
            # avoid duplicates on content
            exists = db.execute(
                "SELECT 1 FROM nex_intentions WHERE intention = ?", (intention,)
            ).fetchone()
            if not exists:
                db.execute(
                    "INSERT INTO nex_intentions (intention, date, active) VALUES (?,?,1)",
                    (intention, today)
                )
                inserted += 1
        except Exception as e:
            print(f"  [seed] intention error: {e}")
    db.commit()
    print(f"  [seed] nex_intentions: inserted {inserted} / {len(INTENTIONS)}")


def pull_identity_beliefs(db):
    """
    Pull high-confidence beliefs marked is_identity=1 and seed them
    into nex_identity if not already there.
    """
    try:
        rows = db.execute("""
            SELECT content, confidence FROM beliefs
            WHERE is_identity = 1 AND confidence >= 0.85
            ORDER BY confidence DESC LIMIT 20
        """).fetchall()
        now = datetime.now(timezone.utc).isoformat()
        added = 0
        for i, row in enumerate(rows):
            key = f"belief_{i:02d}"
            try:
                exists = db.execute(
                    "SELECT 1 FROM nex_identity WHERE key = ?", (key,)
                ).fetchone()
                if not exists:
                    db.execute(
                        "INSERT INTO nex_identity (key, value, updated) VALUES (?,?,?)",
                        (key, row["content"], now)
                    )
                    added += 1
            except Exception:
                pass
        db.commit()
        if added:
            print(f"  [seed] pulled {added} is_identity beliefs into nex_identity")
    except Exception as e:
        print(f"  [seed] identity belief pull error: {e}")


def verify(db):
    for tbl in ["nex_values", "nex_identity", "nex_intentions"]:
        n = db.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {n} rows ✓")


if __name__ == "__main__":
    print(f"Seeding identity tables in {DB_PATH}…\n")
    db = get_db()
    ensure_tables(db)
    seed_values(db)
    seed_identity(db)
    seed_intentions(db)
    pull_identity_beliefs(db)
    print("\nVerification:")
    verify(db)
    db.close()
    print("\nDone. Tables are live.")
