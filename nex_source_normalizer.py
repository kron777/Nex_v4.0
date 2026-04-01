#!/usr/bin/env python3
"""
nex_source_normalizer.py — Source URL normalization
Merges fractured source variants so reinforce_count accumulates properly
and the quality scorer gives full source authority credit.

Normalization rules (in order):
  1. Strip https://www. / http://www. / https:// / http://
  2. Strip trailing /top/.rss?t=day and similar RSS suffixes
  3. Strip trailing slashes
  4. Lowercase

Run: python3 nex_source_normalizer.py [--dry]
"""
import sqlite3, re, sys
from pathlib import Path
from collections import defaultdict

DB_PATH = Path("~/.config/nex/nex.db").expanduser()
DRY = "--dry" in sys.argv

def normalize(source: str) -> str:
    if not source:
        return source
    s = source.strip()
    # Strip protocol + www
    s = re.sub(r'^https?://(www\.)?', '', s)
    # Strip RSS/feed suffixes
    s = re.sub(r'/top/\.rss.*$', '', s)
    s = re.sub(r'\.rss.*$', '', s)
    s = re.sub(r'/feed/?.*$', '', s)
    # Strip trailing slash
    s = s.rstrip('/')
    return s.lower()

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT DISTINCT source FROM beliefs WHERE source IS NOT NULL").fetchall()
sources = [r["source"] for r in rows]

# Group original sources by their normalized form
groups = defaultdict(list)
for s in sources:
    groups[normalize(s)].append(s)

# Only act on groups with multiple variants
to_fix = {norm: variants for norm, variants in groups.items() if len(variants) > 1}

print(f"Found {len(to_fix)} source groups with variants:")
total_updated = 0

for norm, variants in sorted(to_fix.items(), key=lambda x: -len(x[1])):
    # Pick the canonical: prefer the shortest clean form
    canonical = min(variants, key=lambda v: (len(v), v))
    others = [v for v in variants if v != canonical]
    counts = {v: conn.execute("SELECT COUNT(*) FROM beliefs WHERE source=?", (v,)).fetchone()[0]
              for v in variants}
    total = sum(counts.values())
    print(f"\n  [{norm}] {total} beliefs across {len(variants)} variants:")
    for v in variants:
        marker = " ← keep" if v == canonical else ""
        print(f"    {counts[v]:4d}  {v}{marker}")

    if not DRY:
        for other in others:
            conn.execute(
                "UPDATE beliefs SET source=? WHERE source=?",
                (canonical, other)
            )
        total_updated += sum(counts[o] for o in others)

if not DRY:
    conn.commit()
    print(f"\nNormalized {total_updated} belief sources across {len(to_fix)} groups.")
else:
    print(f"\nDRY RUN — {sum(sum(conn.execute('SELECT COUNT(*) FROM beliefs WHERE source=?',(v,)).fetchone()[0] for v in variants if v != min(variants, key=lambda x:(len(x),x))) for variants in to_fix.values())} beliefs would be updated.")

conn.close()
