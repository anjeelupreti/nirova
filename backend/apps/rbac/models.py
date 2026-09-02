"""Roles and their assignment, held in the tenant's own database.

Roles are per-customer data: a hospital's idea of "Ward Sister" is not a
pharmacy chain's. They live in the tenant database alongside the facilities
and departments they are scoped to, so a role assignment is a plain foreign
key rather than a cross-database reference.

The user being assigned lives in the control plane, so `user_id` here is a
bare UUID. That is the one deliberate seam in the model; see
docs/adr/0002-identity-placement.md.
"""

from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.organization.models import Department, Facility, Unit
from apps.rbac.permissions import Scope


class Role(BaseModel):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)

    #: System roles ship with the product and cannot be deleted, so a
    #: customer cannot lock themselves out by tidying up. Their permissions
    #: can still be adjusted -- customers know their own workflows.
    is_system = models.BooleanField(default=False)
    #: Grants every permission. Exactly one such role should exist, and
    #: assignments to it are worth alerting on.
    is_superuser_role = models.BooleanField(default=False)

    #: Permission codes from `apps.rbac.permissions.PERMISSIONS`. Stored as a
    #: list rather than a join table: the set is small, always read whole,
    #: and versioning a role means snapshotting one column.
    permissions = models.JSONField(default=list, blank=True)
    #: Broadest scope this role may be assigned at. A ward nurse role capped
    #: at DEPARTMENT cannot accidentally be granted organization-wide.
    max_scope = models.CharField(
        max_length=24, choices=Scope.CHOICES, default=Scope.FACILITY
    )

    #: Roles this one builds on. Flattened at assignment time.
    inherits_from = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="inherited_by"
    )

    #: Assigning this role needs approval -- for roles that can move money or
    #: change clinical records.
    requires_approval_to_assign = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "role"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name

    def effective_permissions(self, _seen=None) -> set:
        """This role's permissions plus everything it inherits."""
        _seen = _seen or set()
        if self.pk in _seen:
            return set()
        _seen.add(self.pk)

        codes = set(self.permissions or [])
        for parent in self.inherits_from.all():
            codes |= parent.effective_permissions(_seen)
        return codes


class AssignmentStatus(models.TextChoices):
    PENDING = "pending", "Pending approval"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    EXPIRED = "expired", "Expired"
    REVOKED = "revoked", "Revoked"


class RoleAssignment(BaseModel):
    """One user holding one role, within one scope.

    A user may hold several: a consultant who is Head of Department at one
    hospital and a visiting surgeon at another has two assignments with
    different scopes, and the permission check resolves the union.
    """

    #: `identity.User.uuid` in the control plane. No foreign key -- the user
    #: table is in a different database.
    user_id = models.UUIDField(db_index=True)
    user_email = models.CharField(
        max_length=254, blank=True,
        help_text="Denormalised for display, so listing assignments needs no "
                  "cross-database lookup.",
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")

    scope = models.CharField(
        max_length=24, choices=Scope.CHOICES, default=Scope.FACILITY
    )
    #: Populated according to `scope`. Organization scope leaves all three null.
    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    unit = models.ForeignKey(
        Unit, null=True, blank=True, on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    #: For MULTI_FACILITY scope: the facilities covered.
    facility_uuids = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=16, choices=AssignmentStatus.choices,
        default=AssignmentStatus.ACTIVE, db_index=True,
    )
    valid_from = models.DateTimeField(default=timezone.now)
    #: Temporary cover -- a locum, someone acting up during leave. Expiring
    #: on its own is what stops "temporary" access becoming permanent.
    valid_until = models.DateTimeField(null=True, blank=True)

    assigned_by_id = models.UUIDField(null=True, blank=True)
    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "role_assignment"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user_id", "status"]),
            models.Index(fields=["role", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "role", "scope", "facility", "department", "unit"],
                condition=models.Q(status="active"),
                name="uniq_active_role_assignment",
            )
        ]

    def __str__(self):
        return f"{self.user_email or self.user_id} → {self.role.name} ({self.scope})"

    @property
    def is_in_effect(self) -> bool:
        if self.status != AssignmentStatus.ACTIVE:
            return False
        now = timezone.now()
        if self.valid_from > now:
            return False
        return self.valid_until is None or self.valid_until > now


class PermissionOverride(BaseModel):
    """A single permission granted to or withheld from one user.

    The escape hatch that stops role proliferation. When one pharmacist also
    needs to approve stock adjustments, grant that permission rather than
    cloning the pharmacist role. Denials win over grants, so a permission can
    be withheld from someone whose role would otherwise carry it.
    """

    user_id = models.UUIDField(db_index=True)
    user_email = models.CharField(max_length=254, blank=True)
    permission_code = models.CharField(max_length=64, db_index=True)
    #: False withholds the permission even when a role grants it.
    is_granted = models.BooleanField(default=True)
    scope = models.CharField(
        max_length=24, choices=Scope.CHOICES, default=Scope.FACILITY
    )
    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )

    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(help_text="Required: why this person deviates from role.")
    granted_by_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "permission_override"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user_id", "permission_code"])]

    def __str__(self):
        verb = "grant" if self.is_granted else "deny"
        return f"{verb} {self.permission_code} → {self.user_email or self.user_id}"

    @property
    def is_in_effect(self) -> bool:
        now = timezone.now()
        if self.valid_from > now:
            return False
        return self.valid_until is None or self.valid_until > now
