"""Roster a week, mark attendance, and take leave.

Through the real service layer:

1. Shifts, Nepali public holidays, and leave types with their own rules.
2. A published roster, with double-booking and short rest refused.
3. Check-in and check-out, and the statuses that fall out of them.
4. Saturday treated as the weekly off, which is what Nepal works.
5. Leave applied for, refused for insufficient balance, then approved — and
   the balance moving in the ledger rather than in a counter.
6. Leave approved *after* the absence, and the attendance status changing to
   match, which is the whole reason it is derived.
7. An attendance correction, refused for the person who asked for it.
8. Cancelled leave putting the days back as a new entry, not a deletion.
"""

from datetime import time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.common.exceptions import SegregationOfDutiesViolation
from apps.hr.attendance import (
    AttendanceError,
    InsufficientLeave,
    OverlappingLeave,
    apply_for_leave,
    attendance_summary,
    cancel_leave,
    check_in,
    check_out,
    decide_leave,
    decide_regularisation,
    leave_balance,
    leave_calendar,
    leave_year_for,
    open_leave_year,
    publish_roster,
    request_regularisation,
    roster,
    working_days_between,
)
from apps.hr.models import (
    Attendance,
    Employee,
    EmployeeStatus,
    Holiday,
    LeaveLedgerEntry,
    LeaveRequest,
    LeaveType,
    RosterEntry,
    Shift,
    ShiftType,
)
from apps.identity.models import User
from apps.organization.models import Facility
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

#: (code, name, type, start, end, crosses midnight, grace)
SHIFTS = [
    ("MORNING", "Morning", ShiftType.FIXED, time(8, 0), time(16, 0), False, 10),
    ("EVENING", "Evening", ShiftType.FIXED, time(14, 0), time(22, 0), False, 10),
    ("NIGHT", "Night", ShiftType.NIGHT, time(22, 0), time(6, 0), True, 15),
]

#: (code, name, days a year, paid, carry forward, notice, needs a document)
#:
#: Nepal's Labour Act sets minimums; most employers exceed them. These are the
#: shape of a typical hospital policy rather than the statutory floor.
LEAVE_TYPES = [
    ("annual", "Annual leave", Decimal("18"), True, True, 7, False),
    ("sick", "Sick leave", Decimal("15"), True, False, 0, True),
    ("maternity", "Maternity leave", Decimal("98"), True, False, 30, True),
    ("paternity", "Paternity leave", Decimal("15"), True, False, 7, False),
    ("bereavement", "Bereavement leave", Decimal("13"), True, False, 0, False),
    ("unpaid", "Unpaid leave", Decimal("0"), False, False, 7, False),
]

#: Bikram Sambat festivals do not fall on fixed Gregorian dates, so they are
#: entered rather than computed. These are illustrative placements.
HOLIDAYS = [
    ("Constitution Day", 12, False),
    ("Ghatasthapana", 26, False),
    ("Dashain (Fulpati)", 33, False),
    ("Chhath", 61, True),
]


