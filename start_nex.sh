#!/bin/bash
echo "[NEX] Starting full stack..."
mountpoint -q /mnt/nex || sudo mount /dev/sdb2 /mnt/nex

export LD_LIBRARY_PATH=/media/rr/NEX/llama.cpp/build/bin:$LD_LIBRARY_PATH
export HSA_OVERRIDE_GFX_VERSION=10.3.0
export HSA_ENABLE_SDMA=0
export ROCR_VISIBLE_DEVICES=0
LLAMA=/media/rr/NEX/llama.cpp/build/bin/llama-server
MODEL=/media/rr/NEX/models/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf
NEX_DIR=/home/rr/Desktop/nex

pkill -9 -f llama-server 2>/dev/null
pkill -9 -f run.py 2>/dev/null
sleep 2

echo "[NEX] Starting LLM..."
nohup "$LLAMA" -m "$MODEL" --port 8080 -ngl 35 --host 0.0.0.0 >> /tmp/llama_server.log 2>&1 &
LLAMA_PID=$!
echo "[NEX] llama-server PID: $LLAMA_PID"

echo "[NEX] Waiting for LLM..."
for i in $(seq 1 30); do
  curl -s --max-time 2 http://localhost:8080/health | grep -q ok && echo "[NEX] LLM ONLINE" && break
  sleep 3
done

echo "[NEX] Starting terminals..."
NEX_DIR_ESC=$NEX_DIR
gnome-terminal --title="NEX BRAIN" -- bash -c "tmux kill-session -t nex 2>/dev/null; tmux new-session -d -s nex; tmux split-window -h -t nex; tmux send-keys -t nex:0.0 'tail -f /tmp/nex_brain.log' Enter; tmux send-keys -t nex:0.1 'cd $NEX_DIR && source venv/bin/activate && sleep 5 && python3 nex_debug.py' Enter; tmux attach -t nex" &

gnome-terminal --title="NEX AUTO CHECK" -- bash -c "cd $NEX_DIR && source venv/bin/activate && sleep 7 && python3 auto_check.py; exec bash" &

sleep 3
echo "[NEX] Starting brain..."
nohup python3 -u $NEX_DIR/run.py --no-server --background >> /tmp/nex_brain.log 2>&1 &
echo "[NEX] Brain PID: $!"
# NO trap, NO wait
