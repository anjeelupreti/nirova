"""Forgotten passwords: a link by email, used once, within half an hour.

Until this existed the only way back into a forgotten account was an
administrator issuing a temporary password and reading it out — which works
in a clinic where the administrator is down the corridor, and not at 2 a.m. or
for the owner, who has nobody above them to ask.

It follows the OWASP Forgot Password guidance, point by point:

* **The same answer whether or not the address has an account.** "We have
  sent a link if it is registered" — never "no such user", which would let
  anybody test a list of addresses for who works here. The work done is the
  same either way, so the response time does not tell either.
* **A token that is signed, single-use and short-lived.** Django's
  `PasswordResetTokenGenerator` signs the user, their current password hash
  and the time; setting a password changes the hash, which spends the token.
  `PASSWORD_RESET_TIMEOUT` is thirty minutes.
* **Every existing session ends.** Whoever had the account before the reset —
  the reason people reset — is signed out everywhere (see
  `authentication.issued_before_password_change`).
* **The owner is told.** A second email says the password changed, so a reset
  somebody else did is noticed.
* **Rate-limited, quietly.** Three requests for one address in fifteen
  minutes, twenty from one network address in an hour; beyond that the
  answer is the same and nothing is sent. Limiting loudly would itself reveal
  which addresses exist.
* **The second factor still applies.** A reset proves the mailbox, not the
  person; somebody with two-step sign-in on still needs their code to sign in.

Every request and every completed reset is written to the sign-in log
(`LoginAttempt`), which is the control plane's account-security record and,
conveniently, the counter the rate limit reads.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.identity.models import LoginAttempt, LoginOutcome, User

logger = logging.getLogger(__name__)

PER_ADDRESS = 3
PER_ADDRESS_WINDOW = timedelta(minutes=15)
PER_NETWORK = 20
PER_NETWORK_WINDOW = timedelta(hours=1)

GENERIC_ANSWER = (
    "If that address belongs to an account, we have sent it a link to choose a "
    "new password. The link works once, for 30 minutes."
)


class ResetRefused(Exception):
    """The link is wrong, used or old, or the new password is not acceptable."""

    def __init__(self, message: str, code: str = "reset_refused"):
        super().__init__(message)
        self.message = message
        self.code = code


def _too_many(email: str, ip: str | None) -> bool:
    now = timezone.now()
    recent = LoginAttempt.objects.filter(outcome=LoginOutcome.RESET_REQUESTED)
    if recent.filter(email=email, attempted_at__gte=now - PER_ADDRESS_WINDOW).count() >= PER_ADDRESS:
        return True
    if ip and recent.filter(ip_address=ip, attempted_at__gte=now - PER_NETWORK_WINDOW).count() >= PER_NETWORK:
        return True
    return False


def reset_link(user: User) -> str:
    # The public UUID, not the row number: a sequential id in a link says how
    # many accounts there are and which one came after which.
    uid = urlsafe_base64_encode(force_bytes(str(user.uuid)))
    token = default_token_generator.make_token(user)
    return f"{settings.CONSOLE_URL}/reset-password?uid={uid}&token={token}"


def request_reset(email: str, ip: str | None = None, user_agent: str = "") -> None:
    """Send a reset link if the address has an active account. Never says which."""
    email = (email or "").strip().lower()
    if not email:
        return
    limited = _too_many(email, ip)
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    LoginAttempt.objects.create(
        email=email, user=user, outcome=LoginOutcome.RESET_REQUESTED,
        ip_address=ip, user_agent=(user_agent or "")[:512],
    )
    if limited or user is None:
        return

    minutes = settings.PASSWORD_RESET_TIMEOUT // 60
    name = user.preferred_name or user.full_name or "there"
    link = reset_link(user)
    body = (
        f"Hello {name},\n\n"
        f"Somebody asked to reset the password for {user.email} on Nirova. "
        f"If it was you, choose a new password here:\n\n{link}\n\n"
        f"The link works once and expires in {minutes} minutes.\n\n"
        "If it was not you, ignore this email: your password has not changed "
        "and nobody can change it without this link.\n\n"
        "— Nirova"
    )
    html = (
        f"<p>Hello {_escape(name)},</p>"
        f"<p>Somebody asked to reset the password for <strong>{_escape(user.email)}</strong> on Nirova. "
        "If it was you, choose a new password:</p>"
        f'<p><a href="{link}" style="display:inline-block;padding:10px 18px;border-radius:6px;'
        'background:#0f766e;color:#ffffff;text-decoration:none;font-weight:600">Choose a new password</a></p>'
        f"<p>The link works once and expires in {minutes} minutes.</p>"
        "<p style=\"color:#666\">If it was not you, ignore this email: your password has not changed "
        "and nobody can change it without this link.</p>"
    )
    _dispatch(user.email, "Reset your Nirova password", body, html)


def _escape(text: str) -> str:
    from django.utils.html import escape

    return escape(text)


def _dispatch(to: str, subject: str, body: str, html: str | None = None) -> None:
    """Send off the request path. A registered address that waited on the
    mail server would answer measurably slower than an unknown one, and the
    difference is an enumeration oracle; a thread makes both answer at once."""
    import threading

    threading.Thread(target=_send, args=(to, subject, body, html), daemon=True).start()


def _send(to: str, subject: str, body: str, html: str | None = None) -> None:
    """Send, and log rather than raise when the mail server is down: the
    person gets the same answer either way, and an error here would be the
    one response that differed for a registered address."""
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], html_message=html)
    except Exception:  # noqa: BLE001 — a mail outage must not change the answer
        logger.exception("Could not send %r to a registered address", subject)


def _user_from(uid: str) -> User | None:
    try:
        value = force_str(urlsafe_base64_decode(uid))
        return User.objects.get(uuid=value, is_active=True)
    except (TypeError, ValueError, OverflowError, DjangoValidationError, User.DoesNotExist):
        return None


def check_link(uid: str, token: str) -> User:
    """The account a link is for, or `ResetRefused` if the link is no good."""
    user = _user_from(uid or "")
    if user is None or not default_token_generator.check_token(user, token or ""):
        raise ResetRefused(
            "This link has expired or has already been used. Ask for a new one.",
            code="reset_link_invalid",
        )
    return user


def complete_reset(uid: str, token: str, new_password: str, ip: str | None = None, user_agent: str = "") -> User:
    """Set the new password, end every session, and tell the owner."""
    user = check_link(uid, token)
    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        raise ResetRefused(" ".join(exc.messages), code="weak_password") from exc

    user.set_password(new_password)
    user.must_change_password = False
    # Proving the mailbox is the unlock: a locked-out person who resets has
    # shown who they are more strongly than a correct password would.
    user.failed_login_attempts = 0
    user.locked_until = None
    user.save(update_fields=[
        "password", "password_changed_at", "must_change_password",
        "failed_login_attempts", "locked_until", "updated_at",
    ])
    LoginAttempt.objects.create(
        email=user.email, user=user, outcome=LoginOutcome.PASSWORD_RESET,
        ip_address=ip, user_agent=(user_agent or "")[:512],
    )

    when = timezone.localtime().strftime("%d %b %Y, %H:%M")
    _dispatch(
        user.email,
        "Your Nirova password was changed",
        (
            f"Hello {user.preferred_name or user.full_name or 'there'},\n\n"
            f"The password for {user.email} was changed on {when} using a reset link. "
            "Every device that was signed in has been signed out.\n\n"
            "If this was not you, contact your administrator straight away.\n\n— Nirova"
        ),
    )
    return user
