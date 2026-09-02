"""DRF permission classes backed by the tenant RBAC resolver."""

from rest_framework.permissions import BasePermission

from apps.identity.models import Membership, MembershipStatus
from apps.rbac.permissions import Scope
from apps.rbac.services import resolve_authorization


def get_authorization(request):
    """Resolve the caller's authorization once per request, then reuse it.

    Cached on the request because a single view often asks several times --
    once in the permission class, again while filtering a queryset, again
    when deciding which actions to advertise in the response.
    """
    cached = getattr(request, "_authorization", None)
    if cached is not None:
        return cached

    organization = getattr(request, "organization", None)
    if organization is None or not request.user.is_authenticated:
        return None

    membership = Membership.objects.filter(
        user=request.user, organization=organization, status=MembershipStatus.ACTIVE
    ).select_related("organization").first()
    if membership is None:
        return None

    authorization = resolve_authorization(request.user, membership)
    request._authorization = authorization
    return authorization


class HasPermission(BasePermission):
    """Requires a named permission, at an optional minimum scope.

    Used as `HasPermission.of("facility.read")` so views stay declarative:

        permission_classes = [IsAuthenticated, HasPermission.of("facility.read")]
    """

    permission_code = ""
    required_scope = Scope.FACILITY
    message = "You do not have permission to perform this action."

    @classmethod
    def of(cls, code: str, scope: str = Scope.FACILITY):
        return type(
            f"HasPermission_{code.replace('.', '_')}",
            (cls,),
            {"permission_code": code, "required_scope": scope},
        )

    def has_permission(self, request, view):
        authorization = get_authorization(request)
        if authorization is None:
            return False
        if not self.permission_code:
            return True
        allowed = authorization.has(self.permission_code, self.required_scope)
        if not allowed:
            self.message = (
                f"This action requires the '{self.permission_code}' permission."
            )
        return allowed


class IsPlatformStaff(BasePermission):
    """Employees of the platform owner, for the SaaS console."""

    message = "This endpoint is restricted to platform staff."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_platform_staff
        )


class IsOrganizationOwner(BasePermission):
    message = "This action is restricted to organization owners."

    def has_permission(self, request, view):
        authorization = get_authorization(request)
        return bool(authorization and authorization.is_organization_owner)
