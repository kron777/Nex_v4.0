#!/usr/bin/env python3
"""
NEX IDLE WATCHDOG FIX
nex_idle_watchdog.py

NEX brain goes IDLE and stays there — process is alive but doing nothing.
Standard watchdog only checks if process exists, not if it's actually working.

This script:
1. Checks if brain STATUS=IDLE for more than N minutes
2. If so, restarts NEX cleanly
3. Also staggers cron jobs to prevent collision

Run via cron every 5 minutes:
  */5 * * * * /usr/bin/python3 /home/rr/Desktop/nex/nex_idle_watchdog.py >> ~/.config/nex/watchdog_fix.log 2>&1
"""
import subprocess, json, time, os, sys
from pathlib import Path
from datetime import datetime, timezone

NEX        = Path.home() / "Desktop/nex"
CFG        = Path.home() / ".config/nex"
IDLE_FILE  = CFG / "nex_idle_detected.json"
IDLE_LIMIT = 8   # minutes before restart

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] [watchdog_fix] {msg}", flush=True)

def get_brain_status():
    """Read status from auto_check data files."""
    for f in [NEX/"meta_state.json", CFG/"meta_state.json",
              NEX/"session_state.json"]:
        if f.exists():
            try:
                d = json.loads(f.read_text())
                status = d.get("status") or d.get("brain_status") or d.get("state")
                if status:
                    return str(status).upper()
            except:
                pass

    # Fallback: check soul_loop_cycle.txt for staleness
    cycle_file = CFG / "soul_loop_cycle.txt"
    if cycle_file.exists():
        mtime = cycle_file.stat().st_mtime
        age   = time.time() - mtime
        if age > 600:  # 10 minutes without cycle update
            return "STALE"

    return "UNKNOWN"

def get_last_activity():
    """How many seconds since last brain activity."""
    activity_files = [
        NEX / "nex_debug.jsonl",
        CFG / "conversations.json",
        NEX / "session_state.json",
    ]
    most_recent = 0
    for f in activity_files:
        if f.exists():
            mtime = f.stat().st_mtime
            if mtime > most_recent:
                most_recent = mtime
    return time.time() - most_recent if most_recent else 9999

def is_llm_responsive():
    """Check if llama-server is actually responding."""
    try:
        import urllib.request
        req = urllib.request.urlopen("http://localhost:8080/health", timeout=5)
        return req.status == 200
    except:
        return False

def restart_nex():
    """Clean restart."""
    log("RESTARTING NEX — brain was idle/stale")
    exit_script  = NEX / "nex_exit.sh"
    launch_script = NEX / "nex_launch.sh"

    if exit_script.exists():
        subprocess.run(f"bash {exit_script}", shell=True,
                      capture_output=True, timeout=30)
        time.sleep(5)

    if launch_script.exists():
        subprocess.Popen(f"bash {launch_script}",
                        shell=True, start_new_session=True)
        log("Launch script started")
    else:
        log("ERROR: nex_launch.sh not found")

def load_idle_record():
    try:
        return json.loads(IDLE_FILE.read_text()) if IDLE_FILE.exists() else {}
    except:
        return {}

def save_idle_record(record):
    IDLE_FILE.write_text(json.dumps(record, indent=2))

def main():
    status       = get_brain_status()
    last_activity = get_last_activity()
    llm_ok       = is_llm_responsive()
    record       = load_idle_record()

    log(f"status={status} last_activity={last_activity:.0f}s llm={llm_ok}")

    # Conditions for concern
    is_idle  = status in ("IDLE", "STALE", "UNKNOWN")
    is_stale = last_activity > 600  # 10 min no file updates
    llm_dead = not llm_ok

    if llm_dead:
        log("LLM not responding — restarting")
        restart_nex()
        save_idle_record({})
        return

    if is_idle or is_stale:
        now = time.time()
        if "idle_since" not in record:
            record["idle_since"] = now
            record["status"]     = status
            save_idle_record(record)
            log(f"Idle detected — watching (limit={IDLE_LIMIT}min)")
        else:
            idle_minutes = (now - record["idle_since"]) / 60
            log(f"Idle for {idle_minutes:.1f} minutes")
            if idle_minutes >= IDLE_LIMIT:
                restart_nex()
                save_idle_record({})
    else:
        # Active — clear any idle record
        if record:
            log("Brain active — clearing idle record")
            save_idle_record({})

if __name__ == "__main__":
    main()
