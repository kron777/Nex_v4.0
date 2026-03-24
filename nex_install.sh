#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  NEX v4.0 — GUIDED INSTALLER
#  Intelligence Organism Setup
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# ── Colours ────────────────────────────────────────────────────
R='\033[0;31m'  # red
G='\033[0;32m'  # green
C='\033[0;36m'  # cyan
Y='\033[1;33m'  # yellow
W='\033[1;37m'  # white bold
D='\033[2;37m'  # dim
M='\033[0;35m'  # magenta
B='\033[0;34m'  # blue
NC='\033[0m'    # reset
BOLD='\033[1m'
DIM='\033[2m'

# ── Helpers ─────────────────────────────────────────────────────
banner() {
  clear
  echo -e "${C}"
  echo '  ███╗   ██╗███████╗██╗  ██╗'
  echo '  ████╗  ██║██╔════╝╚██╗██╔╝'
  echo '  ██╔██╗ ██║█████╗   ╚███╔╝ '
  echo '  ██║╚██╗██║██╔══╝   ██╔██╗ '
  echo '  ██║ ╚████║███████╗██╔╝ ██╗'
  echo '  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝'
  echo -e "${NC}"
  echo -e "  ${DIM}────────────────────────────────────────────────────${NC}"
  echo -e "  ${W}◈  N E X   v 4 . 0   ◈  [ D Y N A M I C   I N T E L L I G E N C E ]${NC}"
  echo -e "  ${DIM}────────────────────────────────────────────────────${NC}"
  echo ""
}

section() {
  echo ""
  echo -e "  ${C}┌─────────────────────────────────────────────────┐${NC}"
  echo -e "  ${C}│${NC}  ${W}${1}${NC}"
  echo -e "  ${C}└─────────────────────────────────────────────────┘${NC}"
  echo ""
}

ask() {
  # ask <VAR> <PROMPT> [default]
  local var="$1"
  local prompt="$2"
  local default="${3:-}"
  local val=""
  if [[ -n "$default" ]]; then
    echo -ne "  ${Y}▶${NC}  ${prompt} ${DIM}[${default}]${NC}: "
  else
    echo -ne "  ${Y}▶${NC}  ${prompt}: "
  fi
  read -r val
  val="${val:-$default}"
  eval "$var='$val'"
}

ask_secret() {
  local var="$1"
  local prompt="$2"
  local val=""
  echo -ne "  ${Y}▶${NC}  ${prompt}: "
  read -rs val
  echo ""
  eval "$var='$val'"
}

ask_choice() {
  # ask_choice <VAR> <PROMPT> <opt1> <opt2> ...
  local var="$1"
  local prompt="$2"
  shift 2
  local opts=("$@")
  echo -e "  ${Y}▶${NC}  ${prompt}"
  for i in "${!opts[@]}"; do
    echo -e "      ${C}$((i+1))${NC}. ${opts[$i]}"
  done
  local choice=""
  echo -ne "  ${Y}▶${NC}  Enter number: "
  read -r choice
  eval "$var='${opts[$((choice-1))]}'"
}

ok()   { echo -e "  ${G}✓${NC}  $1"; }
info() { echo -e "  ${B}ℹ${NC}  $1"; }
warn() { echo -e "  ${Y}⚠${NC}  $1"; }
fail() { echo -e "  ${R}✗${NC}  $1"; }
step() { echo -e "\n  ${M}◈${NC}  ${BOLD}$1${NC}"; }

confirm() {
  echo -ne "  ${Y}▶${NC}  $1 ${DIM}[y/N]${NC}: "
  read -r ans
  [[ "$ans" =~ ^[Yy]$ ]]
}

pause() {
  echo -ne "\n  ${DIM}Press Enter to continue...${NC}"
  read -r
}

# ═══════════════════════════════════════════════════════════════
#  START
# ═══════════════════════════════════════════════════════════════

banner

