"""Staff administration: who can sign in, and what they may do.

**The product had none of this.** Seven permissions -- `user.read`,
`user.invite`, `user.update`, `user.deactivate`, `role.read`, `role.assign`,
`role.manage` -- were defined in the catalogue, granted by several seeded
roles, and checked by no endpoint anywhere. Every account in every Nirova
database was created by a seed script. A hospital that bought this could not
onboard its second member of staff.

It is also what makes the privilege-escalation guard in
`apps.rbac.services.assign_role` do anything. That guard takes an
`assigner_authorization` and refuses to grant authority the assigner does not
hold; it has been inert since it was written because nothing passed the
argument. **Every role assignment here passes it.**

---

**The two-database problem, and where it shows.** `User` and `Membership` are
control-plane rows; `Role` and `RoleAssignment` are tenant rows. "List the
staff with their roles" is therefore a join across two databases that no query
can express, so it is done in Python:

1. Read the memberships for this organization from the control plane.
2. Read the role assignments for those user ids from the tenant.
3. Stitch them together by `user_id`.

Two queries, not N. The obvious implementation -- loop the members and ask for
each one's roles -- is a query per person and looks fine on the demo tenant of
nine and terrible on a hospital of four hundred.

**Why the list is not a `ModelViewSet`.** There is no single model to serialize.
Making one the "primary" and the other a nested field would put the pagination,
filtering and ordering on whichever side happened to be chosen, and the useful
orderings here (by name, by role) are split across the two.
"""

from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import (
    DomainError,
    PermissionDeniedError,
    SegregationOfDutiesViolation,
)
from apps.common.pagination import DefaultPagination
from apps.common.permissions import HasPermission, get_authorization
from apps.identity.models import Membership, MembershipStatus, User
from apps.identity.services import (
    deactivate_membership,
    invite_user,
    reactivate_membership,
    update_user,
)
from apps.rbac.models import AssignmentStatus, Role, RoleAssignment
from apps.rbac.permissions import Scope
from apps.rbac.services import assign_role, revoke_role
from apps.tenancy.context import CONTROL_PLANE_ALIAS


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class AssignedRoleSerializer(serializers.ModelSerializer):
    """One role somebody holds, and where it reaches."""

    role_code = serializers.CharField(source="role.code", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    facility_name = serializers.CharField(
        source="facility.name", read_only=True, default="",
    )
    department_name = serializers.CharField(
        source="department.name", read_only=True, default="",
    )
    scope_label = serializers.SerializerMethodField()

    class Meta:
        model = RoleAssignment
        fields = [
            "uuid", "role_code", "role_name", "scope", "scope_label",
            "facility_name", "department_name", "status", "valid_from",
            "valid_until", "reason",
        ]

    def get_scope_label(self, obj) -> str:
        """"Own facility" is not useful without saying which facility.

        The scope alone reads the same for two people with very different
        reach, and an administration screen whose rows look identical for
        different access is a screen that teaches nobody anything.
        """
        label = dict(Scope.CHOICES).get(obj.scope, obj.scope)
        where = obj.department.name if obj.department_id else (
            obj.facility.name if obj.facility_id else ""
        )
        return f"{label} — {where}" if where else label


class StaffMemberSerializer(serializers.Serializer):
    """A person, their membership, and the roles they hold.

    A plain `Serializer`, not a `ModelSerializer`: the object is a dict
    assembled from two databases and has no model to point at.
    """

    uuid = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.CharField()
    phone = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    is_organization_owner = serializers.BooleanField()
    consumes_seat = serializers.BooleanField()
    invited_at = serializers.DateTimeField(allow_null=True)
    joined_at = serializers.DateTimeField(allow_null=True)
    last_active_at = serializers.DateTimeField(allow_null=True)
    mfa_enabled = serializers.BooleanField(default=False)
    # Never a password hash, never `is_platform_staff`. An organization
    # administrator has no business knowing which of their colleagues is also
    # a member of the vendor's staff.
    roles = AssignedRoleSerializer(many=True)


class InviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    consumes_seat = serializers.BooleanField(default=True)
    # Optional: invite and grant in one act, which is what an administrator
    # actually wants to do. Validated exactly as a separate grant would be --
    # `assign_role` is the same call either way, escalation guard included.
    role_code = serializers.CharField(required=False, allow_blank=True)
    scope = serializers.ChoiceField(
        choices=[code for code, _ in Scope.CHOICES],
        required=False,
        default=Scope.FACILITY,
    )
    facility_uuid = serializers.UUIDField(required=False, allow_null=True)
    department_uuid = serializers.UUIDField(required=False, allow_null=True)


class UpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255, required=False)
    preferred_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True,
    )
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)


