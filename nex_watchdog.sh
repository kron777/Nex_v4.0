#!/bin/bash
while true; do
  if ! curl -s http://localhost:8080/health > /dev/null 2>&1; then
    echo "[watchdog] llama-server down, restarting..."
    # Kill any zombie instances before spawning
    pkill -f "llama-server.*8080" 2>/dev/null
    sleep 3
    nohup /media/rr/NEX/llama.cpp/build/bin/llama-server \
      -m /home/rr/Desktop/nex/nex_lora.gguf \
      -c 4096 --port 8080 --host 0.0.0.0 -ngl 99 \
      > /tmp/llama-server.log 2>&1 &
    # Wait long enough for model to fully load before checking again
    sleep 45
  fi
  sleep 10
done
