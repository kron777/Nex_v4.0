#!/bin/bash
# update_alias.sh — rewrites the nex alias in ~/.bashrc to launch all platforms
# Run: bash update_alias.sh

BASHRC="$HOME/.bashrc"
BACKUP="$HOME/.bashrc.bak.$(date +%s)"

echo "Backing up ~/.bashrc → $BACKUP"
cp "$BASHRC" "$BACKUP"

# Remove all existing nex alias lines (handles multi-line fragments too)
sed -i '/^alias nex=/d' "$BASHRC"

# Write the new alias
cat >> "$BASHRC" << 'ALIAS'

alias nex='
  pkill -9 -f run.py        2>/dev/null;
  pkill -9 -f auto_check    2>/dev/null;
  pkill -9 -f llama-server  2>/dev/null;
  pkill -9 -f nex_telegram  2>/dev/null;
  pkill -9 -f nex_discord   2>/dev/null;
  pkill -9 -f nex_mastodon  2>/dev/null;
  sleep 2;
  /media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build/bin/llama-server \
    -m /media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf \
    --port 8080 -ngl 35 &>/tmp/llama.log &
  sleep 12;
  cd ~/Desktop/nex && source venv/bin/activate;
  gnome-terminal --title="NEX BRAIN"     -- bash -c "cd ~/Desktop/nex && source venv/bin/activate && python3 run.py --no-server; exec bash" &
  sleep 3;
  gnome-terminal --title="NEX TELEGRAM"  -- bash -c "cd ~/Desktop/nex && source venv/bin/activate && python3 nex_telegram.py; exec bash" &
  gnome-terminal --title="NEX DISCORD"   -- bash -c "cd ~/Desktop/nex && source venv/bin/activate && python3 nex_discord.py; exec bash" &
  gnome-terminal --title="NEX MASTODON"  -- bash -c "cd ~/Desktop/nex && source venv/bin/activate && python3 nex_mastodon.py; exec bash" &
  sleep 4;
  cd ~/Desktop/nex && source venv/bin/activate && python3 auto_check.py
'
ALIAS

echo "Done. Run: source ~/.bashrc && nex"
echo ""
echo "New alias preview:"
grep -A 30 "^alias nex=" "$BASHRC" | head -35
