"""Booking, staffing, running and costing an operation.

Four rules.

**A theatre slot is an interval, and the database refuses an overlap.** Two
operations in one room at one time is not a diary clash, it is a patient on a
trolley in a corridor.

**Nobody operates on a lapsed registration.** The team assignment goes through
`apps.hr.assert_may_practise`, the same check that already refuses a
prescription. A surgeon whose council registration expired is not a scheduling
inconvenience; operating on one is an offence and an uninsurable event.

**The safety checklist is recorded, not enforced.** The WHO checklist works
because it is said aloud, and a system that *blocks* an incision until
somebody ticks seven boxes gets bypassed within a week — usually by one person
ticking them all in advance. So the system lets the case proceed and records
that it proceeded without a time-out. An omission that is undeniable at the
next governance meeting changes behaviour; a dialog box does not.

**Consumption comes out of real stock.** A swab used in theatre leaves the
ledger through `apps.pharmacy.post_movement`, and an implant carries its
serial number, because a recall asks "which patients have one" and the only
acceptable answer is a list of names.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: an operation is the most litigated single event in a hospital. Who
# was in the room, what was implanted, whether the checklist was done.
from apps.audit.services import record
from apps.billing.models import ServiceItem
from apps.billing.services import capture_charge
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.entitlements.services import require_module
from apps.hr.models import Employee
from apps.hr.services import NotPractising, assert_may_practise
from apps.pharmacy.models import Batch, MovementType, Product
from apps.pharmacy.services import post_movement
from apps.tenancy.db import tenant_atomic_method
from apps.theatre.models import (
    AVOIDABLE_REASONS,
    CHECKLIST_ITEMS,
    LICENSED_ROLES,
    LIVE_STATUSES,
    REQUIRED_ROLES,
    AnaesthesiaRecord,
    CancellationReason,
    CaseConsumption,
    CaseStatus,
    ChecklistPhase,
    ConsumptionKind,
    RecoveryRecord,
    SafetyChecklist,
    SurgicalCase,
    TeamMember,
    TeamRole,
    Theatre,
    Urgency,
)

logger = logging.getLogger("nirova.theatre")

ZERO = Decimal("0.00")


class TheatreError(DomainError):
    code = "theatre_operation_failed"


class SlotUnavailable(TheatreError):
    code = "theatre_slot_unavailable"
    status_code = 409


class CaseNotReady(TheatreError):
    code = "case_not_ready"
    status_code = 409


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


def _next_reference() -> str:
    stem = f"OT{timezone.localdate():%y%m}"
    last = (
        SurgicalCase.all_objects.filter(reference__startswith=stem)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    serial = int(last[len(stem):]) + 1 if last else 1
    return f"{stem}{serial:04d}"


# ---------------------------------------------------------------------------
# Requesting and approving
# ---------------------------------------------------------------------------


@tenant_atomic_method
def request_case(
    organization,
    patient,
    facility,
    planned_procedure: str,
    actor=None,
    encounter=None,
    urgency: str = Urgency.ELECTIVE,
    planned_minutes: int = 60,
    laterality: str = "na",
    **details,
) -> SurgicalCase:
    """Ask for an operation.

    A request, not a booking. Separating the two is what lets a hospital hold
    a waiting list at all: the clinical decision that somebody needs surgery
    and the operational decision about when are made by different people,
    weeks apart.
    """
    require_module(organization, ModuleCode.HOSPITAL)

    survivor = patient.resolve()
    if survivor.pk != patient.pk:
        raise TheatreError(
            f"{patient.mrn} was merged into {survivor.mrn}. Request against "
            "the surviving record.",
            detail={"surviving_mrn": survivor.mrn},
        )

    case = SurgicalCase.objects.create(
        reference=_next_reference(),
        patient=patient,
        encounter=encounter,
        facility=facility,
        planned_procedure=planned_procedure,
        urgency=urgency,
        planned_minutes=planned_minutes,
        laterality=laterality,
        requested_by_id=getattr(actor, "uuid", None),
        requested_by_name=getattr(actor, "full_name", "") or "",
        created_by_id=getattr(actor, "uuid", None),
        **details,
    )

    # The three checklist phases exist from the moment the case does, so an
    # unperformed one is visibly unperformed rather than merely absent.
    for phase in ChecklistPhase.values:
        SafetyChecklist.objects.get_or_create(
            case=case, phase=phase,
            defaults={"created_by_id": getattr(actor, "uuid", None)},
        )

    record(
        AuditAction.CREATE,
        entity_type="theatre.SurgicalCase",
        entity_id=case.uuid,
        entity_label=f"{case.reference} — {planned_procedure[:60]}",
        metadata={"urgency": urgency, "patient": patient.mrn},
    )
    return case


@tenant_atomic_method
def approve_case(case: SurgicalCase, actor, notes: str = "") -> SurgicalCase:
    """Authorise the operation, before a slot is found for it."""
    if case.status != CaseStatus.REQUESTED:
        raise TheatreError(
            f"{case.reference} is {case.get_status_display().lower()}.",
            detail={"status": case.status},
        )
    case.status = CaseStatus.APPROVED
    case.approved_at = timezone.now()
    case.approved_by_id = getattr(actor, "uuid", None)
    case.approved_by_name = getattr(actor, "full_name", "") or ""
    if notes:
        case.notes = f"{case.notes}\n{notes}".strip()
    case.save()
    return case


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def overlapping_cases(theatre: Theatre, start, end, exclude=None):
    """Live cases whose slot collides with this one.

    Includes the theatre's own turnaround time on the end of each existing
    case: a room booked back-to-back with no cleaning gap is a room that will
    run late from the second case onwards, and the schedule should say so
    while it is still a schedule.
    """
    queryset = SurgicalCase.objects.filter(
        theatre=theatre,
        status__in=LIVE_STATUSES,
        scheduled_start__isnull=False,
        scheduled_end__isnull=False,
    )
    if exclude is not None:
        queryset = queryset.exclude(pk=exclude.pk)

    gap = timedelta(minutes=theatre.turnaround_minutes)
    return [
        case for case in queryset
        if case.scheduled_start < end + gap
        and start < case.scheduled_end + gap
    ]


@tenant_atomic_method
def schedule(
    case: SurgicalCase,
    theatre: Theatre,
    start,
    actor,
    minutes: int = None,
    force: bool = False,
    force_reason: str = "",
) -> SurgicalCase:
    """Give the case a room and a time.

    Refuses an overlap, including the room's turnaround gap. `force` exists
    for the emergency that genuinely has to go now — and it requires a reason,
    because bumping an elective list is exactly the decision a theatre
    committee later asks about.
    """
    if case.status in {CaseStatus.CANCELLED, CaseStatus.COMPLETED}:
        raise TheatreError(
            f"{case.reference} is {case.get_status_display().lower()}."
        )
    if theatre.facility_id != case.facility_id:
        raise TheatreError("That theatre is at a different facility.")

    minutes = minutes or case.planned_minutes
    end = start + timedelta(minutes=minutes)

    clashes = overlapping_cases(theatre, start, end, exclude=case)
    if clashes and not force:
        first = clashes[0]
        raise SlotUnavailable(
            f"{theatre.code} is booked for {first.reference} from "
            f"{first.scheduled_start:%H:%M} to {first.scheduled_end:%H:%M} "
            f"(plus {theatre.turnaround_minutes} minutes' turnaround).",
            detail={
                "clashes": [row.reference for row in clashes],
                "turnaround_minutes": theatre.turnaround_minutes,
            },
        )
    if clashes and force and not force_reason.strip():
        raise TheatreError("Double-booking a theatre must record why.")

    case.theatre = theatre
    case.scheduled_start = start
    case.scheduled_end = end
    case.planned_minutes = minutes
    case.status = CaseStatus.SCHEDULED
    if force_reason:
        case.notes = (
            f"{case.notes}\nDouble-booked: {force_reason}"
        ).strip()
    case.save()

    record(
        AuditAction.UPDATE,
        entity_type="theatre.SurgicalCase",
        entity_id=case.uuid,
        entity_label=f"{case.reference} scheduled in {theatre.code}",
        reason=force_reason,
        metadata={
            "start": start.isoformat(),
            "minutes": minutes,
            "forced_over": [row.reference for row in clashes],
        },
    )
    if clashes:
        logger.warning(
            "THEATRE DOUBLE-BOOKED %s over %s: %s",
            theatre.code, ", ".join(row.reference for row in clashes),
            force_reason,
        )
    return case


def day_list(theatre: Theatre, on_date=None) -> list:
    """One room's list for one day, in order, with the gaps between cases.

    The gaps are the point. A list with three twenty-minute holes in it has an
    hour of theatre time nobody can use and nobody is looking at.
    """
    on_date = on_date or timezone.localdate()
    cases = list(
        SurgicalCase.objects.filter(
            theatre=theatre,
            scheduled_start__date=on_date,
        )
        .exclude(status=CaseStatus.CANCELLED)
        .select_related("patient")
        .order_by("scheduled_start")
    )

    rows = []
    previous_end = None
    for case in cases:
        gap = None
        if previous_end is not None:
            gap = int(
                (case.scheduled_start - previous_end).total_seconds() // 60
            )
        rows.append(
            {
                "reference": case.reference,
                "patient": case.patient.full_name,
                "mrn": case.patient.mrn,
                "procedure": case.planned_procedure,
                "laterality": case.laterality,
                "urgency": case.urgency,
                "asa_grade": case.asa_grade,
                "status": case.status,
                "scheduled_start": case.scheduled_start,
                "scheduled_end": case.scheduled_end,
                "planned_minutes": case.planned_minutes,
                # Gap *before* this case, net of the room's turnaround. A
                # negative number means the list is booked tighter than the
                # room can physically turn round.
                "gap_before_minutes": gap,
                "unused_gap_minutes": (
                    max(gap - theatre.turnaround_minutes, 0)
                    if gap is not None else None
                ),
                "actual_start": case.wheels_in_at,
                "start_delay_minutes": case.start_delay_minutes,
                "theatre_minutes": case.theatre_minutes,
                "overran_minutes": case.overran_minutes,
            }
        )
        previous_end = case.scheduled_end
    return rows


# ---------------------------------------------------------------------------
# The team
# ---------------------------------------------------------------------------


@tenant_atomic_method
def assign(
    case: SurgicalCase,
    employee: Employee,
    role: str,
    actor=None,
    allow_unregistered: bool = False,
) -> TeamMember:
    """Put somebody in the room.

    A licensed role goes through the same practice check that refuses a
    prescription. Operating on a lapsed council registration is an offence and
    an uninsurable event, so it is refused rather than warned about — and the
    override, where a hospital has a documented reason, is explicit.
    """
    if role in LICENSED_ROLES and not allow_unregistered:
        assert_may_practise(employee)

    registration = ""
    for credential in employee.credentials.all():
        if credential.credential_type == "council" and not credential.is_expired:
            registration = credential.reference_number
            break

    member, _ = TeamMember.objects.update_or_create(
        case=case,
        employee=employee,
        role=role,
        defaults={
            # Snapshotted, because the person may leave and the case record
            # must still say who operated.
            "name": employee.full_name,
            "registration_number": registration,
            "created_by_id": getattr(actor, "uuid", None),
        },
    )
    return member


def team_gaps(case: SurgicalCase) -> list:
    """Required roles nobody is filling.

    A list rather than a boolean, because the theatre coordinator chasing a
    case needs to know which phone to pick up.
    """
    filled = set(case.team.values_list("role", flat=True))
    return [
        {
            "role": role,
            "message": (
                f"No {TeamRole(role).label.lower()} assigned."
            ),
        }
        for role in REQUIRED_ROLES
        if role not in filled
    ]


# ---------------------------------------------------------------------------
# The safety checklist
# ---------------------------------------------------------------------------


@tenant_atomic_method
def complete_checklist(
    case: SurgicalCase,
    phase: str,
    actor,
    responses: dict = None,
    concerns: str = "",
    at=None,
) -> SafetyChecklist:
    """Record that a checklist phase was performed.

    `at` is when it was *performed*, which is not always when it is typed. A
    theatre nurse records the sign-in a few minutes after the team said it
    aloud, and defaulting to the moment of entry would show every case
    checklisted after its own incision — turning the audit's one real finding
    into noise. Defaults to now, because usually the two are close.

    Unanswered items are not treated as failures — a phase performed in a
    hurry with two items unrecorded is still better evidence than no record at
    all, and refusing it would produce exactly the pre-ticking the checklist
    exists to prevent. `unanswered` reports them so an audit can see.
    """
    checklist, _ = SafetyChecklist.objects.get_or_create(case=case, phase=phase)
    checklist.responses = responses or {}
    checklist.concerns = concerns
    checklist.completed_at = at or timezone.now()
    checklist.completed_by_id = getattr(actor, "uuid", None)
    checklist.completed_by_name = getattr(actor, "full_name", "") or ""
    checklist.was_skipped = False
    checklist.skip_reason = ""
    checklist.save()

    if checklist.negative_answers:
        logger.warning(
            "SAFETY CHECKLIST CONCERNS %s %s: %s",
            case.reference, phase, "; ".join(checklist.negative_answers),
        )
    record(
        AuditAction.UPDATE,
        entity_type="theatre.SafetyChecklist",
        entity_id=checklist.uuid,
        entity_label=f"{case.reference} {phase} completed",
        reason=concerns,
        metadata={
            "unanswered": len(checklist.unanswered),
            "negative": checklist.negative_answers,
        },
    )
    return checklist


@tenant_atomic_method
def skip_checklist(
    case: SurgicalCase, phase: str, actor, reason: str
) -> SafetyChecklist:
    """Record that a phase was *not* performed, and why.

    The alternative — leaving it blank — is indistinguishable from nobody
    having got round to filling the form in. A skip with a reason is a
    decision somebody made and can be asked about.
    """
    if not reason.strip():
        raise TheatreError("Skipping a safety checklist phase must say why.")

    checklist, _ = SafetyChecklist.objects.get_or_create(case=case, phase=phase)
    checklist.was_skipped = True
    checklist.skip_reason = reason
    checklist.completed_at = timezone.now()
    checklist.completed_by_id = getattr(actor, "uuid", None)
    checklist.completed_by_name = getattr(actor, "full_name", "") or ""
    checklist.save()

    logger.warning(
        "SAFETY CHECKLIST SKIPPED %s %s by %s: %s",
        case.reference, phase, getattr(actor, "email", "?"), reason,
    )
    record(
        AuditAction.REJECT,
        entity_type="theatre.SafetyChecklist",
        entity_id=checklist.uuid,
        entity_label=f"{case.reference} {phase} SKIPPED",
        reason=reason,
    )
    return checklist


def checklist_state(case: SurgicalCase) -> dict:
    """What was done, what was not, and what happened anyway.

    `incision_without_timeout` is the finding this whole model exists to
    surface. It is not an error the system prevented; it is a fact it refuses
    to lose.
    """
    rows = {row.phase: row for row in case.checklists.all()}
    time_out = rows.get(ChecklistPhase.TIME_OUT)

    incision_without_timeout = bool(
        case.incision_at
        and (
            time_out is None
            or not time_out.is_complete
            or (
                time_out.completed_at
                and time_out.completed_at > case.incision_at
            )
        )
    )

    return {
        "case": case.reference,
        "phases": [
            {
                "phase": phase,
                "label": ChecklistPhase(phase).label,
                "complete": rows[phase].is_complete if phase in rows else False,
                "skipped": rows[phase].was_skipped if phase in rows else False,
                "skip_reason": (
                    rows[phase].skip_reason if phase in rows else ""
                ),
                "completed_at": (
                    rows[phase].completed_at if phase in rows else None
                ),
                "completed_by": (
                    rows[phase].completed_by_name if phase in rows else ""
                ),
                "unanswered": rows[phase].unanswered if phase in rows else (
                    CHECKLIST_ITEMS.get(phase, [])
                ),
                "concerns": rows[phase].concerns if phase in rows else "",
                "negative_answers": (
                    rows[phase].negative_answers if phase in rows else []
                ),
            }
            for phase in ChecklistPhase.values
        ],
        "all_complete": all(
            phase in rows and rows[phase].is_complete
            for phase in ChecklistPhase.values
        ),
        "incision_without_timeout": incision_without_timeout,
    }


# ---------------------------------------------------------------------------
# Running the case
# ---------------------------------------------------------------------------


#: Which timing field each step writes, and what status it moves the case to.
STEPS = {
    "sent_for": ("sent_for_at", CaseStatus.SENT_FOR),
    "wheels_in": ("wheels_in_at", CaseStatus.IN_THEATRE),
    "anaesthesia_start": ("anaesthesia_start_at", CaseStatus.IN_THEATRE),
    "incision": ("incision_at", CaseStatus.IN_THEATRE),
    "closure": ("closure_at", CaseStatus.IN_THEATRE),
    "wheels_out": ("wheels_out_at", CaseStatus.IN_RECOVERY),
    "recovery_out": ("recovery_out_at", CaseStatus.COMPLETED),
}


@tenant_atomic_method
def mark(case: SurgicalCase, step: str, actor, at=None) -> SurgicalCase:
    """Record one of the case's timings.

    Each is a moment somebody records at the time. The productivity figures in
    this module are all differences between two of them, so a timing entered
    from memory at the end of the list is worth much less than one entered as
    it happened — which is why every one is a separate action rather than a
    form filled in afterwards.
    """
    if step not in STEPS:
        raise TheatreError(f"'{step}' is not a step in a case.")
    if case.status in {CaseStatus.CANCELLED, CaseStatus.POSTPONED}:
        raise TheatreError(
            f"{case.reference} is {case.get_status_display().lower()}."
        )

    field, status = STEPS[step]
    if getattr(case, field) is not None:
        return case

    at = at or timezone.now()
    setattr(case, field, at)
    case.status = status
    case.save()

    if step == "incision":
        state = checklist_state(case)
        if state["incision_without_timeout"]:
            # Recorded, not prevented. A system that blocks the incision gets
            # bypassed; one that makes the omission undeniable gets discussed.
            logger.warning(
                "INCISION WITHOUT A TIME-OUT %s — surgeon %s",
                case.reference,
                case.team.filter(role=TeamRole.PRIMARY_SURGEON)
                .values_list("name", flat=True).first() or "unknown",
            )
            record(
                AuditAction.UPDATE,
                entity_type="theatre.SurgicalCase",
                entity_id=case.uuid,
                entity_label=f"{case.reference} incised without a time-out",
                reason="WHO time-out not completed before incision.",
            )
    return case


@tenant_atomic_method
def cancel_case(
    case: SurgicalCase,
    actor,
    reason: str,
    notes: str = "",
    postpone: bool = False,
) -> SurgicalCase:
    """Call it off, with a countable reason.

    The reason is an enum because a cancelled list is the largest single waste
    in a hospital and "why" has to be summable. A free-text reason tells
    nobody whether the fix is more beds, more anaesthetists or better
    pre-assessment.
    """
    if case.status in {CaseStatus.COMPLETED, CaseStatus.CANCELLED}:
        raise TheatreError(
            f"{case.reference} is already "
            f"{case.get_status_display().lower()}."
        )
    if reason not in CancellationReason.values:
        raise TheatreError(f"'{reason}' is not a recognised reason.")

    case.status = (
        CaseStatus.POSTPONED if postpone else CaseStatus.CANCELLED
    )
    case.cancelled_at = timezone.now()
    case.cancellation_reason = reason
    case.cancellation_notes = notes
    case.save()

    record(
        AuditAction.DELETE,
        entity_type="theatre.SurgicalCase",
        entity_id=case.uuid,
        entity_label=f"{case.reference} {case.status}",
        reason=f"{reason}: {notes}",
        metadata={"avoidable": case.was_avoidable_cancellation},
    )
    if case.was_avoidable_cancellation:
        logger.warning(
            "AVOIDABLE THEATRE CANCELLATION %s: %s — %s",
            case.reference, reason, notes,
        )
    return case


# ---------------------------------------------------------------------------
# Consumption
# ---------------------------------------------------------------------------


@tenant_atomic_method
def consume(
    organization,
    case: SurgicalCase,
    description: str,
    actor,
    kind: str = ConsumptionKind.CONSUMABLE,
    product: Product = None,
    batch: Batch = None,
    quantity=Decimal("1"),
    serial_number: str = "",
    unit_cost=None,
    service_code: str = "",
    implanted_site: str = "",
    notes: str = "",
) -> CaseConsumption:
    """Record something used, taking it out of stock and onto the bill.

    Three things happen and the order matters: the stock moves first, so a
    swab that is not there is refused before anybody is charged for it; then
    the consumption row; then the charge.

    An implant must carry a serial number. When a batch is recalled the
    question is "which patients have one", and a product code cannot answer
    it.
    """
    quantity = Decimal(str(quantity))
    if quantity <= ZERO:
        raise TheatreError("A consumption must have a positive quantity.")
    if kind == ConsumptionKind.IMPLANT and not serial_number.strip():
        raise TheatreError(
            "An implant must carry its serial number — a recall asks which "
            "patients have one, and a product code cannot answer that.",
            detail={"description": description},
        )
    if kind == ConsumptionKind.IMPLANT:
        # Checked here as well as by the database constraint, so the theatre
        # gets a sentence rather than an IntegrityError. Two patients cannot
        # hold the same physical device: a repeat means a mis-keyed serial or
        # a counterfeit, and both matter more at the point of entry than at
        # the point of recall.
        existing = CaseConsumption.objects.filter(
            kind=ConsumptionKind.IMPLANT, serial_number=serial_number
        ).select_related("case", "case__patient").first()
        if existing is not None:
            raise TheatreError(
                f"Serial {serial_number} is already recorded against "
                f"{existing.case.patient.full_name} in {existing.case.reference}. "
                "Two patients cannot hold the same device — check the serial.",
                detail={
                    "serial_number": serial_number,
                    "existing_case": existing.case.reference,
                },
            )

    entry = None
    if batch is not None and case.theatre and case.theatre.stock_location:
        entry = post_movement(
            batch=batch,
            location=case.theatre.stock_location,
            movement_type=MovementType.DISPENSE,
            quantity=quantity,
            actor=actor,
            reason=f"Used in {case.reference}",
            reference_type="theatre.SurgicalCase",
            reference_id=case.reference,
            patient=case.patient,
            unit_cost=batch.purchase_price,
        )

    cost = Decimal(str(unit_cost)) if unit_cost is not None else (
        batch.purchase_price if batch else ZERO
    )
    consumption = CaseConsumption.objects.create(
        case=case,
        kind=kind,
        product=product or (batch.product if batch else None),
        batch=batch,
        description=description,
        batch_number=batch.batch_number if batch else "",
        serial_number=serial_number,
        expires_on=batch.expires_on if batch else None,
        quantity=quantity,
        unit_cost=cost,
        total_cost=(cost * quantity).quantize(Decimal("0.01")),
        stock_entry_uuid=getattr(entry, "uuid", None),
        implanted_site=implanted_site,
        recorded_by_id=getattr(actor, "uuid", None),
        recorded_by_name=getattr(actor, "full_name", "") or "",
        notes=notes,
        created_by_id=getattr(actor, "uuid", None),
    )

    if service_code:
        service = ServiceItem.objects.filter(
            code=service_code, is_active=True
        ).first()
        if service is not None:
            charge = capture_charge(
                organization=organization,
                patient=case.patient,
                facility=case.facility,
                service=service,
                actor=actor,
                encounter=case.encounter,
                quantity=quantity,
                notes=f"{case.reference}: {description}",
            )
            consumption.charge_uuid = charge.uuid
            consumption.save(update_fields=["charge_uuid", "updated_at"])

    if kind == ConsumptionKind.IMPLANT:
        logger.info(
            "IMPLANT %s serial %s into %s during %s",
            description, serial_number, case.patient.mrn, case.reference,
        )
    return consumption


def implant_registry(product: Product = None, batch: Batch = None) -> list:
    """Which patients have an implant from a given product or batch.

    The reason serial numbers are stored. Called on the morning a
    manufacturer issues a recall, and the answer has to be names and phone
    numbers rather than a count.
    """
    queryset = CaseConsumption.objects.filter(
        kind=ConsumptionKind.IMPLANT
    ).select_related("case", "case__patient")
    if product is not None:
        queryset = queryset.filter(product=product)
    if batch is not None:
        queryset = queryset.filter(batch=batch)

    return [
        {
            "patient": row.case.patient.full_name,
            "mrn": row.case.patient.mrn,
            "phone": row.case.patient.phone,
            "case": row.case.reference,
            "operated_on": row.case.incision_at or row.case.scheduled_start,
            "procedure": row.case.performed_procedure or row.case.planned_procedure,
            "implant": row.description,
            "serial_number": row.serial_number,
            "batch_number": row.batch_number,
            "site": row.implanted_site,
        }
        for row in queryset.order_by("-created_at")
    ]


def case_cost(case: SurgicalCase) -> dict:
    """What the case consumed, by kind.

    Implants are reported separately because they dominate the cost of an
    orthopaedic case and are the thing a payer queries.
    """
    rows = case.consumption.all()
    by_kind = dict(
        rows.values_list("kind")
        .annotate(total=models.Sum("total_cost"))
        .values_list("kind", "total")
    )
    return {
        "case": case.reference,
        "items": rows.count(),
        "by_kind": by_kind,
        "total": rows.aggregate(t=models.Sum("total_cost"))["t"] or ZERO,
        "implants": [
            {
                "description": row.description,
                "serial_number": row.serial_number,
                "site": row.implanted_site,
                "cost": row.total_cost,
            }
            for row in rows.filter(kind=ConsumptionKind.IMPLANT)
        ],
        "unbilled": rows.filter(charge_uuid__isnull=True).count(),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def utilisation(theatre: Theatre, since=None, until=None) -> dict:
    """How much of the room's staffed time was spent operating.

    Three figures, deliberately: booked, used and available. A room booked to
    90% that only operates for 60% of its session has an hour a day of
    late starts and slow turnarounds, and a single "utilisation" number would
    show the same 90% as a room running perfectly.
    """
    until = until or timezone.localdate()
    since = since or (until - timedelta(days=30))

    cases = SurgicalCase.objects.filter(
        theatre=theatre,
        scheduled_start__date__gte=since,
        scheduled_start__date__lte=until,
    )
    done = [row for row in cases if row.theatre_minutes is not None]

    booked = sum(row.planned_minutes for row in cases.exclude(
        status=CaseStatus.CANCELLED
    ))
    used = sum(row.theatre_minutes for row in done)

    session_minutes = 0
    if theatre.session_starts_at and theatre.session_ends_at:
        start = (
            theatre.session_starts_at.hour * 60
            + theatre.session_starts_at.minute
        )
        end = (
            theatre.session_ends_at.hour * 60 + theatre.session_ends_at.minute
        )
        days = (until - since).days + 1
        # Weekdays only: a room staffed Sunday to Friday in Nepal still does
        # not run on its weekly holiday, and counting Saturdays would make
        # every theatre look 17% idle.
        weekdays = sum(
            1 for offset in range(days)
            if (since + timedelta(days=offset)).weekday() != 5
        )
        session_minutes = max(end - start, 0) * weekdays

    delays = [
        row.start_delay_minutes for row in done
        if row.start_delay_minutes is not None
    ]
    overruns = [
        row.overran_minutes for row in done if row.overran_minutes is not None
    ]

    cancelled = cases.filter(status=CaseStatus.CANCELLED)
    avoidable = cancelled.filter(cancellation_reason__in=AVOIDABLE_REASONS)

    return {
        "theatre": theatre.code,
        "from": since,
        "to": until,
        "cases": cases.count(),
        "completed": len(done),
        "cancelled": cancelled.count(),
        "avoidable_cancellations": avoidable.count(),
        "cancellation_reasons": dict(
            cancelled.values_list("cancellation_reason")
            .annotate(n=models.Count("id"))
            .values_list("cancellation_reason", "n")
        ),
        "session_minutes": session_minutes,
        "booked_minutes": booked,
        "used_minutes": used,
        "booked_percent": (
            round(booked / session_minutes * 100, 1) if session_minutes else None
        ),
        "used_percent": (
            round(used / session_minutes * 100, 1) if session_minutes else None
        ),
        "average_start_delay_minutes": (
            round(sum(delays) / len(delays), 1) if delays else None
        ),
        "cases_starting_late": sum(1 for value in delays if value > 0),
        "average_overrun_minutes": (
            round(sum(overruns) / len(overruns), 1) if overruns else None
        ),
    }


def safety_audit(facility, since=None) -> dict:
    """How reliably the checklist is actually being done.

    The number that matters is not "how many checklists exist" but "how many
    incisions happened without a time-out", because the second is the failure
    the checklist exists to prevent.
    """
    since = since or (timezone.localdate() - timedelta(days=90))
    cases = SurgicalCase.objects.filter(
        facility=facility,
        incision_at__date__gte=since,
    ).prefetch_related("checklists")

    total = cases.count()
    breaches = []
    skipped = 0
    for case in cases:
        state = checklist_state(case)
        if state["incision_without_timeout"]:
            breaches.append(case.reference)
        skipped += sum(1 for row in state["phases"] if row["skipped"])

    return {
        "since": since,
        "operations": total,
        "incisions_without_a_time_out": len(breaches),
        "breach_percent": (
            round(len(breaches) / total * 100, 1) if total else 0.0
        ),
        "breaching_cases": breaches[:20],
        "phases_skipped": skipped,
        "fully_compliant_percent": (
            round((total - len(breaches)) / total * 100, 1) if total else 0.0
        ),
    }
