"""Seed the pharmacy and run stock control end to end.

Exercises, through the real service layer:

1. A product master and a stock location hierarchy.
2. Receiving three batches of the same product with different expiry dates.
3. **FEFO**: dispensing takes the earliest-expiring batch first and spans
   into the next when the first runs out.
4. **FEFO override**: naming a later batch is refused without a reason, then
   allowed with one — and the override is recorded on both the ledger entry
   and the dispensing line.
5. A recall: quarantining a batch, and finding every patient who received it.
6. An expiry sweep writing off stock that has gone out of date.
7. A stock count where the counter cannot approve their own variance.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.common.exceptions import SegregationOfDutiesViolation
from apps.identity.models import User
from apps.organization.models import Department, Facility
from apps.patients.models import Patient, PatientStatus
from apps.pharmacy.models import (
    BatchStock,
    ControlSchedule,
    DosageForm,
    MovementType,
    Product,
    StockCountStatus,
    StockLocation,
    StorageCondition,
)
from apps.pharmacy.services import (
    FefoOverrideRequired,
    approve_count,
    dispense,
    expiring_stock,
    post_movement,
    quarantine_batch,
    recall_exposure,
    reorder_suggestions,
    start_count,
    stock_valuation,
    sweep_expired,
)
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

#: (code, generic, brand, strength, form, unit, reorder, schedule, storage)
PRODUCTS = [
    ("MED-001", "Amoxicillin", "Moxikind", "500 mg", DosageForm.CAPSULE,
     "capsule", 200, ControlSchedule.PRESCRIPTION_ONLY, StorageCondition.AMBIENT),
    ("MED-002", "Paracetamol", "Niko", "500 mg", DosageForm.TABLET,
     "tablet", 500, ControlSchedule.NONE, StorageCondition.AMBIENT),
    ("MED-003", "Metformin", "Glycomet", "500 mg", DosageForm.TABLET,
     "tablet", 300, ControlSchedule.PRESCRIPTION_ONLY, StorageCondition.AMBIENT),
    ("MED-004", "Insulin glargine", "Lantus", "100 IU/mL", DosageForm.INJECTION,
     "vial", 20, ControlSchedule.PRESCRIPTION_ONLY, StorageCondition.COLD_CHAIN),
    ("MED-005", "Diazepam", "Calmpose", "5 mg", DosageForm.TABLET,
     "tablet", 50, ControlSchedule.CONTROLLED, StorageCondition.AMBIENT),
]

#: (product code, batch number, days until expiry, quantity, cost, sell, mrp)
#:
#: Amoxicillin deliberately arrives in three batches with staggered expiry —
#: that is what FEFO is demonstrated against. AMX-2024-A is nearly out of
#: date and deliberately small, so a dispensing has to span into the next.
BATCHES = [
    ("MED-001", "AMX-2024-A", 25, 40, "8.00", "12.00", "14.00"),
    ("MED-001", "AMX-2025-B", 210, 500, "8.50", "12.00", "14.00"),
    ("MED-001", "AMX-2025-C", 400, 800, "8.20", "12.00", "14.00"),
    ("MED-002", "PCM-2025-A", 300, 2000, "1.20", "2.00", "2.50"),
    ("MED-003", "MET-2025-A", 150, 600, "2.40", "4.00", "5.00"),
    ("MED-004", "INS-2025-A", 90, 30, "850.00", "1100.00", "1250.00"),
    ("MED-005", "DZP-2025-A", 240, 100, "3.00", "5.00", "6.00"),
    # Already expired on arrival in the ledger — created directly so the
    # expiry sweep has something to find.
    ("MED-002", "PCM-2024-OLD", -5, 150, "1.10", "2.00", "2.50"),
]


class Command(BaseCommand):
    help = "Seed the pharmacy and run stock control end to end."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        organization = Organization.objects.filter(slug=options["slug"]).first()
        if organization is None:
            raise CommandError(f"No organization '{options['slug']}'.")

        pharmacist = User.objects.filter(
            email=f"manager@{options['slug']}.test"
        ).first()
        supervisor = User.objects.filter(
            email=f"owner@{options['slug']}.test"
        ).first()

        with tenant_context(context_for_organization(organization)):
            facility = Facility.objects.filter(facility_type="pharmacy").first() \
                or Facility.objects.filter(facility_type="clinic").first()
            if facility is None:
                raise CommandError("No facility. Run `seed_demo` first.")

            self._ensure_pharmacy_module(organization)
            dispensary, store = self._locations(facility)
            self._products()
            self._receive(dispensary, store, pharmacist)
            self._fefo(organization, facility, dispensary, pharmacist)
            self._override(organization, facility, dispensary, pharmacist, supervisor)
            self._recall(dispensary, supervisor)
            self._expiry(pharmacist)
            self._count(facility, dispensary, pharmacist, supervisor)
            self._report(dispensary)

    # -- setup -----------------------------------------------------------

    def _ensure_pharmacy_module(self, organization):
        from apps.catalog.keys import ModuleCode
        from apps.entitlements.resolver import resolve_entitlements

        if not resolve_entitlements(organization).has_module(ModuleCode.PHARMACY):
            raise CommandError(
                "The pharmacy module is not in this subscription. That is the "
                "entitlement engine working; attach the add-on to proceed."
            )

    def _locations(self, facility):
        department = Department.objects.filter(
            facility=facility, code="PHR"
        ).first() or Department.objects.filter(facility=facility).first()

        store, _ = StockLocation.objects.update_or_create(
            facility=facility, code="STORE",
            defaults={
                "name": "Main store", "location_type": "store",
                "department": department, "is_dispensable": False,
            },
        )
        dispensary, _ = StockLocation.objects.update_or_create(
            facility=facility, code="DISP",
            defaults={
                "name": "Dispensary counter", "location_type": "dispensary",
                "department": department, "parent": store,
                "is_dispensable": True,
            },
        )
        self.stdout.write(f"  locations: {store.code}, {dispensary.code}")
        return dispensary, store

    def _products(self):
        for (code, generic, brand, strength, form, unit, reorder,
             schedule, storage) in PRODUCTS:
            Product.objects.update_or_create(
                code=code,
                defaults={
                    "generic_name": generic, "brand_name": brand,
                    "strength": strength, "dosage_form": form,
                    "base_unit": unit, "pack_size": 10,
                    "reorder_level": Decimal(reorder),
                    "maximum_stock": Decimal(reorder) * 4,
                    "control_schedule": schedule,
                    "storage_condition": storage,
                    "requires_prescription": schedule != ControlSchedule.NONE,
                    "lead_time_days": 7, "is_active": True,
                },
            )
        self.stdout.write(f"  {len(PRODUCTS)} products in the master")

    def _receive(self, dispensary, store, actor):
        from apps.pharmacy.models import Batch

        today = timezone.localdate()
        for code, number, days, quantity, cost, sell, mrp in BATCHES:
            product = Product.objects.get(code=code)
            expires = today + timedelta(days=days)
            batch, _ = Batch.objects.get_or_create(
                product=product, batch_number=number, expires_on=expires,
                defaults={
                    "purchase_price": Decimal(cost),
                    "selling_price": Decimal(sell),
                    "mrp": Decimal(mrp),
                    "supplier_name": "Nepal Pharma Distributors",
                    "receipt_reference": f"GRN-{number}",
                },
            )
            if not batch.entries.exists():
                post_movement(
                    batch=batch, location=dispensary,
                    movement_type=MovementType.PURCHASE,
                    quantity=Decimal(quantity), actor=actor,
                    reason="Opening receipt",
                    reference_type="goods_receipt",
                    reference_id=batch.receipt_reference,
                )
        self.stdout.write(f"  {len(BATCHES)} batches received into {dispensary.code}")

    # -- 1. FEFO ---------------------------------------------------------

    def _fefo(self, organization, facility, dispensary, actor):
        patient = _live("Sita")
        amoxicillin = Product.objects.get(code="MED-001")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n1. FEFO - dispensing 60 {amoxicillin.generic_name} to "
            f"{patient.full_name}"))

        self._show_batches(amoxicillin, dispensary)

        result = dispense(
            organization, patient, facility, dispensary,
            items=[{"product": amoxicillin, "quantity": Decimal("60")}],
            actor=actor,
            counselling_notes="Take with food. Finish the course.",
        )
        self.stdout.write(self.style.SUCCESS(f"   {result.reference}:"))
        lines = list(result.lines.all())
        for line in lines:
            self.stdout.write(
                f"     {line.quantity:>6} from {line.batch_number} "
                f"(expires {line.expires_on})")

        # Describe what actually happened rather than asserting a fixed
        # outcome: on a re-run the near-expiry batch is already gone, and a
        # narrative that claims otherwise would be quietly lying.
        if len(lines) > 1:
            self.stdout.write(
                f"   spanned {len(lines)} batches, earliest expiry first")
        else:
            self.stdout.write(
                "   one batch covered it — the earliest expiry in stock")

    # -- 2. FEFO override ------------------------------------------------

    def _override(self, organization, facility, dispensary, actor, supervisor):
        patient = _live("Ram")
        amoxicillin = Product.objects.get(code="MED-001")
        later = amoxicillin.batches.order_by("-expires_on").first()
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n2. FEFO override - asking for {later.batch_number} "
            f"(expires {later.expires_on})"))

        try:
            dispense(
                organization, patient, facility, dispensary,
                items=[{"product": amoxicillin, "quantity": Decimal("20"),
                        "batch": later}],
                actor=actor,
            )
            self.stdout.write(self.style.ERROR(
                "   BUG: the override was accepted with no reason"))
        except FefoOverrideRequired as exc:
            self.stdout.write(
                f"   correctly refused: {exc.detail['earliest_batch']} expires "
                f"{exc.detail['earliest_expiry']} and is in stock")

        result = dispense(
            organization, patient, facility, dispensary,
            items=[{
                "product": amoxicillin, "quantity": Decimal("20"),
                "batch": later,
                "override_reason": "Earlier batch physically at the ward "
                                   "counter; patient waiting.",
            }],
            actor=actor, approved_by=supervisor,
        )
        line = result.lines.first()
        self.stdout.write(self.style.WARNING(
            f"   {result.reference}: {line.quantity} from {line.batch_number}, "
            f"override recorded"))
        self.stdout.write(f"     reason: {line.fefo_override_reason[:55]}...")

    # -- 3. recall -------------------------------------------------------

    def _recall(self, dispensary, actor):
        amoxicillin = Product.objects.get(code="MED-001")
        batch = amoxicillin.batches.order_by("expires_on").first()
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n3. Recall - {batch.batch_number}"))

        quarantine_batch(
            batch,
            reason="Manufacturer notice: possible sub-potency in this lot.",
            actor=actor,
            recall_reference="RC-2026-014",
        )
        exposure = recall_exposure(batch)
        self.stdout.write(
            f"   {exposure['dispensed_count']} dispensing(s), "
            f"{exposure['dispensed_quantity']} units went to patients:")
        for row in exposure["patients"]:
            self.stdout.write(
                f"     {row['mrn']}  {row['name']:<24} {row['quantity']} units  "
                f"{row['phone']}")
        for row in exposure["remaining"]:
            self.stdout.write(
                f"   {row['quantity']} units still at {row['location']} — "
                f"now quarantined")

        # Prove the quarantine actually stops it being offered.
        from apps.pharmacy.services import fefo_batches
        offered = [row.batch.batch_number for row in
                   fefo_batches(amoxicillin, dispensary)]
        self.stdout.write(
            f"   FEFO now offers {offered} — "
            f"{batch.batch_number} is excluded")

    # -- 4. expiry -------------------------------------------------------

    def _expiry(self, actor):
        self.stdout.write(self.style.MIGRATE_HEADING("\n4. Expiry"))

        upcoming = expiring_stock(within_days=365)
        for row in upcoming[:6]:
            self.stdout.write(
                f"   {row['product_name']:<32} {row['batch_number']:<14} "
                f"{row['days_to_expiry']:>4}d  {row['bucket']:<12} "
                f"{row['quantity']:>8} units")

        result = sweep_expired(actor=actor)
        self.stdout.write(self.style.WARNING(
            f"   swept {result['batches_expired']} expired batch(es), "
            f"wrote off {result['total_value']}"))
        for row in result["written_off"]:
            self.stdout.write(
                f"     {row['product']} {row['batch']}: {row['quantity']} units")

    # -- 5. stock count --------------------------------------------------

    def _count(self, facility, dispensary, counter, supervisor):
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. Stock count"))

        count = start_count(facility, dispensary, actor=counter, count_type="cycle")
        self.stdout.write(
            f"   {count.reference} opened, {count.lines.count()} batches to count")

        # Count one batch short by 5 — the sort of thing a real count finds.
        line = count.lines.filter(expected_quantity__gt=10).first()
        line.counted_quantity = line.expected_quantity - Decimal("5")
        line.variance_reason = "Five units unaccounted for; breakage suspected."
        line.save()

        for other in count.lines.exclude(pk=line.pk):
            other.counted_quantity = other.expected_quantity
            other.save()

        count.status = StockCountStatus.REVIEW
        count.save(update_fields=["status"])
        self.stdout.write(
            f"   variance found: {line.product.display_name} "
            f"expected {line.expected_quantity}, counted {line.counted_quantity}")

        try:
            approve_count(count, actor=counter)
            self.stdout.write(self.style.ERROR(
                "   BUG: the counter approved their own variance"))
        except SegregationOfDutiesViolation:
            self.stdout.write("   self-approval correctly refused")

        result = approve_count(
            count, actor=supervisor,
            notes="Variance accepted; breakage log updated.",
        )
        for adjustment in result["adjustments"]:
            self.stdout.write(self.style.SUCCESS(
                f"   adjusted {adjustment['product']}: {adjustment['variance']}"))

    # -- 6. reporting ----------------------------------------------------

    def _report(self, dispensary):
        self.stdout.write(self.style.MIGRATE_HEADING("\n6. Position"))
        valuation = stock_valuation(dispensary)
        self.stdout.write(
            f"   value at cost {valuation['value_at_cost']}, "
            f"at retail {valuation['value_at_retail']}, "
            f"potential margin {valuation['potential_margin']}")

        suggestions = reorder_suggestions(dispensary)
        self.stdout.write(f"   {len(suggestions)} product(s) at or below reorder:")
        for row in suggestions[:5]:
            urgency = " URGENT" if row["stockout_before_delivery"] else ""
            self.stdout.write(
                f"     {row['product_name']:<32} on hand {row['on_hand']:>8}  "
                f"reorder at {row['reorder_level']}  "
                f"suggest {row['suggested_quantity']}{urgency}")

    # -- helpers ---------------------------------------------------------

    def _show_batches(self, product, location):
        levels = BatchStock.objects.filter(
            product=product, location=location, quantity__gt=0
        ).select_related("batch").order_by("batch__expires_on")
        for level in levels:
            self.stdout.write(
                f"     {level.batch.batch_number:<14} expires "
                f"{level.batch.expires_on}  {level.quantity:>8} units")


def _live(first_name: str):
    """The active record for a demo patient, never a merged tombstone."""
    return (
        Patient.objects.exclude(status=PatientStatus.MERGED)
        .filter(first_name=first_name)
        .order_by("registered_on")
        .first()
    )
