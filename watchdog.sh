#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  NEX WATCHDOG v2.0
#  - Starts Mistral 7B (llama.cpp) first
#  - Then starts NEX (run.py)
#  - Auto-restarts both on crash/disconnect
#  - Ctrl+C cleanly kills everything
#  Usage: ./watchdog.sh
# ═══════════════════════════════════════════════════════════════

cd ~/Desktop/nex
source venv/bin/activate

# ── Config ──────────────────────────────────────────────────────
LLAMA_SERVER="/media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build/bin/llama-server"
LLAMA_MODEL="/media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf"
PORT=8080
RESTART_DELAY=5
MAX_RESTARTS=100
LOG=~/.config/nex/watchdog.log
mkdir -p ~/.config/nex

LLAMA_PID=""
restarts=0

# ── Banner ───────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║  🐕 NEX WATCHDOG v2.0                    ║"
echo "  ║  Mistral 7B + NEX + Auto-restart         ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
echo "  Restart delay : ${RESTART_DELAY}s"
echo "  Max restarts  : ${MAX_RESTARTS}"
echo "  Log           : ${LOG}"
echo ""

# ── Cleanup on Ctrl+C ───────────────────────────────────────────
cleanup() {
    echo ""
    echo "  🐕 Watchdog stopping. Total restarts: $restarts"
    echo "[$(date)] Watchdog stopped. Restarts: $restarts" >> "$LOG"
    pkill -f "python.*run.py"   2>/dev/null
    pkill -f "nex_telegram"     2>/dev/null
    pkill -f "pipe_all"         2>/dev/null
    pkill -f "gemini_pipeline"  2>/dev/null
    [ -n "$LLAMA_PID" ] && kill "$LLAMA_PID" 2>/dev/null
    pkill -f "llama-server"     2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Function: ensure llama.cpp is running ───────────────────────
ensure_llama() {
    # Already running?
    if curl -s "http://localhost:${PORT}/health" 2>/dev/null | grep -q '"status":"ok"'; then
        return 0
    fi

    echo "  [llama] Starting Mistral 7B on port ${PORT}..."
    echo "[$(date)] Starting llama-server" >> "$LOG"

    # Kill any stale server first
    pkill -f "llama-server" 2>/dev/null
    sleep 1

    "$LLAMA_SERVER" \
        -m "$LLAMA_MODEL" \
        --host 127.0.0.1 \
        --port "$PORT" \
        -c 4096 \
        -ngl 0 \
        --log-disable \
        >> "$LOG" 2>&1 &
    LLAMA_PID=$!

    # Wait up to 45s for it to be ready
    for i in $(seq 1 45); do
        sleep 1
        if curl -s "http://localhost:${PORT}/health" 2>/dev/null | grep -q '"status":"ok"'; then
            echo "  [llama] ✓ Online (${i}s)"
            echo "[$(date)] llama-server ready after ${i}s" >> "$LOG"
            return 0
        fi
        printf "  [llama] loading... %ds\r" "$i"
    done

    echo "  [llama] ✗ Failed to start after 45s — check $LOG"
    echo "[$(date)] llama-server failed to start" >> "$LOG"
    return 1
}

# ── Main watchdog loop ───────────────────────────────────────────
while [ $restarts -lt $MAX_RESTARTS ]; do

    echo "[$(date)] Starting NEX (restart #$restarts)" >> "$LOG"

    if [ $restarts -gt 0 ]; then
        echo ""
        echo "  🐕 Restarting in ${RESTART_DELAY}s... (restart #$restarts)"
        pkill -f "nex_telegram" 2>/dev/null
        sleep "$RESTART_DELAY"
    fi

    # Ensure brain is alive before launching NEX
    ensure_llama
    if [ $? -ne 0 ]; then
        echo "  ✗ Cannot start llama.cpp — retrying in 30s"
        sleep 30
        restarts=$((restarts + 1))
        continue
    fi

    # Launch NEX
    python3 run.py
    EXIT_CODE=$?

    echo "[$(date)] NEX exited with code $EXIT_CODE" >> "$LOG"

    # Clean exit (/quit) — don't restart
    if [ $EXIT_CODE -eq 0 ]; then
        echo "  🐕 Clean exit — watchdog standing down."
        break
    fi

    echo "  🐕 NEX crashed (exit $EXIT_CODE) — watchdog kicking in..."
    restarts=$((restarts + 1))

done

echo "  🐕 Max restarts reached ($MAX_RESTARTS). Giving up."
echo "[$(date)] Max restarts reached" >> "$LOG"

# Final cleanup
[ -n "$LLAMA_PID" ] && kill "$LLAMA_PID" 2>/dev/null
