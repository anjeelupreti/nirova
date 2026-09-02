"""Pricing, charge capture, invoicing and payment."""

import logging
from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import record, record_version
from apps.billing.fiscal import fiscal_year_for
from apps.billing.models import (
    ZERO,
    Charge,
    ChargeStatus,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    NumberSequence,
    Payment,
    PaymentMethod,
    PaymentStatus,
    PriceList,
    PriceListItem,
    ServiceItem,
)
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.entitlements.services import require_module
# assert_different_actors: the maker-checker rule. Whoever took a payment may
# not approve its refund.
from apps.rbac.services import assert_different_actors
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.billing")

PAISA = Decimal("0.01")
RUPEE = Decimal("1")

#: Payment statuses that represent money that actually moved.
#:
#: REFUNDED is included deliberately. A refund is two rows -- the original,
#: marked refunded, and a second row carrying the negative amount. Counting
#: only COMPLETED would drop the original while keeping its reversal,
#: subtracting the refund twice. Both rows are real cash movements and both
#: belong in the total, where they net to zero.
BANKED_STATUSES = (PaymentStatus.COMPLETED, PaymentStatus.REFUNDED)


class BillingError(DomainError):
    code = "billing_operation_failed"


class InvoiceLocked(BillingError):
    code = "invoice_locked"
    message = "An issued invoice cannot be changed. Raise a credit note instead."


class DiscountNotPermitted(BillingError):
    code = "discount_not_permitted"
    status_code = 403


