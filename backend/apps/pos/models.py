"""Point of sale: the retail pharmacy counter.

A separate app from `pharmacy` because it is a different surface with
different assumptions, not because the data is unrelated. A hospital
dispensary knows who the patient is and bills their account; a retail counter
serves someone who walked in off the street, takes their money now, and may
never see them again.

Three properties shape it.

**A sale is an invoice.** Nepal requires a tax invoice for retail sale, so the
money side goes through `apps.billing` — the same statutory numbering, the
same credit notes, the same end-of-day cash-up. A parallel revenue path for
POS would give the organization two sets of books.

**The till is reconciled, not trusted.** A counter session opens with a
counted float and closes with a counted drawer. The variance between what the
system says should be there and what actually is there is the number that
matters, and it is recorded whether or not it is zero.

**A walk-in has no patient record, and that is fine.** Requiring registration
to sell a strip of paracetamol would mean either refusing the sale or
inventing a patient — and inventing patients corrupts the record that the
clinical side depends on.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.pharmacy.models import Batch, Product, StockLocation

ZERO = Decimal("0.000")
MONEY_ZERO = Decimal("0.00")


class SessionStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSING = "closing", "Counting"
    CLOSED = "closed", "Closed"
    RECONCILED = "reconciled", "Reconciled"


class CounterSession(BaseModel):
    """One cashier's shift at one till.

    Exists so cash can be reconciled to a person and a period. Without it,
    a drawer that is short at the end of a day belongs to nobody — and a
    shortage nobody owns is a shortage nobody investigates.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="counter_sessions"
    )
    location = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="counter_sessions"
    )
    counter = models.CharField(max_length=32, help_text="Till identifier.")

    cashier_id = models.UUIDField(db_index=True)
    cashier_name = models.CharField(max_length=255)

    status = models.CharField(
        max_length=16, choices=SessionStatus.choices,
        default=SessionStatus.OPEN, db_index=True,
    )
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)

    #: Cash in the drawer at the start, counted by the cashier.
    opening_float = models.DecimalField(
        max_digits=12, decimal_places=2, default=MONEY_ZERO
    )
    #: Cash counted at the end. Entered before the expected figure is shown,
    #: for the same reason a stock count is blind.
    closing_count = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    #: What the system says should be in the drawer: float plus cash sales
    #: less cash refunds. Computed at close, then frozen.
    expected_cash = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    variance = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    variance_reason = models.CharField(max_length=512, blank=True)

    #: Non-cash takings, for reference at close. Not part of the drawer
    #: reconciliation — wallet and card settlements arrive separately and on
    #: their own schedule.
    card_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=MONEY_ZERO
    )
    wallet_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=MONEY_ZERO
    )
    credit_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=MONEY_ZERO
    )

    reconciled_by_id = models.UUIDField(null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "counter_session"
        ordering = ["-opened_at"]
        constraints = [
            # One open session per till. Two cashiers sharing a drawer makes
            # the variance meaningless, so the model refuses it.
            models.UniqueConstraint(
                fields=["facility", "counter"],
                condition=models.Q(status="open", deleted_at__isnull=True),
                name="uniq_open_session_per_counter",
            )
        ]
        indexes = [
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["cashier_id", "-opened_at"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.counter} ({self.cashier_name})"

    @property
    def is_open(self) -> bool:
        return self.status == SessionStatus.OPEN

    @property
    def has_variance(self) -> bool:
        return self.variance is not None and self.variance != MONEY_ZERO

    @property
    def duration_minutes(self) -> int | None:
        if not self.closed_at:
            return None
        return int((self.closed_at - self.opened_at).total_seconds() / 60)


class SaleType(models.TextChoices):
    """Who the sale is to, which decides pricing and whether stock is tracked
    against a patient."""

    WALK_IN = "walk_in", "Walk-in"
    PATIENT = "patient", "Registered patient"
    PRESCRIPTION = "prescription", "Against a prescription"
    CORPORATE = "corporate", "Corporate account"
    INSURANCE = "insurance", "Insurance"
    STAFF = "staff", "Staff"


class SaleStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    COMPLETED = "completed", "Completed"
    PARTIALLY_RETURNED = "partially_returned", "Partially returned"
    RETURNED = "returned", "Returned"
    VOIDED = "voided", "Voided"


class Sale(BaseModel):
    """One transaction at the counter.

    Carries the POS-specific state — till, session, sale type — while the
    money lives on the linked billing invoice and the stock movement lives in
    the pharmacy ledger. Three records, one event, each owned by the module
    that is responsible for it.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    session = models.ForeignKey(
        CounterSession, on_delete=models.PROTECT, related_name="sales"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="sales"
    )
    location = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="sales"
    )

    sale_type = models.CharField(
        max_length=16, choices=SaleType.choices,
        default=SaleType.WALK_IN, db_index=True,
    )
    #: Null for a walk-in. Requiring registration to sell paracetamol would
    #: mean either refusing the sale or inventing a patient, and invented
    #: patients corrupt the clinical record.
    patient = models.ForeignKey(
        Patient, null=True, blank=True, on_delete=models.PROTECT,
        related_name="pos_sales",
    )
    #: For a walk-in who wants a named receipt, without becoming a patient.
    customer_name = models.CharField(max_length=255, blank=True)
    customer_phone = models.CharField(max_length=32, blank=True)
    customer_pan = models.CharField(max_length=20, blank=True)

    prescription_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    prescription_reference = models.CharField(max_length=32, blank=True)

    status = models.CharField(
        max_length=20, choices=SaleStatus.choices,
        default=SaleStatus.DRAFT, db_index=True,
    )
    sold_at = models.DateTimeField(default=timezone.now, db_index=True)
    sold_by_id = models.UUIDField(null=True, blank=True)
    sold_by_name = models.CharField(max_length=255, blank=True)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    discount_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=MONEY_ZERO
    )
    tax_total = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    rounding_adjustment = models.DecimalField(
        max_digits=6, decimal_places=2, default=MONEY_ZERO
    )
    total = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)

    #: The billing invoice this sale raised. A retail sale is a tax invoice in
    #: Nepal, so it goes through the same statutory numbering as everything
    #: else rather than having a parallel revenue path.
    invoice_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    invoice_number = models.CharField(max_length=32, blank=True)

    #: A dispensing record, when the sale was against a prescription. The
    #: clinical record needs to know the medicine was actually handed over.
    dispense_uuid = models.UUIDField(null=True, blank=True)

    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=512, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "pos_sale"
        ordering = ["-sold_at"]
        indexes = [
            models.Index(fields=["session", "-sold_at"]),
            models.Index(fields=["facility", "-sold_at"]),
            models.Index(fields=["status", "-sold_at"]),
            models.Index(fields=["patient", "-sold_at"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.total}"

    @property
    def customer_label(self) -> str:
        """Who the receipt is made out to."""
        if self.patient_id:
            return self.patient.full_name
        return self.customer_name or "Walk-in customer"

    @property
    def is_returnable(self) -> bool:
        return self.status in {
            SaleStatus.COMPLETED,
            SaleStatus.PARTIALLY_RETURNED,
        }


class SaleLine(BaseModel):
    """One product on a sale, from one batch.

    A single scanned item can produce several lines when the quantity spans
    batches — FEFO makes that routine, and the receipt has to show which
    batches the customer actually received for a later return to be checked.
    """

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="sale_lines"
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name="sale_lines"
    )

    product_name = models.CharField(max_length=255)
    batch_number = models.CharField(max_length=64)
    expires_on = models.DateField()

    quantity = models.DecimalField(
        max_digits=12, decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    returned_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO
    )

    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    mrp = models.DecimalField(max_digits=12, decimal_places=2, default=MONEY_ZERO)
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=MONEY_ZERO
    )
    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=MONEY_ZERO
    )
    tax_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=MONEY_ZERO
    )
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=MONEY_ZERO
    )
    total = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)

    #: Cost at the time, captured so margin can be reported without joining
    #: back to a batch whose price may since have been corrected.
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=MONEY_ZERO
    )

    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "pos_sale_line"
        ordering = ["display_order", "product_name"]
        indexes = [models.Index(fields=["batch", "-created_at"])]

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"

    @property
    def returnable_quantity(self) -> Decimal:
        return max(self.quantity - self.returned_quantity, ZERO)

    @property
    def margin(self) -> Decimal:
        """Gross margin on this line, at the cost captured when it sold."""
        cost = (self.unit_cost * self.quantity).quantize(Decimal("0.01"))
        return (self.total - self.tax_amount - cost).quantize(Decimal("0.01"))

    def clean(self):
        if self.mrp and self.unit_price > self.mrp:
            raise ValidationError(
                {"unit_price": "Cannot sell above the printed MRP."}
            )


class SaleReturnStatus(models.TextChoices):
    PENDING = "pending", "Awaiting approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    COMPLETED = "completed", "Completed"


class SaleReturn(BaseModel):
    """Goods coming back over the counter.

    Approved by someone other than the cashier who made the sale. A refund is
    money leaving the till against goods whose condition only the cashier has
    seen, which is the oldest retail fraud there is.

    Whether the stock goes back on the shelf is a decision, not an assumption:
    a sealed box returned within an hour can be resold, an opened bottle
    cannot, and a medicine that has left the premises may not be resaleable at
    all under the pharmacy's own policy.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="returns")
    session = models.ForeignKey(
        CounterSession, on_delete=models.PROTECT, related_name="returns"
    )

    status = models.CharField(
        max_length=16, choices=SaleReturnStatus.choices,
        default=SaleReturnStatus.PENDING, db_index=True,
    )
    reason = models.CharField(max_length=512)
    #: True when the goods go back into sellable stock. False sends them to
    #: quarantine instead — the money is still refunded either way.
    restock = models.BooleanField(default=True)
    restock_note = models.CharField(max_length=512, blank=True)

    requested_by_id = models.UUIDField(null=True, blank=True)
    requested_by_name = models.CharField(max_length=255, blank=True)
    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_by_name = models.CharField(max_length=255, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    decision_notes = models.CharField(max_length=512, blank=True)

    refund_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=MONEY_ZERO
    )
    refund_method = models.CharField(max_length=20, blank=True)
    #: The credit note raised against the sale's invoice.
    credit_note_uuid = models.UUIDField(null=True, blank=True)
    credit_note_number = models.CharField(max_length=32, blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "pos_sale_return"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["sale", "status"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.reference} against {self.sale.reference}"


class SaleReturnLine(BaseModel):
    sale_return = models.ForeignKey(
        SaleReturn, on_delete=models.CASCADE, related_name="lines"
    )
    sale_line = models.ForeignKey(
        SaleLine, on_delete=models.PROTECT, related_name="return_lines"
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    refund_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=MONEY_ZERO
    )
    condition_note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "pos_sale_return_line"
        ordering = ["sale_line__display_order"]

    def __str__(self):
        return f"{self.sale_line.product_name} × {self.quantity}"
