"""DRF permission classes backed by the tenant RBAC resolver."""

from django.db.models import Q
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

    # Fill the audit context's `actor_role` here, which is the first moment in
    # a request that anybody knows what it is. The middleware builds the
    # context before authorization is resolved, so the field had always been
    # written empty -- and the access-pattern report compares a person's read
    # volume against "the median for the same role", which with every role
    # blank was comparing a consultant to a counter assistant. Exactly what
    # its own docstring says it must not do.
    #
    # No extra query: the roles are already in the authorization that was just
    # resolved and cached.
    try:
        from apps.audit.services import get_audit_context

        context = get_audit_context()
        if context is not None and not context.actor_role:
            context.actor_role = ",".join(
                sorted({
                    source.split("@")[0].removeprefix("role:")
                    for granted in authorization.permissions.values()
                    for source in granted.sources
                    if source.startswith("role:")
                })
            )[:128]
    except Exception:  # noqa: BLE001 - never break a request to label a log
        pass

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
        queryset = queryset.filter(**{f"{facility_attr}_id__in": facility_ids})

        # Narrow to the department where the grant is that specific *and* the
        # model records one.
        #
        # This was written, reverted, and restored on the same day. The revert
        # was right at the time: clinical records carried no department at all
        # -- Encounter 0 of 123, Admission 0 of 31 -- so narrowing would have
        # shown a department-scoped doctor zero encounters, which is worse than
        # the looseness it fixes and silent with it. The attribution came
        # first; this came second. That order is the whole lesson.
        #
        # A model with no department column keeps the facility bound, and a row
        # whose department is null is *included* rather than hidden: an
        # encounter nobody attributed is not evidence that it belongs to
        # somebody else, and excluding it would quietly lose work.
        department_ids = authorization.accessible_department_ids(permission_code)
        if department_ids and any(
            field.name == "department" for field in queryset.model._meta.get_fields()
        ):
            queryset = queryset.filter(
                Q(department_id__in=department_ids) | Q(department_id__isnull=True)
            )
        return queryset

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


def narrow_to_relationship(queryset, request, patient_field="patient_id"):
    """Restrict a *list* to patients the caller has a care relationship with.

    Step 4 of `PHASE2_PLAN.md`, and the distinction that replaces facility
    filtering: browsing is asking the system who exists, while looking
    something up is naming a record somebody has handed you.

    **List actions only.** `retrieve` is deliberately left alone. A patient who
    presents a prescription reference has supplied both the relationship and
    the consent, so a pharmacy that cannot enumerate the group's prescriptions
    can still open the one in front of them. That asymmetry is the point;
    tidying it away would break group dispensing, which is why Phase 1 left a
    test asserting the prescription list is not facility-filtered.

    `None` from `related_patient_ids_for_request` means *no restriction* -- an
    owner, an auditor, an organization-scoped clinical role -- and is not the
    same answer as an empty set, which means nobody. Conflating the two is how
    a list either leaks everything or silently shows nothing; the same
    distinction `accessible_facility_ids` draws, deliberately mirrored so that
    callers handle both the same way.
    """
    from apps.rbac.relationships import related_patient_ids_for_request

    # Resolved once per request. The switch is a configuration row, and an
    # organization does not change its mind about privacy halfway through
    # answering one HTTP request -- but until this memo existed, a global
    # search asked the question once per clinical source and read the config
    # table five times to get the same answer. The patient ids beneath are
    # already cached the same way; this is the flag that guards them.
    # The sentinel, not `None`, and for the reason `related_patient_ids_for_
    # request` uses one: `False` is a real answer here, and a cache that treats
    # it as "not looked up yet" recomputes on every call for exactly the
    # organizations that turned the requirement off.
    required = getattr(request, "_relationship_required", "unset")
    if required == "unset":
        required = relationship_required()
        request._relationship_required = required
    if not required:
        return queryset

    allowed = related_patient_ids_for_request(request)
    if allowed is None:
        return queryset
    return queryset.filter(**{f"{patient_field}__in": allowed})