echo -e "  ${D}Welcome to the NEX v4.0 guided installer.${NC}"
echo -e "  ${D}This will configure your system, GPU, model, and API keys.${NC}"
echo -e "  ${D}Estimated time: 5–20 minutes depending on download speed.${NC}"
echo ""
pause

# ═══════════════════════════════════════════════════════════════
#  SECTION 1 — SYSTEM CHECK
# ═══════════════════════════════════════════════════════════════
banner
section "1 / 7 — SYSTEM CHECK"

step "Checking OS"
OS=$(lsb_release -si 2>/dev/null || echo "Unknown")
VER=$(lsb_release -sr 2>/dev/null || echo "")
ok "Detected: ${OS} ${VER}"

step "Checking Python"
if command -v python3 &>/dev/null; then
  PY=$(python3 --version)
  ok "$PY"
else
  fail "Python3 not found. Install python3 and rerun."
  exit 1
fi

step "Checking Git"
if command -v git &>/dev/null; then
  ok "Git $(git --version | awk '{print $3}')"
else
  warn "Git not found — installing..."
  sudo apt install -y git
fi

step "Checking build tools"
if command -v cmake &>/dev/null; then
  ok "cmake found"
else
  warn "cmake not found — installing build tools..."
  sudo apt install -y cmake build-essential
fi

pause

# ═══════════════════════════════════════════════════════════════
#  SECTION 2 — GPU SETUP
# ═══════════════════════════════════════════════════════════════
banner
section "2 / 7 — GPU CONFIGURATION"

ask_choice GPU_VENDOR "What GPU do you have?" \
  "AMD (ROCm)" \
  "NVIDIA (CUDA)" \
  "CPU only (no GPU)"

echo ""

case "$GPU_VENDOR" in
  "AMD (ROCm)")
    step "AMD GPU setup"
    info "NEX uses ROCm for AMD GPU acceleration."
    info "Your GPU must be GFX9+ (Vega, Navi, RDNA2/3)."
    echo ""

    ask_choice AMD_GFX "Select your AMD GPU family:" \
      "RDNA2 — RX 6000 series (gfx1030)" \
      "RDNA3 — RX 7000 series (gfx1100)" \
      "RDNA1 — RX 5000 series (gfx1010)" \
      "Vega — RX Vega / Radeon VII (gfx906)" \
      "Other — I'll enter manually"

    case "$AMD_GFX" in
      *"gfx1030"*) GFX_VER="10.3.0" ;;
      *"gfx1100"*) GFX_VER="11.0.0" ;;
      *"gfx1010"*) GFX_VER="10.1.0" ;;
      *"gfx906"*)  GFX_VER="9.0.6"  ;;
      *)
        ask GFX_VER "Enter your GFX version (e.g. 10.3.0)" "10.3.0"
        ;;
    esac

    ok "HSA_OVERRIDE_GFX_VERSION=${GFX_VER}"

    if ! command -v /opt/rocm*/bin/rocm-smi &>/dev/null 2>&1; then
      warn "ROCm not detected. Install ROCm from: https://rocm.docs.amd.com"
      warn "After installing ROCm, rerun this installer."
      if confirm "Continue anyway (ROCm already installed but not in PATH)?"; then
        ok "Continuing..."
      else
        exit 1
      fi
    else
      ok "ROCm detected"
    fi

    LLAMA_CMAKE_ARGS="-DGGML_HIPBLAS=ON"
    GPU_ENV="HSA_OVERRIDE_GFX_VERSION=${GFX_VER} HIP_VISIBLE_DEVICES=0 ROCR_VISIBLE_DEVICES=0"
    NGL=99
    ;;

  "NVIDIA (CUDA)")
    step "NVIDIA GPU setup"
    info "NEX uses CUDA for NVIDIA GPU acceleration."
    echo ""

    if command -v nvidia-smi &>/dev/null; then
      GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
      ok "Detected: ${GPU_NAME}"
    else
      warn "nvidia-smi not found. Install NVIDIA drivers + CUDA toolkit first."
      warn "https://developer.nvidia.com/cuda-downloads"
      if confirm "Continue anyway?"; then
        ok "Continuing..."
      fi
    fi

    LLAMA_CMAKE_ARGS="-DGGML_CUDA=ON"
    GPU_ENV=""
    NGL=99
    ;;

  "CPU only"*)
    step "CPU-only mode"
    warn "NEX will run on CPU. Performance will be significantly slower."
    LLAMA_CMAKE_ARGS=""
    GPU_ENV=""
    NGL=0
    ;;