class GrantSerializer(serializers.Serializer):
    role_code = serializers.CharField()
    scope = serializers.ChoiceField(
        choices=[code for code, _ in Scope.CHOICES], default=Scope.FACILITY,
    )
    facility_uuid = serializers.UUIDField(required=False, allow_null=True)
    department_uuid = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField(
        max_length=512, required=False, allow_blank=True,
    )


class RoleSerializer(serializers.ModelSerializer):
    """A role somebody could be granted, and what it carries."""

    permission_count = serializers.SerializerMethodField()
    grantable = serializers.SerializerMethodField()
    beyond_your_authority = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "uuid", "code", "name", "description", "max_scope",
            "permissions", "permission_count", "requires_approval_to_assign",
            "grantable", "beyond_your_authority",
            # Added when the role editor was built. Without them a screen
            # cannot tell a customer's own role from one that ships with the
            # product, so it either offers a delete that will be refused or
            # hides it from everything -- and `grantable_roles` is the field
            # that makes delegation legible rather than mysterious.
            "is_system", "is_superuser_role", "grantable_roles",
            "display_order", "editable", "deletable", "holders",
        ]

    editable = serializers.SerializerMethodField()
    deletable = serializers.SerializerMethodField()
    holders = serializers.SerializerMethodField()

    def get_editable(self, obj) -> bool:
        """Whether *this* caller could save a change to it.

        Computed here for the same reason `grantable` is: a form somebody
        fills in and is then refused is worse than a control that was never
        offered. The superuser role is nobody's to edit.
        """
        if obj.is_superuser_role:
            return False
        authorization = self.context.get("authorization")
        if authorization is None:
            return False
        if getattr(authorization, "is_organization_owner", False):
            return True
        return authorization.has("role.manage", Scope.OWN)

    def get_deletable(self, obj) -> bool:
        """System roles stay; held roles stay until they are not held."""
        if obj.is_system or obj.is_superuser_role:
            return False
        return self.get_editable(obj) and self.get_holders(obj) == 0

    def get_holders(self, obj) -> int:
        """How many people hold it, active assignments only.

        Read from a map the view attaches when it has one, so a list of
        fifteen roles is one query rather than fifteen. Falls back to counting
        for the detail view, where there is a single row and no map.
        """
        counts = self.context.get("holder_counts")
        if counts is not None:
            return counts.get(obj.pk, 0)
        return RoleAssignment.objects.filter(
            role=obj, status=AssignmentStatus.ACTIVE,
        ).count()

    def get_permission_count(self, obj) -> int:
        return len(obj.permissions or [])

    def get_grantable(self, obj) -> bool:
        """Whether *this* caller could grant it.

        Computed here so the screen can grey out what would be refused, rather
        than letting somebody fill in a form and submit it to find out. The
        answer is advisory: `assign_role` re-decides it on the way in, because
        a client-side hint is a convenience and never a control.
        """
        return not self._beyond(obj)

    def get_beyond_your_authority(self, obj) -> list:
        """Which permissions put it out of reach -- the first five.

        "You cannot grant this" is a dead end; "you cannot grant this because
        it carries `payroll.approve`, which you do not hold" tells somebody
        what to ask their own administrator for.
        """
        return self._beyond(obj)[:5]

    def _beyond(self, obj) -> list:
        """The permissions putting this role out of the caller's reach.

        Empty when the caller may grant it -- which now includes the case
        where a role is *delegable* to them without their holding everything
        it carries. `_may_delegate` is imported from the service rather than
        reimplemented, so this hint cannot drift from the rule that actually
        decides: a greyed-out button that submits fine, or an enabled one that
        is refused, are both worse than no hint at all.
        """
        from apps.rbac.services import _may_delegate

        authorization = self.context.get("authorization")
        if authorization is None:
            return []
        if getattr(authorization, "is_organization_owner", False):
            return []
        if _may_delegate(authorization, obj):
            return []
        return sorted(set(obj.permissions or []) - set(authorization.permissions))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _roles_by_user(user_ids) -> dict:
    """Active role assignments for these users, keyed by user id.

    One query for the whole page. See the module docstring: the per-person
    version is invisible on nine people and ruinous on four hundred.
    """
    grouped = {}
    rows = (
        RoleAssignment.objects.filter(
            user_id__in=list(user_ids), status=AssignmentStatus.ACTIVE,
        )
        .select_related("role", "facility", "department")
        .order_by("role__name")
    )
    for row in rows:
        grouped.setdefault(row.user_id, []).append(row)
    return grouped


