"""Resolves which organization a request belongs to, before the view runs."""

import logging

# MiddlewareMixin: gives the old-style process_request / process_response /
# process_exception hooks. Used rather than the plain callable style because
# this middleware must reset the context on *both* the response path and the
# exception path -- a single `__call__` wrapper makes that easy to get wrong.
from django.utils.deprecation import MiddlewareMixin

# JWTAuthentication: this middleware authenticates the bearer token itself.
# It has to. Django's AuthenticationMiddleware only populates request.user
# from the *session*, and this is a token-authenticated API -- DRF does not
# authenticate until the view runs, which is far too late. The database
# router needs the organization bound before the first query, and the first
# query happens inside the view.
#
# The cost is that the token is decoded twice per request: once here, once by
# DRF. That is a signature verification on an already-parsed header -- cheap,
# and worth paying for a context that is reliably present everywhere.
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import (
    AuthenticationFailed,
    InvalidToken,
    TokenError,
)

# DomainError: the base class caught below so any expected failure during
# tenant resolution is stashed on the request instead of exploding in
# middleware, where DRF's exception handler cannot format it.
# TenantResolutionError: raised when the requested organization is unknown or
# the user is not a member of it.
from apps.common.exceptions import DomainError, TenantResolutionError

# context_for_organization: registers the tenant's connection and builds the
# context. The single place a tenant connection comes into existence.
from apps.tenancy.connections import context_for_organization

# TenantContext: rebuilt (rather than mutated) when narrowing to a facility,
# because it is frozen -- see _apply_facility_scope.
# set_current_tenant / reset_current_tenant: bind and unbind the context
# variable. The token returned by set must be handed back to reset, which is
# why it is stashed on the request object.
from apps.tenancy.context import (
    TenantContext,
    reset_current_tenant,
    set_current_tenant,
)

logger = logging.getLogger("nirova.tenancy")

#: Paths that legitimately run with no organization.
#:
#: Only pre-authentication endpoints are listed for /api/auth/ -- not the
#: whole prefix. `/api/auth/session/` and `/api/auth/switch/` are
#: authenticated and *need* the tenant bound, because they return the
#: caller's permissions inside the current organization, which live in the
#: tenant database.
CONTROL_PLANE_PREFIXES = (
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/register",
    "/api/auth/password",
    "/api/platform/",
    "/api/health",
    "/api/schema",
    "/api/docs",
    "/admin/",
    "/static/",
)


class TenantContextMiddleware(MiddlewareMixin):
    """Binds the tenant context for the duration of one request.

    Resolution order, most explicit first:

    1. `X-Organization` header -- how the frontend's context switcher asks
       for a specific organization. Only honoured if the user is a member of
       it, or is platform staff acting with support access.
    2. The authenticated user's default organization.

    Unauthenticated requests, and requests to control-plane paths, run with
    no tenant. Tenant models then raise instead of quietly reading the wrong
    database.
    """

    header = "HTTP_X_ORGANIZATION"
    jwt_authenticator = JWTAuthentication()

    def process_request(self, request):
        request.tenant = None
        request._tenant_token = None

        if self._is_control_plane_path(request.path):
            return None

        user = self._resolve_user(request)
        if user is None:
            return None

        try:
            organization = self._resolve_organization(request, user)
        except DomainError as exc:
            request.tenant_error = exc
            return None

        if organization is None:
            return None

        try:
            context = context_for_organization(organization)
        except DomainError as exc:
            request.tenant_error = exc
            return None

        context = self._apply_facility_scope(request, context)
        request.tenant = context
        request.organization = organization
        request._tenant_token = set_current_tenant(context)
        return None

    def process_response(self, request, response):
        token = getattr(request, "_tenant_token", None)
        if token is not None:
            reset_current_tenant(token)
            request._tenant_token = None
        return response

    def process_exception(self, request, exception):
        token = getattr(request, "_tenant_token", None)
        if token is not None:
            reset_current_tenant(token)
            request._tenant_token = None
        return None

    # -- internals -------------------------------------------------------

    @staticmethod
    def _is_control_plane_path(path: str) -> bool:
        return any(path.startswith(prefix) for prefix in CONTROL_PLANE_PREFIXES)

    def _resolve_user(self, request):
        """Return the authenticated user, authenticating the token if needed.

        Session-authenticated callers (the Django admin) are already
        populated by AuthenticationMiddleware. Token-authenticated callers
        are not, because DRF authenticates inside the view -- so the bearer
        token is verified here instead.

        A bad token is not rejected here. That is DRF's job, and doing it in
        middleware would bypass the API error envelope and return a bare
        Django 401. The request simply proceeds with no tenant bound, and the
        view's authentication returns the proper error.
        """
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return user

        try:
            authenticated = self.jwt_authenticator.authenticate(request)
        except (InvalidToken, TokenError, AuthenticationFailed):
            return None
        except Exception:  # pragma: no cover - never break the request here
            logger.warning("Unexpected error authenticating token", exc_info=True)
            return None

        if authenticated is None:
            return None

        user, _validated_token = authenticated
        # Publish it so the audit middleware, which runs next, stamps events
        # with the real actor rather than AnonymousUser.
        request.user = user
        return user

    def _resolve_organization(self, request, user):
        from apps.identity.models import Membership, MembershipStatus
        from apps.tenancy.models import Organization

        requested = request.META.get(self.header) or request.GET.get("organization")

        if requested:
            organization = Organization.objects.filter(slug=requested).first()
            if organization is None:
                organization = Organization.objects.filter(uuid=requested).first()
            if organization is None:
                raise TenantResolutionError(
                    "No organization matches the requested identifier.",
                    detail={"organization": requested},
                )
            if not self._user_may_access(user, organization):
                raise TenantResolutionError(
                    "You are not a member of that organization.",
                    detail={"organization": requested},
                )
            return organization

        membership = (
            Membership.objects.filter(
                user=user, status=MembershipStatus.ACTIVE
            )
            .select_related("organization", "organization__database")
            .order_by("-is_default", "created_at")
            .first()
        )
        if membership is None:
            if user.is_platform_staff:
                return None
            raise TenantResolutionError(
                "This account is not linked to any organization."
            )
        return membership.organization

    @staticmethod
    def _user_may_access(user, organization) -> bool:
        from apps.identity.models import Membership, MembershipStatus

        if user.is_platform_staff and user.support_access_enabled:
            return True
        return Membership.objects.filter(
            user=user, organization=organization, status=MembershipStatus.ACTIVE
        ).exists()

    @staticmethod
    def _apply_facility_scope(request, context: TenantContext) -> TenantContext:
        facility = request.META.get("HTTP_X_FACILITY") or request.GET.get("facility")
        if not facility:
            return context
        return TenantContext(
            organization_id=context.organization_id,
            organization_slug=context.organization_slug,
            database_alias=context.database_alias,
            facility_id=facility,
        )
