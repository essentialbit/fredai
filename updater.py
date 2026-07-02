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
import sys
import threading
import time
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


def _venv_pip() -> Path | None:
    for candidate in (REPO_DIR / ".venv" / "bin" / "pip", REPO_DIR / "venv" / "bin" / "pip"):
        if candidate.exists():
            return candidate
    return None


def _venv_python() -> str:
    for candidate in (REPO_DIR / ".venv" / "bin" / "python3", REPO_DIR / "venv" / "bin" / "python3"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _install_deps() -> None:
    venv_pip = _venv_pip()
    if venv_pip:
        req_file = REPO_DIR / "requirements.txt"
        if req_file.exists():
            subprocess.run(
                [str(venv_pip), "install", "-q", "-r", str(req_file)],
                capture_output=True, timeout=120,
            )


def _stash_if_dirty() -> bool:
    """Stash uncommitted local changes before a hard reset instead of letting
    reset --hard silently discard them."""
    status = subprocess.run(
        ["git", "-C", str(REPO_DIR), "status", "--porcelain"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    if not status:
        return False
    subprocess.run(
        ["git", "-C", str(REPO_DIR), "stash", "push", "-u", "-m",
         f"pre-update-backup {datetime.now(timezone.utc).isoformat()}"],
        capture_output=True, timeout=15,
    )
    return True


def _git_pull() -> tuple[bool, str]:
    """Run git fetch + reset --hard to update. Returns (success, message)."""
    try:
        stashed = _stash_if_dirty()
        subprocess.run(
            ["git", "-C", str(REPO_DIR), "fetch", GITHUB_REMOTE, BRANCH],
            capture_output=True, timeout=60, check=True,
        )
        subprocess.run(
            ["git", "-C", str(REPO_DIR), "reset", "--hard", f"{GITHUB_REMOTE}/{BRANCH}"],
            capture_output=True, timeout=30, check=True,
        )
        _install_deps()
        msg = "Updated successfully" + (" (local changes stashed as pre-update-backup)" if stashed else "")
        return True, msg
    except subprocess.CalledProcessError as e:
        return False, f"git error: {e.stderr.decode(errors='ignore').strip()}"
    except Exception as e:
        return False, str(e)


def _import_smoke_test() -> tuple[bool, str]:
    """Run the same import check CI uses, against whatever is on disk right
    now — catches a broken pull (syntax/import errors) before it ever touches
    the live process."""
    try:
        result = subprocess.run(
            [_venv_python(), "-c", "from main import app"],
            capture_output=True, text=True, timeout=30, cwd=str(REPO_DIR),
        )
        if result.returncode == 0:
            return True, "OK"
        return False, (result.stderr or result.stdout).strip()[-500:]
    except Exception as e:
        return False, str(e)


def rollback(backup_sha: str) -> tuple[bool, str]:
    """Reset back to a known-good SHA and reinstall its deps. Used when a
    pulled update fails its import check — the live process is never
    restarted onto known-bad code."""
    try:
        subprocess.run(
            ["git", "-C", str(REPO_DIR), "reset", "--hard", backup_sha],
            capture_output=True, timeout=30, check=True,
        )
        _install_deps()
        return True, f"Rolled back to {backup_sha[:8]}"
    except subprocess.CalledProcessError as e:
        return False, f"Rollback git error: {e.stderr.decode(errors='ignore').strip()}"
    except Exception as e:
        return False, str(e)


def _health_check(port: int, retries: int = 10, delay: float = 1.0) -> bool:
    import urllib.request
    for _ in range(retries):
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def trigger_restart() -> bool:
    """Spawn a detached replacement process and exit this one. Only ever
    called after _import_smoke_test() has passed on the new code, so a
    broken pull can no longer take the running instance down with it."""
    try:
        # Spawn a helper python subprocess that sleeps and then launches main.py
        # in its own session, avoiding a direct shell=True invocation.
        cmd = [
            sys.executable,
            "-c",
            f"import time, subprocess, sys; time.sleep(1.2); subprocess.Popen([sys.executable, 'main.py'], start_new_session=True)"
        ]
        subprocess.Popen(cmd, cwd=str(REPO_DIR), env=os.environ, start_new_session=True)
        threading.Timer(0.8, lambda: os._exit(0)).start()
        return True
    except Exception as e:
        print(f"[Updater] Restart trigger failed: {e}")
        return False


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
        update_result = _safe_pull_and_restart(restart=True)
        result.update(update_result)
        result["auto_updated"] = update_result["success"]
        if update_result["success"] and _socketio:
            _socketio.emit("alert", {
                "title": "FredAI Updated",
                "message": f"Auto-updated to {remote[:8]}. Restarting now...",
                "level": "info",
            })
        elif update_result.get("rolled_back") and _socketio:
            _socketio.emit("alert", {
                "title": "FredAI Auto-Update Failed",
                "message": f"Pulled update failed validation and was rolled back: {update_result.get('message','')}",
                "level": "warning",
            })

    return result


def _safe_pull_and_restart(restart: bool) -> dict:
    """Pull, verify the new code actually imports, roll back if it doesn't,
    and only then (optionally) restart. Must be called with _update_lock held."""
    local_before = _local_sha()
    ok, msg = _git_pull()
    local_after = _local_sha()
    result = {
        "success": ok,
        "message": msg,
        "sha_before": local_before,
        "sha_after": local_after,
        "updated": local_before != local_after,
    }
    if not ok or local_before == local_after:
        return result

    healthy, check_msg = _import_smoke_test()
    result["import_check"] = check_msg
    if not healthy:
        rolled_back, rb_msg = rollback(local_before)
        result["success"] = False
        result["rolled_back"] = rolled_back
        result["rollback_message"] = rb_msg
        result["message"] = f"Pulled update failed import check, rolled back: {check_msg}"
        return result

    if restart:
        result["restart_triggered"] = trigger_restart()
    return result


def apply_update(restart: bool = True) -> dict:
    """Manually trigger a pull. Called from /api/update route."""
    with _update_lock:
        return _safe_pull_and_restart(restart=restart)


def status() -> dict:
    from config import PORT
    return {
        "local_sha": _local_sha(),
        "last_remote_sha": _last_remote_sha,
        "last_check": _last_check.isoformat() if _last_check else None,
        "auto_update_mode": os.getenv("AUTO_UPDATE", "notify"),
        "repo_dir": str(REPO_DIR),
        "reachable": _health_check(PORT, retries=1, delay=0),
    }
