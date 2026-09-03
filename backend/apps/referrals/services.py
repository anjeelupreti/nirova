"""Making a referral, moving it through its states, and closing the loop.

The rules this layer keeps.

**A referral cannot be sent without a question.** "Chronic cough" is a reason,
not a question, and a specialist who is not asked something specific replies
with something unspecific. This is the single change that most improves what
comes back.

**The letter is assembled and frozen at the moment of sending.** Allergies,
medications, results and problems are pulled together then, because a letter
is a statement of what was known at the time. Regenerating it later from live
data produces a different letter carrying the same date.

**A second open referral for the same patient and specialty is refused.** The
commonest duplicate in any hospital: three clinicians refer the same patient to
cardiology in a fortnight and the department sees them three times or none.

**Every state change appends an event.** A referral is a conversation between
two organisations over weeks, and the status alone tells whoever picks it up
nothing about how it got there.

**Lapsing is a job, not a judgement.** A referral nobody has touched past its
target is moved to `lapsed` by a sweep that is safe to run repeatedly, so that
"referrals that quietly stopped mattering" is a number rather than an
impression.
"""

import logging
from datetime import timedelta

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: a referral is the point at which responsibility for a patient moves
# between people. Who sent it, who declined it and who answered it are the
# three questions a complaint opens with.
from apps.audit.services import record
from apps.common.exceptions import DomainError
from apps.referrals.models import (
    DECLINE_REASON_KEYS,
    OPEN_STATUSES,
    ExternalProvider,
    Referral,
    ReferralDirection,
    ReferralEvent,
    ReferralResponse,
    ReferralStatus,
    ReferralUrgency,
    target_for,
    validate_decline_reason,
)
# tenant_atomic_method: a referral and its first event are written together or
# not at all, and the transaction must open on the tenant connection — the
# router refuses to guess, so a bare `transaction.atomic` would protect
# nothing.
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.referrals")

#: How long after its target an untouched referral is treated as lapsed.
#:
#: Not zero: a referral one day past target is late, not abandoned. Thirty
#: days past is a referral nobody is chasing, and calling it that is the only
#: way the number ever gets looked at.
LAPSE_GRACE_DAYS = 30


class ReferralError(DomainError):
    """The referral will not go out like that."""


def _next_reference() -> str:
    return f"REF-{Referral.objects.count() + 1:06d}"


def _log(referral: Referral, event: str, actor=None, detail: str = ""):
    return ReferralEvent.objects.create(
        referral=referral,
        event=event,
        detail=detail,
        actor_name=getattr(actor, "full_name", "") or "",
    )


# ---------------------------------------------------------------------------
# Making one
# ---------------------------------------------------------------------------


def open_referrals_for(patient, specialty: str):
    """Existing live referrals for this patient and specialty."""
    return Referral.objects.filter(
        patient=patient,
        specialty__iexact=specialty,
        status__in=OPEN_STATUSES,
    )


