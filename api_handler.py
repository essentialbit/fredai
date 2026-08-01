import os
import json
import stat
from datetime import datetime

# Primary log dir — override via FREDAI_API_LOG_DIR for deployments that need
# a different location (Docker, Raspberry Pi, cloud VM); see CLAUDE.md's
# "every configurable value is an env var" convention.
PRIMARY_LOG_DIR = os.getenv("FREDAI_API_LOG_DIR", "/var/log/fredai")
PRIMARY_LOG_FILE = os.path.join(PRIMARY_LOG_DIR, "api_access.json")

# Local project fallback — used when the primary dir isn't writable (e.g. no
# root on a plain macOS/Linux install). Already covered by .gitignore's `logs/`.
LOCAL_FALLBACK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOCAL_FALLBACK_FILE = os.path.join(LOCAL_FALLBACK_DIR, "api_access.json")

_DIR_MODE = stat.S_IRWXU  # 0700 — owner-only
_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600 — owner-only

def _ensure_owner_only_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, mode=_DIR_MODE, exist_ok=True)
        try:
            os.chmod(path, _DIR_MODE)
        except OSError:
            pass  # e.g. pre-existing dir owned by a different user/process (ops-managed /var/log/fredai)

def _try_candidate(log_dir: str, log_file: str) -> str | None:
    try:
        _ensure_owner_only_dir(log_dir)
        is_new = not os.path.exists(log_file)
        with open(log_file, "a"):
            pass
        if is_new:
            try:
                os.chmod(log_file, _FILE_MODE)
            except OSError:
                pass
        return log_file
    except OSError:
        return None

def get_writable_log_file():
    """
    Returns the first writable log file path among the candidates,
    ensuring directories/files are created owner-only (0700/0600) so
    access-pattern metadata (which keys were saved/read/used, by which
    user id, when) isn't world-readable on shared/multi-tenant hosts.
    Never logs key material itself, only key names.
    """
    for log_dir, log_file in (
        (PRIMARY_LOG_DIR, PRIMARY_LOG_FILE),
        (LOCAL_FALLBACK_DIR, LOCAL_FALLBACK_FILE),
    ):
        result = _try_candidate(log_dir, log_file)
        if result:
            return result

    # Both candidates failed (e.g. read-only filesystem) — return the local
    # path anyway so callers get a consistent target; log_api_access's own
    # try/except degrades this to a no-op print rather than a crash.
    return LOCAL_FALLBACK_FILE

def log_api_access(api_key_name: str, access_type: str, error_code: int = 0, user_id=None):
    """
    Logs API access details to the JSON Lines log file.
    Fields:
      - timestamp: ISO 8601 UTC string
      - api_key_name: name of the key (e.g. 'anthropic_key', 'gemini_key')
      - access_type: action type (e.g. 'save', 'read', 'use', 'validate')
      - error_code: status code or 0 if successful
      - user_id: identifier of the user (if context is available)
    """
    log_file = get_writable_log_file()

    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "api_key_name": api_key_name,
        "access_type": access_type,
        "error_code": error_code,
        "user_id": user_id
    }

    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except OSError as e:
        print(f"[api_handler] Failed to log API access: {e}")
