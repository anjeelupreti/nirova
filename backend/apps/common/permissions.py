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


def apply_scope_filter(
    queryset,
    request,
    permission_code: str,
    employee_attr: str = "employee",
    facility_attr: str = "facility",
):
    """Narrow a queryset to what the caller's scope actually reaches.

    - Organization owner, or `Scope.ORGANIZATION`: the whole tenant.
    - `Scope.OWN`: strictly the caller's own Employee record.
    - `Scope.UNIT` / `DEPARTMENT` / `FACILITY` / `MULTI_FACILITY`: the
      facilities the grant names.
    - Anything else, including no permission at all: nothing.

    **Every path returns explicitly, and the fall-through denies.** An earlier
    version ended `return queryset`, which meant three separate cases handed
    back the entire organization: a `DEPARTMENT` or `UNIT` grant, which are
    *narrower* than facility and so fell past the facility branch; and -- worse
    -- a facility-scoped grant naming no facility, which is the state
    `assign_role` still permits and the checklist queues as a defect. That
    combination inverted the defect from fail-closed to fail-open: the user
    who previously appeared to have a role and could see nothing could now see
    everything. A scope filter whose default is "return everything" is not a
    scope filter.

    `accessible_facility_ids` answers `None` for "all facilities", which only
    happens for an owner or an organization-scoped grant -- both returned
    above. Reaching the facility branch with an empty set therefore means the
    grant genuinely reaches no facility, and the honest answer is no rows.
    """
    authorization = get_authorization(request)
    if authorization is None:
        return queryset.none()
    if authorization.is_organization_owner:
        return queryset

    granted = authorization.permissions.get(permission_code)
    if granted is None:
        return queryset.none()

    if granted.scope == Scope.ORGANIZATION:
        return queryset

    if granted.scope == Scope.OWN:
        from apps.hr.models import Employee

        employee = Employee.for_user(request.user.uuid)
        if employee is None:
            return queryset.none()
        if employee_attr == "self":
            return queryset.filter(pk=employee.pk)
        return queryset.filter(**{employee_attr: employee})

    # Unit and department grants are narrowed to the facility they sit in
    # rather than to the unit itself: `_merge` records the parent facility on
    # every grant, and this helper has no unit or department column to filter
    # on. Looser than the ladder implies, and recorded as such in the
    # checklist -- but bounded, which the previous fall-through was not.
    if granted.scope in (
        Scope.UNIT, Scope.DEPARTMENT, Scope.FACILITY, Scope.MULTI_FACILITY,
    ):
        facility_ids = authorization.accessible_facility_ids(permission_code)
        if not facility_ids:
            return queryset.none()
        return queryset.filter(**{f"{facility_attr}_id__in": facility_ids})

    return queryset.none()
