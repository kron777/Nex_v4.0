#!/usr/bin/env python3
"""NEX DEEP AUDIT — finds why brain keeps going idle"""
import os, sys, json, subprocess, sqlite3, time
from pathlib import Path

NEX = Path.home() / "Desktop/nex"
CFG = Path.home() / ".config/nex"

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip()

def section(title):
    print(f"\n{'═'*60}")
    print(f"  {title}")
    print('═'*60)

# ── PROCESS STATUS ────────────────────────────────────────────
section("PROCESS STATUS")
out, _ = run("ps aux | grep -E 'nex_brain|llama-server|nex_api|nex_watch|nex_sched|nex_ingest' | grep -v grep")
print(out if out else "  NO NEX PROCESSES FOUND")

# ── UPTIME OF KEY PROCESSES ───────────────────────────────────
section("PROCESS AGE (how long running)")
out, _ = run("ps -eo pid,etime,cmd | grep -E 'nex_brain|llama-server' | grep -v grep")
print(out if out else "  none")

# ── LOOP STATE ────────────────────────────────────────────────
section("LOOP STATE")
for f in [CFG/"loop_state.json", NEX/"loop_state.json"]:
    if f.exists():
        print(f"  {f}:")
        print(f"  {f.read_text()[:300]}")

# ── SOUL LOOP CYCLE FILE ──────────────────────────────────────
section("SOUL LOOP CYCLE COUNTER")
for f in [CFG/"soul_loop_cycle.txt", NEX/"soul_loop_cycle.txt"]:
    if f.exists():
        print(f"  {f}: {f.read_text().strip()}")

# ── RECENT BRAIN LOG ──────────────────────────────────────────
section("BRAIN DEBUG LOG (last 30 lines)")
for logf in [NEX/"nex_debug.jsonl", CFG/"nex_debug.jsonl"]:
    if logf.exists():
        lines = logf.read_text().split("\n")[-30:]
        for line in lines:
            if line.strip():
                try:
                    d = json.loads(line)
                    print(f"  {json.dumps(d)[:120]}")
                except:
                    print(f"  {line[:120]}")
        break

# ── SCHEDULER LOG ─────────────────────────────────────────────
section("SCHEDULER STATE")
for f in [NEX/"scheduler.json", CFG/"scheduler.json"]:
    if f.exists():
        try:
            d = json.loads(f.read_text())
            print(f"  {f.name}:")
            for k, v in list(d.items())[:10]:
                print(f"    {k}: {str(v)[:80]}")
        except:
            print(f"  {f}: {f.read_text()[:200]}")

# ── DB LOCK CHECK ─────────────────────────────────────────────
section("DATABASE LOCK STATUS")
for dbf in [NEX/"nex.db", CFG/"nex_memory.db"]:
    if dbf.exists():
        try:
            conn = sqlite3.connect(str(dbf), timeout=2)
            conn.execute("SELECT COUNT(*) FROM sqlite_master")
            conn.close()
            print(f"  ✓ {dbf.name} — accessible")
        except Exception as e:
            print(f"  ✗ {dbf.name} — LOCKED: {e}")
        # Check for WAL/journal files
        for ext in ["-wal", "-journal", "-shm"]:
            lf = Path(str(dbf) + ext)
            if lf.exists():
                size = lf.stat().st_size
                print(f"    ⚠ {lf.name} exists ({size} bytes) — lock artifact")

# ── MEMORY ────────────────────────────────────────────────────
section("MEMORY USAGE")
out, _ = run("free -h")
print(out)
out, _ = run("ps aux --sort=-%mem | head -8")
print(out)

# ── VRAM ──────────────────────────────────────────────────────
section("GPU / VRAM")
out, _ = run("nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu --format=csv,noheader 2>/dev/null || rocm-smi --showmemuse 2>/dev/null || echo 'no gpu tool'")
print(out)

# ── FILE LOCK CHECK ───────────────────────────────────────────
section("FILE LOCKS ON KEY FILES")
key_files = [
    CFG/"beliefs.json",
    CFG/"nex_drives.json",
    NEX/"nex.db",
    NEX/"nex_momentum.db",
]
for f in key_files:
    if f.exists():
        out, _ = run(f"fuser {f} 2>/dev/null")
        if out:
            print(f"  ⚠ {f.name} locked by PIDs: {out}")
        else:
            print(f"  ✓ {f.name} — no locks")

# ── RECENT CRASHES ────────────────────────────────────────────
section("RECENT CRASH SIGNALS")
out, _ = run("journalctl -p err -n 20 --no-pager --since '2 hours ago' 2>/dev/null | grep -i 'nex\\|python\\|llama\\|killed\\|oom'")
print(out if out else "  no recent errors in journal")

# ── CRON COLLISION CHECK ──────────────────────────────────────
section("CRON SCHEDULE (potential collisions)")
out, _ = run("crontab -l | grep nex | grep -v '^#'")
print(out)
print()
print("  Collision risk: multiple jobs writing beliefs.json simultaneously")
print("  Check if nex_agi_run.sh + nex_belief_linker + nex_epistemic_momentum")
print("  all fire at :00 of the same hour")

# ── WARMTH CRON ERRORS ───────────────────────────────────────
section("WARMTH CRON RECENT ERRORS")
wlog = NEX / "logs/warmth_cron.log"
if wlog.exists():
    lines = wlog.read_text().split("\n")
    errors = [l for l in lines[-200:] if any(x in l.lower() for x in
              ["error","fail","exception","traceback","killed","timeout"])]
    for e in errors[-20:]:
        print(f"  {e[:120]}")
    if not errors:
        print("  no errors in last 200 lines")

# ── SESSION STATE ─────────────────────────────────────────────
section("SESSION / BRAIN STATE")
for f in [NEX/"session_state.json", CFG/"session_state.json"]:
    if f.exists():
        try:
            d = json.loads(f.read_text())
            print(f"  {f.name} keys: {list(d.keys())[:10]}")
            for k in ["status","phase","mode","last_cycle","error","idle_reason"]:
                if k in d:
                    print(f"    {k}: {str(d[k])[:80]}")
        except:
            pass

# ── NGNIX / API CHECK ─────────────────────────────────────────
section("LLM API HEALTH")
out, _ = run("curl -s http://localhost:8080/health 2>/dev/null || echo 'no response'")
print(f"  localhost:8080/health: {out[:100]}")

out, _ = run("curl -s http://localhost:8765 2>/dev/null | head -5 || echo 'ws not responding'")
print(f"  localhost:8765 (ws): {out[:100]}")

# ── SUMMARY ───────────────────────────────────────────────────
section("LIKELY CAUSES (ranked)")
print("""
  1. DB LOCK  — beliefs.json written by cron while brain reads it
     Fix: stagger cron jobs, add file locking

  2. IDLE TRAP — brain enters idle state after soul_loop error,
     watchdog doesn't catch it because process is still alive
     Fix: restart brain if STATUS=IDLE for >10 min

  3. CRON COLLISION — multiple cron jobs running simultaneously
     competing for llama-server at :00/:30 marks
     Fix: stagger all cron jobs by 5-10 minutes

  4. MEMORY PRESSURE — 6GB used, swap active, llama-server
     loading full model on each nex_agi_run.sh call
     Fix: nex_agi_run.sh uses existing server, shouldn't reload

  5. TELEGRAM CRASH — bridge crashes silently, brain waits
     Fix: brain should not block on telegram
""")

print("\n[AUDIT COMPLETE]")