esac

pause

# ═══════════════════════════════════════════════════════════════
#  SECTION 3 — CPU / PLATFORM
# ═══════════════════════════════════════════════════════════════
banner
section "3 / 7 — CPU PLATFORM"

CPU_INFO=$(grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)
ok "Detected CPU: ${CPU_INFO}"

ask_choice CPU_PLATFORM "What is your CPU platform?" \
  "AMD Ryzen / Threadripper" \
  "Intel Core" \
  "Other / ARM"

echo ""
ok "Platform set: ${CPU_PLATFORM}"
pause

# ═══════════════════════════════════════════════════════════════
#  SECTION 4 — API KEYS
# ═══════════════════════════════════════════════════════════════
banner
section "4 / 7 — API KEYS"

echo -e "  ${D}NEX connects to several services. Enter your API keys below.${NC}"
echo -e "  ${D}Leave blank to skip optional services (can be added later).${NC}"
echo ""

step "Anthropic (Claude) — REQUIRED for core intelligence"
ask_secret ANTHROPIC_KEY "ANTHROPIC_API_KEY (sk-ant-...)"
[[ -z "$ANTHROPIC_KEY" ]] && warn "Skipped — NEX core functions will be limited"

echo ""
step "Groq — fast LLM inference (optional but recommended)"
ask_secret GROQ_KEY "GROQ_API_KEY"
[[ -z "$GROQ_KEY" ]] && warn "Skipped"

echo ""
step "Telegram Bot — NEX social presence"
ask_secret TELEGRAM_TOKEN "Telegram Bot Token (from @BotFather)"
[[ -z "$TELEGRAM_TOKEN" ]] && warn "Skipped — Telegram disabled"

ask TELEGRAM_OWNER_ID "Your Telegram user ID (numeric)" ""
[[ -z "$TELEGRAM_OWNER_ID" ]] && warn "Skipped"

echo ""
step "Mastodon — federated social (optional)"
ask MASTODON_INSTANCE "Mastodon instance URL" "https://mastodon.social"
ask_secret MASTODON_TOKEN "Mastodon access token"
[[ -z "$MASTODON_TOKEN" ]] && warn "Skipped — Mastodon disabled"

echo ""
step "Discord — webhook for announcements (optional)"
ask_secret DISCORD_WEBHOOK "Discord webhook URL"
[[ -z "$DISCORD_WEBHOOK" ]] && warn "Skipped — Discord disabled"

pause

# ═══════════════════════════════════════════════════════════════
#  SECTION 5 — MODEL SETUP
# ═══════════════════════════════════════════════════════════════
banner
section "5 / 7 — LLM MODEL"

NEX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="${NEX_DIR}/../models"
mkdir -p "$MODEL_DIR"

DEFAULT_MODEL="Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf"
MODEL_PATH="${MODEL_DIR}/${DEFAULT_MODEL}"

if [[ -f "$MODEL_PATH" ]]; then
  ok "Model already present: ${DEFAULT_MODEL}"
  SKIP_MODEL_DL=true
