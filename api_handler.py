import os
import json
from datetime import datetime

# Primary log file path
PRIMARY_LOG_DIR = "/var/log/fredai"
PRIMARY_LOG_FILE = os.path.join(PRIMARY_LOG_DIR, "api_access.json")

# Fallback path inside the shared cockpit or current working directory
FALLBACK_LOG_DIR = "/Volumes/Iron 1TBSSD/Shared/Co-Agent Çockpit"
FALLBACK_LOG_FILE = os.path.join(FALLBACK_LOG_DIR, "api_access.json")

# Project local fallback path
LOCAL_FALLBACK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOCAL_FALLBACK_FILE = os.path.join(LOCAL_FALLBACK_DIR, "api_access.json")

def get_writable_log_file():
    """
    Returns the first writable log file path among the candidates,
    ensuring directories are created.
    """
    # 1. Try primary path
    try:
        if not os.path.exists(PRIMARY_LOG_DIR):
            os.makedirs(PRIMARY_LOG_DIR, exist_ok=True)
        # Test write access
        with open(PRIMARY_LOG_FILE, "a") as f:
            pass
        return PRIMARY_LOG_FILE
    except Exception:
        pass

    # 2. Try shared cockpit fallback
    try:
        if not os.path.exists(FALLBACK_LOG_DIR):
            os.makedirs(FALLBACK_LOG_DIR, exist_ok=True)
        with open(FALLBACK_LOG_FILE, "a") as f:
            pass
        return FALLBACK_LOG_FILE
    except Exception:
        pass

    # 3. Try local fallback
    try:
        if not os.path.exists(LOCAL_FALLBACK_DIR):
            os.makedirs(LOCAL_FALLBACK_DIR, exist_ok=True)
        with open(LOCAL_FALLBACK_FILE, "a") as f:
            pass
        return LOCAL_FALLBACK_FILE
    except Exception:
        pass

    # Default to local fallback path regardless
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
    except Exception as e:
        print(f"[api_handler] Failed to log API access: {e}")
