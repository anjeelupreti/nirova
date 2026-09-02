"""What each customer has actually bought, and its lifecycle."""

from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.catalog.models import AddOn, BillingInterval, Plan
from apps.common.models import BaseModel
from apps.tenancy.models import Organization


class SubscriptionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    TRIALING = "trialing", "Trialing"
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past due"
    GRACE = "grace", "In grace period"
    SUSPENDED = "suspended", "Suspended"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


#: Statuses in which the customer may keep transacting. `past_due` and
#: `grace` are included on purpose: cutting off a hospital mid-shift over an
#: unpaid invoice endangers patients, so collections escalate through
#: warnings and read-only mode instead.
ENTITLED_STATUSES = {
    SubscriptionStatus.TRIALING,
    SubscriptionStatus.ACTIVE,
    SubscriptionStatus.PAST_DUE,
    SubscriptionStatus.GRACE,
}


class Subscription(BaseModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="subscriptions"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(
        max_length=16,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.DRAFT,
        db_index=True,
    )

    billing_interval = models.CharField(
        max_length=16, choices=BillingInterval.choices, default=BillingInterval.MONTHLY
    )
    currency = models.CharField(max_length=3, default="NPR")
    #: Snapshot of the plan price at signup. The plan may be re-priced later;
    #: this contract does not move unless the customer is migrated.
    contracted_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )

    started_at = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    grace_ends_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    #: A cancellation requested mid-term takes effect at period end; the
    #: customer keeps what they paid for until then.
    cancel_at_period_end = models.BooleanField(default=False)
    ended_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)

    auto_renew = models.BooleanField(default=True)
    purchase_order_reference = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "cp_subscription"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self):
        return f"{self.organization.display_name} — {self.plan.name}"

    @property
    def is_entitled(self) -> bool:
        return self.status in ENTITLED_STATUSES

    @property
    def is_in_trial(self) -> bool:
        return (
            self.status == SubscriptionStatus.TRIALING
            and self.trial_ends_at is not None
            and self.trial_ends_at > timezone.now()
        )

    def days_until_renewal(self) -> int | None:
        if not self.current_period_end:
            return None
        return (self.current_period_end - timezone.now()).days


class SubscriptionAddOn(BaseModel):
    """An add-on attached to a subscription, with a quantity.

    Quantity is what makes "three extra pharmacies" expressible without three
    rows or a bespoke plan.
    """

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="addons"
    )
    addon = models.ForeignKey(AddOn, on_delete=models.PROTECT, related_name="+")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    effective_from = models.DateTimeField(default=timezone.now)
    #: NULL means it runs with the subscription.
    effective_to = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    #: Set when the add-on was attached to satisfy a facility request, so the
    #: commercial change and the operational change stay linked.
    source_reference = models.CharField(max_length=128, blank=True)

    class Meta:
        db_table = "cp_subscription_addon"
        ordering = ["addon__name"]
        indexes = [models.Index(fields=["subscription", "is_active"])]

    def __str__(self):
        return f"{self.addon.code} ×{self.quantity}"

    @property
    def is_in_effect(self) -> bool:
        now = timezone.now()
        if not self.is_active or self.effective_from > now:
            return False
        return self.effective_to is None or self.effective_to > now

    @property
    def total_price(self) -> Decimal:
        return self.unit_price * self.quantity


class SubscriptionEventType(models.TextChoices):
    CREATED = "created", "Created"
    TRIAL_STARTED = "trial_started", "Trial started"
    ACTIVATED = "activated", "Activated"
    RENEWED = "renewed", "Renewed"
    UPGRADED = "upgraded", "Upgraded"
    DOWNGRADED = "downgraded", "Downgraded"
    ADDON_ADDED = "addon_added", "Add-on added"
    ADDON_REMOVED = "addon_removed", "Add-on removed"
    PAYMENT_FAILED = "payment_failed", "Payment failed"
    ENTERED_GRACE = "entered_grace", "Entered grace period"
    SUSPENDED = "suspended", "Suspended"
    REACTIVATED = "reactivated", "Reactivated"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


class SubscriptionEvent(BaseModel):
    """Append-only history of everything that happened to a subscription.

    Revenue reporting (new/expansion/contraction/churned MRR) is derived from
    this stream rather than from the subscription's current state, because
    the current state cannot tell you what a customer used to pay.
    """

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(
        max_length=32, choices=SubscriptionEventType.choices, db_index=True
    )
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    from_plan = models.ForeignKey(
        Plan, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    to_plan = models.ForeignKey(
        Plan, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    mrr_before = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    mrr_after = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    actor_id = models.UUIDField(null=True, blank=True)
    reason = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "cp_subscription_event"
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["subscription", "event_type"])]

    def __str__(self):
        return f"{self.get_event_type_display()} @ {self.occurred_at:%Y-%m-%d}"

    @property
    def mrr_delta(self) -> Decimal | None:
        if self.mrr_before is None or self.mrr_after is None:
            return None
        return self.mrr_after - self.mrr_before
