#!/bin/bash
# nex_exit.sh — Hard shutdown of all NEX and GPU processes
# Works with AMD ROCm (RX 6600 LE) — no nvidia-smi dependency

echo "[NEX] Shutting down all processes..."
# ── Stop systemd services first (prevents race with pkill) ──────
sudo systemctl stop nex-llama 2>/dev/null
sudo systemctl stop nex-refinement-loop 2>/dev/null
sleep 1


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

# ── Step 2: Kill only llama-server GPU processes (NOT display server) ──
# Get llama-server PID specifically — never kill gnome-shell or Xorg
LLAMA_PID=$(pgrep -f "llama-server" 2>/dev/null)
if [ -n "$LLAMA_PID" ]; then
    echo "[NEX] Killing llama-server PIDs: $LLAMA_PID"
    kill -9 $LLAMA_PID 2>/dev/null
fi
# Check VRAM holders but ONLY kill known NEX processes
GPU_PIDS=$(sudo fuser /dev/kfd 2>/dev/null | tr " " "\n" | grep -v "^$")
for pid in $GPU_PIDS; do
    PNAME=$(ps -p $pid -o comm= 2>/dev/null)
    if echo "$PNAME" | grep -qE "llama|python|nex"; then
        echo "[NEX] Killing GPU process: $pid ($PNAME)"
        kill -9 "$pid" 2>/dev/null
    fi
done

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
