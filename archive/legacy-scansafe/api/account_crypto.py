"""Secrets for saved accounts: the phone hash, encryption of linked-account tokens, and short
signed tokens (OAuth state, the Dogwood app link).

Env (never commit values, never log them):
  ACCOUNT_PEPPER  mixed into every phone hash. If it isn't set, one is generated on first use
                  and kept in ACCOUNT_PEPPER_FILE (default ~/.scansafe-account-pepper, chmod 600).
                  Never change it once accounts exist: every saved account is keyed by it.
                  The signing keys below are derived from it too.
  ACCOUNT_KEY     Fernet key that encrypts linked-account tokens at rest. Required for linking
                  and for paying with a virtual card (it reads the Dogwood token). Generate one with
                  python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from typing import Optional

from api import config  # noqa: F401  (loads .env)

log = logging.getLogger("scansafe.accounts")

_lock = threading.Lock()
_pepper_cache: Optional[str] = None


class AccountConfigError(Exception):
    """A server setting is missing; the route answers 503 with this code and message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def pepper_file() -> str:
    return os.getenv("ACCOUNT_PEPPER_FILE", os.path.expanduser("~/.scansafe-account-pepper"))


def pepper() -> str:
    """ACCOUNT_PEPPER, else the one saved in ACCOUNT_PEPPER_FILE, else a new one saved there."""
    global _pepper_cache
    env = os.getenv("ACCOUNT_PEPPER", "").strip()
    if env:
        return env
    with _lock:
        if _pepper_cache:
            return _pepper_cache
        path = pepper_file()
        try:
            with open(path) as f:
                value = f.read().strip()
        except OSError:
            value = ""
        if not value:
            value = secrets.token_urlsafe(32)
            tmp = path + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(value + "\n")
            os.replace(tmp, path)
            log.warning("ACCOUNT_PEPPER was not set: generated one and saved it in %s "
                        "(keep that file; copy it into .env to pin it)", path)
        _pepper_cache = value
        return value


def reset_cache() -> None:  # tests
    global _pepper_cache
    with _lock:
        _pepper_cache = None


def phone_hash(phone: str) -> str:
    """sha256 of the E.164 number followed by the server pepper (hex). Accounts are keyed by it."""
    return hashlib.sha256((phone + pepper()).encode()).hexdigest()


def _subkey(label: str) -> bytes:
    return hmac.new(pepper().encode(), b"scansafe:" + label.encode(), hashlib.sha256).digest()


def derived_secret(label: str) -> str:
    """A stable server-side secret for `label` (e.g. the Dogwood demo client secret)."""
    return base64.urlsafe_b64encode(_subkey("secret:" + label)).decode().rstrip("=")


# --- encryption at rest ----------------------------------------------------------------------

def _fernet():
    raw = os.getenv("ACCOUNT_KEY", "").strip()
    if not raw:
        raise AccountConfigError("accounts_not_configured",
                                 "Saved accounts can't store linked accounts yet: the server needs ACCOUNT_KEY.")
    try:
        from cryptography.fernet import Fernet
        return Fernet(raw.encode())
    except ImportError:
        raise AccountConfigError("accounts_not_configured",
                                 "The server is missing the cryptography package.") from None
    except (ValueError, TypeError):
        raise AccountConfigError("accounts_not_configured",
                                 "ACCOUNT_KEY on the server is not a valid Fernet key.") from None


def can_encrypt() -> bool:
    try:
        _fernet()
        return True
    except AccountConfigError:
        return False


def encrypt(secret: dict) -> str:
    """Fernet ciphertext (text) of a small JSON object. Raises AccountConfigError."""
    return _fernet().encrypt(json.dumps(secret, separators=(",", ":")).encode()).decode()


def decrypt(token: str) -> Optional[dict]:
    """The JSON object back, or None if it can't be decrypted (wrong key, empty, tampered)."""
    if not token:
        return None
    try:
        from cryptography.fernet import InvalidToken
        f = _fernet()
        return json.loads(f.decrypt(token.encode()))
    except AccountConfigError:
        raise
    except (InvalidToken, ValueError, TypeError):
        return None


# --- short signed tokens ---------------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(purpose: str, payload: dict, ttl_s: int) -> str:
    """`<base64url JSON>.<base64url HMAC>`, valid for ttl_s seconds, only for `purpose`."""
    body = {**payload, "p": purpose, "exp": int(time.time()) + int(ttl_s)}
    raw = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(_subkey("sign:" + purpose), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{sig}"


def verify(purpose: str, token: str) -> tuple[Optional[dict], str]:
    """(payload, "") if the token is genuine, for `purpose` and unexpired; else (None, reason)
    with reason "invalid" or "expired"."""
    if not token or len(token) > 2048 or token.count(".") != 1:
        return None, "invalid"
    raw, sig = token.split(".")
    want = _b64(hmac.new(_subkey("sign:" + purpose), raw.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, want):
        return None, "invalid"
    try:
        body = json.loads(_unb64(raw))
    except (ValueError, TypeError):
        return None, "invalid"
    if not isinstance(body, dict) or body.get("p") != purpose:
        return None, "invalid"
    if not isinstance(body.get("exp"), int) or body["exp"] < time.time():
        return None, "expired"
    return body, ""