def _member_payload(membership, roles) -> dict:
    user = membership.user
    return {
        "uuid": user.uuid,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "status": membership.status,
        "is_organization_owner": membership.is_organization_owner,
        "consumes_seat": membership.consumes_seat,
        "invited_at": membership.invited_at,
        "joined_at": membership.joined_at,
        "last_active_at": user.last_active_at,
        # Whether they have two-step sign-in — an administrator deciding who
        # to chase before a security review needs to see it, and the reset
        # action only makes sense where it is on.
        "mfa_enabled": user.mfa_enabled,
        "roles": roles,
    }


def _organization(request):
    """The `Organization` row, not the tenant context.

    `TenantContextMiddleware` sets **both**: `request.tenant` is a
    `TenantContext` dataclass -- slug, database alias, optional facility -- and
    `request.organization` is the model instance. They are easy to confuse and
    the failure is loud but late: filtering `Membership.objects.filter(
    organization=request.tenant)` raises `Field 'id' expected a number but got
    TenantContext(...)` at query time, which is how this was found.
    """
    organization = getattr(request, "organization", None)
    if organization is None:
        raise PermissionDeniedError(
            "No organization selected. Send the X-Organization header.",
        )
    return organization


def _holder_counts(roles) -> dict:
    """How many people hold each of these roles, in one query.

    The obvious implementation is a count per role, which is fine against
    fifteen seeded roles and is a query per row on a customer who has written
    forty of their own. `values(...).annotate(...)` is one round trip whatever
    the number.
    """
    from django.db.models import Count

    rows = (
        RoleAssignment.objects
        .filter(role__in=roles, status=AssignmentStatus.ACTIVE)
        .values("role_id")
        .annotate(total=Count("id"))
    )
    return {row["role_id"]: row["total"] for row in rows}


