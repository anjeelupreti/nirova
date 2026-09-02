"""Authentication, the session bootstrap, and the context switcher."""

from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.common.http import client_ip
from apps.entitlements.resolver import resolve_entitlements
from apps.identity.models import (
    LoginAttempt,
    LoginOutcome,
    Membership,
    MembershipStatus,
)
from apps.identity.serializers import (
    LoginSerializer,
    MembershipSerializer,
    UserSerializer,
)
from apps.rbac.services import resolve_authorization
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context

#: Consecutive failures before an account is locked out.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class LoginView(APIView):
    """Exchange credentials for tokens.

    Login runs entirely in the control plane. The user's organization is not
    known until after authentication, so no tenant connection can be chosen
    before this point -- which is precisely why identity lives where it does.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        password = serializer.validated_data["password"]

        ip = client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:512]

        def log(outcome, user=None):
            LoginAttempt.objects.create(
                email=email,
                user=user,
                outcome=outcome,
                ip_address=ip,
                user_agent=user_agent,
            )

        user = authenticate(request, username=email, password=password)

        if user is None:
            # Record the failure against a known account so lockout works,
            # but return the same message either way: distinguishing "wrong
            # password" from "no such user" hands an attacker a list of who
            # holds accounts.
            from apps.identity.models import User

            known = User.objects.filter(email=email).first()
            if known is not None:
                known.failed_login_attempts += 1
                if known.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                    known.locked_until = timezone.now() + timezone.timedelta(
                        minutes=LOCKOUT_MINUTES
                    )
                known.save(update_fields=["failed_login_attempts", "locked_until"])
            log(LoginOutcome.BAD_CREDENTIALS, known)
            return Response(
                {
                    "error": {
                        "code": "invalid_credentials",
                        "message": "Email or password is incorrect.",
                        "detail": {},
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if user.is_locked:
            log(LoginOutcome.LOCKED, user)
            return Response(
                {
                    "error": {
                        "code": "account_locked",
                        "message": (
                            "This account is temporarily locked after repeated "
                            "failed sign-ins. Try again shortly."
                        ),
                        "detail": {"locked_until": user.locked_until.isoformat()},
                    }
                },
                status=status.HTTP_423_LOCKED,
            )

        if not user.is_active:
            log(LoginOutcome.INACTIVE, user)
            return Response(
                {
                    "error": {
                        "code": "account_inactive",
                        "message": "This account has been deactivated.",
                        "detail": {},
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_ip = ip
        user.last_active_at = timezone.now()
        user.save(
            update_fields=[
                "failed_login_attempts",
                "locked_until",
                "last_login_ip",
                "last_active_at",
            ]
        )
        log(LoginOutcome.SUCCESS, user)

        memberships = (
            Membership.objects.filter(user=user, status=MembershipStatus.ACTIVE)
            .select_related("organization")
            .order_by("-is_default", "created_at")
        )

        if not memberships and not user.is_platform_staff:
            log(LoginOutcome.NO_ORGANIZATION, user)
            return Response(
                {
                    "error": {
                        "code": "no_organization",
                        "message": (
                            "This account is not linked to any organization. "
                            "Ask an administrator to invite you."
                        ),
                        "detail": {},
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
                "memberships": MembershipSerializer(memberships, many=True).data,
                "default_organization": (
                    memberships[0].organization.slug if memberships else None
                ),
            }
        )


class SessionView(APIView):
    """Everything the frontend needs to render the shell after a page load.

    One call rather than five: the user, the organizations they can switch
    between, their resolved permissions in the current organization, and
    what that organization's subscription entitles them to. The frontend
    should never have to assemble authorization from separate endpoints --
    that is how UI and API drift apart on who may do what.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        memberships = (
            Membership.objects.filter(user=user, status=MembershipStatus.ACTIVE)
            .select_related("organization")
            .order_by("-is_default", "created_at")
        )

        payload = {
            "user": UserSerializer(user).data,
            "memberships": MembershipSerializer(memberships, many=True).data,
            "organization": None,
            "authorization": None,
            "entitlements": None,
        }

        tenant_error = getattr(request, "tenant_error", None)
        if tenant_error is not None:
            payload["tenant_error"] = tenant_error.as_payload()["error"]
            return Response(payload)

        organization = getattr(request, "organization", None)
        if organization is None:
            return Response(payload)

        membership = memberships.filter(organization=organization).first()
        entitlements = resolve_entitlements(organization)

        payload["organization"] = {
            "uuid": str(organization.uuid),
            "slug": organization.slug,
            "display_name": organization.display_name,
            "business_type": organization.business_type,
            "status": organization.status,
            "logo_url": organization.logo_url,
            "primary_color": organization.primary_color,
            "timezone": organization.timezone,
            "is_read_only": organization.is_read_only,
        }
        payload["entitlements"] = entitlements.as_dict()

        if membership is not None:
            authorization = resolve_authorization(user, membership)
            payload["authorization"] = authorization.as_dict()

        return Response(payload)


class SwitchOrganizationView(APIView):
    """Change which organization the caller is working in.

    The switch is a client-side concern -- subsequent requests carry the
    `X-Organization` header -- so this endpoint exists to *validate* the
    choice and hand back the new context in one round trip, rather than
    letting the frontend discover mid-render that the user has no access.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        slug = request.data.get("organization")
        if not slug:
            return Response(
                {
                    "error": {
                        "code": "organization_required",
                        "message": "Specify the organization to switch to.",
                        "detail": {},
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership = (
            Membership.objects.filter(
                user=request.user,
                organization__slug=slug,
                status=MembershipStatus.ACTIVE,
            )
            .select_related("organization")
            .first()
        )
        if membership is None:
            return Response(
                {
                    "error": {
                        "code": "not_a_member",
                        "message": "You do not have access to that organization.",
                        "detail": {"organization": slug},
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        organization = membership.organization
        context = context_for_organization(organization)
        with tenant_context(context):
            authorization = resolve_authorization(request.user, membership)

        return Response(
            {
                "organization": {
                    "uuid": str(organization.uuid),
                    "slug": organization.slug,
                    "display_name": organization.display_name,
                    "status": organization.status,
                },
                "authorization": authorization.as_dict(),
                "entitlements": resolve_entitlements(organization).as_dict(),
            }
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Tokens are stateless, so the client discards them. The sign-out is
        # recorded in the tenant audit log, where the rest of that user's
        # activity sits -- but only when an organization is bound, since
        # there is no tenant log to write to otherwise.
        if getattr(request, "tenant", None) is not None:
            record(
                AuditAction.LOGOUT,
                entity_type="identity.User",
                entity_id=request.user.uuid,
                entity_label=request.user.email,
            )
        return Response({"status": "signed_out"})
