"""Resolving what an organization is actually entitled to, right now.

Layering, weakest source first:

    1. Plan            the standard offer they signed up on
    2. Add-ons         paid increments, multiplied by quantity  (additive)
    3. Grants          temporary boosts                          (additive)
    4. Overrides       negotiated contract terms               (replacing)

Additive sources stack; an override replaces whatever the additive layers
produced, because a contract term is a statement about the final number, not
an adjustment to it. Provenance is recorded for every key so support can
answer "why can this customer only open two pharmacies?" without guesswork.
"""

# dataclass / field: LimitSpec and ResolvedEntitlements are value objects
# built and discarded per request, never persisted. Dataclasses give equality
# and a readable repr for free, which matters when debugging why a customer
# resolved to the limit they did.
# NOTE: every attribute needs a type annotation, or @dataclass silently
# treats it as a plain class attribute -- see development log entry 026.
from dataclasses import dataclass, field

# Q: builds the OR condition for "grant has no expiry, or has not expired
# yet". Needed because that is one filter with two alternatives, which
# keyword arguments alone cannot express.
from django.db.models import Q

# timezone: every effective-dating comparison uses timezone.now() rather than
# datetime.now(), because USE_TZ is on and naive comparisons would raise.
from django.utils import timezone

# FACILITY_TYPE_MODULE: maps a facility type to the module it requires, used
# by _derive_facility_type_limits to zero out types whose module the customer
# has not bought.
# LimitKey: the limit-key vocabulary, including the "max_facilities.<type>"
# convention this module both reads and generates.
from apps.catalog.keys import FACILITY_TYPE_MODULE, LimitKey

# AddOnKind: distinguishes add-ons that raise a limit from those that unlock
# a module or a feature -- the branch inside _apply_addons.
# Enforcement: the default enforcement mode carried onto a derived LimitSpec.
from apps.catalog.models import AddOnKind, Enforcement

# EntitlementGrant / EntitlementOverride: resolution layers 3 and 4.
# OverrideKind: whether an override targets a limit, a module or a feature.
from apps.entitlements.models import (
    EntitlementGrant,
    EntitlementOverride,
    OverrideKind,
)

# Subscription: layer 1 -- the plan hangs off it.
# SubscriptionStatus: used to exclude draft, cancelled and expired
# subscriptions while deliberately *including* past-due and grace ones.
from apps.subscriptions.models import Subscription, SubscriptionStatus

UNLIMITED = None


@dataclass
class LimitSpec:
    """The resolved ceiling for one limit key."""

    key: str
    value: int | None  # None == unlimited
    enforcement: str = Enforcement.HARD
    warn_at_percent: int = 80
    overage_unit_price: object = None
    sources: list = field(default_factory=list)

    @property
    def is_unlimited(self) -> bool:
        return self.value is None

    def remaining(self, current_usage: int) -> int | None:
        if self.is_unlimited:
            return None
        return max(self.value - current_usage, 0)

    def would_exceed(self, current_usage: int, delta: int = 1) -> bool:
        if self.is_unlimited:
            return False
        return current_usage + delta > self.value

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "unlimited": self.is_unlimited,
            "enforcement": self.enforcement,
            "warn_at_percent": self.warn_at_percent,
            "sources": self.sources,
        }


@dataclass
class ResolvedEntitlements:
    organization_id: str
    plan_code: str
    subscription_status: str
    is_entitled: bool
    modules: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    resolved_at: object = None

    # -- queries ---------------------------------------------------------

    def has_module(self, code: str) -> bool:
        return bool(self.modules.get(code, False))

    def has_feature(self, code: str) -> bool:
        return bool(self.features.get(code, False))

    def limit(self, key: str) -> LimitSpec:
        """Return the spec for a key, defaulting to zero-allowed.

        An unknown limit key resolves to 0 rather than unlimited. Failing
        closed matters here: a typo in a key name should stop an action, not
        silently grant infinite headroom.
        """
        return self.limits.get(
            key, LimitSpec(key=key, value=0, sources=["default:absent"])
        )

    def facility_limit(self, facility_type: str) -> LimitSpec:
        return self.limit(LimitKey.for_facility_type(facility_type))

    def as_dict(self) -> dict:
        return {
            "organization_id": self.organization_id,
            "plan_code": self.plan_code,
            "subscription_status": self.subscription_status,
            "is_entitled": self.is_entitled,
            "modules": self.modules,
            "features": self.features,
            "limits": {k: v.as_dict() for k, v in self.limits.items()},
            "provenance": self.provenance,
        }