@tenant_atomic_method
def create_referral(
    patient,
    specialty: str,
    reason: str,
    actor,
    direction: str = ReferralDirection.INTERNAL,
    urgency: str = ReferralUrgency.ROUTINE,
    question: str = "",
    clinical_summary: str = "",
    provisional_diagnosis: str = "",
    diagnosis_code: str = "",
    encounter=None,
    from_facility=None,
    from_department=None,
    to_facility=None,
    to_department=None,
    to_provider: ExternalProvider = None,
    to_clinician_name: str = "",
    referrer_name: str = "",
    referrer_registration: str = "",
    referrer_contact: str = "",
) -> Referral:
    """Draft a referral.

    A duplicate open referral is refused rather than warned about. Three
    clinicians referring the same patient to cardiology in a fortnight is the
    commonest duplicate in any hospital, and it ends with the department
    seeing them three times or — because each assumes another is the real one
    — not at all.
    """
    if not reason.strip():
        raise ReferralError("A referral must say why.")
    if not specialty.strip():
        raise ReferralError("A referral must name a specialty or service.")

    existing = open_referrals_for(patient, specialty).first()
    if existing is not None:
        raise ReferralError(
            f"{patient.full_name} already has an open referral to "
            f"{specialty}: {existing.reference}, "
            f"{existing.get_status_display().lower()} since "
            f"{existing.created_on}. Add to that one rather than raising a "
            "second.",
            detail={"referral": existing.reference, "status": existing.status},
        )

    if direction == ReferralDirection.OUTBOUND and to_provider is None:
        raise ReferralError(
            "An outbound referral needs a destination provider. A referral "
            "addressed to nobody cannot be sent or chased."
        )
    if direction == ReferralDirection.INTERNAL and to_department is None:
        raise ReferralError(
            "An internal referral needs a destination department."
        )

    referral = Referral.objects.create(
        reference=_next_reference(),
        patient=patient,
        encounter=encounter,
        direction=direction,
        from_facility=from_facility,
        from_department=from_department,
        referrer_id=getattr(actor, "uuid", None),
        referrer_name=referrer_name or (getattr(actor, "full_name", "") or ""),
        referrer_registration=referrer_registration,
        referrer_contact=referrer_contact,
        to_facility=to_facility,
        to_department=to_department,
        to_provider=to_provider,
        to_clinician_name=to_clinician_name,
        specialty=specialty,
        urgency=urgency,
        reason=reason,
        question=question,
        clinical_summary=clinical_summary,
        provisional_diagnosis=provisional_diagnosis,
        diagnosis_code=diagnosis_code,
        created_by_id=getattr(actor, "uuid", None),
    )
    _log(referral, "drafted", actor, reason[:200])
    return referral


def build_letter(referral: Referral) -> dict:
    """Assemble what the receiving clinician needs, from the record.

    Pulled together rather than typed, because a letter written from memory
    omits the allergy. Everything here is read at this moment and frozen onto
    the referral by `send_referral`, so the letter says what was known when it
    was written rather than what is true now.
    """
    patient = referral.patient

    allergies = []
    if hasattr(patient, "allergies"):
        allergies = [
            {
                "substance": row.substance,
                "reaction": getattr(row, "reaction", ""),
                "severity": getattr(row, "severity", ""),
            }
            for row in patient.allergies.all()[:20]
        ]

    conditions = []
    if hasattr(patient, "conditions"):
        conditions = [
            {
                "name": getattr(row, "name", "") or getattr(row, "condition", ""),
                "since": str(getattr(row, "diagnosed_on", "") or ""),
            }
            for row in patient.conditions.all()[:20]
        ]

    medications = []
    if referral.encounter is not None and hasattr(
        referral.encounter, "prescriptions"
    ):
        for prescription in referral.encounter.prescriptions.all()[:5]:
            for line in getattr(prescription, "lines", []).all()[:20]:
                medications.append({
                    "drug": line.generic_name,
                    "dose": line.dose,
                    "frequency": line.frequency,
                    "duration_days": line.duration_days,
                })

    return {
        "patient": {
            "name": patient.full_name,
            "mrn": patient.mrn,
            "date_of_birth": str(patient.date_of_birth or ""),
            "gender": patient.gender,
            "phone": getattr(patient, "phone", ""),
            "address": getattr(patient, "address", ""),
        },
        "referrer": {
            "name": referral.referrer_name,
            "registration": referral.referrer_registration,
            "facility": (
                referral.from_facility.name if referral.from_facility else ""
            ),
            "department": (
                referral.from_department.name if referral.from_department else ""
            ),
            "contact": referral.referrer_contact,
        },
        "to": {
            "provider": referral.to_provider.name if referral.to_provider else "",
            "facility": referral.to_facility.name if referral.to_facility else "",
            "department": (
                referral.to_department.name if referral.to_department else ""
            ),
            "clinician": referral.to_clinician_name,
            "specialty": referral.specialty,
        },
        "urgency": referral.urgency,
        "reason": referral.reason,
        "question": referral.question,
        "clinical_summary": referral.clinical_summary,
        "provisional_diagnosis": referral.provisional_diagnosis,
        "allergies": allergies,
        "conditions": conditions,
        "medications": medications,
        "assembled_at": timezone.now().isoformat(),
    }


