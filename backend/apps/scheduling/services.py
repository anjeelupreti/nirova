"""Booking appointments and running the queue."""

import logging
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.catalog.keys import MeterKey, ModuleCode
from apps.common.exceptions import DomainError
from apps.entitlements.services import require_module
from apps.scheduling.models import (
    OCCUPIES_SLOT,
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    ProviderSchedule,
    QueueStatus,
    QueueToken,
    ScheduleException,
)
# tenant_atomic_method: transactions must open on the tenant database, not the
# control plane. See apps/tenancy/db.py for why this is not optional.
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.scheduling")

#: Times a token is called before the queue moves past it. Three is a
#: compromise: enough that someone in the toilet is not lost, few enough that
#: one absentee does not stall a clinic of forty people.
MAX_CALLS_BEFORE_SKIP = 3


class SchedulingError(DomainError):
    code = "scheduling_failed"


class SlotUnavailable(SchedulingError):
    code = "slot_unavailable"
    message = "That appointment slot is no longer available."


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def _blocked_by_exception(schedule: ProviderSchedule, on_date) -> bool:
    """Whether leave or a holiday removes this session."""
    return ScheduleException.objects.filter(
        Q(schedule=schedule) | Q(provider_uuid=schedule.provider_uuid),
        exception_date=on_date,
        is_unavailable=True,
    ).exists()


def available_slots(schedule: ProviderSchedule, on_date, for_online: bool = False) -> list:
    """Free slot times for one schedule on one date.

    Counts appointments per slot rather than assuming one each, because
    `slot_capacity` allows deliberate overbooking. Online booking additionally
    respects `walk_in_reserve`, so the diary cannot be filled remotely to the
    point where a patient who travelled in has nowhere to go.
    """
    if not schedule.applies_on(on_date) or _blocked_by_exception(schedule, on_date):
        return []
    if for_online and not schedule.is_accepting_online:
        return []

    slots = schedule.slot_times(on_date)
    if not slots:
        return []

    taken = dict(
        Appointment.objects.filter(
            schedule=schedule,
            scheduled_for__date=on_date,
            status__in=list(OCCUPIES_SLOT),
        )
        .values_list("scheduled_for")
        .annotate(count=Count("id"))
        .values_list("scheduled_for", "count")
    )

    free = [slot for slot in slots if taken.get(slot, 0) < schedule.slot_capacity]

    if for_online and schedule.walk_in_reserve:
        # Hold back the last N slots of the session for people at the door.
        keep_back = min(schedule.walk_in_reserve, len(free))
        free = free[: len(free) - keep_back] if keep_back else free

    return free


def booked_count(schedule: ProviderSchedule, on_date) -> int:
    """How many appointments a session already holds on a date."""
    return Appointment.objects.filter(
        schedule=schedule,
        scheduled_for__date=on_date,
        status__in=list(OCCUPIES_SLOT),
    ).count()


def provider_day_view(facility, on_date, provider_uuid=None) -> list:
    """Every session at a facility on a date, with free-slot counts."""
    schedules = ProviderSchedule.objects.filter(facility=facility, is_active=True)
    if provider_uuid:
        schedules = schedules.filter(provider_uuid=provider_uuid)

    day = []
    for schedule in schedules:
        if not schedule.applies_on(on_date):
            continue
        free = available_slots(schedule, on_date)
        # Remaining *capacity*, not the number of slots with room in them.
        # With slot_capacity 2, a session of 9 slots holding 4 bookings still
        # has 9 slots "available" -- which reads to a receptionist as an empty
        # diary. What they need to know is how many more patients fit.
        booked = booked_count(schedule, on_date)
        capacity = schedule.total_slots * schedule.slot_capacity

        day.append(
            {
                "schedule_uuid": str(schedule.uuid),
                "provider_uuid": str(schedule.provider_uuid),
                "provider_name": schedule.provider_name,
                "department": schedule.department.name if schedule.department else None,
                "room": schedule.room,
                "start_time": schedule.start_time.isoformat(),
                "end_time": schedule.end_time.isoformat(),
                "total_slots": schedule.total_slots,
                "slot_capacity": schedule.slot_capacity,
                "capacity": capacity,
                "booked": booked,
                "remaining_capacity": max(capacity - booked, 0),
                "open_slot_times": len(free),
                "is_blocked": _blocked_by_exception(schedule, on_date),
                "next_free": free[0].isoformat() if free else None,
                "consultation_fee": (
                    str(schedule.consultation_fee) if schedule.consultation_fee else None
                ),
            }
        )
    return day


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------