def _scope_targets(scope, facility_uuid, department_uuid):
    """Resolve the facility and department a grant names.

    Returns `(facility, department)`, either of which may be `None`.
    `assign_role` refuses a narrow scope that names neither -- a scope that
    names nothing reaches nothing -- so this does not need to re-check that;
    it only has to turn uuids into rows and refuse ones that do not exist.
    """
    from apps.organization.models import Department, Facility

    facility = department = None
    if facility_uuid:
        facility = Facility.objects.filter(uuid=facility_uuid).first()
        if facility is None:
            raise PermissionDeniedError("No such facility.")
    if department_uuid:
        department = Department.objects.filter(uuid=department_uuid).first()
        if department is None:
            raise PermissionDeniedError("No such department.")
        # A department implies its facility. Taking it from the department
        # rather than from the caller means the two cannot disagree.
        facility = facility or department.facility
    return facility, department


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class StaffListView(APIView):
    """The people in this organization, and what each of them may do.

    `user.read` to look; `user.invite` to POST. Two codes rather than one,
    because seeing who your colleagues are and being able to create a login
    are very different authorities -- a ward clerk may reasonably need the
    first to know who to call.
    """

    permission_classes = [
        IsAuthenticated,
        HasPermission.of("user.read", scope=Scope.OWN, write="user.invite"),
    ]

    def get(self, request):
        organization = _organization(request)

        memberships = (
            Membership.objects.filter(organization=organization)
            .select_related("user")
            .order_by("user__full_name", "user__email")
        )

        # Revoked people are hidden by default and findable on request: an
        # administration screen that shows every leaver for ever is one nobody
        # scrolls, and one that cannot show them at all cannot answer "did we
        # ever give Ram access?".
        wanted = request.query_params.get("status", MembershipStatus.ACTIVE)
        if wanted != "all":
            memberships = memberships.filter(status=wanted)

        search = (request.query_params.get("q") or "").strip()
        if search:
            from django.db.models import Q

            memberships = memberships.filter(
                Q(user__full_name__icontains=search)
                | Q(user__email__icontains=search)
            )

        paginator = DefaultPagination()
        page = paginator.paginate_queryset(memberships, request, view=self)

        roles = _roles_by_user([m.user.uuid for m in page])
        payload = [
            _member_payload(m, roles.get(m.user.uuid, [])) for m in page
        ]
        return paginator.get_paginated_response(
            StaffMemberSerializer(payload, many=True).data
        )

    def post(self, request):
        organization = _organization(request)
        authorization = get_authorization(request)
        form = InviteSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data

        user, _ = invite_user(
            organization,
            email=data["email"],
            full_name=data["full_name"],
            actor=request.user,
            consumes_seat=data["consumes_seat"],
        )
        if data.get("phone"):
            update_user(user, actor=request.user, phone=data["phone"])

        # The role, if one was asked for. Deliberately *after* the membership
        # exists and outside its transaction: if this is refused -- and the
        # escalation guard may well refuse it -- the invitation still stands
        # and the administrator grants a role they are allowed to grant. The
        # alternative, rolling the invitation back, would mean an escalation
        # attempt silently discarded a colleague's account.
        if data.get("role_code"):
            facility, department = _scope_targets(
                data["scope"], data.get("facility_uuid"),
                data.get("department_uuid"),
            )
            assign_role(
                user, data["role_code"], scope=data["scope"],
                facility=facility, department=department,
                assigned_by=request.user,
                reason=f"Granted on invitation by {request.user.email}",
                assigner_authorization=authorization,
            )

        membership = Membership.objects.get(user=user, organization=organization)
        roles = _roles_by_user([user.uuid]).get(user.uuid, [])
        return Response(
            StaffMemberSerializer(_member_payload(membership, roles)).data,
            status=status.HTTP_201_CREATED,
        )


