"""The commercial catalogue: what the platform sells and on what terms."""

from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import BaseModel


class Enforcement(models.TextChoices):
    """How strictly a limit is applied when it is reached.

    Not every ceiling should be a wall. Blocking a hospital from admitting a
    patient because they are 3 users over their plan would be a worse outcome
    than billing them for it -- but blocking a fourth pharmacy branch is
    exactly right, because that is a deliberate, reversible commercial act.
    """

    HARD = "hard", "Block the action"
    SOFT = "soft", "Allow, flag for review"
    GRACE = "grace", "Allow within grace window, then block"
    METERED = "metered", "Allow and bill the overage"


class BillingInterval(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    HALF_YEARLY = "half_yearly", "Half-yearly"
    ANNUAL = "annual", "Annual"
    CUSTOM = "custom", "Custom contract"


class Module(BaseModel):
    """A sellable product area (pharmacy, payroll, radiology...)."""

    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    #: Modules that must also be enabled. Payroll without HRMS has no
    #: employee records to pay, so it declares hrms as a dependency and the
    #: entitlement resolver refuses the incoherent combination.
    depends_on = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="dependents"
    )
    is_core = models.BooleanField(
        default=False, help_text="Included in every plan and cannot be disabled."
    )
    display_order = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "cp_module"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class Feature(BaseModel):
    """A boolean capability, usually inside a module."""

    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name="features",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "cp_feature"
        ordering = ["code"]

    def __str__(self):
        return self.name


class Plan(BaseModel):
    """A packaged offer: a set of modules, features and limits at a price."""

    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    tagline = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    modules = models.ManyToManyField(Module, through="PlanModule", related_name="plans")
    features = models.ManyToManyField(
        Feature, through="PlanFeature", related_name="plans"
    )

    base_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="NPR")
    billing_interval = models.CharField(
        max_length=16, choices=BillingInterval.choices, default=BillingInterval.MONTHLY
    )
    setup_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    trial_days = models.PositiveSmallIntegerField(default=14)
    #: Days after a failed renewal during which the tenant stays usable.
    grace_days = models.PositiveSmallIntegerField(default=7)

    is_public = models.BooleanField(
        default=True, help_text="Listed on pricing pages. Custom deals are private."
    )
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=100)

    #: Plans are versioned rather than edited. A customer keeps the terms they
    #: signed up on until they are explicitly migrated, so changing next
    #: year's pricing never silently re-prices existing subscriptions.
    version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="superseded_by",
    )

    class Meta:
        db_table = "cp_plan"
        ordering = ["display_order", "name"]

    def __str__(self):
        return f"{self.name} v{self.version}"


class PlanModule(BaseModel):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="plan_modules")
    module = models.ForeignKey(
        Module, on_delete=models.CASCADE, related_name="plan_modules"
    )
    #: Included at no extra cost, or available as a paid add-on within the plan.
    is_included = models.BooleanField(default=True)
    additional_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = "cp_plan_module"
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "module"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_module_per_plan",
            )
        ]


class PlanFeature(BaseModel):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="plan_features")
    feature = models.ForeignKey(
        Feature, on_delete=models.CASCADE, related_name="plan_features"
    )
    is_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "cp_plan_feature"
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "feature"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_feature_per_plan",
            )
        ]


class PlanLimit(BaseModel):
    """A numeric ceiling attached to a plan.

    `value = None` means unlimited, which is different from `value = 0`
    (explicitly none allowed). Both are needed: an enterprise contract with
    unlimited clinics and zero pharmacies is a real shape.
    """

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="limits")
    key = models.CharField(max_length=128, db_index=True)
    value = models.IntegerField(
        null=True, blank=True, help_text="NULL means unlimited."
    )
    enforcement = models.CharField(
        max_length=16, choices=Enforcement.choices, default=Enforcement.HARD
    )
    #: Price per unit beyond the ceiling, for METERED limits.
    overage_unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    #: Percentage of the limit at which the customer is warned.
    warn_at_percent = models.PositiveSmallIntegerField(default=80)

    class Meta:
        db_table = "cp_plan_limit"
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "key"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_limit_per_plan",
            )
        ]
        ordering = ["key"]

    def __str__(self):
        return f"{self.plan.code}:{self.key}={'∞' if self.value is None else self.value}"

    def clean(self):
        if self.value is not None and self.value < 0:
            raise ValidationError({"value": "A limit cannot be negative."})
        if self.enforcement == Enforcement.METERED and self.overage_unit_price is None:
            raise ValidationError(
                {"overage_unit_price": "Metered limits need an overage price."}
            )


class AddOnKind(models.TextChoices):
    LIMIT_INCREMENT = "limit_increment", "Increases a limit"
    MODULE = "module", "Adds a module"
    FEATURE = "feature", "Enables a feature"


class AddOn(BaseModel):
    """A purchasable increment on top of a plan.

    This is the pressure valve that keeps plans simple. Rather than inventing
    a "Professional Plus" tier for a customer who needs one more pharmacy,
    sell them an `extra_pharmacy` add-on. Subscriptions carry a quantity, so
    the same add-on serves the customer who needs five.
    """

    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=32, choices=AddOnKind.choices)

    #: For LIMIT_INCREMENT: the limit key raised. For MODULE/FEATURE: the
    #: module or feature code granted.
    target_key = models.CharField(max_length=128, db_index=True)
    #: How much one unit of this add-on raises the limit by.
    increment = models.IntegerField(default=1)

    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="NPR")
    billing_interval = models.CharField(
        max_length=16, choices=BillingInterval.choices, default=BillingInterval.MONTHLY
    )

    #: Plans this add-on may be attached to. Empty means any plan.
    available_on_plans = models.ManyToManyField(
        Plan, blank=True, related_name="available_addons"
    )
    max_quantity = models.PositiveIntegerField(null=True, blank=True)
    requires_approval = models.BooleanField(
        default=False,
        help_text="Platform staff must approve before this add-on takes effect.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "cp_addon"
        ordering = ["name"]

    def __str__(self):
        return self.name


class UsageMeterDefinition(BaseModel):
    """Declares a quantity worth counting, and how to count it."""

    class Aggregation(models.TextChoices):
        SUM = "sum", "Sum over the period"
        MAX = "max", "Peak during the period"
        LAST = "last", "Value at period end"

    key = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    unit = models.CharField(max_length=32, default="count")
    aggregation = models.CharField(
        max_length=8, choices=Aggregation.choices, default=Aggregation.SUM
    )
    #: The limit this meter is checked against, when one exists.
    limit_key = models.CharField(max_length=128, blank=True)
    is_billable = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "cp_usage_meter_definition"
        ordering = ["key"]

    def __str__(self):
        return self.name
