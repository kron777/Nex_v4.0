#!/bin/bash
NEX_DIR="/home/rr/Desktop/nex"

while true; do
  # Watch llama-server
  if ! curl -s http://localhost:8080/health > /dev/null 2>&1; then
    echo "[watchdog] llama-server down, restarting..."
    pkill -f "llama-server.*8080" 2>/dev/null
    sleep 3
    nohup /media/rr/NEX/llama.cpp/build/bin/llama-server \
      -m $NEX_DIR/nex_lora.gguf \
      -c 4096 --port 8080 --host 0.0.0.0 -ngl 99 \
      > /tmp/llama-server.log 2>&1 &
    sleep 45
  fi

  # Watch nex_api
  if ! curl -s http://localhost:7823/api/version > /dev/null 2>&1; then
    echo "[watchdog] nex_api down, restarting..."
    pkill -f "nex_api.py" 2>/dev/null
    sleep 1
    cd $NEX_DIR && source venv/bin/activate
    nohup python3 $NEX_DIR/nex_api.py > /tmp/nex_api.log 2>&1 &
    sleep 5
  fi

  # Watch nex_scheduler
  if ! curl -s http://localhost:7825/scheduler/status > /dev/null 2>&1; then
    echo "[watchdog] nex_scheduler down, restarting..."
    pkill -f "nex_scheduler.py" 2>/dev/null
    sleep 1
    cd $NEX_DIR && source venv/bin/activate
    nohup python3 $NEX_DIR/nex_scheduler.py > /tmp/nex_scheduler.log 2>&1 &
    sleep 5
  fi

  sleep 10
done
