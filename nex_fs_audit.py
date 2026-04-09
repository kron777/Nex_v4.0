#!/usr/bin/env python3
"""
NEX FILESYSTEM AUDIT
nex_fs_audit.py

Scans NEX directories for:
- File count and total size
- Duplicate/redundant files
- Log files that can be rotated
- Stale/orphaned files
- JSON corruption
- Large files that could be compacted
- Backup files that can be cleaned

READ ONLY — reports only, no changes unless --clean flag passed
"""
import os, json, hashlib, sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

NEX        = Path.home() / "Desktop/nex"
CFG        = Path.home() / ".config/nex"
DRY_RUN    = "--clean" not in sys.argv

def size_str(n):
    for unit in ["B","KB","MB","GB"]:
        if n < 1024: return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"

def section(title):
    print(f"\n{'═'*65}")
    print(f"  {title}")
    print('═'*65)

report = {
    "total_files": 0,
    "total_size":  0,
    "issues":      [],
    "cleanable":   [],
    "cleanable_bytes": 0,
}

# ── DIRECTORY OVERVIEW ────────────────────────────────────────
section("DIRECTORY OVERVIEW")
for base in [NEX, CFG]:
    if not base.exists():
        continue
    files = list(base.rglob("*"))
    files = [f for f in files if f.is_file() and "venv" not in str(f) and "llama.cpp" not in str(f)]
    total_size = sum(f.stat().st_size for f in files if f.exists())
    report["total_files"] += len(files)
    report["total_size"]  += total_size
    print(f"  {base}: {len(files)} files, {size_str(total_size)}")

    # Top 10 largest
    files_by_size = sorted(files, key=lambda f: f.stat().st_size, reverse=True)
    print(f"  Largest files:")
    for f in files_by_size[:8]:
        print(f"    {size_str(f.stat().st_size):8s}  {f.name}")

# ── LOG FILE AUDIT ────────────────────────────────────────────
section("LOG FILES (candidates for rotation)")
log_files = []
for base in [NEX, CFG]:
    log_files.extend(base.glob("*.log"))
    log_files.extend(base.glob("logs/*.log"))
    log_files.extend(base.glob("*.jsonl"))
    log_files.extend(base.glob("*.log.*"))

log_files = [f for f in log_files if f.exists()]
log_files.sort(key=lambda f: f.stat().st_size, reverse=True)
total_log = sum(f.stat().st_size for f in log_files)
print(f"  Total log size: {size_str(total_log)}")
for f in log_files[:15]:
    size = f.stat().st_size
    age  = (datetime.now().timestamp() - f.stat().st_mtime) / 3600
    flag = " ← LARGE" if size > 5*1024*1024 else ""
    print(f"  {size_str(size):8s}  {age:5.0f}h old  {f.name}{flag}")
    if size > 1*1024*1024:
        report["cleanable"].append(str(f))
        report["cleanable_bytes"] += size * 0.9  # 90% reducible by rotation

# ── BACKUP FILES ──────────────────────────────────────────────
section("BACKUP / DUPLICATE FILES")
backup_patterns = ["*.bak", "*.bak_*", "*.pre_*", "*.backup", "*_backup*",
                   "*.corrupted", "*.old", "*.orig", "*_20[0-9][0-9]*"]
backup_files = []
for base in [NEX, CFG]:
    for pat in backup_patterns:
        backup_files.extend(base.glob(pat))
        backup_files.extend(base.glob(f"**/{pat}"))

backup_files = list(set(backup_files))
backup_files = [f for f in backup_files if f.is_file() and "venv" not in str(f)]
backup_files.sort(key=lambda f: f.stat().st_size, reverse=True)
total_backup = sum(f.stat().st_size for f in backup_files)
print(f"  Total backup size: {size_str(total_backup)}")
for f in backup_files[:15]:
    print(f"  {size_str(f.stat().st_size):8s}  {f.name}")
    report["cleanable"].append(str(f))
    report["cleanable_bytes"] += f.stat().st_size

# ── JSON HEALTH CHECK ─────────────────────────────────────────
section("JSON FILE HEALTH")
json_files = []
for base in [NEX, CFG]:
    json_files.extend(base.glob("*.json"))
json_files = [f for f in json_files if f.is_file()
              and "venv" not in str(f) and f.stat().st_size > 0]

