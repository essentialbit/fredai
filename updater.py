#!/usr/bin/env python3
"""
FredAI Auto-Updater
Polls GitHub for new commits on main and applies them via git pull.
Emits 'update_available' WebSocket event when behind; applies on demand or auto.

AUTO_UPDATE env var:
  "notify"  — emit WS event, user triggers update (default)
  "auto"    — pull + restart automatically when behind
  "off"     — disabled
"""

import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
GITHUB_REMOTE = "origin"
BRANCH = "main"
GITHUB_API_URL = "https://api.github.com/repos/essentialbit/fredai/commits/main"

_update_lock = threading.Lock()
_last_remote_sha: str = ""
_last_check: datetime | None = None
_socketio = None  # injected by main.py


def init(socketio_instance) -> None:
    global _socketio
    _socketio = socketio_instance


def _local_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_DIR), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _remote_sha() -> str:
    """Fetch latest commit SHA from GitHub API (no auth needed for public repo)."""
    try:
        import urllib.request, json
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"User-Agent": "FredAI-Updater/1.0", "Accept": "application/vnd.github.v3+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            return data.get("sha", "")
    except Exception:
        return ""


def _git_pull() -> tuple[bool, str]:
    """Run git fetch + reset --hard to update. Returns (success, message)."""
    try:
        subprocess.run(
            ["git", "-C", str(REPO_DIR), "fetch", GITHUB_REMOTE, BRANCH],
            capture_output=True, timeout=60, check=True,
        )
        subprocess.run(
            ["git", "-C", str(REPO_DIR), "reset", "--hard", f"{GITHUB_REMOTE}/{BRANCH}"],
            capture_output=True, timeout=30, check=True,
        )
        # Re-install any new deps
        venv_pip = REPO_DIR / ".venv" / "bin" / "pip"
        if not venv_pip.exists():
            venv_pip = REPO_DIR / "venv" / "bin" / "pip"
        if venv_pip.exists():
            req_file = REPO_DIR / "requirements.txt"
            if req_file.exists():
                subprocess.run(
                    [str(venv_pip), "install", "-q", "-r", str(req_file)],
                    capture_output=True, timeout=120,
                )
        return True, "Updated successfully"
    except subprocess.CalledProcessError as e:
        return False, f"git error: {e.stderr.decode(errors='ignore').strip()}"
    except Exception as e:
        return False, str(e)


def _get_changelog(old_sha: str, new_sha: str) -> list[str]:
    """Return commit messages between two SHAs."""
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_DIR), "log",
             "--oneline", f"{old_sha}..{new_sha}"],
            capture_output=True, text=True, timeout=10,
        )
        lines = result.stdout.strip().splitlines()
        return lines[:10]  # max 10 commits shown
    except Exception:
        return []


def check_for_updates(emit_event: bool = True) -> dict:
    """
    Compare local HEAD to GitHub main.
    Returns dict: {status, local_sha, remote_sha, behind, changelog}
    Emits 'update_available' WS event if behind and emit_event=True.
    """
    global _last_remote_sha, _last_check

    local = _local_sha()
    remote = _remote_sha()
    _last_check = datetime.now(timezone.utc)

    if not remote:
        return {"status": "check_failed", "local_sha": local, "remote_sha": "", "behind": False, "changelog": []}

    _last_remote_sha = remote
    behind = bool(remote and local and remote != local)

    changelog = _get_changelog(local, remote) if behind else []

    result = {
        "status": "behind" if behind else "up_to_date",
        "local_sha": local,
        "remote_sha": remote,
        "behind": behind,
        "changelog": changelog,
        "checked_at": _last_check.isoformat(),
    }

    if behind and emit_event and _socketio:
        _socketio.emit("update_available", {
            "message": f"FredAI update available ({len(changelog)} new commit{'s' if len(changelog) != 1 else ''})",
            "changelog": changelog[:5],
            "remote_sha": remote[:8],
        })
        print(f"[Updater] Behind by {len(changelog)} commits. Notified via WebSocket.")

    # Auto-update mode
    auto = os.getenv("AUTO_UPDATE", "notify").lower()
    if behind and auto == "auto":
        with _update_lock:
            ok, msg = _git_pull()
            result["auto_updated"] = ok
            result["update_message"] = msg
            if ok and _socketio:
                _socketio.emit("alert", {
                    "title": "FredAI Updated",
                    "message": f"Auto-updated to {remote[:8]}. Restart recommended.",
                    "level": "info",
                })
            print(f"[Updater] Auto-update: {msg}")

    return result


def apply_update() -> dict:
    """Manually trigger a pull. Called from /api/update route."""
    with _update_lock:
        local_before = _local_sha()
        ok, msg = _git_pull()
        local_after = _local_sha()
        return {
            "success": ok,
            "message": msg,
            "sha_before": local_before,
            "sha_after": local_after,
            "updated": local_before != local_after,
        }


def status() -> dict:
    return {
        "local_sha": _local_sha(),
        "last_remote_sha": _last_remote_sha,
        "last_check": _last_check.isoformat() if _last_check else None,
        "auto_update_mode": os.getenv("AUTO_UPDATE", "notify"),
        "repo_dir": str(REPO_DIR),
    }
