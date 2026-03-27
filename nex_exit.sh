#!/bin/bash
echo "[NEX] Shutting down all processes..."
pkill -9 -f "start_nex.sh" 2>/dev/null
pkill -9 -f "llama-server" 2>/dev/null
pkill -9 -f "run.py" 2>/dev/null
pkill -9 -f "nex_debug.py" 2>/dev/null
pkill -9 -f "nex_telegram" 2>/dev/null
pkill -9 -f "auto_check.py" 2>/dev/null
pkill -9 -f "ollama" 2>/dev/null
sudo systemctl stop ollama 2>/dev/null || true
tmux kill-server 2>/dev/null
sleep 1
echo "[NEX] All stopped. GPU should be free."
ps aux | grep -E "llama|run.py" | grep -v grep && echo "WARNING: still running!" || echo "CLEAN."
