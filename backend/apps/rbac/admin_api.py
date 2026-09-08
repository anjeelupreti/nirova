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
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import PermissionDeniedError
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
        ]

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


class RoleListView(APIView):
    """Roles that exist, annotated with whether *you* could grant each one."""

    permission_classes = [
        IsAuthenticated, HasPermission.of("role.read", scope=Scope.OWN),
    ]

    def get(self, request):
        _organization(request)
        roles = Role.objects.filter(is_active=True).order_by("name")
        return Response(
            RoleSerializer(
                roles, many=True,
                context={"authorization": get_authorization(request)},
            ).data
        )


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
