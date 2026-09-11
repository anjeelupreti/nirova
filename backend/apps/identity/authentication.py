"""Bearer-token authentication, with the temporary-password lock.

**A temporary password was only a lock in the browser.** `must_change_password`
is set when an administrator issues one (`issue_temporary_password`), and the
console showed nothing but the choose-a-password screen until it was replaced.
The API did not care. Anybody holding the token the temporary password signed
in with — the administrator who typed it, a colleague who watched it typed, a
script — could read the patient list, prescribe and dispense with it, as the
person it was issued to, for as long as the token lived. The point of making
somebody choose their own password is that nothing is done in their name until
only they know it; a lock on the front door with the back door open is not
that.

So the lock is here, where every authenticated request passes. Authentication
rather than a permission class because nearly every view in the product names
its own `permission_classes`, which replaces the default — a default permission
would have reached almost nothing — while authentication classes are left at
the default everywhere but the handful of deliberately anonymous endpoints.

The few doors left open are the ones needed to get out of the state: reading
who you are, changing the password, and signing out.

**The same lock holds an unenrolled person when the organization requires
two-step sign-in** (`security.require_mfa`). A policy the console enforced and
the API did not would be the temporary-password hole again: turn the setting
on, and anybody with a password could still script the API with a single
factor. Unenrolled, they reach who they are, the enrolment endpoint, and the
way out.
"""

import time

from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication


class PasswordChangeRequired(PermissionDenied):
    """A DRF exception rather than a `DomainError`, because DRF imports this
    module while `apps.common.exceptions` is still importing DRF — the circular
    import is unavoidable from here. The envelope is the same: the handler
    keeps an `APIException`'s code."""

    default_code = "password_change_required"
    default_detail = (
        "You signed in with a temporary password. Choose your own password "
        "before doing anything else."
    )


class SecondFactorRequired(PermissionDenied):
    default_code = "mfa_enrolment_required"
    default_detail = (
        "Your organization requires two-step sign-in. Set it up before doing "
        "anything else."
    )


#: What an unenrolled person may do while their organization requires it.
ALLOWED_WHILE_UNENROLLED = {
    "/api/auth/session/": {"GET"},
    "/api/auth/me/": {"GET"},
    "/api/auth/me/preferences/": {"GET"},
    "/api/auth/me/mfa/": {"GET", "POST"},
    "/api/auth/logout/": {"POST"},
}

#: Seconds an organization's answer is remembered. Read on every authenticated
#: request otherwise — one query per call, for a switch that changes once.
POLICY_TTL = 30
_policy_cache: dict = {}


def organization_requires_mfa(request) -> bool:
    """Whether the organization this request is for requires a second factor."""
    organization = getattr(request, "organization", None)
    if getattr(request, "tenant", None) is None or organization is None:
        return False
    key = organization.slug
    cached = _policy_cache.get(key)
    now = time.monotonic()
    if cached and now - cached[1] < POLICY_TTL:
        return cached[0]
    from apps.organization.config import config_value

    required = bool(config_value("security", "require_mfa", default=False))
    _policy_cache[key] = (required, now)
    return required


def forget_policy(slug: str) -> None:
    """Drop the cached answer, when the setting changes."""
    _policy_cache.pop(slug, None)


#: (path, methods) a temporarily-passworded session may still use. Exact paths,
#: not prefixes: `/api/auth/me/` is allowed and `/api/auth/me/anything-else/`
#: is not, and a prefix match is how that distinction quietly disappears.
ALLOWED_WHILE_LOCKED = {
    "/api/auth/session/": {"GET"},
    "/api/auth/me/": {"GET"},
    "/api/auth/me/preferences/": {"GET"},
    "/api/auth/me/password/": {"POST"},
    "/api/auth/logout/": {"POST"},
}


class NirovaJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        if getattr(user, "must_change_password", False):
            allowed = ALLOWED_WHILE_LOCKED.get(request.path, set())
            if request.method not in allowed and request.method != "OPTIONS":
                raise PasswordChangeRequired()
        if not getattr(user, "mfa_enabled", False) and request.method != "OPTIONS":
            allowed = ALLOWED_WHILE_UNENROLLED.get(request.path, set())
            if request.method not in allowed and organization_requires_mfa(request):
                raise SecondFactorRequired()
        return user, token
