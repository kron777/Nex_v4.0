#!/usr/bin/env bash
cd ~/Desktop/nex
sudo mount -o remount,exec /media/rr/NEX 2>/dev/null
source venv/bin/activate

LLAMA_BIN="/media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build-rocm/bin/llama-server"
MODEL="/media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf"

pkill -9 -f "llama-server" 2>/dev/null
pkill -9 -f "nex_telegram" 2>/dev/null
sleep 2

echo "  [NEX] Starting Mistral 7B..."
HSA_OVERRIDE_GFX_VERSION=10.3.0 HIP_VISIBLE_DEVICES=0 \
  "$LLAMA_BIN" --model "$MODEL" \
  --port 8080 --n-gpu-layers 28 --ctx-size 2048 \
  >> /tmp/llama_server.log 2>&1 &

echo "  [NEX] Waiting for LLM server..."
for i in $(seq 1 30); do
  if curl -s http://localhost:8080/health | grep -q "ok"; then
    echo "  [NEX] LLM server ready."
    break
  fi
  sleep 2
done

python3 run.py --no-server 2>&1 | tee /tmp/nex_brain.log
