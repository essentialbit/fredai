#!/usr/bin/env python3
"""
FredAI Universal Python Setup
Runs after Python is available on any platform.
Called by install.sh, install.ps1, and directly by users.

Usage:
    python3 deploy/setup.py                   # full install
    python3 deploy/setup.py --update          # update only
    python3 deploy/setup.py --lite            # skip heavy deps
    python3 deploy/setup.py --no-ollama       # skip Ollama install
    python3 deploy/setup.py --dry-run         # show what would happen
"""
import argparse
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT     = Path(__file__).parent.parent.resolve()
VENV     = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
ENV_TMPL = ROOT / ".env.example"
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"

OS   = platform.system()   # Windows / Linux / Darwin
ARCH = platform.machine()  # x86_64 / arm64 / aarch64 / armv7l
RAM_MB = 4096
try:
    import psutil
    RAM_MB = psutil.virtual_memory().total // 1024 // 1024
except ImportError:
    pass


# ── Colour helpers ────────────────────────────────────────────────────────────
def c(colour, text):
    codes = {"G": "\033[32m", "Y": "\033[33m", "R": "\033[31m", "C": "\033[36m", "B": "\033[34m", "X": "\033[0m"}
    if OS == "Windows" and not supports_color():
        return text
    return f"{codes[colour]}{text}{codes['X']}"

def supports_color():
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def log(msg):  print(c("C", "[FredAI] ") + msg)
def ok(msg):   print(c("G", "  ✓  ") + msg)
def warn(msg): print(c("Y", "  !  ") + msg)
def err(msg):  print(c("R", "  ✗  ") + msg); sys.exit(1)


# ── Capability detection ──────────────────────────────────────────────────────
def get_tier():
    if RAM_MB < 512:   return "nano"
    if RAM_MB < 1024:  return "lite"
    if RAM_MB < 4096:  return "standard"
    return "full"

def get_ollama_model(tier):
    return {"nano": None, "lite": "phi3:mini", "standard": "llama3.2", "full": "llama3.2"}[tier]

def is_raspberry_pi():
    try:
        return "Raspberry" in Path("/proc/device-tree/model").read_text()
    except Exception:
        return ARCH.startswith("arm") or ARCH == "aarch64"

def python_ok():
    v = sys.version_info
    return (v.major, v.minor) >= (3, 8)


# ── venv + pip ────────────────────────────────────────────────────────────────
def setup_venv(tier: str, dry: bool):
    log("Setting up Python virtual environment...")
    if not dry:
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)

    pip = VENV / ("Scripts" if OS == "Windows" else "bin") / ("pip" + (".exe" if OS == "Windows" else ""))
    req = ROOT / ("requirements-lite.txt" if tier in ("nano", "lite") else "requirements.txt")

    if not dry:
        subprocess.run([str(pip), "install", "--upgrade", "pip", "wheel", "setuptools", "-q"], check=True)
        subprocess.run([str(pip), "install", "-r", str(req), "-q"], check=True)
    ok(f"Virtual environment ready ({req.name})")
    return pip


# ── .env ─────────────────────────────────────────────────────────────────────
def setup_env(tier: str, ollama_model: str | None, dry: bool):
    if not dry and not ENV_FILE.exists():
        shutil.copy(ENV_TMPL, ENV_FILE)
        warn(f".env created — edit {ENV_FILE} to add API keys")

    if dry:
        ok(".env would be created from .env.example")
        return

    content = ENV_FILE.read_text()

    # Random SECRET_KEY
    if "change_this_to_a_random_string" in content:
        content = content.replace("change_this_to_a_random_string", secrets.token_hex(32))
        ok("Generated random SECRET_KEY")

    # Set Ollama model
    if ollama_model:
        content = re.sub(r"(?m)^OLLAMA_MODEL=.*", f"OLLAMA_MODEL={ollama_model}", content)
        ok(f"Set OLLAMA_MODEL={ollama_model}")
    elif tier in ("nano", "lite"):
        content = re.sub(r"(?m)^AI_PROVIDER=.*", "AI_PROVIDER=auto", content)
        warn("Low-memory device: AI_PROVIDER=auto (Anthropic API if key set, else degraded)")

    ENV_FILE.write_text(content)
    ok(".env configured")


# ── Ollama ────────────────────────────────────────────────────────────────────
def check_ollama():
    return shutil.which("ollama") is not None

