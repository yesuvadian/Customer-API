"""
Symmetric encryption for secrets stored at rest (SMTP passwords, SMS API
keys, etc.) — Fernet (AES-128-CBC + HMAC), keyed by INTEGRATION_SECRET_KEY.

No other credential-encryption pattern exists in this codebase (user
passwords are one-way bcrypt hashes, which can't be reversed to send an
email) — this is the first, and is scoped generically so any future
DB-stored secret can reuse it rather than growing its own scheme.
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

_KEY_ENV = "INTEGRATION_SECRET_KEY"


def _fernet() -> Fernet:
    raw = os.getenv(_KEY_ENV)
    if not raw:
        raise RuntimeError(
            f"{_KEY_ENV} is not set — required to encrypt/decrypt stored "
            f"integration credentials (SMTP/SMS). Generate one with: "
            f"python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    # Accept either a proper Fernet key (32 url-safe base64 bytes) or an
    # arbitrary passphrase — derive a valid key from the latter so ops
    # doesn't need to hand-generate a Fernet key specifically.
    try:
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except (ValueError, TypeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
        return Fernet(derived)


def encrypt_secret(plaintext: str | None) -> str | None:
    """Encrypt a secret for storage. None/empty passes through as None."""
    if not plaintext:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str | None) -> str | None:
    """Decrypt a stored secret. Returns None if empty or undecryptable
    (e.g. key rotated without re-encrypting — fails closed, not with a
    plaintext-looking garbage string an SMTP client would try to use)."""
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None
