"""Editing what is for sale, safely.

The catalogue has been complete since the platform app was written — modules,
features, plans, per-plan limits, add-ons — and **entirely unreachable except
by a seed**. Pricing a module, opening a trial, moving a limit: all of it
needed a developer and a deployment, which is the wrong shape for the one part
of the product the commercial side owns.

Three rules make editing a live catalogue safe, and they are the substance of
this module:

**A plan is not a document; it is a promise to everyone on it.** Changing a
plan's modules or limits changes what every subscriber on that plan may do,
immediately. So a change that *takes something away* is refused until the
caller has been told, by number and by name, which organizations lose what
(`impact_of`), and confirms. A change that only adds goes through.

**Modules are code, not data.** A module code corresponds to enforcement
written in the application (`require_module`); inventing `dialysis` in a form
would produce a module nothing checks and a customer billed for nothing. So
modules are *declared* in `catalog.keys` and only their saleable metadata —
name, description, order, whether it is active — is editable here. Features
are softer and may be created, because a feature flag with no consumer is
inert rather than misleading.

**Nothing is deleted.** A plan nobody may buy any more is `is_public=False`;
one nobody should be on is `is_active=False`, which leaves existing
subscribers alone. Deleting the row would orphan live subscriptions and erase
the answer to "what were they promised when they signed?"
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.catalog.keys import FeatureFlag, LimitKey, ModuleCode
from apps.catalog.models import (
    Enforcement,
    Feature,
    Module,
    Plan,
    PlanFeature,
    PlanLimit,
    PlanModule,
)
from apps.common.exceptions import DomainError


class CatalogueError(DomainError):
    code = "catalogue_edit_refused"


#: Fields on a plan the commercial side owns. `code` is not among them: it is
#: what subscriptions, audit entries and support conversations refer to.
PLAN_FIELDS = {
    "name", "tagline", "description", "base_price", "currency",
    "billing_interval", "setup_fee", "trial_days", "grace_days",
    "is_public", "is_active", "display_order",
}
MODULE_FIELDS = {"name", "description", "display_order", "is_active", "is_core"}
FEATURE_FIELDS = {"name", "description", "is_active"}


def _money(value, field: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CatalogueError(f"{field} must be an amount.") from exc
    if amount < 0:
        raise CatalogueError(f"{field} cannot be negative.")
    return amount.quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Reading the whole catalogue, once
# ---------------------------------------------------------------------------

def catalogue() -> dict:
    """Everything the editor needs in one payload.

    One request rather than five, because the editor is a matrix: plans down
    one axis, modules and features across the other, and a screen that loads
    them separately renders half a matrix first.
    """
    modules = list(Module.objects.order_by("display_order", "name"))
    features = list(Feature.objects.select_related("module").order_by("code"))
    plans = list(
        Plan.objects.prefetch_related(
            "plan_modules__module", "plan_features__feature", "limits",
        ).order_by("display_order", "name")
    )
    return {
        "modules": [
            {
                "code": module.code,
                "name": module.name,
                "description": module.description,
                "is_core": module.is_core,
                "is_active": module.is_active,
                "display_order": module.display_order,
                "depends_on": [row.code for row in module.depends_on.all()],
                "known": module.code in ModuleCode.ALL,
            }
            for module in modules
        ],
        "features": [
            {
                "code": feature.code,
                "name": feature.name,
                "description": feature.description,
                "module": feature.module.code if feature.module_id else "",
                "is_active": feature.is_active,
                "known": feature.code in getattr(FeatureFlag, "ALL", ()),
            }
            for feature in features
        ],
        "limit_keys": sorted(getattr(LimitKey, "ALL", ()) or []),
        "plans": [_plan(plan) for plan in plans],
    }


def _plan(plan: Plan) -> dict:
    included = {row.module.code: row for row in plan.plan_modules.all()}
    enabled = {row.feature.code: row for row in plan.plan_features.all()}
    return {
        "uuid": str(plan.uuid),
        "code": plan.code,
        "name": plan.name,
        "tagline": plan.tagline,
        "description": plan.description,
        "base_price": str(plan.base_price),
        "currency": plan.currency,
        "billing_interval": plan.billing_interval,
        "setup_fee": str(plan.setup_fee),
        "trial_days": plan.trial_days,
        "grace_days": plan.grace_days,
        "is_public": plan.is_public,
        "is_active": plan.is_active,
        "display_order": plan.display_order,
        "version": plan.version,
        "modules": {
            code: {
                "is_included": row.is_included,
                "additional_price": str(row.additional_price),
            }
            for code, row in included.items()
        },
        "features": {code: row.is_enabled for code, row in enabled.items()},
        "limits": {
            row.key: {
                "value": row.value,
                "enforcement": row.enforcement,
                "warn_at_percent": row.warn_at_percent,
                "overage_unit_price": (
                    str(row.overage_unit_price) if row.overage_unit_price is not None else None
                ),
            }
            for row in plan.limits.all()
        },
        "subscribers": plan.subscriptions.exclude(
            status__in=["cancelled", "expired", "draft"],
        ).count() if hasattr(plan, "subscriptions") else 0,
    }


def plan_detail(plan: Plan) -> dict:
    return _plan(
        Plan.objects.prefetch_related(
            "plan_modules__module", "plan_features__feature", "limits",
        ).get(pk=plan.pk)
    )


# ---------------------------------------------------------------------------
# Impact — who is affected, and what do they lose
# ---------------------------------------------------------------------------

def subscribers_of(plan: Plan):
    from apps.subscriptions.models import Subscription, SubscriptionStatus

    return (
        Subscription.objects.filter(plan=plan)
        .exclude(status__in=[
            SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED,
            SubscriptionStatus.DRAFT,
        ])
        .select_related("organization")
    )


def impact_of(plan: Plan, *, removing_modules=(), removing_features=(), lowering=()) -> dict:
    """Who is on this plan, and what this change would take from them.

    Returned *before* a removal is applied, and the reason the endpoint
    refuses an unconfirmed removal. "Are you sure?" on its own is a dialogue
    nobody reads; "this removes Laboratory from 14 organizations, including
    Manakamana Health" is one they do.
    """
    live = list(subscribers_of(plan))
    return {
        "organizations": len(live),
        "names": [row.organization.display_name for row in live[:10]],
        "removes_modules": sorted(removing_modules),
        "removes_features": sorted(removing_features),
        "lowers_limits": sorted(lowering),
        "loses_something": bool(live) and bool(removing_modules or removing_features or lowering),
    }


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

@transaction.atomic
def create_plan(*, code: str, name: str, **fields) -> Plan:
    code = (code or "").strip().lower()
    if not code:
        raise CatalogueError("A plan needs a code.")
    if Plan.objects.filter(code=code).exists():
        raise CatalogueError(f"A plan already uses the code '{code}'.", code="duplicate_code")
    plan = Plan(code=code, name=name or code.title())
    _assign(plan, fields, PLAN_FIELDS)
    plan.full_clean(exclude=["uuid"])
    plan.save()
    return plan


@transaction.atomic
def update_plan(plan: Plan, fields: dict) -> Plan:
    _assign(plan, fields, PLAN_FIELDS)
    plan.full_clean(exclude=["uuid"])
    plan.save()
    return plan


def _assign(instance, fields: dict, allowed: set) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise CatalogueError(f"Not editable here: {', '.join(sorted(unknown))}.")
    for key, value in fields.items():
        if key in {"base_price", "setup_fee"}:
            value = _money(value, key)
        setattr(instance, key, value)


@transaction.atomic
def set_plan_modules(plan: Plan, wanted: dict, *, confirm: bool = False) -> dict:
    """`{module_code: {"is_included": bool, "additional_price": "0.00"}}`.

    The whole set, not a patch: a matrix editor sends what the matrix shows,
    and a partial update would make "unticked" and "not sent" the same thing.
    """
    known = {module.code: module for module in Module.objects.all()}
    unknown = set(wanted) - set(known)
    if unknown:
        raise CatalogueError(f"No such module: {', '.join(sorted(unknown))}.")

    current = {row.module.code: row for row in plan.plan_modules.select_related("module")}
    removing = [
        code for code, row in current.items()
        if row.is_included and not wanted.get(code, {}).get("is_included", False)
    ]
    impact = impact_of(plan, removing_modules=removing)
    if impact["loses_something"] and not confirm:
        raise CatalogueError(
            f"This removes {', '.join(removing)} from {impact['organizations']} "
            "organization(s) already on this plan. Confirm to continue.",
            code="needs_confirmation",
            detail={"impact": impact},
        )

    for code, module in known.items():
        asked = wanted.get(code)
        if asked is None:
            continue
        PlanModule.objects.update_or_create(
            plan=plan, module=module,
            defaults={
                "is_included": bool(asked.get("is_included", False)),
                "additional_price": _money(asked.get("additional_price", 0), "additional_price"),
            },
        )
    return impact


@transaction.atomic
def set_plan_features(plan: Plan, wanted: dict, *, confirm: bool = False) -> dict:
    known = {feature.code: feature for feature in Feature.objects.all()}
    unknown = set(wanted) - set(known)
    if unknown:
        raise CatalogueError(f"No such feature: {', '.join(sorted(unknown))}.")

    current = {row.feature.code: row.is_enabled for row in plan.plan_features.select_related("feature")}
    removing = [code for code, on in current.items() if on and not wanted.get(code, False)]
    impact = impact_of(plan, removing_features=removing)
    if impact["loses_something"] and not confirm:
        raise CatalogueError(
            f"This turns off {', '.join(removing)} for {impact['organizations']} "
            "organization(s) already on this plan. Confirm to continue.",
            code="needs_confirmation",
            detail={"impact": impact},
        )

    for code, feature in known.items():
        if code not in wanted:
            continue
        PlanFeature.objects.update_or_create(
            plan=plan, feature=feature, defaults={"is_enabled": bool(wanted[code])},
        )
    return impact


@transaction.atomic
def set_plan_limits(plan: Plan, wanted: dict, *, confirm: bool = False) -> dict:
    """`{key: {"value": int|None, "enforcement": …, "warn_at_percent": int}}`.

    `value: null` is unlimited and `0` is none allowed — two different
    promises, both real, and the reason this cannot be a plain integer field.
    """
    current = {row.key: row.value for row in plan.limits.all()}
    lowering = []
    for key, asked in wanted.items():
        before, after = current.get(key), asked.get("value")
        if before is None and after is not None:
            lowering.append(key)          # unlimited -> a ceiling
        elif before is not None and after is not None and after < before:
            lowering.append(key)

    impact = impact_of(plan, lowering=lowering)
    if impact["loses_something"] and not confirm:
        raise CatalogueError(
            f"This lowers {', '.join(lowering)} for {impact['organizations']} "
            "organization(s) already on this plan, which may put them over "
            "their limit. Confirm to continue.",
            code="needs_confirmation",
            detail={"impact": impact},
        )

    for key, asked in wanted.items():
        value = asked.get("value")
        enforcement = asked.get("enforcement", Enforcement.HARD)
        if enforcement not in Enforcement.values:
            raise CatalogueError(f"'{enforcement}' is not an enforcement mode.")
        overage = asked.get("overage_unit_price")
        row = PlanLimit(
            plan=plan, key=key,
            value=None if value in (None, "") else int(value),
            enforcement=enforcement,
            warn_at_percent=int(asked.get("warn_at_percent", 80)),
            overage_unit_price=_money(overage, "overage_unit_price") if overage not in (None, "") else None,
        )
        row.clean()
        PlanLimit.objects.update_or_create(
            plan=plan, key=key,
            defaults={
                "value": row.value, "enforcement": row.enforcement,
                "warn_at_percent": row.warn_at_percent,
                "overage_unit_price": row.overage_unit_price,
            },
        )
    # A key the editor no longer shows is removed, so "no limit row" and
    # "unlimited" stay distinguishable in the other direction too.
    plan.limits.exclude(key__in=list(wanted)).delete()
    return impact


@transaction.atomic
def update_module(module: Module, fields: dict) -> Module:
    _assign(module, fields, MODULE_FIELDS)
    module.full_clean(exclude=["uuid"])
    module.save()
    return module


@transaction.atomic
def update_feature(feature: Feature, fields: dict) -> Feature:
    _assign(feature, fields, FEATURE_FIELDS)
    feature.full_clean(exclude=["uuid", "module"])
    feature.save()
    return feature