@tenant_atomic_method
def send_referral(
    referral: Referral, actor, method: str = "", notes: str = "",
) -> Referral:
    """Send it, having refused the two things that make a referral useless.

    No question, and no way of actually reaching the destination. Both are
    refusals rather than warnings: a specialist who was not asked anything
    specific replies with nothing specific, and a referral "emailed" to a
    provider with no email address was never sent at all.
    """
    if referral.status != ReferralStatus.DRAFT:
        raise ReferralError(
            f"{referral.reference} is "
            f"{referral.get_status_display().lower()} and has already gone."
        )
    if not referral.question.strip():
        raise ReferralError(
            "A referral must ask a question. 'Chronic cough' is a reason, not "
            "a question — and a specialist who is not asked something "
            "specific answers with something unspecific.",
            detail={"reason": referral.reason},
        )

    provider = referral.to_provider
    if method == "email" and provider is not None and not provider.accepts_email:
        raise ReferralError(
            f"{provider.name} has no email address on file. Marking this sent "
            "by email would record a referral that never left the building.",
            detail={"provider": provider.name},
        )

    now = timezone.now()
    referral.status = ReferralStatus.SENT
    referral.sent_at = now
    referral.sent_by_method = method
    referral.sent_notes = notes
    referral.target_date = target_for(referral.urgency, now.date())
    # Frozen here, deliberately. A letter regenerated from live data six
    # months later is a different letter with the same date on it.
    referral.letter = build_letter(referral)
    referral.letter_generated_at = now
    referral.save(update_fields=[
        "status", "sent_at", "sent_by_method", "sent_notes", "target_date",
        "letter", "letter_generated_at", "updated_at",
    ])

    _log(referral, "sent", actor, f"By {method or 'unspecified means'}.")
    record(
        AuditAction.UPDATE,
        entity_type="referrals.Referral",
        entity_id=referral.uuid,
        entity_label=f"{referral.reference} sent to {referral.specialty}",
        reason=referral.reason[:200],
        metadata={"urgency": referral.urgency,
                  "target": str(referral.target_date)},
    )
    return referral


# ---------------------------------------------------------------------------
# The receiving end
# ---------------------------------------------------------------------------


@tenant_atomic_method
def acknowledge(referral: Referral, actor, notes: str = "") -> Referral:
    """Somebody at the receiving end has logged it.

    Deliberately not the same as accepting. A front desk recording receipt
    tells the referrer that the paper arrived and nothing about whether a
    consultant will see the patient — and merging the two is how a referral
    sits marked 'accepted' with nobody having read it.
    """
    if referral.status != ReferralStatus.SENT:
        raise ReferralError(
            f"{referral.reference} is "
            f"{referral.get_status_display().lower()}."
        )
    referral.status = ReferralStatus.ACKNOWLEDGED
    referral.acknowledged_at = timezone.now()
    referral.acknowledged_by_name = getattr(actor, "full_name", "") or ""
    referral.save(update_fields=[
        "status", "acknowledged_at", "acknowledged_by_name", "updated_at",
    ])
    _log(referral, "acknowledged", actor, notes)
    return referral


@tenant_atomic_method
def accept(referral: Referral, actor, notes: str = "") -> Referral:
    """The department agrees to see the patient."""
    if referral.status not in (
        ReferralStatus.SENT, ReferralStatus.ACKNOWLEDGED,
    ):
        raise ReferralError(
            f"{referral.reference} is "
            f"{referral.get_status_display().lower()}."
        )
    referral.status = ReferralStatus.ACCEPTED
    referral.accepted_at = timezone.now()
    referral.save(update_fields=["status", "accepted_at", "updated_at"])
    _log(referral, "accepted", actor, notes)
    return referral


