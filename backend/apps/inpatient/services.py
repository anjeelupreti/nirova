"""Admitting, moving, charging and discharging an inpatient.

Three rules hold this module together.

**A bed is occupied over an interval.** Every operation that changes who is
where closes one `BedAssignment` and opens another. Nothing ever mutates a
flag on the bed, because "who was in bed 4 on the night of the 14th?" is asked
after a fall, an infection outbreak or a billing dispute, and a flag cannot
answer it.

**Accrual is idempotent per admission, per day, per kind.** The nightly job
may run twice, be re-run after a failure, or be triggered by hand for a missed
day. The `DailyAccrual` unique constraint refuses the second attempt; nothing
here relies on the job running exactly once.

**Discharge is a process.** Pharmacy returns, an outstanding balance, a
summary to write. Each is a named clearance with a person attached, so a
discharge stuck for two hours has a reason somebody can act on rather than a
flag somebody can force.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: an admission is the most contested episode in a hospital — who
# authorised the bed, who moved the patient, who let them leave owing money.
from apps.audit.services import record
from apps.billing.models import Charge, ChargeStatus, Invoice, InvoiceStatus, ServiceItem
from apps.billing.services import capture_charge
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.encounters.models import Encounter, EncounterStatus, EncounterType
from apps.entitlements.services import require_module
from apps.inpatient.models import (
    ASSIGNABLE_STATUSES,
    CLOSED_STATUSES,
    IN_HOUSE_STATUSES,
    AccrualKind,
    Admission,
    AdmissionStatus,
    Bed,
    BedAssignment,
    BedStatus,
    ClearanceKind,
    DailyAccrual,
    DischargeClearance,
    Gender,
    NursingRound,
    Ward,
)
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.inpatient")

ZERO = Decimal("0.00")

#: Clearances every discharge needs. Housekeeping is not on the list: the bed
#: is released *by* the discharge, so waiting for it would deadlock.
REQUIRED_CLEARANCES = (
    ClearanceKind.CLINICAL,
    ClearanceKind.NURSING,
    ClearanceKind.PHARMACY,
    ClearanceKind.BILLING,
    ClearanceKind.RECORDS,
)


class InpatientError(DomainError):
    code = "inpatient_operation_failed"


class NoBedAvailable(InpatientError):
    code = "no_bed_available"
    status_code = 409


class DischargeBlocked(InpatientError):
    code = "discharge_blocked"
    status_code = 409


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


def _next_reference() -> str:
    stem = f"IPD{timezone.localdate():%y%m}"
    last = (
        Admission.all_objects.filter(reference__startswith=stem)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    serial = int(last[len(stem):]) + 1 if last else 1
    return f"{stem}{serial:04d}"


# ---------------------------------------------------------------------------
# Beds
# ---------------------------------------------------------------------------


def available_beds(ward: Ward = None, facility=None, gender: str = "") -> list:
    """Beds that can actually take a patient right now.

    Three conditions, and all three matter: the bed is active, its physical
    status is assignable — a bed being cleaned is unoccupied and unusable —
    and nobody is in it. A list that checked only occupancy would send a
    patient to a bed with the last patient's linen on it.
    """
    queryset = Bed.objects.filter(
        is_active=True, status__in=ASSIGNABLE_STATUSES
    ).select_related("ward")
    if ward is not None:
        queryset = queryset.filter(ward=ward)
    if facility is not None:
        queryset = queryset.filter(ward__facility=facility)

    occupied = set(
        BedAssignment.objects.filter(vacated_at__isnull=True).values_list(
            "bed_id", flat=True
        )
    )
    beds = [bed for bed in queryset if bed.pk not in occupied]

    if gender:
        gender = gender.lower()
        beds = [
            bed for bed in beds
            if bed.gender_restriction in (Gender.ANY, gender)
        ]
    return beds


def ward_occupancy(ward: Ward) -> dict:
    """How full a ward is, computed rather than stored.

    A stored occupancy figure drifts the moment anything is transferred out of
    hours, and the number is cheap: a ward has tens of beds, not millions.
    """
    beds = list(ward.beds.filter(is_active=True))
    occupied_ids = set(
        BedAssignment.objects.filter(
            vacated_at__isnull=True, bed__ward=ward
        ).values_list("bed_id", flat=True)
    )
    by_status = {}
    for bed in beds:
        by_status[bed.status] = by_status.get(bed.status, 0) + 1

    total = len(beds)
    occupied = len([bed for bed in beds if bed.pk in occupied_ids])
    unusable = len([
        bed for bed in beds
        if bed.status not in ASSIGNABLE_STATUSES and bed.pk not in occupied_ids
    ])

    return {
        "ward": ward.code,
        "ward_name": ward.name,
        "ward_type": ward.ward_type,
        "total_beds": total,
        "occupied": occupied,
        "available": total - occupied - unusable,
        "unusable": unusable,
        "by_status": by_status,
        # Against total beds, not against usable ones. A ward with half its
        # beds broken is not "100% occupied" -- it is a ward with a
        # maintenance problem, and the two need telling apart.
        "occupancy_percent": (
            round(occupied / total * 100, 1) if total else 0.0
        ),
        "nurse_to_patient_ratio": str(ward.nurse_to_patient_ratio),
        "nurses_needed": (
            round(occupied / float(ward.nurse_to_patient_ratio), 1)
            if ward.nurse_to_patient_ratio else None
        ),
    }


@tenant_atomic_method
def set_bed_status(bed: Bed, status: str, actor=None, reason: str = "") -> Bed:
    """Take a bed out of service, or put it back.

    Refuses to mark an occupied bed as available: the bed does not become free
    because somebody clicked, and letting it would put two patients in it.
    """
    if status == BedStatus.AVAILABLE and bed.is_occupied:
        raise InpatientError(
            f"{bed} is occupied. Discharge or transfer the patient first.",
            detail={"bed": str(bed)},
        )
    if status in {BedStatus.MAINTENANCE, BedStatus.BLOCKED} and not reason.strip():
        raise InpatientError("Taking a bed out of service must record why.")

    bed.status = status
    bed.status_reason = reason
    bed.status_changed_at = timezone.now()
    bed.save(
        update_fields=["status", "status_reason", "status_changed_at",
                       "updated_at"]
    )
    return bed


# ---------------------------------------------------------------------------
# Admitting
# ---------------------------------------------------------------------------


@tenant_atomic_method
def admit(
    organization,
    patient,
    facility,
    actor=None,
    bed: Bed = None,
    ward: Ward = None,
    department=None,
    source: str = "opd",
    consultant=None,
    consultant_name: str = "",
    admitting_diagnosis: str = "",
    expected_discharge=None,
    deposit_expected=ZERO,
    is_mlc: bool = False,
    **details,
) -> Admission:
    """Admit a patient, and put them in a bed.

    Creates the inpatient `Encounter` too, so the clinical record hangs off
    the same object an outpatient visit does — notes, prescriptions and orders
    all work unchanged.

    A bed may be named or a ward given, in which case the first assignable bed
    is taken. Admitting with neither leaves the admission `pending`, which is
    a real state: a patient waiting in emergency for a ward bed is admitted in
    every sense except the bed.
    """
    require_module(organization, ModuleCode.HOSPITAL)

    survivor = patient.resolve()
    if survivor.pk != patient.pk:
        raise InpatientError(
            f"{patient.mrn} was merged into {survivor.mrn}. Admit against the "
            "surviving record.",
            detail={"surviving_mrn": survivor.mrn},
        )

    open_stay = Admission.objects.filter(
        patient=patient, status__in=IN_HOUSE_STATUSES
    ).first()
    if open_stay is not None:
        raise InpatientError(
            f"{patient.full_name} is already admitted under "
            f"{open_stay.reference}.",
            detail={"admission": open_stay.reference},
        )

    # See `default_department`: the field existed and nobody filled it.
    from apps.encounters.services import default_department

    department = department or default_department(facility, 'inpatient')

    encounter = Encounter.objects.create(
        reference=f"ENC-{_next_reference()}",
        patient=patient,
        encounter_type=EncounterType.INPATIENT,
        status=EncounterStatus.IN_PROGRESS,
        facility=facility,
        department=department,
        # Falls back to the admitting clinician. The field was here already
        # but only populated when a consultant *object* was passed, and every
        # caller passes a name -- so live admissions carried no attributable
        # clinician at all, 4 of 4 when this was measured. Naming a consultant
        # is not the same fact as somebody being responsible for the admission
        # right now, and the second is the one access control needs.
        provider_uuid=(
            getattr(consultant, "uuid", None) or getattr(actor, "uuid", None)
        ),
        provider_name=consultant_name or getattr(consultant, "full_name", ""),
        chief_complaint=admitting_diagnosis,
        created_by_id=getattr(actor, "uuid", None),
    )

    admission = Admission.objects.create(
        reference=_next_reference(),
        patient=patient,
        encounter=encounter,
        facility=facility,
        department=department,
        source=source,
        consultant_id=getattr(consultant, "uuid", None),
        consultant_name=consultant_name or getattr(consultant, "full_name", ""),
        admitting_diagnosis=admitting_diagnosis,
        expected_discharge=expected_discharge,
        deposit_expected=Decimal(str(deposit_expected)),
        is_mlc=is_mlc,
        created_by_id=getattr(actor, "uuid", None),
        **details,
    )

    if bed is None and ward is not None:
        candidates = available_beds(ward=ward, gender=patient.gender or "")
        if not candidates:
            raise NoBedAvailable(
                f"{ward.name} has no assignable bed"
                + (f" for a {patient.gender} patient." if patient.gender
                   else "."),
                detail={"ward": ward.code},
            )
        bed = candidates[0]

    if bed is not None:
        assign_bed(admission, bed, actor=actor, reason="Admission")
        admission.status = AdmissionStatus.ADMITTED
    else:
        admission.status = AdmissionStatus.PENDING
    admission.save(update_fields=["status", "updated_at"])

    # The clearances a discharge will need, created empty at admission so the
    # list is visible from day one rather than assembled in a hurry on the
    # morning somebody wants to go home.
    for kind in REQUIRED_CLEARANCES:
        DischargeClearance.objects.get_or_create(
            admission=admission, kind=kind,
            defaults={"created_by_id": getattr(actor, "uuid", None)},
        )

    record(
        AuditAction.CREATE,
        entity_type="inpatient.Admission",
        entity_id=admission.uuid,
        entity_label=f"{admission.reference} — {patient.full_name}",
        metadata={
            "bed": str(bed) if bed else "",
            "source": source,
            "mlc": is_mlc,
        },
    )
    if is_mlc:
        logger.warning(
            "MEDICO-LEGAL ADMISSION %s for %s — police must be informed",
            admission.reference, patient.mrn,
        )
    return admission


@tenant_atomic_method
def assign_bed(
    admission: Admission,
    bed: Bed,
    actor=None,
    reason: str = "",
) -> BedAssignment:
    """Put a patient in a bed, closing whatever they were in before.

    The gender check runs here rather than only at admission, because a
    transfer is where it actually gets broken — a full hospital moves somebody
    at 2am into the only free bed.
    """
    if not bed.is_active:
        raise InpatientError(f"{bed} is not in service.")
    if bed.status not in ASSIGNABLE_STATUSES:
        raise InpatientError(
            f"{bed} is {bed.get_status_display().lower()}"
            + (f": {bed.status_reason}" if bed.status_reason else "."),
            detail={"status": bed.status},
        )

    occupant = bed.current_assignment
    if occupant is not None and occupant.admission_id != admission.pk:
        raise InpatientError(
            f"{bed} is occupied by {occupant.admission.patient.full_name}.",
            detail={"admission": occupant.admission.reference},
        )

    patient_gender = (admission.patient.gender or "").lower()
    if (
        bed.gender_restriction != Gender.ANY
        and patient_gender
        and bed.gender_restriction != patient_gender
    ):
        raise InpatientError(
            f"{bed} is reserved for {bed.get_gender_restriction_display().lower()} "
            "patients.",
            detail={"restriction": bed.gender_restriction},
        )

    previous = admission.bed_assignments.filter(vacated_at__isnull=True).first()
    if previous is not None:
        if previous.bed_id == bed.pk:
            return previous
        _vacate(previous, actor=actor)

    assignment = BedAssignment.objects.create(
        admission=admission,
        bed=bed,
        ward=bed.ward,
        # Captured now. The bed's price may be revised next month; what this
        # patient was charged for last Tuesday must not move.
        daily_rate=bed.daily_rate or ZERO,
        reason=reason,
        assigned_by_id=getattr(actor, "uuid", None),
        assigned_by_name=getattr(actor, "full_name", "") or "",
        created_by_id=getattr(actor, "uuid", None),
    )
    bed.status = BedStatus.OCCUPIED
    bed.status_changed_at = timezone.now()
    bed.save(update_fields=["status", "status_changed_at", "updated_at"])
    return assignment


def _vacate(assignment: BedAssignment, actor=None, cleaning: bool = True) -> BedAssignment:
    """Close an assignment and hand the bed to housekeeping.

    The bed goes to `cleaning`, not to `available`. A bed somebody has just
    left is not ready for the next patient, and marking it free is how the
    next admission arrives to unmade linen.
    """
    assignment.vacated_at = timezone.now()
    assignment.save(update_fields=["vacated_at", "updated_at"])

    bed = assignment.bed
    bed.status = BedStatus.CLEANING if cleaning else BedStatus.AVAILABLE
    bed.status_changed_at = timezone.now()
    bed.save(update_fields=["status", "status_changed_at", "updated_at"])
    return assignment


@tenant_atomic_method
def transfer_bed(
    admission: Admission,
    bed: Bed,
    actor,
    reason: str,
) -> BedAssignment:
    """Move a patient. An event, not a mutation."""
    if not admission.is_in_house:
        raise InpatientError(
            f"{admission.reference} is "
            f"{admission.get_status_display().lower()}.",
            detail={"status": admission.status},
        )
    if not reason.strip():
        raise InpatientError("A transfer must record why.")

    from_bed = admission.current_bed
    assignment = assign_bed(admission, bed, actor=actor, reason=reason)

    if admission.status == AdmissionStatus.PENDING:
        admission.status = AdmissionStatus.ADMITTED
        admission.save(update_fields=["status", "updated_at"])

    record(
        AuditAction.UPDATE,
        entity_type="inpatient.Admission",
        entity_id=admission.uuid,
        entity_label=f"{admission.reference} moved to {bed}",
        reason=reason,
        metadata={"from": str(from_bed) if from_bed else "", "to": str(bed)},
    )
    return assignment


# ---------------------------------------------------------------------------
# Daily accrual
# ---------------------------------------------------------------------------


@tenant_atomic_method
def accrue_day(
    organization,
    admission: Admission,
    on_date=None,
    actor=None,
) -> list:
    """Post one day's recurring charges for one admission.

    Idempotent by construction: the `DailyAccrual` unique constraint on
    (admission, date, kind) means the second attempt finds a row and returns
    it rather than charging again. The nightly job can be re-run for a missed
    day, run twice by mistake, or triggered by hand, and none of those double
    a patient's bill.

    Returns the accruals *created*, so a caller can tell a real run from a
    repeat.
    """
    on_date = on_date or timezone.localdate()
    created = []

    if admission.status not in IN_HOUSE_STATUSES:
        return created
    if on_date < admission.admitted_at.date():
        return created
    # The discharge day is not charged: the bed is free that night. A hospital
    # that charged both the arrival and departure day would bill an extra
    # night on every stay.
    if admission.discharged_at and on_date >= admission.discharged_at.date():
        return created

    assignment = _assignment_on(admission, on_date)
    if assignment is None:
        return created

    bed = assignment.bed
    rate = assignment.daily_rate or bed.daily_rate or ZERO
    service_code = bed.service_code or ""

    if rate <= ZERO:
        # Reported, not silently skipped. A bed with no rate produces a free
        # stay, and free stays are noticed at the end of the month by which
        # point the patient has gone.
        logger.warning(
            "NO BED RATE for %s on %s (%s) — the day accrues nothing",
            admission.reference, on_date, bed,
        )
        return created

    accrual, was_created = DailyAccrual.objects.get_or_create(
        admission=admission,
        accrual_date=on_date,
        kind=AccrualKind.BED,
        defaults={
            "bed_assignment": assignment,
            "service_code": service_code,
            "description": f"{bed.ward.name} — bed {bed.code}",
            "quantity": Decimal("1.00"),
            "unit_rate": rate,
            "amount": rate,
            "created_by_id": getattr(actor, "uuid", None),
        },
    )
    if not was_created:
        return created

    # Post it to the bill, if the bed names a billable service. Without one
    # the accrual still exists -- the day happened -- and shows as unbilled,
    # which is a problem somebody can see and fix.
    service = (
        ServiceItem.objects.filter(code=service_code, is_active=True).first()
        if service_code else None
    )
    if service is not None:
        charge = capture_charge(
            organization=organization,
            patient=admission.patient,
            facility=admission.facility,
            service=service,
            actor=actor,
            encounter=admission.encounter,
            quantity=Decimal("1.00"),
            notes=f"{admission.reference} {on_date} — {accrual.description}",
        )
        accrual.charge_uuid = charge.uuid
        accrual.amount = charge.total
        accrual.unit_rate = charge.unit_price
        accrual.save(update_fields=[
            "charge_uuid", "amount", "unit_rate", "updated_at",
        ])
    created.append(accrual)
    return created


def _assignment_on(admission: Admission, on_date):
    """Which bed the patient was in on a given date.

    The whole reason assignments are intervals. A patient moved from a general
    ward to the ICU on Tuesday is charged the general rate up to Tuesday and
    the ICU rate after, and only the interval knows which.
    """
    return (
        admission.bed_assignments.filter(
            occupied_at__date__lte=on_date
        )
        .filter(
            models.Q(vacated_at__isnull=True)
            | models.Q(vacated_at__date__gt=on_date)
        )
        .select_related("bed", "bed__ward")
        .order_by("-occupied_at")
        .first()
    )


@tenant_atomic_method
def accrue_all(organization, facility, on_date=None, actor=None) -> dict:
    """The nightly job: accrue every in-house admission.

    Safe to run repeatedly. Reports what it created and what it skipped,
    because a run that silently did nothing is indistinguishable from one that
    did not run at all.
    """
    on_date = on_date or timezone.localdate()
    admissions = Admission.objects.filter(
        facility=facility, status__in=IN_HOUSE_STATUSES
    ).select_related("patient", "encounter")

    created = 0
    skipped = 0
    unrated = []
    for admission in admissions:
        rows = accrue_day(organization, admission, on_date=on_date, actor=actor)
        if rows:
            created += len(rows)
        else:
            skipped += 1
            assignment = _assignment_on(admission, on_date)
            if assignment and (assignment.daily_rate or ZERO) <= ZERO:
                unrated.append(admission.reference)

    return {
        "date": on_date,
        "admissions": admissions.count(),
        "accrued": created,
        "already_done_or_skipped": skipped,
        "admissions_without_a_bed_rate": unrated,
    }


def backfill_accruals(organization, admission: Admission, actor=None) -> dict:
    """Accrue every day of a stay that has not been accrued yet.

    For a hospital that starts using the system mid-stay, or after a night the
    job did not run. Idempotent for the same reason `accrue_day` is.
    """
    start = admission.admitted_at.date()
    end = (
        admission.discharged_at.date() - timedelta(days=1)
        if admission.discharged_at
        else timezone.localdate()
    )
    created = 0
    day = start
    while day <= end:
        created += len(accrue_day(organization, admission, on_date=day,
                                  actor=actor))
        day += timedelta(days=1)
    return {"admission": admission.reference, "accrued": created}


def stay_charges(admission: Admission) -> dict:
    """What this stay has cost so far, by category.

    Accruals and ad-hoc charges are reported together, because a patient
    querying their bill does not distinguish the two and should not have to.
    """
    accruals = admission.accruals.all()
    by_kind = dict(
        accruals.values_list("kind")
        .annotate(total=models.Sum("amount"))
        .values_list("kind", "total")
    )
    accrued_total = accruals.aggregate(t=models.Sum("amount"))["t"] or ZERO

    # Cancelled charges are excluded. A charge that was raised and then
    # reversed -- the discharge-day bed charge, most often -- is not money
    # anybody owes, and counting it showed a bill 12,000 higher than the
    # accruals it came from.
    charges = Charge.objects.filter(encounter=admission.encounter).exclude(
        status=ChargeStatus.CANCELLED
    )
    by_category = list(
        charges.values("service__category")
        .annotate(total=models.Sum("total"), count=models.Count("id"))
        .order_by("-total")
    )
    charge_total = charges.aggregate(t=models.Sum("total"))["t"] or ZERO
    uninvoiced = charges.filter(status=ChargeStatus.PENDING).aggregate(
        t=models.Sum("total")
    )["t"] or ZERO

    invoiced = Invoice.objects.filter(
        encounter=admission.encounter
    ).exclude(status=InvoiceStatus.DRAFT)
    billed = invoiced.aggregate(t=models.Sum("total"))["t"] or ZERO
    paid = invoiced.aggregate(t=models.Sum("amount_paid"))["t"] or ZERO

    return {
        "admission": admission.reference,
        "nights": admission.length_of_stay_days,
        "accrued_total": accrued_total,
        "accruals_by_kind": by_kind,
        # Charges are the authority: an accrual that posted a charge is
        # counted once, in the charge. The accrual total is shown beside it so
        # a gap between the two is visible -- a gap means a day accrued and
        # never billed.
        "charge_total": charge_total,
        "charges_by_category": by_category,
        "uninvoiced": uninvoiced,
        "invoiced": billed,
        "paid": paid,
        "outstanding": billed - paid,
        "unbilled_accruals": accruals.filter(charge_uuid__isnull=True).count(),
    }


# ---------------------------------------------------------------------------
# Discharge
# ---------------------------------------------------------------------------


@tenant_atomic_method
def reverse_accruals_from(admission: Admission, from_date, actor=None) -> dict:
    """Undo bed-days charged on or after a date, and their charges.

    Needed because a backfill run *before* a discharge accrues today, and then
    the patient goes home today — the bed is free that night, so the day was
    charged and should not have been.

    The seed made this visible by printing both figures side by side: four
    accrued days against a three-night stay. One bed-day of overcharge on
    every discharge is exactly the kind of error that survives for years,
    because each individual bill looks plausible.

    The charge is cancelled rather than deleted: a charge that existed is part
    of the record, and billing already has a reversal for this.
    """
    from apps.billing.services import cancel_charge

    doomed = admission.accruals.filter(accrual_date__gte=from_date)
    reversed_amount = ZERO
    count = 0
    for accrual in doomed:
        if accrual.charge_uuid:
            charge = Charge.objects.filter(uuid=accrual.charge_uuid).first()
            if charge and charge.status == ChargeStatus.PENDING:
                cancel_charge(
                    charge,
                    reason=(
                        f"{admission.reference} discharged on {from_date}; the "
                        "bed was free that night."
                    ),
                    actor=actor,
                )
        reversed_amount += accrual.amount
        count += 1
    doomed.delete()

    if count:
        logger.info(
            "REVERSED %d accrued day(s) worth %s on %s after discharge",
            count, reversed_amount, admission.reference,
        )
    return {"reversed": count, "amount": reversed_amount}


@tenant_atomic_method
def initiate_discharge(admission: Admission, actor, notes: str = "") -> Admission:
    """Start the discharge process.

    A separate state from discharged, because the gap between the two is real
    and is where a hospital's bed-turnaround time is lost. A patient whose
    consultant said "home today" at nine and who leaves at four spent seven
    hours in this state, and that is worth being able to measure.
    """
    if admission.status != AdmissionStatus.ADMITTED:
        raise InpatientError(
            f"{admission.reference} is "
            f"{admission.get_status_display().lower()}.",
            detail={"status": admission.status},
        )
    admission.status = AdmissionStatus.DISCHARGE_INITIATED
    if notes:
        admission.notes = f"{admission.notes}\n{notes}".strip()
    admission.save(update_fields=["status", "notes", "updated_at"])

    record(
        AuditAction.UPDATE,
        entity_type="inpatient.Admission",
        entity_id=admission.uuid,
        entity_label=f"{admission.reference} discharge started",
        reason=notes,
    )
    return admission


@tenant_atomic_method
def clear(
    admission: Admission,
    kind: str,
    actor,
    cleared: bool = True,
    reason: str = "",
) -> DischargeClearance:
    """One department signs off, or says why it cannot."""
    clearance, _ = DischargeClearance.objects.get_or_create(
        admission=admission, kind=kind
    )
    if not cleared and not reason.strip():
        raise InpatientError("Blocking a discharge must say why.")

    clearance.is_cleared = cleared
    clearance.blocking_reason = "" if cleared else reason
    clearance.cleared_by_id = getattr(actor, "uuid", None)
    clearance.cleared_by_name = getattr(actor, "full_name", "") or ""
    clearance.cleared_at = timezone.now() if cleared else None
    clearance.save()
    return clearance


def discharge_blockers(admission: Admission) -> list:
    """Everything standing between this patient and the door.

    A list rather than a boolean, because the ward clerk chasing a discharge
    needs to know *which* department to ring.
    """
    blockers = []
    clearances = {
        row.kind: row for row in admission.clearances.all()
    }
    for kind in REQUIRED_CLEARANCES:
        clearance = clearances.get(kind)
        if clearance is None or not clearance.is_cleared:
            blockers.append({
                "code": kind,
                "message": (
                    clearance.blocking_reason
                    if clearance and clearance.blocking_reason
                    else f"{dict(ClearanceKind.choices)[kind]} not signed off."
                ),
            })

    charges = stay_charges(admission)
    if charges["outstanding"] > ZERO:
        blockers.append({
            "code": "outstanding_balance",
            "message": (
                f"{charges['outstanding']} is outstanding on the account."
            ),
        })
    if charges["uninvoiced"] > ZERO:
        blockers.append({
            "code": "uninvoiced_charges",
            "message": (
                f"{charges['uninvoiced']} of charges have not been invoiced."
            ),
        })
    return blockers


@tenant_atomic_method
def discharge(
    admission: Admission,
    actor,
    outcome: str = AdmissionStatus.DISCHARGED,
    summary: str = "",
    advice: str = "",
    follow_up_on=None,
    final_diagnosis: str = "",
    override_reason: str = "",
) -> Admission:
    """Send the patient home, and free the bed.

    Blocked by any outstanding clearance or balance. The block is overridable
    — a patient leaving against medical advice at midnight is not going to
    wait for the billing office — but the override is a named, reasoned,
    audited act rather than a silent bypass.

    A death or a LAMA skips the balance check: refusing to release a body over
    an unpaid bill is not a policy anybody should be able to configure.
    """
    if admission.status not in IN_HOUSE_STATUSES:
        raise InpatientError(
            f"{admission.reference} is already "
            f"{admission.get_status_display().lower()}.",
            detail={"status": admission.status},
        )
    if outcome not in CLOSED_STATUSES:
        raise InpatientError(f"'{outcome}' is not a way a stay ends.")

    compassionate = outcome in {AdmissionStatus.DIED, AdmissionStatus.LAMA}
    if not compassionate:
        blockers = discharge_blockers(admission)
        if blockers and not override_reason.strip():
            raise DischargeBlocked(
                blockers[0]["message"],
                detail={"blockers": blockers},
            )

    assignment = admission.bed_assignments.filter(vacated_at__isnull=True).first()
    if assignment is not None:
        _vacate(assignment, actor=actor)

    admission.status = outcome
    admission.discharged_at = timezone.now()

    # A day charged on or after the discharge date is a day the bed was free.
    # A backfill run earlier today will have accrued it, so it is reversed
    # here rather than left to make the bill one night longer than the stay.
    reverse_accruals_from(
        admission, admission.discharged_at.date(), actor=actor
    )

    admission.discharge_summary = summary or admission.discharge_summary
    admission.discharge_advice = advice
    admission.follow_up_on = follow_up_on
    if final_diagnosis:
        admission.final_diagnosis = final_diagnosis
    if override_reason:
        admission.outcome_notes = (
            f"{admission.outcome_notes}\nDischarge override: {override_reason}"
        ).strip()
    admission.save()

    if admission.encounter_id:
        encounter = admission.encounter
        encounter.status = EncounterStatus.COMPLETED
        encounter.ended_at = admission.discharged_at
        encounter.save(update_fields=["status", "ended_at", "updated_at"])

    record(
        AuditAction.UPDATE,
        entity_type="inpatient.Admission",
        entity_id=admission.uuid,
        entity_label=f"{admission.reference} {outcome}",
        reason=override_reason or summary,
        metadata={
            "nights": admission.length_of_stay_days,
            "overridden": bool(override_reason),
        },
    )
    if override_reason:
        logger.warning(
            "DISCHARGE OVERRIDE %s by %s: %s",
            admission.reference, getattr(actor, "email", "?"), override_reason,
        )
    return admission


# ---------------------------------------------------------------------------
# Nursing
# ---------------------------------------------------------------------------


@tenant_atomic_method
def record_round(
    admission: Admission,
    actor,
    shift: str = "",
    intake_ml: int = 0,
    output_ml: int = 0,
    pain_score=None,
    observations: str = "",
    interventions: str = "",
    escalate: bool = False,
    escalation_reason: str = "",
) -> NursingRound:
    """Log a bedside round."""
    if not admission.is_in_house:
        raise InpatientError(
            "Rounds are only recorded against a patient who is here."
        )
    if escalate and not escalation_reason.strip():
        raise InpatientError("An escalation must say what is wrong.")

    entry = NursingRound.objects.create(
        admission=admission,
        shift=shift,
        nurse_id=getattr(actor, "uuid", None),
        nurse_name=getattr(actor, "full_name", "") or "",
        intake_ml=intake_ml,
        output_ml=output_ml,
        pain_score=pain_score,
        observations=observations,
        interventions=interventions,
        escalated=escalate,
        escalation_reason=escalation_reason,
        created_by_id=getattr(actor, "uuid", None),
    )
    if escalate:
        logger.warning(
            "NURSING ESCALATION %s: %s", admission.reference, escalation_reason
        )
    return entry


def fluid_balance(admission: Admission, hours: int = 24) -> dict:
    """Intake against output over a window.

    Cumulative, because a single round's figures mean nothing and the trend is
    what gets a deteriorating patient noticed.
    """
    since = timezone.now() - timedelta(hours=hours)
    rounds = admission.rounds.filter(recorded_at__gte=since)
    totals = rounds.aggregate(
        intake=models.Sum("intake_ml"), output=models.Sum("output_ml")
    )
    intake = totals["intake"] or 0
    output = totals["output"] or 0
    return {
        "admission": admission.reference,
        "hours": hours,
        "rounds": rounds.count(),
        "intake_ml": intake,
        "output_ml": output,
        "balance_ml": intake - output,
        "escalations": rounds.filter(escalated=True).count(),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def census(facility, on_date=None) -> dict:
    """Who is in the hospital, and where.

    The single figure a hospital's morning meeting runs on. Computed, never
    stored: a stored census is wrong by breakfast.
    """
    on_date = on_date or timezone.localdate()
    admissions = Admission.objects.filter(
        facility=facility, status__in=IN_HOUSE_STATUSES
    ).select_related("patient")

    wards = Ward.objects.filter(facility=facility, is_active=True)
    by_ward = [ward_occupancy(ward) for ward in wards]

    total_beds = sum(row["total_beds"] for row in by_ward)
    occupied = sum(row["occupied"] for row in by_ward)

    admitted_today = Admission.objects.filter(
        facility=facility, admitted_at__date=on_date
    ).count()
    discharged_today = Admission.objects.filter(
        facility=facility, discharged_at__date=on_date
    ).count()

    return {
        "date": on_date,
        "in_house": admissions.count(),
        "awaiting_a_bed": Admission.objects.filter(
            facility=facility, status=AdmissionStatus.PENDING
        ).count(),
        "total_beds": total_beds,
        "occupied": occupied,
        "available": sum(row["available"] for row in by_ward),
        "unusable": sum(row["unusable"] for row in by_ward),
        "occupancy_percent": (
            round(occupied / total_beds * 100, 1) if total_beds else 0.0
        ),
        "admitted_today": admitted_today,
        "discharged_today": discharged_today,
        "overstaying": [
            {
                "reference": admission.reference,
                "patient": admission.patient.full_name,
                "expected": admission.expected_discharge,
                "nights": admission.length_of_stay_days,
            }
            for admission in admissions
            if admission.is_overstaying
        ],
        "discharge_in_progress": Admission.objects.filter(
            facility=facility, status=AdmissionStatus.DISCHARGE_INITIATED
        ).count(),
        "by_ward": by_ward,
    }


def outcomes(facility, since=None) -> dict:
    """How stays ended, over a period.

    Mortality, LAMA and absconder rates are three different conversations
    with a regulator, so they are counted separately rather than as
    "not discharged normally".
    """
    since = since or (timezone.localdate() - timedelta(days=90))
    closed = Admission.objects.filter(
        facility=facility,
        discharged_at__date__gte=since,
        status__in=CLOSED_STATUSES,
    )
    by_outcome = dict(
        closed.values_list("status")
        .annotate(n=models.Count("id"))
        .values_list("status", "n")
    )
    total = sum(by_outcome.values()) or 1
    nights = [admission.length_of_stay_days for admission in closed]

    return {
        "since": since,
        "total": sum(by_outcome.values()),
        "by_outcome": by_outcome,
        "mortality_percent": round(
            by_outcome.get(AdmissionStatus.DIED, 0) / total * 100, 1
        ),
        "lama_percent": round(
            by_outcome.get(AdmissionStatus.LAMA, 0) / total * 100, 1
        ),
        "average_nights": (
            round(sum(nights) / len(nights), 1) if nights else 0.0
        ),
    }
