#!/bin/bash
while true; do
  if ! curl -s http://localhost:8080/health > /dev/null 2>&1; then
    echo "[watchdog] llama-server down, restarting..."
    nohup /media/rr/NEX/llama.cpp/build/bin/llama-server \
      -m /home/rr/Desktop/nex/nex_lora.gguf \
      -c 4096 --port 8080 --host 0.0.0.0 -ngl 99 \
      > /tmp/llama-server.log 2>&1 &
    sleep 15
  fi
  sleep 10
done
