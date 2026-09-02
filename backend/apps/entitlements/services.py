"""The quota guard: the single place that answers "may they do this?".

Everything that consumes an entitlement -- creating a facility, inviting a
user, uploading a file, calling the API -- goes through `check_quota`. Having
one answer point is what makes the rules auditable: there is exactly one
implementation of "is this allowed", and it explains itself.
"""

import logging

# dataclass / field: QuotaDecision is the answer object returned by every
# quota check -- deliberately richer than a boolean, so a refusal can explain
# itself and offer a way forward (dev log entry 012).
from dataclasses import dataclass, field

from django.utils import timezone

# FACILITY_TYPE_MODULE: check_facility_quota uses it to ask the first of the
# three facility questions -- is the module entitled at all?
# LimitKey: builds per-type keys and recognises them on the way back in.
from apps.catalog.keys import FACILITY_TYPE_MODULE, LimitKey

# Enforcement: decides whether exceeding a limit blocks, warns, or bills.
from apps.catalog.models import Enforcement

# EntitlementError / QuotaExceeded / SubscriptionInactive: the three refusal
# shapes, each mapping to its own HTTP status and client-side handling.
from apps.common.exceptions import EntitlementError, QuotaExceeded, SubscriptionInactive

# EntitlementSnapshot: persists a resolution so a past decision stays
# explainable after the inputs have moved on.
from apps.entitlements.models import EntitlementSnapshot

# LimitSpec / ResolvedEntitlements / resolve_entitlements: the resolver's
# output types and entry point. Callers may pass an already-resolved instance
# to avoid re-resolving several times within one request.
from apps.entitlements.resolver import LimitSpec, ResolvedEntitlements, resolve_entitlements

logger = logging.getLogger("nirova.entitlements")


@dataclass
class QuotaDecision:
    """The answer, with enough context to render it in a UI.

    Deliberately not a bare boolean. When a customer is blocked from opening
    a branch, the screen should say what the limit is, how much of it they
    are using, where the limit came from, and what they can do about it --
    all of which is here.
    """

    key: str
    allowed: bool
    limit: int | None
    current_usage: int
    requested: int
    enforcement: str
    reason: str = ""
    #: True when the action may proceed but should be recorded as an overage.
    is_overage: bool = False
    #: True when usage has crossed the warning threshold.
    is_warning: bool = False
    sources: list = field(default_factory=list)
    remediation: list = field(default_factory=list)

    @property
    def is_unlimited(self) -> bool:
        return self.limit is None

    @property
    def remaining(self) -> int | None:
        if self.limit is None:
            return None
        return max(self.limit - self.current_usage, 0)

    @property
    def usage_percent(self) -> float | None:
        if not self.limit:
            return None
        return round(self.current_usage / self.limit * 100, 1)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "allowed": self.allowed,
            "limit": self.limit,
            "unlimited": self.is_unlimited,
            "current_usage": self.current_usage,
            "requested": self.requested,
            "remaining": self.remaining,
            "usage_percent": self.usage_percent,
            "enforcement": self.enforcement,
            "reason": self.reason,
            "is_overage": self.is_overage,
            "is_warning": self.is_warning,
            "sources": self.sources,
            "remediation": self.remediation,
        }

    def raise_if_blocked(self):
        if not self.allowed:
            raise QuotaExceeded(self.reason, detail=self.as_dict())
        return self


# ---------------------------------------------------------------------------
# Usage providers
# ---------------------------------------------------------------------------
#
# A provider answers "how much of this limit is the organization already
# using?". Registering them by key keeps the guard generic: adding a new
# metered thing means writing one function, not editing the guard.

_USAGE_PROVIDERS: dict[str, callable] = {}


def usage_provider(*keys):
    def decorator(func):
        for key in keys:
            _USAGE_PROVIDERS[key] = func
        return func

    return decorator


@usage_provider(LimitKey.MAX_FACILITIES)
def _facility_usage(organization, key: str) -> int:
    """Facilities counted from the control-plane registry.

    Counting here rather than in the tenant database is what lets the check
    run inside the same transaction that approves a new facility, without
    opening a second connection mid-transaction.
    """
    from apps.tenancy.models import FacilityRegistryEntry, FacilityRegistryStatus

    return FacilityRegistryEntry.objects.filter(
        organization=organization,
        status__in=[
            FacilityRegistryStatus.PENDING,
            FacilityRegistryStatus.ACTIVE,
            FacilityRegistryStatus.SUSPENDED,
        ],
    ).count()


def _facility_type_usage(organization, key: str) -> int:
    from apps.tenancy.models import FacilityRegistryEntry, FacilityRegistryStatus

    facility_type = LimitKey.facility_type_from_key(key)
    return FacilityRegistryEntry.objects.filter(
        organization=organization,
        facility_type=facility_type,
        status__in=[
            FacilityRegistryStatus.PENDING,
            FacilityRegistryStatus.ACTIVE,
            FacilityRegistryStatus.SUSPENDED,
        ],
    ).count()


