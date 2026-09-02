"""Submitting, routing, deciding and executing facility change requests."""

import logging

# timedelta: the churn look-back window and the request expiry deadline, both
# expressed in days read from a ChangeRequestPolicy field.
from datetime import timedelta

# transaction: submit_request and decide are @transaction.atomic. Each writes
# several rows -- the request, its decision, possibly a subscription add-on
# and a subscription event -- that must not be able to half-happen. An
# approval recorded without the capacity it authorised would let execution
# proceed on a false premise.
from django.db import transaction

from django.utils import timezone

from apps.catalog.keys import FACILITY_TYPE_MODULE, FeatureFlag, LimitKey
from apps.common.exceptions import (
    DomainError,
    SegregationOfDutiesViolation,
)
from apps.entitlements.resolver import resolve_entitlements
from apps.entitlements.services import check_facility_quota, record_snapshot
from apps.provisioning.models import (
    CAPACITY_CONSUMING,
    DESTRUCTIVE,
    ApprovalLevel,
    ChangeRequestDecision,
    ChangeRequestPolicy,
    ChangeRequestStatus,
    DecisionType,
    FacilityChangeRequest,
)
from apps.tenancy.models import FacilityRegistryEntry, FacilityRegistryStatus

logger = logging.getLogger("nirova.provisioning")


class ChangeRequestError(DomainError):
    code = "change_request_invalid"


