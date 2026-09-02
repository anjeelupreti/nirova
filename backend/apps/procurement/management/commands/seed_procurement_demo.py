"""Run the procurement chain end to end.

Exercises, through the real service layer:

1. A supplier master, including one whose drug licence has lapsed.
2. A requisition raised automatically from the reorder suggestions.
3. Approval refused for the person who raised it, then allowed.
4. Three quotations compared on **effective** unit cost — the dearest
   headline price wins because of free units.
5. Ordering from an unlicensed supplier refused outright.
6. Choosing a dearer quotation refused without a reason, then allowed.
7. Order approval refused for whoever raised it.
8. Goods receipt → quality check with a rejection → posting to stock, with
   the batch traceable back to the delivery.
9. Supplier performance measured from what actually happened.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum
from django.utils import timezone

from apps.common.exceptions import SegregationOfDutiesViolation
from apps.identity.models import User
from apps.organization.models import Facility
from apps.pharmacy.models import BatchStock, Product, StockLocation
from apps.procurement.models import Supplier, SupplierStatus
from apps.procurement.services import (
    QuotationComparisonRequired,
    SupplierNotOrderable,
    approve_order,
    compare_quotations,
    create_order,
    create_receipt,
    create_requisition,
    decide_requisition,
    post_receipt,
    procurement_dashboard,
    quality_check,
    record_quotation,
    submit_requisition,
    supplier_performance,
)
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

#: (code, name, lead time, credit days, licence expiry offset in days)
#:
#: SUP-003's licence expired last month — ordering from them must be refused
#: at the point of raising the order, not discovered at delivery.
SUPPLIERS = [
    ("SUP-001", "Nepal Pharma Distributors", 5, 30, 400),
    ("SUP-002", "Himalayan Medico Supplies", 10, 45, 250),
    ("SUP-003", "Kathmandu Drug House", 7, 30, -30),
]

#: (supplier code, unit price, free units, lead time)
#:
#: SUP-002 quotes higher per unit but gives 100 free on 500 — which makes
#: them cheaper per unit actually received. That is the point of comparing
#: on effective cost rather than sticker price.
QUOTES = [
    ("SUP-001", "8.60", 0, 5),
    ("SUP-002", "9.20", 100, 10),
]


class Command(BaseCommand):
    help = "Run the procurement chain end to end."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        organization = Organization.objects.filter(slug=options["slug"]).first()
        if organization is None:
            raise CommandError(f"No organization '{options['slug']}'.")

        buyer = User.objects.filter(email=f"manager@{options['slug']}.test").first()
        approver = User.objects.filter(email=f"owner@{options['slug']}.test").first()

        with tenant_context(context_for_organization(organization)):
            facility = (
                Facility.objects.filter(facility_type="pharmacy").first()
                or Facility.objects.filter(facility_type="clinic").first()
            )
            if facility is None:
                raise CommandError("No facility. Run `seed_demo` first.")

            location = StockLocation.objects.filter(
                facility=facility, is_dispensable=True
            ).first()
            if location is None:
                raise CommandError("No dispensary. Run `seed_pharmacy_demo` first.")

            self._ensure_module(organization)
            self._suppliers()
            # Stashed so `_work_in_progress` can approve the order it raises
            # without threading the approver through every call in between.
            self._approver = approver
            requisition = self._requisition(organization, facility, location,
                                            buyer, approver)
            quotation = self._quotations(requisition, buyer)
            self._blocked_supplier(organization, facility, buyer)
            order = self._order(organization, facility, requisition, quotation,
                                location, buyer, approver)
            self._receive(order, location, buyer, approver)
            self._work_in_progress(organization, facility, location, buyer)
            self._performance(facility)

    # -- setup -----------------------------------------------------------

    def _ensure_module(self, organization):
        from apps.catalog.keys import ModuleCode
        from apps.entitlements.resolver import resolve_entitlements

        if not resolve_entitlements(organization).has_module(ModuleCode.PROCUREMENT):
            raise CommandError(
                "The procurement module is not in this subscription. That is "
                "the entitlement engine working; attach the add-on to proceed."
            )

    def _suppliers(self):
        today = timezone.localdate()
        for code, name, lead, credit, licence_offset in SUPPLIERS:
            Supplier.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "pan_number": f"6{code[-3:]}00000",
                    "contact_person": "Sales desk",
                    "phone": "+977-1-5550000",
                    "district": "Kathmandu",
                    "agreed_lead_time_days": lead,
                    "credit_days": credit,
                    "credit_limit": Decimal("500000.00"),
                    "drug_licence_number": f"DDA/{code}",
                    "drug_licence_expires_on": today + timedelta(days=licence_offset),
                    "status": SupplierStatus.ACTIVE,
                },
            )
        expired = Supplier.objects.get(code="SUP-003")
        self.stdout.write(
            f"  {len(SUPPLIERS)} suppliers; {expired.name} has a licence that "
            f"expired {expired.drug_licence_expires_on}")

    # -- 1. requisition --------------------------------------------------

    def _requisition(self, organization, facility, location, buyer, approver):
        amoxicillin = Product.objects.get(code="MED-001")
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n1. Requisition"))

        requisition = create_requisition(
            organization, facility,
            items=[{
                "product": amoxicillin,
                "quantity": Decimal("500"),
                "estimated_unit_price": Decimal("8.50"),
                "notes": "Cover for the next quarter",
            }],
            actor=buyer, location=location,
            justification="Stock will not cover projected demand.",
        )
        line = requisition.lines.first()
        self.stdout.write(
            f"   {requisition.reference}: {line.product_name} × {line.quantity}")
        self.stdout.write(
            f"   stock when raised: {line.stock_on_hand} "
            f"(reorder at {line.reorder_level}) — frozen so the approver sees "
            f"what the requester saw")

        submit_requisition(requisition, actor=buyer)

        try:
            decide_requisition(requisition, approve=True, actor=buyer)
            self.stdout.write(self.style.ERROR(
                "   BUG: the requester approved their own requisition"))
        except SegregationOfDutiesViolation:
            self.stdout.write("   self-approval correctly refused")

        decide_requisition(requisition, approve=True, actor=approver,
                           notes="Agreed; order against the best quotation.")
        self.stdout.write(self.style.SUCCESS(
            f"   approved by {approver.full_name}"))
        return requisition

    # -- 2. quotations ---------------------------------------------------

    def _quotations(self, requisition, buyer):
        amoxicillin = Product.objects.get(code="MED-001")
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. Quotations"))

        for code, price, free, lead in QUOTES:
            supplier = Supplier.objects.get(code=code)
            record_quotation(
                requisition, supplier,
                lines=[{
                    "product": amoxicillin,
                    "quantity": Decimal("500"),
                    "unit_price": Decimal(price),
                    "free_quantity": Decimal(free),
                }],
                actor=buyer,
                valid_until=timezone.localdate() + timedelta(days=30),
                quoted_lead_time_days=lead,
            )

        comparison = compare_quotations(requisition)
        for row in comparison["quotations"]:
            free = row["lines"][0]["free_quantity"]
            self.stdout.write(
                f"   {row['supplier']:<30} total {row['total_value']:>9}  "
                f"units {float(row['total_units']):>5.0f} "
                f"(free {float(free):>4.0f})  "
                f"per unit {row['cost_per_unit']:>6}  "
                f"lead {row['lead_time_days']}d")

        cheapest = next(
            r for r in comparison["quotations"]
            if r["uuid"] == comparison["cheapest"]
        )
        self.stdout.write(self.style.SUCCESS(
            f"   cheapest per unit: {cheapest['supplier']} "
            f"at {cheapest['cost_per_unit']} "
            f"(total {cheapest['total_value']})"))
        self.stdout.write(
            "   the higher total wins on cost per unit because of the free "
            "stock — ranking on the total would pick the wrong supplier")

        # Deliberately choose the *other* one, to exercise the control.
        dearer = next(
            r for r in comparison["quotations"]
            if r["uuid"] != comparison["cheapest"]
        )
        from apps.procurement.models import Quotation
        return Quotation.objects.get(uuid=dearer["uuid"])

    # -- 3. an unlicensed supplier ---------------------------------------

    def _blocked_supplier(self, organization, facility, buyer):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n3. Ordering from an unlicensed supplier"))
        expired = Supplier.objects.get(code="SUP-003")
        amoxicillin = Product.objects.get(code="MED-001")

        try:
            create_order(
                organization, facility, expired,
                lines=[{"product": amoxicillin, "quantity": Decimal("100"),
                        "unit_price": Decimal("8.00")}],
                actor=buyer,
            )
            self.stdout.write(self.style.ERROR(
                "   BUG: ordered from a supplier with an expired licence"))
        except SupplierNotOrderable as exc:
            self.stdout.write(f"   correctly refused: {exc.message}")

    # -- 4. the order ----------------------------------------------------

    def _order(self, organization, facility, requisition, quotation, location,
               buyer, approver):
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n4. Order from {quotation.supplier.name} (not the cheapest)"))
        line = quotation.lines.first()
        requisition_line = requisition.lines.first()

        order_lines = [{
            "product": line.product,
            "quantity": line.quantity,
            "unit_price": line.unit_price,
            "free_quantity": line.free_quantity,
            "requisition_line": requisition_line,
        }]

        try:
            create_order(
                organization, facility, quotation.supplier, order_lines,
                actor=buyer, requisition=requisition, quotation=quotation,
                deliver_to=location,
            )
            self.stdout.write(self.style.ERROR(
                "   BUG: chose a dearer quotation with no reason given"))
        except QuotationComparisonRequired:
            self.stdout.write(
                "   correctly refused — a dearer quotation needs a reason")

        order = create_order(
            organization, facility, quotation.supplier, order_lines,
            actor=buyer, requisition=requisition, quotation=quotation,
            deliver_to=location,
            selection_reason="Five-day shorter lead time and a longer credit "
                             "period; stock cover is tight.",
        )
        self.stdout.write(self.style.SUCCESS(
            f"   {order.reference} raised for {order.total}, "
            f"expected {order.expected_delivery}"))

        requisition.refresh_from_db()
        self.stdout.write(f"   requisition now {requisition.status}")

        try:
            approve_order(order, actor=buyer)
            self.stdout.write(self.style.ERROR(
                "   BUG: the buyer approved their own order"))
        except SegregationOfDutiesViolation:
            self.stdout.write("   self-approval correctly refused")

        approve_order(order, actor=approver)
        self.stdout.write(self.style.SUCCESS(
            f"   approved by {approver.full_name}"))
        return order

    # -- 5. receiving ----------------------------------------------------

    def _receive(self, order, location, buyer, approver):
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. Goods receipt"))
        order_line = order.lines.first()

        receipt = create_receipt(
            order, location,
            lines=[{
                "product": order_line.product,
                "batch_number": "AMX-2026-D",
                "expires_on": timezone.localdate() + timedelta(days=500),
                "received_quantity": order_line.quantity,
                "free_quantity": order_line.free_quantity,
                "unit_cost": order_line.unit_price,
                "selling_price": Decimal("12.00"),
                "mrp": Decimal("14.00"),
                "order_line": order_line,
            }],
            actor=buyer,
            delivery_note_number="DN-88214",
            supplier_invoice_number="INV-HMS-4471",
            supplier_invoice_amount=order.total,
        )
        line = receipt.lines.first()
        self.stdout.write(
            f"   {receipt.reference}: {line.received_quantity} + "
            f"{line.free_quantity} free, batch {line.batch_number}")
        self.stdout.write("   nothing in stock yet — awaiting quality check")

        quality_check(
            receipt,
            rejections=[{
                "line_uuid": str(line.uuid),
                "quantity": "20",
                "reason": "Outer carton crushed; 20 strips unusable.",
            }],
            actor=approver,
            notes="Remainder inspected and acceptable.",
        )
        receipt.refresh_from_db()
        line.refresh_from_db()
        self.stdout.write(self.style.WARNING(
            f"   {receipt.status}: {line.rejected_quantity} rejected, "
            f"{line.accepted_quantity} accepted"))

        before = self._stock_for(order_line.product, location)
        result = post_receipt(receipt, actor=buyer)
        after = self._stock_for(order_line.product, location)

        for batch in result["batches"]:
            self.stdout.write(self.style.SUCCESS(
                f"   posted {batch['quantity']} of {batch['product']} "
                f"batch {batch['batch']} @ {batch['unit_cost']}/unit"))
        # Only claim dilution when there actually was free stock. Asserting it
        # unconditionally is how the arithmetic bug hid: the narration said
        # "diluted" while the number had gone up.
        if order_line.free_quantity:
            self.stdout.write(
                f"   free stock dilutes the unit cost — "
                f"{order_line.unit_price} paid, "
                f"{result['batches'][0]['unit_cost']} effective")
        else:
            self.stdout.write(
                f"   unit cost {result['batches'][0]['unit_cost']} — unchanged "
                f"by the rejection, because rejected stock is credited by the "
                f"supplier rather than loaded onto what was kept")
        self.stdout.write(f"   stock at {location.code}: {before} → {after}")

        receipt.refresh_from_db()
        order.refresh_from_db()
        self.stdout.write(
            f"   invoice matches what arrived: {receipt.invoice_matches}")
        self.stdout.write(f"   order now {order.status}")

    def _stock_for(self, product, location):
        total = BatchStock.objects.filter(
            product=product, location=location
        ).aggregate(total=Sum("quantity"))
        return total["total"] or Decimal("0")

    # -- 6. performance --------------------------------------------------

    def _work_in_progress(self, organization, facility, location, buyer):
        """Leave real work sitting in the queue.

        A seed that runs every chain to completion produces a screen with
        nothing on it, which is the one state a work queue must not be tested
        in. Two documents are deliberately left mid-flight: one waiting on an
        approver, one waiting on an inspector. Both are ordinary states that a
        buyer opening the screen on a Monday morning would actually see.
        """
        self.stdout.write(self.style.MIGRATE_HEADING("\n6. Left in the queue"))

        product = Product.objects.filter(is_active=True).first()
        if product is None:
            return

        pending = create_requisition(
            organization=organization,
            facility=facility,
            items=[{
                "product": product,
                "quantity": Decimal("300"),
                "estimated_unit_price": Decimal("8.80"),
                "notes": "Winter demand; last two months ran short.",
            }],
            actor=buyer,
            location=location,
            is_urgent=True,
            required_by=timezone.localdate() + timedelta(days=14),
            justification=(
                "Consumption has run ahead of the reorder level for two "
                "consecutive months and the current cover is under three weeks."
            ),
        )
        submit_requisition(pending, actor=buyer)
        pending.refresh_from_db()
        self.stdout.write(
            f"   {pending.reference} is {pending.status} — waiting on an "
            "approver, and the approver cannot be the requester")

        # A second delivery, received but not yet inspected. Stock is on the
        # premises and deliberately not on the shelf: nothing may be dispensed
        # until somebody has looked at it.
        # A second delivery, received but not yet inspected. Stock is on the
        # premises and deliberately not on the shelf: nothing may be dispensed
        # until somebody has looked at it. Raised directly rather than reusing
        # an existing order, because every order in the demo has already been
        # received — and an order that is already partially received is not
        # the state a first inspection happens in.
        supplier = Supplier.objects.filter(status=SupplierStatus.ACTIVE).first()
        order = create_order(
            organization=organization,
            facility=facility,
            supplier=supplier,
            lines=[{
                "product": product,
                "quantity": Decimal("400"),
                "unit_price": Decimal("1.15"),
                "free_quantity": Decimal("0"),
            }],
            actor=buyer,
            deliver_to=location,
            expected_delivery=timezone.localdate() + timedelta(days=4),
            notes="Top-up order, seeded to leave a delivery for inspection.",
        )
        approve_order(order, actor=self._approver)
        order.refresh_from_db()

        order_line = order.lines.first()
        receipt = create_receipt(
            order, location,
            lines=[{
                "product": order_line.product,
                "batch_number": "PCM-2026-E",
                "expires_on": timezone.localdate() + timedelta(days=420),
                "received_quantity": order_line.quantity,
                "free_quantity": order_line.free_quantity,
                "unit_cost": order_line.unit_price,
                "selling_price": Decimal("2.20"),
                "mrp": Decimal("2.50"),
                "order_line": order_line,
            }],
            actor=buyer,
            delivery_note_number="DN-90117",
        )
        self.stdout.write(
            f"   {receipt.reference} is {receipt.status} — on the premises, "
            "not on the shelf, until somebody inspects it")


    def _performance(self, facility):
        self.stdout.write(self.style.MIGRATE_HEADING("\n7. Position"))
        for supplier in Supplier.objects.all():
            stats = supplier_performance(supplier)
            if not stats["orders"]:
                continue
            self.stdout.write(
                f"   {stats['supplier']:<30} orders {stats['orders']}  "
                f"fill rate {stats['fill_rate_percent']}%  "
                f"rejection {stats['rejection_rate_percent']}%")
            if stats["measured_lead_time_days"] is not None:
                self.stdout.write(
                    f"     agreed {stats['agreed_lead_time_days']}d, "
                    f"measured {stats['measured_lead_time_days']}d "
                    f"(variance {stats['lead_time_variance']:+d}d)")

        dashboard = procurement_dashboard(facility)
        self.stdout.write(
            f"   open orders {dashboard['orders_open']} worth "
            f"{dashboard['open_order_value']}, "
            f"{dashboard['orders_overdue']} overdue")
        self.stdout.write(
            f"   licences expiring within 60 days: "
            f"{dashboard['licences_expiring']}")
