#!/bin/bash

# ── ROCm / HIP environment ────────────────────────────────────────────────────
export HSA_OVERRIDE_GFX_VERSION=10.3.0
export GGML_CUDA_NO_CUDA_GRAPHS=1
export HSA_ENABLE_SDMA=0
export ROCR_VISIBLE_DEVICES=0
export AMD_SERIALIZE_KERNEL=3
export AMD_SERIALIZE_COPY=3

# ── Kill any existing NEX / LLM processes ────────────────────────────────────
echo "[NEX] Stopping existing processes..."
pkill -9 -f run.py      2>/dev/null
pkill -9 -f auto_check  2>/dev/null
pkill -9 -f llama-server 2>/dev/null
fuser -k 8766/tcp 2>/dev/null
fuser -k 8765/tcp 2>/dev/null
fuser -k 8080/tcp 2>/dev/null
sleep 2

# ── Launch llama-server (GPU, 28 layers) ──────────────────────────────────────
BUILD="/media/rr/4TB DATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build/bin"
MODEL="/media/rr/4TB DATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf"

echo "[NEX] Starting llama-server (GPU ngl=28)..."
"$BUILD/llama-server" \
    -m "$MODEL" \
    --port 8080 \
    -ngl 28 \
    --host 0.0.0.0 \
    > /tmp/llama_server.log 2>&1 &
disown

# ── Wait until llama-server is actually ready (health check loop) ─────────────
echo "[NEX] Waiting for LLM to come online..."
MAX_WAIT=90
ELAPSED=0
while true; do
    STATUS=$(curl -s --max-time 2 http://localhost:8080/health 2>/dev/null | grep -o '"ok"' )
    if [ "$STATUS" = '"ok"' ]; then
        echo "[NEX] LLM ONLINE ✓ (${ELAPSED}s)"
        break
    fi
    if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
        echo "[NEX] WARNING: LLM did not come online after ${MAX_WAIT}s — check /tmp/llama_server.log"
        echo "[NEX] Continuing anyway (Groq fallback will be used)..."
        break
    fi
    sleep 3
    ELAPSED=$((ELAPSED + 3))
    echo "[NEX] ...waiting ${ELAPSED}s"
done

# ── Launch NEX brain ──────────────────────────────────────────────────────────
echo "[NEX] Starting NEX brain..."
cd /home/rr/Desktop/nex
source /home/rr/Desktop/nex/venv/bin/activate
python3 -u run.py --no-server --background > /tmp/nex_brain.log 2>&1 &
disown
sleep 2

# ── Open terminals ────────────────────────────────────────────────────────────
gnome-terminal --title="NEX BRAIN" -- bash -c "
    cd /home/rr/Desktop/nex && source venv/bin/activate
    tmux kill-session -t nex 2>/dev/null
    tmux new-session -d -s nex
    tmux split-window -h -t nex
    tmux send-keys -t nex:0.0 'tail -f /tmp/nex_brain.log' Enter
    tmux send-keys -t nex:0.1 'cd ~/Desktop/nex && source venv/bin/activate && sleep 5 && python3 nex_debug.py' Enter
    tmux attach -t nex
    exec bash" &

gnome-terminal --title="NEX AUTO CHECK" -- bash -c "
    cd /home/rr/Desktop/nex && source venv/bin/activate
    sleep 7 && python3 auto_check.py
    exec bash" &

echo "[NEX] All systems launched."
