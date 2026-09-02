"""Procurement: suppliers, requisitions, orders and goods receipt.

The chain this module implements is the specification's (§48, §53):

    demand → requisition → approval → RFQ → quotation → comparison
           → purchase order → goods receipt → quality check
           → batch → inventory → supplier invoice → payment

Three properties shape it.

**A requisition is a request; a purchase order is a commitment.** They are
separate documents because the first is internal and reversible and the second
binds the organization to a supplier. Collapsing them would mean every
department head who wanted something had authority to spend.

**Receiving is where stock and money meet.** A goods receipt creates the
pharmacy batch and posts the ledger movement, so there is exactly one way
stock comes into existence from outside — and every batch can be traced to the
delivery, the order and the requisition that caused it.

**Suppliers are rated by what they actually did.** Lead time, fill rate and
rejection rate are computed from receipts rather than typed into a field,
because a performance score somebody typed is a performance score somebody
chose.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.organization.models import Department, Facility
from apps.pharmacy.models import Batch, Product, StockLocation

ZERO = Decimal("0.000")
MONEY_ZERO = Decimal("0.00")


class SupplierStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ON_HOLD = "on_hold", "On hold"
    BLACKLISTED = "blacklisted", "Blacklisted"
    INACTIVE = "inactive", "Inactive"


class Supplier(BaseModel):
    """A vendor the organization buys from.

    `BLACKLISTED` is separate from `INACTIVE` on purpose: one is a supplier
    who has stopped trading, the other is one the organization has decided
    not to trade with. Ordering is blocked for both, but only the second is a
    decision somebody has to justify.
    """

    code = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    legal_name = models.CharField(max_length=255, blank=True)

    pan_number = models.CharField(max_length=20, blank=True)
    vat_number = models.CharField(max_length=20, blank=True)
    registration_number = models.CharField(max_length=64, blank=True)

    contact_person = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=512, blank=True)
    district = models.CharField(max_length=64, blank=True)

    #: Days from order to delivery, as agreed. The *actual* figure is computed
    #: from receipts by `Supplier.measured_lead_time()`; this is what they
    #: promised, and the gap between the two is the interesting number.
    agreed_lead_time_days = models.PositiveSmallIntegerField(default=7)
    #: Days after invoice before payment is due.
    credit_days = models.PositiveSmallIntegerField(default=30)
    credit_limit = models.DecimalField(
        max_digits=14, decimal_places=2, default=MONEY_ZERO
    )

    #: What this supplier is approved to sell us. Empty means anything.
    product_categories = models.JSONField(default=list, blank=True)
    #: Licence to distribute medicines. Nepal requires one; ordering from a
    #: supplier whose licence has lapsed is a regulatory problem, not a
    #: commercial one.
    drug_licence_number = models.CharField(max_length=64, blank=True)
    drug_licence_expires_on = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=16, choices=SupplierStatus.choices,
        default=SupplierStatus.ACTIVE, db_index=True,
    )
    status_reason = models.CharField(max_length=512, blank=True)

    bank_name = models.CharField(max_length=255, blank=True)
    bank_account = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "supplier"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_supplier_code",
            )
        ]
        indexes = [models.Index(fields=["status", "name"])]

    def __str__(self):
        return f"{self.code} — {self.name}"

    @property
    def can_order_from(self) -> bool:
        """Whether a purchase order may be raised against this supplier."""
        if self.status != SupplierStatus.ACTIVE:
            return False
        if self.drug_licence_expires_on and (
            self.drug_licence_expires_on < timezone.localdate()
        ):
            return False
        return True

    @property
    def licence_expired(self) -> bool:
        return bool(
            self.drug_licence_expires_on
            and self.drug_licence_expires_on < timezone.localdate()
        )


class RequisitionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    #: Fully converted into one or more purchase orders.
    ORDERED = "ordered", "Ordered"
    PARTIALLY_ORDERED = "partially_ordered", "Partially ordered"
    CANCELLED = "cancelled", "Cancelled"


class PurchaseRequisition(BaseModel):
    """An internal request to buy something.

    Deliberately not a purchase order. A department head asking for stock and
    an organization committing money to a supplier are different acts with
    different authority, and a system that conflates them gives everyone who
    can ask the power to spend.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="requisitions"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="requisitions",
    )
    location = models.ForeignKey(
        StockLocation, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="requisitions",
        help_text="Where the goods are wanted.",
    )

    status = models.CharField(
        max_length=20, choices=RequisitionStatus.choices,
        default=RequisitionStatus.DRAFT, db_index=True,
    )
    #: Higher runs first. An urgent requisition for a stock-out is not the
    #: same as a routine top-up.
    is_urgent = models.BooleanField(default=False)
    required_by = models.DateField(null=True, blank=True)

    justification = models.TextField(blank=True)
    #: Set when the requisition was generated from a reorder suggestion rather
    #: than typed by a person, so automated demand is distinguishable.
    raised_automatically = models.BooleanField(default=False)

    requested_by_id = models.UUIDField(null=True, blank=True)
    requested_by_name = models.CharField(max_length=255, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_by_name = models.CharField(max_length=255, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    decision_notes = models.TextField(blank=True)

    estimated_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=MONEY_ZERO
    )

    class Meta:
        db_table = "purchase_requisition"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["status", "is_urgent", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.reference} ({self.get_status_display()})"

    @property
    def is_open(self) -> bool:
        return self.status in {
            RequisitionStatus.SUBMITTED,
            RequisitionStatus.APPROVED,
            RequisitionStatus.PARTIALLY_ORDERED,
        }


class RequisitionLine(BaseModel):
    requisition = models.ForeignKey(
        PurchaseRequisition, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="requisition_lines"
    )
    product_name = models.CharField(max_length=255)

    quantity = models.DecimalField(
        max_digits=12, decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    #: Quantity already placed on purchase orders. A requisition can be
    #: fulfilled across several orders when suppliers split a basket.
    ordered_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO
    )
    estimated_unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=MONEY_ZERO
    )

    #: Stock position when the requisition was raised, frozen so an approver
    #: sees what the requester saw rather than today's figure.
    stock_on_hand = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO
    )
    reorder_level = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO
    )
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "requisition_line"
        ordering = ["product_name"]

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"

    @property
    def outstanding_quantity(self) -> Decimal:
        return max(self.quantity - self.ordered_quantity, ZERO)

    @property
    def is_fully_ordered(self) -> bool:
        return self.outstanding_quantity <= ZERO


class QuotationStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    RECEIVED = "received", "Received"
    SELECTED = "selected", "Selected"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"


class Quotation(BaseModel):
    """A supplier's price against a requisition.

    Several per requisition is the point: the comparison is the control. A
    single quotation accepted without alternatives is how procurement fraud
    looks, so the model makes the absence of comparison visible rather than
    invisible.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    requisition = models.ForeignKey(
        PurchaseRequisition, on_delete=models.CASCADE, related_name="quotations"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="quotations"
    )

    status = models.CharField(
        max_length=16, choices=QuotationStatus.choices,
        default=QuotationStatus.REQUESTED, db_index=True,
    )
    requested_at = models.DateTimeField(default=timezone.now)
    received_at = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)

    total_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=MONEY_ZERO
    )
    quoted_lead_time_days = models.PositiveSmallIntegerField(null=True, blank=True)
    payment_terms = models.CharField(max_length=255, blank=True)

    #: Why this quotation was chosen over the others. Required when the
    #: selected quotation is not the cheapest — see `ProcurementService`.
    selection_reason = models.TextField(blank=True)
    selected_by_id = models.UUIDField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "quotation"
        ordering = ["total_value"]
        constraints = [
            models.UniqueConstraint(
                fields=["requisition", "supplier"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_quotation_per_supplier",
            )
        ]

    def __str__(self):
        return f"{self.reference} — {self.supplier.name} @ {self.total_value}"

    @property
    def is_expired(self) -> bool:
        return bool(self.valid_until and self.valid_until < timezone.localdate())


class QuotationLine(BaseModel):
    quotation = models.ForeignKey(
        Quotation, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="quotation_lines"
    )
    product_name = models.CharField(max_length=255)

    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    tax_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    #: Suppliers commonly offer free units rather than a discount. Recorded
    #: separately because the free quantity is stock that arrives without cost
    #: and would otherwise distort the unit cost.
    free_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO
    )

    class Meta:
        db_table = "quotation_line"
        ordering = ["product_name"]

    def __str__(self):
        return f"{self.product_name} @ {self.unit_price}"

    @property
    def effective_unit_cost(self) -> Decimal:
        """Cost per unit once free quantity is taken into account.

        The number that should actually be compared between suppliers: a
        higher price with 10% free can beat a lower price without.
        """
        total_units = self.quantity + self.free_quantity
        if total_units <= ZERO:
            return self.unit_price
        return (self.total / total_units).quantize(Decimal("0.01"))


class PurchaseOrderStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_APPROVAL = "pending_approval", "Pending approval"
    APPROVED = "approved", "Approved"
    SENT = "sent", "Sent to supplier"
    PARTIALLY_RECEIVED = "partially_received", "Partially received"
    RECEIVED = "received", "Fully received"
    CANCELLED = "cancelled", "Cancelled"
    CLOSED = "closed", "Closed short"


OPEN_ORDER_STATUSES = {
    PurchaseOrderStatus.APPROVED,
    PurchaseOrderStatus.SENT,
    PurchaseOrderStatus.PARTIALLY_RECEIVED,
}


class PurchaseOrder(BaseModel):
    """A commitment to buy, sent to a supplier.

    Approval is separate from creation, and by a different person: raising an
    order and committing the organization's money are the maker and the
    checker of the same transaction.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="purchase_orders"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="purchase_orders"
    )
    requisition = models.ForeignKey(
        PurchaseRequisition, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="purchase_orders",
    )
    quotation = models.ForeignKey(
        Quotation, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="purchase_orders",
    )
    deliver_to = models.ForeignKey(
        StockLocation, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="purchase_orders",
    )

    status = models.CharField(
        max_length=20, choices=PurchaseOrderStatus.choices,
        default=PurchaseOrderStatus.DRAFT, db_index=True,
    )
    ordered_on = models.DateField(default=timezone.localdate)
    expected_delivery = models.DateField(null=True, blank=True)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    discount_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=MONEY_ZERO
    )
    tax_total = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    currency = models.CharField(max_length=3, default="NPR")

    created_by_name = models.CharField(max_length=255, blank=True)
    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_by_name = models.CharField(max_length=255, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    sent_at = models.DateTimeField(null=True, blank=True)
    payment_terms = models.CharField(max_length=255, blank=True)
    delivery_terms = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=512, blank=True)
    #: Closed short: the supplier will not deliver the rest and the order is
    #: being written off rather than chased. Distinct from cancellation,
    #: which means nothing was delivered.
    closed_reason = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "purchase_order"
        ordering = ["-ordered_on", "-created_at"]
        indexes = [
            models.Index(fields=["supplier", "status"]),
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["status", "expected_delivery"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.supplier.name}"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_ORDER_STATUSES

    @property
    def is_overdue(self) -> bool:
        """Past its expected delivery date and still not complete."""
        if not self.expected_delivery or not self.is_open:
            return False
        return timezone.localdate() > self.expected_delivery

    @property
    def days_late(self) -> int:
        if not self.is_overdue:
            return 0
        return (timezone.localdate() - self.expected_delivery).days


class PurchaseOrderLine(BaseModel):
    order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="order_lines"
    )
    requisition_line = models.ForeignKey(
        RequisitionLine, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="order_lines",
    )

    product_name = models.CharField(max_length=255)
    product_code = models.CharField(max_length=32)

    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    free_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO
    )
    #: Quantity actually received. Partial delivery is normal, so this is a
    #: running total rather than a boolean.
    received_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO
    )
    rejected_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO
    )

    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    tax_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    line_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=MONEY_ZERO
    )

    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "purchase_order_line"
        ordering = ["display_order", "product_name"]

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"

    @property
    def outstanding_quantity(self) -> Decimal:
        """Still to come, counting free units as part of the delivery."""
        expected = self.quantity + self.free_quantity
        return max(expected - self.received_quantity, ZERO)

    @property
    def is_complete(self) -> bool:
        return self.outstanding_quantity <= ZERO

    def compute_total(self) -> Decimal:
        gross = (self.quantity * self.unit_price).quantize(Decimal("0.01"))
        discount = (gross * self.discount_percent / Decimal("100")).quantize(
            Decimal("0.01")
        )
        net = gross - discount
        tax = (net * self.tax_percent / Decimal("100")).quantize(Decimal("0.01"))
        return (net + tax).quantize(Decimal("0.01"))


class ReceiptStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    QUALITY_CHECK = "quality_check", "Awaiting quality check"
    ACCEPTED = "accepted", "Accepted"
    PARTIALLY_REJECTED = "partially_rejected", "Partially rejected"
    REJECTED = "rejected", "Rejected"
    POSTED = "posted", "Posted to stock"


class GoodsReceipt(BaseModel):
    """A delivery arriving against a purchase order.

    The single door through which purchased stock enters. Posting a receipt
    creates the pharmacy batches and the ledger movements, so every batch can
    be traced back to the delivery, the order, the quotation and the
    requisition that caused it.

    Quality check happens before posting, not after: stock that failed
    inspection should never have been on the shelf, and reversing it
    afterwards leaves a window in which it could have been dispensed.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, related_name="receipts"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="receipts"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="goods_receipts"
    )
    location = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="goods_receipts"
    )

    status = models.CharField(
        max_length=20, choices=ReceiptStatus.choices,
        default=ReceiptStatus.DRAFT, db_index=True,
    )
    received_on = models.DateField(default=timezone.localdate)
    received_by_id = models.UUIDField(null=True, blank=True)
    received_by_name = models.CharField(max_length=255, blank=True)

    #: The supplier's own paperwork, for matching against their invoice.
    delivery_note_number = models.CharField(max_length=64, blank=True)
    supplier_invoice_number = models.CharField(max_length=64, blank=True)
    supplier_invoice_date = models.DateField(null=True, blank=True)
    supplier_invoice_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=MONEY_ZERO
    )

    quality_checked_by_id = models.UUIDField(null=True, blank=True)
    quality_checked_at = models.DateTimeField(null=True, blank=True)
    quality_notes = models.TextField(blank=True)

    posted_at = models.DateTimeField(null=True, blank=True)
    total_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=MONEY_ZERO
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "goods_receipt"
        ordering = ["-received_on", "-created_at"]
        indexes = [
            models.Index(fields=["order", "status"]),
            models.Index(fields=["supplier", "-received_on"]),
            models.Index(fields=["status", "-received_on"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.supplier.name}"

    @property
    def is_posted(self) -> bool:
        return self.status == ReceiptStatus.POSTED

    @property
    def invoice_matches(self) -> bool | None:
        """Whether the supplier's invoice agrees with what was received.

        Returns `None` when no invoice amount has been entered yet. A
        mismatch is not an error — it is the thing accounts payable exists to
        investigate — so it is reported rather than blocked.
        """
        if not self.supplier_invoice_amount:
            return None
        return abs(self.supplier_invoice_amount - self.total_value) < Decimal("0.01")


class ReceiptLine(BaseModel):
    """One batch of one product, arriving.

    Batch details live here rather than on the order line because they are
    not known until the goods turn up: the supplier decides which lot they
    ship, and a single order line routinely arrives as two batches with
    different expiry dates.
    """

    receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.CASCADE, related_name="lines"
    )
    order_line = models.ForeignKey(
        PurchaseOrderLine, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="receipt_lines",
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="receipt_lines"
    )
    product_name = models.CharField(max_length=255)

    batch_number = models.CharField(max_length=64)
    manufactured_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField()

    received_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    free_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO
    )
    accepted_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO
    )
    rejected_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO
    )
    rejection_reason = models.CharField(max_length=512, blank=True)

    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=MONEY_ZERO
    )
    mrp = models.DecimalField(max_digits=12, decimal_places=2, default=MONEY_ZERO)
    line_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=MONEY_ZERO
    )

    #: The batch this line created, once posted. Null until then.
    batch = models.ForeignKey(
        Batch, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="receipt_lines",
    )
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "receipt_line"
        ordering = ["display_order", "product_name"]
        indexes = [models.Index(fields=["receipt", "product"])]

    def __str__(self):
        return f"{self.product_name} {self.batch_number} × {self.received_quantity}"

    @property
    def total_units(self) -> Decimal:
        """Everything that arrived, free units included."""
        return self.received_quantity + self.free_quantity

    @property
    def effective_unit_cost(self) -> Decimal:
        """Cost per unit, spread across everything that arrived.

        Divided by `total_units` — received plus free — and deliberately *not*
        by `accepted_quantity`.

        Free units dilute the cost: 500 paid plus 100 free at 9.20 is 7.67 a
        unit, not 9.20, and valuing the free stock at zero would overstate the
        cost of the paid units.

        Rejected units must not concentrate it. Dividing by the accepted
        quantity would load the cost of goods sent back onto the goods kept —
        500 received at 8.60 with 20 rejected came out at 8.96 a unit, which
        overstates inventory value and quietly writes off a claim the supplier
        owes. What was rejected is credited by the supplier, not absorbed by
        the shelf.
        """
        units = self.total_units
        if units <= ZERO:
            return self.unit_cost
        return (self.line_total / units).quantize(Decimal("0.01"))

    def clean(self):
        if self.expires_on and self.expires_on <= timezone.localdate():
            raise ValidationError(
                {"expires_on": "This batch has already expired."}
            )
        if self.rejected_quantity > self.total_units:
            raise ValidationError(
                {"rejected_quantity": "More rejected than arrived."}
            )
