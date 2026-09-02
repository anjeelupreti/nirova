"""Pharmacy: products, batches, and an immutable stock ledger.

Three properties govern everything in this module.

**Stock is a ledger, never a counter.** There is no `quantity_on_hand` column
that code increments and decrements. Every movement is an append-only
`StockEntry`, and the balance is their sum. A counter is one lost update away
from being wrong with no way to discover when it happened; a ledger can always
be replayed, reconciled and explained. `BatchStock` exists as a *cached* sum,
rebuildable from the ledger at any time.

**Batches are the unit of stock, not products.** Two boxes of the same
paracetamol with different expiry dates are different stock. Recall, expiry,
FEFO and traceability all operate on batches, and a system that tracks
products only cannot answer "who received the recalled lot?" — which is the
question that matters when it is asked.

**Expiry is a date, and dates arrive.** A batch does not become worthless on
its expiry date; it becomes progressively harder to shift for months
beforehand. The thresholds in `EXPIRY_BUCKETS` exist so a pharmacist sees a
problem while there is still time to act on it.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.organization.models import Department, Facility
from apps.patients.models import Patient

ZERO = Decimal("0.000")


class DosageForm(models.TextChoices):
    TABLET = "tablet", "Tablet"
    CAPSULE = "capsule", "Capsule"
    SYRUP = "syrup", "Syrup"
    SUSPENSION = "suspension", "Suspension"
    INJECTION = "injection", "Injection"
    INFUSION = "infusion", "Infusion"
    CREAM = "cream", "Cream"
    OINTMENT = "ointment", "Ointment"
    DROPS = "drops", "Drops"
    INHALER = "inhaler", "Inhaler"
    SUPPOSITORY = "suppository", "Suppository"
    POWDER = "powder", "Powder"
    PATCH = "patch", "Patch"
    OTHER = "other", "Other"


class StorageCondition(models.TextChoices):
    """How the product must be kept.

    `COLD_CHAIN` and `FROZEN` are separate from `REFRIGERATED` because they
    imply different equipment and different breach consequences — a vaccine
    that has been out of the cold chain is destroyed, not merely suspect.
    """

    AMBIENT = "ambient", "Room temperature"
    COOL = "cool", "Below 25°C"
    REFRIGERATED = "refrigerated", "2–8°C"
    COLD_CHAIN = "cold_chain", "2–8°C, cold chain"
    FROZEN = "frozen", "Below −15°C"
    PROTECT_FROM_LIGHT = "protect_light", "Protect from light"


class ControlSchedule(models.TextChoices):
    """Regulatory control level.

    Nepal's Narcotic Drugs (Control) Act governs the controlled classes.
    Anything above `NONE` needs an enhanced ledger and an authorised
    dispenser; `NARCOTIC` additionally needs a witnessed count.
    """

    NONE = "none", "Not controlled"
    PRESCRIPTION_ONLY = "prescription_only", "Prescription only"
    CONTROLLED = "controlled", "Controlled"
    NARCOTIC = "narcotic", "Narcotic"
    PSYCHOTROPIC = "psychotropic", "Psychotropic"


class Product(BaseModel):
    """A dispensable item: a medicine, a consumable, a device.

    Generic name is required and brand is not, deliberately: prescribing and
    stock control both work generically, and a brand is a property of the
    particular pack that arrived.
    """

    code = models.CharField(max_length=32, db_index=True)
    generic_name = models.CharField(max_length=255, db_index=True)
    brand_name = models.CharField(max_length=255, blank=True, db_index=True)
    strength = models.CharField(max_length=64, blank=True)
    dosage_form = models.CharField(
        max_length=20, choices=DosageForm.choices, default=DosageForm.TABLET
    )

    manufacturer = models.CharField(max_length=255, blank=True)
    country_of_origin = models.CharField(max_length=64, blank=True)
    #: Therapeutic class, for formulary reporting and substitution.
    therapeutic_class = models.CharField(max_length=128, blank=True, db_index=True)
    category = models.CharField(
        max_length=32,
        choices=[
            ("medicine", "Medicine"),
            ("consumable", "Consumable"),
            ("device", "Device"),
            ("surgical", "Surgical item"),
            ("reagent", "Laboratory reagent"),
            ("other", "Other"),
        ],
        default="medicine",
        db_index=True,
    )

    barcode = models.CharField(max_length=64, blank=True, db_index=True)

    # -- units ------------------------------------------------------------
    #
    # Stock is held in the *base* unit. A pack of 10 strips of 10 tablets is
    # 100 tablets in the ledger, because dispensing is per tablet and a
    # ledger denominated in packs cannot express "give them 15".

    base_unit = models.CharField(max_length=32, default="tablet")
    pack_size = models.PositiveIntegerField(
        default=1, help_text="Base units per purchase pack."
    )
    pack_unit = models.CharField(max_length=32, blank=True, default="box")

    storage_condition = models.CharField(
        max_length=20, choices=StorageCondition.choices,
        default=StorageCondition.AMBIENT,
    )
    control_schedule = models.CharField(
        max_length=20, choices=ControlSchedule.choices,
        default=ControlSchedule.NONE, db_index=True,
    )
    requires_prescription = models.BooleanField(default=False)

    # -- stock policy ------------------------------------------------------

    reorder_level = models.DecimalField(
        max_digits=12, decimal_places=3, default=ZERO,
        help_text="Raise a reorder when free stock falls to this.",
    )
    minimum_stock = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    maximum_stock = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    #: Average days between ordering and receiving. Feeds the reorder point.
    lead_time_days = models.PositiveSmallIntegerField(default=7)

    #: The billable service, when the product is charged through billing
    #: rather than sold at a POS price.
    service_uuid = models.UUIDField(null=True, blank=True)
    #: Links to the prescribing catalogue. A bare UUID because prescriptions
    #: were built before this module existed and store their own text.
    is_formulary = models.BooleanField(
        default=True, help_text="Stocked and prescribable at this organization."
    )

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "pharmacy_product"
        ordering = ["generic_name", "brand_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_product_code",
            )
        ]
        indexes = [
            models.Index(fields=["generic_name", "is_active"]),
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["control_schedule"]),
        ]

    def __str__(self):
        parts = [self.generic_name, self.strength, self.dosage_form]
        return " ".join(part for part in parts if part)

    @property
    def display_name(self) -> str:
        """What a pharmacist reads on a shelf label."""
        base = f"{self.generic_name} {self.strength}".strip()
        return f"{base} ({self.brand_name})" if self.brand_name else base

    @property
    def needs_cold_chain(self) -> bool:
        return self.storage_condition in {
            StorageCondition.REFRIGERATED,
            StorageCondition.COLD_CHAIN,
            StorageCondition.FROZEN,
        }

    @property
    def is_controlled(self) -> bool:
        return self.control_schedule != ControlSchedule.NONE


class StockLocation(BaseModel):
    """Where stock physically sits.

    Hierarchical — a store contains shelves, a shelf contains bins — because a
    stock count is done shelf by shelf and a system that only knows "the
    pharmacy" cannot direct one.
    """

    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, related_name="stock_locations"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="stock_locations",
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE,
        related_name="children",
    )

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    location_type = models.CharField(
        max_length=20,
        choices=[
            ("store", "Store"),
            ("dispensary", "Dispensary"),
            ("shelf", "Shelf"),
            ("bin", "Bin"),
            ("fridge", "Refrigerator"),
            ("cold_room", "Cold room"),
            ("quarantine", "Quarantine"),
            ("ward", "Ward stock"),
        ],
        default="store",
    )

    #: Quarantine holds stock that must not be dispensed — recalled,
    #: damaged, awaiting quality check. Kept as a location rather than a batch
    #: status so a physical shelf corresponds to a system state.
    is_quarantine = models.BooleanField(default=False)
    #: Whether stock here can be dispensed or sold directly.
    is_dispensable = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "stock_location"
        ordering = ["facility_id", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_location_code_per_facility",
            )
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"


class BatchStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    QUARANTINE = "quarantine", "Quarantined"
    EXPIRED = "expired", "Expired"
    RECALLED = "recalled", "Recalled"
    DAMAGED = "damaged", "Damaged"
    DISPOSED = "disposed", "Disposed"


#: Statuses from which stock may be dispensed or sold. Everything else is
#: physically present but must not leave the shelf.
DISPENSABLE_STATUSES = {BatchStatus.ACTIVE}


class Batch(BaseModel):
    """One lot of one product, with its own expiry and cost.

    The unit of stock. Two boxes of the same paracetamol expiring in different
    months are different batches, because FEFO, recall and expiry all operate
    on them.

    Costs are held per batch rather than per product: the same medicine bought
    twice at different prices has two costs, and averaging them silently
    destroys the margin figure.
    """

    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="batches"
    )
    batch_number = models.CharField(max_length=64, db_index=True)

    manufactured_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(db_index=True)

    supplier_name = models.CharField(max_length=255, blank=True)
    #: Goods-receipt reference, so a batch can be traced to its delivery.
    receipt_reference = models.CharField(max_length=64, blank=True)
    received_on = models.DateField(default=timezone.localdate)

    # -- money ------------------------------------------------------------

    purchase_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Cost per base unit.",
    )
    selling_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    mrp = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Maximum retail price printed on the pack.",
    )

    status = models.CharField(
        max_length=16, choices=BatchStatus.choices,
        default=BatchStatus.ACTIVE, db_index=True,
    )
    quarantine_reason = models.CharField(max_length=255, blank=True)
    recall_reference = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "pharmacy_batch"
        ordering = ["expires_on", "batch_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "batch_number", "expires_on"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_batch_per_product",
            )
        ]
        indexes = [
            models.Index(fields=["product", "status", "expires_on"]),
            models.Index(fields=["expires_on", "status"]),
        ]

    def __str__(self):
        return f"{self.product.generic_name} {self.batch_number} exp {self.expires_on}"

    @property
    def days_to_expiry(self) -> int:
        return (self.expires_on - timezone.localdate()).days

    @property
    def is_expired(self) -> bool:
        return self.expires_on < timezone.localdate()

    @property
    def is_dispensable(self) -> bool:
        """Whether stock from this batch may leave the shelf.

        Both conditions matter: a batch can be past its date while still
        marked active (nothing has run the expiry sweep yet), and an
        in-date batch can be quarantined for a recall. Checking only the
        status would dispense expired stock the morning before the sweep.
        """
        return self.status in DISPENSABLE_STATUSES and not self.is_expired

    def clean(self):
        if self.manufactured_on and self.manufactured_on > self.expires_on:
            raise ValidationError(
                {"expires_on": "A batch cannot expire before it was made."}
            )
        if self.mrp and self.selling_price > self.mrp:
            raise ValidationError(
                {"selling_price": "The selling price cannot exceed the printed MRP."}
            )


#: Expiry alert thresholds in days, from the specification (§42). Ordered
#: widest first so the first match is the least urgent bucket a batch falls
#: into — which is the one a report should show it in.
EXPIRY_BUCKETS = [365, 180, 120, 90, 60, 30, 15, 7]


def expiry_bucket(days: int) -> str:
    """Which alert bucket a number of days to expiry falls into."""
    if days < 0:
        return "expired"
    for threshold in sorted(EXPIRY_BUCKETS):
        if days <= threshold:
            return f"{threshold}_days"
    return "beyond_365_days"


class MovementType(models.TextChoices):
    """Every way stock can move.

    The full set from the specification (§40). Kept exhaustive rather than
    collapsed into "in" and "out" because the *reason* is what reporting
    needs: expiry write-off and theft are both stock leaving, and a pharmacy
    manager needs to tell them apart.
    """

    OPENING = "opening", "Opening balance"
    PURCHASE = "purchase", "Purchase receipt"
    SALE = "sale", "Sale"
    DISPENSE = "dispense", "Dispensed to patient"
    PURCHASE_RETURN = "purchase_return", "Return to supplier"
    SALES_RETURN = "sales_return", "Return from customer"
    TRANSFER_OUT = "transfer_out", "Transfer out"
    TRANSFER_IN = "transfer_in", "Transfer in"
    ADJUSTMENT_UP = "adjustment_up", "Adjustment — increase"
    ADJUSTMENT_DOWN = "adjustment_down", "Adjustment — decrease"
    DAMAGE = "damage", "Damaged"
    EXPIRY = "expiry", "Expired"
    RECALL = "recall", "Recalled"
    CONSUMPTION = "consumption", "Internal consumption"
    SAMPLE = "sample", "Sample"
    DONATION = "donation", "Donation"
    LOAN_OUT = "loan_out", "Loaned out"
    LOAN_IN = "loan_in", "Loaned in"
    THEFT = "theft", "Theft or loss"
    DISPOSAL = "disposal", "Disposal"


#: Movements that add stock. Everything else removes it. Held as data rather
#: than as a sign on each entry so the direction of a movement type cannot be
#: got wrong at one call site and right at another.
INBOUND_MOVEMENTS = {
    MovementType.OPENING,
    MovementType.PURCHASE,
    MovementType.SALES_RETURN,
    MovementType.TRANSFER_IN,
    MovementType.ADJUSTMENT_UP,
    MovementType.LOAN_IN,
}


class StockEntry(BaseModel):
    """One movement of stock. Append-only.

    Never updated and never deleted. A mistake is corrected by a compensating
    entry, exactly as in an accounting ledger, so the history of what was
    believed and when stays intact.

    `quantity` is always positive; `movement_type` carries the direction via
    `INBOUND_MOVEMENTS`. Signed quantities were rejected: a negative number
    that should have been positive is invisible on inspection, while a
    movement type that does not match its context is obvious.
    """

    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name="entries"
    )
    location = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="entries"
    )
    #: Denormalised so product-level reporting does not join through batch.
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="entries"
    )

    movement_type = models.CharField(
        max_length=20, choices=MovementType.choices, db_index=True
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    #: Running balance for this batch at this location after the entry.
    #: Stored so the ledger can be read as a statement without recomputing,
    #: and so a discrepancy between it and the running sum is detectable.
    balance_after = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)

    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    total_cost = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    performed_by_id = models.UUIDField(null=True, blank=True)
    performed_by_name = models.CharField(max_length=255, blank=True)

    #: What caused the movement: a prescription, an invoice, a transfer, a
    #: stock count. Free-form because the referent lives in another module.
    reference_type = models.CharField(max_length=64, blank=True)
    reference_id = models.CharField(max_length=64, blank=True, db_index=True)
    patient = models.ForeignKey(
        Patient, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="stock_entries",
    )

    reason = models.CharField(max_length=512, blank=True)
    #: Set when FEFO was overridden, with who authorised it (§41).
    fefo_overridden = models.BooleanField(default=False)
    fefo_override_reason = models.CharField(max_length=512, blank=True)
    approved_by_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "stock_entry"
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["batch", "location", "-occurred_at"]),
            models.Index(fields=["product", "-occurred_at"]),
            models.Index(fields=["movement_type", "-occurred_at"]),
            models.Index(fields=["reference_type", "reference_id"]),
        ]

    def __str__(self):
        sign = "+" if self.is_inbound else "−"
        return f"{sign}{self.quantity} {self.product.generic_name} ({self.movement_type})"

    @property
    def is_inbound(self) -> bool:
        return self.movement_type in INBOUND_MOVEMENTS

    @property
    def signed_quantity(self) -> Decimal:
        """The quantity with its direction applied, for summing."""
        return self.quantity if self.is_inbound else -self.quantity


class BatchStock(BaseModel):
    """Cached quantity of one batch at one location.

    A derived value, rebuildable from the ledger at any time by
    `rebuild_stock_cache()`. It exists because summing a ledger on every
    dispensing decision does not survive a busy pharmacy counter, not because
    it is the source of truth. When the two disagree, the ledger is right.

    `reserved` holds stock committed but not yet handed over — a dispensed
    prescription waiting at the counter. Free stock is `quantity − reserved`,
    which is what FEFO allocates against, so two counters cannot promise the
    same box.
    """

    batch = models.ForeignKey(
        Batch, on_delete=models.CASCADE, related_name="stock_levels"
    )
    location = models.ForeignKey(
        StockLocation, on_delete=models.CASCADE, related_name="stock_levels"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="stock_levels"
    )

    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    reserved = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO)
    last_movement_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "batch_stock"
        ordering = ["batch__expires_on"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "location"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_stock_per_batch_location",
            )
        ]
        indexes = [
            models.Index(fields=["product", "location"]),
            models.Index(fields=["location", "quantity"]),
        ]

    def __str__(self):
        return f"{self.batch} @ {self.location.code}: {self.quantity}"

    @property
    def available(self) -> Decimal:
        """Stock that can actually be promised to somebody."""
        return self.quantity - self.reserved


class DispenseStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    RESERVED = "reserved", "Reserved"
    DISPENSED = "dispensed", "Dispensed"
    CANCELLED = "cancelled", "Cancelled"
    RETURNED = "returned", "Returned"


class Dispense(BaseModel):
    """Medicines handed to a patient, against a prescription.

    Separate from the prescription because the two differ in ways that
    matter: a prescription for 30 tablets may be dispensed 10 at a time, a
    brand may be substituted, and a line may be out of stock. Recording the
    dispensing on the prescription would lose all three.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="dispenses"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="dispenses"
    )
    location = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="dispenses"
    )

    #: The prescription being filled. A bare UUID: prescriptions live in
    #: their own app and were built first.
    prescription_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    prescription_reference = models.CharField(max_length=32, blank=True)
    encounter_uuid = models.UUIDField(null=True, blank=True)

    status = models.CharField(
        max_length=16, choices=DispenseStatus.choices,
        default=DispenseStatus.DRAFT, db_index=True,
    )
    dispensed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    dispensed_by_id = models.UUIDField(null=True, blank=True)
    dispensed_by_name = models.CharField(max_length=255, blank=True)

    #: Counselling given to the patient, which for controlled and
    #: high-risk medicines is a professional obligation, not a nicety.
    counselling_notes = models.TextField(blank=True)
    total_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    charge_uuid = models.UUIDField(null=True, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "dispense"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "-created_at"]),
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["prescription_uuid"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.patient.mrn}"


