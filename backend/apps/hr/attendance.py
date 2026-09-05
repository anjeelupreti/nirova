"""Working the roster, marking attendance, and taking leave.

The two rules this module exists to hold:

**A day's attendance status is derived, never asserted.** Leave is routinely
approved after the absence, and a day stored as `absent` would then contradict
an approved leave record. `derive_status` computes it from the facts —
roster, holiday calendar, weekly off, approved leave, the times themselves —
and `Attendance.status` is a cache that anything upstream refreshes.

**A leave balance is the sum of a ledger, never a counter.** Same discipline
as the stock ledger. A stored balance that drifts cannot be reconstructed, and
leave is something people dispute holding a payslip.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: leave approvals and attendance corrections are both contested, and
# the pattern of corrections is what an auditor actually looks at.
from apps.audit.services import record
# notify / holders_of: an approval nobody is told about is an approval
# that waits. holders_of answers 'who can approve this' from the
# permission outwards, which is the direction a notification needs.
from apps.notifications.models import NotificationCategory
from apps.notifications.services import notify, resolve_by_key
from apps.rbac.services import holders_of
from apps.billing.fiscal import fiscal_year_for
from apps.common.exceptions import DomainError
from apps.hr.models import (
    WEEKLY_HOLIDAY,
    WORKING_STATUSES,
    Attendance,
    AttendanceRegularisation,
    AttendanceSource,
    AttendanceStatus,
    Employee,
    Holiday,
    LeaveLedgerEntry,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    LedgerReason,
    RegularisationStatus,
    RosterEntry,
    RosterStatus,
    Shift,
    ShiftSwapRequest,
    ShiftSwapStatus,
)
# assert_different_actors: nobody approves their own leave, and nobody signs
# off their own attendance correction.
from apps.rbac.services import assert_different_actors
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.hr")

ZERO = Decimal("0.00")
DAY = Decimal("1.00")
HALF = Decimal("0.50")


class AttendanceError(DomainError):
    code = "attendance_operation_failed"


class LeaveError(DomainError):
    code = "leave_operation_failed"


class InsufficientLeave(LeaveError):
    code = "insufficient_leave_balance"
    status_code = 409


class OverlappingLeave(LeaveError):
    code = "overlapping_leave"
    status_code = 409


# ---------------------------------------------------------------------------
# The calendar
# ---------------------------------------------------------------------------


def is_weekly_off(day) -> bool:
    """Saturday, in Nepal.

    A constant rather than a literal because the one organization that works
    Saturdays needs to change it, and because a hard-coded 5 in six places is
    six places to get wrong.
    """
    return day.weekday() == WEEKLY_HOLIDAY


def holidays_between(start, end, facility=None) -> dict:
    """Holidays in a range, keyed by date.

    Returns a dict rather than a queryset because callers loop over days and
    ask "is this one a holiday?" — a query per day would be a hundred queries
    to compute one month's attendance.
    """
    queryset = Holiday.objects.filter(date__gte=start, date__lte=end)
    if facility is not None:
        queryset = queryset.filter(
            models.Q(facility=facility) | models.Q(facility__isnull=True)
        )
    return {holiday.date: holiday for holiday in queryset}


def working_days_between(start, end, facility=None, half_day: bool = False) -> Decimal:
    """Days that actually cost leave.

    Weekly offs and non-optional holidays are excluded. **Optional holidays
    are not**: a festival some staff take and others work is not a day the
    organization is closed, and excluding it would silently give a day back to
    everybody who booked leave across it.
    """
    holidays = holidays_between(start, end, facility)
    days = ZERO
    day = start
    while day <= end:
        holiday = holidays.get(day)
        if not is_weekly_off(day) and not (holiday and not holiday.is_optional):
            days += DAY
        day += timedelta(days=1)

    if half_day and days > ZERO:
        # A half day only makes sense on a single-day request; on a range it
        # means the first or last day is partial, which is one half day off
        # the total either way.
        days -= HALF
    return days


# ---------------------------------------------------------------------------
# Rostering
# ---------------------------------------------------------------------------


@tenant_atomic_method
def roster(
    employee: Employee,
    shift: Shift,
    date,
    actor=None,
    department=None,
    is_on_call: bool = False,
    notes: str = "",
) -> RosterEntry:
    """Put somebody on a shift.

    Refuses three things, all of which produce a timetable that looks fine on
    screen and is impossible in the ward:

    - a second shift on a day they are already rostered;
    - a shift on a day they have approved leave;
    - a shift that starts before the minimum rest since the last one ended.
    """
    if employee.status not in WORKING_STATUSES:
        raise AttendanceError(
            f"{employee.full_name} is "
            f"{employee.get_status_display().lower()} and cannot be rostered.",
            detail={"status": employee.status},
        )

    clash = RosterEntry.objects.filter(
        employee=employee, date=date
    ).exclude(status=RosterStatus.CANCELLED).first()
    if clash is not None:
        raise AttendanceError(
            f"{employee.full_name} is already on {clash.shift.name} that day.",
            detail={"shift": clash.shift.code, "date": str(date)},
        )

    on_leave = LeaveRequest.objects.filter(
        employee=employee,
        status__in=[LeaveStatus.APPROVED, LeaveStatus.TAKEN],
        starts_on__lte=date,
        ends_on__gte=date,
    ).first()
    if on_leave is not None:
        raise AttendanceError(
            f"{employee.full_name} is on "
            f"{on_leave.leave_type.name.lower()} that day ({on_leave.reference}).",
            detail={"leave": on_leave.reference},
        )

    # Rest between shifts. Checked against the previous day's shift because a
    # night shift ending at 06:00 and a morning shift starting at 08:00 is a
    # two-hour turnaround, which is how mistakes get made on a ward.
    previous = RosterEntry.objects.filter(
        employee=employee, date=date - timedelta(days=1)
    ).exclude(status=RosterStatus.CANCELLED).select_related("shift").first()
    if previous is not None:
        end_hour = Decimal(previous.shift.ends_at.hour) + (
            Decimal(previous.shift.ends_at.minute) / Decimal(60)
        )
        if previous.shift.crosses_midnight:
            start_hour = Decimal(shift.starts_at.hour) + (
                Decimal(shift.starts_at.minute) / Decimal(60)
            )
            rest = start_hour - end_hour
            if rest < shift.minimum_rest_hours:
                raise AttendanceError(
                    f"{employee.full_name} finishes {previous.shift.name} at "
                    f"{previous.shift.ends_at:%H:%M} and would start "
                    f"{shift.name} {rest:.1f} hours later; "
                    f"{shift.minimum_rest_hours} is the minimum.",
                    detail={
                        "rest_hours": str(rest),
                        "minimum": str(shift.minimum_rest_hours),
                    },
                )

    return RosterEntry.objects.create(
        employee=employee,
        shift=shift,
        date=date,
        facility=employee.facility,
        department=department or employee.department,
        is_on_call=is_on_call,
        notes=notes,
        created_by_id=getattr(actor, "uuid", None),
    )


@tenant_atomic_method
def publish_roster(facility, start, end, actor=None) -> dict:
    """Make a draft roster real.

    Publishing is separate from drafting because a roster people have not seen
    cannot be relied on, and rearranging a draft is free while rearranging a
    published one costs somebody their childcare.
    """
    entries = RosterEntry.objects.filter(
        facility=facility, date__gte=start, date__lte=end,
        status=RosterStatus.DRAFT,
    )
    count = entries.update(
        status=RosterStatus.PUBLISHED, published_at=timezone.now()
    )
    record(
        AuditAction.UPDATE,
        entity_type="hr.RosterEntry",
        entity_id=None,
        entity_label=f"Roster published for {facility.code} {start}–{end}",
        metadata={"entries": count},
    )
    return {"published": count, "from": start, "to": end}


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------


def derive_status(attendance: Attendance) -> dict:
    """Work out what a day actually was.

    Computed rather than asserted, and the order of the checks is the whole
    logic:

    1. **Approved leave wins.** It is very often approved after the absence,
       and it is the answer payroll needs.
    2. Then a holiday, then the weekly off — days nobody was expected in.
    3. Only then the times. Without a roster there is no shift to be late
       against, so a day with a check-in and no roster is simply *present*.
    """
    employee = attendance.employee
    day = attendance.date

    on_leave = LeaveRequest.objects.filter(
        employee=employee,
        status__in=[LeaveStatus.APPROVED, LeaveStatus.TAKEN],
        starts_on__lte=day,
        ends_on__gte=day,
    ).exists()
    if on_leave:
        return {
            "status": AttendanceStatus.ON_LEAVE,
            "late_minutes": 0,
            "early_exit_minutes": 0,
            "worked_hours": ZERO,
            "overtime_hours": ZERO,
        }

    holiday = Holiday.objects.filter(date=day).filter(
        models.Q(facility=attendance.facility) | models.Q(facility__isnull=True)
    ).first()
    if holiday and not holiday.is_optional and not attendance.checked_in_at:
        return {
            "status": AttendanceStatus.HOLIDAY,
            "late_minutes": 0, "early_exit_minutes": 0,
            "worked_hours": ZERO, "overtime_hours": ZERO,
        }

    if is_weekly_off(day) and not attendance.checked_in_at:
        return {
            "status": AttendanceStatus.WEEKLY_OFF,
            "late_minutes": 0, "early_exit_minutes": 0,
            "worked_hours": ZERO, "overtime_hours": ZERO,
        }

    if not attendance.checked_in_at:
        return {
            "status": AttendanceStatus.ABSENT,
            "late_minutes": 0, "early_exit_minutes": 0,
            "worked_hours": ZERO, "overtime_hours": ZERO,
        }

    worked = ZERO
    if attendance.checked_out_at:
        seconds = (
            attendance.checked_out_at - attendance.checked_in_at
        ).total_seconds()
        worked = (Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.01"))

    entry = attendance.roster_entry
    if entry is None:
        # No shift, so no scheduled break to deduct. Raw clock time is the
        # honest answer when nobody said when the day was meant to start,
        # end, or pause.
        # No shift to measure against. Present is the honest answer -- calling
        # somebody late when nobody told them when to arrive would be a
        # deduction for the employer's own omission.
        return {
            "status": AttendanceStatus.PRESENT,
            "late_minutes": 0, "early_exit_minutes": 0,
            "worked_hours": worked, "overtime_hours": ZERO,
        }

    shift = entry.shift

    # Deduct the scheduled break. Almost nobody clocks out for lunch, so the
    # clock spans the break and `shift.duration_hours` does not. Comparing the
    # two without this manufactures an hour of overtime for every person,
    # every day -- which the seed made obvious by reporting 2.13 hours of
    # overtime across four ordinary shifts.
    if worked > ZERO and shift.break_minutes:
        worked = max(
            worked - (Decimal(shift.break_minutes) / Decimal(60)), ZERO
        ).quantize(Decimal("0.01"))

    local_in = timezone.localtime(attendance.checked_in_at)
    expected_in = local_in.replace(
        hour=shift.starts_at.hour, minute=shift.starts_at.minute,
        second=0, microsecond=0,
    )
    late = max(int((local_in - expected_in).total_seconds() // 60), 0)
    late = max(late - shift.grace_minutes, 0)

    early = 0
    if attendance.checked_out_at:
        local_out = timezone.localtime(attendance.checked_out_at)
        expected_out = local_out.replace(
            hour=shift.ends_at.hour, minute=shift.ends_at.minute,
            second=0, microsecond=0,
        )
        if shift.crosses_midnight:
            expected_out += timedelta(days=1)
        early = max(int((expected_out - local_out).total_seconds() // 60), 0)

    overtime = max(worked - shift.duration_hours, ZERO)

    if worked < shift.half_day_hours:
        status = AttendanceStatus.HALF_DAY
    elif late > 0:
        status = AttendanceStatus.LATE
    elif early > 0:
        status = AttendanceStatus.EARLY_EXIT
    else:
        status = AttendanceStatus.PRESENT

    return {
        "status": status,
        "late_minutes": late,
        "early_exit_minutes": early,
        "worked_hours": worked,
        "overtime_hours": overtime.quantize(Decimal("0.01")),
    }


def refresh_status(attendance: Attendance) -> Attendance:
    """Recompute and store the cached status."""
    derived = derive_status(attendance)
    for field, value in derived.items():
        setattr(attendance, field, value)
    attendance.save(update_fields=[*derived.keys(), "updated_at"])
    return attendance


@tenant_atomic_method
def check_in(
    employee: Employee,
    actor=None,
    at=None,
    source: str = AttendanceSource.WEB,
    latitude: str = "",
    longitude: str = "",
    within_geofence=None,
    device_reference: str = "",
) -> Attendance:
    """Mark somebody in.

    A second check-in on the same day does not create a second row and does
    not overwrite the first: the earliest arrival is the one that matters, and
    somebody re-scanning their card at lunchtime must not reset their day.
    """
    at = at or timezone.now()
    day = timezone.localdate(at)

    attendance, created = Attendance.objects.get_or_create(
        employee=employee,
        date=day,
        defaults={
            "facility": employee.facility,
            "checked_in_at": at,
            "source": source,
            "latitude": latitude,
            "longitude": longitude,
            "within_geofence": within_geofence,
            "device_reference": device_reference,
            "created_by_id": getattr(actor, "uuid", None),
        },
    )
    if not created and attendance.checked_in_at is None:
        attendance.checked_in_at = at
        attendance.source = source
        attendance.save(update_fields=["checked_in_at", "source", "updated_at"])

    attendance.roster_entry = RosterEntry.objects.filter(
        employee=employee, date=day
    ).exclude(status=RosterStatus.CANCELLED).first()
    attendance.save(update_fields=["roster_entry", "updated_at"])
    return refresh_status(attendance)


@tenant_atomic_method
def check_out(employee: Employee, actor=None, at=None) -> Attendance:
    """Mark somebody out.

    The *latest* departure wins, for the mirror of the reason the earliest
    arrival does: somebody who steps out and comes back has not ended their
    day.
    """
    at = at or timezone.now()
    day = timezone.localdate(at)

    attendance = Attendance.objects.filter(employee=employee, date=day).first()
    if attendance is None:
        raise AttendanceError(
            f"{employee.full_name} has not checked in today.",
            detail={"date": str(day)},
        )
    if attendance.checked_out_at and attendance.checked_out_at >= at:
        return attendance

    attendance.checked_out_at = at
    attendance.save(update_fields=["checked_out_at", "updated_at"])
    return refresh_status(attendance)


@tenant_atomic_method
def request_regularisation(
    attendance: Attendance,
    actor,
    reason: str,
    checked_in_at=None,
    checked_out_at=None,
) -> AttendanceRegularisation:
    """Ask for a day to be corrected.

    The original times are captured on the request, not overwritten on the
    attendance row. A record that silently became "present" is
    indistinguishable from one that always was — and the pattern of
    corrections is exactly what an auditor looks at.
    """
    if not reason.strip():
        raise AttendanceError("A correction must say why.")
    if checked_in_at is None and checked_out_at is None:
        raise AttendanceError("Say which time is wrong.")

    return AttendanceRegularisation.objects.create(
        attendance=attendance,
        requested_by_id=getattr(actor, "uuid", None),
        requested_by_name=getattr(actor, "full_name", "") or "",
        original_checked_in_at=attendance.checked_in_at,
        original_checked_out_at=attendance.checked_out_at,
        original_status=attendance.status,
        requested_checked_in_at=checked_in_at,
        requested_checked_out_at=checked_out_at,
        reason=reason,
        created_by_id=getattr(actor, "uuid", None),
    )


@tenant_atomic_method
def decide_regularisation(
    request: AttendanceRegularisation,
    actor,
    approve: bool,
    notes: str = "",
) -> AttendanceRegularisation:
    """Approve or refuse a correction. Not by the person who asked."""
    if request.status != RegularisationStatus.PENDING:
        raise AttendanceError(
            f"This correction is already {request.get_status_display().lower()}."
        )
    assert_different_actors(
        request.requested_by_id, getattr(actor, "uuid", None),
        "attendance correction",
    )
    if not approve and not notes.strip():
        raise AttendanceError("A refused correction must say why.")

    request.status = (
        RegularisationStatus.APPROVED if approve else RegularisationStatus.REJECTED
    )
    request.decided_by_id = getattr(actor, "uuid", None)
    request.decided_by_name = getattr(actor, "full_name", "") or ""
    request.decided_at = timezone.now()
    request.decision_notes = notes
    request.save()

    if approve:
        attendance = request.attendance
        if request.requested_checked_in_at:
            attendance.checked_in_at = request.requested_checked_in_at
        if request.requested_checked_out_at:
            attendance.checked_out_at = request.requested_checked_out_at
        attendance.is_regularised = True
        attendance.source = AttendanceSource.MANUAL
        attendance.save(
            update_fields=[
                "checked_in_at", "checked_out_at", "is_regularised",
                "source", "updated_at",
            ]
        )
        refresh_status(attendance)

    record(
        AuditAction.APPROVE if approve else AuditAction.REJECT,
        entity_type="hr.Attendance",
        entity_id=request.attendance.uuid,
        entity_label=(
            f"{request.attendance.employee.employee_code} "
            f"{request.attendance.date} corrected"
        ),
        reason=request.reason,
        metadata={
            "from": request.original_status,
            "decided_by": request.decided_by_name,
        },
    )
    return request


def attendance_summary(facility, start, end) -> dict:
    """A period's attendance, by status and by person.

    Late minutes are summed rather than averaged: an average hides the one
    person who is forty minutes late every day behind twenty who are punctual.
    """
    rows = Attendance.objects.filter(
        facility=facility, date__gte=start, date__lte=end
    ).select_related("employee")

    by_status = dict(
        rows.values_list("status")
        .annotate(n=models.Count("id"))
        .values_list("status", "n")
    )
    worked = rows.aggregate(
        hours=models.Sum("worked_hours"),
        overtime=models.Sum("overtime_hours"),
        late=models.Sum("late_minutes"),
    )

    per_person = (
        rows.values("employee__employee_code", "employee__first_name",
                    "employee__last_name")
        .annotate(
            days=models.Count("id"),
            late_minutes=models.Sum("late_minutes"),
            absent=models.Count("id", filter=models.Q(status="absent")),
            overtime=models.Sum("overtime_hours"),
        )
        .order_by("-late_minutes")
    )

    # An open check-in is the commonest defect -- somebody forgot to check out
    # -- and payroll must tell it apart from a genuinely short day.
    open_days = rows.filter(
        checked_in_at__isnull=False, checked_out_at__isnull=True
    ).count()

    return {
        "from": start,
        "to": end,
        "records": rows.count(),
        "by_status": by_status,
        "total_hours": worked["hours"] or ZERO,
        "overtime_hours": worked["overtime"] or ZERO,
        "total_late_minutes": worked["late"] or 0,
        "unclosed_days": open_days,
        "by_employee": list(per_person[:50]),
    }


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------


def leave_year_for(day=None) -> str:
    """Which leave year a date falls in.

    Reuses the Nepali fiscal year, because that is what Nepali employers run
    leave on — Shrawan to Ashadh — rather than the Gregorian calendar year.
    Sharing `fiscal_year_for` also means a change to the fiscal-year rule
    moves both together, which is right: they are the same year.
    """
    return fiscal_year_for(day or timezone.localdate())


def leave_balance(employee: Employee, leave_type: LeaveType, year: str = None) -> dict:
    """What somebody has left, summed from the ledger.

    Never a stored counter. The breakdown by reason is returned alongside the
    number because an employee disputing their balance is asking *why*, and a
    single figure cannot answer that.
    """
    year = year or leave_year_for()
    entries = LeaveLedgerEntry.objects.filter(
        employee=employee, leave_type=leave_type, leave_year=year
    )
    by_reason = dict(
        entries.values_list("reason")
        .annotate(total=models.Sum("days"))
        .values_list("reason", "total")
    )
    balance = entries.aggregate(total=models.Sum("days"))["total"] or ZERO

    # Pending requests are not deducted from the ledger -- nothing has been
    # taken yet -- but somebody planning leave needs to know they have already
    # asked for it.
    pending = LeaveRequest.objects.filter(
        employee=employee, leave_type=leave_type, status=LeaveStatus.PENDING
    ).aggregate(total=models.Sum("working_days"))["total"] or ZERO

    return {
        "leave_type": leave_type.code,
        "leave_type_name": leave_type.name,
        "year": year,
        "balance": balance,
        "pending": pending,
        "available": balance - pending,
        "by_reason": by_reason,
        "entitlement": leave_type.annual_entitlement,
    }


def all_balances(employee: Employee, year: str = None) -> list:
    return [
        leave_balance(employee, leave_type, year)
        for leave_type in LeaveType.objects.filter(is_active=True)
    ]


@tenant_atomic_method
def grant_leave(
    employee: Employee,
    leave_type: LeaveType,
    days,
    actor=None,
    reason: str = LedgerReason.GRANT,
    year: str = None,
    notes: str = "",
) -> LeaveLedgerEntry:
    """Add days to a balance."""
    return LeaveLedgerEntry.objects.create(
        employee=employee,
        leave_type=leave_type,
        leave_year=year or leave_year_for(),
        days=Decimal(str(days)),
        reason=reason,
        recorded_by_id=getattr(actor, "uuid", None),
        recorded_by_name=getattr(actor, "full_name", "") or "",
        notes=notes,
        created_by_id=getattr(actor, "uuid", None),
    )


@tenant_atomic_method
def open_leave_year(employee: Employee, actor=None, year: str = None) -> list:
    """Grant a year's entitlement to one employee.

    Idempotent: an entitlement already granted for the year is not granted
    again. Re-running an annual job must not double everybody's holiday.
    """
    year = year or leave_year_for()
    granted = []
    for leave_type in LeaveType.objects.filter(is_active=True):
        if leave_type.annual_entitlement <= ZERO:
            continue
        already = LeaveLedgerEntry.objects.filter(
            employee=employee, leave_type=leave_type, leave_year=year,
            reason__in=[LedgerReason.GRANT, LedgerReason.OPENING],
        ).exists()
        if already:
            continue
        granted.append(
            grant_leave(
                employee, leave_type, leave_type.annual_entitlement,
                actor=actor, reason=LedgerReason.GRANT, year=year,
                notes=f"Annual entitlement for {year}.",
            )
        )
    return granted


def _next_leave_reference() -> str:
    stem = f"LV{timezone.localdate():%y%m}"
    last = (
        LeaveRequest.all_objects.filter(reference__startswith=stem)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    serial = int(last[len(stem):]) + 1 if last else 1
    return f"{stem}{serial:04d}"


@tenant_atomic_method
def apply_for_leave(
    employee: Employee,
    leave_type: LeaveType,
    starts_on,
    ends_on,
    reason: str,
    actor=None,
    is_half_day: bool = False,
    delegate: Employee = None,
    document_url: str = "",
    contact: str = "",
    allow_unpaid: bool = False,
) -> LeaveRequest:
    """Apply to be away.

    Refuses, in this order:

    - dates the wrong way round;
    - a request that overlaps an existing pending or approved one — two
      overlapping approvals are how somebody ends up on annual *and* sick
      leave for the same Tuesday, and payroll then deducts twice;
    - a request covering no working days at all, which is somebody booking
      leave across a weekend and losing nothing;
    - too little notice, for a type that requires it;
    - insufficient balance, unless the employer allows it as unpaid.
    """
    if ends_on < starts_on:
        raise LeaveError("Leave cannot end before it starts.")

    overlap = LeaveRequest.objects.filter(
        employee=employee,
        status__in=[LeaveStatus.PENDING, LeaveStatus.APPROVED, LeaveStatus.TAKEN],
        starts_on__lte=ends_on,
        ends_on__gte=starts_on,
    ).first()
    if overlap is not None:
        raise OverlappingLeave(
            f"{overlap.reference} already covers "
            f"{overlap.starts_on} to {overlap.ends_on}.",
            detail={"existing": overlap.reference},
        )

    calendar_days = Decimal((ends_on - starts_on).days + 1)
    working = working_days_between(
        starts_on, ends_on, employee.facility, half_day=is_half_day
    )
    if working <= ZERO:
        raise LeaveError(
            "Those dates are all weekly offs or holidays — no leave would be "
            "deducted, so none is needed.",
            detail={"calendar_days": str(calendar_days)},
        )

    if leave_type.minimum_notice_days:
        notice = (starts_on - timezone.localdate()).days
        if notice < leave_type.minimum_notice_days:
            raise LeaveError(
                f"{leave_type.name} needs {leave_type.minimum_notice_days} "
                f"days' notice; this gives {notice}.",
                detail={"notice_days": notice},
            )

    if (
        leave_type.maximum_consecutive_days > ZERO
        and working > leave_type.maximum_consecutive_days
    ):
        raise LeaveError(
            f"{leave_type.name} is limited to "
            f"{leave_type.maximum_consecutive_days} consecutive days.",
            detail={"requested": str(working)},
        )

    if (
        leave_type.requires_document
        and working >= leave_type.document_required_after_days
        and not document_url
    ):
        raise LeaveError(
            f"{leave_type.name} of {working} days needs a supporting document.",
            detail={"threshold": str(leave_type.document_required_after_days)},
        )

    if leave_type.minimum_service_months:
        months = int(employee.years_of_service * 12)
        if months < leave_type.minimum_service_months:
            raise LeaveError(
                f"{leave_type.name} needs "
                f"{leave_type.minimum_service_months} months' service; "
                f"{employee.full_name} has {months}.",
                detail={"service_months": months},
            )

    balance = leave_balance(employee, leave_type)
    is_unpaid = False
    if working > balance["available"]:
        if leave_type.allow_negative_balance or allow_unpaid:
            is_unpaid = True
        else:
            raise InsufficientLeave(
                f"{employee.full_name} has {balance['available']} days of "
                f"{leave_type.name.lower()} available and asked for {working}.",
                detail={
                    "available": str(balance["available"]),
                    "requested": str(working),
                    "pending_elsewhere": str(balance["pending"]),
                },
            )

    request = LeaveRequest.objects.create(
        reference=_next_leave_reference(),
        employee=employee,
        leave_type=leave_type,
        starts_on=starts_on,
        ends_on=ends_on,
        is_half_day=is_half_day,
        calendar_days=calendar_days,
        working_days=working,
        reason=reason,
        contact_during_leave=contact,
        delegate=delegate,
        document_url=document_url,
        is_unpaid=is_unpaid,
        leave_year=leave_year_for(starts_on),
        created_by_id=getattr(actor, "uuid", None),
    )
    record(
        AuditAction.CREATE,
        entity_type="hr.LeaveRequest",
        entity_id=request.uuid,
        entity_label=f"{request.reference} for {employee.employee_code}",
        reason=reason,
        metadata={"days": str(working), "unpaid": is_unpaid},
    )

    # Tell whoever can actually approve it. Raised inside this transaction on
    # purpose: if the application is refused there is no request to approve,
    # and a notification pointing at a row that was rolled back is worse than
    # silence. `notify` writes in its own savepoint, so failing to tell anybody
    # cannot undo the application itself.
    notify(
        source="hr",
        event="leave_awaiting_approval",
        category=NotificationCategory.APPROVAL,
        title=f"{employee.full_name} has applied for {working} day"
              f"{'' if working == 1 else 's'} of {leave_type.name.lower()}",
        body=f"{starts_on:%d %b} to {ends_on:%d %b}. {reason}".strip(),
        link="/time",
        recipients=holders_of(
            "leave.approve",
            facility=employee.facility,
            # The applicant does not approve their own leave. Segregation of
            # duties refuses it anyway; asking them to try is just rude.
            exclude_user_id=getattr(employee, "user_id", None),
        ),
        subject_type="hr.LeaveRequest",
        subject_uuid=request.uuid,
        facility=employee.facility,
        actor_name=employee.full_name,
        dedupe_key=f"leave_approval:{request.uuid}",
    )
    return request


@tenant_atomic_method
def decide_leave(
    request: LeaveRequest,
    actor,
    approve: bool,
    notes: str = "",
) -> LeaveRequest:
    """Approve or refuse. Never your own.

    On approval the balance moves — one ledger entry, negative, referencing
    the request. Unpaid leave still records the days taken but does not deduct
    from a paid balance it was never drawn from.
    """
    if request.status != LeaveStatus.PENDING:
        raise LeaveError(
            f"{request.reference} is already "
            f"{request.get_status_display().lower()}."
        )
    assert_different_actors(
        request.employee.user_id, getattr(actor, "uuid", None), "leave approval"
    )
    if not approve and not notes.strip():
        raise LeaveError("A refused request must say why.")

    request.status = LeaveStatus.APPROVED if approve else LeaveStatus.REJECTED
    request.decided_by_id = getattr(actor, "uuid", None)
    request.decided_by_name = getattr(actor, "full_name", "") or ""
    request.decided_at = timezone.now()
    request.decision_notes = notes
    request.save()

    if approve and not request.is_unpaid:
        LeaveLedgerEntry.objects.create(
            employee=request.employee,
            leave_type=request.leave_type,
            leave_year=request.leave_year or leave_year_for(request.starts_on),
            days=-request.working_days,
            reason=LedgerReason.CONSUMED,
            effective_on=request.starts_on,
            reference_type="hr.LeaveRequest",
            reference_id=request.reference,
            recorded_by_id=getattr(actor, "uuid", None),
            recorded_by_name=request.decided_by_name,
            created_by_id=getattr(actor, "uuid", None),
        )

    if approve:
        # Any attendance already recorded for those days is now wrong. This is
        # exactly why the status is derived rather than asserted -- there is a
        # correct answer to recompute towards.
        for attendance in Attendance.objects.filter(
            employee=request.employee,
            date__gte=request.starts_on,
            date__lte=request.ends_on,
        ):
            refresh_status(attendance)

    record(
        AuditAction.APPROVE if approve else AuditAction.REJECT,
        entity_type="hr.LeaveRequest",
        entity_id=request.uuid,
        entity_label=f"{request.reference} {request.status}",
        reason=notes or request.reason,
    )

    # The approval is no longer waiting on anybody, so the situation that
    # raised it has ended. Resolving is not the same as everybody dismissing
    # it: their copies stay readable, marked as resolved, because "this was
    # approved on Tuesday by Sunita" is worth being able to look up.
    resolve_by_key(
        f"leave_approval:{request.uuid}",
        reason=f"{request.get_status_display()} by "
               f"{request.decided_by_name or 'a manager'}",
    )

    # And tell the applicant, which is the half every leave system forgets.
    # Somebody who applied on Monday should not have to keep opening the
    # screen to find out.
    if request.employee.user_id:
        notify(
            source="hr",
            event="leave_decided",
            category=NotificationCategory.INFORMATION,
            title=f"Your leave request was "
                  f"{request.get_status_display().lower()}",
            body=f"{request.starts_on:%d %b} to {request.ends_on:%d %b}."
                 + (f" {notes}" if notes.strip() else ""),
            link="/self-service",
            recipients=[{
                "id": request.employee.user_id,
                "name": request.employee.full_name,
                "reason": "You applied for this leave",
            }],
            subject_type="hr.LeaveRequest",
            subject_uuid=request.uuid,
            facility=request.employee.facility,
            actor_name=request.decided_by_name,
            dedupe_key=f"leave_decided:{request.uuid}",
        )
    return request


@tenant_atomic_method
def cancel_leave(request: LeaveRequest, actor, reason: str) -> LeaveRequest:
    """Withdraw leave, and put the days back.

    Returning the days is a *new* ledger entry, not a deletion of the old one.
    The balance history has to show that leave was taken and then returned,
    because an employee who cancelled a week's holiday will one day ask where
    it went.
    """
    if request.status not in {LeaveStatus.PENDING, LeaveStatus.APPROVED}:
        raise LeaveError(
            f"{request.reference} is "
            f"{request.get_status_display().lower()} and cannot be cancelled."
        )
    if not reason.strip():
        raise LeaveError("A cancellation must say why.")

    was_approved = request.status == LeaveStatus.APPROVED
    request.status = LeaveStatus.CANCELLED
    request.cancelled_at = timezone.now()
    request.cancellation_reason = reason
    request.save(
        update_fields=[
            "status", "cancelled_at", "cancellation_reason", "updated_at",
        ]
    )

    if was_approved and not request.is_unpaid:
        LeaveLedgerEntry.objects.create(
            employee=request.employee,
            leave_type=request.leave_type,
            leave_year=request.leave_year or leave_year_for(request.starts_on),
            days=request.working_days,
            reason=LedgerReason.CANCELLED,
            reference_type="hr.LeaveRequest",
            reference_id=request.reference,
            recorded_by_id=getattr(actor, "uuid", None),
            recorded_by_name=getattr(actor, "full_name", "") or "",
            notes=reason,
            created_by_id=getattr(actor, "uuid", None),
        )

    for attendance in Attendance.objects.filter(
        employee=request.employee,
        date__gte=request.starts_on,
        date__lte=request.ends_on,
    ):
        refresh_status(attendance)

    return request


def leave_calendar(facility, start, end) -> list:
    """Who is away, and when.

    A department head planning next week needs one view of every absence, not
    a per-person lookup. Returns the requests rather than a day grid: the
    client draws the grid, and the shape of that grid is a display decision.
    """
    requests = LeaveRequest.objects.filter(
        employee__facility=facility,
        status__in=[LeaveStatus.APPROVED, LeaveStatus.TAKEN, LeaveStatus.PENDING],
        starts_on__lte=end,
        ends_on__gte=start,
    ).select_related("employee", "leave_type", "employee__department")

    return [
        {
            "reference": request.reference,
            "employee_code": request.employee.employee_code,
            "employee_name": request.employee.full_name,
            "department": (
                request.employee.department.name
                if request.employee.department else ""
            ),
            "leave_type": request.leave_type.name,
            "colour": request.leave_type.colour,
            "starts_on": request.starts_on,
            "ends_on": request.ends_on,
            "working_days": request.working_days,
            "status": request.status,
            "is_unpaid": request.is_unpaid,
            "delegate": (
                request.delegate.full_name if request.delegate else ""
            ),
        }
        for request in requests.order_by("starts_on")
    ]


def request_shift_swap(
    requester_entry: RosterEntry,
    target_employee: Employee,
    target_entry: RosterEntry | None,
    reason: str,
    actor,
) -> ShiftSwapRequest:
    """Propose a shift swap or shift cover to a colleague."""
    requester = requester_entry.employee
    if requester.pk == target_employee.pk:
        raise AttendanceError("You cannot swap a shift with yourself.")

    if requester_entry.status != RosterStatus.PUBLISHED:
        raise AttendanceError("Only published roster entries can be swapped.")

    if target_entry is not None:
        if target_entry.employee_id != target_employee.pk:
            raise AttendanceError(
                "The target shift entry does not belong to the selected colleague."
            )
        if target_entry.status != RosterStatus.PUBLISHED:
            raise AttendanceError(
                "The target colleague's shift must be published."
            )

    if ShiftSwapRequest.objects.filter(
        requester_entry=requester_entry,
        status__in=[ShiftSwapStatus.PENDING_PEER, ShiftSwapStatus.PENDING_MANAGER],
    ).exists():
        raise AttendanceError(
            "There is already an active swap request for this shift."
        )

    swap = ShiftSwapRequest.objects.create(
        requester=requester,
        requester_entry=requester_entry,
        target_employee=target_employee,
        target_entry=target_entry,
        reason=reason.strip(),
        status=ShiftSwapStatus.PENDING_PEER,
    )
    return swap


def peer_decide_shift_swap(
    swap: ShiftSwapRequest,
    actor,
    accept: bool,
    notes: str = "",
) -> ShiftSwapRequest:
    """The target colleague accepts or declines the proposed swap."""
    if swap.status != ShiftSwapStatus.PENDING_PEER:
        raise AttendanceError(
            f"Swap request is {swap.status}, not pending colleague acceptance."
        )

    target_emp = Employee.for_user(actor.uuid)
    if target_emp and target_emp.pk != swap.target_employee_id:
        raise AttendanceError(
            "Only the targeted colleague may accept or decline this swap."
        )

    swap.peer_decided_at = timezone.now()
    swap.peer_notes = notes.strip()
    if accept:
        swap.status = ShiftSwapStatus.PENDING_MANAGER
    else:
        swap.status = ShiftSwapStatus.REJECTED_PEER
    swap.save()
    return swap


def manager_decide_shift_swap(
    swap: ShiftSwapRequest,
    actor,
    approve: bool,
    notes: str = "",
) -> ShiftSwapRequest:
    """A manager approves or rejects the shift swap."""
    if swap.status != ShiftSwapStatus.PENDING_MANAGER:
        raise AttendanceError(
            f"Swap request is {swap.status}, not pending manager approval."
        )

    caller_emp = Employee.for_user(actor.uuid)
    if caller_emp and caller_emp.pk in (swap.requester_id, swap.target_employee_id):
        raise AttendanceError(
            "You cannot approve a shift swap that involves yourself."
        )

    swap.manager_user_id = actor.uuid
    swap.manager_name = (
        getattr(actor, "get_full_name", lambda: str(actor))() or str(actor)
    )
    swap.manager_notes = notes.strip()
    swap.manager_decided_at = timezone.now()

    if not approve:
        swap.status = ShiftSwapStatus.REJECTED_MANAGER
        swap.save()
        return swap

    swap.status = ShiftSwapStatus.APPROVED
    req_entry = swap.requester_entry
    tgt_entry = swap.target_entry

    if tgt_entry is None:
        req_entry.employee = swap.target_employee
        req_entry.notes = (
            f"{req_entry.notes} (Covered from {swap.requester.employee_code})".strip()
        )
        req_entry.save(update_fields=["employee", "notes", "updated_at"])
    else:
        if req_entry.date == tgt_entry.date:
            req_entry.shift, tgt_entry.shift = tgt_entry.shift, req_entry.shift
            req_entry.notes = (
                f"{req_entry.notes} (Swapped with {swap.target_employee.employee_code})".strip()
            )
            tgt_entry.notes = (
                f"{tgt_entry.notes} (Swapped with {swap.requester.employee_code})".strip()
            )
            req_entry.save(update_fields=["shift", "notes", "updated_at"])
            tgt_entry.save(update_fields=["shift", "notes", "updated_at"])
        else:
            req_entry.employee = swap.target_employee
            tgt_entry.employee = swap.requester
            req_entry.notes = (
                f"{req_entry.notes} (Swapped with {swap.target_employee.employee_code})".strip()
            )
            tgt_entry.notes = (
                f"{tgt_entry.notes} (Swapped with {swap.requester.employee_code})".strip()
            )
            req_entry.save(update_fields=["employee", "notes", "updated_at"])
            tgt_entry.save(update_fields=["employee", "notes", "updated_at"])

    swap.save()
    return swap


def cancel_shift_swap(
    swap: ShiftSwapRequest,
    actor,
) -> ShiftSwapRequest:
    """Requester cancels their swap request."""
    if swap.status not in (
        ShiftSwapStatus.PENDING_PEER,
        ShiftSwapStatus.PENDING_MANAGER,
    ):
        raise AttendanceError(
            f"Cannot cancel a request that is already {swap.status}."
        )
    swap.status = ShiftSwapStatus.CANCELLED
    swap.save(update_fields=["status", "updated_at"])
    return swap
