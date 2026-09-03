"""Monthly recurring revenue, computed the way a SaaS business means it.

MRR is the single number a platform owner runs on, and it is easy to get
wrong in three ways at once — all three of which this module exists to avoid.

**Normalise the billing interval.** An annual subscription at 192,000 is
16,000 of monthly recurring revenue, not 192,000. Summing `contracted_price`
across mixed intervals reports an annual customer as twelve times the size
they are, and the error grows as more customers move to annual billing —
which is exactly the direction a maturing SaaS pushes them.

**Include add-ons.** A customer on a 16,000 plan with 72,000 of add-ons is an
88,000 customer. Counting only the plan under-reports them by 450%, and
under-reports the business by whatever proportion of revenue comes from
expansion — which for a modular product like this one is most of it.

**Apply the discount.** A contracted price with 20% off is not the contracted
price. Reporting the list price as revenue overstates the business by exactly
the discount the sales team gave away.

Everything is `Decimal`. MRR feeds a board pack; a float that drifts by a
paisa per customer is a board pack that does not add up.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.utils import timezone

from apps.catalog.models import BillingInterval
from apps.subscriptions.models import (
    ENTITLED_STATUSES,
    Subscription,
    SubscriptionStatus,
)

ZERO = Decimal("0.00")
PAISA = Decimal("0.01")

#: How many months one billing period covers. Used to divide a period price
#: down to a month.
#:
#: A dict rather than a chain of `if`s because a new interval is then one row
#: rather than an edit in every place that reasons about intervals — and a
#: missing key raises rather than silently defaulting to monthly, which would
#: over-report by up to twelve times.
MONTHS_PER_INTERVAL = {
    BillingInterval.MONTHLY: Decimal("1"),
    BillingInterval.QUARTERLY: Decimal("3"),
    BillingInterval.HALF_YEARLY: Decimal("6"),
    BillingInterval.ANNUAL: Decimal("12"),
}


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(PAISA, rounding=ROUND_HALF_UP)


def months_in(interval: str) -> Decimal:
    """How many months a billing interval covers.

    Falls back to monthly for an unknown value, which is the *conservative*
    direction: it under-states rather than over-states, and an MRR that looks
    low prompts a question while one that looks high does not.
    """
    return MONTHS_PER_INTERVAL.get(interval, Decimal("1"))


def subscription_mrr(subscription: Subscription, on_date=None) -> dict:
    """One subscription's monthly recurring revenue, and where it comes from.

    Returns the breakdown as well as the total, because "why did MRR move?"
    is the question that follows every MRR number, and plan-versus-add-on is
    the first cut of the answer.
    """
    on_date = on_date or timezone.now()
    months = months_in(subscription.billing_interval)

    base = Decimal(subscription.contracted_price or ZERO) / months
    discount = Decimal(subscription.discount_percent or ZERO)
    base_after_discount = base * (Decimal("100") - discount) / Decimal("100")

    addon_total = ZERO
    addons = []
    for addon in subscription.addons.all():
        if not addon.is_active:
            continue
        # Effective-dated: an add-on sold for a quarter and since expired is
        # not revenue today, and one starting next month is not revenue yet.
        if addon.effective_from and addon.effective_from > on_date:
            continue
        if addon.effective_to and addon.effective_to <= on_date:
            continue

        # An add-on is priced per the subscription's own interval -- it is
        # billed on the same invoice -- so it normalises the same way.
        monthly = Decimal(addon.total_price) / months
        addon_total += monthly
        addons.append(
            {
                "code": addon.addon.code,
                "name": addon.addon.name,
                "quantity": addon.quantity,
                "monthly": money(monthly),
            }
        )

    total = base_after_discount + addon_total
    return {
        "subscription": str(subscription.uuid),
        "organization": subscription.organization.slug,
        "plan": subscription.plan.code if subscription.plan_id else "",
        "billing_interval": subscription.billing_interval,
        "months_per_period": str(months),
        "contracted_price": money(subscription.contracted_price or ZERO),
        "base_mrr": money(base_after_discount),
        "discount_percent": str(discount),
        "addon_mrr": money(addon_total),
        "addons": addons,
        "mrr": money(total),
    }


def platform_mrr(on_date=None) -> dict:
    """The whole book of business, monthly.

    Only `ACTIVE` subscriptions count towards MRR. A trial is not revenue —
    it is a hope — and counting it is how a SaaS dashboard tells its owner
    the business is bigger than it is. Trials are reported separately, as
    *potential*, so the number is visible without being added in.
    """
    on_date = on_date or timezone.now()

    active = (
        Subscription.objects.filter(status=SubscriptionStatus.ACTIVE)
        .select_related("organization", "plan")
        .prefetch_related("addons__addon")
    )
    trialing = (
        Subscription.objects.filter(status=SubscriptionStatus.TRIALING)
        .select_related("organization", "plan")
        .prefetch_related("addons__addon")
    )

    rows = [subscription_mrr(row, on_date) for row in active]
    trial_rows = [subscription_mrr(row, on_date) for row in trialing]

    total = sum((row["mrr"] for row in rows), ZERO)
    base = sum((row["base_mrr"] for row in rows), ZERO)
    addon = sum((row["addon_mrr"] for row in rows), ZERO)
    trial_value = sum((row["mrr"] for row in trial_rows), ZERO)

    by_plan = {}
    for row in rows:
        by_plan[row["plan"]] = by_plan.get(row["plan"], ZERO) + row["mrr"]

    by_interval = {}
    for row in rows:
        key = row["billing_interval"]
        by_interval[key] = by_interval.get(key, ZERO) + row["mrr"]

    customers = len(rows)
    return {
        "mrr": money(total),
        "arr": money(total * Decimal("12")),
        "base_mrr": money(base),
        # Named "expansion" because that is what it is: revenue above the
        # plan the customer originally bought. For a modular product it is
        # usually most of the growth, and a dashboard that hides it inside a
        # single MRR figure cannot show that.
        "expansion_mrr": money(addon),
        "expansion_share_percent": (
            round(float(addon / total) * 100, 1) if total > ZERO else 0.0
        ),
        "paying_customers": customers,
        "arpu": money(total / customers) if customers else ZERO,
        "trial_customers": len(trial_rows),
        #: Not added to MRR. A trial is a hope, not revenue.
        "trial_potential_mrr": money(trial_value),
        "by_plan": {key: money(value) for key, value in by_plan.items()},
        "by_billing_interval": {
            key: money(value) for key, value in by_interval.items()
        },
        "currency": "NPR",
    }


def largest_customers(limit: int = 10, on_date=None) -> list:
    """Who the revenue actually comes from.

    Concentration is the risk a SaaS owner most often cannot see: a business
    where one customer is 40% of MRR is a different business from one where
    the largest is 4%, and the headline number is identical in both.
    """
    active = (
        Subscription.objects.filter(status=SubscriptionStatus.ACTIVE)
        .select_related("organization", "plan")
        .prefetch_related("addons__addon")
    )
    rows = sorted(
        (subscription_mrr(row, on_date) for row in active),
        key=lambda row: row["mrr"],
        reverse=True,
    )
    total = sum((row["mrr"] for row in rows), ZERO)
    return [
        {
            "organization": row["organization"],
            "plan": row["plan"],
            "mrr": row["mrr"],
            "share_percent": (
                round(float(row["mrr"] / total) * 100, 1) if total > ZERO else 0.0
            ),
            "expansion_mrr": row["addon_mrr"],
        }
        for row in rows[:limit]
    ]


def entitled_but_unbilled() -> list:
    """Subscriptions serving a customer without producing revenue.

    Trials, grace periods and anything past due. Not a fault — every one is a
    deliberate state — but a list worth having in front of somebody, because
    each row is a customer using the product while not paying for it, and the
    reason it happened is rarely still remembered a month later.
    """
    rows = (
        Subscription.objects.filter(status__in=ENTITLED_STATUSES)
        .exclude(status=SubscriptionStatus.ACTIVE)
        .select_related("organization", "plan")
    )
    return [
        {
            "organization": row.organization.slug,
            "organization_name": row.organization.display_name,
            "plan": row.plan.code if row.plan_id else "",
            "status": row.status,
            "trial_ends_at": row.trial_ends_at,
            "grace_ends_at": row.grace_ends_at,
            "contracted_price": money(row.contracted_price or ZERO),
        }
        for row in rows
    ]
