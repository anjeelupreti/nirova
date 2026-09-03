"""Insurance, third-party administrators, and Nepal's government schemes.

A hospital does not have one payer. It has a general public paying cash, a
handful of insurers, two or three TPAs administering other people's policies,
several corporate accounts, and the Health Insurance Board — and the rules
differ for every one of them. The whole design follows from a single
observation: **the hospital's claim and the payer's answer are different
records, and the gap between them is the business.**

Six decisions, each a place where the obvious design loses money.

**Claimed, approved, deducted and paid are four separate amounts.** Not one
amount with a status. An insurer approves 80,000 of a 100,000 claim, deducts
15,000 as non-payable and pays 78,000 six weeks later — and every one of those
four numbers has to be recoverable, because the difference between them is
what the hospital is arguing about.

**A deduction has a reason, from a list.** "Rs 15,000 deducted" is not
actionable. "Rs 15,000 deducted: consumables not covered under the package" is
a policy the hospital can change. Free text produces a field nobody
aggregates, and the aggregate is the only thing that improves the next claim.

**Coverage is checked against the policy as it was on the date of service.**
Not as it is today. A policy that lapsed last week did not lapse before last
month's admission, and a system that checks "is this policy active" answers
the wrong question every time a claim is submitted late.

**A pre-authorisation is a promise with an expiry and an amount.** Both
matter. An approval for 60,000 that the hospital then spends 90,000 against is
a 30,000 argument, and one obtained in March for surgery in July is usually
void. The system knows both and says so before the surgery, not after.

**A claim's own status and the invoice's status are separate.** An invoice can
be fully raised while the claim is still being argued over, and marking the
invoice "paid" because a claim was submitted is how a hospital loses track of
what it is owed.

**The government schemes are not insurers.** Nepal's Health Insurance Board
pays by capitated package, the poor-citizen and specific-disease funds
reimburse against a ceiling per condition, and none of them behave like a
policy with a sum insured. They are modelled as their own payer type rather
than bent into an insurance shape that fits none of them.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# BaseModel gives every row a UUID, timestamps and soft delete. UUIDs are what
# the API publishes — with a database per tenant an integer PK means a
# different row in every customer's database.
from apps.common.models import BaseModel
from apps.billing.models import Invoice
from apps.encounters.models import Encounter
from apps.organization.models import Facility
from apps.patients.models import Patient

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Payers
# ---------------------------------------------------------------------------


class PayerKind(models.TextChoices):
    """What kind of thing is paying, which decides how a claim behaves.

    An insurer, a TPA and the Health Insurance Board are not variations on one
    concept. An insurer carries the risk; a TPA administers somebody else's
    risk and is the party the hospital actually deals with; the Board pays
    fixed packages regardless of what the treatment cost. Modelling them as
    one "insurance company" with optional fields produces a claim workflow
    with three unreachable branches.
    """

    INSURER = "insurer", "Insurance company"
    TPA = "tpa", "Third-party administrator"
    GOVERNMENT = "government", "Government scheme"
    CORPORATE = "corporate", "Corporate account"
    EMBASSY = "embassy", "Embassy or foreign mission"


class Payer(BaseModel):
    """An organisation that pays some or all of a patient's bill."""

    code = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    name_nepali = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=16, choices=PayerKind.choices)

    #: The insurer whose risk a TPA administers. A TPA with no insurer behind
    #: it is a self-funded corporate scheme, which is a real arrangement, so
    #: this is nullable rather than required.
    administers_for = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="administrators",
        limit_choices_to={"kind": PayerKind.INSURER},
    )

    registration_number = models.CharField(max_length=64, blank=True)
    pan_number = models.CharField(max_length=20, blank=True)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    contact_email = models.EmailField(blank=True)
    address = models.CharField(max_length=512, blank=True)

    #: Which price list this payer's patients are billed from. Insurers
    #: negotiate rates, and billing already resolves price by payer category —
    #: this is the join between the two.
    price_list_code = models.CharField(max_length=32, blank=True)

    #: How long the hospital has to submit after discharge. Missing this
    #: window is the single commonest way a claim becomes worthless, and it is
    #: per payer: some allow ninety days, some fifteen.
    submission_window_days = models.PositiveSmallIntegerField(default=90)
    #: How long they usually take to pay. Used to age a claim against the
    #: payer's own promise rather than a generic thirty days.
    settlement_days = models.PositiveSmallIntegerField(default=45)

    requires_preauthorisation = models.BooleanField(default=True)
    #: Below this, no pre-authorisation is needed. Zero means always.
    preauthorisation_threshold = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO,
    )

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["kind", "is_active"])]
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uniq_payer_code"),
        ]

    def __str__(self):
        return self.name

    @property
    def is_scheme(self) -> bool:
        """Government schemes pay by package, not against a sum insured."""
        return self.kind == PayerKind.GOVERNMENT


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


class PolicyStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    LAPSED = "lapsed", "Lapsed"
    SUSPENDED = "suspended", "Suspended"
    CANCELLED = "cancelled", "Cancelled"


class Policy(BaseModel):
    """One patient's cover with one payer, over a period.

    An interval, not a flag, and for the same reason as every other interval in
    this system: a claim is judged against the policy *as it was on the date of
    service*. A patient whose policy lapsed last week was covered for last
    month's admission, and a system that only knows the current state answers
    the wrong question on every late claim.
    """

    policy_number = models.CharField(max_length=64, db_index=True)
    payer = models.ForeignKey(
        Payer, on_delete=models.PROTECT, related_name="policies",
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="policies",
    )

    #: The person the policy belongs to, when the patient is a dependant.
    #: Claims are made against the principal's number, so this cannot be
    #: inferred from the patient record.
    principal_name = models.CharField(max_length=255, blank=True)
    relationship = models.CharField(
        max_length=32, blank=True,
        help_text="Self, spouse, child, parent.",
    )

    valid_from = models.DateField(db_index=True)
    valid_to = models.DateField(db_index=True)
    status = models.CharField(
        max_length=12, choices=PolicyStatus.choices,
        default=PolicyStatus.ACTIVE, db_index=True,
    )

    #: The annual ceiling. Null means uncapped, which is real for some
    #: corporate schemes and must not be confused with zero.
    sum_insured = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
    )
    #: Consumed so far. A cache over the claims, rebuildable — never the
    #: source of truth. The same rule as every other counter in this system.
    utilised = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO,
    )

    #: What the patient pays before the payer starts.
    deductible = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO,
    )
    #: The share of each bill the patient carries, as a percentage.
    co_payment_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=ZERO,
    )
    #: Sub-limits per category, e.g. {"room": 5000, "icu": 12000}. A daily
    #: room cap is the commonest deduction on a Nepali claim and the one
    #: patients are never told about.
    sub_limits = models.JSONField(default=dict, blank=True)

    #: Conditions the policy will not pay for, and until when. A waiting
    #: period on a pre-existing condition is the second commonest rejection.
    exclusions = models.JSONField(default=list, blank=True)
    waiting_period_until = models.DateField(null=True, blank=True)

    card_number = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-valid_from"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["payer", "policy_number"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_to__gte=models.F("valid_from")),
                name="policy_ends_after_it_starts",
            ),
            #: The same policy number twice for the same patient and payer is
            #: a duplicate record, and claims would then be split across two.
            models.UniqueConstraint(
                fields=["payer", "policy_number", "patient"],
                name="uniq_policy_per_patient",
            ),
        ]

    def __str__(self):
        return f"{self.payer_id} {self.policy_number}"

    def was_active_on(self, on_date) -> bool:
        """Whether cover was in force on a given date.

        Deliberately not `is_active`. The question a claim asks is about the
        date of service, and the answer changes as soon as somebody asks it
        about today instead.
        """
        if self.status in (PolicyStatus.CANCELLED,):
            return False
        return self.valid_from <= on_date <= self.valid_to

    @property
    def remaining(self) -> Decimal | None:
        if self.sum_insured is None:
            return None
        return self.sum_insured - self.utilised


# ---------------------------------------------------------------------------
# Pre-authorisation
# ---------------------------------------------------------------------------


class PreAuthStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    APPROVED = "approved", "Approved"
    PARTIALLY_APPROVED = "partially_approved", "Approved for less"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"
    #: The treatment happened and the approval was consumed.
    USED = "used", "Used"
    CANCELLED = "cancelled", "Cancelled"