def money(value) -> Decimal:
    """Round a value to paisa, half up.

    Half-up rather than Python's default banker's rounding: a customer
    presented with a total that rounds 0.005 down to their advantage half the
    time and against them the other half will not find the explanation
    satisfying, and neither will an auditor.
    """
    return Decimal(value).quantize(PAISA, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def resolve_price(service: ServiceItem, patient, facility, on_date=None) -> dict:
    """Find the price for a service, for this patient, at this facility.

    Resolution order, most specific first:

    1. A price list matching the patient's category *and* this facility.
    2. A price list matching the patient's category, organization-wide.
    3. A facility-wide general list.
    4. The service's own default price.

    Ties are broken by the list's `priority`, so a negotiated corporate rate
    beats the general list without either being deleted. The chosen source is
    returned alongside the price, because "why was I charged this?" is a
    question that gets asked.
    """
    on_date = on_date or timezone.localdate()
    category = getattr(patient, "category", "") or ""

    candidates = (
        PriceList.objects.filter(is_active=True)
        .filter(
            models.Q(facility=facility) | models.Q(facility__isnull=True)
        )
        .filter(
            models.Q(patient_category=category) | models.Q(patient_category="")
        )
        .order_by("-priority")
    )

    def specificity(price_list) -> int:
        """Higher is more specific. Facility match counts for more than
        category match, because a facility's own rate card is a deliberate
        local decision."""
        return (2 if price_list.facility_id else 0) + (
            1 if price_list.patient_category else 0
        )

    applicable = [pl for pl in candidates if pl.applies_on(on_date)]
    applicable.sort(key=lambda pl: (specificity(pl), pl.priority), reverse=True)

    for price_list in applicable:
        item = PriceListItem.objects.filter(
            price_list=price_list, service=service
        ).first()
        if item is not None:
            return {
                "unit_price": money(item.price),
                "discount_percent": item.discount_percent,
                "price_list": price_list,
                "source": f"price_list:{price_list.code}",
            }

    return {
        "unit_price": money(service.default_price),
        "discount_percent": ZERO,
        "price_list": None,
        "source": f"service_default:{service.code}",
    }


# ---------------------------------------------------------------------------
# Charge capture
# ---------------------------------------------------------------------------


@tenant_atomic_method
def capture_charge(
    organization,
    patient,
    facility,
    service: ServiceItem,
    actor=None,
    encounter=None,
    quantity=Decimal("1.00"),
    discount_percent=ZERO,
    discount_reason: str = "",
    discount_approved_by=None,
    notes: str = "",
) -> Charge:
    """Record that something billable happened.

    The price is resolved and **captured onto the charge** here. The price list
    may change tomorrow; what the patient was quoted today is what they are
    billed.
    """
    require_module(organization, ModuleCode.FINANCE)

    quantity = Decimal(str(quantity))
    if quantity <= ZERO:
        raise BillingError("A charge must have a positive quantity.")

    pricing = resolve_price(service, patient, facility)
    discount_percent = Decimal(str(discount_percent or ZERO))
    # A discount built into the payer's arrangement applies on top of whatever
    # the user asked for -- it is part of the deal, not a concession.
    discount_percent = max(discount_percent, pricing["discount_percent"] or ZERO)

    if discount_percent > (service.max_discount_percent or ZERO):
        if discount_approved_by is None:
            raise DiscountNotPermitted(
                f"A discount of {discount_percent}% on {service.name} exceeds "
                f"the {service.max_discount_percent}% limit and needs approval.",
                detail={
                    "service": service.code,
                    "requested_percent": str(discount_percent),
                    "max_percent": str(service.max_discount_percent),
                },
            )
        if not discount_reason.strip():
            raise DiscountNotPermitted(
                "An approved discount must record why it was given."
            )

    charge = Charge(
        patient=patient,
        encounter=encounter,
        facility=facility,
        department=service.department,
        service=service,
        service_code=service.code,
        service_name=service.name,
        quantity=quantity,
        unit_price=pricing["unit_price"],
        discount_percent=discount_percent,
        tax_rate=service.effective_tax_rate,
        price_list=pricing["price_list"],
        price_source=pricing["source"],
        charged_by_id=getattr(actor, "uuid", None),
        discount_approved_by_id=getattr(discount_approved_by, "uuid", None),
        discount_reason=discount_reason,
        notes=notes,
        created_by_id=getattr(actor, "uuid", None),
    )
    charge.total = charge.compute_total()
    charge.save()

    record(
        AuditAction.CREATE,
        entity_type="billing.Charge",
        entity_id=charge.uuid,
        entity_label=f"{service.code} × {quantity} for {patient.mrn}",
        metadata={
            "total": str(charge.total),
            "price_source": charge.price_source,
            "discount_percent": str(discount_percent),
        },
    )
    return charge


@tenant_atomic_method
def capture_consultation_charge(organization, encounter, actor=None) -> Charge | None:
    """Charge the consultation fee for an encounter.

    Returns `None` when no consultation service is configured, rather than
    raising: a clinic that has not set up its price list should still be able
    to see patients. The gap shows up as an uncharged encounter in reporting,
    which is the right place for it to surface.
    """
    service = ServiceItem.objects.filter(
        category="consultation", is_active=True
    ).order_by("display_order").first()
    if service is None:
        logger.warning(
            "No consultation service configured; encounter %s not charged",
            encounter.reference,
        )
        return None

    existing = Charge.objects.filter(
        encounter=encounter, service=service, status=ChargeStatus.PENDING
    ).first()
    if existing:
        return existing

    return capture_charge(
        organization,
        patient=encounter.patient,
        facility=encounter.facility,
        service=service,
        actor=actor,
        encounter=encounter,
    )


@tenant_atomic_method
def cancel_charge(charge: Charge, reason: str, actor=None) -> Charge:
    """Cancel an uninvoiced charge."""
    if not reason.strip():
        raise BillingError("Cancelling a charge must record a reason.")
    if charge.status == ChargeStatus.INVOICED:
        raise BillingError(
            "This charge is already on an invoice. Raise a credit note "
            "against the invoice instead.",
            detail={"charge": str(charge.uuid)},
        )

    charge.status = ChargeStatus.CANCELLED
    charge.cancelled_at = timezone.now()
    charge.cancellation_reason = reason
    charge.save(
        update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"]
    )
    record(
        AuditAction.CANCEL,
        entity_type="billing.Charge",
        entity_id=charge.uuid,
        entity_label=charge.service_name,
        reason=reason,
    )
    return charge


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------


def allocate_number(facility, document_type: str, on_date=None) -> str:
    """Take the next number in a gapless sequence, under a row lock.

    `select_for_update` holds the sequence row until the surrounding
    transaction commits, so two counters issuing invoices at the same moment
    cannot take the same number. That is the whole point of a sequence table
    rather than `MAX(number) + 1`, which is neither concurrency-safe nor
    correct after a deletion.

    Must be called inside a transaction; the lock is meaningless otherwise.
    """
    fiscal_year = fiscal_year_for(on_date or timezone.localdate())

    sequence, _ = NumberSequence.objects.select_for_update().get_or_create(
        facility=facility,
        document_type=document_type,
        fiscal_year=fiscal_year,
        # The facility code goes into the prefix, not just into the row the
        # counter is kept on. Without it two facilities in one organization
        # both render INV-<year>-000001 and collide on the unique number.
        defaults={
            "last_number": 0,
            "prefix": f"{document_type[:3].upper()}-{facility.code}",
        },
    )
    sequence.last_number += 1
    sequence.save(update_fields=["last_number", "updated_at"])
    return sequence.format(sequence.last_number)


# ---------------------------------------------------------------------------
# Invoicing
# ---------------------------------------------------------------------------


def _recalculate(invoice: Invoice) -> Invoice:
    """Roll the lines up into the invoice totals.

    Rounding to the whole rupee is held in its own field rather than folded
    into the total, so the invoice still adds up when someone checks it line
    by line -- which is exactly what a patient disputing a bill will do.
    """
    lines = list(invoice.lines.all())
    subtotal = sum((line.quantity * line.unit_price for line in lines), ZERO)
    discount = sum((line.discount_amount for line in lines), ZERO)
    tax = sum((line.tax_amount for line in lines), ZERO)

    net = money(subtotal) - money(discount) + money(tax)
    rounded = net.quantize(RUPEE, rounding=ROUND_HALF_UP)

    invoice.subtotal = money(subtotal)
    invoice.discount_total = money(discount)
    invoice.tax_total = money(tax)
    invoice.rounding_adjustment = money(rounded - net)
    invoice.total = money(rounded)
    invoice.save(
        update_fields=[
            "subtotal", "discount_total", "tax_total",
            "rounding_adjustment", "total", "updated_at",
        ]
    )
    return invoice


@tenant_atomic_method
def create_invoice(
    organization,
    patient,
    facility,
    actor=None,
    encounter=None,
    charges=None,
    issue: bool = True,
    notes: str = "",
) -> Invoice:
    """Collect charges into an invoice.

    With no `charges` given, every pending charge for the patient at this
    facility is collected — which is what a counter clerk means by "bill this
    patient".
    """
    require_module(organization, ModuleCode.FINANCE)

    if charges is None:
        queryset = Charge.objects.filter(
            patient=patient, facility=facility, status=ChargeStatus.PENDING
        )
        if encounter is not None:
            queryset = queryset.filter(encounter=encounter)
        charges = list(queryset.order_by("charged_at"))

    if not charges:
        raise BillingError(
            "There are no uninvoiced charges for this patient.",
            detail={"patient": patient.mrn},
        )

    invoice = Invoice.objects.create(
        patient=patient,
        encounter=encounter,
        facility=facility,
        bill_to_name=patient.full_name,
        bill_to_address=", ".join(
            part for part in (patient.tole, patient.municipality, patient.district)
            if part
        ),
        patient_category=patient.category,
        payer_reference=patient.corporate_account or patient.insurance_policy_number,
        status=InvoiceStatus.DRAFT,
        created_by_id=getattr(actor, "uuid", None),
    )

    for order, charge in enumerate(charges):
        if charge.status != ChargeStatus.PENDING:
            raise BillingError(
                f"Charge {charge.service_code} is already "
                f"{charge.get_status_display().lower()}.",
                detail={"charge": str(charge.uuid)},
            )
        InvoiceLine.objects.create(
            invoice=invoice,
            charge=charge,
            service_code=charge.service_code,
            description=charge.service_name,
            category=charge.service.category,
            quantity=charge.quantity,
            unit_price=charge.unit_price,
            discount_amount=charge.discount_amount,
            tax_rate=charge.tax_rate,
            tax_amount=charge.tax_amount,
            total=charge.total,
            display_order=order,
            created_by_id=getattr(actor, "uuid", None),
        )
        charge.status = ChargeStatus.INVOICED
        charge.save(update_fields=["status", "updated_at"])

    _recalculate(invoice)

    if issue:
        issue_invoice(invoice, actor=actor)
    return invoice


@tenant_atomic_method
def create_retail_invoice(
    organization,
    facility,
    lines,
    patient=None,
    bill_to_name: str = "",
    bill_to_pan: str = "",
    payer_reference: str = "",
    credit_of: Invoice = None,
    credit_reason: str = "",
    actor=None,
    issue: bool = True,
    notes: str = "",
) -> Invoice:
    """Raise an invoice for goods sold over a counter.

    `create_invoice` collects `Charge` rows, which exist because a clinical
    event happened to a known patient and will be billed later. A retail sale
    has neither: the customer may not be a patient, and the money is taken in
    the same breath as the goods are handed over. Manufacturing a charge just
    to invoice it would put a phantom clinical event in the patient ledger.

    So the lines are passed in directly, as plain dicts. Everything after that
    -- rounding, numbering, the fiscal year, the audit snapshot -- is the same
    machinery every other invoice goes through, because a retail sale is a tax
    invoice under exactly the same rules.
    """
    require_module(organization, ModuleCode.FINANCE)

    if not lines:
        raise BillingError("A sale with no items cannot be invoiced.")

    # A partial return credits some lines and some quantities, not the whole
    # document, so the caller supplies the negative lines rather than this
    # mirroring the original. `credit_invoice` still handles the whole-invoice
    # reversal, which also closes the original off as CREDITED; a partial
    # credit must leave the original standing, because the rest of it is still
    # owed and still sold.
    if credit_of is not None and not credit_reason.strip():
        raise BillingError("A credit note must record why it was raised.")

    invoice = Invoice.objects.create(
        patient=patient,
        facility=facility,
        is_credit_note=credit_of is not None,
        credit_reason=credit_reason,
        # A walk-in still needs a name on the receipt. Falling back to the
        # patient's own name when there is one keeps the two paths consistent.
        bill_to_name=(
            bill_to_name or (patient.full_name if patient else "Walk-in customer")
        ),
        bill_to_pan=bill_to_pan,
        patient_category=getattr(patient, "category", "") or "",
        payer_reference=payer_reference,
        status=InvoiceStatus.DRAFT,
        notes=notes,
        created_by_id=getattr(actor, "uuid", None),
    )

    for order, line in enumerate(lines):
        InvoiceLine.objects.create(
            invoice=invoice,
            service_code=line.get("service_code", "")[:32],
            description=line["description"][:255],
            category=line.get("category", ""),
            quantity=line["quantity"],
            unit_price=line["unit_price"],
            discount_amount=line.get("discount_amount", ZERO),
            tax_rate=line.get("tax_rate", ZERO),
            tax_amount=line.get("tax_amount", ZERO),
            total=line["total"],
            display_order=order,
            created_by_id=getattr(actor, "uuid", None),
        )

    _recalculate(invoice)

    if issue:
        issue_invoice(invoice, actor=actor)
    return invoice


@tenant_atomic_method
def issue_invoice(invoice: Invoice, actor=None) -> Invoice:
    """Allocate a number and make the invoice final.

    The number is taken here, not at creation. An abandoned draft would
    otherwise consume a number and leave a gap in a sequence that a tax audit
    expects to be unbroken.
    """
    if invoice.status != InvoiceStatus.DRAFT:
        raise BillingError(
            f"Invoice is already {invoice.get_status_display().lower()}.",
            detail={"status": invoice.status},
        )
    if not invoice.lines.exists():
        raise BillingError("An empty invoice cannot be issued.")

    document_type = "credit_note" if invoice.is_credit_note else "invoice"
    invoice.number = allocate_number(invoice.facility, document_type)
    invoice.fiscal_year = fiscal_year_for()
    invoice.status = InvoiceStatus.ISSUED
    invoice.issued_at = timezone.now()
    invoice.issued_by_id = getattr(actor, "uuid", None)
    invoice.save(
        update_fields=[
            "number", "fiscal_year", "status", "issued_at",
            "issued_by_id", "updated_at",
        ]
    )

    # Snapshotted because an issued invoice is a statutory document: what it
    # said at issue must be reconstructable regardless of anything after.
    record_version(
        entity_type="billing.Invoice",
        entity_id=invoice.uuid,
        snapshot=_snapshot(invoice),
        reason="Invoice issued",
    )
    record(
        AuditAction.CREATE,
        entity_type="billing.Invoice",
        entity_id=invoice.uuid,
        entity_label=f"{invoice.number} — {invoice.bill_to_name}",
        metadata={"total": str(invoice.total), "fiscal_year": invoice.fiscal_year},
    )
    logger.info("Issued %s for %s: %s", invoice.number, invoice.bill_to_name,
                invoice.total)
    return invoice


@tenant_atomic_method
def credit_invoice(invoice: Invoice, reason: str, actor=None) -> Invoice:
    """Reverse an issued invoice with a credit note.

    The original is untouched. A credit note is a second document that
    negates the first, which is how a reversal has to work when the original
    is a statutory record with a number that cannot be withdrawn.
    """
    if not reason.strip():
        raise BillingError("A credit note must record why it was raised.")
    if invoice.status in {InvoiceStatus.DRAFT, InvoiceStatus.CREDITED}:
        raise BillingError(
            f"An invoice that is {invoice.get_status_display().lower()} "
            "cannot be credited.",
            detail={"status": invoice.status},
        )

    credit = Invoice.objects.create(
        patient=invoice.patient,
        encounter=invoice.encounter,
        facility=invoice.facility,
        bill_to_name=invoice.bill_to_name,
        bill_to_address=invoice.bill_to_address,
        bill_to_pan=invoice.bill_to_pan,
        patient_category=invoice.patient_category,
        payer_reference=invoice.payer_reference,
        status=InvoiceStatus.DRAFT,
        is_credit_note=True,
        credit_reason=reason,
        created_by_id=getattr(actor, "uuid", None),
    )

    # Negative quantities rather than negative prices: the unit price is what
    # was charged, and a report grouping by service should still show the
    # right rate alongside a reversed quantity.
    for line in invoice.lines.all():
        InvoiceLine.objects.create(
            invoice=credit,
            service_code=line.service_code,
            description=line.description,
            category=line.category,
            quantity=-line.quantity,
            unit_price=line.unit_price,
            discount_amount=-line.discount_amount,
            tax_rate=line.tax_rate,
            tax_amount=-line.tax_amount,
            total=-line.total,
            display_order=line.display_order,
            created_by_id=getattr(actor, "uuid", None),
        )

    _recalculate(credit)
    issue_invoice(credit, actor=actor)

    invoice.status = InvoiceStatus.CREDITED
    invoice.credited_by = credit
    invoice.save(update_fields=["status", "credited_by", "updated_at"])

    # Charges return to pending so they can be re-invoiced correctly, unless
    # the credit was because the service was never delivered.
    Charge.objects.filter(invoice_lines__invoice=invoice).update(
        status=ChargeStatus.PENDING
    )

    record(
        AuditAction.REFUND,
        entity_type="billing.Invoice",
        entity_id=credit.uuid,
        entity_label=f"{credit.number} credits {invoice.number}",
        reason=reason,
    )
    return credit


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------


@tenant_atomic_method
def record_payment(
    invoice: Invoice,
    amount,
    method: str,
    actor=None,
    reference: str = "",
    counter: str = "",
    notes: str = "",
) -> Payment:
    """Take money against an invoice.

    Overpayment is refused rather than absorbed. A counter that can take more
    than is owed produces a credit balance nobody asked for, and reconciling
    it later costs more than the keystroke saved.
    """
    amount = money(amount)
    if amount <= ZERO:
        raise BillingError("A payment must be a positive amount.")
    if invoice.status == InvoiceStatus.DRAFT:
        raise BillingError(
            "Issue the invoice before taking payment against it.",
            detail={"invoice": str(invoice.uuid)},
        )
    if amount > invoice.balance_due:
        raise BillingError(
            f"That is more than the {invoice.balance_due} outstanding on "
            f"{invoice.number}.",
            detail={
                "balance_due": str(invoice.balance_due),
                "offered": str(amount),
            },
        )

    payment = Payment.objects.create(
        receipt_number=allocate_number(invoice.facility, "receipt"),
        invoice=invoice,
        patient=invoice.patient,
        facility=invoice.facility,
        amount=amount,
        method=method,
        status=PaymentStatus.COMPLETED,
        reference=reference,
        counter=counter,
        received_by_id=getattr(actor, "uuid", None),
        received_by_name=getattr(actor, "full_name", ""),
        notes=notes,
        created_by_id=getattr(actor, "uuid", None),
    )

    _apply_payment_totals(invoice)

    record(
        AuditAction.CREATE,
        entity_type="billing.Payment",
        entity_id=payment.uuid,
        entity_label=f"{payment.receipt_number} — {amount} ({method})",
        metadata={
            "invoice": invoice.number,
            "balance_after": str(invoice.balance_due),
        },
    )
    return payment


def _apply_payment_totals(invoice: Invoice) -> Invoice:
    """Recompute what has been paid, and move the invoice's status with it."""
    paid = Payment.objects.filter(
        invoice=invoice, status__in=BANKED_STATUSES
    ).aggregate(total=models.Sum("amount"))["total"] or ZERO

    invoice.amount_paid = money(paid)

    # A credited invoice keeps that status regardless of what has been paid
    # against it. Its balance was settled by the credit note, not by cash,
    # and flipping it back to "issued" when a refund lands would make it look
    # like an open demand for money that no longer exists.
    if invoice.status != InvoiceStatus.CREDITED:
        if invoice.total > ZERO and invoice.amount_paid >= invoice.total:
            invoice.status = InvoiceStatus.PAID
        elif invoice.amount_paid > ZERO:
            invoice.status = InvoiceStatus.PARTIALLY_PAID
        else:
            invoice.status = InvoiceStatus.ISSUED
    invoice.save(update_fields=["amount_paid", "status", "updated_at"])
    return invoice


@tenant_atomic_method
def refund_payment(payment: Payment, reason: str, actor=None, approved_by=None) -> Payment:
    """Return money, as a second payment row that reverses the first.

    Segregation of duties applies: whoever took the payment may not approve
    its return. That is the classic till fraud, and it is cheap to prevent.
    """
    if not reason.strip():
        raise BillingError("A refund must record a reason.")
    if payment.status != PaymentStatus.COMPLETED:
        raise BillingError(
            f"A payment that is {payment.get_status_display().lower()} cannot "
            "be refunded.",
            detail={"status": payment.status},
        )

    approver = approved_by or actor
    assert_different_actors(
        payment.received_by_id, getattr(approver, "uuid", None), "refund"
    )

    refund = Payment.objects.create(
        receipt_number=allocate_number(payment.facility, "receipt"),
        invoice=payment.invoice,
        patient=payment.patient,
        facility=payment.facility,
        amount=-payment.amount,
        method=payment.method,
        status=PaymentStatus.COMPLETED,
        reference=payment.reference,
        counter=payment.counter,
        received_by_id=getattr(actor, "uuid", None),
        received_by_name=getattr(actor, "full_name", ""),
        refunds=payment,
        refund_reason=reason,
        refund_approved_by_id=getattr(approver, "uuid", None),
        created_by_id=getattr(actor, "uuid", None),
    )

    payment.status = PaymentStatus.REFUNDED
    payment.save(update_fields=["status", "updated_at"])
    _apply_payment_totals(payment.invoice)

    record(
        AuditAction.REFUND,
        entity_type="billing.Payment",
        entity_id=refund.uuid,
        entity_label=f"Refund of {payment.receipt_number}",
        reason=reason,
        metadata={"approved_by": str(getattr(approver, "uuid", ""))},
    )
    logger.warning(
        "REFUND %s of %s by %s approved by %s: %s",
        refund.receipt_number, payment.amount,
        getattr(actor, "email", "?"), getattr(approver, "email", "?"), reason,
    )
    return refund


@tenant_atomic_method
def record_counter_refund(
    credit_note: Invoice,
    amount,
    method: str,
    actor=None,
    counter: str = "",
    reference: str = "",
    reason: str = "",
) -> Payment:
    """Hand money back across the counter against a credit note.

    Distinct from `refund_payment`, which reverses one specific payment in
    full. A counter return is usually partial -- two of the four boxes come
    back -- and the customer may have paid by two methods, so there is no
    single payment row to reverse. What there is, is a credit note for the
    goods returned; this pays it off, negatively.

    The amount is negative for the same reason `refund_payment`'s is: a
    refund is cash leaving the drawer, and the day's takings should net it out
    rather than count it as income.
    """
    amount = money(amount)
    if amount <= ZERO:
        raise BillingError("A refund must be a positive amount to hand back.")
    if not credit_note.is_credit_note:
        raise BillingError("A counter refund must be against a credit note.")
    if credit_note.status == InvoiceStatus.DRAFT:
        raise BillingError("Issue the credit note before refunding against it.")

    # `balance_due` on a credit note is negative -- it is money owed *to* the
    # customer -- so the comparison is against its magnitude.
    outstanding = -credit_note.balance_due
    if amount > outstanding:
        raise BillingError(
            f"That is more than the {outstanding} outstanding on "
            f"{credit_note.number}.",
            detail={"outstanding": str(outstanding), "offered": str(amount)},
        )

    refund = Payment.objects.create(
        receipt_number=allocate_number(credit_note.facility, "receipt"),
        invoice=credit_note,
        patient=credit_note.patient,
        facility=credit_note.facility,
        amount=-amount,
        method=method,
        status=PaymentStatus.COMPLETED,
        reference=reference,
        counter=counter,
        received_by_id=getattr(actor, "uuid", None),
        received_by_name=getattr(actor, "full_name", ""),
        refund_reason=reason,
        created_by_id=getattr(actor, "uuid", None),
    )
    _apply_payment_totals(credit_note)

    record(
        AuditAction.REFUND,
        entity_type="billing.Payment",
        entity_id=refund.uuid,
        entity_label=f"Counter refund on {credit_note.number}",
        reason=reason,
    )
    logger.warning(
        "COUNTER REFUND %s of %s at %s by %s: %s",
        refund.receipt_number, amount, counter or "?",
        getattr(actor, "email", "?"), reason,
    )
    return refund


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def patient_account(patient) -> dict:
    """What a patient owes, has paid, and has outstanding."""
    invoices = Invoice.objects.filter(patient=patient).exclude(
        status=InvoiceStatus.DRAFT
    )
    billed = invoices.aggregate(total=models.Sum("total"))["total"] or ZERO
    paid = invoices.aggregate(total=models.Sum("amount_paid"))["total"] or ZERO
    pending_charges = Charge.objects.filter(
        patient=patient, status=ChargeStatus.PENDING
    )
    uninvoiced = pending_charges.aggregate(total=models.Sum("total"))["total"] or ZERO

    # Outstanding is floored at zero. A negative "amount owed" is not a
    # thing a patient can act on; money owed *to* a patient is a credit
    # balance, which is a different concept and reported separately.
    outstanding = billed - paid

    return {
        "patient_uuid": str(patient.uuid),
        "patient_mrn": patient.mrn,
        "total_billed": money(billed),
        "total_paid": money(paid),
        "outstanding": money(max(outstanding, ZERO)),
        "credit_balance": money(abs(min(outstanding, ZERO))),
        "uninvoiced_charges": money(uninvoiced),
        "uninvoiced_count": pending_charges.count(),
        "invoices": [
            {
                "number": invoice.number,
                "issued_at": invoice.issued_at,
                "total": invoice.total,
                "paid": invoice.amount_paid,
                "balance": invoice.balance_due,
                "status": invoice.status,
                "is_credit_note": invoice.is_credit_note,
            }
            for invoice in invoices.order_by("-issued_at")[:20]
        ],
    }


def daily_collection(facility, on_date=None) -> dict:
    """End-of-day cash-up, split by method.

    The report a counter reconciles against at close of shift, which is why
    it is by method rather than a single total: the cash drawer is counted
    separately from the wallet settlements.
    """
    on_date = on_date or timezone.localdate()
    payments = Payment.objects.filter(
        facility=facility,
        received_at__date=on_date,
        status__in=BANKED_STATUSES,
    )

    by_method = {}
    for method, label in PaymentMethod.choices:
        total = payments.filter(method=method).aggregate(
            total=models.Sum("amount")
        )["total"]
        if total:
            by_method[method] = {"label": label, "total": money(total)}

    gross = payments.filter(amount__gt=ZERO).aggregate(
        total=models.Sum("amount")
    )["total"] or ZERO
    refunded = payments.filter(amount__lt=ZERO).aggregate(
        total=models.Sum("amount")
    )["total"] or ZERO

    invoices = Invoice.objects.filter(
        facility=facility, issued_at__date=on_date
    ).exclude(status=InvoiceStatus.DRAFT)

    return {
        "date": on_date.isoformat(),
        "facility": facility.name,
        "gross_collected": money(gross),
        "refunded": money(abs(refunded)),
        "net_collected": money(gross + refunded),
        "by_method": by_method,
        "invoices_issued": invoices.filter(is_credit_note=False).count(),
        "credit_notes_issued": invoices.filter(is_credit_note=True).count(),
        "invoiced_total": money(
            invoices.aggregate(total=models.Sum("total"))["total"] or ZERO
        ),
        "payment_count": payments.count(),
    }


def _snapshot(invoice: Invoice) -> dict:
    return {
        "number": invoice.number,
        "fiscal_year": invoice.fiscal_year,
        # Blank for a retail sale to a walk-in: there is no patient, and the
        # snapshot has to survive that rather than assume a hospital.
        "patient_mrn": invoice.patient.mrn if invoice.patient_id else "",
        "bill_to_name": invoice.bill_to_name,
        "issued_at": invoice.issued_at.isoformat() if invoice.issued_at else None,
        "subtotal": str(invoice.subtotal),
        "discount_total": str(invoice.discount_total),
        "tax_total": str(invoice.tax_total),
        "total": str(invoice.total),
        "is_credit_note": invoice.is_credit_note,
        "lines": [
            {
                "service_code": line.service_code,
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "discount_amount": str(line.discount_amount),
                "tax_amount": str(line.tax_amount),
                "total": str(line.total),
            }
            for line in invoice.lines.all()
        ],
    }
