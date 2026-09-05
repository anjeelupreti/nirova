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

#: The namespace and key of the switch that turns clinical access control on.
#: Off by default -- a single-site clinic gets nothing from a care-relationship
#: requirement and pays the complexity, the same position §17 already takes on
#: segregation of duties, which a two-person practice cannot enforce because
#: there is nobody to segregate.
PRIVACY_NAMESPACE = "privacy"
REQUIRE_RELATIONSHIP_KEY = "require_care_relationship"


def relationship_required(facility=None) -> bool:
    """Whether this organization enforces care relationships on clinical reads.

    Read through the configuration hierarchy, so a group can turn it on
    everywhere and leave it off at the one site still being migrated -- which
    is the realistic way this gets adopted, rather than a flag day.
    """
    from apps.organization.config import config_value

    return bool(
        config_value(
            PRIVACY_NAMESPACE, REQUIRE_RELATIONSHIP_KEY,
            default=False, facility=facility,
        )
    )


class HasClinicalAccess(BasePermission):
    """`patient.clinical.read`, plus a care relationship with *this* patient.

    Phase 2 of `docs/ACCESS_DESIGN.md`. Two questions, kept apart on purpose:
    whether somebody may read clinical data at all, and whether they may read
    *this* record. Collapsing them is how a permission comes to mean "everyone
    at this site", which is what the 4 September probe found.

    **The object is what is checked, not the list.** This is an object-level
    permission; narrowing lists is step 4 and a different mechanism, because a
    list of patients somebody may not open is not the same failure as opening
    one of them.

    **The refusal names the way out.** A bare 403 on a clinical record at three
    in the morning is how somebody decides the system is broken and borrows a
    colleague's login. The message says the record can be opened by giving a
    reason, which is true and is the whole point of building break-glass first.
    """

    message = "You are not currently treating this patient."

    def has_permission(self, request, view):
        authorization = get_authorization(request)
        if authorization is None:
            return False
        # The permission question, unchanged. Scope.OWN as the floor for the
        # same reason the break-glass endpoint uses it: a department-scoped
        # clinician holds clinical access more narrowly than a facility, and
        # they are still a clinician.
        return authorization.has("patient.clinical.read", Scope.OWN)

    def has_object_permission(self, request, view, obj):
        patient = _patient_of(obj)
        if patient is None:
            # Nothing patient-shaped to check. Falling open here is deliberate
            # and narrow: this class is only ever attached to patient-scoped
            # views, and refusing an object it cannot interpret would produce
            # a 403 nobody can act on.
            return True

        facility = getattr(obj, "facility", None)
        if not relationship_required(facility):
            return True

        from apps.rbac.relationships import relationship_for_request

        found = relationship_for_request(request, patient)
        if found is None:
            self.message = (
                f"You are not currently treating {patient.full_name}. If this "
                "is an emergency, open the record by giving a reason -- it "
                "will be recorded against your name and reviewed."
            )
            return False

        # Recorded on the request so the view can say *why* access was granted
        # and write it onto the access log. A relationship that cannot be
        # explained afterwards is not reviewable, and reviewability is the
        # point of the whole phase.
        request.care_relationship = found
        return True


def _patient_of(obj):
    """The patient an object concerns, however it happens to be attached."""
    from apps.patients.models import Patient

    if isinstance(obj, Patient):
        return obj
    for attribute in ("patient", "encounter", "admission", "order"):
        related = getattr(obj, attribute, None)
        if isinstance(related, Patient):
            return related
        if related is not None:
            nested = getattr(related, "patient", None)
            if isinstance(nested, Patient):
                return nested
    return None