class PreAuthorisation(BaseModel):
    """A payer's promise to cover a planned treatment, up to an amount, until
    a date.

    Both halves matter and both are routinely lost. An approval for 60,000
    against which the hospital spends 90,000 is a 30,000 argument; one
    obtained in Chaitra for surgery in Shrawan is usually void. The system
    knows both and says so before the operation rather than after it.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    policy = models.ForeignKey(
        Policy, on_delete=models.PROTECT, related_name="preauthorisations",
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="preauthorisations",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="preauthorisations",
    )
    encounter = models.ForeignKey(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="preauthorisations",
    )

    requested_at = models.DateTimeField(default=timezone.now, db_index=True)
    requested_by_name = models.CharField(max_length=255, blank=True)
    planned_treatment = models.CharField(max_length=512)
    diagnosis = models.CharField(max_length=512, blank=True)
    diagnosis_code = models.CharField(max_length=32, blank=True)
    planned_admission_on = models.DateField(null=True, blank=True)
    estimated_days = models.PositiveSmallIntegerField(null=True, blank=True)
    estimated_amount = models.DecimalField(max_digits=14, decimal_places=2)

    status = models.CharField(
        max_length=20, choices=PreAuthStatus.choices,
        default=PreAuthStatus.REQUESTED, db_index=True,
    )
    #: The payer's own reference, which is what they will ask for on the phone
    #: and what must appear on the claim.
    payer_reference = models.CharField(max_length=64, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    approved_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO,
    )
    #: When the approval stops being worth anything.
    valid_until = models.DateField(null=True, blank=True, db_index=True)
    conditions = models.TextField(
        blank=True,
        help_text="What the payer attached to the approval.",
    )
    rejection_reason = models.CharField(max_length=512, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["policy", "status"]),
            models.Index(fields=["facility", "status"]),
        ]

    def __str__(self):
        return f"{self.reference} {self.planned_treatment[:40]}"

    @property
    def is_usable(self) -> bool:
        if self.status not in (
            PreAuthStatus.APPROVED, PreAuthStatus.PARTIALLY_APPROVED,
        ):
            return False
        if self.valid_until and self.valid_until < timezone.localdate():
            return False
        return True

    @property
    def days_until_expiry(self) -> int | None:
        if not self.valid_until:
            return None
        return (self.valid_until - timezone.localdate()).days


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


class ClaimStatus(models.TextChoices):
    """Where a claim is, from the hospital's point of view.

    `QUERIED` earns its place: a payer that has asked a question has not
    rejected the claim and is not processing it either, and the hospital owes
    an answer. Folding it into "submitted" is how a claim sits for four months
    waiting for a document nobody knew was wanted.
    """

    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    QUERIED = "queried", "Query raised by the payer"
    APPROVED = "approved", "Approved"
    PARTIALLY_APPROVED = "partially_approved", "Approved in part"
    REJECTED = "rejected", "Rejected"
    #: Rejected once, argued, resubmitted. Kept distinct because the appeal
    #: rate is the number that says whether rejections are being fought.
    APPEALED = "appealed", "Under appeal"
    SETTLED = "settled", "Settled"
    #: The hospital gave up. An explicit outcome, because a claim quietly
    #: abandoned is revenue nobody records losing.
    WRITTEN_OFF = "written_off", "Written off"


class Claim(BaseModel):
    """What the hospital asked a payer for, and what the payer did about it.

    The four amounts — claimed, approved, deducted, settled — are separate
    fields rather than one amount with a status. Every one of them is a real,
    different number, and the differences between them are the entire subject
    of the hospital's relationship with the payer.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    payer = models.ForeignKey(
        Payer, on_delete=models.PROTECT, related_name="claims",
    )
    policy = models.ForeignKey(
        Policy, null=True, blank=True, on_delete=models.PROTECT,
        related_name="claims",
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="claims",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="claims",
    )
    #: The invoice being claimed against. Kept separate from the claim's own
    #: state: an invoice can be fully raised while the claim is still argued
    #: over, and marking the invoice paid because a claim was submitted is how
    #: a hospital loses track of what it is owed.
    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.PROTECT,
        related_name="claims",
    )
    encounter = models.ForeignKey(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="claims",
    )
    preauthorisation = models.ForeignKey(
        PreAuthorisation, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="claims",
    )

    #: When the treatment happened — not when the claim was made. Coverage is
    #: judged on this date, and the submission deadline runs from it.
    service_date = models.DateField(db_index=True)
    discharge_date = models.DateField(null=True, blank=True)
    diagnosis = models.CharField(max_length=512, blank=True)
    diagnosis_code = models.CharField(max_length=32, blank=True)
    treatment_summary = models.TextField(blank=True)

    status = models.CharField(
        max_length=20, choices=ClaimStatus.choices, default=ClaimStatus.DRAFT,
        db_index=True,
    )
    submitted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    submitted_by_name = models.CharField(max_length=255, blank=True)
    payer_reference = models.CharField(max_length=64, blank=True, db_index=True)

    # The four amounts.
    claimed_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO,
    )
    approved_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO,
    )
    deducted_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO,
    )
    settled_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO,
    )
    #: What the patient pays: deductible, co-payment and anything excluded.
    #: Computed at submission and stored, because the policy terms may change
    #: afterwards and the patient was told a number at the time.
    patient_liability = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO,
    )

    responded_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=512, blank=True)
    query_text = models.TextField(blank=True)
    query_raised_at = models.DateTimeField(null=True, blank=True)
    query_answered_at = models.DateTimeField(null=True, blank=True)

    #: How many times this claim has been sent. A claim resubmitted four times
    #: is a process problem, and it is invisible if resubmission overwrites.
    submission_count = models.PositiveSmallIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-service_date", "-created_at"]
        indexes = [
            models.Index(fields=["payer", "status"]),
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["status", "-submitted_at"]),
        ]
        constraints = [
            #: One claim per invoice per payer. A second claim for the same
            #: invoice is either a duplicate submission — which payers reject
            #: and sometimes penalise — or a resubmission that should have
            #: reused the original.
            models.UniqueConstraint(
                fields=["invoice", "payer"],
                condition=models.Q(invoice__isnull=False),
                name="uniq_claim_per_invoice_and_payer",
            ),
        ]

    def __str__(self):
        return f"{self.reference} {self.payer_id}"

    @property
    def outstanding(self) -> Decimal:
        """Approved but not yet in the bank."""
        return self.approved_amount - self.settled_amount

    @property
    def shortfall(self) -> Decimal:
        """The gap between what was asked for and what was allowed.

        Not the same as `deducted_amount`: a payer can allow less without
        recording a deduction against any particular line, and the difference
        between the two is itself worth seeing.
        """
        return self.claimed_amount - self.approved_amount

    @property
    def days_since_submission(self) -> int | None:
        if not self.submitted_at:
            return None
        return (timezone.now() - self.submitted_at).days

    @property
    def is_open(self) -> bool:
        return self.status in (
            ClaimStatus.DRAFT, ClaimStatus.SUBMITTED, ClaimStatus.QUERIED,
            ClaimStatus.APPROVED, ClaimStatus.PARTIALLY_APPROVED,
            ClaimStatus.APPEALED,
        )