class DispenseLine(BaseModel):
    """One medicine handed over, from one batch.

    A single prescription line can produce several of these when the quantity
    spans batches — which FEFO makes routine, because the oldest batch is
    usually not big enough on its own.
    """

    dispense = models.ForeignKey(
        Dispense, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="dispense_lines"
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name="dispense_lines"
    )

    #: Snapshot, so a later rename cannot change what the label said.
    product_name = models.CharField(max_length=255)
    batch_number = models.CharField(max_length=64)
    expires_on = models.DateField()

    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    #: The prescription line this fills, where there is one.
    prescription_line_uuid = models.UUIDField(null=True, blank=True)
    #: Set when a different brand was given than the one prescribed.
    is_substitution = models.BooleanField(default=False)
    substitution_reason = models.CharField(max_length=255, blank=True)

    #: FEFO override, carried onto the line as well as the ledger entry so a
    #: dispensing record is self-explanatory without joining.
    fefo_overridden = models.BooleanField(default=False)
    fefo_override_reason = models.CharField(max_length=512, blank=True)

    instructions = models.CharField(max_length=512, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "dispense_line"
        ordering = ["display_order", "product_name"]
        indexes = [models.Index(fields=["batch", "-created_at"])]

    def __str__(self):
        return f"{self.product_name} × {self.quantity} from {self.batch_number}"


class StockCountStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    COUNTING = "counting", "Counting"
    REVIEW = "review", "Variance review"
    APPROVED = "approved", "Approved"
    APPLIED = "applied", "Adjustments applied"
    CANCELLED = "cancelled", "Cancelled"


class StockCount(BaseModel):
    """A physical count, and the variance it found.

    Adjustments are never applied straight from a count. The variance is
    reviewed and approved first, by somebody other than the counter — a
    stock adjustment is the classic route for concealing theft, and an
    unreviewed count is a blank cheque.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="stock_counts"
    )
    location = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="stock_counts"
    )

    count_type = models.CharField(
        max_length=16,
        choices=[
            ("full", "Full stocktake"),
            ("cycle", "Cycle count"),
            ("abc", "ABC count"),
            ("spot", "Spot check"),
        ],
        default="cycle",
    )
    #: A blind count hides the expected figure from the counter. Standard
    #: practice: showing it produces counts that match expectation rather
    #: than reality.
    is_blind = models.BooleanField(default=True)

    status = models.CharField(
        max_length=16, choices=StockCountStatus.choices,
        default=StockCountStatus.DRAFT, db_index=True,
    )
    started_at = models.DateTimeField(default=timezone.now)
    counted_by_id = models.UUIDField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_notes = models.TextField(blank=True)

    class Meta:
        db_table = "stock_count"
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.reference} — {self.location.code}"


class StockCountLine(BaseModel):
    """One batch counted, expected against actual."""

    count = models.ForeignKey(
        StockCount, on_delete=models.CASCADE, related_name="lines"
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name="count_lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="count_lines"
    )

    #: What the system believed at the moment counting began. Frozen so a
    #: movement during the count does not silently change the variance.
    expected_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    counted_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    recount_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )

    variance_reason = models.CharField(max_length=255, blank=True)
    is_approved = models.BooleanField(default=False)

    class Meta:
        db_table = "stock_count_line"
        ordering = ["product__generic_name"]

    def __str__(self):
        return f"{self.product.generic_name}: {self.variance}"

    @property
    def final_quantity(self) -> Decimal | None:
        """A recount supersedes the first count where one was done."""
        return (
            self.recount_quantity
            if self.recount_quantity is not None
            else self.counted_quantity
        )

    @property
    def variance(self) -> Decimal | None:
        final = self.final_quantity
        if final is None:
            return None
        return final - self.expected_quantity

    @property
    def has_variance(self) -> bool:
        variance = self.variance
        return variance is not None and variance != ZERO
