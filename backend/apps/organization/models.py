"""The customer's own structure, held inside their own database.

Facility → Department → Unit is the spine every operational module hangs
off. A prescription, a stock movement, a payroll line and a bed all resolve
to a facility; most also resolve to a department. Getting this layer right
is what lets a single-clinic customer and a twelve-hospital group run the
same code.
"""

from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel

# Facility types are declared in the control plane because entitlements are
# expressed in terms of them; re-used here so both sides cannot drift.
from apps.tenancy.models import FacilityType


class FacilityStatus(models.TextChoices):
    PENDING = "pending", "Pending activation"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    CLOSED = "closed", "Closed"


class Facility(BaseModel):
    """A business unit: one hospital, clinic, pharmacy, lab or warehouse.

    Never created directly. Facilities come into existence by executing an
    approved `FacilityChangeRequest`, which is what guarantees that every
    facility was checked against the plan and signed off by someone. See
    `FacilityService.apply_change_request`.
    """

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=64, blank=True)
    facility_type = models.CharField(
        max_length=32, choices=FacilityType.choices, db_index=True
    )
    status = models.CharField(
        max_length=16,
        choices=FacilityStatus.choices,
        default=FacilityStatus.PENDING,
        db_index=True,
    )

    #: Warehouses serving branches, or a flagship hospital with satellites.
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )

    # Nepal administrative geography
    province = models.CharField(max_length=64, blank=True)
    district = models.CharField(max_length=64, blank=True)
    municipality = models.CharField(max_length=128, blank=True)
    ward = models.CharField(max_length=16, blank=True)
    street_address = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)

    #: Facility-level statutory identity. Branches often hold their own
    #: pharmacy or laboratory licence distinct from the organization's.
    pan_number = models.CharField(max_length=20, blank=True)
    license_number = models.CharField(max_length=64, blank=True)
    license_expires_on = models.DateField(null=True, blank=True)

    #: {"sun": [["08:00", "20:00"]], ...}. A list per day, so a clinic that
    #: shuts for lunch is expressible without a second model.
    operating_hours = models.JSONField(default=dict, blank=True)
    is_24x7 = models.BooleanField(default=False)

    timezone = models.CharField(max_length=64, default="Asia/Kathmandu")
    currency = models.CharField(max_length=3, default="NPR")

    opened_on = models.DateField(null=True, blank=True)
    closed_on = models.DateField(null=True, blank=True)
    #: Reference of the change request that created this facility.
    origin_reference = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = "facility"
        ordering = ["name"]
        verbose_name_plural = "facilities"
        indexes = [models.Index(fields=["facility_type", "status"])]

    def __str__(self):
        return f"{self.name} ({self.get_facility_type_display()})"

    @property
    def is_operational(self) -> bool:
        return self.status == FacilityStatus.ACTIVE


class DepartmentKind(models.TextChoices):
    """Broad classification, used for defaults rather than for logic.

    Reporting and costing care whether a department earns revenue, consumes
    it, or supports clinical work -- so that distinction is stored, while the
    specific department names stay the customer's to choose.
    """

    CLINICAL = "clinical", "Clinical"
    DIAGNOSTIC = "diagnostic", "Diagnostic"
    NURSING = "nursing", "Nursing"
    PHARMACY = "pharmacy", "Pharmacy"
    ADMINISTRATIVE = "administrative", "Administrative"
    SUPPORT = "support", "Support services"
    FINANCE = "finance", "Finance"
    OPERATIONS = "operations", "Operations"


class Department(BaseModel):
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="departments"
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    kind = models.CharField(
        max_length=32, choices=DepartmentKind.choices, default=DepartmentKind.CLINICAL
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )

    #: Where this department's revenue and cost land in the ledger. Held here
    #: rather than derived, because organizations restructure departments
    #: without wanting to restate last year's accounts.
    cost_centre_code = models.CharField(max_length=32, blank=True)
    profit_centre_code = models.CharField(max_length=32, blank=True)
    is_revenue_generating = models.BooleanField(default=True)

    head_employee_uuid = models.UUIDField(null=True, blank=True)
    phone_extension = models.CharField(max_length=16, blank=True)
    location_note = models.CharField(max_length=255, blank=True)

    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "department"
        ordering = ["facility_id", "display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_department_code_per_facility",
            )
        ]

    def __str__(self):
        return f"{self.name} — {self.facility.name}"


class Unit(BaseModel):
    """The smallest organizational box: a ward, a counter, a lab bench, a team."""

    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="units"
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=512, blank=True)
    capacity = models.PositiveIntegerField(
        null=True, blank=True, help_text="Beds, chairs or counters, where meaningful."
    )
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "unit"
        ordering = ["department_id", "display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_unit_code_per_department",
            )
        ]

    def __str__(self):
        return f"{self.name} — {self.department.name}"


class ConfigScope(models.TextChoices):
    ORGANIZATION = "organization", "Organization"
    FACILITY = "facility", "Facility"
    DEPARTMENT = "department", "Department"


class ConfigSetting(BaseModel):
    """One configuration value at one level of the hierarchy.

    Configuration resolves platform default → organization → facility →
    department, most specific winning. Storing each level as its own row
    (rather than copying the organization's value down into every facility)
    is what makes "change the VAT rate everywhere except Pokhara" a one-row
    edit instead of a migration.
    """

    scope = models.CharField(max_length=16, choices=ConfigScope.choices, db_index=True)
    #: NULL at organization scope; set at facility or department scope.
    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.CASCADE, related_name="settings"
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="settings",
    )

    namespace = models.CharField(
        max_length=64, db_index=True, help_text="e.g. billing, pharmacy, payroll."
    )
    key = models.CharField(max_length=128, db_index=True)
    value = models.JSONField()

    #: Stops a facility from overriding a value the organization has fixed --
    #: statutory tax rates, controlled-drug rules, approval thresholds.
    is_locked = models.BooleanField(default=False)
    description = models.CharField(max_length=512, blank=True)
    effective_from = models.DateTimeField(default=timezone.now)
    effective_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "config_setting"
        ordering = ["namespace", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "facility", "department", "namespace", "key"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_config_per_scope",
            )
        ]
        indexes = [models.Index(fields=["namespace", "key", "scope"])]

    def __str__(self):
        return f"{self.namespace}.{self.key} @ {self.scope}"

    @property
    def is_in_effect(self) -> bool:
        now = timezone.now()
        if self.effective_from > now:
            return False
        return self.effective_to is None or self.effective_to > now
