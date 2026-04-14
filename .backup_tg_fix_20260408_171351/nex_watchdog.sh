#!/bin/bash
# nex_watchdog.sh — NEX v4.0 watchdog (simplified)
NEX_DIR="/home/rr/Desktop/nex"
while true; do
    # Watch llama-server via systemd
    if ! curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo "[watchdog] llama-server down, restarting via systemd..."
        sudo systemctl restart nex-llama
        sleep 15
    fi
    # Watch run.py (the real brain)
    if ! pgrep -f "run.py" > /dev/null 2>&1; then
        echo "[watchdog] run.py DEAD - restarting brain..."
        cd $NEX_DIR && source venv/bin/activate
        nohup python3 -u $NEX_DIR/run.py --no-server >> /tmp/nex_brain.log 2>&1 &
        sleep 15
    fi
    # Watch nex_telegram
    if ! pgrep -f "nex_telegram.py" > /dev/null 2>&1; then
        echo "[watchdog] nex_telegram DEAD - restarting..."
        cd $NEX_DIR && source venv/bin/activate
        nohup python3 $NEX_DIR/nex_telegram.py >> /tmp/nex_telegram.log 2>&1 &
        sleep 30
    fi
    # Watch auto_check
    if ! pgrep -f "auto_check.py" > /dev/null 2>&1; then
        echo "[watchdog] auto_check DEAD - restarting..."
        cd $NEX_DIR && source venv/bin/activate
        nohup python3 $NEX_DIR/auto_check.py > /tmp/nex_auto_check.log 2>&1 &
        sleep 5
    fi
    sleep 10
done
