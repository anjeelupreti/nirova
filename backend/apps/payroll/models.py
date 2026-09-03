"""Payroll: what somebody earns, what is deducted, and what they are paid.

The most consequential module in the system to get wrong, and the one where
the rules change most often. Five decisions.

**Rates are data, not code.** Nepal's income-tax slabs, the SSF percentages
and the deduction ceilings change with the budget, every year, and a rate
compiled into a service means a code deployment to obey a law that took effect
last Shrawan. `TaxSlab` and `ContributionScheme` are effective-dated rows.

**An approved payroll run is immutable.** A payslip is a statutory document
and the basis of a tax filing. It is corrected by a supplementary run, never
edited — the same rule as an invoice, and for the same reason.

**Every figure traces to the rule that produced it.** A payslip line records
which component, at what rate, on what base. "Why is my tax 4,200?" has to be
answerable without anybody re-deriving it by hand.

**Gross is rebuilt each run, never carried forward.** Attendance, unpaid leave
and overtime differ every month, so a run reads them fresh. Carrying last
month's gross forward is how an employee keeps being paid after they leave.

**Money is `Decimal`, rounded once, at the end.** Rounding each component
independently and summing them drifts by rupees across a payroll of hundreds.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.hr.models import Employee
from apps.organization.models import Facility

ZERO = Decimal("0.00")


class ComponentType(models.TextChoices):
    """What a line on a payslip is.

    The distinction drives the order of calculation and what each thing is
    taxed on: an earning adds to gross, a deduction comes out of it, and an
    employer contribution never touches the employee's pay at all — it is a
    cost to the organization that must still appear, because it is remitted
    with the same statutory return.
    """

    EARNING = "earning", "Earning"
    DEDUCTION = "deduction", "Deduction"
    EMPLOYER_CONTRIBUTION = "employer", "Employer contribution"
    TAX = "tax", "Tax"
    REIMBURSEMENT = "reimbursement", "Reimbursement"


class CalculationBasis(models.TextChoices):
    """How a component's amount is arrived at."""

    FIXED = "fixed", "Fixed amount"
    PERCENT_OF_BASIC = "percent_basic", "Percentage of basic"
    PERCENT_OF_GROSS = "percent_gross", "Percentage of gross"
    PER_DAY = "per_day", "Per day worked"
    PER_HOUR = "per_hour", "Per hour"
    FORMULA = "formula", "Computed by the engine"


class PayComponent(BaseModel):
    """One named thing that appears on a payslip.

    Configurable rather than hard-coded because two hospitals do not agree on
    what allowances exist, and a customer inventing a "remote posting
    allowance" should not need a migration.
    """

    code = models.SlugField(max_length=32, db_index=True)
    name = models.CharField(max_length=128)
    name_nepali = models.CharField(max_length=128, blank=True)
    component_type = models.CharField(
        max_length=16, choices=ComponentType.choices, db_index=True
    )
    basis = models.CharField(
        max_length=20, choices=CalculationBasis.choices,
        default=CalculationBasis.FIXED,
    )
    #: Used when the basis is a percentage or a rate.
    rate = models.DecimalField(max_digits=9, decimal_places=4, default=ZERO)
    #: Used when the basis is fixed.
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)

    #: Whether income tax is charged on it. A medical reimbursement is not
    #: income; a transport allowance generally is.
    is_taxable = models.BooleanField(default=True)
    #: Whether it counts towards the base that SSF and PF are computed on.
    #: In Nepal those are on *basic* salary, not gross, and getting this wrong
    #: over-contributes for every employee, every month.
    counts_towards_contribution_base = models.BooleanField(default=False)
    #: Whether an unpaid day reduces it. Basic salary is pro-rated; a fixed
    #: festival allowance is not.
    is_prorated = models.BooleanField(default=True)

    #: Lower is calculated first. Tax must run after every earning is known,
    #: so it sits high.
    sequence = models.PositiveSmallIntegerField(default=100)
    is_statutory = models.BooleanField(
        default=False,
        help_text="Required by law; cannot be removed from a structure.",
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_component"
        ordering = ["sequence", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_pay_component_code",
            )
        ]
        indexes = [models.Index(fields=["component_type", "is_active"])]

    def __str__(self):
        return f"{self.name} ({self.get_component_type_display()})"

    @property
    def sign(self) -> int:
        """+1 if it adds to net pay, −1 if it takes away, 0 if neither."""
        if self.component_type in {
            ComponentType.EARNING, ComponentType.REIMBURSEMENT
        }:
            return 1
        if self.component_type in {ComponentType.DEDUCTION, ComponentType.TAX}:
            return -1
        return 0


