"""Billing: what was done, what it costs, what was invoiced, what was paid.

Money is the other half of the clinical record, and it obeys different rules
from the clinical half. Three shape everything here.

**Every amount is a `Decimal`.** Never a float. `0.1 + 0.2` is not `0.3` in
binary floating point, and a rounding drift of one paisa per line becomes a
reconciliation failure at the end of a month. `DecimalField` all the way down,
and arithmetic in `Decimal` throughout the service layer.

**Issued invoices are immutable.** An invoice is a statutory document. It is
reversed by a credit note, never edited, and its number is never reused. Nepal
requires sequential, gapless invoice numbering per fiscal year, and an audit
that finds a missing number will ask why.

**Charges and invoices are separate.** A charge records that something
billable happened; an invoice collects charges and asks for money. For
outpatients the two happen minutes apart, but an inpatient accumulates charges
for three weeks before anyone bills them — and building the invoice as the
only record of a charge would make that impossible.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.encounters.models import Encounter
from apps.organization.models import Department, Facility
from apps.patients.models import Patient, PatientCategory

ZERO = Decimal("0.00")


class ServiceCategory(models.TextChoices):
    """What kind of thing is being charged for.

    Drives reporting and, later, revenue recognition per department. A
    hospital's board asks "how much came from theatre?" and the answer has to
    come from somewhere.
    """

    CONSULTATION = "consultation", "Consultation"
    REGISTRATION = "registration", "Registration"
    PROCEDURE = "procedure", "Procedure"
    LABORATORY = "laboratory", "Laboratory"
    RADIOLOGY = "radiology", "Radiology"
    PHARMACY = "pharmacy", "Pharmacy"
    CONSUMABLE = "consumable", "Consumables"
    BED = "bed", "Bed and accommodation"
    NURSING = "nursing", "Nursing"
    THEATRE = "theatre", "Operation theatre"
    AMBULANCE = "ambulance", "Ambulance"
    DIET = "diet", "Dietary"
    PACKAGE = "package", "Package"
    OTHER = "other", "Other"


class TaxTreatment(models.TextChoices):
    """How VAT applies.

    Most healthcare services in Nepal are VAT-exempt, but not all, and the
    treatment differs for medicines and for non-clinical services like
    ambulance hire or a private room. Exempt and zero-rated are kept distinct
    because they are different things on a VAT return, even though both
    produce no tax on the line.
    """

    EXEMPT = "exempt", "VAT exempt"
    ZERO_RATED = "zero_rated", "Zero rated"
    STANDARD = "standard", "Standard rate"


#: Nepal's standard VAT rate. A single constant rather than a hard-coded 13
#: scattered through the code, so a rate change is one edit -- and so the
#: number is findable when someone asks where it came from.
STANDARD_VAT_RATE = Decimal("13.00")


class ServiceItem(BaseModel):
    """Something a facility can charge for.

    The catalogue. Prices live on `PriceListItem` rather than here, because
    the same service costs different amounts for a general patient, a
    corporate scheme and an insurer — and one price on the service would make
    that inexpressible.
    """

    code = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    name_nepali = models.CharField(max_length=255, blank=True)
    category = models.CharField(
        max_length=24, choices=ServiceCategory.choices, db_index=True
    )
    description = models.TextField(blank=True)

    #: Which department earns the revenue. Drives departmental profitability.
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="service_items",
    )

    #: Fallback price when no price list covers the patient's category. Having
    #: one means a service can always be charged; a missing price list should
    #: not stop a patient being billed at the counter.
    default_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    tax_treatment = models.CharField(
        max_length=16, choices=TaxTreatment.choices, default=TaxTreatment.EXEMPT
    )
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=ZERO,
        help_text="Percentage. Ignored unless the treatment is standard.",
    )

    #: Ceiling on the discount a user may apply without approval. Zero means
    #: no discount without an authorised override.
    max_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=ZERO
    )
    #: Whether the charge repeats per day of stay. Bed charges do; a
    #: consultation does not.
    is_recurring_daily = models.BooleanField(default=False)
    requires_prescription = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "service_item"
        ordering = ["category", "display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_service_code",
            )
        ]
        indexes = [models.Index(fields=["category", "is_active"])]

    def __str__(self):
        return f"{self.code} — {self.name}"

    @property
    def effective_tax_rate(self) -> Decimal:
        """The rate actually applied. Exempt and zero-rated both yield zero."""
        if self.tax_treatment != TaxTreatment.STANDARD:
            return ZERO
        return self.tax_rate or STANDARD_VAT_RATE


class PriceList(BaseModel):
    """A set of prices for one payer arrangement.

    Effective-dated rather than edited in place: last month's invoices must
    still be explicable against the prices that applied when they were raised.
    """

    code = models.SlugField(max_length=64)
    name = models.CharField(max_length=255)
    #: Which patients this list serves. Null means it is the general list.
    patient_category = models.CharField(
        max_length=16, choices=PatientCategory.choices, blank=True, db_index=True
    )
    #: Facility-specific pricing. Null means it applies organization-wide.
    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.CASCADE,
        related_name="price_lists",
    )
    #: Named counterparty, for corporate schemes and insurers whose rates are
    #: negotiated individually.
    payer_reference = models.CharField(max_length=128, blank=True)

    effective_from = models.DateField(default=timezone.localdate)
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    #: Higher wins when several lists match. Lets a negotiated corporate rate
    #: beat the general list without deleting either.
    priority = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "price_list"
        ordering = ["-priority", "name"]
        indexes = [models.Index(fields=["patient_category", "is_active"])]

    def __str__(self):
        return self.name

    def applies_on(self, on_date) -> bool:
        if not self.is_active or self.effective_from > on_date:
            return False
        return self.effective_to is None or self.effective_to >= on_date


class PriceListItem(BaseModel):
    price_list = models.ForeignKey(
        PriceList, on_delete=models.CASCADE, related_name="items"
    )
    service = models.ForeignKey(
        ServiceItem, on_delete=models.CASCADE, related_name="prices"
    )
    price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(ZERO)]
    )
    #: Discount baked into the arrangement, applied before any user discount.
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=ZERO
    )

    class Meta:
        db_table = "price_list_item"
        constraints = [
            models.UniqueConstraint(
                fields=["price_list", "service"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_price_per_list_service",
            )
        ]

    def __str__(self):
        return f"{self.service.code} @ {self.price}"


class ChargeStatus(models.TextChoices):
    PENDING = "pending", "Pending invoice"
    INVOICED = "invoiced", "Invoiced"
    CANCELLED = "cancelled", "Cancelled"
    WRITTEN_OFF = "written_off", "Written off"


class Charge(BaseModel):
    """A billable event: something was done, and it costs money.

    Separate from the invoice line so an inpatient can accumulate three weeks
    of charges before anyone bills them, and so a charge can be cancelled
    before invoicing without touching a statutory document.

    Prices are **captured onto the charge** at the moment it is raised. The
    price list may change tomorrow; what the patient was told today is what
    they are billed.
    """

    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="charges"
    )
    encounter = models.ForeignKey(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="charges",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="charges"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="charges",
    )
    service = models.ForeignKey(
        ServiceItem, on_delete=models.PROTECT, related_name="charges"
    )

    #: Snapshot of the service as it was when charged. A service can be
    #: renamed or retired; an invoice raised last year must still read
    #: correctly.
    service_code = models.CharField(max_length=32)
    service_name = models.CharField(max_length=255)

    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("1.00")
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=ZERO
    )
    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    #: Quantity × unit price, less discount, plus tax. Stored rather than
    #: computed on read so a historical total cannot drift if the arithmetic
    #: is ever changed.
    total = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)

    price_list = models.ForeignKey(
        PriceList, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="charges",
    )
    #: How the price was arrived at, for the same reason entitlements carry
    #: provenance: "why was I charged this?" should be answerable.
    price_source = models.CharField(max_length=128, blank=True)

    status = models.CharField(
        max_length=16, choices=ChargeStatus.choices,
        default=ChargeStatus.PENDING, db_index=True,
    )
    charged_at = models.DateTimeField(default=timezone.now, db_index=True)
    charged_by_id = models.UUIDField(null=True, blank=True)

    #: A discount beyond the service's ceiling needs someone to authorise it.
    discount_approved_by_id = models.UUIDField(null=True, blank=True)
    discount_reason = models.CharField(max_length=255, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "charge"
        ordering = ["-charged_at"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["encounter", "status"]),
            models.Index(fields=["facility", "-charged_at"]),
            models.Index(fields=["status", "-charged_at"]),
        ]

    def __str__(self):
        return f"{self.service_name} × {self.quantity} = {self.total}"

    @property
    def is_billable(self) -> bool:
        return self.status == ChargeStatus.PENDING

    def compute_total(self) -> Decimal:
        """Line total: (quantity × price) − discount + tax.

        Discount is taken before tax, which is the correct order: VAT is due
        on what the customer actually pays, not on the list price.
        """
        gross = (self.quantity * self.unit_price).quantize(Decimal("0.01"))
        discount = self.discount_amount or (
            gross * self.discount_percent / Decimal("100")
        ).quantize(Decimal("0.01"))
        net = gross - discount
        tax = (net * self.tax_rate / Decimal("100")).quantize(Decimal("0.01"))
        self.discount_amount = discount
        self.tax_amount = tax
        return (net + tax).quantize(Decimal("0.01"))


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ISSUED = "issued", "Issued"
    PARTIALLY_PAID = "partially_paid", "Partially paid"
    PAID = "paid", "Paid"
    #: Reversed by a credit note. The invoice itself stays exactly as issued.
    CREDITED = "credited", "Credited"
    WRITTEN_OFF = "written_off", "Written off"
    CANCELLED = "cancelled", "Cancelled"


class Invoice(BaseModel):
    """A demand for payment. A statutory document.

    Draft invoices can be changed. Issued invoices cannot: they are reversed
    by a credit note and reissued. The number is allocated at issue, not at
    creation, so an abandoned draft does not consume one and leave a gap that
    a tax audit will ask about.
    """

    #: Allocated on issue. Null while draft.
    number = models.CharField(
        max_length=32, null=True, blank=True, unique=True, db_index=True
    )
    #: Nepali fiscal year the number belongs to, e.g. "2082/83". Numbering
    #: restarts each year, so the year is part of the identity.
    fiscal_year = models.CharField(max_length=16, blank=True, db_index=True)

    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="invoices"
    )
    encounter = models.ForeignKey(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="invoices",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="invoices"
    )

    #: Snapshot of who was billed. A patient can change their name or address;
    #: the invoice must keep saying what it said when it was issued.
    bill_to_name = models.CharField(max_length=255)
    bill_to_address = models.CharField(max_length=512, blank=True)
    bill_to_pan = models.CharField(max_length=20, blank=True)
    patient_category = models.CharField(max_length=16, blank=True)
    payer_reference = models.CharField(max_length=128, blank=True)

    status = models.CharField(
        max_length=16, choices=InvoiceStatus.choices,
        default=InvoiceStatus.DRAFT, db_index=True,
    )
    issued_at = models.DateTimeField(null=True, blank=True, db_index=True)
    issued_by_id = models.UUIDField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    discount_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=ZERO
    )
    tax_total = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    #: Rounding to the nearest rupee, since Nepali counters rarely hold coin.
    #: Held separately so the arithmetic on the invoice still adds up.
    rounding_adjustment = models.DecimalField(
        max_digits=6, decimal_places=2, default=ZERO
    )
    total = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)

    currency = models.CharField(max_length=3, default="NPR")
    notes = models.TextField(blank=True)

    #: Set when a credit note reverses this invoice.
    credited_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="credits",
    )
    #: True when this document *is* a credit note. Same table because a credit
    #: note is an invoice with negative intent, shares the numbering sequence,
    #: and every report that lists invoices must list it.
    is_credit_note = models.BooleanField(default=False)
    credit_reason = models.TextField(blank=True)

    class Meta:
        db_table = "invoice"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "-created_at"]),
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["status", "-issued_at"]),
            models.Index(fields=["fiscal_year", "number"]),
        ]

    def __str__(self):
        return f"{self.number or 'DRAFT'} — {self.bill_to_name} — {self.total}"

    @property
    def balance_due(self) -> Decimal:
        return (self.total - self.amount_paid).quantize(Decimal("0.01"))

    @property
    def is_settled(self) -> bool:
        return self.balance_due <= ZERO

    @property
    def is_editable(self) -> bool:
        return self.status == InvoiceStatus.DRAFT

    def clean(self):
        if self.status != InvoiceStatus.DRAFT and not self.number:
            raise ValidationError(
                {"number": "An issued invoice must carry a number."}
            )


class InvoiceLine(BaseModel):
    """One line on an invoice.

    A copy of the charge, not a pointer to it. The charge may later be
    cancelled or corrected; the issued invoice must keep saying what it said.
    """

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="lines"
    )
    charge = models.ForeignKey(
        Charge, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="invoice_lines",
    )

    service_code = models.CharField(max_length=32)
    description = models.CharField(max_length=255)
    category = models.CharField(max_length=24, blank=True)

    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "invoice_line"
        ordering = ["display_order", "id"]

    def __str__(self):
        return f"{self.description} = {self.total}"


class PaymentMethod(models.TextChoices):
    """How the money arrived.

    eSewa, Khalti and IME Pay are Nepal's dominant wallets and are named
    individually rather than lumped into "digital", because reconciliation is
    per provider — each settles separately and on its own schedule.
    """

    CASH = "cash", "Cash"
    CARD = "card", "Card"
    ESEWA = "esewa", "eSewa"
    KHALTI = "khalti", "Khalti"
    IME_PAY = "ime_pay", "IME Pay"
    FONEPAY = "fonepay", "Fonepay"
    BANK_TRANSFER = "bank_transfer", "Bank transfer"
    CHEQUE = "cheque", "Cheque"
    CREDIT = "credit", "On account"
    INSURANCE = "insurance", "Insurance"
    WAIVER = "waiver", "Waived"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"
    REVERSED = "reversed", "Reversed"


class Payment(BaseModel):
    """Money received against an invoice.

    Several per invoice is normal: a deposit, a wallet payment, the rest in
    cash. Recorded individually rather than as a running total, because
    reconciliation happens per method and per counter.
    """

    receipt_number = models.CharField(
        max_length=32, null=True, blank=True, unique=True, db_index=True
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="payments"
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="payments"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="payments"
    )

    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(ZERO)]
    )
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    status = models.CharField(
        max_length=16, choices=PaymentStatus.choices,
        default=PaymentStatus.COMPLETED, db_index=True,
    )

    #: Wallet transaction id, cheque number, card authorisation code.
    reference = models.CharField(max_length=128, blank=True)
    #: Which till took the money, for end-of-shift cash reconciliation.
    counter = models.CharField(max_length=32, blank=True)

    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    received_by_id = models.UUIDField(null=True, blank=True)
    received_by_name = models.CharField(max_length=255, blank=True)

    #: Refunds point at the payment they reverse. Both rows stay.
    refunds = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="refunded_by",
    )
    refund_reason = models.CharField(max_length=255, blank=True)
    #: Segregation of duties: whoever took the money may not approve its
    #: return. Enforced in the service layer.
    refund_approved_by_id = models.UUIDField(null=True, blank=True)

    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "payment"
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["invoice", "status"]),
            models.Index(fields=["facility", "-received_at"]),
            models.Index(fields=["method", "-received_at"]),
        ]

    def __str__(self):
        return f"{self.receipt_number or 'unreceipted'} — {self.amount} ({self.method})"

    @property
    def is_refund(self) -> bool:
        return self.refunds_id is not None


class NumberSequence(BaseModel):
    """Gapless sequential numbering, per facility, per year, per document type.

    A separate table rather than `MAX(number) + 1`, because the maximum of a
    column is not safe under concurrency and is wrong the moment a row is
    deleted. Nepal requires sequential, gapless invoice numbering per fiscal
    year, and the row is locked while a number is taken.
    """

    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, related_name="number_sequences"
    )
    document_type = models.CharField(
        max_length=32,
        choices=[
            ("invoice", "Invoice"),
            ("credit_note", "Credit note"),
            ("receipt", "Receipt"),
        ],
    )
    fiscal_year = models.CharField(max_length=16)
    prefix = models.CharField(max_length=16, blank=True)
    last_number = models.PositiveIntegerField(default=0)
    padding = models.PositiveSmallIntegerField(default=6)

    class Meta:
        db_table = "number_sequence"
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "document_type", "fiscal_year"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_sequence_per_facility_year",
            )
        ]

    def __str__(self):
        return f"{self.document_type} {self.fiscal_year}: {self.last_number}"

    def format(self, number: int) -> str:
        prefix = self.prefix or self.document_type[:3].upper()
        return f"{prefix}-{self.fiscal_year}-{number:0{self.padding}d}"
