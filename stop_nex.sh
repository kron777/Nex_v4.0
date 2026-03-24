#!/bin/bash
echo "[NEX] Shutting down..."
sudo pkill -9 -f run.py 2>/dev/null
sudo pkill -9 -f auto_check 2>/dev/null
sudo pkill -9 -f nex_debug 2>/dev/null
sudo pkill -9 -f ollama 2>/dev/null
pkill -9 -f cloudflared 2>/dev/null
fuser -k 8766/tcp 2>/dev/null
fuser -k 8765/tcp 2>/dev/null
fuser -k 7777/tcp 2>/dev/null
tmux kill-server 2>/dev/null
sleep 2
echo "[NEX] GPU memory freed:"
rocm-smi --showmeminfo vram 2>/dev/null || echo "(rocm-smi not available)"
echo "[NEX] Shutdown complete."