else
  warn "Model not found: ${DEFAULT_MODEL}"
  echo ""
  info "NEX uses Mistral-7B-Instruct-v0.3 (abliterated, Q4_K_M ~4.1GB)"
  info "Download from: https://huggingface.co/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF"
  echo ""
  if confirm "Download model now? (requires ~4.1GB free space)"; then
    step "Downloading model..."
    HF_URL="https://huggingface.co/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/resolve/main/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf"
    wget -q --show-progress -O "$MODEL_PATH" "$HF_URL" && ok "Model downloaded" || {
      fail "Download failed. Place model manually at: ${MODEL_PATH}"
    }
  else
    warn "Skipping download. Place model at: ${MODEL_PATH}"
  fi
  SKIP_MODEL_DL=false
fi

pause

# ═══════════════════════════════════════════════════════════════
#  SECTION 6 — BUILD llama.cpp
# ═══════════════════════════════════════════════════════════════
banner
section "6 / 7 — BUILD llama.cpp"

LLAMA_DIR="${NEX_DIR}/../llama.cpp"

if [[ -f "${LLAMA_DIR}/build/bin/llama-server" ]]; then
  ok "llama-server already built"
  if confirm "Rebuild? (only needed after GPU driver changes)"; then
    REBUILD=true
  else
    REBUILD=false
  fi
else
  info "llama.cpp not built — building now..."
  REBUILD=true
fi

if [[ "$REBUILD" == true ]]; then
  step "Cloning llama.cpp..."
  if [[ ! -d "$LLAMA_DIR/.git" ]]; then
    git clone https://github.com/ggml-org/llama.cpp "$LLAMA_DIR"
  else
    git -C "$LLAMA_DIR" pull
  fi

  step "Building llama.cpp with GPU support..."
  mkdir -p "${LLAMA_DIR}/build"
  cd "${LLAMA_DIR}/build"

  if [[ -n "$LLAMA_CMAKE_ARGS" ]]; then
    cmake .. $LLAMA_CMAKE_ARGS -DCMAKE_BUILD_TYPE=Release
  else
    cmake .. -DCMAKE_BUILD_TYPE=Release
  fi

  cmake --build . --config Release -j$(nproc)
  cd "$NEX_DIR"

  if [[ -f "${LLAMA_DIR}/build/bin/llama-server" ]]; then
    ok "llama-server built successfully"
  else
    fail "Build failed. Check errors above."
    exit 1
  fi
fi

pause

# ═══════════════════════════════════════════════════════════════
#  SECTION 7 — PYTHON VENV + WRITE CONFIG
# ═══════════════════════════════════════════════════════════════
banner
section "7 / 7 — PYTHON ENVIRONMENT + FINAL CONFIG"

step "Setting up Python venv..."
if [[ ! -d "${NEX_DIR}/venv" ]]; then
  python3 -m venv "${NEX_DIR}/venv"
  ok "venv created"
else
  ok "venv exists"
fi

step "Installing Python dependencies..."
"${NEX_DIR}/venv/bin/pip" install --upgrade pip -q
"${NEX_DIR}/venv/bin/pip" install -r "${NEX_DIR}/requirements.txt" -q && ok "Dependencies installed"

step "Writing environment config..."
CONFIG_DIR="${HOME}/.config/nex"
mkdir -p "$CONFIG_DIR"

# Write .env file
ENV_FILE="${NEX_DIR}/.env"
cat > "$ENV_FILE" <<EOF
# NEX v4.0 — Environment Configuration
# Generated by nex_install.sh

ANTHROPIC_API_KEY=${ANTHROPIC_KEY}
GROQ_API_KEY=${GROQ_KEY}
TELEGRAM_BOT_TOKEN=${TELEGRAM_TOKEN}
TELEGRAM_OWNER_ID=${TELEGRAM_OWNER_ID}
MASTODON_INSTANCE=${MASTODON_INSTANCE}
MASTODON_ACCESS_TOKEN=${MASTODON_TOKEN}
DISCORD_WEBHOOK=${DISCORD_WEBHOOK}

# GPU
HSA_OVERRIDE_GFX_VERSION=${GFX_VER:-}
HIP_VISIBLE_DEVICES=0
ROCR_VISIBLE_DEVICES=0
EOF
ok ".env written to ${ENV_FILE}"

