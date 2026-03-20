#!/bin/bash
echo "[NEX EXIT] Initiating clean shutdown..."

NEX_PID=$(pgrep -f 'python3.*run.py' | head -1)
if [ -n "$NEX_PID" ]; then
    echo "[NEX EXIT] SIGTERM to brain (pid=$NEX_PID)..."
    kill -TERM "$NEX_PID" 2>/dev/null
    for i in $(seq 1 8); do
        sleep 1
        kill -0 "$NEX_PID" 2>/dev/null || { echo "[NEX EXIT] Brain exited (${i}s)"; break; }
    done
    kill -9 "$NEX_PID" 2>/dev/null
fi

pkill -9 -f 'auto_check.py'   2>/dev/null
pkill -9 -f 'nex_debug.py'    2>/dev/null
pkill -9 -f 'pipe_all.py'     2>/dev/null
pkill -9 -f 'groq_pipeline'   2>/dev/null
pkill -9 -f 'claude_pipeline' 2>/dev/null

echo "[NEX EXIT] Stopping Ollama..."
sudo systemctl stop ollama 2>/dev/null

fuser -k 8765/tcp 2>/dev/null
fuser -k 8766/tcp 2>/dev/null

if command -v rocm-smi &>/dev/null; then
    echo "[NEX EXIT] Releasing ROCm context..."
    rocm-smi --resetclocks >/dev/null 2>&1 || true
    VRAM=$(rocm-smi --showmeminfo vram 2>/dev/null | grep 'Used' | awk '{print $NF}' | head -1)
    echo "[NEX EXIT] VRAM used: ${VRAM:-unknown}"
fi

echo "[NEX EXIT] Done."
