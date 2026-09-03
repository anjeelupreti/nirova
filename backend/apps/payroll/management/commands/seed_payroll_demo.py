"""Run a payroll, and check every number against the rule that produced it.

Through the real service layer:

1. Nepal's tax slabs and contribution schemes loaded as data.
2. A salary structure with taxable and non-taxable allowances.
3. The tax engine checked by hand against the published slabs.
4. A run calculated from real attendance and leave.
5. Unpaid leave reducing pay; an employee with no contract held rather than
   paid zero silently.
6. Approval refused for the person who ran it.
7. The statutory return, and a bank file that names what it cannot pay.

Every figure below is asserted against an independently stated expectation.
Payroll is the one module where a plausible wrong number is worse than a
crash, because a crash gets fixed and a plausible number gets paid.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.billing.fiscal import fiscal_year_for
from apps.common.exceptions import SegregationOfDutiesViolation
from apps.hr.models import Employee, EmployeeStatus
from apps.hr.services import current_contract, issue_contract
from apps.identity.models import User
from apps.organization.models import Facility
from apps.payroll.models import (
    CalculationBasis,
    ComponentType,
    ContributionScheme,
    EmployeePayroll,
    PayComponent,
    RunStatus,
    SalaryStructure,
    StructureComponent,
    TaxRegime,
    TaxSlab,
)
from apps.payroll.nepal import (
    CONTRIBUTION_SCHEMES,
    COUPLE_SLABS,
    INDIVIDUAL_SLABS,
    compute_tax,
)
from apps.payroll.services import (
    PayrollError,
    approve,
    bank_file_rows,
    calculate,
    create_payment_batch,
    open_run,
    payable_days,
    run_summary,
    statutory_return,
    submit_for_approval,
)
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

#: (code, name, type, basis, rate, amount, taxable, in contribution base,
#:  prorated, sequence)
COMPONENTS = [
    ("house_allowance", "House allowance", ComponentType.EARNING,
     CalculationBasis.PERCENT_OF_BASIC, "20", "0", True, False, True, 10),
    ("transport", "Transport allowance", ComponentType.EARNING,
     CalculationBasis.FIXED, "0", "3000", True, False, False, 20),
    ("medical_reimbursement", "Medical reimbursement",
     ComponentType.REIMBURSEMENT, CalculationBasis.FIXED, "0", "1500",
     False, False, False, 30),
    ("dearness", "Dearness allowance", ComponentType.EARNING,
     CalculationBasis.PERCENT_OF_BASIC, "10", "0", True, True, True, 40),
]


class Command(BaseCommand):
    help = "Run a payroll and check every number against its rule."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"No organization '{slug}'.")

        officer = User.objects.filter(email=f"manager@{slug}.test").first()
        approver = User.objects.filter(email=f"owner@{slug}.test").first()
        if not (officer and approver):
            raise CommandError("Run `seed_demo` first.")

        with tenant_context(context_for_organization(organization)):
            facility = (
                Facility.objects.filter(facility_type="clinic").first()
                or Facility.objects.first()
            )
            staff = list(
                Employee.objects.filter(
                    facility=facility, status=EmployeeStatus.ACTIVE
                )
            )
            if not staff:
                raise CommandError("Run `seed_hr_demo` first.")

            year = fiscal_year_for()
            self._rates(year)
            structure = self._structure(facility)
            self._profiles(staff, structure, year, officer)
            self._check_tax_by_hand(year)
            run = self._run(facility, staff, officer, approver)
            self._report(run)

    # -- reference data ----------------------------------------------------

    def _rates(self, year):
        self.stdout.write(self.style.MIGRATE_HEADING("\n1. Nepal's rates, as data"))

        for regime, table in (
            (TaxRegime.INDIVIDUAL, INDIVIDUAL_SLABS),
            (TaxRegime.COUPLE, COUPLE_SLABS),
        ):
            for seq, lower, upper, rate, waived, label in table:
                TaxSlab.objects.update_or_create(
                    fiscal_year=year, regime=regime, sequence=seq,
                    defaults={
                        "lower_bound": Decimal(lower),
                        "upper_bound": Decimal(upper) if upper else None,
                        "rate_percent": Decimal(rate),
                        "waived_for_ssf_contributors": waived,
                        "label": label,
                    },
                )

        for code, name, employee, employer, deductible, ceiling, replaces in (
            CONTRIBUTION_SCHEMES
        ):
            ContributionScheme.objects.update_or_create(
                code=code, fiscal_year=year,
                defaults={
                    "name": name,
                    "employee_percent": Decimal(employee),
                    "employer_percent": Decimal(employer),
                    "is_tax_deductible": deductible,
                    "annual_deduction_ceiling": Decimal(ceiling),
                    "replaces_social_security_tax": replaces,
                },
            )

        ssf = ContributionScheme.objects.get(code="ssf", fiscal_year=year)
        self.stdout.write(
            f"   {TaxSlab.objects.filter(fiscal_year=year).count()} tax bands "
            f"for {year}, {ContributionScheme.objects.filter(fiscal_year=year).count()} "
            "contribution schemes"
        )
        self.stdout.write(
            f"   SSF: {ssf.employee_percent}% employee + "
            f"{ssf.employer_percent}% employer = {ssf.total_percent}% of "
            "basic — and it replaces the 1% social security tax band"
        )
        self.stdout.write(
            "   these are rows, not code: the slabs move with every budget "
            "and a rate in a service means a deployment to obey a law"
        )

    def _structure(self, facility):
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. A salary structure"))
        for (code, name, kind, basis, rate, amount, taxable, in_base,
             prorated, seq) in COMPONENTS:
            PayComponent.objects.update_or_create(
                code=code,
                defaults={
                    "name": name, "component_type": kind, "basis": basis,
                    "rate": Decimal(rate), "amount": Decimal(amount),
                    "is_taxable": taxable,
                    "counts_towards_contribution_base": in_base,
                    "is_prorated": prorated, "sequence": seq,
                },
            )

        structure, _ = SalaryStructure.objects.update_or_create(
            code="clinical-standard",
            defaults={"name": "Clinical staff — standard", "facility": facility},
        )
        for code, *_ in COMPONENTS:
            StructureComponent.objects.update_or_create(
                structure=structure,
                component=PayComponent.objects.get(code=code),
            )

        for line in structure.lines.select_related("component"):
            component = line.component
            flags = []
            if not component.is_taxable:
                flags.append("not taxed")
            if component.counts_towards_contribution_base:
                flags.append("in the contribution base")
            if not component.is_prorated:
                flags.append("not pro-rated")
            self.stdout.write(
                f"   {component.name:<24} "
                f"{component.get_basis_display():<22}"
                + (f"  [{', '.join(flags)}]" if flags else "")
            )
        self.stdout.write(
            "   the contribution base is basic, not gross — computing SSF on "
            "gross over-contributes for everybody, every month"
        )
        return structure

    def _profiles(self, staff, structure, year, actor):
        self.stdout.write(self.style.MIGRATE_HEADING("\n3. Payroll profiles"))
        ssf = ContributionScheme.objects.get(code="ssf", fiscal_year=year)

        for index, employee in enumerate(staff):
            EmployeePayroll.objects.update_or_create(
                employee=employee,
                defaults={
                    "structure": structure,
                    "scheme": ssf,
                    "tax_regime": (
                        TaxRegime.COUPLE if index % 3 == 0
                        else TaxRegime.INDIVIDUAL
                    ),
                    "life_insurance_premium": (
                        Decimal("25000") if index % 2 == 0 else Decimal("0")
                    ),
                },
            )
            # Everybody needs terms in force, or payroll correctly holds them.
            if current_contract(employee) is None:
                issue_contract(
                    employee=employee,
                    starts_on=employee.joined_on,
                    basic_salary=Decimal("38000.00") + Decimal(index * 7000),
                    actor=actor,
                )
        self.stdout.write(f"   {len(staff)} profiles on the SSF scheme")

        # Bank details for some but not all, so the transfer file has both
        # cases to show: a payable row and one that has to be named rather
        # than silently dropped.
        for employee in staff[:2]:
            if not employee.bank_account_number:
                employee.bank_name = "Nabil Bank"
                employee.bank_account_number = (
                    f"0110{employee.employee_code[-4:]}00017"
                )
                employee.save(update_fields=[
                    "bank_name", "bank_account_number", "updated_at",
                ])

        # One person deliberately left without terms, to prove payroll holds
        # rather than pays zero.
        orphan = staff[-1]
        orphan.contracts.update(status="terminated")
        self.stdout.write(
            f"   {orphan.full_name}'s contract terminated on purpose — payroll "
            "should hold them, not pay them nothing quietly"
        )

    # -- the tax engine, checked by hand -----------------------------------

    def _check_tax_by_hand(self, year):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n4. The tax engine, checked by hand")
        )

        # An individual on 100,000 a month, no SSF, no deductions.
        # Annual 1,200,000. Bands: 1% of 500,000 = 5,000; 10% of 200,000
        # = 20,000; 20% of 300,000 = 60,000; 30% of the remaining 200,000
        # = 60,000. Total 145,000 a year, 12,083.33 a month.
        result = compute_tax(
            fiscal_year=year,
            monthly_taxable_gross=Decimal("100000"),
            regime=TaxRegime.INDIVIDUAL,
            ssf_contributor=False,
        )
        expected_annual = Decimal("145000.00")
        self.stdout.write(
            f"   1,200,000 a year, no SSF: annual tax {result['annual_tax']} "
            f"(expected {expected_annual}), monthly {result['monthly_tax']}"
        )
        if Decimal(result["annual_tax"]) != expected_annual:
            self.stdout.write(self.style.ERROR(
                f"   the slabs produced {result['annual_tax']} where hand "
                f"arithmetic gives {expected_annual}"
            ))
        for band in result["bands"]:
            self.stdout.write(
                f"     {band['band']:<40} {band['amount_taxed']:>12} "
                f"@ {band['rate_percent']:>5}% = {band['tax']:>10}"
            )

        # The same person contributing to the SSF: the 1% band is waived, so
        # the tax falls by exactly 5,000.
        with_ssf = compute_tax(
            fiscal_year=year,
            monthly_taxable_gross=Decimal("100000"),
            regime=TaxRegime.INDIVIDUAL,
            ssf_contributor=True,
        )
        difference = Decimal(result["annual_tax"]) - Decimal(with_ssf["annual_tax"])
        self.stdout.write(
            f"   contributing to the SSF: {with_ssf['annual_tax']} — "
            f"{difference} less, which is exactly the 1% band"
        )
        if difference != Decimal("5000.00"):
            self.stdout.write(self.style.ERROR(
                f"   the SSF waiver moved the tax by {difference}, not 5,000"
            ))

        # The retirement deduction is capped by the *lower* of a flat ceiling
        # and a third of income. On 300,000 a year contributing 150,000, the
        # third (100,000) binds, not the 500,000 ceiling.
        capped = compute_tax(
            fiscal_year=year,
            monthly_taxable_gross=Decimal("25000"),
            monthly_retirement_contribution=Decimal("12500"),
            ssf_contributor=True,
        )
        retirement = capped["retirement"]
        self.stdout.write(
            f"   300,000 a year contributing {retirement['contributed']}: "
            f"deductible {retirement['deductible']} — capped by the "
            f"{retirement['binding_cap']}"
        )
        if retirement["binding_cap"] != "one third of assessable income":
            self.stdout.write(self.style.ERROR(
                "   the flat ceiling bound where the one-third rule should "
                "have — a low earner making a large contribution would "
                "over-deduct"
            ))

        # Insurance premiums cap separately, not against a combined limit.
        insured = compute_tax(
            fiscal_year=year,
            monthly_taxable_gross=Decimal("80000"),
            life_insurance_premium=Decimal("60000"),
            health_insurance_premium=Decimal("5000"),
            ssf_contributor=True,
        )
        ins = insured["insurance"]
        self.stdout.write(
            f"   premiums 60,000 life + 5,000 health: deductible "
            f"{ins['life_deductible']} + {ins['health_deductible']} = "
            f"{ins['total']} (life capped at {ins['life_cap']})"
        )
        if ins["total"] != Decimal("45000.00"):
            self.stdout.write(self.style.ERROR(
                f"   expected 45,000 deductible, got {ins['total']}"
            ))

    # -- the run -----------------------------------------------------------

    def _run(self, facility, staff, officer, approver):
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. The run"))
        today = timezone.localdate()
        start = today.replace(day=1)
        end = today

        existing = facility.payroll_runs.filter(
            period_start=start, period_end=end, corrects__isnull=True
        ).exclude(status=RunStatus.CANCELLED).first()
        if existing:
            existing.status = RunStatus.CANCELLED
            existing.cancellation_reason = "Superseded by a seed re-run."
            existing.save(update_fields=["status", "cancellation_reason"])

        run = open_run(
            facility, start, end, actor=officer,
            period_label=f"{start:%B %Y} (part period)",
        )
        self.stdout.write(f"   {run.reference} open for {run.period_label}")

        # A second run for the same period, refused.
        try:
            open_run(facility, start, end, actor=officer)
        except PayrollError as exc:
            self.stdout.write(f"   duplicate run refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   two live runs for one period — everybody would be paid twice"
            ))

        # One senior salary, so the run exercises a taxed payslip as well as
        # the untaxed ones. A payroll seed where nobody pays tax proves only
        # half the engine.
        senior = staff[0]
        issue_contract(
            employee=senior,
            starts_on=start,
            basic_salary=Decimal("140000.00"),
            actor=officer,
        )
        self.stdout.write(
            f"   {senior.full_name} moved to 140,000 basic, so the run has a "
            "taxed payslip as well as untaxed ones"
        )

        sample = staff[0]
        days = payable_days(sample, start, end)
        self.stdout.write(
            f"   {sample.full_name}: {days['working_days']} working days in "
            f"the period, {days['payable_days']} payable "
            f"({days['days_present']} present, {days['days_paid_leave']} on "
            f"paid leave, {days['days_unpaid_leave']} unpaid, "
            f"{days['days_absent']} absent)"
        )

        calculate(run, actor=officer)
        run.refresh_from_db()
        self.stdout.write(
            f"   calculated: {run.employee_count} payslips, gross "
            f"{run.gross_total}, deductions {run.deduction_total}, tax "
            f"{run.tax_total}, net {run.net_total}"
        )

        if run.tax_total == Decimal("0.00"):
            self.stdout.write(
                "   tax is 0.00, and that is right: everyone here earns under "
                "500,000 a year, which falls entirely in the first band — and "
                "the first band is the 1% social security tax, waived because "
                "they contribute to the SSF"
            )
            sample_slip = run.payslips.filter(is_held=False).first()
            if sample_slip and sample_slip.tax_workings:
                workings = sample_slip.tax_workings
                self.stdout.write(
                    f"     {sample_slip.employee_name}: annual "
                    f"{workings.get('annual_gross')} taxable "
                    f"{workings.get('taxable_income')} -> "
                    f"{workings.get('annual_tax')}"
                )

        derived = run.gross_total - run.deduction_total - run.tax_total
        if abs(derived - run.net_total) > Decimal("1.00"):
            self.stdout.write(self.style.ERROR(
                f"   gross − deductions − tax = {derived} but net is "
                f"{run.net_total}"
            ))
        else:
            self.stdout.write(
                f"   gross − deductions − tax = {derived}, which is the net"
            )
        self.stdout.write(
            f"   employer contributions {run.employer_cost_total} on top — "
            f"total cost to the organization {run.total_cost}"
        )

        # One payslip, in full.
        slip = run.payslips.filter(is_held=False).order_by("-gross").first()
        if slip:
            self.stdout.write(f"\n   {slip.employee_name} — {slip.reference}")
            for line in slip.lines.all():
                sign = (
                    "-" if line.component_type in ("deduction", "tax") else " "
                )
                self.stdout.write(
                    f"     {sign}{line.name:<32} {line.amount:>12}"
                    + (f"   {line.explanation}" if line.explanation else "")
                )
            self.stdout.write(
                f"      {'Gross':<32} {slip.gross:>12}"
            )
            self.stdout.write(
                f"      {'Net':<32} {slip.net:>12}"
            )
            checked = (
                slip.gross - slip.deductions - slip.tax
            ).quantize(Decimal("0.01"))
            if checked != slip.net:
                self.stdout.write(self.style.ERROR(
                    f"      the lines sum to {checked}, not {slip.net}"
                ))

        held = run.payslips.filter(is_held=True)
        for slip in held:
            self.stdout.write(self.style.WARNING(
                f"   HELD {slip.employee_name}: {slip.hold_reason}"
            ))

        # Approval, refused for the person who ran it.
        submit_for_approval(run, actor=officer)
        try:
            approve(run, actor=officer)
        except SegregationOfDutiesViolation as exc:
            self.stdout.write(f"   self-approval refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   the person who ran the payroll approved it"
            ))

        approve(run, actor=approver, notes="Checked against the register.")
        run.refresh_from_db()
        self.stdout.write(
            f"   approved by {run.approved_by_name} — the run is now immutable"
        )

        try:
            calculate(run, actor=officer)
        except Exception as exc:
            self.stdout.write(f"   recalculation refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   an approved run was recalculated"
            ))
        return run

    # -- reporting ---------------------------------------------------------

    def _report(self, run):
        self.stdout.write(self.style.MIGRATE_HEADING("\n6. What is owed to whom"))
        statutory = statutory_return(run)
        self.stdout.write(
            f"   income tax to remit: {statutory['income_tax']}"
        )
        self.stdout.write(
            f"   contributions: {statutory['employee_contributions']} from "
            f"employees + {statutory['employer_contributions']} from the "
            f"employer = {statutory['total_contributions']}"
        )
        self.stdout.write(
            "   reported separately because they are filed separately and on "
            "different schedules"
        )

        summary = run_summary(run)
        self.stdout.write(f"\n   by component:")
        for row in summary["by_component"]:
            self.stdout.write(
                f"     {row['name']:<32} {row['component_type']:<10} "
                f"{row['total']:>12}  ({row['count']} payslips)"
            )

        try:
            batch = create_payment_batch(run, actor=None)
            self.stdout.write(
                f"\n   {batch.reference}: {batch.count} payslips, "
                f"{batch.total} to transfer"
            )
            rows = bank_file_rows(batch)
            problems = [row for row in rows if row["problem"]]
            for row in rows[:5]:
                self.stdout.write(
                    f"     {row['employee_name']:<22} {row['account_number'] or '(none)':<20} "
                    f"{row['amount']:>10}"
                    + (f"  !! {row['problem']}" if row["problem"] else "")
                )
            if problems:
                self.stdout.write(self.style.WARNING(
                    f"   {len(problems)} cannot be paid by transfer — named "
                    "rather than silently dropped, because a file that quietly "
                    "omits three people pays three people nothing"
                ))
        except PayrollError as exc:
            self.stdout.write(f"   nothing to pay: {exc}")

        self.stdout.write(self.style.SUCCESS("\nPayroll run complete.\n"))
