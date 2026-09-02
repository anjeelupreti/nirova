"""Usage measurement: what each customer actually consumed.

Two tables on purpose. `UsageEvent` is the append-only truth (auditable,
replayable, billable). `UsageCounter` is the rolled-up figure the quota guard
and the dashboards read, because counting millions of raw events on every
permission check would not survive contact with a busy hospital.
"""

from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel, TimeStampedModel, UUIDModel
from apps.tenancy.models import Organization


class UsageEvent(UUIDModel, TimeStampedModel):
    """One measurable thing happened. Never updated, never deleted."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="usage_events"
    )
    meter_key = models.CharField(max_length=64, db_index=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    #: Facility the usage is attributable to, for per-branch cost reporting.
    facility_uuid = models.UUIDField(null=True, blank=True)
    actor_id = models.UUIDField(null=True, blank=True)

    #: Caller-supplied key that makes ingestion idempotent. Retried webhooks
    #: and re-delivered queue messages must not bill a customer twice.
    idempotency_key = models.CharField(max_length=128, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "cp_usage_event"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["organization", "meter_key", "-occurred_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "meter_key", "idempotency_key"],
                condition=models.Q(idempotency_key__gt=""),
                name="uniq_usage_event_idempotency",
            )
        ]

    def __str__(self):
        return f"{self.meter_key}={self.quantity} @ {self.occurred_at:%Y-%m-%d}"


class UsagePeriod(models.TextChoices):
    DAY = "day", "Day"
    MONTH = "month", "Month"
    BILLING_PERIOD = "billing_period", "Billing period"
    LIFETIME = "lifetime", "Lifetime"


class UsageCounter(BaseModel):
    """A rolled-up total for one meter over one period."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="usage_counters"
    )
    meter_key = models.CharField(max_length=64, db_index=True)
    #: The limit this counter is compared against, when one exists. Denormal-
    #: ised so the quota guard can find the counter by limit key alone.
    limit_key = models.CharField(max_length=128, blank=True, db_index=True)

    period = models.CharField(
        max_length=16, choices=UsagePeriod.choices, default=UsagePeriod.MONTH
    )
    period_start = models.DateTimeField(db_index=True)
    period_end = models.DateTimeField(null=True, blank=True)

    value = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    peak_value = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    #: Portion of `value` that exceeded the entitled limit, for overage billing.
    overage = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    last_event_at = models.DateTimeField(null=True, blank=True)
    is_closed = models.BooleanField(
        default=False, help_text="Closed periods are frozen for billing."
    )

    class Meta:
        db_table = "cp_usage_counter"
        ordering = ["-period_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "meter_key", "period", "period_start"],
                name="uniq_usage_counter_period",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "meter_key", "-period_start"]),
        ]

    def __str__(self):
        return f"{self.meter_key} {self.period_start:%Y-%m} = {self.value}"
