"""Identity: users, their membership of organizations, and their sessions.

Identity lives in the control plane rather than in tenant databases, which
is a deliberate trade-off documented in docs/adr/0002-identity-placement.md.
The short version: one person may work for two organizations in a group, SSO
and MFA are platform-level concerns, and a login has to resolve *before* any
tenant connection can be chosen. Clinical, financial and operational data --
the material that actually needs physical isolation -- stays in the tenant
database.
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel, TimeStampedModel, UUIDModel
from apps.tenancy.models import Organization


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_platform_staff", True)
        extra.setdefault("is_active", True)
        if extra.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, UUIDModel, TimeStampedModel):
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(max_length=32, blank=True)

    full_name = models.CharField(max_length=255)
    preferred_name = models.CharField(max_length=128, blank=True)
    avatar_url = models.URLField(blank=True)
    locale = models.CharField(max_length=10, default="en-NP")
    timezone = models.CharField(max_length=64, default="Asia/Kathmandu")

    is_active = models.BooleanField(default=True)
    #: Django-admin access. Separate from platform staff on purpose.
    is_staff = models.BooleanField(default=False)
    #: Employee of the platform owner, with access to the SaaS console.
    is_platform_staff = models.BooleanField(default=False)
    #: Platform staff may only enter a customer's data when this is on. It is
    #: time-boxed, logged, and off by default, so "we can technically see
    #: everything" does not become "we routinely do".
    support_access_enabled = models.BooleanField(default=False)
    support_access_expires_at = models.DateTimeField(null=True, blank=True)

    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=64, blank=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    must_change_password = models.BooleanField(default=False)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_active_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "cp_user"
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    @property
    def display_name(self) -> str:
        return self.preferred_name or self.full_name

    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > timezone.now()

    @property
    def has_live_support_access(self) -> bool:
        if not (self.is_platform_staff and self.support_access_enabled):
            return False
        if self.support_access_expires_at is None:
            return True
        return self.support_access_expires_at > timezone.now()


class MembershipStatus(models.TextChoices):
    INVITED = "invited", "Invited"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    REVOKED = "revoked", "Revoked"


class Membership(BaseModel):
    """Links a user to an organization they may act within.

    The membership -- not the user -- is what a seat licence counts, and what
    role assignments in the tenant database hang off. A doctor consulting for
    two hospitals in a group has one account and two memberships.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    status = models.CharField(
        max_length=16,
        choices=MembershipStatus.choices,
        default=MembershipStatus.INVITED,
        db_index=True,
    )
    #: Which organization this user lands in after login.
    is_default = models.BooleanField(default=False)
    #: Organization-wide administrator. Facility- and department-scoped
    #: authority is expressed by role assignments in the tenant database.
    is_organization_owner = models.BooleanField(default=False)

    #: Mirrors `Employee.uuid` in the tenant database when the user is also
    #: on the payroll. Not every user is an employee (a consultant, a
    #: platform support agent), so this is optional.
    employee_uuid = models.UUIDField(null=True, blank=True)
    #: Facilities the user is posted to, by tenant facility UUID. Empty means
    #: organization-wide.
    facility_uuids = models.JSONField(default=list, blank=True)

    invited_at = models.DateTimeField(null=True, blank=True)
    invited_by_id = models.UUIDField(null=True, blank=True)
    joined_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    #: Counts against the seat limit. Set False for accounts that should not,
    #: such as a break-glass emergency login.
    consumes_seat = models.BooleanField(default=True)

    class Meta:
        db_table = "cp_membership"
        ordering = ["organization_id", "user_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_membership_per_org",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="uniq_default_membership_per_user",
            ),
        ]
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self):
        return f"{self.user.email} @ {self.organization.slug}"


class LoginOutcome(models.TextChoices):
    SUCCESS = "success", "Success"
    BAD_CREDENTIALS = "bad_credentials", "Bad credentials"
    MFA_REQUIRED = "mfa_required", "MFA required"
    MFA_FAILED = "mfa_failed", "MFA failed"
    LOCKED = "locked", "Account locked"
    INACTIVE = "inactive", "Account inactive"
    NO_ORGANIZATION = "no_organization", "No organization"


class LoginAttempt(UUIDModel, TimeStampedModel):
    """Every attempt, successful or not. Feeds lockout and security review."""

    email = models.CharField(max_length=254, db_index=True)
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="login_attempts"
    )
    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    outcome = models.CharField(max_length=24, choices=LoginOutcome.choices, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    attempted_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "cp_login_attempt"
        ordering = ["-attempted_at"]
        indexes = [models.Index(fields=["email", "-attempted_at"])]

    def __str__(self):
        return f"{self.email} {self.outcome} @ {self.attempted_at:%Y-%m-%d %H:%M}"


class UserDevice(BaseModel):
    """A device a user has signed in from, so sessions can be reviewed and cut."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    device_id = models.CharField(max_length=128, db_index=True)
    label = models.CharField(max_length=128, blank=True)
    platform = models.CharField(max_length=64, blank=True)
    app_version = models.CharField(max_length=32, blank=True)

    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    last_ip = models.GenericIPAddressField(null=True, blank=True)

    is_trusted = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=False)
    #: Set when an administrator forces sign-out; tokens issued before this
    #: moment are rejected.
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cp_user_device"
        ordering = ["-last_seen_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "device_id"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_device_per_user",
            )
        ]

    def __str__(self):
        return f"{self.label or self.device_id} ({self.user.email})"
