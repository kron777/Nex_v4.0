#!/bin/bash
# nex_exit.sh — Hard shutdown of all NEX and GPU processes
# Works with AMD ROCm (RX 6600 LE) — no nvidia-smi dependency

echo "[NEX] Shutting down all processes..."

# ── Step 1: Kill by name (catches most cases) ─────────────────────
for pattern in \
    "llama-server" \
    "nex_api.py" \
    "nex_brain" \
    "nex_scheduler.py" \
    "nex_ingest.py" \
    "nex_watchdog" \
    "nex_debug.py" \
    "nex_telegram" \
    "nex_launch.sh" \
    "start_nex.sh" \
    "auto_check.py" \
    "run.py" \
    "ollama" \
    "nex_self_trainer" \
    "nex_finetune"
do
    pkill -9 -f "$pattern" 2>/dev/null
done

# ── Step 2: Kill any process holding the GPU render node ──────────
GPU_PIDS=$(sudo fuser /dev/dri/renderD128 2>/dev/null | tr ' ' '\n' | grep -v '^$')
if [ -n "$GPU_PIDS" ]; then
    echo "[NEX] Killing GPU holders: $GPU_PIDS"
    for pid in $GPU_PIDS; do
        kill -9 "$pid" 2>/dev/null
    done
fi

# Also check renderD129 (some setups use different node)
GPU_PIDS2=$(sudo fuser /dev/dri/renderD129 2>/dev/null | tr ' ' '\n' | grep -v '^$')
if [ -n "$GPU_PIDS2" ]; then
    echo "[NEX] Killing GPU holders (D129): $GPU_PIDS2"
    for pid in $GPU_PIDS2; do
        kill -9 "$pid" 2>/dev/null
    done
fi

# ── Step 3: Kill tmux sessions ────────────────────────────────────
tmux kill-server 2>/dev/null

# ── Step 4: Wait and verify ───────────────────────────────────────
sleep 2

STILL_RUNNING=$(ps aux | grep -E "llama-server|nex_api|nex_brain|nex_sched|nex_watch|nex_ingest|nex_self_train" | grep -v grep)
if [ -n "$STILL_RUNNING" ]; then
    echo "[NEX] WARNING: still running!"
    echo "$STILL_RUNNING"
else
    echo "[NEX] All stopped."
fi

# ── Step 5: Verify VRAM freed (ROCm) ─────────────────────────────
VRAM_FILE=$(ls /sys/class/drm/card*/device/mem_info_vram_used 2>/dev/null | head -1)
if [ -n "$VRAM_FILE" ]; then
    VRAM_USED=$(cat "$VRAM_FILE")
    VRAM_MB=$((VRAM_USED / 1024 / 1024))
    if [ "$VRAM_MB" -lt 500 ]; then
        echo "[NEX] VRAM free: ~${VRAM_MB}MB used — GPU is clear ✓"
    else
        echo "[NEX] WARNING: VRAM still shows ${VRAM_MB}MB used"
        echo "[NEX] If training next, wait 10s or reboot for a clean state"
    fi
fi

echo "CLEAN."