class ClaimLine(BaseModel):
    """One billed item as it appears on the claim, and what the payer did to it.

    A copy rather than a reference to the invoice line. The invoice is a
    statutory document and cannot change; the claim is a negotiation, and the
    payer's decision belongs on the claim's own copy. Pointing at the invoice
    line would mean either mutating a statutory document or having nowhere to
    record the deduction.
    """

    claim = models.ForeignKey(
        Claim, on_delete=models.CASCADE, related_name="lines",
    )
    description = models.CharField(max_length=255)
    service_code = models.CharField(max_length=32, blank=True)
    #: Which sub-limit this falls under: room, icu, investigation, drug,
    #: consumable, procedure. Policies cap by category and a claim that cannot
    #: be grouped this way cannot be checked against the caps.
    category = models.CharField(max_length=32, blank=True, db_index=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    claimed_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO,
    )
    approved_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO,
    )
    deducted_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO,
    )
    deduction_reason = models.CharField(max_length=32, blank=True)
    deduction_notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["claim", "category"])]
        constraints = [
            #: A deduction without a reason is a number nobody can argue with
            #: and nobody can aggregate. The reason is the entire value of
            #: recording it.
            models.CheckConstraint(
                condition=models.Q(deducted_amount=0)
                | ~models.Q(deduction_reason=""),
                name="deduction_has_a_reason",
            ),
        ]

    def __str__(self):
        return f"{self.description[:40]} {self.claimed_amount}"


