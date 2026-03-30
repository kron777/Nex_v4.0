#!/bin/bash
# NEX launcher — opens 3 terminal windows

NEX_DIR="$HOME/Desktop/nex"

# Window 1: Brain
gnome-terminal --title="NEX · brain" -- bash -c "cd $NEX_DIR && source venv/bin/activate && python3 run.py; exec bash"

# Window 2: Auto-check
gnome-terminal --title="NEX · auto-check" -- bash -c "cd $NEX_DIR && source venv/bin/activate && python3 auto_check.py; exec bash"

# Window 3: Chat
gnome-terminal --title="NEX · chat" -- bash -c "cd $NEX_DIR && source venv/bin/activate && python3 nex_chat.py; exec bash"