class StaffMemberView(APIView):
    """One person: their details, and whether they still have access."""

    permission_classes = [
        IsAuthenticated,
        HasPermission.of("user.read", scope=Scope.OWN, write="user.update"),
    ]

    def _membership(self, request, uuid):
        organization = _organization(request)
        membership = (
            Membership.objects.select_related("user")
            .filter(user__uuid=uuid, organization=organization)
            .first()
        )
        if membership is None:
            raise PermissionDeniedError("No such person in this organization.")
        return membership

    def get(self, request, uuid):
        membership = self._membership(request, uuid)
        roles = _roles_by_user([membership.user.uuid]).get(membership.user.uuid, [])
        return Response(
            StaffMemberSerializer(_member_payload(membership, roles)).data
        )

    def patch(self, request, uuid):
        membership = self._membership(request, uuid)
        form = UpdateSerializer(data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        update_user(membership.user, actor=request.user, **form.validated_data)
        membership.refresh_from_db()
        roles = _roles_by_user([membership.user.uuid]).get(membership.user.uuid, [])
        return Response(
            StaffMemberSerializer(_member_payload(membership, roles)).data
        )


class StaffDeactivateView(APIView):
    """Ending and restoring somebody's access.

    Its own view, and its own permission. `user.update` corrects a misspelled
    name; `user.deactivate` takes a colleague's access away and revokes every
    role they hold. Putting both behind one code would mean whoever fixes typos
    can also lock out the finance director.
    """

    permission_classes = [
        IsAuthenticated,
        HasPermission.of(
            "user.deactivate", scope=Scope.OWN, write="user.deactivate",
        ),
    ]

    def post(self, request, uuid):
        organization = _organization(request)
        user = User.objects.filter(uuid=uuid).first()
        if user is None:
            raise PermissionDeniedError("No such person.")

        # **You may not lock yourself out.** Not because it would be insecure
        # -- it is your own access -- but because the last administrator doing
        # it by accident leaves an organization nobody can administer, and the
        # only repair is a support ticket to the vendor.
        if user.uuid == request.user.uuid:
            raise PermissionDeniedError(
                "You cannot deactivate your own account.",
            )

        reason = (request.data or {}).get("reason", "")
        if request.query_params.get("undo") == "1":
            membership = reactivate_membership(
                organization, user, actor=request.user, reason=reason,
            )
        else:
            membership = deactivate_membership(
                organization, user, actor=request.user, reason=reason,
            )

        roles = _roles_by_user([user.uuid]).get(user.uuid, [])
        return Response(
            StaffMemberSerializer(_member_payload(membership, roles)).data
        )


class StaffPasswordView(APIView):
    """`POST staff/<uuid>/password/` — issue a one-time password.

    Behind `user.deactivate`, the strongest of the user-administration
    permissions, deliberately: whoever can set a colleague's password can sign
    in as them until they change it, which is at least as consequential as
    taking their access away. The service refuses the cases that would reach
    beyond this organization; see `issue_temporary_password`.
    """

    permission_classes = [
        IsAuthenticated,
        HasPermission.of("user.deactivate", scope=Scope.OWN, write="user.deactivate"),
    ]

    def post(self, request, uuid):
        from apps.identity.services import IdentityError, issue_temporary_password

        organization = _organization(request)
        user = User.objects.filter(uuid=uuid).first()
        if user is None:
            raise PermissionDeniedError("No such person.")
        try:
            temporary = issue_temporary_password(
                organization, user, actor=request.user,
                reason=(request.data or {}).get("reason", ""),
            )
        except IdentityError as problem:
            return Response(
                {"code": "refused", "message": str(problem)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            "email": user.email,
            "temporary_password": temporary,
            "must_change_password": True,
        })


class StaffSecondFactorResetView(APIView):
    """`POST staff/<uuid>/mfa-reset/ {reason}` — for a lost phone.

    Behind `user.deactivate` for the same reason as the temporary password:
    it weakens how somebody signs in, which is as consequential as removing
    their access. The service draws the same organizational lines.
    """

    permission_classes = [
        IsAuthenticated,
        HasPermission.of("user.deactivate", scope=Scope.OWN, write="user.deactivate"),
    ]

    def post(self, request, uuid):
        from apps.identity.services import IdentityError, reset_second_factor

        organization = _organization(request)
        user = User.objects.filter(uuid=uuid).first()
        if user is None:
            raise PermissionDeniedError("No such person.")
        try:
            reset_second_factor(
                organization, user, actor=request.user,
                reason=(request.data or {}).get("reason", ""),
            )
        except IdentityError as problem:
            return Response(
                {"code": "refused", "message": str(problem)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"email": user.email, "mfa_enabled": False})


class PermissionCatalogueView(APIView):
    """Every permission this product defines, grouped for a role editor.

    **`grouped_permissions()` has existed in `apps/rbac/permissions.py` since
    the catalogue was written, with the docstring "for rendering the role
    editor", and no endpoint served it.** So the console grouped permissions by
    parsing the code's prefix -- a stand-in that got `patient.clinical.read`
    into "Patients" by luck and would have got a new module wrong. This is the
    real thing: the group each permission was *declared* in, its label, its
    description, whether it is sensitive, and what it conflicts with.

    `role.read` rather than `role.manage`: knowing what a permission means is
    what makes the role list readable, and somebody who may look at roles must
    be able to.
    """

    permission_classes = [
        IsAuthenticated, HasPermission.of("role.read", scope=Scope.OWN),
    ]

    def get(self, request):
        from apps.rbac.permissions import grouped_permissions

        _organization(request)
        groups = grouped_permissions()
        return Response({
            "groups": [
                {"group": name, "permissions": permissions}
                for name, permissions in sorted(groups.items())
            ],
            "count": sum(len(items) for items in groups.values()),
        })


class RoleWriteSerializer(serializers.Serializer):
    """The editable half of a role.

    `code` is accepted on create and ignored on update: it is what
    `grantable_roles` and every seed reference by, and letting somebody rename
    it would silently break both. The name is what people read; the code is
    what the system means.
    """

    code = serializers.SlugField(max_length=64, required=False)
    name = serializers.CharField(max_length=128)
    description = serializers.CharField(allow_blank=True, required=False, default="")
    permissions = serializers.ListField(
        child=serializers.CharField(max_length=64), allow_empty=True,
    )
    max_scope = serializers.ChoiceField(
        choices=[choice[0] for choice in Scope.CHOICES], default=Scope.FACILITY,
    )
    grantable_roles = serializers.ListField(
        child=serializers.SlugField(max_length=64), required=False, default=list,
    )
    requires_approval_to_assign = serializers.BooleanField(default=False)
    display_order = serializers.IntegerField(default=100, min_value=0, max_value=32767)


def _validate_role_write(data, authorization, existing=None):
    """The four rules a role must satisfy before it is written.

    Kept out of the serializer because three of them need the *caller's*
    authority, and a serializer that reaches for the request is a serializer
    that cannot be tested on its own.
    """
    from apps.rbac.permissions import PERMISSION_MAP
    from apps.rbac.services import check_segregation_of_duties

    codes = sorted(set(data["permissions"]))

    # 1. Every code must exist. **Fails closed**, and this is not pedantry: an
    #    unknown code is stored happily by a JSONField, resolves to nothing at
    #    check time, and produces a role that looks powerful in the editor and
    #    does nothing on the ward. A typo must be a 400, not a mystery.
    unknown = [code for code in codes if code not in PERMISSION_MAP]
    if unknown:
        raise DomainError(
            "These permissions do not exist.",
            detail={"unknown_permissions": unknown},
            code="unknown_permission",
        )

    # 2. Segregation of duties, at design time. The service has done this
    #    since it was written; nothing ever called it, because nothing ever
    #    saved a role through an API.
    conflicts = check_segregation_of_duties(codes)
    if conflicts:
        raise SegregationOfDutiesViolation(
            "These permissions may not be held by the same person.",
            detail={"conflicts": [list(pair) for pair in conflicts]},
        )

    # 3. **You may not create authority you do not hold.** Without this,
    #    `role.manage` is a privilege-escalation primitive: anybody who may
    #    edit roles writes themselves one carrying `payroll.approve` and
    #    assigns it. `assign_role` would catch the assignment, but only
    #    because `_assert_may_grant` re-checks -- and depending on a second
    #    guard for the first one's job is how both eventually get removed.
    #
    #    The organization owner is exempt, as they are everywhere: they
    #    already hold everything.
    if not getattr(authorization, "is_organization_owner", False):
        beyond = sorted(set(codes) - set(authorization.permissions))
        if beyond:
            raise PermissionDeniedError(
                "A role cannot carry permissions you do not hold yourself.",
                detail={"beyond_your_authority": beyond},
            )

    # 4. The superuser role is not editable through this door. It grants
    #    everything by definition, so "edit" means only "make it grant less",
    #    which is a lockout waiting to happen and belongs in a migration with
    #    somebody watching.
    if existing is not None and existing.is_superuser_role:
        raise PermissionDeniedError(
            "The superuser role cannot be edited through the API.",
        )

    return codes


class RoleListView(APIView):
    """Roles that exist, annotated with whether *you* could grant each one.

    `role.read` to look, `role.manage` to create -- the same split as
    `StaffListView`. Reading the roles is how anybody understands the access
    model; writing one is an administrative act.
    """

    permission_classes = [
        IsAuthenticated,
        HasPermission.of("role.read", scope=Scope.OWN, write="role.manage"),
    ]

    def get(self, request):
        _organization(request)
        roles = list(Role.objects.filter(is_active=True).order_by("name"))
        return Response(
            RoleSerializer(
                roles, many=True,
                context={
                    "authorization": get_authorization(request),
                    # One aggregate for the whole list rather than a count per
                    # role. The obvious version is a query per row and looks
                    # fine against fifteen seeded roles.
                    "holder_counts": _holder_counts(roles),
                },
            ).data
        )

    @transaction.atomic
    def post(self, request):
        _organization(request)
        authorization = get_authorization(request)

        serializer = RoleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        code = data.get("code") or slugify(data["name"])[:64]
        if not code:
            raise DomainError("A role needs a code.", code="invalid_role_code")
        if Role.objects.filter(code=code).exists():
            raise DomainError(
                f"A role with the code '{code}' already exists.",
                detail={"code": code},
                code="role_exists",
            )

        codes = _validate_role_write(data, authorization)

        role = Role.objects.create(
            code=code,
            name=data["name"],
            description=data.get("description", ""),
            permissions=codes,
            max_scope=data["max_scope"],
            grantable_roles=data.get("grantable_roles", []),
            requires_approval_to_assign=data["requires_approval_to_assign"],
            display_order=data["display_order"],
            # Never through this door. A customer-written role is theirs to
            # delete; marking one `is_system` would make it undeletable and
            # there is no way back without a migration.
            is_system=False,
            is_superuser_role=False,
        )
        return Response(
            RoleSerializer(role, context={"authorization": authorization}).data,
            status=status.HTTP_201_CREATED,
        )


class RoleDetailView(APIView):
    """One role: read it, edit it, or retire it."""

    permission_classes = [
        IsAuthenticated,
        HasPermission.of("role.read", scope=Scope.OWN, write="role.manage"),
    ]

    def _role(self, uuid):
        role = Role.objects.filter(uuid=uuid).first()
        if role is None:
            raise DomainError(
                "No such role.", code="not_found", detail={"uuid": str(uuid)},
            )
        return role

    def get(self, request, uuid):
        _organization(request)
        return Response(
            RoleSerializer(
                self._role(uuid),
                context={"authorization": get_authorization(request)},
            ).data
        )

    @transaction.atomic
    def patch(self, request, uuid):
        _organization(request)
        authorization = get_authorization(request)
        role = self._role(uuid)

        # `partial=True` would let a caller send `{"name": "x"}` and have
        # `permissions` default to `[]` -- silently emptying the role. So the
        # current values are merged in first and the whole thing is validated,
        # which also means the segregation check always sees the final set
        # rather than the delta.
        merged = {
            "name": role.name,
            "description": role.description,
            "permissions": list(role.permissions or []),
            "max_scope": role.max_scope,
            "grantable_roles": list(role.grantable_roles or []),
            "requires_approval_to_assign": role.requires_approval_to_assign,
            "display_order": role.display_order,
            **{
                key: value for key, value in request.data.items()
                # `code` and the two flags are not editable; see above.
                if key in {
                    "name", "description", "permissions", "max_scope",
                    "grantable_roles", "requires_approval_to_assign",
                    "display_order",
                }
            },
        }

        serializer = RoleWriteSerializer(data=merged)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        codes = _validate_role_write(data, authorization, existing=role)

        role.name = data["name"]
        role.description = data.get("description", "")
        role.permissions = codes
        role.max_scope = data["max_scope"]
        role.grantable_roles = data.get("grantable_roles", [])
        role.requires_approval_to_assign = data["requires_approval_to_assign"]
        role.display_order = data["display_order"]
        role.save()

        return Response(
            RoleSerializer(role, context={"authorization": authorization}).data
        )

    @transaction.atomic
    def delete(self, request, uuid):
        """Retire a role. Never a hard delete, and never while it is held.

        Two refusals, both deliberate:

        **A system role stays.** They ship with the product, seeds reference
        them by code, and a customer who tidies one away has broken their own
        next migration. Their permissions are editable -- customers know their
        own workflows -- but the row is not theirs to remove.

        **A held role stays until it is not held.** Deactivating a role that
        forty people hold would take their access away in one request, with no
        record against any of them, and the audit would show a role edit rather
        than forty revocations. Revoke first; the message says how many.
        """
        _organization(request)
        role = self._role(uuid)

        if role.is_system:
            raise PermissionDeniedError(
                f"'{role.name}' ships with the product and cannot be removed. "
                "Its permissions can still be changed.",
                detail={"role": role.code},
            )

        holders = RoleAssignment.objects.filter(
            role=role, status=AssignmentStatus.ACTIVE,
        ).count()
        if holders:
            raise DomainError(
                f"{holders} "
                f"{'person holds' if holders == 1 else 'people hold'} this role. "
                "Revoke it from them first, so each revocation is recorded "
                "against the person it affects.",
                detail={"holders": holders, "role": role.code},
                code="role_in_use",
            )

        role.is_active = False
        role.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffRolesView(APIView):
    """Granting and revoking one person's roles.

    `role.assign` on both verbs. Taking a role away is exactly as consequential
    as giving one -- more so, in the moment somebody needs it -- and a system
    where revocation is the easier act invites its use as a weapon.
    """

    permission_classes = [
        IsAuthenticated,
        HasPermission.of("role.assign", scope=Scope.OWN, write="role.assign"),
    ]

    def post(self, request, uuid):
        organization = _organization(request)
        authorization = get_authorization(request)
        user = User.objects.filter(uuid=uuid).first()
        if user is None or not Membership.objects.filter(
            user=user, organization=organization,
            status=MembershipStatus.ACTIVE,
        ).exists():
            raise PermissionDeniedError(
                "That person is not an active member of this organization.",
            )

        form = GrantSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data

        facility, department = _scope_targets(
            data["scope"], data.get("facility_uuid"),
            data.get("department_uuid"),
        )
        assignment = assign_role(
            user, data["role_code"], scope=data["scope"],
            facility=facility, department=department,
            assigned_by=request.user,
            reason=data.get("reason") or f"Granted by {request.user.email}",
            # **This is the argument the escalation guard has been waiting
            # for.** Nobody may grant an authority they do not hold, and the
            # guard cannot know who is asking unless the API says.
            assigner_authorization=authorization,
        )
        return Response(
            AssignedRoleSerializer(assignment).data,
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, uuid, assignment_uuid=None):
        organization = _organization(request)
        user = User.objects.filter(uuid=uuid).first()
        if user is None:
            raise PermissionDeniedError("No such person.")

        assignment = (
            RoleAssignment.objects.select_related("role")
            .filter(uuid=assignment_uuid, user_id=user.uuid)
            .first()
        )
        if assignment is None:
            raise PermissionDeniedError("No such role assignment.")

        # The same reasoning as self-deactivation, one level finer: revoking
        # your own last administrative role locks you out just as thoroughly.
        if user.uuid == request.user.uuid:
            raise PermissionDeniedError(
                "You cannot revoke your own roles. Ask a colleague.",
            )
        if Membership.objects.filter(
            user=user, organization=organization, is_organization_owner=True,
        ).exists():
            raise PermissionDeniedError(
                "The organization owner's roles cannot be revoked.",
            )

        revoke_role(
            assignment, actor=request.user,
            reason=(request.data or {}).get("reason", "")
            or f"Revoked by {request.user.email}",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