@usage_provider(LimitKey.MAX_USERS)
def _user_usage(organization, key: str) -> int:
    from apps.identity.models import Membership, MembershipStatus

    return Membership.objects.filter(
        organization=organization, status=MembershipStatus.ACTIVE
    ).count()


def _metered_usage(organization, key: str) -> int:
    """Fallback: read the current period's counter for the matching meter."""
    from apps.metering.models import UsageCounter

    counter = (
        UsageCounter.objects.filter(organization=organization, limit_key=key)
        .order_by("-period_start")
        .first()
    )
    return int(counter.value) if counter else 0


def get_current_usage(organization, key: str) -> int:
    if LimitKey.is_facility_type_limit(key):
        return _facility_type_usage(organization, key)
    provider = _USAGE_PROVIDERS.get(key)
    if provider is None:
        return _metered_usage(organization, key)
    return provider(organization, key)


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def _remediation_for(key: str, entitlements: ResolvedEntitlements) -> list:
    """Suggest what the customer can actually do about a blocked action."""
    options = []
    if LimitKey.is_facility_type_limit(key) or key == LimitKey.MAX_FACILITIES:
        options.append(
            {
                "action": "purchase_addon",
                "label": "Add capacity to the current plan",
                "detail": "Buy additional facility capacity as an add-on.",
            }
        )
        options.append(
            {
                "action": "close_facility",
                "label": "Close an existing facility",
                "detail": "Closing a facility frees its slot; suspending does not.",
            }
        )
    options.append(
        {
            "action": "upgrade_plan",
            "label": "Move to a larger plan",
            "detail": f"The current plan is '{entitlements.plan_code}'.",
        }
    )
    options.append(
        {
            "action": "contact_platform",
            "label": "Request an exception",
            "detail": "Platform staff can grant temporary or contracted headroom.",
        }
    )
    return options


def check_quota(
    organization,
    key: str,
    requested: int = 1,
    entitlements: ResolvedEntitlements | None = None,
    current_usage: int | None = None,
) -> QuotaDecision:
    """Decide whether `organization` may consume `requested` more of `key`.

    Does not mutate anything and does not raise on refusal -- callers that
    want an exception call `.raise_if_blocked()`. Returning a decision lets
    the UI preview the outcome ("this will exceed your plan") before the user
    commits to the action, which is the difference between a helpful product
    and a wall.
    """
    entitlements = entitlements or resolve_entitlements(organization)

    if not entitlements.is_entitled:
        return QuotaDecision(
            key=key,
            allowed=False,
            limit=0,
            current_usage=0,
            requested=requested,
            enforcement=Enforcement.HARD,
            reason=(
                "The organization does not have an active subscription, so no "
                "new capacity can be consumed."
            ),
            sources=["subscription:inactive"],
            remediation=_remediation_for(key, entitlements),
        )

    spec: LimitSpec = entitlements.limit(key)
    usage = current_usage if current_usage is not None else get_current_usage(
        organization, key
    )

    if spec.is_unlimited:
        return QuotaDecision(
            key=key,
            allowed=True,
            limit=None,
            current_usage=usage,
            requested=requested,
            enforcement=spec.enforcement,
            reason="No limit applies.",
            sources=spec.sources,
        )

    projected = usage + requested
    exceeds = projected > spec.value
    warning_threshold = spec.value * spec.warn_at_percent / 100

    if not exceeds:
        return QuotaDecision(
            key=key,
            allowed=True,
            limit=spec.value,
            current_usage=usage,
            requested=requested,
            enforcement=spec.enforcement,
            reason=f"Within the limit ({projected} of {spec.value}).",
            is_warning=projected >= warning_threshold,
            sources=spec.sources,
        )

    over_by = projected - spec.value
    base_reason = (
        f"This would use {projected} of a limit of {spec.value} "
        f"({over_by} over)."
    )

    if spec.enforcement == Enforcement.SOFT:
        return QuotaDecision(
            key=key,
            allowed=True,
            limit=spec.value,
            current_usage=usage,
            requested=requested,
            enforcement=spec.enforcement,
            reason=f"{base_reason} Allowed, and flagged for review.",
            is_overage=True,
            is_warning=True,
            sources=spec.sources,
            remediation=_remediation_for(key, entitlements),
        )

    if spec.enforcement == Enforcement.METERED:
        return QuotaDecision(
            key=key,
            allowed=True,
            limit=spec.value,
            current_usage=usage,
            requested=requested,
            enforcement=spec.enforcement,
            reason=f"{base_reason} Allowed and billed as overage.",
            is_overage=True,
            is_warning=True,
            sources=spec.sources,
        )

    return QuotaDecision(
        key=key,
        allowed=False,
        limit=spec.value,
        current_usage=usage,
        requested=requested,
        enforcement=spec.enforcement,
        reason=base_reason,
        sources=spec.sources,
        remediation=_remediation_for(key, entitlements),
    )