# Write Mastodon config if provided
if [[ -n "${MASTODON_TOKEN:-}" ]]; then
  cat > "${CONFIG_DIR}/mastodon_config.json" <<EOF
{
  "instance_url": "${MASTODON_INSTANCE}",
  "access_token": "${MASTODON_TOKEN}"
}
EOF
  ok "mastodon_config.json written"
fi

# Write Discord config if provided
if [[ -n "${DISCORD_WEBHOOK:-}" ]]; then
  cat > "${CONFIG_DIR}/discord_config.json" <<EOF
{
  "webhook_url": "${DISCORD_WEBHOOK}"
}
EOF
  ok "discord_config.json written"
fi

step "Writing nex launch alias..."
ALIAS_LINE="alias nex='pkill -9 -f run.py 2>/dev/null; pkill -9 -f auto_check 2>/dev/null; pkill -f llama-server 2>/dev/null; sleep 2; nohup env ${GPU_ENV} ${LLAMA_DIR}/build/bin/llama-server -m ${MODEL_PATH} --host 0.0.0.0 --port 8080 -ngl ${NGL} -c 2048 --parallel 1 > /tmp/llama-server.log 2>&1 & sleep 20; cd ${NEX_DIR} && source venv/bin/activate && gnome-terminal --title=\"NEX BRAIN\" -- bash -c \"cd ${NEX_DIR} && source venv/bin/activate && tmux new-session \\; split-window -h \\; select-pane -t 0 \\; send-keys \\\"python3 run.py --no-server\\\" Enter \\; select-pane -t 1 \\; send-keys \\\"sleep 5 && python3 nex_debug.py\\\" Enter; exec bash\" & gnome-terminal --title=\"NEX AUTO CHECK\" -- bash -c \"cd ${NEX_DIR} && source venv/bin/activate && sleep 7 && python3 auto_check.py; exec bash\"'"

# Remove old alias if exists
sed -i '/^alias nex=/d' ~/.bashrc

# Add GPU env exports
if [[ "$GPU_VENDOR" == "AMD (ROCm)" ]]; then
  grep -q "HSA_OVERRIDE_GFX_VERSION" ~/.bashrc || echo "export HSA_OVERRIDE_GFX_VERSION=${GFX_VER}" >> ~/.bashrc
  grep -q "HIP_VISIBLE_DEVICES" ~/.bashrc       || echo "export HIP_VISIBLE_DEVICES=0" >> ~/.bashrc
  grep -q "ROCR_VISIBLE_DEVICES" ~/.bashrc       || echo "export ROCR_VISIBLE_DEVICES=0" >> ~/.bashrc
fi

echo "$ALIAS_LINE" >> ~/.bashrc
ok "nex alias written to ~/.bashrc"

source ~/.bashrc 2>/dev/null || true

# ═══════════════════════════════════════════════════════════════
#  DONE
# ═══════════════════════════════════════════════════════════════
banner

echo -e "  ${G}┌─────────────────────────────────────────────────┐${NC}"
echo -e "  ${G}│${NC}  ${W}✓  NEX v4.0 INSTALLATION COMPLETE${NC}"
echo -e "  ${G}└─────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "  ${D}To launch NEX, open a new terminal and run:${NC}"
echo ""
echo -e "      ${C}nex${NC}"
echo ""
echo -e "  ${D}Logs:${NC}  /tmp/llama-server.log"
echo -e "  ${D}Config:${NC} ~/.config/nex/"
echo -e "  ${D}Env:${NC}    ${NEX_DIR}/.env"
echo ""
echo -e "  ${DIM}────────────────────────────────────────────────────${NC}"
echo -e "  ${M}◈  N E X   I S   A L I V E${NC}"
echo -e "  ${DIM}────────────────────────────────────────────────────${NC}"
echo ""
