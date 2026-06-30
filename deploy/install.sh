#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
#  FredAI — Universal Installer for Linux / macOS / Raspberry Pi
#  Supports: Ubuntu · Debian · Fedora · Arch · Alpine · Raspberry Pi OS · macOS
#
#  One-line install:
#    curl -sSL https://raw.githubusercontent.com/essentialbit/fredai/main/deploy/install.sh | bash
#
#  Or download and run:
#    chmod +x install.sh && ./install.sh
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colour helpers ───────────────────────────────────────────────────────────
R='\033[0;31m' G='\033[0;32m' Y='\033[1;33m' B='\033[0;34m' C='\033[0;36m' NC='\033[0m'
log()  { echo -e "${B}[FredAI]${NC} $*"; }
ok()   { echo -e "${G}  ✓${NC} $*"; }
warn() { echo -e "${Y}  !${NC} $*"; }
err()  { echo -e "${R}  ✗ ERROR:${NC} $*"; exit 1; }
hdr()  { echo -e "\n${C}══ $* ══${NC}"; }

# ── Environment detection ────────────────────────────────────────────────────
ARCH=$(uname -m)
OS=$(uname -s)
REPO_URL="https://github.com/essentialbit/fredai"
INSTALL_DIR="${FREDAI_DIR:-$HOME/fredai}"
VENV_DIR="$INSTALL_DIR/.venv"
DISTRO="" PKG_MGR="" SUDO=""

# distro
[[ -f /etc/os-release ]] && source /etc/os-release && DISTRO="${ID:-}"

# package manager
for pm in apt-get dnf yum pacman brew apk zypper; do
    command -v $pm &>/dev/null && { PKG_MGR=$pm; break; }
done

# sudo availability
command -v sudo &>/dev/null && SUDO="sudo"

# Memory (MB) — works on Linux and macOS
if [[ "$OS" == "Linux" ]]; then
    RAM_MB=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 4096)
elif [[ "$OS" == "Darwin" ]]; then
    RAM_MB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 4294967296) / 1024 / 1024 ))
else
    RAM_MB=4096
fi

# Determine capability tier
if   [[ $RAM_MB -lt 512 ]];  then TIER="nano"     # Pi Zero W
elif [[ $RAM_MB -lt 1024 ]]; then TIER="lite"     # Pi Zero 2
elif [[ $RAM_MB -lt 4096 ]]; then TIER="standard" # Pi 4 2GB / low-end VM
else                               TIER="full"     # Desktop / server
fi

# Ollama model selection by RAM
case $TIER in
    nano|lite) OLLAMA_MODEL="phi3:mini" ;;   # 2.3 GB VRAM / ~3 GB RAM
    standard)  OLLAMA_MODEL="llama3.2" ;;    # 4.7 GB
    full)      OLLAMA_MODEL="llama3.2" ;;
esac

hdr "FredAI Installer"
log "Platform  : $OS / $ARCH / $DISTRO"
log "RAM       : ${RAM_MB} MB  →  tier: $TIER"
log "Install   : $INSTALL_DIR"
log "AI model  : $OLLAMA_MODEL (if Ollama installed)"

# ── Step 1 — System dependencies ─────────────────────────────────────────────
hdr "1/8 System dependencies"

pkg_install() {
    local pkg="$1"
    case $PKG_MGR in
        apt-get)  $SUDO apt-get install -y -q "$pkg" ;;
        dnf|yum)  $SUDO $PKG_MGR install -y "$pkg" ;;
        pacman)   $SUDO pacman -Sy --noconfirm "$pkg" ;;
        brew)     brew install "$pkg" ;;
        apk)      $SUDO apk add --quiet "$pkg" ;;
        zypper)   $SUDO zypper install -y "$pkg" ;;
        *)        err "Unknown package manager. Please install $pkg manually." ;;
    esac
}

# Update package lists once
if [[ "$PKG_MGR" == "apt-get" ]]; then
    log "Updating apt cache..."
    $SUDO apt-get update -q
fi

# Python 3
if ! command -v python3 &>/dev/null; then
    log "Installing Python 3..."
    case $PKG_MGR in
        apt-get) $SUDO apt-get install -y -q python3 python3-pip python3-venv ;;
        dnf|yum) $SUDO $PKG_MGR install -y python3 python3-pip ;;
        pacman)  $SUDO pacman -Sy --noconfirm python python-pip ;;
        brew)    brew install python3 ;;
        apk)     $SUDO apk add --quiet python3 py3-pip ;;
        zypper)  $SUDO zypper install -y python3 python3-pip ;;
        *) err "Install python3 manually then re-run this script." ;;
    esac
fi

