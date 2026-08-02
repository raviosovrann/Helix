"""Symmetric encryption for venue secrets at rest.

Credentials must never be stored in clear text. This wraps Fernet
(AES-128-CBC + HMAC-SHA256) from ``cryptography`` with a key supplied via the
``HELIX_SECRETS_KEY`` environment variable, so the operator controls the
key and it never lives next to the ciphertext. Generate one with
``python -c "from helix.service.crypto import generate_key; print(generate_key())"``.

The pre-rename ``TRADINGBOT_SECRETS_KEY`` is still read (see ``helix.config``).
That fallback matters more here than anywhere else: an absent key and a wrong
key fail identically, so dropping the old name would have looked to an
operator like their stored credentials had been corrupted.
"""

from __future__ import annotations

from cryptography.fernet import Fernet

from ..config import PREFIX, env

_ENV_KEY = PREFIX + "SECRETS_KEY"


def generate_key() -> str:
    """Return a new base64 Fernet key suitable for ``HELIX_SECRETS_KEY``."""
    return Fernet.generate_key().decode("ascii")


def _fernet() -> Fernet:
    """Build a Fernet from the configured key.

    Returns:
        A ``Fernet`` instance bound to the environment key.

    Raises:
        RuntimeError: If ``HELIX_SECRETS_KEY`` is not set.
    """
    key = env("SECRETS_KEY").strip()
    if not key:
        raise RuntimeError(
            f"{_ENV_KEY} is not set; it is required to encrypt/decrypt secrets at rest"
        )
    return Fernet(key.encode("utf-8"))


def encrypt(plaintext: str) -> str:
    """Encrypt ``plaintext`` and return the token as text.

    Args:
        plaintext: The value to encrypt.

    Returns:
        A URL-safe base64 Fernet token.
    """
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`.

    Args:
        token: The Fernet token to decrypt.

    Returns:
        The recovered plaintext.

    Raises:
        cryptography.fernet.InvalidToken: If the token is invalid for the key.
    """
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
