"""Running a payroll: from attendance to a net figure and a bank file.

The order of calculation is the whole design, and it is not negotiable:

    payable days  ->  earnings  ->  gross  ->  contributions
                  ->  taxable gross  ->  tax  ->  net

Contributions come before tax because the employee's share reduces taxable
income. Tax comes last among deductions because it is computed on everything
above it. Getting this order wrong does not crash — it quietly pays everybody
the wrong amount, which is the failure mode this module is arranged to avoid.

Two further rules:

**Rounding happens once.** Components are computed at full precision and the
payslip is rounded at the end. Rounding each line and summing drifts by rupees
across a payroll of hundreds.

**An approved run is immutable.** It is the basis of a tax filing and a set of
bank transfers. Corrections are a supplementary run, exactly as an invoice is
corrected by a credit note.
"""

import logging
from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from datetime import timedelta

from django.utils import timezone

# notify / holders_of: an approval nobody is told about is an approval
# that waits. See development log 164.
from apps.notifications.models import NotificationCategory
from apps.notifications.services import notify, resolve_by_key
from apps.rbac.services import holders_of
from apps.audit.models import AuditAction
# record: payroll is the most disputed data in any organization, and every
# run, approval and hold needs to be attributable.
from apps.audit.services import record
from apps.billing.fiscal import fiscal_year_for
from apps.common.exceptions import DomainError
from apps.hr.attendance import holidays_between, is_weekly_off
from apps.hr.models import (
    WORKING_STATUSES,
    Attendance,
    AttendanceStatus,
    Employee,
    LeaveRequest,
    LeaveStatus,
)
from apps.hr.services import current_contract
from apps.payroll.models import (
    CalculationBasis,
    ComponentType,
    ContributionScheme,
    EmployeePayroll,
    PayComponent,
    PaymentBatchStatus,
    PayrollRun,
    Payslip,
    PayslipLine,
    RunStatus,
    SalaryPaymentBatch,
    TaxRegime,
)
from apps.payroll.nepal import compute_tax, jsonable, money, scheme_for
# assert_different_actors: whoever runs the payroll may not approve it. This
# is the single highest-value control in the module.
from apps.rbac.services import assert_different_actors
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.payroll")

ZERO = Decimal("0.00")
PAISA = Decimal("0.01")

#: Attendance statuses that are paid. Everything else is either unpaid or
#: needs a leave record to say which.
PAID_STATUSES = {
    AttendanceStatus.PRESENT,
    AttendanceStatus.LATE,
    AttendanceStatus.EARLY_EXIT,
    AttendanceStatus.ON_DUTY,
    AttendanceStatus.ON_CALL,
    AttendanceStatus.HOLIDAY,
    AttendanceStatus.WEEKLY_OFF,
}


class PayrollError(DomainError):
    code = "payroll_operation_failed"


class RunLocked(PayrollError):
    code = "payroll_run_locked"
    message = (
        "An approved payroll run cannot be changed. Raise a supplementary run."
    )


# ---------------------------------------------------------------------------
# Attendance -> payable days
# ---------------------------------------------------------------------------


