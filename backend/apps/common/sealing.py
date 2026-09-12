"""Secrets a tenant stores with us, encrypted at rest.

A payment gateway's merchant key is a password to the hospital's money: with
it, anybody can initiate and look up payments as the hospital. It is kept
sealed (Fernet: AES-128-CBC with an HMAC) so a leaked backup or a stray
`SELECT` shows ciphertext, and it is never sent back to a browser — the
settings screen shows only that one is set and its last four characters.

The key comes from `SETTINGS_ENCRYPTION_KEY`, or is derived from
`SECRET_KEY` with its own label so it is not the same key the second-factor
secrets use.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

PREFIX = "sealed:"


def _fernet() -> Fernet:
    key = getattr(settings, "SETTINGS_ENCRYPTION_KEY", "") or ""
    if not key:
        digest = hashlib.sha256(f"nirova-settings::{settings.SECRET_KEY}".encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def seal(text: str) -> str:
    return PREFIX + _fernet().encrypt(text.encode()).decode()


def unseal(value) -> str:
    """The plain text, or "" for anything that is not a readable sealed value."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return ""
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def hint(value) -> str:
    """What a screen may show of a sealed secret: that it exists, and its tail."""
    text = unseal(value)
    return f"•••• {text[-4:]}" if len(text) >= 8 else ("Set" if text else "")
