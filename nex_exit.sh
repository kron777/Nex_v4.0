#!/bin/bash
# nex_exit.sh — clean NEX shutdown, releases RX 6600 VRAM

echo "[NEX EXIT] Initiating clean shutdown..."

# 1. Signal run.py to flush beliefs gracefully before killing
NEX_PID=$(pgrep -f 'python3.*run.py' | head -1)
if [ -n "$NEX_PID" ]; then
    echo "[NEX EXIT] Sending SIGTERM to NEX brain (pid=$NEX_PID)..."
    kill -TERM "$NEX_PID" 2>/dev/null
    # Give it up to 8s to flush
    for i in $(seq 1 8); do
        sleep 1
        kill -0 "$NEX_PID" 2>/dev/null || { echo "[NEX EXIT] Brain exited cleanly (${i}s)"; break; }
    done
    # Force kill if still alive
    kill -9 "$NEX_PID" 2>/dev/null
fi

# 2. Kill all NEX-related python processes
pkill -9 -f 'auto_check.py'   2>/dev/null
pkill -9 -f 'nex_debug.py'    2>/dev/null
pkill -9 -f 'pipe_all.py'     2>/dev/null
pkill -9 -f 'groq_pipeline'   2>/dev/null
pkill -9 -f 'claude_pipeline' 2>/dev/null

# 3. Kill llama-server and release GPU
LLAMA_PID=$(pgrep -f 'llama-server' | head -1)
if [ -n "$LLAMA_PID" ]; then
    echo "[NEX EXIT] Stopping llama-server (pid=$LLAMA_PID)..."
    kill -TERM "$LLAMA_PID" 2>/dev/null
    sleep 3
    kill -9 "$LLAMA_PID" 2>/dev/null
fi

# 4. Release ports
fuser -k 8080/tcp 2>/dev/null
fuser -k 8765/tcp 2>/dev/null
fuser -k 8766/tcp 2>/dev/null

# 5. Force ROCm/HIP GPU context release
# rocm-smi --resetclocks resets any hung compute contexts
if command -v rocm-smi &>/dev/null; then
    echo "[NEX EXIT] Releasing ROCm GPU context..."
    rocm-smi --resetclocks >/dev/null 2>&1 || true
fi

# 6. Verify VRAM cleared
if command -v rocm-smi &>/dev/null; then
    VRAM_USED=$(rocm-smi --showmeminfo vram 2>/dev/null | grep 'VRAM Total Used' | awk '{print $NF}' | head -1)
    echo "[NEX EXIT] VRAM used after cleanup: ${VRAM_USED:-unknown} bytes"
fi

echo "[NEX EXIT] Done."
