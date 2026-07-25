"""
Host-aware dynamic port allocation.

Servers call `find_free_port(preferred)` at startup instead of binding
`preferred` blindly. If it's taken (by another instance, another app, or a
stale process), the next free port is found and persisted to a small JSON
state file. Anything that needs to know "what port is FredAI actually on
right now" (installer-generated shortcuts, the updater's health check, the
/api/install route) reads that state file instead of assuming the
configured default is what's actually bound.
"""

import json
import socket
from pathlib import Path

RUNTIME_PORT_FILE = Path(__file__).resolve().parent / "data" / ".runtime_port.json"


def _is_free(port: int, host: str) -> bool:
    # Check both address families — a port can look "free" on IPv4 while an
    # IPv6 listener (or vice versa) is already sitting on it, which produces
    # two unrelated servers silently sharing one port number instead of a
    # clean bind failure.
    for family, bind_host in ((socket.AF_INET, host), (socket.AF_INET6, "::")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((bind_host, port))
        except OSError:
            return False
    return True


def find_free_port(preferred: int, host: str = "0.0.0.0", max_scan: int = 50) -> int:
    """Return `preferred` if it's free, else the nearest free port above it."""
    if _is_free(preferred, host):
        return preferred
    for candidate in range(preferred + 1, min(preferred + 1 + max_scan, 65536)):
        if _is_free(candidate, host):
            return candidate
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def write_runtime_port(port: int, state_path: Path = RUNTIME_PORT_FILE) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"port": port}))


def current_port(default: int, state_path: Path = RUNTIME_PORT_FILE) -> int:
    """What port is the server actually bound to right now, per its own state file."""
    try:
        return int(json.loads(state_path.read_text())["port"])
    except Exception:
        return default
