"""Per-organization deviations from the plan, and cached resolutions.

Plans describe the standard offer. Real customers negotiate. These models
hold the exceptions without corrupting the catalogue -- so a hospital group
can be given four extra clinics for a quarter, and nobody has to invent a
plan called "Enterprise (Manakamana variant)".
"""

from django.db import models
from django.utils import timezone

from apps.catalog.models import Enforcement
from apps.common.models import BaseModel
from apps.tenancy.models import Organization


class OverrideKind(models.TextChoices):
    LIMIT = "limit", "Limit value"
    MODULE = "module", "Module access"
    FEATURE = "feature", "Feature flag"


class EntitlementOverride(BaseModel):
    """A negotiated, durable deviation from the plan for one organization.

    Overrides *replace* the plan value rather than adding to it -- they are
    for contracts ("unlimited clinics, capped at 2 hospitals"), whereas
    `EntitlementGrant` is for temporary boosts that stack.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="entitlement_overrides"
    )
    kind = models.CharField(max_length=16, choices=OverrideKind.choices)
    key = models.CharField(max_length=128, db_index=True)

    #: For LIMIT overrides. NULL with `is_unlimited=False` means "no opinion".
    value = models.IntegerField(null=True, blank=True)
    is_unlimited = models.BooleanField(default=False)
    #: For MODULE / FEATURE overrides.
    is_enabled = models.BooleanField(null=True, blank=True)
    enforcement = models.CharField(
        max_length=16, choices=Enforcement.choices, blank=True
    )

    effective_from = models.DateTimeField(default=timezone.now)
    effective_to = models.DateTimeField(null=True, blank=True)

    reason = models.TextField(
        help_text="Why this customer deviates from their plan. Required."
    )
    contract_reference = models.CharField(max_length=128, blank=True)
    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cp_entitlement_override"
        ordering = ["key"]
        indexes = [models.Index(fields=["organization", "kind", "key"])]

    def __str__(self):
        return f"{self.organization.slug}:{self.key}"

    @property
    def is_in_effect(self) -> bool:
        now = timezone.now()
        if self.effective_from > now:
            return False
        return self.effective_to is None or self.effective_to > now


class EntitlementGrant(BaseModel):
    """A temporary, additive boost to a limit.

    Used for the situations a plan cannot anticipate: a customer opening a
    disaster-relief clinic for two months, a migration that temporarily needs
    double the storage, an apology for an outage. Grants expire on their own,
    which is what stops them from quietly becoming permanent.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="entitlement_grants"
    )
    key = models.CharField(max_length=128, db_index=True)
    delta = models.IntegerField(help_text="Added to the resolved limit.")

    granted_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="NULL means it does not expire on its own."
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    reason = models.TextField()
    granted_by_id = models.UUIDField(null=True, blank=True)
    #: Links a grant back to the facility request that justified it.
    source_reference = models.CharField(max_length=128, blank=True)

    class Meta:
        db_table = "cp_entitlement_grant"
        ordering = ["-granted_at"]
        indexes = [models.Index(fields=["organization", "key"])]

    def __str__(self):
        return f"{self.organization.slug}:{self.key} +{self.delta}"

    @property
    def is_in_effect(self) -> bool:
        now = timezone.now()
        if self.revoked_at is not None or self.granted_at > now:
            return False
        return self.expires_at is None or self.expires_at > now


class EntitlementSnapshot(BaseModel):
    """A materialised resolution, kept for audit and for fast reads.

    Resolution is cheap but not free, and more importantly it changes over
    time: when a customer disputes a bill or an action is blocked, you need
    to know what the answer *was* on the day, not what it is now.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="entitlement_snapshots"
    )
    resolved_at = models.DateTimeField(default=timezone.now, db_index=True)
    plan_code = models.CharField(max_length=64)
    subscription_status = models.CharField(max_length=16)

    modules = models.JSONField(default=dict)
    features = models.JSONField(default=dict)
    limits = models.JSONField(default=dict)
    #: Which source won for each key -- plan, addon, override or grant.
    provenance = models.JSONField(default=dict, blank=True)

    #: Set when the resolution was recorded because an action was refused.
    triggering_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "cp_entitlement_snapshot"
        ordering = ["-resolved_at"]
        indexes = [models.Index(fields=["organization", "-resolved_at"])]

    def __str__(self):
        return f"{self.organization.slug} @ {self.resolved_at:%Y-%m-%d %H:%M}"
