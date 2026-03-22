#!/bin/bash
echo "[NEX] Starting full stack..."
# Mount NEX drive if not mounted
mountpoint -q /mnt/nex || sudo mount /dev/sdb2 /mnt/nex

export LD_LIBRARY_PATH=/mnt/steam_library/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build-vulkan/bin:$LD_LIBRARY_PATH
export HSA_OVERRIDE_GFX_VERSION=10.3.0
export HSA_ENABLE_SDMA=0
export ROCR_VISIBLE_DEVICES=0

LLAMA=/mnt/steam_library/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build-vulkan/bin/llama-server
MODEL=/mnt/steam_library/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf
NEX_DIR=/home/rr/Nex_v4.0

pkill -f llama-server 2>/dev/null
pkill -f run.py 2>/dev/null
sleep 2

echo "[NEX] Starting LLM..."
"$LLAMA" -m "$MODEL" --port 8080 -ngl 20 --host 0.0.0.0 > /tmp/llama_server.log 2>&1 &

echo "[NEX] Waiting for LLM..."
for i in $(seq 1 30); do
  curl -s --max-time 2 http://localhost:8080/health | grep -q ok && echo "[NEX] LLM ONLINE" && break
  sleep 3
done

echo "[NEX] Starting brain..."
cd "$NEX_DIR" && source venv/bin/activate
python3 -u run.py --no-server --background > /tmp/nex_brain.log 2>&1 &
sleep 3

while true; do
  curl -s --max-time 2 http://localhost:8080/health | grep -q ok || {
    echo "[watchdog] LLM down - restarting..."
    "$LLAMA" -m "$MODEL" --port 8080 -ngl 20 --host 0.0.0.0 >> /tmp/llama_server.log 2>&1 &
    sleep 15
  }
  sleep 30
done &


gnome-terminal --title="NEX BRAIN" -- bash -c "cd /home/rr/Nex_v4.0 && source venv/bin/activate && tmux kill-session -t nex 2>/dev/null; tmux new-session -d -s nex && tmux split-window -h -t nex && tmux send-keys -t nex:0.0 'tail -f /tmp/nex_brain.log' Enter && tmux send-keys -t nex:0.1 'cd /home/rr/Nex_v4.0 && source venv/bin/activate && sleep 5 && python3 nex_debug.py' Enter && tmux attach -t nex; exec bash" &
gnome-terminal --title="NEX AUTO CHECK" -- bash -c "cd /home/rr/Nex_v4.0 && source venv/bin/activate && sleep 5 && python3 auto_check.py; exec bash" &
echo "[NEX] All systems live!"