def check_facility_quota(
    organization,
    facility_type: str,
    requested: int = 1,
    entitlements: ResolvedEntitlements | None = None,
) -> list[QuotaDecision]:
    """Check every constraint that governs opening a facility of a type.

    Three separate questions, all of which must pass, returned together so
    the caller can show the customer exactly which one bites:

    1. Is the module for this facility type entitled at all?
    2. Is the per-type ceiling clear?
    3. Is the overall facility ceiling clear?
    """
    entitlements = entitlements or resolve_entitlements(organization)
    decisions = []

    required_module = FACILITY_TYPE_MODULE.get(facility_type)
    if required_module and not entitlements.has_module(required_module):
        decisions.append(
            QuotaDecision(
                key=f"module:{required_module}",
                allowed=False,
                limit=0,
                current_usage=0,
                requested=requested,
                enforcement=Enforcement.HARD,
                reason=(
                    f"The '{required_module}' module is not part of this "
                    f"subscription, so {facility_type} facilities cannot be opened."
                ),
                sources=entitlements.provenance.get(f"module:{required_module}", []),
                remediation=_remediation_for(
                    LimitKey.for_facility_type(facility_type), entitlements
                ),
            )
        )

    decisions.append(
        check_quota(
            organization,
            LimitKey.for_facility_type(facility_type),
            requested=requested,
            entitlements=entitlements,
        )
    )
    decisions.append(
        check_quota(
            organization,
            LimitKey.MAX_FACILITIES,
            requested=requested,
            entitlements=entitlements,
        )
    )
    return decisions


def facility_quota_summary(organization, entitlements=None) -> dict:
    """Per-type capacity, for the facilities screen and the platform console.

    Rendering this up front is the honest way to run limits: the customer
    sees "2 of 3 pharmacies used" before they start filling in a form, not
    after.
    """
    entitlements = entitlements or resolve_entitlements(organization)
    summary = {}
    for facility_type in FACILITY_TYPE_MODULE:
        key = LimitKey.for_facility_type(facility_type)
        spec = entitlements.limit(key)
        usage = get_current_usage(organization, key)
        required_module = FACILITY_TYPE_MODULE.get(facility_type)
        summary[facility_type] = {
            "facility_type": facility_type,
            "limit": spec.value,
            "unlimited": spec.is_unlimited,
            "used": usage,
            "remaining": spec.remaining(usage),
            "enforcement": spec.enforcement,
            "module_entitled": (
                True if not required_module else entitlements.has_module(required_module)
            ),
            "sources": spec.sources,
        }

    overall_spec = entitlements.limit(LimitKey.MAX_FACILITIES)
    overall_usage = get_current_usage(organization, LimitKey.MAX_FACILITIES)
    summary["_overall"] = {
        "limit": overall_spec.value,
        "unlimited": overall_spec.is_unlimited,
        "used": overall_usage,
        "remaining": overall_spec.remaining(overall_usage),
        "sources": overall_spec.sources,
    }
    return summary


def require_module(organization, module_code: str, entitlements=None) -> None:
    """Raise unless the organization has the module. For view guards."""
    entitlements = entitlements or resolve_entitlements(organization)
    if not entitlements.is_entitled:
        raise SubscriptionInactive(
            detail={"organization": str(organization.uuid)},
        )
    if not entitlements.has_module(module_code):
        raise EntitlementError(
            f"The '{module_code}' module is not included in this subscription.",
            detail={
                "module": module_code,
                "plan": entitlements.plan_code,
                "sources": entitlements.provenance.get(f"module:{module_code}", []),
            },
        )


def require_feature(organization, feature_code: str, entitlements=None) -> None:
    entitlements = entitlements or resolve_entitlements(organization)
    if not entitlements.has_feature(feature_code):
        raise EntitlementError(
            f"The '{feature_code}' feature is not enabled for this subscription.",
            detail={"feature": feature_code, "plan": entitlements.plan_code},
        )


def record_snapshot(organization, reason: str = "", entitlements=None) -> EntitlementSnapshot:
    """Persist the current resolution, so a past decision stays explainable."""
    entitlements = entitlements or resolve_entitlements(organization)
    return EntitlementSnapshot.objects.create(
        organization=organization,
        resolved_at=timezone.now(),
        plan_code=entitlements.plan_code,
        subscription_status=entitlements.subscription_status,
        modules=entitlements.modules,
        features=entitlements.features,
        limits={k: v.as_dict() for k, v in entitlements.limits.items()},
        provenance=entitlements.provenance,
        triggering_reason=reason[:255],
    )
