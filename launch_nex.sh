#!/bin/bash
export MISTRAL_API_KEY=ynlH7Lh5i9MPmIZy69T3G6sYYxMTu0mb

pkill -9 -f run.py 2>/dev/null
pkill -9 -f auto_check 2>/dev/null
pkill -9 -f nex_debug 2>/dev/null
fuser -k 8766/tcp 2>/dev/null
fuser -k 8765/tcp 2>/dev/null
tmux kill-server 2>/dev/null
sleep 2

cd /opt/nex
export MISTRAL_API_KEY=ynlH7Lh5i9MPmIZy69T3G6sYYxMTu0mb
/opt/nex/venv/bin/python3 -u run.py --no-server --background > /tmp/nex_brain.log 2>&1 &
sleep 2

gnome-terminal --title="NEX BRAIN" -- tmux new-session \; \
  send-keys "tail -f /tmp/nex_brain.log" Enter \; \
  split-window -h \; \
  send-keys "sleep 3 && cd /opt/nex && /opt/nex/venv/bin/python3 nex_debug.py" Enter \; \
  select-pane -t 0 &

gnome-terminal --title="NEX AUTO CHECK" -- bash -c "
export MISTRAL_API_KEY=ynlH7Lh5i9MPmIZy69T3G6sYYxMTu0mb
cd /opt/nex
sleep 7 && /opt/nex/venv/bin/python3 auto_check.py
exec bash
" &
