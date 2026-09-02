"""The counter: opening a till, selling, taking money, handing goods back.

Every sale touches three modules and this is the only place that knows how to
sequence them:

    pharmacy   stock leaves the shelf   (FEFO allocation, ledger movement)
    billing    money is asked for       (tax invoice, payments)
    pos        the counter's own state  (which till, which cashier, which shift)

The order is deliberate. **Stock moves first.** If the ledger posting fails —
the batch was quarantined a second ago, someone else took the last three
tablets — nothing has been billed and the customer is told before they pay. The
reverse order would take money for goods that turn out not to exist, and
refunding that is far more expensive than declining the sale.
"""

import logging
from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: the append-only audit trail. Cash handling is the highest-fraud
# surface in a pharmacy, so opening a till, voiding a sale and approving a
# return all leave a row somebody can be asked about.
from apps.audit.services import record
from apps.billing.models import PaymentMethod, PaymentStatus
from apps.billing.services import (
    BANKED_STATUSES,
    create_retail_invoice,
    money,
    record_counter_refund,
    record_payment,
)
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.entitlements.services import require_module
from apps.pharmacy.models import (
    Batch,
    MovementType,
    Product,
    StockLocation,
)
from apps.pharmacy.services import (
    InsufficientStock,
    allocate_fefo,
    post_movement,
    quantise,
)
from apps.pos.models import (
    MONEY_ZERO,
    ZERO,
    CounterSession,
    Sale,
    SaleLine,
    SaleReturn,
    SaleReturnLine,
    SaleReturnStatus,
    SaleStatus,
    SaleType,
    SessionStatus,
)
# assert_different_actors: maker-checker. The cashier who took the money may
# not be the one who approves handing it back.
from apps.rbac.services import assert_different_actors
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.pos")

PAISA = Decimal("0.01")
#: Nepali counters settle in whole rupees; the paisa goes to rounding.
RUPEE = Decimal("1")

#: Methods that put notes in the drawer. Everything else settles elsewhere and
#: on its own schedule, so it has no business in a cash variance.
CASH_METHODS = {PaymentMethod.CASH}

#: Sale types that may leave money owed at the end of the transaction.
#: A walk-in pays now; a corporate account and an insurer are billed.
CREDIT_SALE_TYPES = {SaleType.CORPORATE, SaleType.INSURANCE, SaleType.STAFF}


class PosError(DomainError):
    code = "pos_operation_failed"


class SessionClosed(PosError):
    code = "counter_session_closed"
    message = "This till session is closed. Open a new one to sell."


class PrescriptionRequired(PosError):
    code = "prescription_required"
    status_code = 422


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


