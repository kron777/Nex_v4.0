#!/bin/bash
NEX_DIR="/home/rr/Desktop/nex"
gnome-terminal --title="NEX BRAIN" -- bash -c "while true; do tail -F /tmp/nex_brain.log 2>/dev/null; sleep 2; done; exec bash" &
sleep 2
gnome-terminal --title="NEX DEBUG" -- bash -c "cd $NEX_DIR && source venv/bin/activate && sleep 5 && while true; do python3 nex_debug.py; sleep 3; done; exec bash" &
