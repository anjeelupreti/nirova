"""Shifts, holidays, attendance and leave.

Kept in a separate module from the employee record because they are a
different kind of data: the employee record changes a few times a career,
these change every day, for everybody. Same app, because they are meaningless
without an employee.

Four decisions.

**Saturday is the weekend.** Nepal's weekly holiday is Saturday, not Sunday,
and a system that assumes otherwise will mark the entire workforce absent once
a week and present on their day off. `WEEKLY_HOLIDAY` is a constant rather
than a literal so the one organization that works Saturdays can change it.

**Attendance stores what happened; the status is derived.** A row records a
check-in and a check-out. Whether that is *present*, *late*, *half day* or
*absent* depends on the shift, the roster, the holiday calendar and any leave
approved later — and leave is very often approved after the fact. Storing
"absent" and then approving leave for that day would leave two records that
disagree, and the wrong one is the one payroll reads.

**Leave balance is a ledger, never a counter.** Accrual, consumption, carry
forward, encashment and adjustment are all entries; the balance is their sum.
This is the same discipline as the stock ledger, for the same reason: a
counter that drifts cannot be reconstructed, and somebody's leave balance is
something they will dispute.

**A leave request that overlaps an approved one is refused.** Two overlapping
approvals are how a person ends up marked both on annual leave and on sick
leave for the same Tuesday, and payroll then deducts twice.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.hr.models import Employee
from apps.organization.models import Department, Facility

ZERO = Decimal("0.00")

#: Python's `weekday()`: Monday is 0, Saturday is 5.
#:
#: Nepal's weekly holiday is Saturday. Assuming Sunday would mark the whole
#: workforce absent every Saturday and present every Sunday, which is not a
#: small cosmetic error -- it is a payroll deduction for everybody, every week.
WEEKLY_HOLIDAY = 5


class ShiftType(models.TextChoices):
    FIXED = "fixed", "Fixed"
    ROTATING = "rotating", "Rotating"
    SPLIT = "split", "Split"
    FLEXIBLE = "flexible", "Flexible"
    NIGHT = "night", "Overnight"
    ON_CALL = "on_call", "On call"


class Shift(BaseModel):
    """A named working pattern.

    `crosses_midnight` is a field rather than something inferred from the
    times, because a night shift's end time is genuinely *earlier* than its
    start and every duration calculation in the system needs to know that
    rather than derive a negative.
    """

    code = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=128)
    shift_type = models.CharField(
        max_length=16, choices=ShiftType.choices, default=ShiftType.FIXED
    )

    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.CASCADE,
        related_name="shifts",
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="shifts",
    )

    starts_at = models.TimeField()
    ends_at = models.TimeField()
    #: A night shift ending at 06:00 ends the *next* day. Stated rather than
    #: inferred, because "ends before it starts" is also what a data-entry
    #: error looks like.
    crosses_midnight = models.BooleanField(default=False)

    break_minutes = models.PositiveSmallIntegerField(default=60)
    #: How late somebody may be before it counts. Zero means any lateness
    #: counts, which is the honest default for a shift where a handover
    #: happens at the start.
    grace_minutes = models.PositiveSmallIntegerField(default=10)
    #: Below this, a day worked counts as a half day.
    half_day_hours = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("4.00")
    )
    #: Minimum rest before the next shift. Enforced by rostering, recorded
    #: here because it is a property of the shift's demands.
    minimum_rest_hours = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("11.00")
    )

    is_active = models.BooleanField(default=True)
    colour = models.CharField(
        max_length=16, blank=True, help_text="For the roster grid."
    )

    class Meta:
        db_table = "hr_shift"
        ordering = ["starts_at", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_shift_code",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.starts_at:%H:%M}–{self.ends_at:%H:%M})"

    @property
    def duration_hours(self) -> Decimal:
        """Paid hours, breaks excluded."""
        start = self.starts_at.hour * 60 + self.starts_at.minute
        end = self.ends_at.hour * 60 + self.ends_at.minute
        if self.crosses_midnight or end <= start:
            end += 24 * 60
        minutes = end - start - self.break_minutes
        return (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.01"))


class Holiday(BaseModel):
    """A day the organization does not work.

    Nepal's public holidays follow the Bikram Sambat calendar and several move
    with the lunar month, so they cannot be computed from a rule — they are
    published each year and entered. `is_optional` covers festival holidays
    that some staff take and others do not, which is common and which payroll
    must not treat as absence.
    """

    name = models.CharField(max_length=128)
    name_nepali = models.CharField(max_length=128, blank=True)
    date = models.DateField(db_index=True)
    #: Null means the whole organization.
    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.CASCADE,
        related_name="holidays",
    )
    is_optional = models.BooleanField(
        default=False,
        help_text="Staff may choose to work; absence is not counted either way.",
    )
    #: Some festivals apply to particular communities. Recorded so a manager
    #: understands why half the ward is in and half is not.
    applies_to = models.CharField(max_length=128, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "hr_holiday"
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(
                fields=["date", "facility", "name"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_holiday",
            )
        ]
        indexes = [models.Index(fields=["date", "facility"])]

    def __str__(self):
        return f"{self.name} — {self.date}"


class RosterStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    CANCELLED = "cancelled", "Cancelled"


class RosterEntry(BaseModel):
    """One person, one day, one shift.

    Published separately from being drafted because a roster people have not
    seen cannot be relied on, and rearranging a draft is free while
    rearranging a published one costs somebody their childcare.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="roster_entries"
    )
    shift = models.ForeignKey(
        Shift, on_delete=models.PROTECT, related_name="roster_entries"
    )
    date = models.DateField(db_index=True)
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, related_name="roster_entries"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="roster_entries",
    )

    status = models.CharField(
        max_length=16, choices=RosterStatus.choices,
        default=RosterStatus.DRAFT, db_index=True,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    is_on_call = models.BooleanField(default=False)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "hr_roster_entry"
        ordering = ["date", "shift__starts_at"]
        constraints = [
            # One shift per person per day. Double-booking is the commonest
            # rostering error and the one that produces an impossible
            # timetable nobody notices until the morning.
            models.UniqueConstraint(
                fields=["employee", "date"],
                condition=models.Q(deleted_at__isnull=True)
                & ~models.Q(status="cancelled"),
                name="uniq_roster_per_employee_per_day",
            )
        ]
        indexes = [
            models.Index(fields=["facility", "date"]),
            models.Index(fields=["employee", "date"]),
        ]

    def __str__(self):
        return f"{self.employee.employee_code} {self.date} {self.shift.code}"


class AttendanceSource(models.TextChoices):
    """How the mark was captured.

    Recorded because trust differs. A biometric scan at the door is evidence;
    a manager typing a time a week later is an assertion, and the two should
    not be indistinguishable when a dispute arises.
    """

    BIOMETRIC = "biometric", "Biometric"
    FACE = "face", "Face recognition"
    RFID = "rfid", "RFID card"
    MOBILE = "mobile", "Mobile app"
    WEB = "web", "Web"
    MANUAL = "manual", "Entered by a manager"
    IMPORTED = "imported", "Imported from a device"


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    LATE = "late", "Late"
    EARLY_EXIT = "early_exit", "Left early"
    HALF_DAY = "half_day", "Half day"
    ABSENT = "absent", "Absent"
    ON_LEAVE = "on_leave", "On leave"
    HOLIDAY = "holiday", "Holiday"
    WEEKLY_OFF = "weekly_off", "Weekly off"
    ON_DUTY = "on_duty", "On duty elsewhere"
    ON_CALL = "on_call", "On call"


class Attendance(BaseModel):
    """What actually happened on one day for one person.

    Stores the facts — when they arrived, when they left, how it was captured.
    The *status* is computed by `apps.hr.attendance.derive_status`, not stored
    as gospel, because leave is routinely approved days after the absence and
    a stored "absent" would then contradict an approved leave record. The
    computed field here is a cache, refreshed whenever anything it depends on
    changes.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="attendance"
    )
    date = models.DateField(db_index=True)
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, related_name="attendance"
    )
    roster_entry = models.ForeignKey(
        RosterEntry, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="attendance",
    )

    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=16, choices=AttendanceSource.choices,
        default=AttendanceSource.WEB,
    )

    #: Where the mark was made, for a mobile check-in. Stored as text rather
    #: than a geo type to avoid a PostGIS dependency for one feature; the
    #: geofence decision is made at capture and recorded in `within_geofence`.
    latitude = models.CharField(max_length=32, blank=True)
    longitude = models.CharField(max_length=32, blank=True)
    within_geofence = models.BooleanField(null=True, blank=True)
    device_reference = models.CharField(max_length=128, blank=True)

    #: A cache of the derived status. Never the source of truth -- see the
    #: class docstring.
    status = models.CharField(
        max_length=16, choices=AttendanceStatus.choices,
        default=AttendanceStatus.ABSENT, db_index=True,
    )
    late_minutes = models.PositiveSmallIntegerField(default=0)
    early_exit_minutes = models.PositiveSmallIntegerField(default=0)
    worked_hours = models.DecimalField(
        max_digits=5, decimal_places=2, default=ZERO
    )
    overtime_hours = models.DecimalField(
        max_digits=5, decimal_places=2, default=ZERO
    )

    #: Set when a manager corrected the record. The original times are kept in
    #: the regularisation request, so a correction is visible as a correction.
    is_regularised = models.BooleanField(default=False)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "hr_attendance"
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "date"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_attendance_per_employee_per_day",
            )
        ]
        indexes = [
            models.Index(fields=["facility", "-date"]),
            models.Index(fields=["employee", "-date"]),
            models.Index(fields=["status", "-date"]),
        ]

    def __str__(self):
        return f"{self.employee.employee_code} {self.date} {self.status}"

    @property
    def is_complete(self) -> bool:
        """Both ends recorded.

        An open check-in is the commonest attendance defect — somebody forgets
        to check out — and payroll must be able to tell it apart from a short
        day.
        """
        return bool(self.checked_in_at and self.checked_out_at)


class RegularisationStatus(models.TextChoices):
    PENDING = "pending", "Awaiting approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class AttendanceRegularisation(BaseModel):
    """A request to correct an attendance record.

    The original times are kept here rather than overwritten on the
    attendance row, so a corrected day is visibly corrected. A record that
    silently became "present" is indistinguishable from one that always was,
    and the pattern of corrections is exactly what an auditor looks at.
    """

    attendance = models.ForeignKey(
        Attendance, on_delete=models.CASCADE, related_name="regularisations"
    )
    requested_by_id = models.UUIDField(null=True, blank=True)
    requested_by_name = models.CharField(max_length=255, blank=True)

    original_checked_in_at = models.DateTimeField(null=True, blank=True)
    original_checked_out_at = models.DateTimeField(null=True, blank=True)
    original_status = models.CharField(max_length=16, blank=True)

    requested_checked_in_at = models.DateTimeField(null=True, blank=True)
    requested_checked_out_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=512)

    status = models.CharField(
        max_length=16, choices=RegularisationStatus.choices,
        default=RegularisationStatus.PENDING, db_index=True,
    )
    decided_by_id = models.UUIDField(null=True, blank=True)
    decided_by_name = models.CharField(max_length=255, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "hr_attendance_regularisation"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return f"Correction to {self.attendance}"


class LeaveUnit(models.TextChoices):
    DAY = "day", "Days"
    HALF_DAY = "half_day", "Half days"
    HOUR = "hour", "Hours"


class LeaveType(BaseModel):
    """A kind of leave, and the rules that govern it.

    Configurable per organization rather than hard-coded, because Nepali
    labour law sets minimums that many employers exceed, and a hospital's
    sick-leave policy is not a clinic's.
    """

    code = models.SlugField(max_length=32, db_index=True)
    name = models.CharField(max_length=128)
    name_nepali = models.CharField(max_length=128, blank=True)
    description = models.TextField(blank=True)

    #: Days granted per year. Zero with `is_unpaid` means unlimited unpaid.
    annual_entitlement = models.DecimalField(
        max_digits=6, decimal_places=2, default=ZERO
    )
    unit = models.CharField(
        max_length=16, choices=LeaveUnit.choices, default=LeaveUnit.DAY
    )
    #: Accrues monthly rather than being granted in full on day one. Nepali
    #: annual leave accrues; sick leave is usually granted whole.
    accrues_monthly = models.BooleanField(default=False)

    is_paid = models.BooleanField(default=True)
    #: Whether an unused balance carries into next year, and how much.
    carry_forward = models.BooleanField(default=False)
    max_carry_forward = models.DecimalField(
        max_digits=6, decimal_places=2, default=ZERO
    )
    #: Whether an unused balance can be paid out instead.
    encashable = models.BooleanField(default=False)

    requires_document = models.BooleanField(
        default=False,
        help_text="A medical certificate, typically, beyond a threshold.",
    )
    document_required_after_days = models.DecimalField(
        max_digits=4, decimal_places=1, default=Decimal("3.0")
    )
    #: Minimum notice. Zero for sick and emergency leave, which by definition
    #: cannot be planned.
    minimum_notice_days = models.PositiveSmallIntegerField(default=0)
    maximum_consecutive_days = models.DecimalField(
        max_digits=6, decimal_places=2, default=ZERO,
        help_text="Zero means no limit.",
    )

    #: Restricts who may take it. Maternity and paternity leave are the
    #: obvious cases; stored as free text rather than an enum because the
    #: eligibility rules differ per employer.
    eligibility = models.CharField(max_length=255, blank=True)
    #: Months of service before it may be taken.
    minimum_service_months = models.PositiveSmallIntegerField(default=0)

    #: Whether the balance may go negative. Some employers allow borrowing
    #: against next year's entitlement; most do not.
    allow_negative_balance = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=100)
    colour = models.CharField(max_length=16, blank=True)

    class Meta:
        db_table = "hr_leave_type"
        ordering = ["display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_leave_type_code",
            )
        ]

    def __str__(self):
        return self.name


class LedgerReason(models.TextChoices):
    """Why a leave balance moved.

    Enumerated because the balance is reconstructed from these and a free-text
    reason cannot be summed, filtered or explained back to the employee who
    disputes it.
    """

    OPENING = "opening", "Opening balance"
    ACCRUAL = "accrual", "Accrued"
    GRANT = "grant", "Granted"
    CONSUMED = "consumed", "Taken"
    CANCELLED = "cancelled", "Returned after cancellation"
    CARRY_FORWARD_IN = "carry_in", "Carried forward in"
    CARRY_FORWARD_OUT = "carry_out", "Carried forward out"
    LAPSED = "lapsed", "Lapsed"
    ENCASHED = "encashed", "Encashed"
    ADJUSTMENT = "adjustment", "Manual adjustment"


class LeaveLedgerEntry(BaseModel):
    """One movement in somebody's leave balance.

    Append-only, exactly like the stock ledger, and for the same reason: a
    stored balance that drifts cannot be reconstructed, and leave is something
    people dispute with a payslip in their hand. Positive adds, negative takes
    away.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="leave_ledger"
    )
    leave_type = models.ForeignKey(
        LeaveType, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    #: The leave year this belongs to, as a Nepali fiscal-year label. Balances
    #: are per year, and an entry that did not say which year it belonged to
    #: could not be carried forward correctly.
    leave_year = models.CharField(max_length=16, db_index=True)

    #: Positive adds to the balance, negative takes from it.
    days = models.DecimalField(max_digits=7, decimal_places=2)
    reason = models.CharField(
        max_length=16, choices=LedgerReason.choices, db_index=True
    )
    effective_on = models.DateField(default=timezone.localdate)

    #: What caused it, for traceability back to the request.
    reference_type = models.CharField(max_length=64, blank=True)
    reference_id = models.CharField(max_length=64, blank=True)

    recorded_by_id = models.UUIDField(null=True, blank=True)
    recorded_by_name = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "hr_leave_ledger"
        ordering = ["-effective_on", "-created_at"]
        indexes = [
            models.Index(fields=["employee", "leave_type", "leave_year"]),
            models.Index(fields=["leave_year", "reason"]),
        ]

    def __str__(self):
        sign = "+" if self.days >= 0 else ""
        return (
            f"{sign}{self.days} {self.leave_type.code} "
            f"for {self.employee.employee_code} ({self.reason})"
        )


class LeaveStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING = "pending", "Awaiting approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"
    TAKEN = "taken", "Taken"


class LeaveRequest(BaseModel):
    """An application to be away.

    `working_days` is computed and frozen at application, not recomputed on
    read. The holiday calendar can gain a festival after somebody applied, and
    a request whose length changed under them — after approval, after payroll
    ran — is worse than one that is slightly stale.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="leave_requests"
    )
    leave_type = models.ForeignKey(
        LeaveType, on_delete=models.PROTECT, related_name="requests"
    )

    starts_on = models.DateField(db_index=True)
    ends_on = models.DateField(db_index=True)
    #: True when only part of the first or last day is taken.
    is_half_day = models.BooleanField(default=False)
    #: Calendar days between the dates, inclusive.
    calendar_days = models.DecimalField(max_digits=6, decimal_places=2)
    #: Days actually deducted: weekends and holidays excluded.
    working_days = models.DecimalField(max_digits=6, decimal_places=2)

    reason = models.CharField(max_length=512)
    contact_during_leave = models.CharField(max_length=128, blank=True)
    #: Who covers. Not a foreign key requirement -- a ward attendant's absence
    #: needs no named delegate -- but a consultant's does.
    delegate = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="leave_delegations",
    )
    document_url = models.URLField(blank=True)

    status = models.CharField(
        max_length=16, choices=LeaveStatus.choices,
        default=LeaveStatus.PENDING, db_index=True,
    )
    applied_at = models.DateTimeField(default=timezone.now)
    decided_by_id = models.UUIDField(null=True, blank=True)
    decided_by_name = models.CharField(max_length=255, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_notes = models.CharField(max_length=512, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=512, blank=True)

    #: True when the balance was insufficient and the employer allowed it
    #: anyway. Payroll needs to know: these days are not paid.
    is_unpaid = models.BooleanField(default=False)
    leave_year = models.CharField(max_length=16, blank=True, db_index=True)

    class Meta:
        db_table = "hr_leave_request"
        ordering = ["-starts_on"]
        indexes = [
            models.Index(fields=["employee", "-starts_on"]),
            models.Index(fields=["status", "starts_on"]),
            models.Index(fields=["starts_on", "ends_on"]),
        ]

    def __str__(self):
        return (
            f"{self.reference}: {self.employee.employee_code} "
            f"{self.leave_type.code} {self.starts_on}–{self.ends_on}"
        )

    @property
    def is_open(self) -> bool:
        return self.status in {LeaveStatus.DRAFT, LeaveStatus.PENDING}

    @property
    def covers_today(self) -> bool:
        today = timezone.localdate()
        return (
            self.status in {LeaveStatus.APPROVED, LeaveStatus.TAKEN}
            and self.starts_on <= today <= self.ends_on
        )

    def dates(self):
        """Every calendar date the request covers."""
        day = self.starts_on
        while day <= self.ends_on:
            yield day
            day += timedelta(days=1)

    def clean(self):
        if self.ends_on < self.starts_on:
            raise ValidationError(
                {"ends_on": "Leave cannot end before it starts."}
            )


class ShiftSwapStatus(models.TextChoices):
    PENDING_PEER = "pending_peer", "Pending colleague acceptance"
    PENDING_MANAGER = "pending_manager", "Pending manager approval"
    APPROVED = "approved", "Approved"
    REJECTED_PEER = "rejected_peer", "Declined by colleague"
    REJECTED_MANAGER = "rejected_manager", "Declined by manager"
    CANCELLED = "cancelled", "Cancelled"


class ShiftSwapRequest(BaseModel):
    """A shift-swap request between two named employees.

    Requires both parties to accept: the target employee must first accept,
    and then their manager must approve before the roster entries are swapped.
    """

    requester = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="outgoing_swap_requests"
    )
    requester_entry = models.ForeignKey(
        RosterEntry, on_delete=models.CASCADE, related_name="outgoing_swaps"
    )
    target_employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="incoming_swap_requests"
    )
    target_entry = models.ForeignKey(
        RosterEntry, null=True, blank=True, on_delete=models.CASCADE,
        related_name="incoming_swaps"
    )
    reason = models.CharField(max_length=512)
    status = models.CharField(
        max_length=20,
        choices=ShiftSwapStatus.choices,
        default=ShiftSwapStatus.PENDING_PEER,
        db_index=True,
    )
    peer_notes = models.CharField(max_length=255, blank=True)
    peer_decided_at = models.DateTimeField(null=True, blank=True)

    manager_user_id = models.UUIDField(null=True, blank=True)
    manager_name = models.CharField(max_length=255, blank=True)
    manager_notes = models.CharField(max_length=255, blank=True)
    manager_decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr_shift_swap"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Swap: {self.requester.employee_code} -> "
            f"{self.target_employee.employee_code} ({self.status})"
        )
