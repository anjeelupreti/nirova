"""Control-plane records describing customers and where their data lives."""

from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel

slug_validator = RegexValidator(
    r"^[a-z][a-z0-9_]{2,48}$",
    "Use lowercase letters, digits and underscores; must start with a letter.",
)


class OrganizationStatus(models.TextChoices):
    PENDING = "pending", "Pending provisioning"
    TRIAL = "trial", "Trial"
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past due"
    SUSPENDED = "suspended", "Suspended"
    CANCELLED = "cancelled", "Cancelled"


class BusinessType(models.TextChoices):
    """What the customer is, which seeds their initial module selection."""

    CLINIC = "clinic", "Clinic"
    HOSPITAL = "hospital", "Hospital"
    PHARMACY = "pharmacy", "Pharmacy"
    LABORATORY = "laboratory", "Laboratory"
    DIAGNOSTIC = "diagnostic", "Diagnostic centre"
    POLYCLINIC = "polyclinic", "Polyclinic"
    CHAIN = "chain", "Multi-branch chain"
    GROUP = "group", "Healthcare group"
    DISTRIBUTOR = "distributor", "Pharmaceutical distributor"


class Organization(BaseModel):
    """A customer. The billing entity, the tenant, the isolation boundary.

    A hospital is *not* an organization -- it is a facility belonging to one.
    A single-hospital customer therefore has one organization with one
    facility inside it, and grows into a chain without restructuring.
    """

    slug = models.SlugField(
        max_length=50,
        unique=True,
        validators=[slug_validator],
        help_text="Immutable. Used for the tenant database name and subdomain.",
    )
    legal_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    business_type = models.CharField(
        max_length=32, choices=BusinessType.choices, default=BusinessType.CLINIC
    )
    status = models.CharField(
        max_length=16,
        choices=OrganizationStatus.choices,
        default=OrganizationStatus.PENDING,
        db_index=True,
    )

    # Nepal statutory identity
    pan_number = models.CharField(max_length=20, blank=True)
    vat_number = models.CharField(max_length=20, blank=True)
    registration_number = models.CharField(max_length=64, blank=True)

    primary_email = models.EmailField()
    primary_phone = models.CharField(max_length=32, blank=True)
    website = models.URLField(blank=True)

    province = models.CharField(max_length=64, blank=True)
    district = models.CharField(max_length=64, blank=True)
    municipality = models.CharField(max_length=128, blank=True)
    ward = models.CharField(max_length=16, blank=True)
    street_address = models.CharField(max_length=255, blank=True)

    # Nepal fiscal years run mid-July to mid-July; the start is configurable
    # because organizations migrating from other systems keep their own.
    fiscal_year_start_month = models.PositiveSmallIntegerField(default=4)
    fiscal_year_start_day = models.PositiveSmallIntegerField(default=1)
    uses_bikram_sambat = models.BooleanField(default=True)

    logo_url = models.URLField(blank=True)
    primary_color = models.CharField(max_length=9, blank=True)
    locale = models.CharField(max_length=10, default="en-NP")
    timezone = models.CharField(max_length=64, default="Asia/Kathmandu")

    trial_ends_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "cp_organization"
        ordering = ["display_name"]
        indexes = [
            models.Index(fields=["status", "business_type"]),
        ]

    def __str__(self):
        return self.display_name

    @property
    def is_operational(self) -> bool:
        """Whether users may transact. Past-due tenants stay readable."""
        return self.status in {
            OrganizationStatus.TRIAL,
            OrganizationStatus.ACTIVE,
            OrganizationStatus.PAST_DUE,
        }

    @property
    def is_read_only(self) -> bool:
        return self.status in {
            OrganizationStatus.SUSPENDED,
            OrganizationStatus.CANCELLED,
        }


class TenantDatabaseStatus(models.TextChoices):
    PENDING = "pending", "Pending creation"
    PROVISIONING = "provisioning", "Provisioning"
    MIGRATING = "migrating", "Migrating"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"
    ARCHIVED = "archived", "Archived"


