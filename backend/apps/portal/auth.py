"""Authenticating a patient, which is not the same as authenticating staff.

Two pieces, and both exist because the staff path cannot be reused.

**A tenant binding that does not require a staff user.** The ordinary
middleware resolves the organization from the caller's membership, and a
patient has none. The portal binds from the `X-Organization` header alone,
which is safe because the header only names *which database to look in*: the
session token has to exist in that database, and a wrong header finds nothing.

**A principal that is not a `User`.** `request.user` on a portal request is a
`PortalPrincipal` — it answers `is_authenticated`, and it deliberately
answers nothing else. Anything that reaches for `request.user.has_perm` or a
membership fails loudly rather than silently treating a patient as staff,
which is the failure this whole separation exists to prevent.
"""

from django.utils.deprecation import MiddlewareMixin
from rest_framework import authentication, exceptions

from apps.common.exceptions import DomainError
from apps.portal.services import session_for
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import reset_current_tenant, set_current_tenant
from apps.tenancy.models import Organization

#: Only these paths get the patient-side treatment. Narrow on purpose: the
#: staff API must keep its existing membership-based resolution, and a
#: middleware that binds a tenant from a header for every request would undo
#: that.
PORTAL_PREFIX = "/api/me/"


class PortalTenantMiddleware(MiddlewareMixin):
    """Bind the tenant for portal requests, from the header alone.

    Runs before the ordinary tenant middleware would give up: a patient has
    no membership, so `TenantContextMiddleware` resolves nothing for them and
    every tenant model would raise.
    """

    header = "HTTP_X_ORGANIZATION"

    def process_request(self, request):
        if not request.path.startswith(PORTAL_PREFIX):
            return None

        slug = request.META.get(self.header, "").strip()
        if not slug:
            return None

        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            return None

        try:
            context = context_for_organization(organization)
        except DomainError as exc:
            request.tenant_error = exc
            return None

        request.tenant = context
        request.organization = organization
        request._portal_tenant_token = set_current_tenant(context)
        return None

    def _release(self, request):
        token = getattr(request, "_portal_tenant_token", None)
        if token is not None:
            reset_current_tenant(token)
            request._portal_tenant_token = None

    def process_response(self, request, response):
        self._release(request)
        return response

    def process_exception(self, request, exception):
        self._release(request)
        return None


class PortalPrincipal:
    """The authenticated subject of a portal request.

    Not a `User`, and not pretending to be one. It answers
    `is_authenticated` because DRF's `IsAuthenticated` asks, and it answers
    nothing else — so any code that treats a portal caller as staff raises an
    `AttributeError` instead of quietly granting clinical permissions.
    """

    is_authenticated = True
    is_anonymous = False

    def __init__(self, account, session):
        self.account = account
        self.session = session
        self.patient = account.patient

    def __str__(self):
        return f"portal:{self.account.login_identifier}"

    @property
    def full_name(self) -> str:
        return self.patient.full_name

    @property
    def uuid(self):
        return self.account.uuid


class PortalSessionAuthentication(authentication.BaseAuthentication):
    """`Authorization: Portal <token>`.

    A distinct scheme from `Bearer` on purpose. If a patient's token were
    presented as a bearer token it would be handed to the JWT authenticator,
    which would reject it — but the two schemes sharing a keyword is the kind
    of thing that stops being true after a refactor.
    """

    keyword = "Portal"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed(
                "Malformed portal credentials."
            )

        token = header[1].decode()
        session = session_for(token)
        if session is None:
            raise exceptions.AuthenticationFailed(
                "That session has expired or been signed out."
            )
        return PortalPrincipal(session.account, session), session

    def authenticate_header(self, request):
        return self.keyword