@tenant_atomic_method
def decline(referral: Referral, reason: str, actor, notes: str = "") -> Referral:
    """Refuse the referral, with a reason from the countable list.

    A declined referral is more useful to the referring clinic than a silent
    one, but only if the reason can be counted: forty declines for
    "insufficient information" is a template problem, not forty individual
    mistakes.
    """
    if referral.status not in (
        ReferralStatus.SENT, ReferralStatus.ACKNOWLEDGED,
        ReferralStatus.ACCEPTED,
    ):
        raise ReferralError(
            f"{referral.reference} is "
            f"{referral.get_status_display().lower()} and cannot be declined."
        )
    if reason not in DECLINE_REASON_KEYS:
        raise ReferralError(
            f"'{reason}' is not a recognised reason for declining. The list "
            "is fixed so that declines can be counted and the referring "
            f"clinic told what to fix. Use one of: "
            f"{', '.join(sorted(DECLINE_REASON_KEYS))}."
        )

    referral.status = ReferralStatus.DECLINED
    referral.declined_at = timezone.now()
    referral.decline_reason = reason
    referral.decline_notes = notes
    referral.closed_at = referral.declined_at
    referral.save(update_fields=[
        "status", "declined_at", "decline_reason", "decline_notes",
        "closed_at", "updated_at",
    ])
    _log(referral, "declined", actor, f"{reason}: {notes}".strip(": "))
    record(
        AuditAction.UPDATE,
        entity_type="referrals.Referral",
        entity_id=referral.uuid,
        entity_label=f"{referral.reference} declined",
        reason=notes or reason,
        metadata={"reason": reason},
    )
    return referral


@tenant_atomic_method
def book(referral: Referral, when, actor, notes: str = "") -> Referral:
    """An appointment exists."""
    if referral.status not in (
        ReferralStatus.SENT, ReferralStatus.ACKNOWLEDGED,
        ReferralStatus.ACCEPTED, ReferralStatus.BOOKED,
        ReferralStatus.DID_NOT_ATTEND,
    ):
        raise ReferralError(
            f"{referral.reference} is "
            f"{referral.get_status_display().lower()}."
        )
    referral.status = ReferralStatus.BOOKED
    referral.booked_for = when
    referral.save(update_fields=["status", "booked_for", "updated_at"])
    _log(referral, "booked", actor, notes or f"For {when:%d %b %Y %H:%M}.")
    return referral


@tenant_atomic_method
def mark_seen(referral: Referral, actor, at=None, encounter=None) -> Referral:
    """The patient was seen.

    Not the end of the referral. The referrer still knows nothing, and
    `awaiting_answer` is true from this moment until somebody responds — which
    is the state this module exists to make visible.
    """
    if referral.status in (
        ReferralStatus.DECLINED, ReferralStatus.CANCELLED,
        ReferralStatus.COMPLETED,
    ):
        raise ReferralError(
            f"{referral.reference} is "
            f"{referral.get_status_display().lower()}."
        )

    at = at or timezone.now()
    if referral.sent_at is None:
        raise ReferralError(
            f"{referral.reference} has not been sent. A referral seen before "
            "anybody sent it is a date entered wrongly."
        )
    if at < referral.sent_at:
        # The waiting time is `seen_at - sent_at`, so one reversed pair puts a
        # negative number into the median wait and the breach rate — and a
        # negative wait is not obviously wrong to anybody reading a report.
        raise ReferralError(
            f"{referral.reference} was sent on "
            f"{referral.sent_at:%d %b %Y} and cannot have been seen on "
            f"{at:%d %b %Y}. Check the date.",
            detail={"sent_at": str(referral.sent_at),
                    "seen_at": str(at)},
        )

    referral.status = ReferralStatus.SEEN
    referral.seen_at = at
    if encounter is not None:
        referral.encounter = encounter
    referral.save(update_fields=[
        "status", "seen_at", "encounter", "updated_at",
    ])
    _log(
        referral, "seen", actor,
        f"{referral.days_waiting} days after sending."
        + (" Past target." if referral.is_breaching else ""),
    )
    return referral