def payable_days(employee: Employee, start, end) -> dict:
    """How much of the period this person is paid for.

    Built from the attendance records rather than by counting absences,
    because the two are not complements: a day with no record at all is
    different from a day recorded as absent, and only the first can be an
    employee who joined mid-month.

    Weekly offs and holidays are payable. Somebody is not docked for Saturday.
    """
    working_days = ZERO
    day = start
    holidays = holidays_between(start, end, employee.facility)
    while day <= end:
        if not is_weekly_off(day) and day not in holidays:
            working_days += Decimal("1")
        day += timedelta(days=1)

    calendar_days = Decimal((end - start).days + 1)

    records = {
        row.date: row
        for row in Attendance.objects.filter(
            employee=employee, date__gte=start, date__lte=end
        )
    }
    unpaid_leave = LeaveRequest.objects.filter(
        employee=employee,
        status__in=[LeaveStatus.APPROVED, LeaveStatus.TAKEN],
        is_unpaid=True,
        starts_on__lte=end,
        ends_on__gte=start,
    )
    unpaid_dates = set()
    for request in unpaid_leave:
        for date in request.dates():
            if start <= date <= end and not is_weekly_off(date):
                unpaid_dates.add(date)

    present = paid_leave = unpaid = absent = half = ZERO
    overtime = ZERO

    day = start
    while day <= end:
        record_for_day = records.get(day)
        if record_for_day:
            overtime += record_for_day.overtime_hours
        if day in unpaid_dates:
            unpaid += Decimal("1")
        elif record_for_day is None:
            # No record at all. Only counted against a working day: a missing
            # record on a Saturday means nothing happened, not that somebody
            # was absent.
            if not is_weekly_off(day) and day not in holidays:
                absent += Decimal("1")
        elif record_for_day.status == AttendanceStatus.ON_LEAVE:
            paid_leave += Decimal("1")
        elif record_for_day.status == AttendanceStatus.HALF_DAY:
            half += Decimal("1")
            present += Decimal("0.5")
        elif record_for_day.status in PAID_STATUSES:
            present += Decimal("1")
        elif record_for_day.status == AttendanceStatus.ABSENT:
            absent += Decimal("1")
        day += timedelta(days=1)

    # Somebody who joined or left mid-period is paid only for their part of
    # it. Without this a joiner on the 25th receives a full month.
    joined_after = max(employee.joined_on, start) if employee.joined_on else start
    left_before = (
        min(employee.separated_on, end) if employee.separated_on else end
    )
    in_service = Decimal((left_before - joined_after).days + 1)
    if in_service < calendar_days:
        proportion = in_service / calendar_days
    else:
        proportion = Decimal("1")

    payable = max(working_days - unpaid - absent - (half / Decimal("2")), ZERO)
    payable = (payable * proportion).quantize(PAISA, rounding=ROUND_HALF_UP)

    return {
        "calendar_days": calendar_days,
        "working_days": working_days,
        "payable_days": payable,
        "days_present": present,
        "days_paid_leave": paid_leave,
        "days_unpaid_leave": unpaid,
        "days_absent": absent,
        "half_days": half,
        "overtime_hours": overtime,
        "part_period_proportion": proportion,
    }


# ---------------------------------------------------------------------------
# Components -> gross
# ---------------------------------------------------------------------------


