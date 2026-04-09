#!/usr/bin/env python3
"""
debug_machine.py — NEX Live Diagnostic Dashboard
Run this BEFORE starting NEX to catch everything.
"""

import subprocess
import time
import os
import sys
import signal
import datetime
import threading
import collections

# ─── CONFIG ───────────────────────────────────────────────────────────────────

PROCESSES = {
    "brain":      {"match": "run.py",           "log": "/tmp/nex_brain.log"},
    "auto_check": {"match": "auto_check.py",     "log": "/tmp/nex_auto_check.log"},
    "llama":      {"match": "llama-server",      "log": "/tmp/llama_server.log"},
    "telegram":   {"match": "nex_telegram.py",   "log": "/tmp/nex_telegram.log"},
    "watchdog":   {"match": "nex_watchdog.sh",   "log": None},
    "scheduler":  {"match": "nex_scheduler.py",  "log": "/tmp/nex_scheduler.log"},
    "api":        {"match": "nex_api.py",         "log": "/tmp/nex_api.log"},
}

PORTS = {
    "LLM  (8080)": 8080,
    "API  (7823)": 7823,
    "SCHED(7825)": 7825,
    "GUI  (8765)": 8765,
}

REFRESH = 3  # seconds

# ─── COLOURS ──────────────────────────────────────────────────────────────────

R  = "\033[0m"
B  = "\033[1m"
G  = "\033[92m"
Y  = "\033[93m"
RE = "\033[91m"
C  = "\033[96m"
DM = "\033[2m"

# ─── STATE ────────────────────────────────────────────────────────────────────

restart_counts = collections.defaultdict(int)
last_pids      = {}
crash_log      = []  # list of (time, name, reason)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def clear():
    os.system("clear")

def now():
    return datetime.datetime.now().strftime("%H:%M:%S")

def check_process(name, match):
    try:
        r = subprocess.run(
            ["pgrep", "-f", match],
            capture_output=True, text=True
        )
        pids = [p for p in r.stdout.strip().split("\n") if p]
        return pids
    except Exception:
        return []

def get_mem_cpu(pid):
    try:
        r = subprocess.run(
            ["ps", "-p", pid, "-o", "pid,%mem,%cpu", "--no-headers"],
            capture_output=True, text=True
        )
        parts = r.stdout.strip().split()
        if len(parts) >= 3:
            return parts[1], parts[2]
    except Exception:
        pass
    return "?", "?"

def check_port(port):
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "1",
             f"http://localhost:{port}/health"],
            capture_output=True, text=True
        )
        if r.returncode == 0 and r.stdout:
            return True
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "1",
             f"http://localhost:{port}/"],
            capture_output=True, text=True
        )
        return r.returncode == 0
    except Exception:
        return False

def tail_log(path, n=3):
    if not path or not os.path.exists(path):
        return ["(no log)"]
    try:
        r = subprocess.run(
            ["tail", f"-{n}", path],
            capture_output=True, text=True
        )
        lines = r.stdout.strip().split("\n")
        return [l[:100] for l in lines if l.strip()]
    except Exception:
        return ["(error reading log)"]

def get_log_errors(path, n=20):
    if not path or not os.path.exists(path):
        return []
    try:
        r = subprocess.run(
            ["grep", "-i", "error\\|exception\\|traceback\\|killed\\|crash",
             path],
            capture_output=True, text=True
        )
        lines = r.stdout.strip().split("\n")
        return [l[:120] for l in lines[-5:] if l.strip()]
    except Exception:
        return []

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

def draw():
    global last_pids, restart_counts, crash_log

    clear()
    ts = now()

    print(f"{C}{B}╔══════════════════════════════════════════════════════════════╗{R}")
    print(f"{C}{B}║  NEX DEBUG MACHINE                              {DM}{ts}{R}{C}{B}  ║{R}")
    print(f"{C}{B}╚══════════════════════════════════════════════════════════════╝{R}")
    print()

    # ── PROCESS STATUS ────────────────────────────────────────────────────────
    print(f"{B}  PROCESSES{R}  {DM}(restarts tracked){R}")
    print(f"  {'─'*60}")

    for name, cfg in PROCESSES.items():
        pids = check_process(name, cfg["match"])
        alive = len(pids) > 0

        # Detect restart
        prev = last_pids.get(name, [])
        if prev and not alive:
            restart_counts[name] += 1
            crash_log.append((ts, name, "process died"))
        elif prev and alive and set(pids) != set(prev):
            restart_counts[name] += 1
            crash_log.append((ts, name, f"restarted (new PID {pids[0]})"))
        last_pids[name] = pids

        status = f"{G}ALIVE{R}" if alive else f"{RE}DEAD {R}"
        pid_str = pids[0] if pids else "-----"
        restarts = restart_counts[name]
        restart_str = f"{Y}↺{restarts}{R}" if restarts > 0 else f"{DM}↺0{R}"

        mem, cpu = ("?", "?")
        if alive and pids:
            mem, cpu = get_mem_cpu(pids[0])

        print(f"  {B}{name:<12}{R} {status}  PID:{DM}{pid_str:<8}{R}  "
              f"MEM:{DM}{mem:>5}%{R}  CPU:{DM}{cpu:>5}%{R}  {restart_str}")

    print()

    # ── PORT STATUS ───────────────────────────────────────────────────────────
    print(f"{B}  PORTS{R}")
    print(f"  {'─'*60}")

    port_results = {}
    threads = []
    def check_p(label, port):
        port_results[label] = check_port(port)

    for label, port in PORTS.items():
        t = threading.Thread(target=check_p, args=(label, port), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=2)

    for label in PORTS:
        up = port_results.get(label, False)
        status = f"{G}UP  {R}" if up else f"{RE}DOWN{R}"
        print(f"  {label:<14} {status}")

    print()

    # ── RECENT ERRORS ─────────────────────────────────────────────────────────
    print(f"{B}  RECENT ERRORS{R}  {DM}(from logs){R}")
    print(f"  {'─'*60}")

    found_errors = False
    for name, cfg in PROCESSES.items():
        errors = get_log_errors(cfg["log"])
        if errors:
            found_errors = True
            print(f"  {Y}{name}:{R}")
            for e in errors[-2:]:
                print(f"    {DM}{e[:100]}{R}")

    if not found_errors:
        print(f"  {G}No errors found in logs{R}")

    print()

    # ── CRASH LOG ─────────────────────────────────────────────────────────────
    if crash_log:
        print(f"{B}  CRASH LOG{R}  {DM}(this session){R}")
        print(f"  {'─'*60}")
        for entry in crash_log[-5:]:
            print(f"  {RE}[{entry[0]}] {entry[1]}: {entry[2]}{R}")
        print()

    # ── BRAIN LOG TAIL ────────────────────────────────────────────────────────
    print(f"{B}  BRAIN LOG{R}  {DM}(last 4 lines){R}")
    print(f"  {'─'*60}")
    for line in tail_log("/tmp/nex_brain.log", 4):
        print(f"  {DM}{line}{R}")

    print()
    print(f"  {DM}Refreshing every {REFRESH}s — Ctrl+C to stop{R}")

def main():
    print(f"{C}Starting NEX Debug Machine...{R}")
    time.sleep(0.5)

    try:
        while True:
            draw()
            time.sleep(REFRESH)
    except KeyboardInterrupt:
        print(f"\n{C}Debug machine stopped.{R}")
        if crash_log:
            print(f"\n{Y}Session crash summary:{R}")
            for entry in crash_log:
                print(f"  [{entry[0]}] {entry[1]}: {entry[2]}")

if __name__ == "__main__":
    main()