class SalaryStructure(BaseModel):
    """A named set of components an employee is paid under.

    Assigned to an employee rather than built per person, because a hospital
    pays forty nurses on the same terms and forty copies of one structure is
    forty places for it to diverge.
    """

    code = models.SlugField(max_length=32, db_index=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.CASCADE,
        related_name="salary_structures",
    )
    components = models.ManyToManyField(
        PayComponent, through="StructureComponent",
        related_name="structures",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "payroll_structure"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_salary_structure_code",
            )
        ]

    def __str__(self):
        return self.name


class StructureComponent(BaseModel):
    """One component in a structure, with a structure-specific override.

    The override exists because the same allowance is a different amount at
    two facilities, and duplicating the component to change one number would
    make "how much do we spend on transport allowance?" unanswerable.
    """

    structure = models.ForeignKey(
        SalaryStructure, on_delete=models.CASCADE, related_name="lines"
    )
    component = models.ForeignKey(
        PayComponent, on_delete=models.CASCADE, related_name="structure_lines"
    )
    #: Null means use the component's own rate or amount.
    override_rate = models.DecimalField(
        max_digits=9, decimal_places=4, null=True, blank=True
    )
    override_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    is_optional = models.BooleanField(
        default=False,
        help_text="Applied only when the employee has opted in.",
    )

    class Meta:
        db_table = "payroll_structure_component"
        ordering = ["component__sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["structure", "component"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_component_per_structure",
            )
        ]

    def __str__(self):
        return f"{self.component.code} in {self.structure.code}"


class TaxRegime(models.TextChoices):
    """Which set of slabs applies.

    Nepal taxes an individual and a married couple on different thresholds,
    and the choice is the taxpayer's declaration rather than something the
    system can infer from a marital-status field.
    """

    INDIVIDUAL = "individual", "Individual"
    COUPLE = "couple", "Married, assessed jointly"


class TaxSlab(BaseModel):
    """One band of Nepal's income-tax table, effective-dated.

    Data rather than code because the slabs move with every budget, and a rate
    compiled into a service means a deployment to obey a law that took effect
    last Shrawan.

    The 1% first band is Nepal's social security tax. It is **not charged** to
    an employee contributing to the Social Security Fund — the SSF
    contribution replaces it — which is why `waived_for_ssf_contributors`
    exists rather than the band simply being removed.
    """

    fiscal_year = models.CharField(max_length=16, db_index=True)
    regime = models.CharField(
        max_length=16, choices=TaxRegime.choices, default=TaxRegime.INDIVIDUAL
    )
    sequence = models.PositiveSmallIntegerField(
        help_text="1 is the lowest band."
    )

    #: Annual amounts. Payroll works monthly and annualises, because a
    #: progressive rate applied to a month's pay would put somebody in the
    #: wrong band twelve times over.
    lower_bound = models.DecimalField(max_digits=14, decimal_places=2)
    #: Null for the top band.
    upper_bound = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    rate_percent = models.DecimalField(max_digits=6, decimal_places=3)
    waived_for_ssf_contributors = models.BooleanField(default=False)
    label = models.CharField(max_length=128, blank=True)

    class Meta:
        db_table = "payroll_tax_slab"
        ordering = ["fiscal_year", "regime", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "regime", "sequence"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_tax_slab",
            )
        ]
        indexes = [models.Index(fields=["fiscal_year", "regime"])]

    def __str__(self):
        upper = self.upper_bound if self.upper_bound is not None else "∞"
        return f"{self.fiscal_year} {self.regime}: {self.lower_bound}–{upper} @ {self.rate_percent}%"

    @property
    def width(self) -> Decimal | None:
        if self.upper_bound is None:
            return None
        return self.upper_bound - self.lower_bound

    def clean(self):
        if self.upper_bound is not None and self.upper_bound <= self.lower_bound:
            raise ValidationError(
                {"upper_bound": "A band must end above where it starts."}
            )


