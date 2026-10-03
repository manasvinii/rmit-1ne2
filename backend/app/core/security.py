"""Password hashing, session tokens, Canvas-token encryption, signed media URLs, log redaction."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- secrets


def _dev_secret(name: str, factory) -> str:
    """Development-only fallback: generate once and persist next to the local DB (gitignored)."""
    settings = get_settings()
    if settings.env == "production":
        raise RuntimeError(f"{name} must be set in the environment in production")
    path = Path(settings.sqlite_path).parent / "dev_secrets.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else {}
    if name not in data:
        data[name] = factory()
        path.write_text(json.dumps(data))
        path.chmod(0o600)
        log.warning("%s not set; generated a development secret in %s", name, path)
    return data[name]


@lru_cache
def _jwt_secret() -> str:
    return get_settings().jwt_secret or _dev_secret("JWT_SECRET", lambda: secrets.token_urlsafe(48))


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().fernet_key or _dev_secret(
        "FERNET_KEY", lambda: Fernet.generate_key().decode()
    )
    return Fernet(key.encode())


# --------------------------------------------------------------------------- passwords

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def is_password_hash(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(_BCRYPT_PREFIXES)


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored or not is_password_hash(stored):
        return False
    try:
        return bcrypt.checkpw(password.encode(), stored.encode())
    except ValueError:
        return False


def verify_legacy_plaintext(password: str, stored: Optional[str]) -> bool:
    """Legacy rows stored plaintext passwords. Used once to migrate them to bcrypt on login."""
    return bool(stored) and not is_password_hash(stored) and hmac.compare_digest(password, stored)


# --------------------------------------------------------------------------- sessions


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=get_settings().jwt_ttl_minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    return payload.get("sub")


# --------------------------------------------------------------------------- Canvas token at rest

_ENC_PREFIX = "enc:v1:"


def encrypt_secret(value: str) -> str:
    return _ENC_PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    """Decrypts tokens; legacy plaintext values are returned as-is so they can be re-encrypted."""
    if not value:
        return None
    if not value.startswith(_ENC_PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(_ENC_PREFIX) :].encode()).decode()
    except InvalidToken:
        log.error("Stored Canvas token could not be decrypted (wrong FERNET_KEY?)")
        return None


def is_encrypted(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(_ENC_PREFIX)


# --------------------------------------------------------------------------- signed media URLs


def sign_resource_url(user_id: str, resource_id: str, ttl: Optional[int] = None) -> tuple[int, str]:
    exp = int(time.time()) + (ttl or get_settings().signed_url_ttl_seconds)
    msg = f"{user_id}|{resource_id}|{exp}".encode()
    sig = hmac.new(_jwt_secret().encode(), msg, hashlib.sha256).digest()
    return exp, base64.urlsafe_b64encode(sig).decode().rstrip("=")


def verify_resource_signature(user_id: str, resource_id: str, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    msg = f"{user_id}|{resource_id}|{exp}".encode()
    expected = base64.urlsafe_b64encode(
        hmac.new(_jwt_secret().encode(), msg, hashlib.sha256).digest()
    ).decode().rstrip("=")
    return hmac.compare_digest(expected, sig)


# --------------------------------------------------------------------------- log redaction

_REDACTIONS = [
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.I), r"\1[REDACTED]"),
    (re.compile(r"\b\d{4,6}~[A-Za-z0-9]{20,}\b"), "[REDACTED_CANVAS_TOKEN]"),  # Canvas token shape
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "[REDACTED_JWT]"),
    (re.compile(r"(\"?(?:api_token|password|access_token|token)\"?\s*[:=]\s*)\"?[^\s\",}]+", re.I),
     r"\1[REDACTED]"),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        record.msg, record.args = redact(msg), ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in root.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
