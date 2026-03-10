#!/bin/bash
# NEX v4 Install Script
# Run this after cloning: bash install.sh

set -e

echo "═══════════════════════════════════════════════════"
echo "  NEX v4.0 — Dynamic Intelligence Organism"
echo "  Install Script"
echo "═══════════════════════════════════════════════════"

# ── 1. System deps ───────────────────────────────────────
echo ""
echo "[1/7] Installing system dependencies..."
sudo apt install -y python3-pip python3-venv tmux git curl

# ── 2. Detect GPU ────────────────────────────────────────
echo ""
echo "[2/7] Detecting GPU..."
GPU_TYPE="cpu"

if command -v nvidia-smi &> /dev/null; then
    echo "  ✓ NVIDIA GPU detected"
    GPU_TYPE="nvidia"
    nvidia-smi --query-gpu=name --format=csv,noheader
elif command -v rocm-smi &> /dev/null && rocm-smi &> /dev/null; then
    echo "  ✓ AMD ROCm GPU detected"
    GPU_TYPE="amd"
    rocm-smi --showproductname 2>/dev/null || true
else
    echo "  ⚠ No GPU detected — will use CPU (slow for local LLM)"
    GPU_TYPE="cpu"
fi

# ── 3. Venv ──────────────────────────────────────────────
echo ""
echo "[3/7] Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip

# ── 4. Install PyTorch for correct GPU ───────────────────
echo ""
echo "[4/7] Installing PyTorch for $GPU_TYPE..."

if [ "$GPU_TYPE" = "nvidia" ]; then
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
elif [ "$GPU_TYPE" = "amd" ]; then
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2
else
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
fi

# ── 5. Python deps ───────────────────────────────────────
echo ""
echo "[5/7] Installing Python dependencies (this will take a while)..."
pip install -r requirements.txt

# ── 6. Config dir ────────────────────────────────────────
echo ""
echo "[6/7] Setting up config directory..."
mkdir -p ~/.config/nex
echo ""
echo "  NOTE: NEX stores all data in ~/.config/nex"
echo "  If you have a dedicated drive, symlink it:"
echo "    ln -s /media/YOUR_USER/NEX/nex/config ~/.config/nex"
echo ""
read -p "  Symlink to a dedicated drive? (y/n): " SYMLINK
if [ "$SYMLINK" = "y" ]; then
    read -p "  Enter full path to your NEX data directory: " NEX_DATA_PATH
    rm -rf ~/.config/nex
    ln -s "$NEX_DATA_PATH" ~/.config/nex
    echo "  ✓ Symlinked ~/.config/nex -> $NEX_DATA_PATH"
fi

# ── 7. Aliases ───────────────────────────────────────────
echo ""
echo "[7/7] Adding aliases to ~/.bashrc..."

cat << 'ALIASES' >> ~/.bashrc

# ── NEX aliases ──────────────────────────────────────────
alias nex='pkill -9 -f run.py 2>/dev/null; pkill -9 -f auto_check 2>/dev/null; pkill -9 -f nex_debug 2>/dev/null; sleep 2; cd ~/Desktop/nex && source venv/bin/activate && gnome-terminal --title="NEX BRAIN" -- bash -c "cd ~/Desktop/nex && source venv/bin/activate && tmux new-session \; split-window -h \; select-pane -t 0 \; send-keys \"python3 run.py --no-server\" Enter \; select-pane -t 1 \; send-keys \"sleep 5 && python3 nex_debug.py\" Enter; exec bash" & gnome-terminal --title="NEX AUTO CHECK" -- bash -c "cd ~/Desktop/nex && source venv/bin/activate && sleep 7 && python3 auto_check.py; exec bash"'
alias nex-check='python3 ~/Desktop/nex/auto_check.py'
alias nex-debug='python3 ~/Desktop/nex/nex_debug.py'
alias nex-brain='python3 ~/Desktop/nex/nex_brain_monitor.py'
alias nex-status='python3 -c "import json,os; s=json.load(open(os.path.expanduser(\"~/.config/nex/session_state.json\"))); print(\"replied:\", len(s.get(\"replied_posts\",[])), \"known:\", len(s.get(\"known_posts\",[])), \"chatted:\", len(s.get(\"chatted_agents\",[])));"'
ALIASES

source ~/.bashrc

# ── Done ─────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  INSTALL COMPLETE — MANUAL STEPS REQUIRED:"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  1. Add API keys to ~/.bashrc:"
echo "       export GROQ_API_KEY=your_key_here"
echo "       export MISTRAL_API_KEY=your_key_here"
echo "       export OPENROUTER_API_KEY=your_key_here"
echo ""
echo "  2. Configure platforms:"
echo "       ~/.config/nex/mastodon_config.json"
echo "       ~/.config/nex/discord_config.json"
echo "       nex_telegram.py line 53 (token)"
echo "       nex_devto.py (Dev.to API key)"
echo ""
if [ "$GPU_TYPE" = "amd" ]; then
echo "  3. AMD GPU — ensure ROCm drivers installed:"
echo "       sudo apt install rocm"
echo "       Check: rocm-smi"
elif [ "$GPU_TYPE" = "nvidia" ]; then
echo "  3. NVIDIA GPU — ensure CUDA drivers installed:"
echo "       Check: nvidia-smi"
else
echo "  3. No GPU — local Mistral 7B will be very slow."
echo "       Cloud LLMs (Groq/Mistral API) will still work fine."
fi
echo ""
echo "  4. Launch:"
echo "       nex"
echo ""
echo "═══════════════════════════════════════════════════"