class ContributionScheme(BaseModel):
    """A statutory retirement or welfare contribution.

    Nepal has several and an employer is on one of them, not all: the Social
    Security Fund (SSF) replaced the older Provident Fund arrangement for
    employers who enrolled, and both still exist in the field. Effective-dated
    for the same reason as the tax slabs.
    """

    code = models.SlugField(max_length=32, db_index=True)
    name = models.CharField(max_length=128)
    fiscal_year = models.CharField(max_length=16, db_index=True)

    employee_percent = models.DecimalField(
        max_digits=6, decimal_places=3, default=ZERO
    )
    employer_percent = models.DecimalField(
        max_digits=6, decimal_places=3, default=ZERO
    )
    #: What the percentage is *of*. In Nepal, basic salary — not gross.
    #: Computing SSF on gross over-contributes for every employee every month
    #: and the error compounds with every allowance the employer adds.
    on_basic = models.BooleanField(default=True)

    #: The employee's share reduces taxable income, up to a ceiling.
    is_tax_deductible = models.BooleanField(default=True)
    #: Annual ceiling on the deduction, in rupees. Nepal also caps it at a
    #: third of assessable income, which the engine applies alongside this.
    annual_deduction_ceiling = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )
    #: Contributing to this replaces the 1% social security tax band.
    replaces_social_security_tax = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_contribution_scheme"
        ordering = ["fiscal_year", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code", "fiscal_year"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_scheme_per_year",
            )
        ]

    def __str__(self):
        return f"{self.name} {self.fiscal_year}"

    @property
    def total_percent(self) -> Decimal:
        return self.employee_percent + self.employer_percent


class EmployeePayroll(BaseModel):
    """How one employee is paid: structure, scheme, and their declarations.

    Separate from `EmploymentContract` because the contract is what was
    agreed and this is how it is operated. A tax regime declaration and an
    insurance premium change without the contract changing.
    """

    employee = models.OneToOneField(
        Employee, on_delete=models.CASCADE, related_name="payroll_profile"
    )
    structure = models.ForeignKey(
        SalaryStructure, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="employees",
    )
    scheme = models.ForeignKey(
        ContributionScheme, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="employees",
    )
    tax_regime = models.CharField(
        max_length=16, choices=TaxRegime.choices, default=TaxRegime.INDIVIDUAL
    )

    #: Declared deductible premiums. Nepal allows a life-insurance premium and
    #: a health-insurance premium against taxable income, each capped.
    life_insurance_premium = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    health_insurance_premium = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    #: Voluntary Citizen Investment Trust contribution, also deductible within
    #: the same overall retirement ceiling.
    cit_contribution = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )

    #: True for a remote-area posting, which attracts a further allowance
    #: against taxable income under Nepali rules.
    remote_area_category = models.CharField(max_length=8, blank=True)
    is_disabled = models.BooleanField(
        default=False,
        help_text="Attracts an additional exemption under Nepali tax rules.",
    )

    #: Set when payroll must not run for this person — a leaver whose final
    #: settlement is pending, or a dispute.
    is_on_hold = models.BooleanField(default=False)
    hold_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "payroll_employee_profile"

    def __str__(self):
        return f"Payroll profile for {self.employee.employee_code}"


class RunStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    CALCULATED = "calculated", "Calculated"
    PENDING_APPROVAL = "pending_approval", "Awaiting approval"
    APPROVED = "approved", "Approved"
    PAID = "paid", "Paid"
    CANCELLED = "cancelled", "Cancelled"


class PayrollRun(BaseModel):
    """One payroll, for one facility, for one period.

    Recalculating is free while the run is a draft and forbidden once it is
    approved. An approved run is the basis of a tax filing and a set of bank
    transfers; correcting it means a supplementary run, exactly as an invoice
    is corrected by a credit note.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="payroll_runs"
    )
    #: Nepali fiscal year and month, as labels. Payroll in Nepal runs on the
    #: Bikram Sambat month, and storing only Gregorian dates would make a
    #: statutory return impossible to reconcile.
    fiscal_year = models.CharField(max_length=16, db_index=True)
    period_label = models.CharField(
        max_length=32, help_text="e.g. 'Shrawan 2083'."
    )
    period_start = models.DateField()
    period_end = models.DateField()

    status = models.CharField(
        max_length=20, choices=RunStatus.choices,
        default=RunStatus.DRAFT, db_index=True,
    )
    #: Supplementary runs correct an approved one rather than editing it.
    corrects = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="corrections",
    )

    calculated_at = models.DateTimeField(null=True, blank=True)
    calculated_by_id = models.UUIDField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_by_name = models.CharField(max_length=255, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    employee_count = models.PositiveIntegerField(default=0)
    gross_total = models.DecimalField(
        max_digits=16, decimal_places=2, default=ZERO
    )
    deduction_total = models.DecimalField(
        max_digits=16, decimal_places=2, default=ZERO
    )
    tax_total = models.DecimalField(
        max_digits=16, decimal_places=2, default=ZERO
    )
    net_total = models.DecimalField(
        max_digits=16, decimal_places=2, default=ZERO
    )
    #: What the organization pays on top of salaries. Not part of net pay, and
    #: reported because it is remitted with the same return.
    employer_cost_total = models.DecimalField(
        max_digits=16, decimal_places=2, default=ZERO
    )

    notes = models.TextField(blank=True)
    cancellation_reason = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "payroll_run"
        ordering = ["-period_start"]
        constraints = [
            # One live run per facility per period. A second would double
            # everybody's pay, and the reason it happens is somebody clicking
            # twice.
            models.UniqueConstraint(
                fields=["facility", "period_start", "period_end"],
                condition=models.Q(deleted_at__isnull=True)
                & ~models.Q(status="cancelled")
                & models.Q(corrects__isnull=True),
                name="uniq_payroll_run_per_period",
            )
        ]
        indexes = [
            models.Index(fields=["facility", "-period_start"]),
            models.Index(fields=["status", "-period_start"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.period_label}"

    @property
    def is_editable(self) -> bool:
        return self.status in {RunStatus.DRAFT, RunStatus.CALCULATED}

    @property
    def total_cost(self) -> Decimal:
        """What the organization actually spends: gross plus employer share."""
        return self.gross_total + self.employer_cost_total


class Payslip(BaseModel):
    """One employee's pay for one period.

    The attendance figures are snapshotted rather than joined, because the
    attendance record can be corrected next week and last month's payslip must
    still explain itself with the numbers it was calculated from.
    """

    run = models.ForeignKey(
        PayrollRun, on_delete=models.CASCADE, related_name="payslips"
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="payslips"
    )
    reference = models.CharField(max_length=32, db_index=True)

    #: Snapshots. See the class docstring.
    employee_code = models.CharField(max_length=32)
    employee_name = models.CharField(max_length=255)
    position_title = models.CharField(max_length=255, blank=True)
    department_name = models.CharField(max_length=255, blank=True)
    bank_name = models.CharField(max_length=128, blank=True)
    bank_account_number = models.CharField(max_length=64, blank=True)
    pan_number = models.CharField(max_length=20, blank=True)

    #: What the pay was calculated from.
    basic_salary = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO
    )
    payable_days = models.DecimalField(
        max_digits=6, decimal_places=2, default=ZERO
    )
    days_in_period = models.DecimalField(
        max_digits=6, decimal_places=2, default=ZERO
    )
    days_present = models.DecimalField(
        max_digits=6, decimal_places=2, default=ZERO
    )
    days_paid_leave = models.DecimalField(
        max_digits=6, decimal_places=2, default=ZERO
    )
    days_unpaid_leave = models.DecimalField(
        max_digits=6, decimal_places=2, default=ZERO
    )
    days_absent = models.DecimalField(
        max_digits=6, decimal_places=2, default=ZERO
    )
    overtime_hours = models.DecimalField(
        max_digits=8, decimal_places=2, default=ZERO
    )

    gross = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    taxable_gross = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO
    )
    deductions = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO
    )
    tax = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    net = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    employer_cost = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO
    )

    #: How the tax was arrived at, kept so "why is my tax this?" is answerable
    #: from the payslip alone rather than by re-deriving it.
    tax_workings = models.JSONField(default=dict, blank=True)

    is_held = models.BooleanField(default=False)
    hold_reason = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "payroll_payslip"
        ordering = ["employee_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "employee"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_payslip_per_employee_per_run",
            )
        ]
        indexes = [
            models.Index(fields=["employee", "-created_at"]),
            models.Index(fields=["run", "employee_name"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.employee_name}"


class PayslipLine(BaseModel):
    """One component on one payslip, with how it was arrived at.

    `basis`, `rate` and `base_amount` are stored alongside the amount so the
    figure can be explained rather than merely stated. "10% of 45,000" answers
    a question that "4,500" does not.
    """

    payslip = models.ForeignKey(
        Payslip, on_delete=models.CASCADE, related_name="lines"
    )
    component = models.ForeignKey(
        PayComponent, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="payslip_lines",
    )
    #: Snapshot, because a component can be renamed or deactivated.
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    component_type = models.CharField(max_length=16, db_index=True)

    basis = models.CharField(max_length=20, blank=True)
    rate = models.DecimalField(max_digits=9, decimal_places=4, default=ZERO)
    base_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)

    is_taxable = models.BooleanField(default=True)
    sequence = models.PositiveSmallIntegerField(default=100)
    explanation = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "payroll_payslip_line"
        ordering = ["sequence", "name"]
        indexes = [models.Index(fields=["payslip", "component_type"])]

    def __str__(self):
        return f"{self.name}: {self.amount}"


class PaymentBatchStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    EXPORTED = "exported", "Exported to the bank"
    CONFIRMED = "confirmed", "Confirmed paid"
    FAILED = "failed", "Failed"


class SalaryPaymentBatch(BaseModel):
    """A set of payslips paid together, usually as one bank upload.

    Separate from the run because a run can be paid in tranches — the bank
    rejects three accounts, or a facility pays daily-wage staff in cash on a
    different day — and marking the whole run "paid" would be a lie about the
    three that bounced.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    run = models.ForeignKey(
        PayrollRun, on_delete=models.PROTECT, related_name="payment_batches"
    )
    method = models.CharField(
        max_length=20,
        choices=[
            ("bank_transfer", "Bank transfer"),
            ("cash", "Cash"),
            ("cheque", "Cheque"),
            ("wallet", "Mobile wallet"),
        ],
        default="bank_transfer",
    )
    status = models.CharField(
        max_length=16, choices=PaymentBatchStatus.choices,
        default=PaymentBatchStatus.DRAFT, db_index=True,
    )
    payslips = models.ManyToManyField(Payslip, related_name="payment_batches")

    total = models.DecimalField(max_digits=16, decimal_places=2, default=ZERO)
    count = models.PositiveIntegerField(default=0)
    bank_name = models.CharField(max_length=128, blank=True)
    exported_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by_id = models.UUIDField(null=True, blank=True)
    value_date = models.DateField(default=timezone.localdate)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "payroll_payment_batch"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference}: {self.count} payslips, {self.total}"