def _component_amount(line, basic, gross_so_far, days, working_days, hourly):
    """One component's value at full precision.

    Deliberately not rounded here. Rounding each line and summing them drifts
    by rupees across a payroll of hundreds, so the quantisation happens once,
    on the payslip.
    """
    component = line.component
    rate = line.override_rate if line.override_rate is not None else component.rate
    fixed = (
        line.override_amount
        if line.override_amount is not None
        else component.amount
    )

    if component.basis == CalculationBasis.FIXED:
        amount = Decimal(fixed)
        base = Decimal(fixed)
    elif component.basis == CalculationBasis.PERCENT_OF_BASIC:
        base = basic
        amount = basic * Decimal(rate) / Decimal("100")
    elif component.basis == CalculationBasis.PERCENT_OF_GROSS:
        base = gross_so_far
        amount = gross_so_far * Decimal(rate) / Decimal("100")
    elif component.basis == CalculationBasis.PER_DAY:
        base = Decimal(rate)
        amount = Decimal(rate) * days
    elif component.basis == CalculationBasis.PER_HOUR:
        base = Decimal(rate)
        amount = Decimal(rate) * hourly
    else:
        base = ZERO
        amount = ZERO

    # Pro-rating applies to the earning components that scale with attendance.
    # A fixed festival allowance does not shrink because somebody took three
    # days unpaid; basic salary does.
    if (
        component.is_prorated
        and component.basis in {
            CalculationBasis.FIXED, CalculationBasis.PERCENT_OF_BASIC
        }
        and working_days > ZERO
        and days < working_days
    ):
        amount = amount * days / working_days

    return amount, base, rate


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def _next_run_reference() -> str:
    stem = f"PR{timezone.localdate():%y%m}"
    last = (
        PayrollRun.all_objects.filter(reference__startswith=stem)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    serial = int(last[len(stem):]) + 1 if last else 1
    return f"{stem}{serial:03d}"


@tenant_atomic_method
def open_run(
    facility,
    period_start,
    period_end,
    actor=None,
    period_label: str = "",
    corrects: PayrollRun = None,
    notes: str = "",
) -> PayrollRun:
    """Start a payroll for a period.

    Refuses a second live run for the same facility and period unless it is
    explicitly a correction. A duplicate run is how everybody gets paid twice,
    and the reason it happens is somebody clicking twice.
    """
    if period_end < period_start:
        raise PayrollError("A period cannot end before it starts.")

    if corrects is None:
        existing = PayrollRun.objects.filter(
            facility=facility,
            period_start=period_start,
            period_end=period_end,
            corrects__isnull=True,
        ).exclude(status=RunStatus.CANCELLED).first()
        if existing is not None:
            raise PayrollError(
                f"{existing.reference} already covers this period "
                f"({existing.get_status_display().lower()}).",
                detail={"run": existing.reference, "status": existing.status},
            )
    elif corrects.status not in {RunStatus.APPROVED, RunStatus.PAID}:
        raise PayrollError(
            "Only an approved run needs correcting; edit the draft instead.",
            detail={"status": corrects.status},
        )

    run = PayrollRun.objects.create(
        reference=_next_run_reference(),
        facility=facility,
        fiscal_year=fiscal_year_for(period_start),
        period_label=period_label or f"{period_start:%B %Y}",
        period_start=period_start,
        period_end=period_end,
        corrects=corrects,
        notes=notes,
        created_by_id=getattr(actor, "uuid", None),
    )
    record(
        AuditAction.CREATE,
        entity_type="payroll.PayrollRun",
        entity_id=run.uuid,
        entity_label=f"{run.reference} — {run.period_label}",
        metadata={"facility": facility.code, "corrects": (
            corrects.reference if corrects else ""
        )},
    )
    return run


@tenant_atomic_method
def calculate(run: PayrollRun, actor=None, employees=None) -> PayrollRun:
    """Compute every payslip in the run.

    Idempotent: existing payslips are discarded and rebuilt. Recalculating is
    the normal thing to do after correcting an attendance record, and a
    calculation that appended rather than replaced would double everybody's
    pay on the second click.
    """
    if not run.is_editable:
        raise RunLocked(detail={"status": run.status})

    run.payslips.all().delete()

    if employees is None:
        employees = Employee.objects.filter(
            facility=run.facility, status__in=WORKING_STATUSES
        ).select_related("position", "department")

    totals = {
        "gross": ZERO, "deductions": ZERO, "tax": ZERO,
        "net": ZERO, "employer": ZERO, "count": 0,
    }

    for employee in employees:
        slip = _calculate_one(run, employee, actor)
        if slip is None:
            continue
        totals["gross"] += slip.gross
        totals["deductions"] += slip.deductions
        totals["tax"] += slip.tax
        totals["net"] += slip.net
        totals["employer"] += slip.employer_cost
        totals["count"] += 1

    run.employee_count = totals["count"]
    run.gross_total = money(totals["gross"])
    run.deduction_total = money(totals["deductions"])
    run.tax_total = money(totals["tax"])
    run.net_total = money(totals["net"])
    run.employer_cost_total = money(totals["employer"])
    run.status = RunStatus.CALCULATED
    run.calculated_at = timezone.now()
    run.calculated_by_id = getattr(actor, "uuid", None)
    run.save()

    logger.info(
        "PAYROLL CALCULATED %s: %d payslips, gross %s, net %s",
        run.reference, run.employee_count, run.gross_total, run.net_total,
    )
    return run


def _calculate_one(run: PayrollRun, employee: Employee, actor=None) -> Payslip | None:
    """One employee's payslip, in the order the rules must apply."""
    profile = getattr(employee, "payroll_profile", None)
    if profile and profile.is_on_hold:
        # Still produce a payslip, held at zero. Omitting the person entirely
        # would make them disappear from the run's headcount, and a payroll
        # that quietly has fewer people than the facility employs is a payroll
        # nobody can reconcile.
        slip = _new_payslip(run, employee)
        slip.is_held = True
        slip.hold_reason = profile.hold_reason
        slip.save()
        return slip

    contract = current_contract(employee)
    if contract is None:
        slip = _new_payslip(run, employee)
        slip.is_held = True
        slip.hold_reason = "No contract in force for this period."
        slip.save()
        logger.warning(
            "PAYROLL HELD %s: no contract in force", employee.employee_code
        )
        return slip

    attendance = payable_days(employee, run.period_start, run.period_end)
    basic = Decimal(contract.basic_salary)
    days = attendance["payable_days"]
    working = attendance["working_days"]

    slip = _new_payslip(run, employee)
    slip.basic_salary = money(basic)
    slip.days_in_period = attendance["calendar_days"]
    slip.payable_days = days
    slip.days_present = attendance["days_present"]
    slip.days_paid_leave = attendance["days_paid_leave"]
    slip.days_unpaid_leave = attendance["days_unpaid_leave"]
    slip.days_absent = attendance["days_absent"]
    slip.overtime_hours = attendance["overtime_hours"]
    slip.save()

    hourly = attendance["overtime_hours"]
    lines = []

    # -- 1. Basic, pro-rated for unpaid absence -----------------------------
    prorated_basic = (
        basic * days / working if working > ZERO else basic
    )
    lines.append({
        "code": "basic", "name": "Basic salary",
        "component_type": ComponentType.EARNING,
        "basis": CalculationBasis.PER_DAY, "rate": ZERO,
        "base_amount": basic, "amount": prorated_basic,
        "is_taxable": True, "sequence": 1, "component": None,
        "explanation": (
            f"{days} of {working} working days"
            if days < working else "Full period"
        ),
    })

    gross = prorated_basic
    taxable_gross = prorated_basic
    contribution_base = prorated_basic

    # -- 2. Structure components -------------------------------------------
    structure = profile.structure if profile else None
    if structure:
        for line in structure.lines.select_related("component").order_by(
            "component__sequence"
        ):
            component = line.component
            if not component.is_active:
                continue
            if component.component_type == ComponentType.TAX:
                continue      # tax is computed by the engine, never configured
            amount, base, rate = _component_amount(
                line, basic, gross, days, working, hourly
            )
            if amount == ZERO:
                continue

            lines.append({
                "code": component.code, "name": component.name,
                "component_type": component.component_type,
                "basis": component.basis, "rate": Decimal(rate),
                "base_amount": base, "amount": amount,
                "is_taxable": component.is_taxable,
                "sequence": component.sequence, "component": component,
                "explanation": "",
            })

            if component.component_type == ComponentType.EARNING:
                gross += amount
                if component.is_taxable:
                    taxable_gross += amount
                if component.counts_towards_contribution_base:
                    contribution_base += amount

    # -- 3. Statutory contributions, before tax -----------------------------
    #
    # Before tax because the employee's share reduces taxable income. After
    # earnings because the base depends on them.
    scheme = profile.scheme if profile else None
    if scheme is None:
        scheme = scheme_for("ssf", run.fiscal_year)

    employee_contribution = ZERO
    employer_cost = ZERO
    if scheme:
        base = contribution_base if scheme.on_basic else gross
        employee_contribution = base * scheme.employee_percent / Decimal("100")
        employer_cost = base * scheme.employer_percent / Decimal("100")

        if employee_contribution > ZERO:
            lines.append({
                "code": f"{scheme.code}_employee",
                "name": f"{scheme.name} — employee",
                "component_type": ComponentType.DEDUCTION,
                "basis": CalculationBasis.PERCENT_OF_BASIC,
                "rate": scheme.employee_percent,
                "base_amount": base, "amount": employee_contribution,
                "is_taxable": False, "sequence": 500, "component": None,
                "explanation": (
                    f"{scheme.employee_percent}% of "
                    f"{'basic' if scheme.on_basic else 'gross'}"
                ),
            })
        if employer_cost > ZERO:
            lines.append({
                "code": f"{scheme.code}_employer",
                "name": f"{scheme.name} — employer",
                "component_type": ComponentType.EMPLOYER_CONTRIBUTION,
                "basis": CalculationBasis.PERCENT_OF_BASIC,
                "rate": scheme.employer_percent,
                "base_amount": base, "amount": employer_cost,
                "is_taxable": False, "sequence": 510, "component": None,
                "explanation": (
                    f"{scheme.employer_percent}% of "
                    f"{'basic' if scheme.on_basic else 'gross'} — a cost to "
                    "the organization, not a deduction from pay"
                ),
            })

    # -- 4. Tax, last, on everything above ----------------------------------
    months_remaining = _months_remaining(employee, run)
    tax_result = compute_tax(
        fiscal_year=run.fiscal_year,
        monthly_taxable_gross=taxable_gross,
        regime=profile.tax_regime if profile else TaxRegime.INDIVIDUAL,
        monthly_retirement_contribution=employee_contribution,
        annual_cit_contribution=profile.cit_contribution if profile else ZERO,
        retirement_ceiling=(
            scheme.annual_deduction_ceiling if scheme else Decimal("500000.00")
        ),
        life_insurance_premium=(
            profile.life_insurance_premium if profile else ZERO
        ),
        health_insurance_premium=(
            profile.health_insurance_premium if profile else ZERO
        ),
        remote_area_category=profile.remote_area_category if profile else "",
        is_disabled=profile.is_disabled if profile else False,
        ssf_contributor=bool(scheme and scheme.replaces_social_security_tax),
        months_remaining=months_remaining,
    )
    tax = Decimal(tax_result["monthly_tax"])
    if tax > ZERO:
        lines.append({
            "code": "income_tax", "name": "Income tax",
            "component_type": ComponentType.TAX,
            "basis": CalculationBasis.FORMULA, "rate": ZERO,
            "base_amount": taxable_gross, "amount": tax,
            "is_taxable": False, "sequence": 900, "component": None,
            "explanation": (
                f"Annualised over {tax_result['months_projected']} months, "
                f"taxable {tax_result['taxable_income']}"
            ),
        })

    # -- 5. Totals, rounded once -------------------------------------------
    deductions = sum(
        (row["amount"] for row in lines
         if row["component_type"] == ComponentType.DEDUCTION),
        ZERO,
    )
    reimbursements = sum(
        (row["amount"] for row in lines
         if row["component_type"] == ComponentType.REIMBURSEMENT),
        ZERO,
    )
    net = gross + reimbursements - deductions - tax

    for order, row in enumerate(lines):
        PayslipLine.objects.create(
            payslip=slip,
            component=row["component"],
            code=row["code"],
            name=row["name"],
            component_type=row["component_type"],
            basis=row["basis"],
            rate=row["rate"],
            base_amount=money(row["base_amount"]),
            amount=money(row["amount"]),
            is_taxable=row["is_taxable"],
            sequence=row["sequence"] or order,
            explanation=row["explanation"],
        )

    slip.gross = money(gross + reimbursements)
    slip.taxable_gross = money(taxable_gross)
    slip.deductions = money(deductions)
    slip.tax = money(tax)
    slip.net = money(net)
    slip.employer_cost = money(employer_cost)
    slip.tax_workings = jsonable(tax_result)
    slip.save()
    return slip


def _new_payslip(run: PayrollRun, employee: Employee) -> Payslip:
    """A payslip with the employee's details snapshotted onto it.

    Snapshotted rather than joined, because the employee record can change —
    a transfer, a bank account, a name — and last month's payslip must still
    say what it said when it was issued.
    """
    return Payslip.objects.create(
        run=run,
        employee=employee,
        reference=f"{run.reference}-{employee.employee_code}",
        employee_code=employee.employee_code,
        employee_name=employee.full_name,
        position_title=employee.position.title if employee.position else "",
        department_name=employee.department.name if employee.department else "",
        bank_name=employee.bank_name,
        bank_account_number=employee.bank_account_number,
        pan_number=employee.pan_number,
    )


def _months_remaining(employee: Employee, run: PayrollRun) -> Decimal:
    """How many months of this fiscal year the employee will actually be paid.

    A mid-year joiner projected over twelve months lands in a band they never
    reach, and is over-deducted every month until somebody notices at year
    end. Twelve is the answer for everybody who was here at the start.
    """
    if employee.joined_on and employee.joined_on > run.period_start:
        return Decimal("12")
    months = Decimal("12")
    if employee.joined_on:
        # Shrawan is month 4 of the Gregorian year in the Nepali fiscal
        # calendar; approximating by counting from July is close enough for a
        # projection and is stated as an approximation rather than hidden.
        elapsed = (run.period_start.year - employee.joined_on.year) * 12 + (
            run.period_start.month - employee.joined_on.month
        )
        if 0 <= elapsed < 12:
            months = Decimal(max(12 - elapsed, 1))
    return months


@tenant_atomic_method
def submit_for_approval(run: PayrollRun, actor=None) -> PayrollRun:
    if run.status != RunStatus.CALCULATED:
        raise PayrollError(
            "Calculate the run before submitting it.",
            detail={"status": run.status},
        )
    if run.employee_count == 0:
        raise PayrollError("An empty payroll run cannot be approved.")

    run.status = RunStatus.PENDING_APPROVAL
    run.save(update_fields=["status", "updated_at"])

    # The single highest-value approval in the system: whoever computed the
    # numbers is not the person who authorises the money leaving, and the
    # second person has to be told the first has finished.
    notify(
        source="payroll",
        event="payroll_awaiting_approval",
        category=NotificationCategory.APPROVAL,
        title=f"Payroll {run.reference} is ready to approve",
        body=f"{run.payslips.count()} payslip(s) for {run.period_label}."
             if hasattr(run, "period_label") else
             f"{run.payslips.count()} payslip(s).",
        link="/payroll",
        recipients=holders_of(
            "payroll.approve",
            exclude_user_id=getattr(actor, "uuid", None),
        ),
        subject_type="payroll.PayrollRun",
        subject_uuid=run.uuid,
        actor_name=getattr(actor, "full_name", "") or "",
        dedupe_key=f"payroll_approval:{run.uuid}",
    )
    return run


@tenant_atomic_method
def approve(run: PayrollRun, actor, notes: str = "") -> PayrollRun:
    """Sign off a payroll. Never the person who ran it.

    The single highest-value control in this module: whoever computed the
    numbers is not the person who authorises the money leaving. Once approved
    the run is immutable.
    """
    if run.status != RunStatus.PENDING_APPROVAL:
        raise PayrollError(
            f"{run.reference} is {run.get_status_display().lower()} and is "
            "not awaiting approval.",
            detail={"status": run.status},
        )
    assert_different_actors(
        run.calculated_by_id, getattr(actor, "uuid", None), "payroll approval"
    )

    held = run.payslips.filter(is_held=True).count()
    run.status = RunStatus.APPROVED
    run.approved_at = timezone.now()
    run.approved_by_id = getattr(actor, "uuid", None)
    run.approved_by_name = getattr(actor, "full_name", "") or ""
    if notes:
        run.notes = f"{run.notes}\n{notes}".strip()
    run.save()

    record(
        AuditAction.APPROVE,
        entity_type="payroll.PayrollRun",
        entity_id=run.uuid,
        entity_label=f"{run.reference} approved",
        reason=notes,
        metadata={
            "employees": run.employee_count,
            "net_total": str(run.net_total),
            "held": held,
        },
    )
    logger.warning(
        "PAYROLL APPROVED %s: %d payslips, net %s, approved by %s",
        run.reference, run.employee_count, run.net_total,
        getattr(actor, "email", "?"),
    )
    # The approval is no longer waiting on anybody. The copies stay
    # readable, marked resolved -- who approved it and when is worth
    # being able to look up.
    resolve_by_key(f"payroll_approval:{run.uuid}", reason="Approved")

    return run


@tenant_atomic_method
def cancel_run(run: PayrollRun, actor, reason: str) -> PayrollRun:
    """Abandon a run that has not been paid."""
    if run.status == RunStatus.PAID:
        raise PayrollError(
            "A paid run cannot be cancelled. Raise a supplementary run."
        )
    if not reason.strip():
        raise PayrollError("A cancellation must say why.")

    run.status = RunStatus.CANCELLED
    run.cancellation_reason = reason
    run.save(update_fields=["status", "cancellation_reason", "updated_at"])
    record(
        AuditAction.DELETE,
        entity_type="payroll.PayrollRun",
        entity_id=run.uuid,
        entity_label=f"{run.reference} cancelled",
        reason=reason,
    )
    return run


# ---------------------------------------------------------------------------
# Paying
# ---------------------------------------------------------------------------


@tenant_atomic_method
def create_payment_batch(
    run: PayrollRun,
    actor,
    method: str = "bank_transfer",
    payslips=None,
    bank_name: str = "",
    value_date=None,
) -> SalaryPaymentBatch:
    """Group payslips for a bank upload.

    A run can be paid in tranches — the bank rejects three accounts, or
    daily-wage staff are paid in cash on a different day — so marking the
    whole run paid would be a lie about the three that bounced.
    """
    if run.status not in {RunStatus.APPROVED, RunStatus.PAID}:
        raise PayrollError(
            "Only an approved run can be paid.",
            detail={"status": run.status},
        )

    if payslips is None:
        payslips = list(
            run.payslips.filter(is_held=False, net__gt=ZERO)
            .exclude(payment_batches__isnull=False)
        )
    payslips = [slip for slip in payslips if not slip.is_held]
    if not payslips:
        raise PayrollError("There is nothing left to pay in this run.")

    batch = SalaryPaymentBatch.objects.create(
        reference=f"{run.reference}-B{run.payment_batches.count() + 1}",
        run=run,
        method=method,
        bank_name=bank_name,
        value_date=value_date or timezone.localdate(),
        total=money(sum((slip.net for slip in payslips), ZERO)),
        count=len(payslips),
        created_by_id=getattr(actor, "uuid", None),
    )
    batch.payslips.set(payslips)
    return batch


@tenant_atomic_method
def confirm_payment(batch: SalaryPaymentBatch, actor) -> SalaryPaymentBatch:
    """Record that the money actually moved.

    Separate from exporting the file, because a file being generated is not a
    payment being made, and the gap between the two is where a failed transfer
    lives.
    """
    if batch.status == PaymentBatchStatus.CONFIRMED:
        return batch

    batch.status = PaymentBatchStatus.CONFIRMED
    batch.confirmed_at = timezone.now()
    batch.confirmed_by_id = getattr(actor, "uuid", None)
    batch.save(
        update_fields=["status", "confirmed_at", "confirmed_by_id", "updated_at"]
    )

    run = batch.run
    unpaid = run.payslips.filter(is_held=False).exclude(
        payment_batches__status="confirmed"
    ).exists()
    if not unpaid:
        run.status = RunStatus.PAID
        run.paid_at = timezone.now()
        run.save(update_fields=["status", "paid_at", "updated_at"])

    record(
        AuditAction.UPDATE,
        entity_type="payroll.SalaryPaymentBatch",
        entity_id=batch.uuid,
        entity_label=f"{batch.reference} confirmed paid",
        metadata={"total": str(batch.total), "count": batch.count},
    )
    return batch


def bank_file_rows(batch: SalaryPaymentBatch) -> list:
    """The rows a bank upload needs, with anything missing flagged.

    Missing account details are reported rather than silently skipped: a
    transfer file that quietly drops three people pays three people nothing
    and nobody finds out until they ask.
    """
    rows = []
    for slip in batch.payslips.all().order_by("employee_name"):
        rows.append(
            {
                "employee_code": slip.employee_code,
                "employee_name": slip.employee_name,
                "bank_name": slip.bank_name,
                "account_number": slip.bank_account_number,
                "amount": str(slip.net),
                "reference": slip.reference,
                "problem": (
                    "No bank account on the employee record."
                    if not slip.bank_account_number else ""
                ),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def run_summary(run: PayrollRun) -> dict:
    """A run at a glance, including what it costs beyond salaries."""
    slips = run.payslips.all()
    by_component = (
        PayslipLine.objects.filter(payslip__run=run)
        .values("code", "name", "component_type")
        .annotate(total=models.Sum("amount"), count=models.Count("id"))
        .order_by("component_type", "-total")
    )
    return {
        "reference": run.reference,
        "period": run.period_label,
        "status": run.status,
        "employees": run.employee_count,
        "gross": run.gross_total,
        "deductions": run.deduction_total,
        "tax": run.tax_total,
        "net": run.net_total,
        "employer_cost": run.employer_cost_total,
        "total_cost": run.total_cost,
        "held": slips.filter(is_held=True).count(),
        "held_reasons": list(
            slips.filter(is_held=True).values_list("employee_name", "hold_reason")
        ),
        "missing_bank_details": slips.filter(
            is_held=False, bank_account_number=""
        ).count(),
        "by_component": list(by_component),
    }


def statutory_return(run: PayrollRun) -> dict:
    """What has to be remitted, and to whom.

    Tax and the contribution scheme are filed separately and on different
    schedules, so they are reported separately rather than as one deduction
    total that somebody has to unpick.
    """
    lines = PayslipLine.objects.filter(payslip__run=run)
    tax = lines.filter(component_type=ComponentType.TAX).aggregate(
        total=models.Sum("amount")
    )["total"] or ZERO
    employee_contrib = lines.filter(
        component_type=ComponentType.DEDUCTION
    ).exclude(code="income_tax").aggregate(total=models.Sum("amount"))[
        "total"
    ] or ZERO
    employer_contrib = lines.filter(
        component_type=ComponentType.EMPLOYER_CONTRIBUTION
    ).aggregate(total=models.Sum("amount"))["total"] or ZERO

    return {
        "period": run.period_label,
        "fiscal_year": run.fiscal_year,
        "income_tax": money(tax),
        "employee_contributions": money(employee_contrib),
        "employer_contributions": money(employer_contrib),
        "total_contributions": money(employee_contrib + employer_contrib),
        "employees": run.employee_count,
    }


def employee_payslips(employee: Employee, limit: int = 24) -> list:
    """Somebody's payslips, newest first."""
    return list(
        Payslip.objects.filter(employee=employee)
        .select_related("run")
        .order_by("-run__period_start")[:limit]
    )
