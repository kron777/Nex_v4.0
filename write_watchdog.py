content = """#!/bin/bash
# nex_watchdog.sh — NEX v4.0 watchdog (systemd-aware)
NEX_DIR="/home/rr/Desktop/nex"

while true; do
    # Watch llama-server via systemd
    if ! curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo "[watchdog] llama-server down, restarting via systemd..."
        sudo systemctl restart nex-llama
        sleep 15
    fi

    # Watch nex_api
    if ! curl -s http://localhost:7823/api/version > /dev/null 2>&1; then
        echo "[watchdog] nex_api down, restarting..."
        pkill -f "nex_api.py" 2>/dev/null
        sleep 1
        cd $NEX_DIR && source venv/bin/activate
        nohup python3 $NEX_DIR/nex_api.py > /tmp/nex_api.log 2>&1 &
        sleep 5
    fi

    # Watch nex_scheduler
    if ! curl -s http://localhost:7825/scheduler/status > /dev/null 2>&1; then
        echo "[watchdog] nex_scheduler down, restarting..."
        pkill -f "nex_scheduler.py" 2>/dev/null
        sleep 1
        cd $NEX_DIR && source venv/bin/activate
        nohup python3 $NEX_DIR/nex_scheduler.py > /tmp/nex_scheduler.log 2>&1 &
        sleep 5
    fi

    # Watch nex_soul_loop (the brain)
    if ! pgrep -f "nex_soul_loop.py" > /dev/null 2>&1; then
        echo "[watchdog] nex_soul_loop DEAD — restarting brain..."
        cd $NEX_DIR && source venv/bin/activate
        nohup python3 $NEX_DIR/nex_soul_loop.py > /tmp/nex_brain.log 2>&1 &
        sleep 10
    fi

    sleep 10
done
"""

with open("/home/rr/Desktop/nex/nex_watchdog.sh", "w") as f:
    f.write(content)

import os
os.chmod("/home/rr/Desktop/nex/nex_watchdog.sh", 0o755)
print("watchdog written OK")