# Ensure venv module available (Debian/Ubuntu splits it out)
if [[ "$PKG_MGR" == "apt-get" ]]; then
    python3 -m venv --help &>/dev/null 2>&1 || $SUDO apt-get install -y -q python3-venv
fi

# git
command -v git &>/dev/null || pkg_install git

# curl (used later for Ollama)
command -v curl &>/dev/null || pkg_install curl

# Raspberry Pi: install additional system libs for cairosvg / yfinance
if [[ "$ARCH" == "arm"* ]] || [[ "$ARCH" == "aarch64" ]]; then
    log "Raspberry Pi detected — installing ARM build tools..."
    if [[ "$PKG_MGR" == "apt-get" ]]; then
        $SUDO apt-get install -y -q build-essential libssl-dev libffi-dev \
            python3-dev libcairo2 libglib2.0-0 2>/dev/null || true
    fi
fi

ok "System dependencies ready (python3: $(python3 --version 2>&1 | cut -d' ' -f2))"

# ── Step 2 — Clone / update repository ───────────────────────────────────────
hdr "2/8 Repository"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "Updating existing installation..."
    git -C "$INSTALL_DIR" fetch origin
    git -C "$INSTALL_DIR" reset --hard origin/main
    ok "Updated to latest"
else
    log "Cloning FredAI from GitHub..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    ok "Cloned to $INSTALL_DIR"
fi

# ── Step 3 — Python virtual environment ──────────────────────────────────────
hdr "3/8 Python environment"
log "Creating virtual environment..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip wheel setuptools -q

if [[ "$TIER" == "nano" || "$TIER" == "lite" ]]; then
    warn "Low-memory device — installing minimal dependencies"
    pip install -r "$INSTALL_DIR/requirements-lite.txt" -q
else
    pip install -r "$INSTALL_DIR/requirements.txt" -q
fi
ok "Python environment ready at $VENV_DIR"

# ── Step 4 — .env configuration ──────────────────────────────────────────────
hdr "4/8 Configuration"
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    warn ".env created from template — edit $INSTALL_DIR/.env to add API keys"
else
    ok ".env already exists — skipping"
fi

# Patch AI_PROVIDER and model based on tier
if [[ "$TIER" == "nano" || "$TIER" == "lite" ]]; then
    sed -i "s|^AI_PROVIDER=.*|AI_PROVIDER=auto|" "$INSTALL_DIR/.env" 2>/dev/null || true
    warn "Low-memory: Ollama skipped. Set ANTHROPIC_API_KEY in .env for AI features."
else
    sed -i "s|^OLLAMA_MODEL=.*|OLLAMA_MODEL=$OLLAMA_MODEL|" "$INSTALL_DIR/.env" 2>/dev/null || true
fi

# Random SECRET_KEY if still default
if grep -q "change_this_to_a_random_string" "$INSTALL_DIR/.env" 2>/dev/null; then
    NEW_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s|change_this_to_a_random_string|$NEW_KEY|" "$INSTALL_DIR/.env"
    ok "Generated random SECRET_KEY"
fi

# ── Step 5 — Data directories ─────────────────────────────────────────────────
hdr "5/8 Data directories"
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/logs" "$INSTALL_DIR/static/icons"
ok "Created data/ logs/ static/icons/"

# ── Step 6 — Ollama local AI ──────────────────────────────────────────────────
hdr "6/8 Ollama (local AI — free, no API cost)"

if [[ "$TIER" == "nano" ]]; then
    warn "Skipping Ollama — insufficient RAM (${RAM_MB}MB < 512MB)"
elif command -v ollama &>/dev/null; then
    ok "Ollama already installed ($(ollama --version 2>&1 | head -1))"
    # Ensure daemon running
    ollama serve &>/dev/null & sleep 2
    ollama pull "$OLLAMA_MODEL" 2>/dev/null && ok "Model $OLLAMA_MODEL ready" || warn "Model pull failed — run: ollama pull $OLLAMA_MODEL"
else
    log "Installing Ollama..."
    if curl -fsSL https://ollama.com/install.sh | sh; then
        ok "Ollama installed"
        ollama serve &>/dev/null & sleep 3
        log "Pulling AI model: $OLLAMA_MODEL (may take several minutes on first run)..."
        ollama pull "$OLLAMA_MODEL" && ok "Model $OLLAMA_MODEL ready" || warn "Pull failed — run: ollama pull $OLLAMA_MODEL"
        sed -i "s|^AI_PROVIDER=.*|AI_PROVIDER=auto|" "$INSTALL_DIR/.env" 2>/dev/null || true
    else
        warn "Ollama install failed — Fred will use Anthropic API if key is set"
    fi
