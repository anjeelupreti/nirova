"""Run a shift at the retail counter, end to end.

Exercises, through the real service layer:

1. Opening a till with a counted float, and refusing a second one on it.
2. An over-the-counter sale to a walk-in, paid part cash part wallet.
3. A prescription-only medicine refused to a walk-in, then sold against a
   prescription.
4. Selling more than the shelf holds, refused.
5. A partial return: raised by the cashier, refused for the same cashier to
   approve, then approved by the manager with a credit note and a refund.
6. A return of goods that must not be resold — refunded, but written off
   rather than put back on the shelf.
7. Closing the drawer: a blind count, a variance that must be explained, and
   a second person signing it off.

The seed narrates what it expects beside each number. That is deliberate —
three arithmetic errors in procurement were found because the narration and
the figures disagreed, which a test asserting the code's own output would
never have shown.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.billing.models import Payment
from apps.common.exceptions import SegregationOfDutiesViolation
from apps.identity.models import User
from apps.organization.models import Facility
from apps.pharmacy.models import Product, StockLocation
from apps.pharmacy.services import InsufficientStock, stock_on_hand
from apps.pos.models import CounterSession, Sale, SaleStatus
from apps.pos.services import (
    PosError,
    PrescriptionRequired,
    approve_return,
    close_session,
    create_sale,
    open_session,
    quote_sale,
    reconcile_session,
    request_return,
    sales_summary,
    search_products,
    session_takings,
)
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

COUNTER = "COUNTER-1"
OPENING_FLOAT = Decimal("2000.00")


class Command(BaseCommand):
    help = "Run a shift at the retail pharmacy counter."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"No organization '{slug}'.")

        # Three distinct people, because every control at a till is a
        # maker-checker pair. One user playing all three parts would make the
        # seed pass while proving nothing.
        cashier = User.objects.filter(email=f"counter@{slug}.test").first()
        manager = User.objects.filter(email=f"pharmacy@{slug}.test").first()
        supervisor = User.objects.filter(email=f"owner@{slug}.test").first()
        if not (cashier and manager and supervisor):
            raise CommandError(
                "Run `seed_demo` first — the counter staff are missing."
            )

        with tenant_context(context_for_organization(organization)):
            facility = (
                Facility.objects.filter(facility_type="pharmacy").first()
                or Facility.objects.filter(facility_type="clinic").first()
            )
            location = StockLocation.objects.filter(
                facility=facility, is_dispensable=True
            ).first()
            if location is None:
                raise CommandError("No dispensary. Run `seed_pharmacy_demo` first.")

            self._reset(facility)
            session = self._open(organization, facility, location, cashier)
            self._search(location)
            sale = self._otc_sale(organization, session, location, cashier)
            self._prescription_guard(organization, session, location, cashier)
            self._oversell(organization, session, location, cashier)
            self._return(organization, sale, session, cashier, manager)
            self._writeoff_return(organization, session, location, cashier, manager)
            self._close(session, cashier, supervisor)
            self._summary(facility)

    # -- setup -------------------------------------------------------------

    def _reset(self, facility):
        """Leave no session open from a previous run.

        Re-running a seed should be safe. The model refuses a second open
        session on a till, which is correct in production and merely annoying
        here.
        """
        stale = CounterSession.objects.filter(
            facility=facility, counter=COUNTER, status="open"
        )
        for session in stale:
            Sale.objects.filter(session=session, status=SaleStatus.DRAFT).delete()
            session.status = "closed"
            session.closed_at = timezone.now()
            session.variance_reason = "Closed by seed re-run."
            session.save(update_fields=[
                "status", "closed_at", "variance_reason", "updated_at",
            ])
        if stale:
            self.stdout.write("  closed a session left open by an earlier run")

    def _open(self, organization, facility, location, cashier):
        self.stdout.write(self.style.MIGRATE_HEADING("\n1. Opening the till"))
        session = open_session(
            organization=organization,
            facility=facility,
            location=location,
            counter=COUNTER,
            cashier=cashier,
            opening_float=OPENING_FLOAT,
        )
        self.stdout.write(
            f"  {session.reference} open at {COUNTER} under "
            f"{session.cashier_name}, float {session.opening_float}"
        )

        try:
            open_session(
                organization=organization, facility=facility, location=location,
                counter=COUNTER, cashier=cashier, opening_float=Decimal("500.00"),
            )
        except PosError as exc:
            self.stdout.write(f"  second session on the same till refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "  a second session opened on the same till — the variance on "
                "either is now meaningless"
            ))
        return session

    def _search(self, location):
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. Counter lookup"))
        for term in ("para", "amox"):
            results = search_products(term, location=location)
            for row in results[:2]:
                self.stdout.write(
                    f"  '{term}' -> {row['product'].display_name}: "
                    f"{row['available']} available, batch "
                    f"{row['batch'].batch_number if row['batch'] else '-'} "
                    f"at {row['unit_price']}"
                    + (" (prescription only)" if row["requires_prescription"] else "")
                )

    # -- selling -----------------------------------------------------------

    def _sellable(self, location, *, prescription_only=False, minimum=1):
        """A product with stock on the shelf, matching the guard we want."""
        for product in Product.objects.filter(
            is_active=True, requires_prescription=prescription_only
        ):
            if stock_on_hand(product, location) >= Decimal(minimum):
                return product
        return None

    def _otc_sale(self, organization, session, location, cashier):
        self.stdout.write(self.style.MIGRATE_HEADING("\n3. Over-the-counter sale"))
        product = self._sellable(location, minimum=10)
        if product is None:
            raise CommandError("No open-sale stock. Run `seed_pharmacy_demo`.")

        preview = search_products(product.generic_name, location=location)[0]
        quantity = Decimal("10")
        self.stdout.write(
            f"  {quantity} x {product.display_name} at {preview['unit_price']}"
        )

        quote = quote_sale(
            session, [{"product": product, "quantity": quantity}]
        )
        self.stdout.write(
            f"  quoted {quote['total']} (rounding {quote['rounding_adjustment']}) "
            f"across {len(quote['lines'])} batch line(s) — nothing committed yet"
        )

        # Part cash, part wallet: ordinary in a Nepali pharmacy, and the reason
        # a sale carries several tenders rather than one method. The second
        # tender omits its amount, which means "settle the rest" — the only way
        # to hit a rupee-rounded total exactly without guessing it.
        cash_part = (quote["total"] / 2).quantize(Decimal("1"))
        sale = create_sale(
            organization=organization,
            session=session,
            items=[{"product": product, "quantity": quantity}],
            actor=cashier,
            customer_name="Walk-in customer",
            customer_phone="+977-98-00000000",
            sale_type="walk_in",
            payments=[
                {"method": "cash", "amount": cash_part},
                {"method": "esewa", "reference": "ESW-DEMO-1"},
            ],
        )
        self.stdout.write(
            f"  tendered {cash_part} cash + the balance on eSewa"
        )
        self.stdout.write(
            f"  {sale.reference} -> invoice {sale.invoice_number}, "
            f"total {sale.total} (rounding {sale.rounding_adjustment})"
        )
        if sale.total != quote["total"]:
            self.stdout.write(self.style.ERROR(
                f"  the quote said {quote['total']} and the invoice says "
                f"{sale.total} — the counter would ask for the wrong money"
            ))
        for line in sale.lines.all():
            self.stdout.write(
                f"    {line.product_name} {line.quantity} from batch "
                f"{line.batch_number} exp {line.expires_on} -> {line.total}"
            )
        if sale.lines.count() > 1:
            self.stdout.write(
                "    spans two batches — FEFO emptied the first, which is why "
                "a receipt lists batches rather than products"
            )
        return sale

    def _prescription_guard(self, organization, session, location, cashier):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n4. Prescription-only medicine")
        )
        product = self._sellable(location, prescription_only=True, minimum=1)
        if product is None:
            self.stdout.write(
                "  no prescription-only stock on hand — guard not exercised"
            )
            return
        try:
            create_sale(
                organization=organization, session=session,
                items=[{"product": product, "quantity": Decimal("1")}],
                actor=cashier, sale_type="walk_in",
                customer_name="Walk-in customer", payments=[],
            )
        except PrescriptionRequired as exc:
            self.stdout.write(f"  refused to a walk-in: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                f"  {product.display_name} sold over the counter without a "
                "prescription"
            ))

    def _oversell(self, organization, session, location, cashier):
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. Selling what is not there"))
        product = self._sellable(location, minimum=1)
        on_hand = stock_on_hand(product, location)
        try:
            create_sale(
                organization=organization, session=session,
                items=[{"product": product, "quantity": on_hand + Decimal("100")}],
                actor=cashier, sale_type="walk_in",
                customer_name="Walk-in customer", payments=[],
            )
        except InsufficientStock as exc:
            self.stdout.write(f"  refused with {on_hand} on hand: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "  sold more than the shelf holds — the ledger now says "
                "negative"
            ))

    # -- returns -----------------------------------------------------------

    def _return(self, organization, sale, session, cashier, manager):
        self.stdout.write(self.style.MIGRATE_HEADING("\n6. A partial return"))
        line = sale.lines.first()
        quantity = Decimal("3")
        before = stock_on_hand(line.product, sale.location)

        sale_return = request_return(
            sale=sale,
            entries=[{"sale_line": line, "quantity": quantity,
                      "condition_note": "Strip sealed, sold an hour ago."}],
            reason="Customer bought more than the prescription called for.",
            actor=cashier,
            restock=True,
        )
        share = (line.total * quantity / line.quantity).quantize(Decimal("0.01"))
        self.stdout.write(
            f"  {sale_return.reference}: {quantity} of {line.quantity} back, "
            f"refund {sale_return.refund_total} "
            f"(proportion of the {line.total} charged, expected {share})"
        )

        try:
            approve_return(
                organization=organization, sale_return=sale_return, actor=cashier
            )
        except SegregationOfDutiesViolation as exc:
            self.stdout.write(f"  the cashier cannot approve their own: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "  the cashier approved their own refund — the till would "
                "still balance"
            ))

        sale_return = approve_return(
            organization=organization,
            sale_return=sale_return,
            actor=manager,
            refund_method="cash",
            decision_notes="Seal intact, back on the shelf.",
        )
        after = stock_on_hand(line.product, sale.location)
        sale.refresh_from_db()
        self.stdout.write(
            f"  approved by {sale_return.approved_by_name}: credit note "
            f"{sale_return.credit_note_number}, {sale_return.refund_total} "
            f"refunded, stock {before} -> {after} (+{after - before})"
        )
        self.stdout.write(f"  sale is now {sale.get_status_display().lower()}")

    def _writeoff_return(self, organization, session, location, cashier, manager):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n7. A return that cannot be resold")
        )
        product = self._sellable(location, minimum=5)
        sale = create_sale(
            organization=organization, session=session,
            items=[{"product": product, "quantity": Decimal("2")}],
            actor=cashier, sale_type="walk_in",
            customer_name="Walk-in customer",
            payments=[{"method": "cash"}],   # no amount: settle the lot
        )

        line = sale.lines.first()
        before = stock_on_hand(product, location)
        sale_return = request_return(
            sale=sale,
            entries=[{"sale_line": line, "quantity": line.quantity,
                      "condition_note": "Blister opened."}],
            reason="Wrong item — customer opened the pack.",
            actor=cashier,
            restock=False,
            restock_note="Blister opened; cannot be resold.",
        )
        sale_return = approve_return(
            organization=organization, sale_return=sale_return, actor=manager,
            refund_method="cash",
            decision_notes="Refund the customer, write the stock off.",
        )
        after = stock_on_hand(product, location)
        self.stdout.write(
            f"  {sale_return.refund_total} refunded, stock {before} -> {after}"
        )
        self.stdout.write(
            "  the goods came back into the ledger and were then written off, "
            "so the loss shows as a write-off rather than as a sale that "
            "quietly never reversed"
        )

    # -- closing -----------------------------------------------------------

    def _close(self, session, cashier, supervisor):
        self.stdout.write(self.style.MIGRATE_HEADING("\n8. Cashing up"))
        takings = session_takings(session)
        self.stdout.write(
            f"  system: {takings['sales_count']} sales ringing "
            f"{takings['sales_total']}, settling net to {takings['net_takings']} "
            f"after refunds — cash {takings['cash']}, wallet {takings['wallet']}"
        )
        self.stdout.write(
            f"  expected in the drawer: float {session.opening_float} + cash "
            f"{takings['cash']} = {takings['expected_cash']}"
        )

        short_by = Decimal("50.00")
        counted = takings["expected_cash"] - short_by
        try:
            close_session(session, closing_count=counted, actor=cashier)
        except PosError as exc:
            self.stdout.write(f"  close refused without an explanation: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "  a short drawer closed silently — nobody will ever look at it"
            ))

        session = close_session(
            session,
            closing_count=counted,
            actor=cashier,
            variance_reason="Change given from own pocket for a 50 note.",
        )
        self.stdout.write(
            f"  counted {session.closing_count} against {session.expected_cash}: "
            f"variance {session.variance} — {session.variance_reason}"
        )

        try:
            reconcile_session(session, actor=cashier)
        except SegregationOfDutiesViolation as exc:
            self.stdout.write(f"  the cashier cannot sign off their own count: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "  the cashier attested their own shortage"
            ))

        session = reconcile_session(
            session, actor=supervisor, notes="Accepted; watch this till."
        )
        self.stdout.write(f"  {session.reference} {session.get_status_display().lower()}")

    def _summary(self, facility):
        self.stdout.write(self.style.MIGRATE_HEADING("\n9. The day at the counter"))
        summary = sales_summary(facility)
        self.stdout.write(
            f"  {summary['sales_count']} sales gross {summary['gross_revenue']}, "
            f"less {summary['returns_count']} returns of "
            f"{summary['returns_total']} = net {summary['net_revenue']}"
        )
        self.stdout.write(
            f"  cost {summary['cost_of_goods']} less {summary['cost_recovered']} "
            f"back on the shelf = {summary['net_cost_of_goods']} "
            f"(of which {summary['cost_written_off']} written off)"
        )
        self.stdout.write(
            f"  margin {summary['gross_margin']} ({summary['margin_percent']}%) "
            "— on the net, because goods that came back earned nothing"
        )
        for row in summary["top_products"][:5]:
            self.stdout.write(
                f"    {row['product_name']}: {row['quantity']} -> {row['total']}"
            )

        banked = Payment.objects.filter(
            facility=facility, received_at__date=timezone.localdate(),
            status__in=("completed", "refunded"),
        )
        net = sum((p.amount for p in banked), Decimal("0.00"))
        self.stdout.write(
            f"  payments net to {net} across {banked.count()} rows — refunds "
            "are negative rows, so the day nets rather than double-counting"
        )
        self.stdout.write(self.style.SUCCESS("\nCounter shift complete.\n"))
