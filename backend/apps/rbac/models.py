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


#: How long an override lasts. Long enough to manage an emergency, short
#: enough that nobody uses one as a way of working. Four hours is roughly a
#: shift's worth of one crisis; a clinician who needs longer is no longer in an
#: emergency and should have a real relationship by then.
BREAK_GLASS_HOURS = 4

#: A reason has to be a sentence somebody can review. "Emergency" is not a
#: reason -- it is the category, and it is the one thing every override has in
#: common, so it distinguishes nothing.
MINIMUM_REASON_LENGTH = 20


class BreakGlassOutcome(models.TextChoices):
    """What a reviewer concluded. Recorded because the queue is the control."""

    PENDING = "pending", "Awaiting review"
    APPROPRIATE = "appropriate", "Appropriate"
    QUERIED = "queried", "Queried with the clinician"
    ESCALATED = "escalated", "Escalated"


class BreakGlassGrant(BaseModel):
    """One person, one patient, one emergency, four hours.

    Rigid access kills people. An unconscious patient arrives and nobody has a
    care relationship with them; a clinician telephoned about a ward they have
    never worked on needs the record now, not after a request is approved. So
    this is granted instantly and refuses nobody.

    **What makes it a control is not the grant, it is the review.** Every one
    writes an audit event at critical severity, raises a `CRITICAL`
    notification to whoever holds `privacy.review`, and stays on a queue until
    a human signs it off. An override nobody reviews is theatre, and this is
    the part most likely to be quietly dropped later for looking like
    paperwork.

    Deliberately **not** an approval workflow, and deliberately **not**
    revocable by the person who used it. Time is what ends it.
    """

    #: `patients.Patient` by UUID rather than a foreign key, so that a grant
    #: survives the record being merged into another. The evidence that
    #: somebody opened a record must outlive tidying up of the record itself.
    patient_uuid = models.UUIDField(db_index=True)
    patient_label = models.CharField(
        max_length=255, blank=True,
        help_text="Name and MRN as they stood when the record was opened.",
    )

    user_id = models.UUIDField(db_index=True)
    user_label = models.CharField(max_length=255, blank=True)

    reason = models.CharField(max_length=512)

    granted_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(db_index=True)

    #: How many times the grant was actually used. A grant taken and never used
    #: is a different fact from one used forty times, and only the second is
    #: worth a conversation.
    use_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    outcome = models.CharField(
        max_length=16, choices=BreakGlassOutcome.choices,
        default=BreakGlassOutcome.PENDING, db_index=True,
    )
    reviewed_by_id = models.UUIDField(null=True, blank=True)
    reviewed_by_name = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "break_glass_grant"
        ordering = ["-granted_at"]
        indexes = [
            models.Index(fields=["user_id", "patient_uuid", "expires_at"]),
            models.Index(fields=["outcome", "-granted_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("granted_at")),
                name="break_glass_expires_after_it_is_granted",
            ),
            # A review is a person and a moment together. Half of one recorded
            # is how a queue comes to look attended-to without anybody having
            # attended to it.
            models.CheckConstraint(
                condition=(
                    models.Q(outcome=BreakGlassOutcome.PENDING,
                             reviewed_at__isnull=True)
                    | models.Q(reviewed_at__isnull=False)
                ),
                name="break_glass_decided_means_reviewed",
            ),
        ]

    def __str__(self):
        return f"{self.user_label or self.user_id} → {self.patient_label}"

    @property
    def is_live(self) -> bool:
        return self.expires_at > timezone.now()

    @property
    def is_reviewed(self) -> bool:
        return self.outcome != BreakGlassOutcome.PENDING
