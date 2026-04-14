#!/usr/bin/env python3
"""NEX HUD deep audit — outputs to ~/Desktop/data.txt"""
import os, sys, sqlite3, json, subprocess, socket, time
from pathlib import Path

out = []
def log(s=""): out.append(s); print(s)

log("="*60)
log("NEX HUD AUDIT")
log(time.strftime("%Y-%m-%d %H:%M:%S"))
log("="*60)

# ── 1. Path audit ─────────────────────────────────────────────
log("\n[1] PATH AUDIT")
paths = {
    "CFG dir (~/.config/nex)":     Path.home()/".config/nex",
    "DB (~/.config/nex/nex.db)":   Path.home()/".config/nex/nex.db",
    "DB (~/Desktop/nex/nex.db)":   Path.home()/"Desktop/nex/nex.db",
    "Log (~/.config/nex/nex_loop.log)": Path.home()/".config/nex/nex_loop.log",
    "State (~/.config/nex/session_state.json)": Path.home()/".config/nex/session_state.json",
    "Loop state (~/.config/nex/loop_state.json)": Path.home()/".config/nex/loop_state.json",
    "nex_hud_server.py": Path.home()/"Desktop/nex/nex_hud_server.py",
    "nex_hud.html":      Path.home()/"Desktop/nex/nex_hud.html",
    "run.py":            Path.home()/"Desktop/nex/run.py",
}
for label, p in paths.items():
    exists = p.exists()
    size   = p.stat().st_size if exists and p.is_file() else "-"
    log(f"  {'OK' if exists else 'MISSING':<8} {label}  (size={size})")

# ── 2. DB audit ───────────────────────────────────────────────
log("\n[2] DATABASE AUDIT")
for db_path in [Path.home()/".config/nex/nex.db", Path.home()/"Desktop/nex/nex.db"]:
    log(f"\n  DB: {db_path}")
    if not db_path.exists():
        log("    MISSING")
        continue
    try:
        con = sqlite3.connect(str(db_path), timeout=3)
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        log(f"    Tables: {tables}")
        for tbl in ["beliefs","opinions","episodic_events","curiosity_gaps","contradiction_pairs","reflections"]:
            if tbl in tables:
                try:
                    n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                    log(f"    {tbl}: {n} rows")
                except Exception as e:
                    log(f"    {tbl}: ERROR {e}")
            else:
                log(f"    {tbl}: NOT FOUND")
        con.close()
    except Exception as e:
        log(f"    CONNECT ERROR: {e}")

# ── 3. Process audit ──────────────────────────────────────────
log("\n[3] PROCESS AUDIT")
procs = ["run.py","nex_hud_server","llama-server","nex_scheduler","nex_telegram","nex_api"]
try:
    ps = subprocess.check_output(["ps","aux"], text=True)
    for proc in procs:
        hits = [l for l in ps.splitlines() if proc in l and "grep" not in l]
        log(f"  {proc}: {'RUNNING ('+str(len(hits))+')' if hits else 'NOT FOUND'}")
        for h in hits[:2]:
            parts = h.split()
            log(f"    PID={parts[1]} CPU={parts[2]} MEM={parts[3]}")
except Exception as e:
    log(f"  ps error: {e}")

# ── 4. Port audit ─────────────────────────────────────────────
log("\n[4] PORT AUDIT")
for port in [7700, 8080, 11434]:
    try:
        s = socket.create_connection(("localhost", port), timeout=1)
        s.close()
        log(f"  :{port} OPEN")
    except:
        log(f"  :{port} CLOSED/UNREACHABLE")

# ── 5. HUD server DB path mismatch ───────────────────────────
log("\n[5] HUD SERVER CONFIG MISMATCH")
hud_server = Path.home()/"Desktop/nex/nex_hud_server.py"
if hud_server.exists():
    src = hud_server.read_text()
    cfg_db  = '".config" / "nex"' in src or '.config/nex' in src
    desk_db = 'Desktop/nex/nex.db' in src
    log(f"  References ~/.config/nex/nex.db: {cfg_db}")
    log(f"  References ~/Desktop/nex/nex.db: {desk_db}")
    actual_db = Path.home()/"Desktop/nex/nex.db"
    config_db = Path.home()/".config/nex/nex.db"
    if actual_db.exists() and not config_db.exists() and cfg_db:
        log("  *** MISMATCH: HUD reads ~/.config/nex/nex.db but DB is at ~/Desktop/nex/nex.db ***")
        log("  FIX: symlink or update CFG path in nex_hud_server.py")

# ── 6. Log file check ─────────────────────────────────────────
log("\n[6] LOG FILES")
log_paths = [
    Path.home()/".config/nex/nex_loop.log",
    Path.home()/"Desktop/nex/logs",
]
for lp in log_paths:
    if lp.exists():
        if lp.is_dir():
            files = list(lp.iterdir())
            log(f"  {lp}: DIR with {len(files)} files")
            for f in sorted(files)[-3:]:
                log(f"    {f.name} ({f.stat().st_size}b)")
        else:
            log(f"  {lp}: {lp.stat().st_size}b")
            try:
                tail = lp.read_text(errors="replace").splitlines()[-5:]
                for l in tail: log(f"    > {l}")
            except: pass
    else:
        log(f"  {lp}: MISSING")

# ── 7. /data endpoint test ────────────────────────────────────
log("\n[7] HUD /data ENDPOINT TEST")
try:
    import urllib.request
    r = urllib.request.urlopen("http://localhost:7700/data", timeout=3)
    data = json.loads(r.read())
    log(f"  Response OK")
    log(f"  beliefs.total: {data.get('beliefs',{}).get('total','?')}")
    log(f"  cycle: {data.get('cycle','?')}")
    log(f"  llm_online: {data.get('llm_online','?')}")
    log(f"  log lines: {len(data.get('log',[]))}")
    log(f"  recent_beliefs: {len(data.get('recent_beliefs',[]))}")
except Exception as e:
    log(f"  FAILED: {e}")

# ── 8. /agi endpoint test ─────────────────────────────────────
log("\n[8] AGI ENDPOINT TEST")
try:
    import urllib.request
    r = urllib.request.urlopen("http://localhost:7700/agi", timeout=3)
    data = json.loads(r.read())
    log(f"  /agi OK — hits: {len(data.get('hits',[]))}")
except Exception as e:
    log(f"  /agi FAILED: {e}")

# ── 9. Quick fix suggestions ──────────────────────────────────
log("\n[9] SUGGESTED FIXES")
actual_db = Path.home()/"Desktop/nex/nex.db"
config_dir = Path.home()/".config/nex"
config_db  = config_dir/"nex.db"
if actual_db.exists() and not config_db.exists():
    log(f"  FIX 1: symlink DB into config dir:")
    log(f"    mkdir -p ~/.config/nex")
    log(f"    ln -s ~/Desktop/nex/nex.db ~/.config/nex/nex.db")
if not (config_dir/"nex_loop.log").exists():
    log(f"  FIX 2: create log symlink:")
    log(f"    ln -s ~/Desktop/nex/logs/nex_loop.log ~/.config/nex/nex_loop.log  (if log exists)")

log("\n" + "="*60)
log("END AUDIT")

# Write to desktop
out_path = Path.home()/"Desktop/data.txt"
out_path.write_text("\n".join(out))
print(f"\nWritten to {out_path}")