@tenant_atomic_method
def mark_did_not_attend(referral: Referral, actor, notes: str = "") -> Referral:
    """The patient did not come.

    An outcome, not an absence. A referral left sitting because the patient
    never attended looks identical to one nobody has processed, and the two
    need opposite responses: one is a phone call to the patient, the other is
    a phone call to the department.
    """
    referral.status = ReferralStatus.DID_NOT_ATTEND
    referral.save(update_fields=["status", "updated_at"])
    _log(referral, "did_not_attend", actor, notes)
    return referral


# ---------------------------------------------------------------------------
# Closing the loop
# ---------------------------------------------------------------------------


@tenant_atomic_method
def respond(
    referral: Referral,
    answer: str,
    actor,
    findings: str = "",
    diagnosis: str = "",
    treatment: str = "",
    advice: str = "",
    care_handed_back: bool = True,
    follow_up_here: bool = False,
    follow_up_on=None,
    is_interim: bool = False,
    at=None,
) -> ReferralResponse:
    """Answer the referrer.

    Refused before the patient has been seen: a response to a referral nobody
    attended is about a different patient, a different visit, or nothing. The
    database constraint says the same thing, and this says it in a sentence.

    A response can be given more than once — an interim opinion, then a
    definitive one — so it is its own record rather than a field. Overwriting
    the first would lose the fact that the referrer was told something
    different in between and may have acted on it.
    """
    if referral.seen_at is None:
        raise ReferralError(
            f"{referral.reference} has not been seen. A response to a "
            "referral nobody attended is about a different patient, a "
            "different visit, or nothing at all."
        )
    if not answer.strip():
        raise ReferralError(
            "A response must answer the referrer's question"
            + (f" — they asked: {referral.question}" if referral.question else "")
            + "."
        )

    at = at or timezone.now()
    if at < referral.seen_at:
        # The time to answer is `responded_at - seen_at`. One reversed pair
        # makes that negative, and a negative turnaround is not obviously
        # wrong to anybody reading the report it lands in.
        raise ReferralError(
            f"{referral.reference} was seen on "
            f"{referral.seen_at:%d %b %Y} and cannot have been answered on "
            f"{at:%d %b %Y}. Check the date.",
            detail={"seen_at": str(referral.seen_at), "responded_at": str(at)},
        )

    response = ReferralResponse.objects.create(
        referral=referral,
        responded_at=at,
        responder_id=getattr(actor, "uuid", None),
        responder_name=getattr(actor, "full_name", "") or "",
        answer=answer,
        findings=findings,
        diagnosis=diagnosis,
        treatment=treatment,
        advice_to_referrer=advice,
        care_handed_back=care_handed_back,
        follow_up_here=follow_up_here,
        follow_up_on=follow_up_on,
        is_interim=is_interim,
        created_by_id=getattr(actor, "uuid", None),
    )

    referral.responded_at = at
    referral.status = (
        ReferralStatus.COMPLETED
        if care_handed_back and not is_interim
        else ReferralStatus.RESPONDED
    )
    if referral.status == ReferralStatus.COMPLETED:
        referral.closed_at = at
    referral.save(update_fields=[
        "responded_at", "status", "closed_at", "updated_at",
    ])

    _log(
        referral,
        "interim_response" if is_interim else "responded",
        actor,
        answer[:200],
    )
    record(
        AuditAction.CREATE,
        entity_type="referrals.ReferralResponse",
        entity_id=response.uuid,
        entity_label=f"Answer to {referral.reference}",
        reason=answer[:200],
        metadata={"handed_back": care_handed_back, "interim": is_interim},
    )
    return response