corrupt  = []
bloated  = []
for f in json_files:
    try:
        d = json.loads(f.read_text(errors='ignore'))
        size = f.stat().st_size
        if size > 5 * 1024 * 1024:
            bloated.append((f, size))
    except Exception as e:
        corrupt.append((f, str(e)))

if corrupt:
    print(f"  CORRUPT JSON FILES ({len(corrupt)}):")
    for f, err in corrupt:
        print(f"    ✗ {f.name}: {err[:60]}")
        report["issues"].append(f"CORRUPT: {f.name}")
else:
    print(f"  ✓ All JSON files parse OK ({len(json_files)} checked)")

if bloated:
    print(f"\n  LARGE JSON FILES (>5MB):")
    for f, size in sorted(bloated, key=lambda x: x[1], reverse=True):
        # Count entries
        try:
            d = json.loads(f.read_text(errors='ignore'))
            entries = len(d) if isinstance(d, (list, dict)) else "?"
        except:
            entries = "?"
        print(f"  {size_str(size):8s}  {entries} entries  {f.name}")

# ── PRESSURE TEST RUNS ────────────────────────────────────────
section("PRESSURE TEST RUN FILES")
pt_dir = CFG / "pressure_tests"
if pt_dir.exists():
    runs = list(pt_dir.glob("run_*.json"))
    total = sum(f.stat().st_size for f in runs)
    print(f"  {len(runs)} run files, {size_str(total)} total")
    if len(runs) > 20:
        old_runs = sorted(runs, key=lambda f: f.stat().st_mtime)[:-20]
        old_size = sum(f.stat().st_size for f in old_runs)
        print(f"  {len(old_runs)} runs older than latest 20 — {size_str(old_size)} cleanable")
        for f in old_runs:
            report["cleanable"].append(str(f))
            report["cleanable_bytes"] += f.stat().st_size

# ── STALE FILES ───────────────────────────────────────────────
section("STALE FILES (>30 days old, not core)")
now = datetime.now().timestamp()
stale = []
core_files = {"beliefs.json", "nex_drives.json", "nex.db", "nex_momentum.db",
              "conversations.json", "insights.json", "reflection_scores.json"}
for base in [NEX, CFG]:
    for f in base.glob("*"):
        if not f.is_file(): continue
        if f.name in core_files: continue
        if "venv" in str(f) or "llama" in str(f): continue
        age_days = (now - f.stat().st_mtime) / 86400
        if age_days > 30 and f.stat().st_size < 100*1024:  # old small files
            stale.append((f, age_days))

stale.sort(key=lambda x: x[1], reverse=True)
if stale:
    print(f"  {len(stale)} stale files found:")
    for f, age in stale[:15]:
        print(f"  {age:5.0f} days  {size_str(f.stat().st_size):6s}  {f.name}")
else:
    print("  No stale files found")

# ── DB COMPACTION CHECK ───────────────────────────────────────
section("DATABASE COMPACTION")
import sqlite3
for dbf in [NEX/"nex.db", NEX/"nex_momentum.db"]:
    if not dbf.exists(): continue
    try:
        conn = sqlite3.connect(str(dbf), timeout=3)
        cur  = conn.cursor()
        # Check fragmentation
        cur.execute("PRAGMA page_count")
        pages = cur.fetchone()[0]
        cur.execute("PRAGMA freelist_count")
        free  = cur.fetchone()[0]
        cur.execute("PRAGMA page_size")
        psize = cur.fetchone()[0]
        frag  = (free/pages*100) if pages > 0 else 0
        wasted = free * psize
        print(f"  {dbf.name}: {size_str(dbf.stat().st_size)} on disk, "
              f"{frag:.1f}% fragmented, {size_str(wasted)} reclaimable")
        if frag > 10:
            report["issues"].append(f"DB fragmented: {dbf.name} ({frag:.0f}%)")
            report["cleanable_bytes"] += wasted
        conn.close()
    except Exception as e:
        print(f"  {dbf.name}: could not analyse ({e})")