def generate_appointment_reference() -> str:
    """Sequential, quotable reference: APT-2026-000142."""
    year = timezone.now().year
    prefix = f"APT-{year}-"
    last = (
        Appointment.all_objects.filter(reference__startswith=prefix)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{sequence:06d}"


@tenant_atomic_method
def book_appointment(
    organization,
    patient,
    facility,
    scheduled_for,
    schedule=None,
    department=None,
    provider_uuid=None,
    provider_name: str = "",
    reason: str = "",
    source: str = AppointmentSource.COUNTER,
    priority: int = 0,
    actor=None,
    is_follow_up: bool = False,
) -> Appointment:
    """Book an appointment, re-checking capacity inside the transaction.

    The availability check is repeated here rather than trusted from the
    caller's earlier read: between a patient choosing a slot on screen and
    confirming it, someone at a counter may have taken it. Checking under the
    transaction is what makes double-booking impossible rather than unlikely.
    """
    require_module(organization, ModuleCode.CLINIC)

    if scheduled_for < timezone.now() - timedelta(hours=1):
        raise SchedulingError(
            "Appointments cannot be booked in the past.",
            detail={"scheduled_for": scheduled_for.isoformat()},
        )

    if schedule is not None:
        taken = Appointment.objects.select_for_update().filter(
            schedule=schedule,
            scheduled_for=scheduled_for,
            status__in=list(OCCUPIES_SLOT),
        ).count()
        if taken >= schedule.slot_capacity:
            raise SlotUnavailable(
                f"That slot already holds {taken} of {schedule.slot_capacity} "
                "bookings.",
                detail={
                    "scheduled_for": scheduled_for.isoformat(),
                    "capacity": schedule.slot_capacity,
                },
            )
        provider_uuid = provider_uuid or schedule.provider_uuid
        provider_name = provider_name or schedule.provider_name
        department = department or schedule.department

    # A patient double-booked with the same provider at the same moment is
    # always a mistake -- usually a double-submitted form.
    clash = Appointment.objects.filter(
        patient=patient,
        scheduled_for=scheduled_for,
        status__in=list(OCCUPIES_SLOT),
    ).exists()
    if clash:
        raise SchedulingError(
            "This patient already has an appointment at that time.",
            detail={"patient": patient.mrn},
        )

    appointment = Appointment.objects.create(
        reference=generate_appointment_reference(),
        patient=patient,
        facility=facility,
        department=department,
        schedule=schedule,
        provider_uuid=provider_uuid,
        provider_name=provider_name,
        scheduled_for=scheduled_for,
        duration_minutes=schedule.slot_minutes if schedule else 15,
        reason=reason,
        source=source,
        priority=priority,
        is_follow_up=is_follow_up,
        booked_by_id=getattr(actor, "uuid", None),
        created_by_id=getattr(actor, "uuid", None),
    )

    record(
        AuditAction.CREATE,
        entity_type="scheduling.Appointment",
        entity_id=appointment.uuid,
        entity_label=f"{appointment.reference} for {patient.mrn}",
        metadata={
            "scheduled_for": scheduled_for.isoformat(),
            "provider": provider_name,
            "source": source,
        },
    )
    _meter(organization, MeterKey.APPOINTMENTS)
    return appointment


@tenant_atomic_method
def cancel_appointment(appointment, actor, reason: str) -> Appointment:
    """Cancel an appointment and release its slot."""
    if appointment.status in {
        AppointmentStatus.COMPLETED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
    }:
        raise SchedulingError(
            f"An appointment that is {appointment.get_status_display().lower()} "
            "cannot be cancelled.",
            detail={"status": appointment.status},
        )

    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancelled_at = timezone.now()
    appointment.cancellation_reason = reason
    appointment.cancelled_by_id = getattr(actor, "uuid", None)
    appointment.save(
        update_fields=[
            "status", "cancelled_at", "cancellation_reason",
            "cancelled_by_id", "updated_at",
        ]
    )

    # A cancelled appointment's token should not keep a place in the queue.
    token = getattr(appointment, "queue_token", None)
    if token and token.is_active:
        token.status = QueueStatus.LEFT
        token.completed_at = timezone.now()
        token.save(update_fields=["status", "completed_at", "updated_at"])

    record(
        AuditAction.CANCEL,
        entity_type="scheduling.Appointment",
        entity_id=appointment.uuid,
        entity_label=appointment.reference,
        reason=reason,
    )
    return appointment


def mark_no_show(appointment, actor) -> Appointment:
    """Record that a patient did not attend.

    Distinct from cancellation: a no-show consumed the slot and is a signal
    worth measuring, both for provider utilisation and for spotting patients
    who repeatedly cannot attend and may need a different arrangement.
    """
    appointment.status = AppointmentStatus.NO_SHOW
    appointment.save(update_fields=["status", "updated_at"])
    record(
        AuditAction.UPDATE,
        entity_type="scheduling.Appointment",
        entity_id=appointment.uuid,
        entity_label=appointment.reference,
        changes={"status": {"before": AppointmentStatus.SCHEDULED,
                            "after": AppointmentStatus.NO_SHOW}},
    )
    return appointment


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


def _next_token_number(facility, on_date, department=None) -> str:
    """Next token for a facility-day, prefixed by department.

    Prefixing matters at a counter: "D-014" and "L-014" are told apart when
    called across a crowded waiting room; "14" and "14" are not.
    """
    prefix = (department.code[:1].upper() if department and department.code else "T")
    last = (
        QueueToken.all_objects.filter(
            facility=facility, queue_date=on_date, token_number__startswith=f"{prefix}-"
        )
        .order_by("-token_number")
        .values_list("token_number", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}-{sequence:03d}"


@tenant_atomic_method
def issue_token(
    organization,
    patient,
    facility,
    department=None,
    appointment=None,
    provider_uuid=None,
    priority: int = 0,
    is_emergency: bool = False,
    actor=None,
) -> QueueToken:
    """Put a patient into today's queue.

    Emergencies are given a priority that outranks every routine token
    outright, rather than a merely higher number — triage should not be a
    matter of degree when someone is critically unwell.
    """
    require_module(organization, ModuleCode.CLINIC)
    today = timezone.localdate()

    existing = QueueToken.objects.filter(
        patient=patient,
        facility=facility,
        queue_date=today,
        status__in=[QueueStatus.WAITING, QueueStatus.CALLED, QueueStatus.IN_SERVICE],
    ).first()
    if existing:
        return existing

    token = QueueToken.objects.create(
        token_number=_next_token_number(facility, today, department),
        queue_date=today,
        patient=patient,
        appointment=appointment,
        facility=facility,
        department=department,
        provider_uuid=provider_uuid
        or (appointment.provider_uuid if appointment else None),
        priority=100 if is_emergency else priority,
        is_emergency=is_emergency,
        created_by_id=getattr(actor, "uuid", None),
    )

    if appointment and appointment.status in OCCUPIES_SLOT:
        appointment.status = AppointmentStatus.ARRIVED
        appointment.arrived_at = timezone.now()
        appointment.save(update_fields=["status", "arrived_at", "updated_at"])

    record(
        AuditAction.CREATE,
        entity_type="scheduling.QueueToken",
        entity_id=token.uuid,
        entity_label=f"{token.token_number} for {patient.mrn}",
        metadata={"emergency": is_emergency, "priority": token.priority},
    )
    return token


def queue_for(facility, department=None, provider_uuid=None, on_date=None) -> list:
    """The live queue, in the order patients will actually be seen."""
    on_date = on_date or timezone.localdate()
    tokens = QueueToken.objects.filter(
        facility=facility,
        queue_date=on_date,
        status__in=[QueueStatus.WAITING, QueueStatus.CALLED, QueueStatus.IN_SERVICE],
    ).select_related("patient", "department")

    if department:
        tokens = tokens.filter(department=department)
    if provider_uuid:
        tokens = tokens.filter(provider_uuid=provider_uuid)

    # Priority first, then arrival. Emergencies carry priority 100 and so
    # always precede routine tokens regardless of when they arrived.
    return list(tokens.order_by("-priority", "issued_at"))


@tenant_atomic_method
def call_next(facility, department=None, provider_uuid=None, counter: str = "",
              actor=None) -> QueueToken | None:
    """Call the next waiting patient.

    Returns `None` when the queue is empty, rather than raising: an empty
    queue is the normal state of a quiet afternoon, not an error.
    """
    waiting = [
        token
        for token in queue_for(facility, department, provider_uuid)
        if token.status == QueueStatus.WAITING
    ]
    if not waiting:
        return None

    token = waiting[0]
    token.status = QueueStatus.CALLED
    token.called_at = timezone.now()
    token.call_count += 1
    token.counter = counter or token.counter
    token.save(
        update_fields=["status", "called_at", "call_count", "counter", "updated_at"]
    )
    return token


@tenant_atomic_method
def recall_or_skip(token, actor=None) -> QueueToken:
    """Call a token again, or move past it once it has been called enough.

    Skipping does not discard the patient: a skipped token can be re-queued
    when they reappear, and the record shows they were called.
    """
    if token.call_count >= MAX_CALLS_BEFORE_SKIP:
        token.status = QueueStatus.SKIPPED
        token.save(update_fields=["status", "updated_at"])
        logger.info("Token %s skipped after %d calls", token.token_number,
                    token.call_count)
        return token

    token.call_count += 1
    token.called_at = timezone.now()
    token.save(update_fields=["call_count", "called_at", "updated_at"])
    return token


@tenant_atomic_method
def start_service(token, actor=None) -> QueueToken:
    """The patient is now with the clinician."""
    token.status = QueueStatus.IN_SERVICE
    token.service_started_at = timezone.now()
    token.save(update_fields=["status", "service_started_at", "updated_at"])

    if token.appointment:
        token.appointment.status = AppointmentStatus.IN_CONSULTATION
        token.appointment.consultation_started_at = token.service_started_at
        token.appointment.save(
            update_fields=["status", "consultation_started_at", "updated_at"]
        )
    return token


@tenant_atomic_method
def complete_service(token, actor=None) -> QueueToken:
    token.status = QueueStatus.COMPLETED
    token.completed_at = timezone.now()
    token.save(update_fields=["status", "completed_at", "updated_at"])

    if token.appointment:
        token.appointment.status = AppointmentStatus.COMPLETED
        token.appointment.consultation_ended_at = token.completed_at
        token.appointment.save(
            update_fields=["status", "consultation_ended_at", "updated_at"]
        )
    return token


def queue_statistics(facility, on_date=None) -> dict:
    """Today's queue at a glance, for the front desk and the command centre."""
    on_date = on_date or timezone.localdate()
    tokens = QueueToken.objects.filter(facility=facility, queue_date=on_date)

    counts = dict(
        tokens.values_list("status").annotate(n=Count("id")).values_list("status", "n")
    )
    waiting = [t for t in tokens if t.status == QueueStatus.WAITING]
    served = [t for t in tokens if t.service_started_at]

    average_wait = (
        int(sum(t.waiting_minutes for t in served) / len(served)) if served else 0
    )
    return {
        "date": on_date.isoformat(),
        "total_tokens": tokens.count(),
        "waiting": counts.get(QueueStatus.WAITING, 0),
        "in_service": counts.get(QueueStatus.IN_SERVICE, 0),
        "completed": counts.get(QueueStatus.COMPLETED, 0),
        "skipped": counts.get(QueueStatus.SKIPPED, 0),
        "left": counts.get(QueueStatus.LEFT, 0),
        "emergencies": tokens.filter(is_emergency=True).count(),
        "average_wait_minutes": average_wait,
        "longest_wait_minutes": (
            max((t.waiting_minutes for t in waiting), default=0)
        ),
    }


def _meter(organization, meter_key: str) -> None:
    from apps.metering.models import UsageEvent

    try:
        UsageEvent.objects.create(
            organization=organization, meter_key=meter_key, quantity=1
        )
    except Exception:
        logger.exception("Failed to meter %s for %s", meter_key, organization.slug)