@tenant_atomic_method
def cancel(referral: Referral, reason: str, actor) -> Referral:
    """Withdraw a referral."""
    if not reason.strip():
        raise ReferralError("Cancelling a referral must say why.")
    if referral.status in (
        ReferralStatus.COMPLETED, ReferralStatus.DECLINED,
    ):
        raise ReferralError(
            f"{referral.reference} is already "
            f"{referral.get_status_display().lower()}."
        )

    referral.status = ReferralStatus.CANCELLED
    referral.cancelled_reason = reason
    referral.closed_at = timezone.now()
    referral.save(update_fields=[
        "status", "cancelled_reason", "closed_at", "updated_at",
    ])
    _log(referral, "cancelled", actor, reason)
    return referral


@tenant_atomic_method
def lapse_stale(facility=None, on_date=None) -> dict:
    """Move referrals nobody has touched past their target into `lapsed`.

    Not a judgement made at read time: the state is written, so that
    "referrals that quietly stopped mattering" is a number somebody can be
    shown rather than an impression. Idempotent — it selects on the date and
    the status, so a second run in the same day changes nothing.

    A referral one day past target is late, not abandoned; the grace period
    keeps the distinction honest.
    """
    on_date = on_date or timezone.localdate()
    cutoff = on_date - timedelta(days=LAPSE_GRACE_DAYS)

    stale = Referral.objects.filter(
        status__in=(
            ReferralStatus.SENT, ReferralStatus.ACKNOWLEDGED,
            ReferralStatus.ACCEPTED,
        ),
        target_date__lt=cutoff,
    )
    if facility:
        stale = stale.filter(from_facility=facility)

    references = list(stale.values_list("reference", flat=True))
    for referral in stale:
        _log(
            referral, "lapsed", None,
            f"No outcome {(on_date - referral.target_date).days} days past "
            "target.",
        )
    count = stale.update(status=ReferralStatus.LAPSED, updated_at=timezone.now())
    if count:
        logger.info("Lapsed %s referrals with no outcome", count)
    return {"lapsed": count, "references": references[:50], "on": on_date}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def worklist(facility=None, specialty: str = "", direction: str = "") -> list:
    """What the receiving end has to deal with, most urgent first.

    Ordered by breach then by target date, not by arrival, because a routine
    referral sent in Shrawan and an urgent one sent yesterday need opposite
    treatment and a date-ordered list gives them the same.
    """
    rows = Referral.objects.filter(status__in=OPEN_STATUSES).exclude(
        status=ReferralStatus.DRAFT
    ).select_related("patient", "to_provider", "from_department")
    if facility:
        rows = rows.filter(
            models.Q(to_facility=facility) | models.Q(from_facility=facility)
        )
    if specialty:
        rows = rows.filter(specialty__iexact=specialty)
    if direction:
        rows = rows.filter(direction=direction)

    out = []
    for referral in rows:
        out.append({
            "reference": referral.reference,
            "patient": referral.patient.full_name,
            "mrn": referral.patient.mrn,
            "specialty": referral.specialty,
            "urgency": referral.urgency,
            "status": referral.status,
            "direction": referral.direction,
            "referrer": referral.referrer_name,
            "sent_at": referral.sent_at,
            "days_waiting": referral.days_waiting,
            "target_date": referral.target_date,
            "days_to_target": referral.days_to_target,
            "breaching": referral.is_breaching,
            "awaiting_answer": referral.awaiting_answer,
            "question": referral.question,
        })

    return sorted(
        out,
        key=lambda row: (
            not row["breaching"],
            row["target_date"] or timezone.localdate() + timedelta(days=3650),
        ),
    )