# ── SYNTHESIS LOG SIZE ────────────────────────────────────────
section("SYNTHESIS LOG")
sf = CFG / "gap_synthesis.json"
if sf.exists():
    try:
        entries = json.loads(sf.read_text())
        size    = sf.stat().st_size
        print(f"  {len(entries)} entries, {size_str(size)}")
        dupes = sum(1 for e in entries if 'duplicate_response' in str(e.get('score_notes','')))
        recombined = sum(1 for e in entries if e.get('synthesis_type') == 'recombined')
        novel = sum(1 for e in entries if e.get('synthesis_type') in ('novel','analogy') and e.get('flagged'))
        print(f"  Novel/flagged: {novel}  Recombined: {recombined}  Duplicate-blocked: {dupes}")
        if recombined > novel * 3:
            print(f"  Consider pruning recombined entries to reduce file size")
            reclaimable = recombined * (size // len(entries)) if entries else 0
            report["cleanable_bytes"] += reclaimable
    except Exception as e:
        print(f"  Could not parse: {e}")

# ── SUMMARY ───────────────────────────────────────────────────
section("SUMMARY & RECOMMENDATIONS")
print(f"  Total files scanned:     {report['total_files']}")
print(f"  Total size:              {size_str(report['total_size'])}")
print(f"  Cleanable (estimate):    {size_str(int(report['cleanable_bytes']))}")
print(f"  Issues found:            {len(report['issues'])}")

if report["issues"]:
    print(f"\n  ISSUES:")
    for issue in report["issues"]:
        print(f"    • {issue}")

print(f"""
  RECOMMENDED ACTIONS:
  1. Rotate large log files (keep last 1000 lines each)
  2. Delete backup .bak/.pre_* files older than 7 days
  3. VACUUM nex.db and nex_momentum.db to reclaim space
  4. Keep only latest 20 pressure test run files
  5. Prune recombined entries from gap_synthesis.json
  6. Archive conversations.jsonl if > 50MB

  Run with --clean flag to apply all safe fixes automatically.
""")

if "--clean" in sys.argv:
    print("\n  APPLYING CLEAN...")
    # Safe operations only
    import shutil

    # 1. Rotate logs — keep last 2000 lines
    rotated = 0
    for logf in log_files:
        if logf.stat().st_size > 2*1024*1024:
            lines = logf.read_text(errors='ignore').split('\n')
            if len(lines) > 2000:
                logf.write_text('\n'.join(lines[-2000:]))
                rotated += 1
    print(f"  ✓ Rotated {rotated} log files")

    # 2. Delete old pressure test runs (keep latest 20)
    if pt_dir.exists():
        runs = sorted(pt_dir.glob("run_*.json"), key=lambda f: f.stat().st_mtime)
        old  = runs[:-20] if len(runs) > 20 else []
        for f in old: f.unlink()
        print(f"  ✓ Deleted {len(old)} old pressure test runs")

    # 3. VACUUM databases
    for dbf in [NEX/"nex.db", NEX/"nex_momentum.db"]:
        if dbf.exists():
            try:
                conn = sqlite3.connect(str(dbf), timeout=10)
                conn.execute("VACUUM")
                conn.close()
                print(f"  ✓ VACUUMed {dbf.name}")
            except Exception as e:
                print(f"  ✗ VACUUM {dbf.name} failed: {e}")

    # 4. Prune gap_synthesis — remove recombined non-flagged entries older than 50
    if sf.exists():
        try:
            entries = json.loads(sf.read_text())
            before  = len(entries)
            # Keep all flagged + novel + last 30 recombined
            flagged_entries = [e for e in entries if e.get('flagged') or
                               e.get('synthesis_type') in ('novel','analogy')]
            recomb = [e for e in entries if not e.get('flagged') and
                      e.get('synthesis_type') not in ('novel','analogy')]
            kept   = flagged_entries + recomb[-30:]
            sf.write_text(json.dumps(kept, indent=2))
            print(f"  ✓ Pruned synthesis log: {before} → {len(kept)} entries")
        except Exception as e:
            print(f"  ✗ Synthesis prune failed: {e}")

    # 5. Delete safe backup files (older than 7 days)
    import time
    cutoff = time.time() - 7*86400
    deleted_bak = 0
    for f in backup_files:
        if f.exists() and f.stat().st_mtime < cutoff:
            # Extra safety check — don't delete .db backups
            if not f.suffix == '.db' and 'beliefs' not in f.name:
                f.unlink()
                deleted_bak += 1
    print(f"  ✓ Deleted {deleted_bak} old backup files")

    print("\n  CLEAN COMPLETE")