def active_subscription(organization) -> Subscription | None:
    """The subscription that governs entitlements right now.

    Cancelled and expired subscriptions are excluded, but past-due and grace
    ones are not -- see `ENTITLED_STATUSES` for why.
    """
    return (
        Subscription.objects.filter(organization=organization)
        .exclude(
            status__in=[
                SubscriptionStatus.DRAFT,
                SubscriptionStatus.CANCELLED,
                SubscriptionStatus.EXPIRED,
            ]
        )
        .select_related("plan")
        .order_by("-created_at")
        .first()
    )


def _apply_plan(plan, entitlements: ResolvedEntitlements) -> None:
    for plan_module in plan.plan_modules.select_related("module"):
        code = plan_module.module.code
        entitlements.modules[code] = plan_module.is_included
        entitlements.provenance[f"module:{code}"] = [f"plan:{plan.code}"]

    for module in plan.modules.filter(is_core=True):
        entitlements.modules[module.code] = True

    for plan_feature in plan.plan_features.select_related("feature"):
        code = plan_feature.feature.code
        entitlements.features[code] = plan_feature.is_enabled
        entitlements.provenance[f"feature:{code}"] = [f"plan:{plan.code}"]

    for plan_limit in plan.limits.all():
        entitlements.limits[plan_limit.key] = LimitSpec(
            key=plan_limit.key,
            value=plan_limit.value,
            enforcement=plan_limit.enforcement,
            warn_at_percent=plan_limit.warn_at_percent,
            sources=[f"plan:{plan.code}"],
        )


def _apply_addons(subscription, entitlements: ResolvedEntitlements) -> None:
    addons = subscription.addons.select_related("addon").filter(is_active=True)
    for subscription_addon in addons:
        if not subscription_addon.is_in_effect:
            continue
        addon = subscription_addon.addon
        label = f"addon:{addon.code}×{subscription_addon.quantity}"

        if addon.kind == AddOnKind.MODULE:
            entitlements.modules[addon.target_key] = True
            entitlements.provenance.setdefault(
                f"module:{addon.target_key}", []
            ).append(label)

        elif addon.kind == AddOnKind.FEATURE:
            entitlements.features[addon.target_key] = True
            entitlements.provenance.setdefault(
                f"feature:{addon.target_key}", []
            ).append(label)

        elif addon.kind == AddOnKind.LIMIT_INCREMENT:
            spec = entitlements.limits.get(addon.target_key)
            increment = addon.increment * subscription_addon.quantity
            if spec is None:
                spec = LimitSpec(key=addon.target_key, value=increment, sources=[])
                entitlements.limits[addon.target_key] = spec
            elif spec.is_unlimited:
                # Already unlimited; an increment cannot improve on that.
                spec.sources.append(f"{label} (no effect: already unlimited)")
                continue
            else:
                spec.value += increment
            spec.sources.append(label)