def unanswered(facility=None, days: int = 14) -> list:
    """Patients who were seen and whose referrer has still been told nothing.

    The failure this module exists to surface. Every other status is somebody
    waiting for something to happen; this one is something having happened
    that nobody passed on.
    """
    cutoff = timezone.now() - timedelta(days=days)
    rows = Referral.objects.filter(
        seen_at__isnull=False, responded_at__isnull=True,
        seen_at__lte=cutoff,
    ).select_related("patient")
    if facility:
        rows = rows.filter(
            models.Q(to_facility=facility) | models.Q(from_facility=facility)
        )

    return [
        {
            "reference": referral.reference,
            "patient": referral.patient.full_name,
            "mrn": referral.patient.mrn,
            "specialty": referral.specialty,
            "referrer": referral.referrer_name,
            "seen_at": referral.seen_at,
            "days_since_seen": (timezone.now() - referral.seen_at).days,
            "question": referral.question,
        }
        for referral in rows.order_by("seen_at")
    ]


def summary(facility=None, since=None) -> dict:
    """How the referral process is actually working.

    Four numbers a clinical director asks for and most systems cannot produce:
    how many breached, how many were declined and why, how long the answer
    takes, and how many were never answered at all.
    """
    since = since or (timezone.localdate() - timedelta(days=180))
    rows = Referral.objects.filter(created_on__gte=since)
    if facility:
        rows = rows.filter(
            models.Q(to_facility=facility) | models.Q(from_facility=facility)
        )

    total = rows.count()
    sent = rows.exclude(status=ReferralStatus.DRAFT)
    seen = [row for row in sent if row.seen_at]
    breached = [row for row in sent if row.is_breaching]
    answered = [row for row in sent if row.responded_at]

    waits = [row.days_waiting for row in seen if row.days_waiting is not None]
    answer_days = [
        (row.responded_at.date() - row.seen_at.date()).days
        for row in answered if row.seen_at
    ]

    declines = {}
    for row in rows.filter(status=ReferralStatus.DECLINED):
        declines[row.decline_reason] = declines.get(row.decline_reason, 0) + 1

    by_specialty = {}
    for row in sent:
        bucket = by_specialty.setdefault(
            row.specialty, {"sent": 0, "seen": 0, "breached": 0, "answered": 0},
        )
        bucket["sent"] += 1
        bucket["seen"] += 1 if row.seen_at else 0
        bucket["breached"] += 1 if row.is_breaching else 0
        bucket["answered"] += 1 if row.responded_at else 0

    return {
        "since": since,
        "total": total,
        "sent": sent.count(),
        "seen": len(seen),
        "breached": len(breached),
        "breach_percent": (
            round(len(breached) * 100 / sent.count(), 1) if sent.count() else None
        ),
        "declined": rows.filter(status=ReferralStatus.DECLINED).count(),
        "decline_reasons": dict(
            sorted(declines.items(), key=lambda item: -item[1])
        ),
        "lapsed": rows.filter(status=ReferralStatus.LAPSED).count(),
        "did_not_attend": rows.filter(
            status=ReferralStatus.DID_NOT_ATTEND
        ).count(),
        "answered": len(answered),
        "answered_percent": (
            round(len(answered) * 100 / len(seen), 1) if seen else None
        ),
        "seen_but_unanswered": len(seen) - len(answered),
        "median_days_to_be_seen": _median(waits),
        "median_days_to_answer": _median(answer_days),
        "by_specialty": dict(
            sorted(by_specialty.items(), key=lambda item: -item[1]["sent"])
        ),
    }


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def patient_history(patient) -> list:
    """Every referral this patient has had, with what came back.

    Read by the next clinician who sees them, which is why the answer matters
    more than the fact of the referral.
    """
    return [
        {
            "reference": referral.reference,
            "specialty": referral.specialty,
            "created_on": referral.created_on,
            "status": referral.status,
            "urgency": referral.urgency,
            "reason": referral.reason,
            "question": referral.question,
            "seen_at": referral.seen_at,
            "answers": [
                {
                    "responded_at": response.responded_at,
                    "responder": response.responder_name,
                    "answer": response.answer,
                    "diagnosis": response.diagnosis,
                    "handed_back": response.care_handed_back,
                    "interim": response.is_interim,
                }
                for response in referral.responses.all()
            ],
        }
        for referral in patient.referrals.prefetch_related("responses")
    ]
