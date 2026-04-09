#!/usr/bin/env python3
"""
nex_debug.py — NEX Activity Stream
Raw continuous stream of everything happening.
Run this first, then start NEX in another terminal.
"""

import subprocess
import time
import os
import sys
import threading
import datetime
import collections

# ─── CONFIG ───────────────────────────────────────────────────────────────────

PROCESSES = {
    "BRAIN   ": "run.py",
    "AUTOCHECK": "auto_check.py",
    "LLAMA   ": "llama-server",
    "TELEGRAM": "nex_telegram_clean.py",
    "WATCHDOG": "nex_telegram_clean.py",
    "SCHEDULER": "nex_scheduler.py",
    "API     ": "nex_api.py",
}

LOGS = {
    "BRAIN   ": "/tmp/nex_brain.log",
    "AUTOCHECK": "/tmp/nex_auto_check.log",
    "LLAMA   ": "/tmp/llama_server.log",
    "TELEGRAM": "/tmp/nex_telegram.log",
    "SCHEDULER": "/tmp/nex_scheduler.log",
    "API     ": "/tmp/nex_api.log",
}

PORTS = {
    8080: "LLM",
    7823: "API",
    7825: "SCHED",
    8765: "GUI",
}

CHECK_INTERVAL  = 2    # process/port check every N seconds
LOG_TAIL_LINES  = 2    # lines to show from each log on change
STREAM_INTERVAL = 0.5  # stream tick

# ─── COLOURS ──────────────────────────────────────────────────────────────────

R   = "\033[0m"
B   = "\033[1m"
G   = "\033[92m"
Y   = "\033[93m"
RE  = "\033[91m"
C   = "\033[96m"
M   = "\033[95m"
DM  = "\033[2m"
ORG = "\033[33m"

SOURCE_COLORS = {
    "BRAIN   ": C,
    "AUTOCHECK": M,
    "LLAMA   ": Y,
    "TELEGRAM": ORG,
    "WATCHDOG": DM,
    "SCHEDULER": G,
    "API     ": C,
    "PORT    ": Y,
    "CRASH   ": RE,
    "SYS     ": DM,
}

# ─── STATE ────────────────────────────────────────────────────────────────────

last_pids      = {}
restart_counts = collections.defaultdict(int)
last_log_pos   = {}
last_port_state = {}

# ─── OUTPUT ───────────────────────────────────────────────────────────────────

def emit(source, msg, colour=None):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    col = colour or SOURCE_COLORS.get(source, R)
    src = source[:8].ljust(8)
    print(f"{DM}[{ts}]{R} {col}[{src}]{R} {msg}", flush=True)

# ─── PROCESS CHECKER ──────────────────────────────────────────────────────────

def check_processes():
    for name, match in PROCESSES.items():
        try:
            r = subprocess.run(["pgrep", "-f", match], capture_output=True, text=True)
            pids = [p.strip() for p in r.stdout.strip().split("\n") if p.strip()]
        except Exception:
            pids = []

        prev = last_pids.get(name)

        if prev is None:
            # First check
            if pids:
                emit(name, f"{G}✓ alive{R}  PID:{pids[0]}")
            else:
                emit(name, f"{RE}✗ not running{R}")

        elif prev and not pids:
            # Was alive, now dead
            restart_counts[name] += 1
            emit("CRASH   ", f"{RE}{name.strip()} DIED{R}  (seen {restart_counts[name]}x)", RE)
            # Grab last log lines
            log = LOGS.get(name)
            if log and os.path.exists(log):
                try:
                    r2 = subprocess.run(["tail", "-3", log], capture_output=True, text=True)
                    for line in r2.stdout.strip().split("\n"):
                        if line.strip():
                            emit("CRASH   ", f"  last log: {DM}{line[:120]}{R}", RE)
                except Exception:
                    pass

        elif not prev and pids:
            # Was dead, now alive
            emit(name, f"{G}↑ came alive{R}  PID:{pids[0]}")

        elif prev and pids and set(pids) != set(prev):
            # PID changed = restart
            restart_counts[name] += 1
            emit(name, f"{Y}↺ restarted{R}  new PID:{pids[0]}  (x{restart_counts[name]})")

        last_pids[name] = pids

# ─── PORT CHECKER ─────────────────────────────────────────────────────────────

def check_port(port):
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "1", f"http://localhost:{port}/health"],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            return True
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "1", f"http://localhost:{port}/"],
            capture_output=True, text=True
        )
        return r.returncode == 0
    except Exception:
        return False

def check_ports():
    for port, label in PORTS.items():
        up = check_port(port)
        prev = last_port_state.get(port)
        if prev is None:
            status = f"{G}UP{R}" if up else f"{RE}DOWN{R}"
            emit("PORT    ", f"{label} :{port} {status}")
        elif prev and not up:
            emit("PORT    ", f"{RE}{label} :{port} WENT DOWN{R}", RE)
        elif not prev and up:
            emit("PORT    ", f"{G}{label} :{port} came UP{R}", G)
        last_port_state[port] = up

# ─── LOG STREAMER ─────────────────────────────────────────────────────────────

def stream_logs():
    for name, path in LOGS.items():
        if not path or not os.path.exists(path):
            continue
        try:
            size = os.path.getsize(path)
            prev_size = last_log_pos.get(path, size)

            if size < prev_size:
                # File was truncated/rotated
                emit(name, f"{Y}log truncated — reattaching{R}")
                last_log_pos[path] = 0
                prev_size = 0

            if size > prev_size:
                with open(path, "r", errors="replace") as f:
                    f.seek(prev_size)
                    new_content = f.read()

                lines = [l for l in new_content.split("\n") if l.strip()]
                # Only show error/warning lines or last 2 lines
                important = [l for l in lines if any(
                    kw in l.lower() for kw in
                    ["error", "exception", "traceback", "killed", "crash",
                     "warn", "dead", "fail", "critical"]
                )]
                if important:
                    for line in important[-3:]:
                        emit(name, f"{Y}⚠ {line[:120]}{R}", Y)
                elif lines:
                    for line in lines[-2:]:
                        emit(name, f"{DM}{line[:120]}{R}")

                last_log_pos[path] = size

        except Exception as e:
            pass

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    emit("SYS     ", f"{C}{B}NEX Debug Stream starting...{R}  press Ctrl+C to stop")
    emit("SYS     ", f"{DM}Watching: processes, ports, logs — streaming all activity{R}")
    print()

    last_check = 0

    try:
        while True:
            now = time.time()

            if now - last_check >= CHECK_INTERVAL:
                check_processes()
                check_ports()
                last_check = now

            stream_logs()
            time.sleep(STREAM_INTERVAL)

    except KeyboardInterrupt:
        print()
        emit("SYS     ", "Debug stream stopped.")
        if restart_counts:
            emit("SYS     ", "Restart summary:")
            for name, count in restart_counts.items():
                if count > 0:
                    emit("SYS     ", f"  {name.strip()}: restarted {count}x")

if __name__ == "__main__":
    main()
