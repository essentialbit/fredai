"""
FredAI Credential Encryption
=============================
Encrypts secrets before they're stored in the users.preferences JSON blob
(OAuth tokens, user-supplied API keys) — previously stored in plaintext,
readable by anyone with read access to data/sentinel.db.

The Fernet key is derived deterministically from SECRET_KEY via SHA-256, so
no separate key needs to be generated, stored, or rotated independently —
rotating SECRET_KEY also rotates this key (and invalidates previously
encrypted values, same as it already invalidates sessions).
"""

import base64
import hashlib
from cryptography.fernet import Fernet
from config import SECRET_KEY


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str | None:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except Exception:
        return None