fi

# ── Step 7 — System service ───────────────────────────────────────────────────
hdr "7/8 System service"

if [[ "$OS" == "Linux" ]] && command -v systemctl &>/dev/null; then
    cat > /tmp/fredai.service << SVCEOF
[Unit]
Description=FredAI Financial Intelligence Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python3 main.py
Restart=always
RestartSec=15
StandardOutput=append:$INSTALL_DIR/logs/fredai.log
StandardError=append:$INSTALL_DIR/logs/fredai.log
Environment=PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
SVCEOF
    $SUDO mv /tmp/fredai.service /etc/systemd/system/fredai.service
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable fredai
    ok "systemd service installed — FredAI will auto-start on boot"
elif [[ "$OS" == "Darwin" ]]; then
    PLIST="$HOME/Library/LaunchAgents/com.essentialbit.fredai.plist"
    cat > "$PLIST" << PLEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.essentialbit.fredai</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_DIR/bin/python3</string>
        <string>$INSTALL_DIR/main.py</string>
    </array>
    <key>WorkingDirectory</key><string>$INSTALL_DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$INSTALL_DIR/logs/fredai.log</string>
    <key>StandardErrorPath</key><string>$INSTALL_DIR/logs/fredai.log</string>
</dict>
</plist>
PLEOF
    launchctl load "$PLIST" 2>/dev/null || true
    ok "macOS LaunchAgent installed — FredAI auto-starts at login"
else
    warn "No init system detected — FredAI will start manually"
fi

# Desktop shortcut (Linux with desktop environment)
if [[ "$OS" == "Linux" ]] && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    mkdir -p "$HOME/.local/share/applications"
    ICON="$INSTALL_DIR/assets/icons/linux-256.png"
    [[ -f "$ICON" ]] || ICON="$INSTALL_DIR/assets/fredai-icon.svg"
    cat > "$HOME/.local/share/applications/fredai.desktop" << DSKEOF
[Desktop Entry]
Version=1.0
Name=FredAI
GenericName=Financial Intelligence Dashboard
Comment=AI-powered financial signals and portfolio tracking
Exec=bash -c "systemctl --user start fredai 2>/dev/null || (cd $INSTALL_DIR && $VENV_DIR/bin/python3 main.py &); sleep 3; xdg-open http://localhost:8080"
Icon=$ICON
Terminal=false
Type=Application
Categories=Finance;Office;
StartupWMClass=FredAI
DSKEOF
    ok "Desktop shortcut created"
fi

# ── Step 8 — Start ────────────────────────────────────────────────────────────
hdr "8/8 Launch"

# Start via systemd if available, else direct
if [[ "$OS" == "Linux" ]] && command -v systemctl &>/dev/null; then
    $SUDO systemctl start fredai
    ok "FredAI started via systemd"
elif [[ "$OS" == "Darwin" ]]; then
    launchctl start com.essentialbit.fredai 2>/dev/null || (
        cd "$INSTALL_DIR"
        source "$VENV_DIR/bin/activate"
        nohup python3 main.py >> logs/fredai.log 2>&1 &
        echo $! > fredai.pid
    )
    ok "FredAI started"
else
    cd "$INSTALL_DIR"
    source "$VENV_DIR/bin/activate"
    nohup python3 main.py >> logs/fredai.log 2>&1 &
    echo $! > "$INSTALL_DIR/fredai.pid"
    ok "FredAI started (PID: $!)"
fi

sleep 3

# Open browser
for opener in xdg-open gnome-open open; do
    command -v $opener &>/dev/null && { $opener "http://localhost:8080" &>/dev/null & break; } || true
done

# Final message
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || ipconfig getifaddr en0 2>/dev/null || echo "your-device-ip")
echo ""
echo -e "${G}════════════════════════════════════════════${NC}"
echo -e "${G}  FredAI is running!${NC}"
echo ""
echo -e "  Local:   ${C}http://localhost:8080${NC}"
echo -e "  Network: ${C}http://${LOCAL_IP}:8080${NC}"
echo ""
echo -e "  Login:   admin / sentinel2024"
echo -e "  Config:  ${Y}$INSTALL_DIR/.env${NC}"
echo -e "  Logs:    ${Y}$INSTALL_DIR/logs/fredai.log${NC}"
echo ""
echo -e "  For iOS/Android: open ${C}http://${LOCAL_IP}:8080${NC}"
echo -e "  in your browser and tap 'Add to Home Screen'"
echo -e "${G}════════════════════════════════════════════${NC}"
echo ""
echo -e "${Y}Next step: edit .env to add your API keys${NC}"
echo -e "  nano $INSTALL_DIR/.env"