class TenantDatabase(BaseModel):
    """Connection details for one organization's dedicated database.

    Storing host/port per tenant (rather than deriving them from settings)
    is what makes it possible to move a large customer onto its own database
    server later without touching application code -- update the row and the
    next request connects somewhere else.
    """

    organization = models.OneToOneField(
        Organization, on_delete=models.PROTECT, related_name="database"
    )
    alias = models.CharField(
        max_length=64,
        unique=True,
        help_text="Django connection alias, e.g. tenant_manakamana.",
    )
    db_name = models.CharField(max_length=128, unique=True)
    host = models.CharField(max_length=255)
    port = models.CharField(max_length=8, default="5432")
    db_user = models.CharField(max_length=128)
    # Kept out of the API layer entirely; in production this holds a secrets
    # manager reference rather than the literal password.
    db_password = models.CharField(max_length=255)

    status = models.CharField(
        max_length=16,
        choices=TenantDatabaseStatus.choices,
        default=TenantDatabaseStatus.PENDING,
        db_index=True,
    )
    schema_version = models.CharField(max_length=64, blank=True)
    last_migrated_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    region = models.CharField(max_length=64, default="default")
    is_read_only = models.BooleanField(default=False)

    last_backup_at = models.DateTimeField(null=True, blank=True)
    backup_location = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "cp_tenant_database"
        ordering = ["alias"]

    def __str__(self):
        return f"{self.alias} ({self.get_status_display()})"

    def as_connection_settings(self) -> dict:
        from django.conf import settings

        template = settings.TENANT_DATABASE
        return {
            "ENGINE": template["ENGINE"],
            "NAME": self.db_name,
            "HOST": self.host,
            "PORT": self.port,
            "USER": self.db_user,
            "PASSWORD": self.db_password,
            "CONN_MAX_AGE": template.get("CONN_MAX_AGE", 60),
            "ATOMIC_REQUESTS": False,
            "AUTOCOMMIT": True,
            "CONN_HEALTH_CHECKS": True,
            "TIME_ZONE": None,
            "OPTIONS": {},
            "TEST": {},
        }


class FacilityType(models.TextChoices):
    """Shared by the control plane and every tenant database.

    Defined here rather than in the tenant app because entitlements are
    expressed per facility type ("max 3 pharmacies") and the control plane
    has to reason about them without opening a tenant connection.
    """

    HOSPITAL = "hospital", "Hospital"
    CLINIC = "clinic", "Clinic"
    PHARMACY = "pharmacy", "Pharmacy"
    LABORATORY = "laboratory", "Laboratory"
    DIAGNOSTIC = "diagnostic", "Diagnostic centre"
    WAREHOUSE = "warehouse", "Warehouse"
    CORPORATE_OFFICE = "corporate_office", "Corporate office"
    OTHER = "other", "Other"


class FacilityRegistryStatus(models.TextChoices):
    PENDING = "pending", "Pending approval"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    CLOSED = "closed", "Closed"


class FacilityRegistryEntry(BaseModel):
    """A non-clinical mirror of a tenant facility, kept in the control plane.

    Two jobs, both of which need facility data without a tenant connection:

    1. Quota enforcement -- "does this organization already have 3 pharmacies?"
       must be answerable inside the same transaction that approves a fourth.
    2. Platform analytics -- counting hospitals across every customer would
       otherwise mean opening every tenant database in turn.

    It holds no patient, clinical or financial data. It is written only by
    `apps.organization.services.FacilityService`, which keeps the two sides
    consistent in one transaction.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="facility_registry"
    )
    #: `Facility.uuid` in the tenant database. Not a foreign key -- different
    #: database.
    facility_uuid = models.UUIDField(unique=True)
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    facility_type = models.CharField(
        max_length=32, choices=FacilityType.choices, db_index=True
    )
    status = models.CharField(
        max_length=16,
        choices=FacilityRegistryStatus.choices,
        default=FacilityRegistryStatus.PENDING,
        db_index=True,
    )

    province = models.CharField(max_length=64, blank=True)
    district = models.CharField(max_length=64, blank=True)
    municipality = models.CharField(max_length=128, blank=True)

    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    #: Set when a facility is closed, so a later re-open can be recognised as
    #: a re-open rather than counted as fresh growth.
    reopened_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "cp_facility_registry"
        ordering = ["organization_id", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_facility_code_per_org",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "facility_type", "status"]),
        ]

    def __str__(self):
        return f"{self.name} [{self.get_facility_type_display()}]"

    @property
    def counts_towards_quota(self) -> bool:
        """Closed facilities free their slot; suspended ones do not.

        Suspension is a temporary state the organization can reverse at will,
        so releasing the slot would let a customer hold more facilities than
        they pay for by rotating suspensions.
        """
        return self.status in {
            FacilityRegistryStatus.PENDING,
            FacilityRegistryStatus.ACTIVE,
            FacilityRegistryStatus.SUSPENDED,
        }

    def mark_closed(self):
        self.status = FacilityRegistryStatus.CLOSED
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "closed_at", "updated_at"])
