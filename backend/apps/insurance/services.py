"""Checking cover, asking permission, claiming, and chasing what is owed.

The rules this layer keeps, all of which cost a hospital real money when they
are not kept.

**Cover is checked against the date of service.** Never against today. A
policy that lapsed last week did not lapse before last month's admission, and
a system that asks "is this active" gets the wrong answer on every late claim.

**A patient is told what they owe before the treatment, not after.**
`estimate` resolves the deductible, the co-payment, the sub-limits and the
remaining sum insured into one number, and every deduction it predicts carries
its reason. A hospital that discovers the shortfall at discharge is having an
argument it could have had at admission.

**Submission deadlines are counted down, not discovered.** Missing the window
is the commonest way a valid claim becomes worthless, and it is per payer:
some allow ninety days, some fifteen.

**Nothing about a claim is overwritten.** Every response appends a
`ClaimEvent`. A claim is a conversation conducted over months by people who
leave, and the status field alone tells whoever picks it up nothing about how
it got there.

**Deductions are countable.** The reason comes from a fixed list, because the
only useful thing about a deduction is the aggregate — a hospital that learns
40% of its deductions are "consumables not covered" can change what it bills.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: a claim is money, and every one of its states is disputed sooner or
# later. Who submitted it, who accepted a deduction, and who wrote it off are
# the three questions asked afterwards.
from apps.audit.services import record
from apps.billing.models import Invoice, InvoiceStatus
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.entitlements.services import require_module
from apps.insurance.models import (
    DEDUCTION_REASON_KEYS,
    Claim,
    ClaimEvent,
    ClaimLine,
    ClaimStatus,
    Payer,
    PayerKind,
    Policy,
    PolicyStatus,
    PreAuthStatus,
    PreAuthorisation,
    SchemePackage,
    validate_deduction_reason,
)
# tenant_atomic_method: a claim and its lines are written together or not at
# all, and the transaction must open on the tenant connection -- the router
# refuses to guess, so a bare `transaction.atomic` would protect nothing.
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.insurance")

ZERO = Decimal("0.00")

#: Ageing buckets for claims, in days since submission.
AGEING_BUCKETS = [(0, 30), (31, 60), (61, 90), (91, None)]


class InsuranceError(DomainError):
    """The claim will not go out like that."""


class NotCovered(InsuranceError):
    """The policy does not answer for this."""


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def check_eligibility(patient, on_date=None, payer: Payer = None) -> dict:
    """Which of this patient's policies answer for treatment on a given date.

    `on_date` defaults to today but is the whole point of the function: a
    claim submitted in Bhadra for an admission in Shrawan is checked against
    Shrawan, and any other answer is wrong.

    Returns every policy with a sentence saying why it does or does not apply,
    rather than a boolean. The reception desk needs to be able to tell the
    patient which card to hand over.
    """
    on_date = on_date or timezone.localdate()
    policies = patient.policies.select_related("payer")
    if payer is not None:
        policies = policies.filter(payer=payer)

    rows = []
    for policy in policies:
        problems = []
        if policy.status == PolicyStatus.CANCELLED:
            problems.append("The policy was cancelled.")
        elif policy.status == PolicyStatus.SUSPENDED:
            problems.append("The policy is suspended.")
        if on_date < policy.valid_from:
            problems.append(
                f"Cover did not begin until {policy.valid_from}."
            )
        elif on_date > policy.valid_to:
            problems.append(f"Cover ended on {policy.valid_to}.")
        if policy.waiting_period_until and on_date <= policy.waiting_period_until:
            problems.append(
                "Within the waiting period, which runs until "
                f"{policy.waiting_period_until}."
            )
        if policy.remaining is not None and policy.remaining <= 0:
            problems.append(
                f"The sum insured of {policy.sum_insured} is exhausted."
            )

        rows.append({
            "policy": str(policy.uuid),
            "policy_number": policy.policy_number,
            "payer": policy.payer.name,
            "payer_kind": policy.payer.kind,
            "valid_from": policy.valid_from,
            "valid_to": policy.valid_to,
            "eligible": not problems,
            "problems": problems,
            "sum_insured": policy.sum_insured,
            "remaining": policy.remaining,
            "deductible": policy.deductible,
            "co_payment_percent": policy.co_payment_percent,
            "sub_limits": policy.sub_limits,
            "exclusions": policy.exclusions,
        })

    return {
        "patient": patient.full_name,
        "mrn": patient.mrn,
        "as_at": on_date,
        "policies": rows,
        "any_eligible": any(row["eligible"] for row in rows),
    }


def estimate(policy: Policy, amount, category_totals: dict = None,
             on_date=None) -> dict:
    """What the payer will cover and what the patient will owe.

    Applied in the order a payer applies them: sub-limits first, then the
    deductible, then the co-payment, then the remaining sum insured. The order
    matters — a co-payment taken before the deductible produces a different
    and smaller number, and the patient will have been told the wrong one.

    Every reduction carries its reason, because a patient told "the insurance
    will pay 62,000 of your 100,000" and given no breakdown is a complaint
    waiting to happen.
    """
    on_date = on_date or timezone.localdate()
    amount = money(amount)
    category_totals = category_totals or {}
    reductions = []
    covered = amount

    # Sub-limits, per category. A daily room cap is the commonest deduction on
    # a Nepali claim and the one patients are never told about.
    for category, cap in (policy.sub_limits or {}).items():
        billed = money(category_totals.get(category, 0))
        cap = money(cap)
        if billed > cap:
            over = billed - cap
            covered -= over
            reductions.append({
                "reason": "above_sub_limit",
                "amount": over,
                "detail": f"{category}: {billed} billed against a cap of {cap}",
            })

    deductible = money(policy.deductible)
    if deductible > 0:
        taken = min(deductible, covered)
        covered -= taken
        reductions.append({
            "reason": "deductible",
            "amount": taken,
            "detail": f"The first {deductible} is the patient's.",
        })

    if policy.co_payment_percent > 0:
        share = (covered * policy.co_payment_percent / 100).quantize(
            Decimal("0.01")
        )
        covered -= share
        reductions.append({
            "reason": "co_payment",
            "amount": share,
            "detail": f"{policy.co_payment_percent}% of the balance.",
        })

    if policy.remaining is not None and covered > policy.remaining:
        over = covered - policy.remaining
        covered = policy.remaining
        reductions.append({
            "reason": "above_sum_insured",
            "amount": over,
            "detail": (
                f"Only {policy.remaining} of the {policy.sum_insured} sum "
                "insured is left."
            ),
        })

    covered = max(ZERO, covered)
    return {
        "billed": amount,
        "payer_pays": covered,
        "patient_pays": amount - covered,
        "reductions": reductions,
        "eligible": policy.was_active_on(on_date),
    }


# ---------------------------------------------------------------------------
# Pre-authorisation
# ---------------------------------------------------------------------------


def _next_reference(model, prefix: str) -> str:
    return f"{prefix}-{model.objects.count() + 1:06d}"


@tenant_atomic_method
def request_preauthorisation(
    organization,
    policy: Policy,
    facility,
    treatment: str,
    amount,
    actor,
    diagnosis: str = "",
    diagnosis_code: str = "",
    encounter=None,
    planned_on=None,
    estimated_days=None,
) -> PreAuthorisation:
    """Ask a payer to agree to a planned treatment before it happens."""
    require_module(organization, ModuleCode.INSURANCE)

    on_date = planned_on or timezone.localdate()
    if not policy.was_active_on(on_date):
        raise NotCovered(
            f"Policy {policy.policy_number} does not cover "
            f"{on_date} — it runs from {policy.valid_from} to "
            f"{policy.valid_to}.",
            detail={"valid_from": str(policy.valid_from),
                    "valid_to": str(policy.valid_to)},
        )
    if not treatment.strip():
        raise InsuranceError("A pre-authorisation must say what is planned.")

    request = PreAuthorisation.objects.create(
        reference=_next_reference(PreAuthorisation, "PA"),
        policy=policy,
        patient=policy.patient,
        facility=facility,
        encounter=encounter,
        requested_by_name=getattr(actor, "full_name", "") or "",
        planned_treatment=treatment,
        diagnosis=diagnosis,
        diagnosis_code=diagnosis_code,
        planned_admission_on=planned_on,
        estimated_days=estimated_days,
        estimated_amount=money(amount),
        created_by_id=getattr(actor, "uuid", None),
    )
    record(
        AuditAction.CREATE,
        entity_type="insurance.PreAuthorisation",
        entity_id=request.uuid,
        entity_label=f"{request.reference} for {policy.patient.full_name}",
        reason=treatment[:200],
    )
    return request


@tenant_atomic_method
def record_preauth_response(
    request: PreAuthorisation,
    approved: bool,
    actor,
    approved_amount=None,
    payer_reference: str = "",
    valid_until=None,
    conditions: str = "",
    reason: str = "",
) -> PreAuthorisation:
    """Write down what the payer said.

    An approval for less than was asked is `partially_approved`, not
    `approved`. The distinction is the whole value of the record: a hospital
    proceeding on a 60,000 approval against a 90,000 estimate needs to know it
    is carrying 30,000 of risk, and "approved" does not say that.
    """
    if request.status not in (PreAuthStatus.REQUESTED,):
        raise InsuranceError(
            f"{request.reference} is already "
            f"{request.get_status_display().lower()}."
        )

    request.responded_at = timezone.now()
    request.payer_reference = payer_reference
    request.conditions = conditions

    if not approved:
        if not reason.strip():
            raise InsuranceError("A rejection must record the payer's reason.")
        request.status = PreAuthStatus.REJECTED
        request.rejection_reason = reason
        request.approved_amount = ZERO
    else:
        amount = money(
            request.estimated_amount if approved_amount is None
            else approved_amount
        )
        request.approved_amount = amount
        request.status = (
            PreAuthStatus.APPROVED if amount >= request.estimated_amount
            else PreAuthStatus.PARTIALLY_APPROVED
        )
        # A promise with no expiry is one the payer will later say expired.
        # Thirty days is the usual default and is written down rather than
        # assumed.
        request.valid_until = valid_until or (
            timezone.localdate() + timedelta(days=30)
        )

    request.save(update_fields=[
        "status", "responded_at", "payer_reference", "approved_amount",
        "valid_until", "conditions", "rejection_reason", "updated_at",
    ])
    record(
        AuditAction.UPDATE,
        entity_type="insurance.PreAuthorisation",
        entity_id=request.uuid,
        entity_label=f"{request.reference} {request.status}",
        reason=reason or conditions,
        metadata={"approved": str(request.approved_amount)},
    )
    return request


def preauth_warnings(request: PreAuthorisation, spent_so_far=None) -> list:
    """What is about to go wrong with this approval.

    Sentences, produced before the treatment rather than after the claim is
    deducted. The two failures this catches — spending past the approved
    amount and operating after the approval expired — are both entirely
    predictable and both routinely missed.
    """
    warnings = []
    if not request.is_usable:
        if request.valid_until and request.valid_until < timezone.localdate():
            warnings.append(
                f"The approval expired on {request.valid_until}. Treating "
                "against it now will be rejected as unauthorised."
            )
        else:
            warnings.append(
                f"The request is {request.get_status_display().lower()} and "
                "cannot be treated against."
            )
        return warnings

    days = request.days_until_expiry
    if days is not None and days <= 7:
        warnings.append(
            f"The approval expires in {days} day{'s' if days != 1 else ''} "
            f"({request.valid_until})."
        )
    if spent_so_far is not None:
        spent = money(spent_so_far)
        if spent > request.approved_amount:
            warnings.append(
                f"Charges of {spent} already exceed the approved "
                f"{request.approved_amount} by "
                f"{spent - request.approved_amount}. That difference will be "
                "deducted unless a further approval is obtained."
            )
        elif spent > request.approved_amount * Decimal("0.8"):
            warnings.append(
                f"Charges of {spent} are approaching the approved "
                f"{request.approved_amount}."
            )
    return warnings


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


#: Which sub-limit category a service code belongs to.
#:
#: Crude on purpose: a full mapping belongs in the service catalogue, and
#: guessing from the code prefix is honest about being a guess. What matters
#: is that every claim line carries *some* category, because a claim that
#: cannot be grouped cannot be checked against the policy's caps at all.
CATEGORY_PREFIXES = {
    "BED": "room",
    "ICU": "icu",
    "LAB": "investigation",
    "RAD": "investigation",
    "OT": "procedure",
    "PROC": "procedure",
    "DRUG": "drug",
    "CONS": "consultation",
}


def _category_for(code: str, description: str) -> str:
    for prefix, category in CATEGORY_PREFIXES.items():
        if code.upper().startswith(prefix):
            return category
    lowered = description.lower()
    if "bed" in lowered or "room" in lowered:
        return "room"
    if "consultation" in lowered:
        return "consultation"
    return "other"


@tenant_atomic_method
def create_claim(
    organization,
    invoice: Invoice,
    policy: Policy,
    actor,
    preauthorisation: PreAuthorisation = None,
    diagnosis: str = "",
    diagnosis_code: str = "",
    service_date=None,
) -> Claim:
    """Build a claim from an issued invoice.

    The lines are copied rather than referenced. The invoice is a statutory
    document that cannot change; the claim is a negotiation, and the payer's
    decision has to live somewhere that is allowed to change. Pointing at the
    invoice line would mean either mutating a statutory document or having
    nowhere to record the deduction.
    """
    require_module(organization, ModuleCode.INSURANCE)

    if invoice.status == InvoiceStatus.DRAFT:
        raise InsuranceError(
            "An invoice must be issued before it can be claimed for."
        )
    # A retail counter sale has no patient record. There is nobody for an
    # insurer to check a policy against, so there is nothing to claim — and
    # accepting it would let a walk-in purchase be billed to whichever policy
    # happened to be selected.
    if invoice.patient_id is None:
        raise InsuranceError(
            f"{invoice.number} is a counter sale with no patient record. "
            "An insurer has nobody to check a policy against.",
            detail={"invoice": invoice.number},
        )
    # Claiming one patient's treatment against another's policy is fraud,
    # whether or not anybody meant it. The commonest innocent version is a
    # dependant's card used for the principal.
    if invoice.patient_id != policy.patient_id:
        raise InsuranceError(
            f"{invoice.number} is for {invoice.patient.full_name}, but policy "
            f"{policy.policy_number} belongs to {policy.patient.full_name}. "
            "A dependant needs their own policy record naming the principal.",
            detail={"invoice_patient": invoice.patient.mrn,
                    "policy_patient": policy.patient.mrn},
        )
    if Claim.objects.filter(invoice=invoice, payer=policy.payer).exists():
        raise InsuranceError(
            f"{invoice.number} has already been claimed to "
            f"{policy.payer.name}. Resubmit the existing claim rather than "
            "raising a second one — payers reject duplicates.",
            detail={"invoice": invoice.number},
        )

    service_date = service_date or (
        invoice.issued_at.date() if invoice.issued_at else timezone.localdate()
    )
    if not policy.was_active_on(service_date):
        raise NotCovered(
            f"Policy {policy.policy_number} did not cover {service_date}.",
            detail={"service_date": str(service_date)},
        )

    claim = Claim.objects.create(
        reference=_next_reference(Claim, "CLM"),
        payer=policy.payer,
        policy=policy,
        patient=invoice.patient,
        facility=invoice.facility,
        invoice=invoice,
        encounter=invoice.encounter,
        preauthorisation=preauthorisation,
        service_date=service_date,
        diagnosis=diagnosis,
        diagnosis_code=diagnosis_code,
        created_by_id=getattr(actor, "uuid", None),
    )

    totals = {}
    lines = []
    for line in invoice.lines.all():
        # The invoice's own category when billing set one; the code prefix
        # otherwise. Either way every claim line gets a category, because a
        # claim that cannot be grouped cannot be checked against the policy's
        # sub-limits at all -- and an uncategorised line is silently exempt
        # from every cap, which is the direction that loses money.
        category = line.category or _category_for(
            line.service_code or "", line.description,
        )
        amount = money(line.total)
        totals[category] = totals.get(category, ZERO) + amount
        lines.append(ClaimLine(
            claim=claim,
            description=line.description,
            service_code=line.service_code or "",
            category=category,
            quantity=line.quantity or 1,
            unit_price=line.unit_price or ZERO,
            claimed_amount=amount,
        ))
    ClaimLine.objects.bulk_create(lines)

    claimed = sum((line.claimed_amount for line in lines), ZERO)
    prediction = estimate(policy, claimed, totals, on_date=service_date)

    claim.claimed_amount = claimed
    # Stored rather than recomputed later: the policy's terms may change, and
    # the patient was quoted a number on the day.
    claim.patient_liability = prediction["patient_pays"]
    claim.save(update_fields=[
        "claimed_amount", "patient_liability", "updated_at",
    ])

    ClaimEvent.objects.create(
        claim=claim, event="created",
        detail=f"Built from {invoice.number}.",
        amount=claimed,
        actor_name=getattr(actor, "full_name", "") or "",
    )
    return claim


def submission_deadline(claim: Claim) -> dict:
    """How long is left to submit, against this payer's own window.

    Per payer, because the windows differ wildly and a generic thirty days
    would be wrong in both directions. Missing this is the commonest way a
    valid claim becomes worthless.
    """
    window = claim.payer.submission_window_days
    deadline = claim.service_date + timedelta(days=window)
    days_left = (deadline - timezone.localdate()).days
    return {
        "window_days": window,
        "deadline": deadline,
        "days_left": days_left,
        "expired": days_left < 0,
        "urgent": 0 <= days_left <= 7,
    }


@tenant_atomic_method
def submit_claim(claim: Claim, actor, payer_reference: str = "") -> Claim:
    """Send it, refusing the two things that make a claim worthless.

    Past the deadline and without a pre-authorisation the payer requires. Both
    are refusals rather than warnings, because a claim submitted in either
    state is not a claim — it is a rejection with extra steps, and the hospital
    will believe it is owed money it is not.
    """
    if claim.status not in (
        ClaimStatus.DRAFT, ClaimStatus.QUERIED, ClaimStatus.REJECTED,
        ClaimStatus.APPEALED,
    ):
        raise InsuranceError(
            f"{claim.reference} is {claim.get_status_display().lower()} and "
            "cannot be submitted."
        )
    if claim.claimed_amount <= 0:
        raise InsuranceError("There is nothing to claim for.")

    deadline = submission_deadline(claim)
    if deadline["expired"]:
        raise InsuranceError(
            f"{claim.payer.name} allows {deadline['window_days']} days from "
            f"the date of service. That window closed on "
            f"{deadline['deadline']}, {abs(deadline['days_left'])} days ago.",
            detail=deadline,
        )

    payer = claim.payer
    needs_preauth = (
        payer.requires_preauthorisation
        and claim.claimed_amount > payer.preauthorisation_threshold
    )
    if needs_preauth and claim.preauthorisation is None:
        raise InsuranceError(
            f"{payer.name} requires pre-authorisation above "
            f"{payer.preauthorisation_threshold} and this claim is for "
            f"{claim.claimed_amount}. Submitting without one will be rejected.",
            detail={"threshold": str(payer.preauthorisation_threshold)},
        )

    claim.status = ClaimStatus.SUBMITTED
    claim.submitted_at = timezone.now()
    claim.submitted_by_name = getattr(actor, "full_name", "") or ""
    claim.payer_reference = payer_reference or claim.payer_reference
    claim.submission_count += 1
    claim.save(update_fields=[
        "status", "submitted_at", "submitted_by_name", "payer_reference",
        "submission_count", "updated_at",
    ])

    if claim.preauthorisation and claim.preauthorisation.status in (
        PreAuthStatus.APPROVED, PreAuthStatus.PARTIALLY_APPROVED,
    ):
        claim.preauthorisation.status = PreAuthStatus.USED
        claim.preauthorisation.save(update_fields=["status", "updated_at"])

    ClaimEvent.objects.create(
        claim=claim,
        event="submitted" if claim.submission_count == 1 else "resubmitted",
        detail=f"Submission {claim.submission_count}. "
               f"{deadline['days_left']} days inside the window.",
        amount=claim.claimed_amount,
        actor_name=getattr(actor, "full_name", "") or "",
    )
    record(
        AuditAction.UPDATE,
        entity_type="insurance.Claim",
        entity_id=claim.uuid,
        entity_label=f"{claim.reference} submitted to {payer.name}",
        metadata={"amount": str(claim.claimed_amount),
                  "submission": claim.submission_count},
    )
    return claim


@tenant_atomic_method
def raise_query(claim: Claim, question: str, actor) -> Claim:
    """The payer has asked something and is waiting.

    Its own state, because a queried claim is neither being processed nor
    rejected — the hospital owes an answer, and a claim that looks "submitted"
    sits for four months waiting for a document nobody knew was wanted.
    """
    if not question.strip():
        raise InsuranceError("A query must record what was asked.")
    claim.status = ClaimStatus.QUERIED
    claim.query_text = question
    claim.query_raised_at = timezone.now()
    claim.query_answered_at = None
    claim.save(update_fields=[
        "status", "query_text", "query_raised_at", "query_answered_at",
        "updated_at",
    ])
    ClaimEvent.objects.create(
        claim=claim, event="queried", detail=question,
        actor_name=getattr(actor, "full_name", "") or "",
    )
    return claim


@tenant_atomic_method
def record_response(
    claim: Claim,
    actor,
    approved_amount=None,
    deductions: list = None,
    rejection_reason: str = "",
    payer_reference: str = "",
    responded_at=None,
) -> Claim:
    """Write down the payer's decision, line by line.

    `deductions` are dicts of `line` (a `ClaimLine` or its UUID), `amount` and
    `reason` — the reason from the fixed list, because the only useful thing
    about a deduction is the aggregate.

    The approved total is taken from the lines when deductions are given, so
    the header and the lines cannot disagree. A payer that quotes only a total
    is accepted too, and the difference then shows as a shortfall with no line
    against it — which is itself worth seeing, since it is a payer refusing to
    say what it disallowed.
    """
    if claim.status in (ClaimStatus.SETTLED, ClaimStatus.WRITTEN_OFF):
        raise InsuranceError(
            f"{claim.reference} is {claim.get_status_display().lower()}."
        )

    responded_at = responded_at or timezone.now()
    deductions = deductions or []

    total_deducted = ZERO
    for entry in deductions:
        line = entry["line"]
        if not isinstance(line, ClaimLine):
            line = ClaimLine.objects.get(uuid=line, claim=claim)
        amount = money(entry["amount"])
        reason = entry.get("reason", "")
        validate_deduction_reason(reason)
        if amount > 0 and not reason:
            raise InsuranceError(
                f"The deduction of {amount} on '{line.description}' has no "
                "reason. A deduction nobody can aggregate cannot be argued "
                f"with — use one of: {', '.join(sorted(DEDUCTION_REASON_KEYS))}."
            )
        if amount > line.claimed_amount:
            raise InsuranceError(
                f"{amount} cannot be deducted from '{line.description}', "
                f"which was claimed at {line.claimed_amount}."
            )
        line.deducted_amount = amount
        line.approved_amount = line.claimed_amount - amount
        line.deduction_reason = reason
        line.deduction_notes = entry.get("notes", "")
        line.save(update_fields=[
            "deducted_amount", "approved_amount", "deduction_reason",
            "deduction_notes", "updated_at",
        ])
        total_deducted += amount

    # Lines nobody deducted from are approved in full.
    for line in claim.lines.filter(deducted_amount=0, approved_amount=0):
        line.approved_amount = line.claimed_amount
        line.save(update_fields=["approved_amount", "updated_at"])

    from_lines = claim.lines.aggregate(t=models.Sum("approved_amount"))["t"] or ZERO
    approved = money(from_lines if approved_amount is None else approved_amount)

    claim.approved_amount = approved
    claim.deducted_amount = total_deducted
    claim.responded_at = responded_at
    claim.payer_reference = payer_reference or claim.payer_reference

    if approved <= 0:
        if not rejection_reason.strip():
            raise InsuranceError("A rejection must record the payer's reason.")
        claim.status = ClaimStatus.REJECTED
        claim.rejection_reason = rejection_reason
    elif approved < claim.claimed_amount:
        claim.status = ClaimStatus.PARTIALLY_APPROVED
    else:
        claim.status = ClaimStatus.APPROVED

    if claim.query_raised_at and not claim.query_answered_at:
        claim.query_answered_at = responded_at

    claim.save(update_fields=[
        "approved_amount", "deducted_amount", "responded_at",
        "payer_reference", "status", "rejection_reason", "query_answered_at",
        "updated_at",
    ])

    ClaimEvent.objects.create(
        claim=claim,
        event=claim.status,
        detail=rejection_reason or (
            f"{len(deductions)} deduction"
            f"{'s' if len(deductions) != 1 else ''} totalling {total_deducted}."
        ),
        amount=approved,
        actor_name=getattr(actor, "full_name", "") or "",
    )
    record(
        AuditAction.UPDATE,
        entity_type="insurance.Claim",
        entity_id=claim.uuid,
        entity_label=f"{claim.reference} {claim.status}",
        reason=rejection_reason,
        metadata={
            "claimed": str(claim.claimed_amount),
            "approved": str(approved),
            "deducted": str(total_deducted),
        },
    )
    return claim


@tenant_atomic_method
def settle_claim(claim: Claim, amount, actor, settled_at=None,
                 payment_reference: str = "") -> Claim:
    """Money arrived.

    Part settlements are normal — a payer pays a batch of claims with one
    transfer and short-pays some of them — so the amount accumulates and the
    claim only becomes `settled` when it is whole.
    """
    if claim.status not in (
        ClaimStatus.APPROVED, ClaimStatus.PARTIALLY_APPROVED,
        ClaimStatus.SETTLED,
    ):
        raise InsuranceError(
            f"{claim.reference} is {claim.get_status_display().lower()} — "
            "nothing has been approved to settle."
        )

    amount = money(amount)
    if amount <= 0:
        raise InsuranceError("A settlement must have an amount.")
    if claim.settled_amount + amount > claim.approved_amount:
        raise InsuranceError(
            f"That would settle {claim.settled_amount + amount} against an "
            f"approved {claim.approved_amount}. Record the excess as a "
            "separate credit rather than over-settling the claim.",
            detail={"approved": str(claim.approved_amount),
                    "already": str(claim.settled_amount)},
        )

    claim.settled_amount += amount
    claim.settled_at = settled_at or timezone.now()
    if claim.settled_amount >= claim.approved_amount:
        claim.status = ClaimStatus.SETTLED
    claim.save(update_fields=[
        "settled_amount", "settled_at", "status", "updated_at",
    ])

    ClaimEvent.objects.create(
        claim=claim, event="settled", amount=amount,
        detail=payment_reference,
        actor_name=getattr(actor, "full_name", "") or "",
    )

    # The policy's utilisation is a cache over the claims, rebuilt rather than
    # incremented, so a corrected claim cannot leave it drifting.
    if claim.policy:
        rebuild_utilisation(claim.policy)
    return claim


@tenant_atomic_method
def appeal_claim(claim: Claim, grounds: str, actor) -> Claim:
    """Argue with a rejection or a deduction.

    Its own state so that the appeal rate is countable. A hospital that never
    appeals is one whose deductions are never tested, and that number is
    invisible if an appeal just re-opens the claim as a draft.
    """
    if claim.status not in (
        ClaimStatus.REJECTED, ClaimStatus.PARTIALLY_APPROVED,
    ):
        raise InsuranceError(
            "Only a rejected or partly approved claim can be appealed."
        )
    if not grounds.strip():
        raise InsuranceError("An appeal must say on what grounds.")

    claim.status = ClaimStatus.APPEALED
    claim.save(update_fields=["status", "updated_at"])
    ClaimEvent.objects.create(
        claim=claim, event="appealed", detail=grounds,
        amount=claim.shortfall,
        actor_name=getattr(actor, "full_name", "") or "",
    )
    return claim


@tenant_atomic_method
def write_off_claim(claim: Claim, reason: str, actor) -> Claim:
    """Give up on it, explicitly.

    An explicit outcome because a claim quietly abandoned is revenue nobody
    records losing, and the total written off per payer per year is the number
    that decides whether to keep the contract.
    """
    if not reason.strip():
        raise InsuranceError("Writing off a claim must say why.")

    claim.status = ClaimStatus.WRITTEN_OFF
    claim.save(update_fields=["status", "updated_at"])
    ClaimEvent.objects.create(
        claim=claim, event="written_off", detail=reason,
        amount=claim.claimed_amount - claim.settled_amount,
        actor_name=getattr(actor, "full_name", "") or "",
    )
    record(
        AuditAction.UPDATE,
        entity_type="insurance.Claim",
        entity_id=claim.uuid,
        entity_label=f"{claim.reference} written off",
        reason=reason,
        metadata={"amount": str(claim.claimed_amount - claim.settled_amount)},
    )
    return claim


@tenant_atomic_method
def rebuild_utilisation(policy: Policy) -> Decimal:
    """Recompute what a policy has consumed, from the claims.

    A cache, never a counter. An incremented total and the claims disagree the
    first time a claim is corrected, and it is always the total that is wrong
    — the same rule as the stock ledger and every other derived figure here.
    """
    total = policy.claims.filter(
        status__in=(
            ClaimStatus.APPROVED, ClaimStatus.PARTIALLY_APPROVED,
            ClaimStatus.SETTLED,
        )
    ).aggregate(t=models.Sum("approved_amount"))["t"] or ZERO

    policy.utilised = money(total)
    policy.save(update_fields=["utilised", "updated_at"])
    return policy.utilised


# ---------------------------------------------------------------------------
# Government schemes
# ---------------------------------------------------------------------------


def package_rate(payer: Payer, code: str, on_date=None) -> SchemePackage:
    """The package rate in force on a date.

    Effective-dated because a government notice changes the rate and every
    claim already made against the old one must keep it. The same pattern as
    the payroll tax slabs.
    """
    on_date = on_date or timezone.localdate()
    package = (
        SchemePackage.objects.filter(
            payer=payer, code=code, effective_from__lte=on_date, is_active=True,
        )
        .filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=on_date))
        .order_by("-effective_from")
        .first()
    )
    if package is None:
        raise InsuranceError(
            f"{payer.name} has no package '{code}' in force on {on_date}.",
            detail={"code": code},
        )
    return package


def package_margin(claim: Claim, package: SchemePackage) -> dict:
    """What the treatment cost against what the scheme pays.

    The number a scheme hospital lives or dies by, and one that no
    insurance-shaped model produces: the package pays a fixed amount whatever
    happened, so the difference between cost and rate is the hospital's, in
    either direction.
    """
    cost = claim.claimed_amount
    rate = package.package_amount
    return {
        "package": package.code,
        "package_name": package.name,
        "billed": cost,
        "package_amount": rate,
        "margin": rate - cost,
        "margin_percent": (
            ((rate - cost) * 100 / cost).quantize(Decimal("0.1"))
            if cost > 0 else None
        ),
        "loss_making": rate < cost,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def claims_ageing(facility=None, payer: Payer = None) -> dict:
    """Submitted claims by how long they have been waiting.

    Aged against each payer's own promised settlement days rather than a
    generic thirty, so "overdue" means the payer has broken its own terms and
    not merely that a month has passed.
    """
    claims = Claim.objects.filter(
        status__in=(
            ClaimStatus.SUBMITTED, ClaimStatus.QUERIED, ClaimStatus.APPROVED,
            ClaimStatus.PARTIALLY_APPROVED, ClaimStatus.APPEALED,
        ),
        submitted_at__isnull=False,
    ).select_related("payer", "patient")
    if facility:
        claims = claims.filter(facility=facility)
    if payer:
        claims = claims.filter(payer=payer)

    buckets = {f"{low}-{high or 'plus'}": ZERO for low, high in AGEING_BUCKETS}
    rows = []
    total = ZERO
    overdue = ZERO

    for claim in claims:
        outstanding = (
            claim.approved_amount - claim.settled_amount
            if claim.approved_amount > 0 else claim.claimed_amount
        )
        if outstanding <= 0:
            continue
        days = claim.days_since_submission or 0
        for low, high in AGEING_BUCKETS:
            if days >= low and (high is None or days <= high):
                buckets[f"{low}-{high or 'plus'}"] += outstanding
                break
        total += outstanding
        past_promise = days > claim.payer.settlement_days
        if past_promise:
            overdue += outstanding
        rows.append({
            "claim": claim.reference,
            "payer": claim.payer.name,
            "patient": claim.patient.full_name,
            "status": claim.status,
            "submitted": claim.submitted_at.date(),
            "days": days,
            "promised_days": claim.payer.settlement_days,
            "past_promise": past_promise,
            "claimed": claim.claimed_amount,
            "approved": claim.approved_amount,
            "outstanding": outstanding,
        })

    rows.sort(key=lambda row: -row["days"])
    return {
        "buckets": buckets,
        "total": total,
        "overdue": overdue,
        "claims": rows,
    }


def deduction_analysis(facility=None, since=None) -> dict:
    """Why claims are being cut, ranked.

    The point of the whole module. A hospital that learns 40% of its
    deductions are "consumables not covered" can change what it bills; one
    with a thousand free-text reasons can change nothing.
    """
    since = since or (timezone.localdate() - timedelta(days=365))
    lines = ClaimLine.objects.filter(
        claim__service_date__gte=since, deducted_amount__gt=0,
    ).select_related("claim")
    if facility:
        lines = lines.filter(claim__facility=facility)

    by_reason = {}
    by_category = {}
    total = ZERO
    for line in lines:
        amount = line.deducted_amount
        total += amount
        bucket = by_reason.setdefault(
            line.deduction_reason, {"amount": ZERO, "lines": 0},
        )
        bucket["amount"] += amount
        bucket["lines"] += 1
        category = by_category.setdefault(
            line.category or "other", {"amount": ZERO, "lines": 0},
        )
        category["amount"] += amount
        category["lines"] += 1

    ranked = sorted(
        (
            {
                "reason": reason,
                "amount": bucket["amount"],
                "lines": bucket["lines"],
                "share_percent": (
                    (bucket["amount"] * 100 / total).quantize(Decimal("0.1"))
                    if total > 0 else None
                ),
            }
            for reason, bucket in by_reason.items()
        ),
        key=lambda row: -row["amount"],
    )

    return {
        "since": since,
        "total_deducted": total,
        "by_reason": ranked,
        "by_category": {
            key: value["amount"] for key, value in by_category.items()
        },
    }


def payer_performance(since=None) -> list:
    """Which payers are worth dealing with.

    Approval rate, deduction rate, days to settle and the write-off total, per
    payer. A contract is renegotiated on these four numbers, and a hospital
    that cannot produce them renegotiates on impressions.
    """
    since = since or (timezone.localdate() - timedelta(days=365))
    rows = []

    for payer in Payer.objects.filter(is_active=True):
        claims = payer.claims.filter(service_date__gte=since)
        submitted = claims.exclude(status=ClaimStatus.DRAFT)
        count = submitted.count()
        if count == 0:
            continue

        claimed = submitted.aggregate(t=models.Sum("claimed_amount"))["t"] or ZERO
        approved = submitted.aggregate(t=models.Sum("approved_amount"))["t"] or ZERO
        settled = submitted.aggregate(t=models.Sum("settled_amount"))["t"] or ZERO
        # Counted from the events, not from the current status. A claim that
        # was rejected and then written off is still a rejection, and reading
        # the status alone makes a payer's rejection rate fall every time the
        # hospital gives up on a claim -- which is exactly backwards.
        rejected = ClaimEvent.objects.filter(
            claim__in=submitted, event=ClaimStatus.REJECTED,
        ).values("claim_id").distinct().count()
        written_off = submitted.filter(status=ClaimStatus.WRITTEN_OFF)

        turnarounds = [
            (claim.responded_at.date() - claim.submitted_at.date()).days
            for claim in submitted
            if claim.responded_at and claim.submitted_at
        ]
        resubmitted = submitted.filter(submission_count__gt=1).count()

        rows.append({
            "payer": payer.name,
            "kind": payer.kind,
            "claims": count,
            "claimed": claimed,
            "approved": approved,
            "settled": settled,
            "outstanding": approved - settled,
            "approval_percent": (
                (approved * 100 / claimed).quantize(Decimal("0.1"))
                if claimed > 0 else None
            ),
            "rejected": rejected,
            "rejection_percent": round(rejected * 100 / count, 1),
            "resubmitted": resubmitted,
            "written_off": written_off.aggregate(
                t=models.Sum("claimed_amount")
            )["t"] or ZERO,
            "median_days_to_respond": _median(turnarounds),
            "promised_days": payer.settlement_days,
        })

    return sorted(rows, key=lambda row: -row["claimed"])


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def expiring_preauthorisations(facility=None, within_days: int = 7) -> list:
    """Approvals about to become worthless.

    An approval that expires with the patient still waiting for a theatre slot
    is a claim that will be rejected as unauthorised, and it is entirely
    predictable a week in advance.
    """
    limit = timezone.localdate() + timedelta(days=within_days)
    rows = PreAuthorisation.objects.filter(
        status__in=(PreAuthStatus.APPROVED, PreAuthStatus.PARTIALLY_APPROVED),
        valid_until__isnull=False,
        valid_until__lte=limit,
    ).select_related("patient", "policy__payer")
    if facility:
        rows = rows.filter(facility=facility)

    return [
        {
            "reference": row.reference,
            "patient": row.patient.full_name,
            "mrn": row.patient.mrn,
            "payer": row.policy.payer.name,
            "treatment": row.planned_treatment,
            "approved": row.approved_amount,
            "valid_until": row.valid_until,
            "days_left": row.days_until_expiry,
            "expired": (row.days_until_expiry or 0) < 0,
        }
        for row in rows.order_by("valid_until")
    ]
