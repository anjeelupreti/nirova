"""Second-factor sign-in: time-based one-time codes, and recovery codes.

`User.mfa_enabled` and `User.mfa_secret` were in the first identity migration
and nothing ever read them — so an account could be marked as having a second
factor and sign in with a password alone. A hospital's security review asks
for this before anything else, and a password is the one credential staff
reuse, write on the monitor and share on a night shift.

**Standard TOTP (RFC 6238)** — SHA-1, six digits, thirty-second steps — because
that is what Google Authenticator, Microsoft Authenticator and every hardware
token speak, and a hospital cannot tell three hundred staff to install
something unusual. Written here in forty lines rather than taken from a
library: the algorithm is small, fixed by the RFC, and tested against the
RFC's own vectors.

Three properties hold:

- **The secret is encrypted at rest** (Fernet, keyed from `MFA_ENCRYPTION_KEY`
  or derived from `SECRET_KEY`). Read from a database backup, a bare secret
  is a way to sign in as the person forever.
- **A code works once.** It stays valid for about a minute either side of the
  clock, so without remembering the last accepted step, a code read over a
  shoulder could be used again straight away.
- **Recovery codes are stored like passwords** — hashed, each removed when
  used — because a phone is lost more often than it is stolen, and the way
  back in must not be a list anybody with database access can read.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing

STEP_SECONDS = 30
DIGITS = 6
#: Steps either side of now that are accepted: phone clocks drift.
WINDOW = 1
RECOVERY_CODES = 10
#: How long the password step's challenge lasts before the code must be given.
CHALLENGE_SECONDS = 300
CHALLENGE_SALT = "nirova.identity.mfa-challenge"


# -- the secret ----------------------------------------------------------------


def _fernet() -> Fernet:
    key = getattr(settings, "MFA_ENCRYPTION_KEY", "") or ""
    if not key:
        digest = hashlib.sha256(f"nirova-mfa::{settings.SECRET_KEY}".encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def new_secret() -> str:
    """160 random bits, base32 without padding, as authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def seal(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def unseal(sealed: str) -> str | None:
    try:
        return _fernet().decrypt(sealed.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def provisioning_uri(secret: str, account: str, issuer: str = "Nirova") -> str:
    """The `otpauth://` link an authenticator app reads from a QR code."""
    label = quote(f"{issuer}:{account}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


# -- codes -------------------------------------------------------------------


def code_at(secret: str, step: int) -> str:
    """RFC 4226 HOTP for one counter value — the heart of TOTP."""
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10**DIGITS
    return f"{number:0{DIGITS}d}"


def current_step(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // STEP_SECONDS)


def verify(secret: str, code: str, last_step: int | None = None, at: float | None = None) -> int | None:
    """The step `code` belongs to, if it is valid now and not already used.

    Compared in constant time, and only against steps later than the last one
    accepted — which is what makes a code single-use.
    """
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now = current_step(at)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


# -- recovery codes ------------------------------------------------------------


def new_recovery_codes() -> tuple[list[str], list[str]]:
    """Ten codes to show once, and their hashes to keep.

    `xxxx-xxxx` from an alphabet with no 0/O or 1/l, because these are read
    off paper in a hurry.
    """
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    plain = [
        "".join(secrets.choice(alphabet) for _ in range(4))
        + "-"
        + "".join(secrets.choice(alphabet) for _ in range(4))
        for _ in range(RECOVERY_CODES)
    ]
    return plain, [make_password(code) for code in plain]


def use_recovery_code(user, code: str) -> bool:
    """Spend one recovery code. True if it was valid; it cannot be used again."""
    given = str(code).strip().lower()
    remaining = list(user.mfa_recovery_codes or [])
    for index, hashed in enumerate(remaining):
        if check_password(given, hashed):
            del remaining[index]
            user.mfa_recovery_codes = remaining
            user.save(update_fields=["mfa_recovery_codes"])
            return True
    return False


# -- the challenge between the password and the code -------------------------------


def issue_challenge(user) -> str:
    """A signed, short-lived token saying "this person gave the right password".

    Bound to the password hash as it is now, so a challenge issued before a
    password change cannot be finished after it.
    """
    return signing.dumps(
        {"u": str(user.uuid), "p": user.password[-16:]},
        salt=CHALLENGE_SALT,
    )


def read_challenge(token: str):
    """The user a challenge was issued for, or None if it is forged or stale."""
    from apps.identity.models import User

    try:
        data = signing.loads(token, salt=CHALLENGE_SALT, max_age=CHALLENGE_SECONDS)
    except signing.BadSignature:
        return None
    user = User.objects.filter(uuid=data.get("u")).first()
    if user is None or user.password[-16:] != data.get("p"):
        return None
    return user


def check_second_factor(user, code: str) -> str | None:
    """"totp" or "recovery" if the code signs this user in, else None.

    Records the accepted step so the same code cannot be replayed.
    """
    secret = unseal(user.mfa_secret) if user.mfa_secret else None
    if secret:
        step = verify(secret, code, last_step=user.mfa_last_step)
        if step is not None:
            user.mfa_last_step = step
            user.save(update_fields=["mfa_last_step"])
            return "totp"
    if "-" in str(code) and use_recovery_code(user, code):
        return "recovery"
    return None