def generate_reference() -> str:
    """Sequential, human-quotable reference: FCR-2026-0041."""
    year = timezone.now().year
    prefix = f"FCR-{year}-"
    last = (
        FacilityChangeRequest.objects.filter(reference__startswith=prefix)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{sequence:04d}"


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def detect_churn(organization, facility_type: str, policy) -> dict:
    """Look for capacity being cycled rather than genuinely reorganised.

    Closing a branch and opening another is often legitimate -- a relocation,
    a lease ending. It is also the obvious way to stay under a limit while
    running more sites than you pay for. Rather than guessing, the pattern is
    surfaced to a human with the dates attached.
    """
    window_days = getattr(policy, "churn_window_days", 90)
    threshold = getattr(policy, "churn_threshold", 2)
    since = timezone.now() - timedelta(days=window_days)

    recent_closures = FacilityRegistryEntry.objects.filter(
        organization=organization,
        facility_type=facility_type,
        status=FacilityRegistryStatus.CLOSED,
        closed_at__gte=since,
    ).order_by("-closed_at")

    count = recent_closures.count()
    return {
        "window_days": window_days,
        "threshold": threshold,
        "closures_in_window": count,
        "is_churn_signal": count >= threshold,
        "recent": [
            {
                "name": entry.name,
                "code": entry.code,
                "closed_at": entry.closed_at.isoformat() if entry.closed_at else None,
            }
            for entry in recent_closures[:5]
        ],
    }


def evaluate_request(
    organization,
    request_type: str,
    facility_type: str,
    target_facility_uuid=None,
) -> dict:
    """Work out what a proposed change would mean, before anyone commits.

    Called twice: once when the frontend previews the change (so the user
    sees "this exceeds your plan" while still filling the form), and again at
    submission, where the result is frozen onto the request.
    """
    policy = ChangeRequestPolicy.for_organization(organization)
    entitlements = resolve_entitlements(organization)

    evaluation = {
        "evaluated_at": timezone.now().isoformat(),
        "plan_code": entitlements.plan_code,
        "subscription_status": entitlements.subscription_status,
        "quota_decisions": [],
        "escalation_reasons": [],
        "within_entitlement": True,
        "churn": {},
        "required_module": FACILITY_TYPE_MODULE.get(facility_type),
    }

    if request_type in CAPACITY_CONSUMING:
        decisions = check_facility_quota(organization, facility_type, requested=1,
                                         entitlements=entitlements)
        evaluation["quota_decisions"] = [d.as_dict() for d in decisions]
        blocked = [d for d in decisions if not d.allowed]
        evaluation["within_entitlement"] = not blocked

        for decision in blocked:
            if decision.key.startswith("module:"):
                evaluation["escalation_reasons"].append(
                    {
                        "code": "module_not_entitled",
                        "message": decision.reason,
                        "key": decision.key,
                    }
                )
            else:
                evaluation["escalation_reasons"].append(
                    {
                        "code": "over_quota",
                        "message": decision.reason,
                        "key": decision.key,
                        "limit": decision.limit,
                        "current_usage": decision.current_usage,
                    }
                )

        churn = detect_churn(organization, facility_type, policy)
        evaluation["churn"] = churn
        if churn["is_churn_signal"]:
            evaluation["escalation_reasons"].append(
                {
                    "code": "churn_pattern",
                    "message": (
                        f"{churn['closures_in_window']} {facility_type} "
                        f"facilities were closed in the last "
                        f"{churn['window_days']} days."
                    ),
                }
            )

    if request_type in DESTRUCTIVE:
        evaluation["escalation_reasons"].append(
            {
                "code": "destructive_change",
                "message": (
                    "Closing a facility ends its operations and releases its "
                    "capacity. Historical records are retained."
                ),
            }
        )

    evaluation["approval_level"] = _derive_approval_level(
        request_type, evaluation, policy, entitlements
    )
    return evaluation


def _derive_approval_level(request_type, evaluation, policy, entitlements) -> str:
    """Decide who must approve. Never chosen by the requester.

    The rule in one line: if it fits inside what they already pay for and is
    not destructive, the customer governs it; if it changes the commercial
    relationship, the platform does.
    """
    if not evaluation["within_entitlement"]:
        return ApprovalLevel.BOTH

    if any(
        reason["code"] == "churn_pattern" for reason in evaluation["escalation_reasons"]
    ):
        return ApprovalLevel.BOTH

    if request_type in DESTRUCTIVE:
        if getattr(policy, "require_platform_approval_for_close", False):
            return ApprovalLevel.BOTH
        if getattr(policy, "require_org_approval_for_close", True):
            return ApprovalLevel.ORGANIZATION
        return ApprovalLevel.AUTOMATIC

    self_service_allowed = (
        getattr(policy, "allow_self_service_within_quota", True)
        and entitlements.has_feature(FeatureFlag.SELF_SERVICE_FACILITY_CREATION)
    )
    if self_service_allowed and not getattr(
        policy, "require_org_approval_for_open", True
    ):
        return ApprovalLevel.AUTOMATIC

    return ApprovalLevel.ORGANIZATION


def _status_for_level(level: str) -> str:
    if level == ApprovalLevel.PLATFORM:
        return ChangeRequestStatus.PLATFORM_REVIEW
    if level in (ApprovalLevel.ORGANIZATION, ApprovalLevel.BOTH):
        return ChangeRequestStatus.ORG_REVIEW
    return ChangeRequestStatus.APPROVED


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


@transaction.atomic
def submit_request(
    organization,
    request_type: str,
    facility_type: str,
    requested_by,
    payload: dict | None = None,
    justification: str = "",
    target_facility_uuid=None,
    requested_effective_date=None,
) -> FacilityChangeRequest:
    """Raise a facility change request and route it to the right approver."""
    policy = ChangeRequestPolicy.for_organization(organization)
    payload = payload or {}

    if getattr(policy, "require_justification", True):
        minimum = getattr(policy, "min_justification_length", 40)
        if len(justification.strip()) < minimum:
            raise ChangeRequestError(
                f"A justification of at least {minimum} characters is required "
                "so the approver can weigh up the request.",
                detail={"field": "justification", "min_length": minimum},
            )

    evaluation = evaluate_request(
        organization, request_type, facility_type, target_facility_uuid
    )
    approval_level = evaluation["approval_level"]

    request = FacilityChangeRequest.objects.create(
        organization=organization,
        reference=generate_reference(),
        request_type=request_type,
        facility_type=facility_type,
        target_facility_uuid=target_facility_uuid,
        proposed_name=payload.get("name", ""),
        proposed_code=payload.get("code", ""),
        payload=payload,
        justification=justification,
        requested_effective_date=requested_effective_date,
        quota_evaluation=evaluation,
        escalation_reasons=evaluation["escalation_reasons"],
        churn_signal=evaluation.get("churn", {}),
        requires_capacity_purchase=not evaluation["within_entitlement"],
        approval_level=approval_level,
        status=_status_for_level(approval_level),
        requested_by_id=getattr(requested_by, "uuid", None),
        requested_by_email=getattr(requested_by, "email", ""),
        submitted_at=timezone.now(),
        expires_at=timezone.now()
        + timedelta(days=getattr(policy, "auto_expire_days", 30)),
        created_by_id=getattr(requested_by, "uuid", None),
    )

    record_snapshot(
        organization,
        reason=f"Facility change request {request.reference}",
    )

    if request.status == ChangeRequestStatus.APPROVED:
        # Self-service inside the entitlement: still recorded, still audited,
        # just not queued behind a human.
        ChangeRequestDecision.objects.create(
            request=request,
            level=ApprovalLevel.AUTOMATIC,
            decision=DecisionType.APPROVE,
            decided_by_id=getattr(requested_by, "uuid", None),
            decided_by_email=getattr(requested_by, "email", ""),
            comment="Within entitlement; auto-approved by policy.",
        )
        execute_request(request, actor=requested_by)

    logger.info(
        "Facility change request %s raised for %s (%s, level=%s)",
        request.reference,
        organization.slug,
        request_type,
        approval_level,
    )
    return request


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


def _assert_may_decide(request, actor, level, policy) -> None:
    if not getattr(policy, "enforce_segregation_of_duties", True):
        return
    actor_id = getattr(actor, "uuid", None)
    if actor_id and request.requested_by_id == actor_id:
        raise SegregationOfDutiesViolation(
            "The person who raised a facility change may not approve it.",
            detail={"reference": request.reference},
        )


@transaction.atomic
def decide(
    request: FacilityChangeRequest,
    actor,
    decision: str,
    level: str,
    comment: str = "",
    granted_addon_code: str = "",
    granted_addon_quantity: int = 0,
    granted_addons: list | None = None,
    granted_entitlement_delta: int | None = None,
    conditions: list | None = None,
) -> FacilityChangeRequest:
    """Record a verdict and advance the request.

    Approving at the final required level executes the change immediately;
    there is no separate "apply" step to forget.
    """
    if not request.is_open:
        raise ChangeRequestError(
            f"Request {request.reference} is {request.get_status_display().lower()} "
            "and can no longer be decided.",
            detail={"status": request.status},
        )

    policy = ChangeRequestPolicy.for_organization(request.organization)
    if decision == DecisionType.APPROVE:
        _assert_may_decide(request, actor, level, policy)

    ChangeRequestDecision.objects.create(
        request=request,
        level=level,
        decision=decision,
        decided_by_id=getattr(actor, "uuid", None),
        decided_by_email=getattr(actor, "email", ""),
        comment=comment,
        conditions=conditions or [],
        granted_addon_code=granted_addon_code,
        granted_addon_quantity=granted_addon_quantity,
        granted_entitlement_delta=granted_entitlement_delta,
    )

    if decision == DecisionType.REJECT:
        request.status = ChangeRequestStatus.REJECTED
        request.decided_at = timezone.now()
        request.save(update_fields=["status", "decided_at", "updated_at"])
        return request

    if decision == DecisionType.REQUEST_INFO:
        request.status = ChangeRequestStatus.INFO_REQUESTED
        request.save(update_fields=["status", "updated_at"])
        return request

    if decision == DecisionType.WITHDRAW:
        request.status = ChangeRequestStatus.WITHDRAWN
        request.decided_at = timezone.now()
        request.save(update_fields=["status", "decided_at", "updated_at"])
        return request

    if decision == DecisionType.ESCALATE:
        request.status = ChangeRequestStatus.PLATFORM_REVIEW
        request.approval_level = ApprovalLevel.BOTH
        request.save(update_fields=["status", "approval_level", "updated_at"])
        return request

    # -- approval --------------------------------------------------------

    # Attaching capacity is usually two purchases, not one: opening a
    # hospital on a plan without the hospital module needs the module *and* a
    # hospital slot. `granted_addons` carries the list; the single-add-on
    # arguments remain for the common one-purchase case.
    for grant in _normalise_addon_grants(
        granted_addons, granted_addon_code, granted_addon_quantity
    ):
        _attach_addon(request, grant["code"], grant["quantity"], actor)
    if granted_entitlement_delta:
        _grant_headroom(request, granted_entitlement_delta, actor, comment)

    needs_platform_next = (
        request.approval_level == ApprovalLevel.BOTH
        and level == ApprovalLevel.ORGANIZATION
    )
    if needs_platform_next:
        request.status = ChangeRequestStatus.PLATFORM_REVIEW
        request.save(update_fields=["status", "updated_at"])
        return request

    request.status = ChangeRequestStatus.APPROVED
    request.decided_at = timezone.now()
    request.save(update_fields=["status", "decided_at", "updated_at"])

    effective = request.requested_effective_date
    if effective and effective > timezone.localdate():
        request.status = ChangeRequestStatus.SCHEDULED
        request.save(update_fields=["status", "updated_at"])
        return request

    return execute_request(request, actor=actor)


def _normalise_addon_grants(granted_addons, single_code, single_quantity) -> list:
    """Collapse the two ways of naming add-ons into one list.

    Duplicated codes are summed rather than applied twice, so a caller that
    passes the same add-on in both forms does not silently double the
    customer's bill.
    """
    quantities: dict[str, int] = {}

    for grant in granted_addons or []:
        code = (grant.get("code") or "").strip()
        quantity = int(grant.get("quantity") or 0)
        if code and quantity > 0:
            quantities[code] = quantities.get(code, 0) + quantity

    if single_code and single_quantity:
        quantities[single_code] = quantities.get(single_code, 0) + int(single_quantity)

    return [{"code": code, "quantity": qty} for code, qty in quantities.items()]


def _attach_addon(request, addon_code: str, quantity: int, actor) -> None:
    """Buy the capacity the approver agreed to, as part of the same decision."""
    from apps.catalog.models import AddOn
    from apps.entitlements.resolver import active_subscription
    from apps.subscriptions.models import (
        SubscriptionAddOn,
        SubscriptionEvent,
        SubscriptionEventType,
    )

    subscription = active_subscription(request.organization)
    if subscription is None:
        raise ChangeRequestError(
            "Capacity cannot be added without an active subscription.",
            detail={"reference": request.reference},
        )

    addon = AddOn.objects.filter(code=addon_code, is_active=True).first()
    if addon is None:
        raise ChangeRequestError(
            f"No active add-on with code '{addon_code}'.",
            detail={"addon": addon_code},
        )

    existing = SubscriptionAddOn.objects.filter(
        subscription=subscription, addon=addon, is_active=True
    ).first()
    if existing:
        existing.quantity += quantity
        existing.save(update_fields=["quantity", "updated_at"])
    else:
        SubscriptionAddOn.objects.create(
            subscription=subscription,
            addon=addon,
            quantity=quantity,
            unit_price=addon.unit_price,
            source_reference=request.reference,
        )

    SubscriptionEvent.objects.create(
        subscription=subscription,
        event_type=SubscriptionEventType.ADDON_ADDED,
        actor_id=getattr(actor, "uuid", None),
        reason=f"Approved with {request.reference}",
        payload={"addon": addon_code, "quantity": quantity},
    )


def _grant_headroom(request, delta: int, actor, reason: str) -> None:
    """Give temporary capacity instead of selling it. For goodwill and pilots."""
    from apps.entitlements.models import EntitlementGrant

    EntitlementGrant.objects.create(
        organization=request.organization,
        key=LimitKey.for_facility_type(request.facility_type),
        delta=delta,
        reason=reason or f"Granted with {request.reference}",
        granted_by_id=getattr(actor, "uuid", None),
        source_reference=request.reference,
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute_request(request: FacilityChangeRequest, actor=None) -> FacilityChangeRequest:
    """Apply an approved change to the tenant database and the registry.

    Re-checks the quota immediately before acting. Time passes between
    approval and execution -- a scheduled request may sit for weeks -- and
    the customer's entitlement may have moved. Approving is permission to
    act, not a licence to act regardless of the position at the time.
    """
    from apps.organization.services import FacilityService

    if request.status not in {
        ChangeRequestStatus.APPROVED,
        ChangeRequestStatus.SCHEDULED,
    }:
        raise ChangeRequestError(
            f"Request {request.reference} is not approved.",
            detail={"status": request.status},
        )

    try:
        if request.request_type in CAPACITY_CONSUMING:
            decisions = check_facility_quota(
                request.organization, request.facility_type, requested=1
            )
            blocked = [d for d in decisions if not d.allowed]
            if blocked:
                raise ChangeRequestError(
                    "The approved change no longer fits within the entitlement. "
                    "It was re-checked at execution time.",
                    detail={"blocked": [d.as_dict() for d in blocked]},
                )

        service = FacilityService(request.organization, actor=actor)
        facility_uuid = service.apply_change_request(request)

        request.status = ChangeRequestStatus.EXECUTED
        request.executed_at = timezone.now()
        request.resulting_facility_uuid = facility_uuid
        request.execution_error = ""
        request.save(
            update_fields=[
                "status",
                "executed_at",
                "resulting_facility_uuid",
                "execution_error",
                "updated_at",
            ]
        )
        logger.info("Executed %s for %s", request.reference, request.organization.slug)

    except Exception as exc:
        logger.exception("Execution failed for %s", request.reference)
        request.status = ChangeRequestStatus.FAILED
        request.execution_error = str(exc)[:2000]
        request.save(update_fields=["status", "execution_error", "updated_at"])
        raise

    return request


def expire_stale_requests() -> int:
    """Close out requests nobody decided. Run daily."""
    now = timezone.now()
    stale = FacilityChangeRequest.objects.filter(
        status__in=[
            ChangeRequestStatus.SUBMITTED,
            ChangeRequestStatus.ORG_REVIEW,
            ChangeRequestStatus.PLATFORM_REVIEW,
            ChangeRequestStatus.INFO_REQUESTED,
        ],
        expires_at__lt=now,
    )
    return stale.update(status=ChangeRequestStatus.EXPIRED, decided_at=now)
