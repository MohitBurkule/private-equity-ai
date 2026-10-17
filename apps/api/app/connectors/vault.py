"""Encrypted storage for connector credentials (Fernet, key from CONNECTOR_KEY).
No key configured = refuse to store: tokens are never kept in plaintext."""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class VaultError(Exception):
    pass


def _fernet() -> Fernet:
    key = os.environ.get("CONNECTOR_KEY")
    if not key:
        raise VaultError("CONNECTOR_KEY not set; cannot store credentials (generate one with Fernet.generate_key())")
    try:
        return Fernet(key.encode())
    except ValueError as e:
        raise VaultError("CONNECTOR_KEY is not a valid Fernet key") from e


def seal(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def unseal(blob: str) -> str:
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except InvalidToken as e:
        raise VaultError("stored credential cannot be decrypted (key changed?)") from e
