#!/usr/bin/env bash
cd ~

# ── Mount fixes ──────────────────────────────────────────────
sudo mount -o remount,exec /media/rr/NEX 2>/dev/null

# ── Activate venv ────────────────────────────────────────────
source ~/Desktop/nex/venv/bin/activate

# ── Kill all stale processes ─────────────────────────────────
pkill -9 -f "llama-server" 2>/dev/null
pkill -9 -f "nex_telegram" 2>/dev/null
pkill -9 -f "auto_check" 2>/dev/null
pkill -9 -f "nex_debug" 2>/dev/null
sleep 2

# ── Start Mistral 7B ─────────────────────────────────────────
MODEL="/media/rr/4TB DATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf"

echo "  [NEX] Starting Mistral 7B..."
HSA_OVERRIDE_GFX_VERSION=10.3.0 HIP_VISIBLE_DEVICES=0 \
  ~/llama-bin/llama-server --model "$MODEL" \
  --port 8080 --n-gpu-layers 28 --ctx-size 2048 \
  >> /tmp/llama_server.log 2>&1 &

# ── Wait for LLM health ──────────────────────────────────────
echo "  [NEX] Waiting for LLM server..."
for i in $(seq 1 30); do
  if curl -s http://localhost:8080/health | grep -q "ok"; then
    echo "  [NEX] LLM server ready."
    break
  fi
  sleep 2
done

# ── Clear old log ────────────────────────────────────────────
> /tmp/nex_brain.log

# ── Launch NEX brain ─────────────────────────────────────────
cd ~/Desktop/nex
python3 run.py --no-server 2>&1 | tee /tmp/nex_brain.log
