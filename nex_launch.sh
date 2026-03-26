#!/bin/bash
# nex_launch.sh — hardened launch with clean exit trap
# license check removed — file no longer exists

# ── ROCm / HIP environment ───────────────────────────────────────────────────
export HSA_OVERRIDE_GFX_VERSION=10.3.0
export LD_LIBRARY_PATH=/mnt/steam_library/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build-vulkan/bin:$LD_LIBRARY_PATH
export GGML_CUDA_NO_CUDA_GRAPHS=1
export HSA_ENABLE_SDMA=0
export ROCR_VISIBLE_DEVICES=0
export AMD_SERIALIZE_KERNEL=3
export AMD_SERIALIZE_COPY=3

BUILD="/mnt/steam_library/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build-vulkan/bin"
MODEL="/mnt/steam_library/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf"
NEX_DIR="/home/rr/Desktop/nex"

# ── Clean any existing processes first ───────────────────────────────────────
echo "[NEX] Stopping existing processes..."
bash "$NEX_DIR/nex_exit.sh" 2>/dev/null
sleep 2

# ── Launch llama-server ───────────────────────────────────────────────────────
echo "[NEX] Starting llama-server (GPU ngl=28)..."
"$BUILD/llama-server" \
    -m "$MODEL" \
    --port 8080 \
    -ngl 35 \
    --host 0.0.0.0 \
    -c 1024 \
    --parallel 2 \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    -fa 1 \
    --no-mmap \
    > /tmp/llama_server.log 2>&1 &
LLAMA_PID=$!
disown

# ── Wait for LLM to be ready ─────────────────────────────────────────────────
echo "[NEX] Waiting for LLM..."
MAX_WAIT=90
ELAPSED=0
while true; do
    STATUS=$(curl -s --max-time 2 http://localhost:8080/health 2>/dev/null | grep -o '"ok"')
    if [ "$STATUS" = '"ok"' ]; then
        echo "[NEX] LLM ONLINE ✓ (${ELAPSED}s)"
        break
    fi
    if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
        echo "[NEX] WARNING: LLM not ready after ${MAX_WAIT}s — check /tmp/llama_server.log"
        echo "[NEX] Tail: $(tail -5 /tmp/llama_server.log)"
        echo "[NEX] Continuing with Groq fallback..."
        break
    fi
    sleep 3
    ELAPSED=$((ELAPSED + 3))
    printf "[NEX] ...%ds\r" "$ELAPSED"
done

# ── Launch NEX brain ──────────────────────────────────────────────────────────
echo "[NEX] Starting NEX brain..."
cd "$NEX_DIR"
source "$NEX_DIR/venv/bin/activate"
python3 -u run.py --no-server > /tmp/nex_brain.log 2>&1 &
NEX_PID=$!
disown
sleep 2

# ── Verify brain started ──────────────────────────────────────────────────────
if kill -0 "$NEX_PID" 2>/dev/null; then
    echo "[NEX] Brain ONLINE ✓ (pid=$NEX_PID)"
else
    echo "[NEX] ERROR: Brain failed to start — check /tmp/nex_brain.log"
    tail -20 /tmp/nex_brain.log
    exit 1
fi

# ── Open terminals ────────────────────────────────────────────────────────────
gnome-terminal --title="NEX BRAIN" -- bash -c "
    cd "$NEX_DIR" && source venv/bin/activate
    tmux kill-session -t nex 2>/dev/null
    tmux new-session -d -s nex
    tmux split-window -h -t nex
    tmux send-keys -t nex:0.0 'tail -f /tmp/nex_brain.log' Enter
    tmux send-keys -t nex:0.1 'cd $NEX_DIR && source venv/bin/activate && sleep 5 && python3 nex_debug.py' Enter
    tmux attach -t nex
    exec bash" &

gnome-terminal --title="NEX AUTO CHECK" -- bash -c "
    cd $NEX_DIR && source venv/bin/activate
    sleep 7 && python3 auto_check.py
    exec bash" &

echo "[NEX] All systems live."
echo "[NEX] To stop cleanly: bash $NEX_DIR/nex_exit.sh"