class Command(BaseCommand):
    help = "Roster a week, mark attendance, and take leave."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"No organization '{slug}'.")

        manager = User.objects.filter(email=f"manager@{slug}.test").first()
        director = User.objects.filter(email=f"owner@{slug}.test").first()
        if not (manager and director):
            raise CommandError("Run `seed_demo` first.")

        with tenant_context(context_for_organization(organization)):
            facility = (
                Facility.objects.filter(facility_type="clinic").first()
                or Facility.objects.first()
            )
            staff = list(
                Employee.objects.filter(
                    facility=facility, status=EmployeeStatus.ACTIVE
                )[:4]
            )
            if len(staff) < 2:
                raise CommandError("Run `seed_hr_demo` first — no staff.")

            self._setup(facility)
            self._roster(staff, manager)
            self._mark(staff, manager)
            self._leave(staff, manager, director)
            self._late_leave(staff, manager, director)
            self._correction(staff, manager, director)
            self._report(facility, staff)

    # -- setup -------------------------------------------------------------

    def _setup(self, facility):
        self.stdout.write(self.style.MIGRATE_HEADING("\n1. Shifts, holidays, leave types"))

        for code, name, kind, start, end, crosses, grace in SHIFTS:
            Shift.objects.update_or_create(
                code=code,
                defaults={
                    "name": name, "shift_type": kind, "starts_at": start,
                    "ends_at": end, "crosses_midnight": crosses,
                    "grace_minutes": grace, "facility": facility,
                },
            )
        night = Shift.objects.get(code="NIGHT")
        self.stdout.write(
            f"   {len(SHIFTS)} shifts; night runs {night.starts_at:%H:%M}–"
            f"{night.ends_at:%H:%M} = {night.duration_hours} paid hours — the "
            "end time is earlier than the start, which is why crossing "
            "midnight is a field rather than something inferred"
        )
        if night.duration_hours <= 0:
            self.stdout.write(self.style.ERROR(
                "   a night shift computed a non-positive duration"
            ))

        today = timezone.localdate()
        for name, offset, optional in HOLIDAYS:
            Holiday.objects.update_or_create(
                date=today + timedelta(days=offset),
                facility=None,
                name=name,
                defaults={"is_optional": optional},
            )
        self.stdout.write(
            f"   {len(HOLIDAYS)} holidays entered — Bikram Sambat festivals "
            "move against the Gregorian calendar, so they cannot be computed"
        )

        for code, name, days, paid, carry, notice, document in LEAVE_TYPES:
            LeaveType.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "annual_entitlement": days,
                    "is_paid": paid,
                    "carry_forward": carry,
                    "max_carry_forward": Decimal("10") if carry else Decimal("0"),
                    "minimum_notice_days": notice,
                    "requires_document": document,
                    "encashable": carry,
                },
            )
        self.stdout.write(f"   {len(LEAVE_TYPES)} leave types")

        # Saturday, demonstrated rather than asserted.
        saturday = today + timedelta(days=(5 - today.weekday()) % 7)
        friday = saturday - timedelta(days=1)
        span = working_days_between(friday, saturday + timedelta(days=1))
        self.stdout.write(
            f"   {friday} to {saturday + timedelta(days=1)} is 3 calendar days "
            f"and {span} working days — {saturday} is a Saturday, which is "
            "Nepal's weekly holiday"
        )
        if span != Decimal("2"):
            self.stdout.write(self.style.ERROR(
                f"   expected 2 working days across a Saturday, got {span}"
            ))

    # -- rostering ---------------------------------------------------------

    def _roster(self, staff, manager):
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. The roster"))
        morning = Shift.objects.get(code="MORNING")
        night = Shift.objects.get(code="NIGHT")
        start = timezone.localdate()

        placed = 0
        for offset in range(7):
            day = start + timedelta(days=offset)
            for index, employee in enumerate(staff):
                shift = night if index == len(staff) - 1 else morning
                try:
                    roster(employee, shift, day, actor=manager)
                    placed += 1
                except AttendanceError:
                    pass          # already rostered from an earlier run
        self.stdout.write(f"   {placed} shifts placed across 7 days")

        # Double booking, refused.
        try:
            roster(staff[0], night, start, actor=manager)
        except AttendanceError as exc:
            self.stdout.write(f"   double booking refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   the same person was rostered twice on one day"
            ))

        # Short rest after a night shift, refused.
        night_worker = staff[-1]
        try:
            RosterEntry.objects.filter(
                employee=night_worker, date=start + timedelta(days=1)
            ).delete()
            roster(night_worker, morning, start + timedelta(days=1), actor=manager)
        except AttendanceError as exc:
            self.stdout.write(f"   short turnaround refused: {exc}")
        else:
            self.stdout.write(self.style.WARNING(
                "   a morning shift was allowed straight after a night shift"
            ))

        result = publish_roster(
            staff[0].facility, start, start + timedelta(days=6), actor=manager
        )
        self.stdout.write(
            f"   {result['published']} entries published — a roster nobody has "
            "seen cannot be relied on"
        )

    # -- attendance --------------------------------------------------------

    def _mark(self, staff, manager):
        self.stdout.write(self.style.MIGRATE_HEADING("\n3. Marking attendance"))
        now = timezone.now()
        today = timezone.localdate()

        # On time.
        punctual = staff[0]
        arrival = timezone.localtime(now).replace(hour=8, minute=2, second=0)
        record = check_in(punctual, actor=punctual, at=arrival, source="biometric")
        record = check_out(punctual, at=arrival.replace(hour=16, minute=10))
        self.stdout.write(
            f"   {punctual.full_name}: in 08:02, out 16:10 -> "
            f"{record.status} ({record.worked_hours}h, "
            f"{record.late_minutes} late)"
        )

        # Late beyond the grace period.
        latecomer = staff[1]
        arrival = timezone.localtime(now).replace(hour=8, minute=47, second=0)
        check_in(latecomer, actor=latecomer, at=arrival, source="mobile")
        record = check_out(latecomer, at=arrival.replace(hour=16, minute=5))
        self.stdout.write(
            f"   {latecomer.full_name}: in 08:47 with a 10-minute grace -> "
            f"{record.status}, {record.late_minutes} minutes late"
        )
        if record.late_minutes != 37:
            self.stdout.write(self.style.ERROR(
                f"   47 minutes past 08:00 less 10 grace should be 37, "
                f"got {record.late_minutes}"
            ))

        # A short day.
        early = staff[2] if len(staff) > 2 else staff[0]
        if early is not punctual:
            arrival = timezone.localtime(now).replace(hour=8, minute=0, second=0)
            check_in(early, actor=early, at=arrival)
            record = check_out(early, at=arrival.replace(hour=11, minute=0))
            self.stdout.write(
                f"   {early.full_name}: three hours worked -> {record.status}"
            )

        # Nobody marked at all.
        absentee = staff[-1]
        Attendance.objects.filter(employee=absentee, date=today).delete()
        blank = Attendance.objects.create(
            employee=absentee, date=today, facility=absentee.facility
        )
        from apps.hr.attendance import refresh_status

        blank = refresh_status(blank)
        self.stdout.write(
            f"   {absentee.full_name}: never checked in -> {blank.status}"
        )

    # -- leave -------------------------------------------------------------

    def _leave(self, staff, manager, director):
        self.stdout.write(self.style.MIGRATE_HEADING("\n4. Leave"))
        employee = staff[0]
        annual = LeaveType.objects.get(code="annual")
        year = leave_year_for()

        open_leave_year(employee, actor=manager)
        balance = leave_balance(employee, annual)
        self.stdout.write(
            f"   {employee.full_name}: {balance['balance']} days of "
            f"{annual.name.lower()} for {year}"
        )

        # Re-running must not double the entitlement.
        open_leave_year(employee, actor=manager)
        again = leave_balance(employee, annual)
        if again["balance"] != balance["balance"]:
            self.stdout.write(self.style.ERROR(
                f"   re-opening the year changed the balance from "
                f"{balance['balance']} to {again['balance']}"
            ))
        else:
            self.stdout.write(
                "   re-opening the leave year is idempotent — an annual job "
                "that ran twice must not double everybody's holiday"
            )

        # More than the balance, refused.
        far = timezone.localdate() + timedelta(days=30)
        try:
            apply_for_leave(
                employee, annual, far, far + timedelta(days=40),
                reason="A very long holiday.", actor=employee,
            )
        except InsufficientLeave as exc:
            self.stdout.write(f"   over-long request refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   more leave was granted than the balance held"
            ))

        request = apply_for_leave(
            employee, annual, far, far + timedelta(days=4),
            reason="Family wedding in Pokhara.", actor=employee,
        )
        self.stdout.write(
            f"   {request.reference}: {request.calendar_days} calendar days "
            f"= {request.working_days} working days deducted"
        )

        # Overlapping, refused.
        try:
            apply_for_leave(
                employee, LeaveType.objects.get(code="sick"),
                far + timedelta(days=2), far + timedelta(days=3),
                reason="Overlapping on purpose.", actor=employee,
            )
        except OverlappingLeave as exc:
            self.stdout.write(f"   overlapping request refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   two overlapping approvals — payroll would deduct twice"
            ))

        # Self-approval, refused.
        if employee.user_id:
            holder = User.objects.filter(uuid=employee.user_id).first()
            try:
                decide_leave(request, actor=holder, approve=True)
            except SegregationOfDutiesViolation as exc:
                self.stdout.write(f"   self-approval refused: {exc}")
            else:
                self.stdout.write(self.style.ERROR(
                    "   somebody approved their own leave"
                ))

        before = leave_balance(employee, annual)["balance"]
        decide_leave(request, actor=manager, approve=True, notes="Approved.")
        after = leave_balance(employee, annual)["balance"]
        self.stdout.write(
            f"   approved: balance {before} -> {after} "
            f"(−{before - after}, from the ledger not a counter)"
        )
        if before - after != request.working_days:
            self.stdout.write(self.style.ERROR(
                f"   deducted {before - after} for a {request.working_days}-day "
                "request"
            ))

        # Cancelling puts the days back as a new entry.
        cancel_leave(request, actor=manager, reason="Wedding postponed.")
        restored = leave_balance(employee, annual)["balance"]
        entries = LeaveLedgerEntry.objects.filter(
            employee=employee, reference_id=request.reference
        ).count()
        self.stdout.write(
            f"   cancelled: balance back to {restored} via {entries} ledger "
            "entries — the deduction is not deleted, because somebody will "
            "one day ask where that week went"
        )

    def _late_leave(self, staff, manager, director):
        """Leave approved after the absence, which is the ordinary case."""
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n5. Leave approved after the fact")
        )
        employee = staff[-1]
        sick = LeaveType.objects.get(code="sick")
        open_leave_year(employee, actor=manager)

        # The most recent working day, not simply today. `apply_for_leave`
        # correctly refuses a request that lands entirely on weekly offs or
        # holidays -- so a scenario hard-coded to `today` passes from Sunday to
        # Friday and fails every Saturday. A seed whose result depends on the
        # day of the week it is run is a seed that will be quietly abandoned
        # the first time it goes red for a reason nobody can reproduce.
        today = timezone.localdate()
        for back in range(0, 14):
            candidate = today - timedelta(days=back)
            if working_days_between(candidate, candidate, employee.facility) > 0:
                break
        else:
            self.stdout.write(self.style.WARNING(
                "   no working day in the last fortnight — skipping"
            ))
            return
        if candidate != today:
            self.stdout.write(
                f"   today is a weekly off, so using {candidate:%a %d %b}"
            )
        today = candidate

        blank = Attendance.objects.filter(employee=employee, date=today).first()
        self.stdout.write(
            f"   {employee.full_name} is marked {blank.status if blank else '—'} "
            f"for {today:%d %b}"
        )

        # A request from an earlier run already covers today, and the
        # overlap check correctly refuses a second. Reuse it rather than
        # crashing: the point being demonstrated is what approval does to the
        # attendance record, not that a duplicate is refused.
        existing = LeaveRequest.objects.filter(
            employee=employee, starts_on__lte=today, ends_on__gte=today
        ).exclude(status__in=["rejected", "cancelled"]).first()
        if existing is not None:
            request = existing
            self.stdout.write(
                f"   {request.reference} from an earlier run already covers "
                "today — reused"
            )
        else:
            request = apply_for_leave(
                employee, sick, today, today,
                reason="Fever; saw a doctor this morning.", actor=employee,
            )
        if request.status == "pending":
            decide_leave(request, actor=manager, approve=True,
                         notes="Certificate seen.")

        blank.refresh_from_db()
        self.stdout.write(
            f"   {request.reference} approved -> today is now {blank.status}"
        )
        if blank.status != "on_leave":
            self.stdout.write(self.style.ERROR(
                "   the attendance record still contradicts the approved leave "
                "— which is exactly what deriving the status is meant to stop"
            ))
        else:
            self.stdout.write(
                "   the day changed without anyone editing it, because the "
                "status is derived rather than asserted"
            )

    def _correction(self, staff, manager, director):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n6. Correcting an attendance record")
        )
        employee = staff[1]
        today = timezone.localdate()
        record = Attendance.objects.filter(employee=employee, date=today).first()
        if record is None:
            self.stdout.write("   nothing to correct")
            return

        original = record.status
        corrected = timezone.localtime(record.checked_in_at).replace(
            hour=8, minute=5
        )
        correction = request_regularisation(
            record, actor=manager,
            reason="Biometric reader was down; arrival witnessed at 08:05.",
            checked_in_at=corrected,
        )
        self.stdout.write(
            f"   correction raised by {correction.requested_by_name}: "
            f"{original} with in-time "
            f"{timezone.localtime(correction.original_checked_in_at):%H:%M}"
        )

        try:
            decide_regularisation(correction, actor=manager, approve=True)
        except SegregationOfDutiesViolation as exc:
            self.stdout.write(f"   self-approval refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   the person who asked for the correction approved it"
            ))

        decide_regularisation(
            correction, actor=director, approve=True,
            notes="Reader outage confirmed in the maintenance log.",
        )
        record.refresh_from_db()
        self.stdout.write(
            f"   approved by {correction.decided_by_name}: {original} -> "
            f"{record.status}, marked as corrected: {record.is_regularised}"
        )
        self.stdout.write(
            "   the original time is kept on the correction, so a corrected "
            "day is visibly corrected rather than silently right"
        )

    # -- reporting ---------------------------------------------------------

    def _report(self, facility, staff):
        self.stdout.write(self.style.MIGRATE_HEADING("\n7. The period"))
        today = timezone.localdate()
        summary = attendance_summary(facility, today - timedelta(days=7), today)
        self.stdout.write(
            f"   {summary['records']} records, {summary['total_hours']}h worked, "
            f"{summary['overtime_hours']}h overtime, "
            f"{summary['total_late_minutes']} minutes late in total"
        )
        for status, count in sorted(summary["by_status"].items()):
            self.stdout.write(f"     {status:<12} {count}")
        if summary["unclosed_days"]:
            self.stdout.write(self.style.WARNING(
                f"   {summary['unclosed_days']} days have a check-in and no "
                "check-out — a short day and a forgotten scan are not the same "
                "thing and payroll must tell them apart"
            ))

        calendar = leave_calendar(
            facility, today - timedelta(days=7), today + timedelta(days=60)
        )
        self.stdout.write(f"   {len(calendar)} absences in the next two months:")
        for row in calendar[:8]:
            self.stdout.write(
                f"     {row['employee_name']:<20} {row['leave_type']:<18} "
                f"{row['starts_on']} → {row['ends_on']} "
                f"({row['working_days']}d, {row['status']})"
            )

        self.stdout.write(self.style.SUCCESS("\nAttendance and leave seeded.\n"))