def start_ollama_daemon():
    if OS == "Windows":
        subprocess.Popen(["ollama", "serve"], creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def pull_ollama_model(model: str, dry: bool):
    log(f"Pulling AI model: {model} (this may take several minutes)...")
    if dry:
        ok(f"Would pull: {model}")
        return True
    try:
        start_ollama_daemon()
        import time; time.sleep(3)
        result = subprocess.run(["ollama", "pull", model], timeout=600)
        if result.returncode == 0:
            ok(f"Model {model} ready")
            return True
        else:
            warn(f"Pull failed — run manually: ollama pull {model}")
            return False
    except subprocess.TimeoutExpired:
        warn("Model pull timed out — run manually: ollama pull " + model)
        return False
    except Exception as e:
        warn(f"Ollama error: {e}")
        return False

def install_ollama_guide(tier: str):
    warn("Ollama not found. For free local AI (no API cost):")
    if OS == "Darwin":
        warn("  brew install ollama  OR  https://ollama.com/download/mac")
    elif OS == "Windows":
        warn("  Download: https://ollama.com/download/windows")
    elif OS == "Linux":
        warn("  curl -fsSL https://ollama.com/install.sh | sh")
    model = get_ollama_model(tier)
    if model:
        warn(f"  Then: ollama pull {model}")
    warn("Alternatively, set ANTHROPIC_API_KEY in .env")


# ── systemd service ───────────────────────────────────────────────────────────
def install_service_linux(dry: bool):
    if OS != "Linux":
        return
    if not shutil.which("systemctl"):
        return

    py_bin = VENV / "bin" / "python3"
    service = f"""[Unit]
Description=FredAI Financial Intelligence Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={os.getenv('USER', 'pi')}
WorkingDirectory={ROOT}
ExecStart={py_bin} main.py
Restart=always
RestartSec=15
StandardOutput=append:{LOGS_DIR}/fredai.log
StandardError=append:{LOGS_DIR}/fredai.log

[Install]
WantedBy=multi-user.target
"""
    svc_path = Path("/etc/systemd/system/fredai.service")
    if not dry:
        try:
            svc_path.write_text(service)
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "enable", "fredai"], check=True)
            ok("systemd service enabled (auto-starts at boot)")
        except PermissionError:
            # Write to tmp and prompt sudo
            tmp = Path("/tmp/fredai.service")
            tmp.write_text(service)
            warn(f"Run to install service: sudo mv /tmp/fredai.service {svc_path} && sudo systemctl daemon-reload && sudo systemctl enable fredai")
    else:
        ok("Would install systemd service")


# ── Print network access info ─────────────────────────────────────────────────
def print_final_message(port=8080):
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "your-device-ip"

    print("\n" + c("G", "=" * 46))
    print(c("G", "  FredAI is ready!"))
    print()
    print(f"  Local:   {c('C', f'http://localhost:{port}')}")
    print(f"  Network: {c('C', f'http://{local_ip}:{port}')}")
    print()
    print("  Default login: admin / sentinel2024")
    print(f"  Config:  {c('Y', str(ENV_FILE))}")
    print(f"  Logs:    {c('Y', str(LOGS_DIR / 'fredai.log'))}")
    print()
    print(f"  iOS/Android: open {c('C', f'http://{local_ip}:{port}')} in browser")
    print("               then tap 'Add to Home Screen' for app experience")
    print(c("G", "=" * 46))
    print()
    print(c("Y", "NEXT: edit .env to add your API keys"))
    print(f"  nano {ENV_FILE}" if OS != "Windows" else f"  notepad {ENV_FILE}")
    print()


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="FredAI Setup")
    parser.add_argument("--update",    action="store_true", help="Update only (skip service reinstall)")
    parser.add_argument("--lite",      action="store_true", help="Force lite dependencies")
    parser.add_argument("--no-ollama", action="store_true", help="Skip Ollama setup")
    parser.add_argument("--dry-run",   action="store_true", help="Show what would be done without doing it")
    args = parser.parse_args()

    dry = args.dry_run
    if dry:
        log("DRY RUN — no changes will be made")

    if not python_ok():
        err(f"Python 3.8+ required (found {sys.version}). Download: https://python.org")

    tier = "lite" if args.lite else get_tier()
    ollama_model = None if (args.no_ollama or tier == "nano") else get_ollama_model(tier)

    log(f"Platform: {OS} / {ARCH} | RAM: {RAM_MB}MB | Tier: {tier}")
    if is_raspberry_pi():
        log("Raspberry Pi detected")

    # Directories
    if not dry:
        DATA_DIR.mkdir(exist_ok=True)
        LOGS_DIR.mkdir(exist_ok=True)
        (ROOT / "static" / "icons").mkdir(parents=True, exist_ok=True)
    ok("Directories ready")

    # venv + pip
    setup_venv(tier, dry)

    # .env
    setup_env(tier, ollama_model, dry)

    # Ollama
    if not args.no_ollama and tier not in ("nano",):
        if check_ollama():
            ok("Ollama found")
            if ollama_model:
                pull_ollama_model(ollama_model, dry)
        else:
            install_ollama_guide(tier)

    # Service (Linux)
    if not args.update:
        install_service_linux(dry)

    if not dry:
        print_final_message()
    else:
        ok("Dry run complete — no changes made")


if __name__ == "__main__":
    main()