def _apply_grants(organization, entitlements: ResolvedEntitlements) -> None:
    now = timezone.now()
    grants = EntitlementGrant.objects.filter(
        organization=organization, revoked_at__isnull=True, granted_at__lte=now
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    for grant in grants:
        spec = entitlements.limits.get(grant.key)
        label = f"grant:{grant.uuid} {grant.delta:+d}"
        if spec is None:
            entitlements.limits[grant.key] = LimitSpec(
                key=grant.key, value=max(grant.delta, 0), sources=[label]
            )
            continue
        if spec.is_unlimited:
            spec.sources.append(f"{label} (no effect: already unlimited)")
            continue
        spec.value = max(spec.value + grant.delta, 0)
        spec.sources.append(label)


def _apply_overrides(organization, entitlements: ResolvedEntitlements) -> None:
    overrides = EntitlementOverride.objects.filter(organization=organization)
    for override in overrides:
        if not override.is_in_effect:
            continue
        label = f"override:{override.uuid}"

        if override.kind == OverrideKind.MODULE:
            entitlements.modules[override.key] = bool(override.is_enabled)
            entitlements.provenance[f"module:{override.key}"] = [label]

        elif override.kind == OverrideKind.FEATURE:
            entitlements.features[override.key] = bool(override.is_enabled)
            entitlements.provenance[f"feature:{override.key}"] = [label]

        elif override.kind == OverrideKind.LIMIT:
            value = UNLIMITED if override.is_unlimited else override.value
            existing = entitlements.limits.get(override.key)
            enforcement = (
                override.enforcement
                or (existing.enforcement if existing else Enforcement.HARD)
            )
            entitlements.limits[override.key] = LimitSpec(
                key=override.key,
                value=value,
                enforcement=enforcement,
                warn_at_percent=existing.warn_at_percent if existing else 80,
                sources=[label],
            )


def _derive_facility_type_limits(entitlements: ResolvedEntitlements) -> None:
    """Fill in per-type facility limits that were never stated explicitly.

    A plan usually says `max_facilities = 5` and nothing per type. Rather
    than treating an unstated type as zero (which would block a perfectly
    legitimate clinic), a type inherits the overall facility ceiling -- but
    only if the organization has the module that type requires. The overall
    ceiling still applies on top, so a customer with 5 facilities cannot open
    5 clinics *and* 5 pharmacies.
    """
    overall = entitlements.limits.get(LimitKey.MAX_FACILITIES)
    for facility_type, required_module in FACILITY_TYPE_MODULE.items():
        key = LimitKey.for_facility_type(facility_type)
        if key in entitlements.limits:
            continue

        if required_module and not entitlements.has_module(required_module):
            entitlements.limits[key] = LimitSpec(
                key=key,
                value=0,
                sources=[f"derived: module '{required_module}' not entitled"],
            )
            continue

        if overall is None:
            entitlements.limits[key] = LimitSpec(
                key=key, value=0, sources=["derived: no facility limit defined"]
            )
        else:
            entitlements.limits[key] = LimitSpec(
                key=key,
                value=overall.value,
                enforcement=overall.enforcement,
                warn_at_percent=overall.warn_at_percent,
                sources=[f"derived from {LimitKey.MAX_FACILITIES}"],
            )


def resolve_entitlements(organization) -> ResolvedEntitlements:
    """Compute the organization's effective entitlements.

    Never cached across requests: a support agent granting headroom expects
    the next click to reflect it. Where a hot path needs caching, cache the
    `ResolvedEntitlements` for the duration of a single request.
    """
    subscription = active_subscription(organization)

    if subscription is None:
        entitlements = ResolvedEntitlements(
            organization_id=str(organization.uuid),
            plan_code="",
            subscription_status="none",
            is_entitled=False,
            resolved_at=timezone.now(),
        )
        _derive_facility_type_limits(entitlements)
        return entitlements

    entitlements = ResolvedEntitlements(
        organization_id=str(organization.uuid),
        plan_code=subscription.plan.code,
        subscription_status=subscription.status,
        is_entitled=subscription.is_entitled,
        resolved_at=timezone.now(),
    )

    _apply_plan(subscription.plan, entitlements)
    _apply_addons(subscription, entitlements)
    _apply_grants(organization, entitlements)
    _apply_overrides(organization, entitlements)
    _derive_facility_type_limits(entitlements)

    return entitlements