#: Why a payer refused to pay for something.
#:
#: A fixed list rather than free text, because the only useful thing about a
#: deduction is the aggregate: a hospital that discovers 40% of its deductions
#: are "consumables not covered" can change what it bills, and one with a
#: thousand distinct free-text reasons can change nothing.
DEDUCTION_REASONS = [
    ("not_covered", "Not covered by the policy"),
    ("above_sub_limit", "Above the category sub-limit"),
    ("above_sum_insured", "Above the sum insured"),
    ("co_payment", "Patient co-payment"),
    ("deductible", "Patient deductible"),
    ("pre_existing", "Pre-existing condition within the waiting period"),
    ("no_preauth", "No pre-authorisation obtained"),
    ("above_preauth", "Above the approved pre-authorisation"),
    ("tariff_difference", "Above the agreed tariff"),
    ("documentation", "Supporting documents missing or inadequate"),
    ("not_medically_necessary", "Not accepted as medically necessary"),
    ("duplicate", "Duplicate billing"),
    ("late_submission", "Submitted after the deadline"),
    ("package_inclusive", "Included in the package rate"),
    ("other", "Other"),
]

DEDUCTION_REASON_KEYS = {key for key, _ in DEDUCTION_REASONS}


class ClaimEvent(BaseModel):
    """Everything that has happened to a claim, in order. Append-only.

    A claim is a conversation conducted over months by people who leave. The
    status field says where it is now; this says how it got there, which is
    what anybody picking it up actually needs.
    """

    claim = models.ForeignKey(
        Claim, on_delete=models.CASCADE, related_name="events",
    )
    happened_at = models.DateTimeField(default=timezone.now, db_index=True)
    event = models.CharField(max_length=32)
    detail = models.CharField(max_length=1000, blank=True)
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
    )
    actor_name = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["happened_at", "id"]
        indexes = [models.Index(fields=["claim", "happened_at"])]

    def __str__(self):
        return f"{self.event} {self.happened_at:%Y-%m-%d}"


# ---------------------------------------------------------------------------
# Government schemes
# ---------------------------------------------------------------------------


class SchemePackage(BaseModel):
    """A fixed price a government scheme pays for a named condition.

    The Health Insurance Board and the specific-disease funds pay a set amount
    per package regardless of what the treatment actually cost. That is not a
    policy with a sum insured, and modelling it as one produces a claim that is
    always either over or under by the difference between cost and package
    rate — which is precisely the number a scheme hospital needs to manage.
    """

    payer = models.ForeignKey(
        Payer, on_delete=models.CASCADE, related_name="packages",
        limit_choices_to={"kind": PayerKind.GOVERNMENT},
    )
    code = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    name_nepali = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=64, blank=True)
    package_amount = models.DecimalField(max_digits=12, decimal_places=2)
    #: Some packages cap the number of days or episodes per year.
    maximum_per_year = models.PositiveSmallIntegerField(null=True, blank=True)
    includes = models.TextField(
        blank=True, help_text="What the package covers.",
    )
    excludes = models.TextField(blank=True)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            #: A package's rate changes by government notice; the old rate
            #: must stay for claims already made against it, so the key is the
            #: code *and* the date it took effect.
            models.UniqueConstraint(
                fields=["payer", "code", "effective_from"],
                name="uniq_package_rate_from",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


def validate_deduction_reason(reason: str) -> None:
    """Refuse a deduction reason that is not one of the countable ones.

    A service-layer check so the message can say what the alternatives are,
    which a check constraint cannot.
    """
    if reason and reason not in DEDUCTION_REASON_KEYS:
        raise ValidationError(
            f"'{reason}' is not a recognised deduction reason. Use one of: "
            f"{', '.join(sorted(DEDUCTION_REASON_KEYS))}."
        )