def _next_reference(model, prefix: str) -> str:
    """A human-sayable, per-day sequential reference.

    Deliberately not the statutory invoice number — that is allocated by
    `billing.allocate_number` under a lock and must be gapless. This one is
    for people to read out over a counter, so a gap in it costs nothing.
    """
    today = timezone.localdate()
    stem = f"{prefix}{today:%y%m%d}"
    last = (
        model.all_objects.filter(reference__startswith=stem)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    serial = int(last[len(stem):]) + 1 if last else 1
    return f"{stem}{serial:04d}"


# ---------------------------------------------------------------------------
# Till sessions
# ---------------------------------------------------------------------------


@tenant_atomic_method
def open_session(
    organization,
    facility,
    location: StockLocation,
    counter: str,
    cashier,
    opening_float=MONEY_ZERO,
) -> CounterSession:
    """Start a shift at a till.

    The opening float is counted by the cashier and typed in, not carried over
    from the last session. Carrying it over would mean an unexplained shortage
    silently becomes next shift's starting position, and nobody ever owns it.
    """
    require_module(organization, ModuleCode.PHARMACY)

    open_here = CounterSession.objects.filter(
        facility=facility, counter=counter, status=SessionStatus.OPEN
    ).first()
    if open_here is not None:
        raise PosError(
            f"{counter} already has an open session under "
            f"{open_here.cashier_name}. Close it before opening another.",
            detail={"session": open_here.reference},
        )

    session = CounterSession.objects.create(
        reference=_next_reference(CounterSession, "TS"),
        facility=facility,
        location=location,
        counter=counter,
        cashier_id=cashier.uuid,
        cashier_name=getattr(cashier, "full_name", "") or cashier.email,
        opening_float=money(opening_float),
        created_by_id=cashier.uuid,
    )
    record(
        AuditAction.CREATE,
        entity_type="pos.CounterSession",
        entity_id=session.uuid,
        entity_label=f"{session.reference} opened at {counter}",
        metadata={"opening_float": str(session.opening_float)},
    )
    return session


def session_takings(session: CounterSession) -> dict:
    """What the system believes passed through this till.

    Computed from the payment rows, never accumulated on the session as sales
    happen. A running counter drifts the moment anything is voided or a
    refund is posted out of band; a query cannot.
    """
    from apps.billing.models import Payment  # local: avoids a circular import

    rows = Payment.objects.filter(
        counter=session.reference, status__in=BANKED_STATUSES
    ).values("method").annotate(total=models.Sum("amount"))
    by_method = {row["method"]: money(row["total"] or MONEY_ZERO) for row in rows}

    cash = sum((by_method.get(m, MONEY_ZERO) for m in CASH_METHODS), MONEY_ZERO)
    card = by_method.get(PaymentMethod.CARD, MONEY_ZERO)
    wallet = sum(
        (
            by_method.get(m, MONEY_ZERO)
            for m in (
                PaymentMethod.ESEWA, PaymentMethod.KHALTI,
                PaymentMethod.IME_PAY, PaymentMethod.FONEPAY,
            )
        ),
        MONEY_ZERO,
    )
    credit = by_method.get(PaymentMethod.CREDIT, MONEY_ZERO)

    sales = Sale.objects.filter(session=session).exclude(status=SaleStatus.VOIDED)
    return {
        "session": session,
        "by_method": by_method,
        "cash": money(cash),
        "card": money(card),
        "wallet": money(wallet),
        "credit": money(credit),
        "sales_count": sales.count(),
        #: What was rung up. Refunds are separate rows and are *not* deducted
        #: here -- a cashier reconciling a till needs to see both, because
        #: "we sold 24 and gave 10 back" and "we sold 14" are different days.
        "sales_total": money(
            sales.aggregate(t=models.Sum("total"))["t"] or MONEY_ZERO
        ),
        #: What actually settled, refunds included. This is the figure that
        #: matches the drawer.
        "net_takings": money(sum(by_method.values(), MONEY_ZERO)),
        "expected_cash": money(session.opening_float + cash),
    }


@tenant_atomic_method
def close_session(
    session: CounterSession,
    closing_count,
    actor=None,
    variance_reason: str = "",
    notes: str = "",
) -> CounterSession:
    """Count the drawer and record the difference.

    The counted figure is taken as given and the variance recorded whether or
    not it is zero — the same reason a stock count is blind. A close that
    silently accepted whatever the system expected would never surface a
    shortage, which is the only thing this procedure exists to find.
    """
    if session.status != SessionStatus.OPEN:
        raise SessionClosed(detail={"status": session.status})

    open_sales = Sale.objects.filter(
        session=session, status=SaleStatus.DRAFT
    ).count()
    if open_sales:
        raise PosError(
            f"{open_sales} sale(s) are still in progress at this till.",
            detail={"draft_sales": open_sales},
        )

    takings = session_takings(session)
    counted = money(closing_count)
    variance = money(counted - takings["expected_cash"])

    # A discrepancy has to be explained. Not to punish the cashier — most are
    # a mis-keyed tender or change given from a pocket — but because an
    # unexplained variance that recurs is the signal, and it is only visible
    # if each one was written down at the time.
    if variance != MONEY_ZERO and not variance_reason.strip():
        raise PosError(
            f"The drawer is {'over' if variance > 0 else 'short'} by "
            f"{abs(variance)}. Record why before closing.",
            detail={
                "expected": str(takings["expected_cash"]),
                "counted": str(counted),
                "variance": str(variance),
            },
        )

    session.closing_count = counted
    session.expected_cash = takings["expected_cash"]
    session.variance = variance
    session.variance_reason = variance_reason
    session.card_total = takings["card"]
    session.wallet_total = takings["wallet"]
    session.credit_total = takings["credit"]
    session.status = SessionStatus.CLOSED
    session.closed_at = timezone.now()
    session.notes = notes
    session.save(
        update_fields=[
            "closing_count", "expected_cash", "variance", "variance_reason",
            "card_total", "wallet_total", "credit_total", "status",
            "closed_at", "notes", "updated_at",
        ]
    )

    record(
        AuditAction.UPDATE,
        entity_type="pos.CounterSession",
        entity_id=session.uuid,
        entity_label=f"{session.reference} closed",
        reason=variance_reason,
        metadata={
            "expected": str(session.expected_cash),
            "counted": str(counted),
            "variance": str(variance),
        },
    )
    if variance != MONEY_ZERO:
        logger.warning(
            "TILL VARIANCE %s at %s: expected %s counted %s (%s) — %s",
            session.reference, session.counter, session.expected_cash,
            counted, variance, variance_reason,
        )
    return session


@tenant_atomic_method
def reconcile_session(session: CounterSession, actor, notes: str = "") -> CounterSession:
    """Sign off a closed session.

    A second person accepts the variance. The cashier counted the drawer;
    somebody else agrees that is what was there. Without the second signature
    a shortage is only ever attested by the person it would implicate.
    """
    if session.status != SessionStatus.CLOSED:
        raise PosError(
            f"Only a closed session can be reconciled; this one is "
            f"{session.get_status_display().lower()}.",
            detail={"status": session.status},
        )
    assert_different_actors(
        session.cashier_id, getattr(actor, "uuid", None), "till reconciliation"
    )

    session.status = SessionStatus.RECONCILED
    session.reconciled_by_id = actor.uuid
    session.reconciled_at = timezone.now()
    if notes:
        session.notes = f"{session.notes}\n{notes}".strip()
    session.save(
        update_fields=[
            "status", "reconciled_by_id", "reconciled_at", "notes", "updated_at",
        ]
    )
    record(
        AuditAction.APPROVE,
        entity_type="pos.CounterSession",
        entity_id=session.uuid,
        entity_label=f"{session.reference} reconciled",
        reason=notes,
    )
    return session


# ---------------------------------------------------------------------------
# Selling
# ---------------------------------------------------------------------------


def search_products(term: str, location: StockLocation = None, limit: int = 20) -> list:
    """Counter lookup: barcode, brand name, generic name, or code.

    Barcode is checked first and exactly. A scanner types faster than a person
    and a scanned code that fell through to a fuzzy name search would produce
    a list where the cashier expected one item — the single most common way a
    counter picks the wrong product.
    """
    term = (term or "").strip()
    if not term:
        return []

    exact = Product.objects.filter(barcode=term, is_active=True).first()
    matches = [exact] if exact else list(
        Product.objects.filter(is_active=True)
        .filter(
            # Generic and brand both searched: a customer asks for "Brufen",
            # a prescription says "ibuprofen", and the counter has to find the
            # same box from either.
            models.Q(generic_name__icontains=term)
            | models.Q(brand_name__icontains=term)
            | models.Q(code__icontains=term)
        )
        .order_by("generic_name")[:limit]
    )

    results = []
    for product in matches:
        allocation = (
            allocate_fefo(product, location, Decimal("1")) if location else None
        )
        first = (allocation["allocation"] or [None])[0] if allocation else None
        batch = first["batch"] if first else None
        results.append(
            {
                "product": product,
                "available": (
                    _available(product, location) if location else ZERO
                ),
                # The batch FEFO would pick, so the counter shows the price
                # the customer will actually be charged rather than a
                # catalogue figure that may be a batch or two out of date.
                "batch": batch,
                "unit_price": batch.selling_price if batch else MONEY_ZERO,
                "mrp": batch.mrp if batch else MONEY_ZERO,
                "expires_on": batch.expires_on if batch else None,
                "requires_prescription": product.requires_prescription,
            }
        )
    return results


def _available(product: Product, location: StockLocation) -> Decimal:
    from apps.pharmacy.models import BatchStock, DISPENSABLE_STATUSES

    rows = BatchStock.objects.filter(
        batch__product=product,
        location=location,
        batch__status__in=DISPENSABLE_STATUSES,
        batch__expires_on__gte=timezone.localdate(),
    ).aggregate(qty=models.Sum("quantity"), reserved=models.Sum("reserved"))
    return quantise((rows["qty"] or ZERO) - (rows["reserved"] or ZERO))


def _price_line(product: Product, batch: Batch, quantity, unit_price, discount_percent):
    """Work out one line's money.

    Discount comes off before tax, which is the order the tax authority
    expects: VAT is charged on what was actually received, not on a headline
    price nobody paid.
    """
    quantity = quantise(quantity)
    unit_price = money(unit_price if unit_price is not None else batch.selling_price)
    discount_percent = money(discount_percent or MONEY_ZERO)

    gross = money(unit_price * quantity)
    discount = money(gross * discount_percent / Decimal("100"))
    net = money(gross - discount)
    tax_rate = money(product.vat_rate or MONEY_ZERO)
    tax = money(net * tax_rate / Decimal("100"))

    return {
        "quantity": quantity,
        "unit_price": unit_price,
        "discount_percent": discount_percent,
        "discount_amount": discount,
        "tax_percent": tax_rate,
        "tax_amount": tax,
        "total": money(net + tax),
    }


def quote_sale(session: CounterSession, items, sale_type: str = SaleType.WALK_IN) -> dict:
    """Price a basket without committing anything.

    The till screen calls this on every scan. It exists because the total a
    customer is asked for is **rounded to the whole rupee**, and that rounding
    happens on the invoice, server-side, after discount and tax. A counter
    that computed its own figure would eventually ask for a rupee more or less
    than the invoice says — and the customer is looking at both.

    Nothing here touches stock or money. It reports what *would* happen,
    including whether the shelf can cover it, so the cashier finds out before
    the customer has handed over a note.
    """
    location = session.location
    lines, shortfalls, warnings = [], [], []
    subtotal = discount_total = tax_total = MONEY_ZERO

    for entry in items:
        product = entry["product"]
        quantity = quantise(entry["quantity"])

        if product.requires_prescription and sale_type != SaleType.PRESCRIPTION:
            warnings.append(
                f"{product.display_name} is prescription-only."
            )

        try:
            result = allocate_fefo(
                product, location, quantity, preferred_batch=entry.get("batch")
            )
        except InsufficientStock:
            shortfalls.append(
                {"product": product.code, "requested": quantity, "available": ZERO}
            )
            continue

        if result["allocated"] < quantity:
            shortfalls.append(
                {
                    "product": product.code,
                    "requested": quantity,
                    "available": result["allocated"],
                }
            )

        for row in result["allocation"]:
            pricing = _price_line(
                product, row["batch"], row["quantity"],
                entry.get("unit_price"), entry.get("discount_percent"),
            )
            subtotal += money(pricing["unit_price"] * pricing["quantity"])
            discount_total += pricing["discount_amount"]
            tax_total += pricing["tax_amount"]
            lines.append(
                {
                    "product": product.code,
                    "product_name": product.display_name,
                    "batch_number": row["batch"].batch_number,
                    "expires_on": row["batch"].expires_on,
                    **pricing,
                }
            )

    net = money(subtotal) - money(discount_total) + money(tax_total)
    # Same rounding rule as `billing._recalculate`, so the quote and the
    # invoice agree to the paisa.
    rounded = net.quantize(RUPEE, rounding=ROUND_HALF_UP)
    return {
        "lines": lines,
        "subtotal": money(subtotal),
        "discount_total": money(discount_total),
        "tax_total": money(tax_total),
        "rounding_adjustment": money(rounded - net),
        "total": money(rounded),
        "shortfalls": shortfalls,
        "warnings": warnings,
        "can_sell": not shortfalls and not warnings,
    }


@tenant_atomic_method
def create_sale(
    organization,
    session: CounterSession,
    items,
    actor,
    sale_type: str = SaleType.WALK_IN,
    patient=None,
    customer_name: str = "",
    customer_phone: str = "",
    customer_pan: str = "",
    prescription=None,
    payments=None,
    notes: str = "",
    allow_prescription_override: bool = False,
) -> Sale:
    """Sell across the counter: allocate stock, invoice it, take the money.

    `items` are `{product, quantity, batch?, unit_price?, discount_percent?}`.
    A batch may be named — a customer who wants the same batch as last time,
    or one the pharmacist has in their hand — otherwise FEFO chooses, and one
    item can become several lines when the quantity spans batches.

    `payments` are `{method, amount, reference?}`. Several are allowed: part
    cash, part wallet is ordinary in a Nepali pharmacy. Omitting them entirely
    leaves the invoice unpaid, which is only legitimate for the credit sale
    types.
    """
    require_module(organization, ModuleCode.PHARMACY)

    if not session.is_open:
        raise SessionClosed(detail={"session": session.reference})
    if not items:
        raise PosError("A sale needs at least one item.")

    location = session.location

    # -- 1. Work out what leaves the shelf, before anything is written -----
    #
    # Allocation is resolved for every item first so a short line fails the
    # whole sale rather than half-committing it. Partially posting stock and
    # then discovering item four is unavailable leaves the ledger holding a
    # sale that never happened.
    planned = []
    for entry in items:
        product = entry["product"]
        quantity = quantise(entry["quantity"])
        if quantity <= ZERO:
            raise PosError(f"{product.display_name}: quantity must be positive.")

        if product.requires_prescription and not allow_prescription_override:
            if sale_type != SaleType.PRESCRIPTION or prescription is None:
                raise PrescriptionRequired(
                    f"{product.display_name} may not be sold without a "
                    "prescription.",
                    detail={"product": product.code},
                )

        result = allocate_fefo(
            product, location, quantity, preferred_batch=entry.get("batch")
        )
        if result["allocated"] < quantity:
            raise InsufficientStock(
                f"{product.display_name}: only {result['allocated']} of "
                f"{quantity} "
                f"available at {location.code}.",
                detail={
                    "product": product.code,
                    "requested": str(quantity),
                    "available": str(result["allocated"]),
                },
            )
        for row in result["allocation"]:
            planned.append(
                {
                    "product": product,
                    "batch": row["batch"],
                    "quantity": row["quantity"],
                    "unit_price": entry.get("unit_price"),
                    "discount_percent": entry.get("discount_percent"),
                    "fefo_overridden": result.get("breaks_fefo", False),
                }
            )

    sale = Sale.objects.create(
        reference=_next_reference(Sale, "S"),
        session=session,
        facility=session.facility,
        location=location,
        sale_type=sale_type,
        patient=patient,
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_pan=customer_pan,
        prescription_uuid=getattr(prescription, "uuid", None),
        prescription_reference=getattr(prescription, "reference", "") or "",
        sold_by_id=actor.uuid,
        sold_by_name=getattr(actor, "full_name", "") or actor.email,
        notes=notes,
        created_by_id=actor.uuid,
    )

    # -- 2. Move the stock -------------------------------------------------
    #
    # Before the money. If a batch was quarantined between allocation and now,
    # the transaction rolls back and the customer is told — rather than
    # having paid for goods that cannot leave the shelf.
    invoice_lines = []
    for order, row in enumerate(planned):
        pricing = _price_line(
            row["product"], row["batch"], row["quantity"],
            row["unit_price"], row["discount_percent"],
        )
        line = SaleLine.objects.create(
            sale=sale,
            product=row["product"],
            batch=row["batch"],
            product_name=row["product"].display_name,
            batch_number=row["batch"].batch_number,
            expires_on=row["batch"].expires_on,
            mrp=row["batch"].mrp,
            unit_cost=row["batch"].purchase_price,
            display_order=order,
            created_by_id=actor.uuid,
            **pricing,
        )
        line.full_clean(exclude=["sale", "product", "batch"])

        post_movement(
            batch=row["batch"],
            location=location,
            movement_type=MovementType.SALE,
            quantity=line.quantity,
            actor=actor,
            reference_type="pos.Sale",
            reference_id=sale.reference,
            patient=patient,
            unit_cost=row["batch"].purchase_price,
            fefo_overridden=row["fefo_overridden"],
            fefo_override_reason=(
                f"Batch chosen at the counter on {sale.reference}"
                if row["fefo_overridden"] else ""
            ),
            approved_by=actor if row["fefo_overridden"] else None,
        )
        invoice_lines.append(
            {
                "service_code": row["product"].code,
                "description": (
                    f"{row['product'].display_name} "
                    f"[{row['batch'].batch_number} exp {row['batch'].expires_on}]"
                ),
                "category": "pharmacy",
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "discount_amount": line.discount_amount,
                "tax_rate": line.tax_percent,
                "tax_amount": line.tax_amount,
                "total": line.total,
            }
        )

    # -- 3. Bill it --------------------------------------------------------
    invoice = create_retail_invoice(
        organization=organization,
        facility=session.facility,
        lines=invoice_lines,
        patient=patient,
        bill_to_name=customer_name or (patient.full_name if patient else ""),
        bill_to_pan=customer_pan,
        payer_reference=(
            patient.corporate_account or patient.insurance_policy_number
            if patient else ""
        ),
        actor=actor,
        issue=True,
        notes=f"Counter sale {sale.reference}",
    )

    sale.invoice_uuid = invoice.uuid
    sale.invoice_number = invoice.number
    sale.subtotal = invoice.subtotal
    sale.discount_total = invoice.discount_total
    sale.tax_total = invoice.tax_total
    sale.rounding_adjustment = invoice.rounding_adjustment
    sale.total = invoice.total

    # -- 4. Take the money -------------------------------------------------
    #
    # A tender with no amount settles whatever is left. This is how a real
    # counter works -- "the rest on eSewa" -- and it is the only way a caller
    # can settle a sale exactly without first knowing a total that is rounded
    # to the rupee on the invoice, after discount and tax. Guessing it and
    # missing by a paisa would leave the sale unpayable.
    for tender in payments or []:
        amount = tender.get("amount")
        if amount in (None, ""):
            invoice.refresh_from_db()
            amount = invoice.balance_due
            if amount <= MONEY_ZERO:
                continue
        record_payment(
            invoice=invoice,
            amount=amount,
            method=tender["method"],
            actor=actor,
            reference=tender.get("reference", ""),
            # Tagging the payment with the session reference is what makes the
            # end-of-shift cash-up a query rather than a running total.
            counter=session.reference,
        )
    invoice.refresh_from_db()

    if invoice.balance_due > MONEY_ZERO and sale_type not in CREDIT_SALE_TYPES:
        raise PosError(
            f"{invoice.balance_due} is still unpaid. A walk-in sale must be "
            "settled at the counter, or recorded as a credit sale.",
            detail={"balance_due": str(invoice.balance_due)},
        )

    sale.status = SaleStatus.COMPLETED
    sale.save()

    record(
        AuditAction.CREATE,
        entity_type="pos.Sale",
        entity_id=sale.uuid,
        entity_label=f"{sale.reference} — {sale.total} ({invoice.number})",
        metadata={
            "session": session.reference,
            "invoice": invoice.number,
            "lines": len(planned),
        },
    )
    return sale


@tenant_atomic_method
def void_sale(sale: Sale, reason: str, actor, approved_by=None) -> Sale:
    """Cancel a completed sale in full and put the stock back.

    Approved by someone other than the seller: voiding a sale after pocketing
    the cash is the textbook counter fraud, and the whole point of the till
    session is that it would otherwise balance perfectly.
    """
    if sale.status not in {SaleStatus.COMPLETED, SaleStatus.DRAFT}:
        raise PosError(
            f"A sale that is {sale.get_status_display().lower()} cannot be voided.",
            detail={"status": sale.status},
        )
    if not reason.strip():
        raise PosError("A void must record why.")

    approver = approved_by or actor
    assert_different_actors(sale.sold_by_id, getattr(approver, "uuid", None), "void")

    for line in sale.lines.all():
        post_movement(
            batch=line.batch,
            location=sale.location,
            movement_type=MovementType.SALES_RETURN,
            quantity=line.quantity,
            actor=actor,
            reason=f"Void of {sale.reference}: {reason}",
            reference_type="pos.Sale",
            reference_id=sale.reference,
        )

    if sale.invoice_uuid:
        from apps.billing.models import Invoice, Payment
        from apps.billing.services import credit_invoice, refund_payment

        invoice = Invoice.objects.get(uuid=sale.invoice_uuid)
        for payment in Payment.objects.filter(
            invoice=invoice, status=PaymentStatus.COMPLETED, amount__gt=0
        ):
            refund_payment(payment, reason=reason, actor=actor, approved_by=approver)
        credit_invoice(invoice, reason=f"Sale {sale.reference} voided: {reason}",
                       actor=actor)

    sale.status = SaleStatus.VOIDED
    sale.voided_at = timezone.now()
    sale.void_reason = reason
    sale.save(update_fields=["status", "voided_at", "void_reason", "updated_at"])

    record(
        AuditAction.DELETE,
        entity_type="pos.Sale",
        entity_id=sale.uuid,
        entity_label=f"{sale.reference} voided",
        reason=reason,
        metadata={"approved_by": str(getattr(approver, "uuid", ""))},
    )
    logger.warning(
        "SALE VOID %s (%s) by %s approved by %s: %s",
        sale.reference, sale.total, getattr(actor, "email", "?"),
        getattr(approver, "email", "?"), reason,
    )
    return sale


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------


@tenant_atomic_method
def request_return(
    sale: Sale,
    entries,
    reason: str,
    actor,
    session: CounterSession = None,
    restock: bool = True,
    restock_note: str = "",
) -> SaleReturn:
    """Raise a return for approval.

    `entries` are `{sale_line, quantity, condition_note?}`.

    Raised, not executed. Money leaves the till against goods whose condition
    only the cashier has seen — the approval is the point at which somebody
    else looks at both.
    """
    if not sale.is_returnable:
        raise PosError(
            f"A sale that is {sale.get_status_display().lower()} cannot be "
            "returned against.",
            detail={"status": sale.status},
        )
    if not reason.strip():
        raise PosError("A return must record why the goods came back.")
    if not entries:
        raise PosError("A return needs at least one line.")

    session = session or sale.session
    sale_return = SaleReturn.objects.create(
        reference=_next_reference(SaleReturn, "R"),
        sale=sale,
        session=session,
        reason=reason,
        restock=restock,
        restock_note=restock_note,
        requested_by_id=actor.uuid,
        requested_by_name=getattr(actor, "full_name", "") or actor.email,
        created_by_id=actor.uuid,
    )

    total = MONEY_ZERO
    for entry in entries:
        line = entry["sale_line"]
        quantity = quantise(entry["quantity"])
        if line.sale_id != sale.pk:
            raise PosError("That line belongs to a different sale.")
        if quantity <= ZERO:
            raise PosError(f"{line.product_name}: return quantity must be positive.")
        if quantity > line.returnable_quantity:
            raise PosError(
                f"{line.product_name}: only {line.returnable_quantity} of the "
                f"{line.quantity} sold are still returnable.",
                detail={
                    "line": str(line.uuid),
                    "returnable": str(line.returnable_quantity),
                },
            )

        # Refund the proportion of what was actually charged, tax and discount
        # included. Recomputing from the unit price would refund a different
        # figure from the one on the receipt, and the customer is holding the
        # receipt.
        share = (quantity / line.quantity)
        refund = (line.total * share).quantize(PAISA, rounding=ROUND_HALF_UP)
        total += refund

        SaleReturnLine.objects.create(
            sale_return=sale_return,
            sale_line=line,
            quantity=quantity,
            refund_amount=refund,
            condition_note=entry.get("condition_note", ""),
            created_by_id=actor.uuid,
        )

    sale_return.refund_total = money(total)
    sale_return.save(update_fields=["refund_total", "updated_at"])

    record(
        AuditAction.CREATE,
        entity_type="pos.SaleReturn",
        entity_id=sale_return.uuid,
        entity_label=f"{sale_return.reference} against {sale.reference}",
        reason=reason,
        metadata={"refund_total": str(sale_return.refund_total)},
    )
    return sale_return


@tenant_atomic_method
def approve_return(
    organization,
    sale_return: SaleReturn,
    actor,
    refund_method: str = PaymentMethod.CASH,
    decision_notes: str = "",
) -> SaleReturn:
    """Accept the goods back: credit note, refund, and stock decision.

    Restocking is a decision made here rather than assumed at request time,
    because the person approving is the one who has looked at the goods. A
    sealed box that came back within the hour goes on the shelf; an opened
    bottle goes to quarantine. Either way the customer is refunded — the
    money and the stock are separate questions.
    """
    if sale_return.status != SaleReturnStatus.PENDING:
        raise PosError(
            f"This return is already "
            f"{sale_return.get_status_display().lower()}.",
            detail={"status": sale_return.status},
        )
    assert_different_actors(
        sale_return.requested_by_id, getattr(actor, "uuid", None), "sales return"
    )

    from apps.billing.models import Invoice

    sale = sale_return.sale
    lines = list(sale_return.lines.select_related("sale_line").all())

    # -- 1. Credit note, against the sale's own invoice --------------------
    original = Invoice.objects.filter(uuid=sale.invoice_uuid).first()
    credit_lines = [
        {
            "service_code": row.sale_line.product.code,
            "description": (
                f"Return: {row.sale_line.product_name} "
                f"[{row.sale_line.batch_number}]"
            ),
            "category": "pharmacy",
            "quantity": -row.quantity,
            "unit_price": row.sale_line.unit_price,
            "discount_amount": MONEY_ZERO,
            "tax_rate": row.sale_line.tax_percent,
            "tax_amount": MONEY_ZERO,
            "total": -row.refund_amount,
        }
        for row in lines
    ]
    credit_note = create_retail_invoice(
        organization=organization,
        facility=sale.facility,
        lines=credit_lines,
        patient=sale.patient,
        bill_to_name=sale.customer_label,
        bill_to_pan=sale.customer_pan,
        credit_of=original,
        credit_reason=sale_return.reason,
        actor=actor,
        issue=True,
        notes=f"Return {sale_return.reference} against {sale.reference}",
    ) if original else None

    # -- 2. Hand the money back --------------------------------------------
    if credit_note is not None:
        record_counter_refund(
            credit_note=credit_note,
            amount=sale_return.refund_total,
            method=refund_method,
            actor=actor,
            counter=sale_return.session.reference,
            reason=sale_return.reason,
        )
        sale_return.credit_note_uuid = credit_note.uuid
        sale_return.credit_note_number = credit_note.number

    # -- 3. Decide where the goods go --------------------------------------
    for row in lines:
        line = row.sale_line
        if sale_return.restock:
            post_movement(
                batch=line.batch,
                location=sale.location,
                movement_type=MovementType.SALES_RETURN,
                quantity=row.quantity,
                actor=actor,
                reason=f"Return {sale_return.reference}: {sale_return.reason}",
                reference_type="pos.SaleReturn",
                reference_id=sale_return.reference,
            )
        else:
            # The goods came back but must not be resold. They are still
            # returned to the ledger first — they physically exist and the
            # count would be short otherwise — then written off, so the
            # write-off is visible as a write-off rather than as a sale that
            # quietly never reversed.
            post_movement(
                batch=line.batch,
                location=sale.location,
                movement_type=MovementType.SALES_RETURN,
                quantity=row.quantity,
                actor=actor,
                reason=f"Return {sale_return.reference} (not resaleable)",
                reference_type="pos.SaleReturn",
                reference_id=sale_return.reference,
            )
            post_movement(
                batch=line.batch,
                location=sale.location,
                movement_type=MovementType.DAMAGE,
                quantity=row.quantity,
                actor=actor,
                reason=(
                    sale_return.restock_note
                    or f"Returned goods not resaleable ({sale_return.reference})"
                ),
                reference_type="pos.SaleReturn",
                reference_id=sale_return.reference,
            )

        line.returned_quantity = quantise(line.returned_quantity + row.quantity)
        line.save(update_fields=["returned_quantity", "updated_at"])

    # -- 4. Move both documents on ----------------------------------------
    fully_returned = all(
        line.returnable_quantity <= ZERO for line in sale.lines.all()
    )
    sale.status = (
        SaleStatus.RETURNED if fully_returned else SaleStatus.PARTIALLY_RETURNED
    )
    sale.save(update_fields=["status", "updated_at"])

    sale_return.status = SaleReturnStatus.COMPLETED
    sale_return.refund_method = refund_method
    sale_return.approved_by_id = actor.uuid
    sale_return.approved_by_name = getattr(actor, "full_name", "") or actor.email
    sale_return.approved_at = timezone.now()
    sale_return.completed_at = timezone.now()
    sale_return.decision_notes = decision_notes
    sale_return.save()

    record(
        AuditAction.APPROVE,
        entity_type="pos.SaleReturn",
        entity_id=sale_return.uuid,
        entity_label=f"{sale_return.reference} completed",
        reason=decision_notes or sale_return.reason,
        metadata={
            "refund_total": str(sale_return.refund_total),
            "restocked": sale_return.restock,
            "credit_note": sale_return.credit_note_number,
        },
    )
    return sale_return


@tenant_atomic_method
def reject_return(sale_return: SaleReturn, actor, decision_notes: str) -> SaleReturn:
    """Refuse a return. Nothing moves, and the refusal is on the record."""
    if sale_return.status != SaleReturnStatus.PENDING:
        raise PosError(
            f"This return is already "
            f"{sale_return.get_status_display().lower()}."
        )
    if not decision_notes.strip():
        raise PosError("A refused return must say why.")
    assert_different_actors(
        sale_return.requested_by_id, getattr(actor, "uuid", None), "sales return"
    )

    sale_return.status = SaleReturnStatus.REJECTED
    sale_return.approved_by_id = actor.uuid
    sale_return.approved_by_name = getattr(actor, "full_name", "") or actor.email
    sale_return.approved_at = timezone.now()
    sale_return.decision_notes = decision_notes
    sale_return.save()

    record(
        AuditAction.REJECT,
        entity_type="pos.SaleReturn",
        entity_id=sale_return.uuid,
        entity_label=f"{sale_return.reference} refused",
        reason=decision_notes,
    )
    return sale_return


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def sales_summary(facility, on_date=None) -> dict:
    """A day at the counter: what was sold, what came back, what was earned.

    Gross and net are both reported, and **margin is computed on the net**.
    A day that sold 24 and refunded 10 did not earn margin on 24, and an owner
    reading a single "revenue" figure that ignores returns is being told the
    business is 70% larger than it is.

    The cost side nets too, but asymmetrically, and the asymmetry is the whole
    point:

    - goods returned **and restocked** give their cost back — they are on the
      shelf and will be sold again;
    - goods returned and **written off** do not. The pharmacy refunded the
      customer *and* lost the stock, so that cost stays in the day.

    Nothing here is stored. Margin recomputed from the ledger is margin that
    cannot silently disagree with the ledger.
    """
    on_date = on_date or timezone.localdate()
    sales = Sale.objects.filter(
        facility=facility, sold_at__date=on_date
    ).exclude(status=SaleStatus.VOIDED)

    lines = SaleLine.objects.filter(sale__in=sales)
    gross_revenue = money(sales.aggregate(t=models.Sum("total"))["t"] or MONEY_ZERO)
    tax = money(sales.aggregate(t=models.Sum("tax_total"))["t"] or MONEY_ZERO)
    gross_cost = money(
        sum((line.unit_cost * line.quantity for line in lines), Decimal("0"))
    )

    returns = SaleReturn.objects.filter(
        sale__facility=facility,
        completed_at__date=on_date,
        status=SaleReturnStatus.COMPLETED,
    )
    returns_total = money(
        returns.aggregate(t=models.Sum("refund_total"))["t"] or MONEY_ZERO
    )

    # Cost recovered only where the goods went back on the shelf.
    recovered = Decimal("0")
    written_off = Decimal("0")
    for row in SaleReturnLine.objects.filter(
        sale_return__in=returns
    ).select_related("sale_return", "sale_line"):
        line_cost = row.sale_line.unit_cost * row.quantity
        if row.sale_return.restock:
            recovered += line_cost
        else:
            written_off += line_cost

    net_revenue = money(gross_revenue - returns_total)
    net_cost = money(gross_cost - recovered)
    # Tax is not margin: it was collected on the customer's behalf. Refunded
    # tax comes back out with the refund, so netting the revenue first is what
    # keeps the two sides consistent.
    net_margin = money(net_revenue - tax - net_cost)

    by_product = (
        lines.values("product_name")
        .annotate(quantity=models.Sum("quantity"), total=models.Sum("total"))
        .order_by("-total")[:10]
    )

    taxable_base = net_revenue - tax
    return {
        "date": on_date,
        "sales_count": sales.count(),
        "gross_revenue": gross_revenue,
        "returns_count": returns.count(),
        "returns_total": returns_total,
        "net_revenue": net_revenue,
        "tax": tax,
        "cost_of_goods": gross_cost,
        "cost_recovered": money(recovered),
        "cost_written_off": money(written_off),
        "net_cost_of_goods": net_cost,
        "gross_margin": net_margin,
        "margin_percent": (
            money(net_margin / taxable_base * 100)
            if taxable_base > MONEY_ZERO else MONEY_ZERO
        ),
        "top_products": list(by_product),
    }
