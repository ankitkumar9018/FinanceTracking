"""Security utilities: JWT tokens, password hashing, encryption, 2FA."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

# Monkey-patch for passlib + bcrypt 5.0 compatibility (must be before passlib import)
import bcrypt
if not hasattr(bcrypt, "__about__"):
    class _About:
        __version__ = getattr(bcrypt, "__version__", "5.0.0")
    bcrypt.__about__ = _About()

import pyotp
from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

logger = logging.getLogger(__name__)

# ── Password Hashing ─────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT Tokens ───────────────────────────────────────────────────────────────
ALGORITHM = "HS256"


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def create_refresh_token(data: dict[str, Any]) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT token. Returns payload or None if invalid."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# ── Fernet Encryption (for API keys, secrets stored in DB) ───────────────────
_fernet_instance: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        key = settings.fernet_key
        if not key:
            logger.warning(
                "FERNET_KEY not set — generating ephemeral key. "
                "Encrypted data will be lost on restart. "
                "Set FERNET_KEY in .env for persistence."
            )
            key = Fernet.generate_key().decode()
        if isinstance(key, str):
            key = key.encode()
        _fernet_instance = Fernet(key)
    return _fernet_instance


def encrypt_value(value: str) -> str:
    """Encrypt a string value (e.g., API key) for database storage."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(encrypted_value: str) -> str:
    """Decrypt a stored encrypted value."""
    return _get_fernet().decrypt(encrypted_value.encode()).decode()


# ── TOTP / 2FA ────────────────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    """Generate a new TOTP secret for 2FA setup."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str, issuer: str = "FinanceTracker") -> str:
    """Generate an otpauth:// URI for QR code generation."""
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code against a secret."""
    totp = pyotp.totp.TOTP(secret)
    return totp.verify(code, valid_window=1)
