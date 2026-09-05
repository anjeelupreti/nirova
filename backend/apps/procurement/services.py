"""Requisitions, quotations, orders, receipts and supplier performance."""

import logging
from decimal import Decimal

from django.db import models
from django.utils import timezone

# notify / holders_of: an approval nobody is told about is an approval
# that waits. See development log 164.
from apps.notifications.models import NotificationCategory
from apps.notifications.services import notify, resolve_by_key
from apps.rbac.services import holders_of
from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.entitlements.services import require_module
from apps.pharmacy.models import Batch, MovementType, Product
from apps.pharmacy.services import post_movement, stock_on_hand
from apps.procurement.models import (
    MONEY_ZERO,
    OPEN_ORDER_STATUSES,
    ZERO,
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchaseRequisition,
    Quotation,
    QuotationLine,
    QuotationStatus,
    ReceiptLine,
    ReceiptStatus,
    RequisitionLine,
    RequisitionStatus,
    Supplier,
    SupplierStatus,
)
# assert_different_actors: raising an order and committing the money are the
# maker and the checker of one transaction.
from apps.rbac.services import assert_different_actors
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.procurement")

PAISA = Decimal("0.01")


class ProcurementError(DomainError):
    code = "procurement_operation_failed"


class SupplierNotOrderable(ProcurementError):
    code = "supplier_not_orderable"
    status_code = 409


class QuotationComparisonRequired(ProcurementError):
    """A dearer quotation was chosen without saying why.

    Not a refusal — there are good reasons to pay more (shorter lead time, a
    supplier who actually delivers, a licence the cheap one lacks). What is
    unacceptable is the choice being unexplained, because an unexplained
    preference for a dearer supplier is what procurement fraud looks like.
    """

    code = "selection_reason_required"
    status_code = 409
    message = "A quotation that is not the cheapest needs a reason."


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(PAISA)


def _next_reference(model, prefix: str, width: int = 6) -> str:
    """Sequential reference per document type per year."""
    year = timezone.now().year
    stem = f"{prefix}-{year}-"
    last = (
        model.all_objects.filter(reference__startswith=stem)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{stem}{sequence:0{width}d}"


# ---------------------------------------------------------------------------
# Requisitions
# ---------------------------------------------------------------------------


@tenant_atomic_method
def create_requisition(
    organization,
    facility,
    items: list,
    actor=None,
    department=None,
    location=None,
    is_urgent: bool = False,
    required_by=None,
    justification: str = "",
    raised_automatically: bool = False,
) -> PurchaseRequisition:
    """Raise a request to buy.

    The stock position is captured onto each line as it is raised, so an
    approver sees what the requester saw. Looking it up at approval time would
    show today's figure, which may be very different — and would make an
    urgent requisition look unjustified once someone else's delivery landed.
    """
    require_module(organization, ModuleCode.PROCUREMENT)

    if not items:
        raise ProcurementError("A requisition must ask for something.")

    requisition = PurchaseRequisition.objects.create(
        reference=_next_reference(PurchaseRequisition, "PR"),
        facility=facility,
        department=department,
        location=location,
        is_urgent=is_urgent,
        required_by=required_by,
        justification=justification,
        raised_automatically=raised_automatically,
        requested_by_id=getattr(actor, "uuid", None),
        requested_by_name=getattr(actor, "full_name", ""),
        created_by_id=getattr(actor, "uuid", None),
    )

    estimated = MONEY_ZERO
    for item in items:
        product = item["product"]
        quantity = Decimal(str(item["quantity"]))
        price = Decimal(str(item.get("estimated_unit_price") or MONEY_ZERO))

        RequisitionLine.objects.create(
            requisition=requisition,
            product=product,
            product_name=product.display_name,
            quantity=quantity,
            estimated_unit_price=price,
            stock_on_hand=stock_on_hand(product, location),
            reorder_level=product.reorder_level,
            notes=item.get("notes", ""),
            created_by_id=getattr(actor, "uuid", None),
        )
        estimated += money(quantity * price)

    requisition.estimated_value = estimated
    requisition.save(update_fields=["estimated_value", "updated_at"])

    record(
        AuditAction.CREATE,
        entity_type="procurement.PurchaseRequisition",
        entity_id=requisition.uuid,
        entity_label=f"{requisition.reference} ({len(items)} lines)",
        reason=justification,
        metadata={"urgent": is_urgent, "estimated_value": str(estimated)},
    )
    return requisition


@tenant_atomic_method
def requisitions_from_reorder(organization, facility, location, actor=None) -> PurchaseRequisition | None:
    """Turn the reorder suggestions into a requisition.

    Returns `None` when nothing needs ordering, rather than an empty
    requisition — a document with no lines is noise in an approval queue.

    Marked `raised_automatically` so a buyer can tell computed demand from a
    human's request, and so a run of automated requisitions is recognisable
    when reviewing spend.
    """
    from apps.pharmacy.services import reorder_suggestions

    suggestions = reorder_suggestions(location)
    if not suggestions:
        return None

    items = []
    for row in suggestions:
        product = Product.objects.filter(code=row["product_code"]).first()
        if product is None:
            continue
        items.append(
            {
                "product": product,
                "quantity": row["suggested_quantity"],
                "notes": (
                    f"{row['days_of_cover']} days of cover"
                    if row["days_of_cover"] is not None
                    else "no recent consumption"
                ),
            }
        )

    if not items:
        return None

    urgent = any(row["stockout_before_delivery"] for row in suggestions)
    return create_requisition(
        organization,
        facility,
        items,
        actor=actor,
        location=location,
        is_urgent=urgent,
        justification="Raised from reorder levels.",
        raised_automatically=True,
    )


@tenant_atomic_method
def submit_requisition(requisition: PurchaseRequisition, actor=None) -> PurchaseRequisition:
    if requisition.status != RequisitionStatus.DRAFT:
        raise ProcurementError(
            f"{requisition.reference} is "
            f"{requisition.get_status_display().lower()}.",
            detail={"status": requisition.status},
        )
    if not requisition.lines.exists():
        raise ProcurementError("An empty requisition cannot be submitted.")

    requisition.status = RequisitionStatus.SUBMITTED
    requisition.submitted_at = timezone.now()
    requisition.save(update_fields=["status", "submitted_at", "updated_at"])

    # Tell whoever can approve it. Raised inside this transaction: if the
    # submission is refused there is nothing to approve, and a notification
    # pointing at a rolled-back row is worse than silence.
    notify(
        source="procurement",
        event="requisition_awaiting_approval",
        category=NotificationCategory.APPROVAL,
        title=f"{requisition.reference} needs approval",
        body=f"{requisition.lines.count()} line(s) from "
             f"{requisition.department.name if requisition.department_id else 'the store'}.",
        link="/procurement",
        recipients=holders_of(
            "purchase.approve",
            facility=requisition.facility,
            exclude_user_id=getattr(actor, "uuid", None),
        ),
        subject_type="procurement.PurchaseRequisition",
        subject_uuid=requisition.uuid,
        facility=requisition.facility,
        actor_name=getattr(actor, "full_name", "") or "",
        dedupe_key=f"requisition_approval:{requisition.uuid}",
    )
    return requisition


@tenant_atomic_method
def decide_requisition(
    requisition: PurchaseRequisition,
    approve: bool,
    actor=None,
    notes: str = "",
) -> PurchaseRequisition:
    """Approve or reject a requisition.

    The requester may not approve their own. This is the first control in the
    chain, and the cheapest one to enforce.
    """
    if requisition.status != RequisitionStatus.SUBMITTED:
        raise ProcurementError(
            f"{requisition.reference} is not awaiting a decision.",
            detail={"status": requisition.status},
        )
    if approve:
        assert_different_actors(
            requisition.requested_by_id,
            getattr(actor, "uuid", None),
            "requisition approval",
        )
    elif not notes.strip():
        raise ProcurementError("A rejection must say why.")

    requisition.status = (
        RequisitionStatus.APPROVED if approve else RequisitionStatus.REJECTED
    )
    requisition.approved_by_id = getattr(actor, "uuid", None)
    requisition.approved_by_name = getattr(actor, "full_name", "")
    requisition.approved_at = timezone.now()
    requisition.decision_notes = notes
    requisition.save(
        update_fields=[
            "status", "approved_by_id", "approved_by_name",
            "approved_at", "decision_notes", "updated_at",
        ]
    )

    record(
        AuditAction.APPROVE if approve else AuditAction.REJECT,
        entity_type="procurement.PurchaseRequisition",
        entity_id=requisition.uuid,
        entity_label=requisition.reference,
        reason=notes,
        metadata={"estimated_value": str(requisition.estimated_value)},
    )
    # The approval is no longer waiting on anybody. The copies stay
    # readable, marked resolved -- who approved it and when is worth
    # being able to look up.
    resolve_by_key(f"requisition_approval:{requisition.uuid}", reason="Decided")

    return requisition


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------


@tenant_atomic_method
def record_quotation(
    requisition: PurchaseRequisition,
    supplier: Supplier,
    lines: list,
    actor=None,
    valid_until=None,
    quoted_lead_time_days=None,
    payment_terms: str = "",
) -> Quotation:
    """Record what a supplier quoted."""
    if requisition.status not in {
        RequisitionStatus.SUBMITTED,
        RequisitionStatus.APPROVED,
    }:
        raise ProcurementError(
            f"{requisition.reference} is not open for quotations.",
            detail={"status": requisition.status},
        )

    quotation = Quotation.objects.create(
        reference=_next_reference(Quotation, "QT"),
        requisition=requisition,
        supplier=supplier,
        status=QuotationStatus.RECEIVED,
        received_at=timezone.now(),
        valid_until=valid_until,
        quoted_lead_time_days=quoted_lead_time_days,
        payment_terms=payment_terms,
        created_by_id=getattr(actor, "uuid", None),
    )

    total = MONEY_ZERO
    for entry in lines:
        product = entry["product"]
        quantity = Decimal(str(entry["quantity"]))
        unit_price = Decimal(str(entry["unit_price"]))
        discount = Decimal(str(entry.get("discount_percent") or 0))
        tax = Decimal(str(entry.get("tax_percent") or 0))

        gross = money(quantity * unit_price)
        net = gross - money(gross * discount / Decimal("100"))
        line_total = net + money(net * tax / Decimal("100"))

        QuotationLine.objects.create(
            quotation=quotation,
            product=product,
            product_name=product.display_name,
            quantity=quantity,
            unit_price=unit_price,
            discount_percent=discount,
            tax_percent=tax,
            free_quantity=Decimal(str(entry.get("free_quantity") or 0)),
            total=line_total,
            created_by_id=getattr(actor, "uuid", None),
        )
        total += line_total

    quotation.total_value = total
    quotation.save(update_fields=["total_value", "updated_at"])
    return quotation


def compare_quotations(requisition: PurchaseRequisition) -> dict:
    """Line up the quotations against each other.

    Ranks on **blended effective cost per unit** — total spend divided by
    total units actually received, free ones included.

    Not on total spend, which is only comparable when the quantities are
    equal, and free units are exactly the case where they are not. A quote of
    4,600 for 600 units beats one of 4,300 for 500, and ranking on the totals
    picks the wrong supplier while the per-unit figures on the same screen say
    otherwise.

    Total spend is still reported, because the buyer also has a budget and a
    cheaper unit price on more stock than they need is not automatically the
    right answer.
    """
    quotations = list(
        requisition.quotations.filter(
            status__in=[QuotationStatus.RECEIVED, QuotationStatus.SELECTED]
        ).select_related("supplier").prefetch_related("lines")
    )
    if not quotations:
        return {"count": 0, "quotations": [], "cheapest": None}

    rows = []
    for quotation in quotations:
        lines = list(quotation.lines.all())
        total_units = sum(
            (line.quantity + line.free_quantity for line in lines), ZERO
        )
        blended = (
            money(quotation.total_value / total_units)
            if total_units > ZERO
            else quotation.total_value
        )
        rows.append(
            {
                "uuid": str(quotation.uuid),
                "reference": quotation.reference,
                "supplier": quotation.supplier.name,
                "supplier_uuid": str(quotation.supplier.uuid),
                "total_value": quotation.total_value,
                "total_units": total_units,
                #: The number to rank on: what each unit actually costs.
                "cost_per_unit": blended,
                "lead_time_days": quotation.quoted_lead_time_days,
                "valid_until": quotation.valid_until,
                "is_expired": quotation.is_expired,
                "can_order_from": quotation.supplier.can_order_from,
                "status": quotation.status,
                "lines": [
                    {
                        "product": line.product_name,
                        "quantity": str(line.quantity),
                        "free_quantity": str(line.free_quantity),
                        "unit_price": str(line.unit_price),
                        "effective_unit_cost": str(line.effective_unit_cost),
                        "total": str(line.total),
                    }
                    for line in lines
                ],
            }
        )

    # Only orderable, unexpired quotations can be the benchmark: naming a
    # cheapest that cannot legally be bought from would be worse than useless.
    eligible = [r for r in rows if r["can_order_from"] and not r["is_expired"]]
    rows.sort(key=lambda r: r["cost_per_unit"])
    cheapest = min(eligible, key=lambda r: r["cost_per_unit"]) if eligible else None

    return {
        "count": len(rows),
        "quotations": rows,
        "cheapest": cheapest["uuid"] if cheapest else None,
        "cheapest_cost_per_unit": cheapest["cost_per_unit"] if cheapest else None,
        "cheapest_total": cheapest["total_value"] if cheapest else None,
        "ineligible": [r["reference"] for r in rows if r not in eligible],
    }


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------


@tenant_atomic_method
def create_order(
    organization,
    facility,
    supplier: Supplier,
    lines: list,
    actor=None,
    requisition=None,
    quotation=None,
    deliver_to=None,
    expected_delivery=None,
    selection_reason: str = "",
    payment_terms: str = "",
    notes: str = "",
) -> PurchaseOrder:
    """Raise a purchase order.

    Refuses a supplier who is on hold, blacklisted, or whose drug licence has
    lapsed. The licence check is not commercial housekeeping: buying medicines
    from an unlicensed distributor is a regulatory breach, and the moment to
    catch it is before the order goes out.

    When the order follows a quotation that is not the cheapest, a reason is
    required — see `QuotationComparisonRequired`.
    """
    require_module(organization, ModuleCode.PROCUREMENT)

    if not supplier.can_order_from:
        reason = (
            "their drug licence has expired"
            if supplier.licence_expired
            else f"they are {supplier.get_status_display().lower()}"
        )
        raise SupplierNotOrderable(
            f"Cannot order from {supplier.name}: {reason}.",
            detail={
                "supplier": supplier.code,
                "status": supplier.status,
                "licence_expires_on": (
                    supplier.drug_licence_expires_on.isoformat()
                    if supplier.drug_licence_expires_on
                    else None
                ),
            },
        )

    if quotation is not None and requisition is not None:
        comparison = compare_quotations(requisition)
        if (
            comparison["cheapest"]
            and comparison["cheapest"] != str(quotation.uuid)
            and not selection_reason.strip()
        ):
            raise QuotationComparisonRequired(
                f"{quotation.supplier.name} is not the cheapest quotation. "
                "Give a reason for choosing them.",
                detail=comparison,
            )

    order = PurchaseOrder.objects.create(
        reference=_next_reference(PurchaseOrder, "PO"),
        facility=facility,
        supplier=supplier,
        requisition=requisition,
        quotation=quotation,
        deliver_to=deliver_to,
        expected_delivery=(
            expected_delivery
            or timezone.localdate()
            + timezone.timedelta(days=supplier.agreed_lead_time_days)
        ),
        payment_terms=payment_terms or f"{supplier.credit_days} days",
        notes=notes,
        created_by_name=getattr(actor, "full_name", ""),
        created_by_id=getattr(actor, "uuid", None),
    )

    subtotal = discount_total = tax_total = MONEY_ZERO
    for index, entry in enumerate(lines):
        product = entry["product"]
        line = PurchaseOrderLine(
            order=order,
            product=product,
            requisition_line=entry.get("requisition_line"),
            product_name=product.display_name,
            product_code=product.code,
            quantity=Decimal(str(entry["quantity"])),
            free_quantity=Decimal(str(entry.get("free_quantity") or 0)),
            unit_price=Decimal(str(entry["unit_price"])),
            discount_percent=Decimal(str(entry.get("discount_percent") or 0)),
            tax_percent=Decimal(str(entry.get("tax_percent") or 0)),
            display_order=index,
            created_by_id=getattr(actor, "uuid", None),
        )
        line.line_total = line.compute_total()
        line.save()

        gross = money(line.quantity * line.unit_price)
        discount = money(gross * line.discount_percent / Decimal("100"))
        net = gross - discount
        subtotal += gross
        discount_total += discount
        tax_total += money(net * line.tax_percent / Decimal("100"))

        # Track how much of the requisition this order covers, so a basket
        # split across two suppliers closes the requisition correctly.
        if line.requisition_line:
            line.requisition_line.ordered_quantity += line.quantity
            line.requisition_line.save(
                update_fields=["ordered_quantity", "updated_at"]
            )

    order.subtotal = subtotal
    order.discount_total = discount_total
    order.tax_total = tax_total
    order.total = money(subtotal - discount_total + tax_total)
    order.save(
        update_fields=[
            "subtotal", "discount_total", "tax_total", "total", "updated_at"
        ]
    )

    if quotation is not None:
        quotation.status = QuotationStatus.SELECTED
        quotation.selection_reason = selection_reason
        quotation.selected_by_id = getattr(actor, "uuid", None)
        quotation.save(
            update_fields=[
                "status", "selection_reason", "selected_by_id", "updated_at"
            ]
        )

    if requisition is not None:
        _refresh_requisition_status(requisition)

    record(
        AuditAction.CREATE,
        entity_type="procurement.PurchaseOrder",
        entity_id=order.uuid,
        entity_label=f"{order.reference} — {supplier.name}",
        reason=selection_reason,
        metadata={"total": str(order.total), "lines": len(lines)},
    )
    return order


def _refresh_requisition_status(requisition: PurchaseRequisition) -> None:
    """Move a requisition on once its lines are covered by orders."""
    lines = list(requisition.lines.all())
    if not lines:
        return
    if all(line.is_fully_ordered for line in lines):
        requisition.status = RequisitionStatus.ORDERED
    elif any(line.ordered_quantity > ZERO for line in lines):
        requisition.status = RequisitionStatus.PARTIALLY_ORDERED
    else:
        return
    requisition.save(update_fields=["status", "updated_at"])


@tenant_atomic_method
def approve_order(order: PurchaseOrder, actor=None) -> PurchaseOrder:
    """Approve a purchase order, committing the organization to the spend.

    The person who raised it may not approve it. Raising an order and
    committing money against it are the maker and checker of one transaction,
    and this is the point at which the organization is actually bound.
    """
    if order.status not in {
        PurchaseOrderStatus.DRAFT,
        PurchaseOrderStatus.PENDING_APPROVAL,
    }:
        raise ProcurementError(
            f"{order.reference} is {order.get_status_display().lower()}.",
            detail={"status": order.status},
        )

    assert_different_actors(
        order.created_by_id, getattr(actor, "uuid", None), "purchase order approval"
    )

    # Re-check the supplier at approval: an order raised last week against a
    # supplier whose licence has since lapsed must not go out.
    if not order.supplier.can_order_from:
        raise SupplierNotOrderable(
            f"{order.supplier.name} can no longer be ordered from.",
            detail={"supplier": order.supplier.code, "status": order.supplier.status},
        )

    order.status = PurchaseOrderStatus.APPROVED
    order.approved_by_id = getattr(actor, "uuid", None)
    order.approved_by_name = getattr(actor, "full_name", "")
    order.approved_at = timezone.now()
    order.save(
        update_fields=[
            "status", "approved_by_id", "approved_by_name",
            "approved_at", "updated_at",
        ]
    )

    record(
        AuditAction.APPROVE,
        entity_type="procurement.PurchaseOrder",
        entity_id=order.uuid,
        entity_label=f"{order.reference} — {order.supplier.name}",
        metadata={"total": str(order.total)},
    )
    return order


@tenant_atomic_method
def cancel_order(order: PurchaseOrder, reason: str, actor=None) -> PurchaseOrder:
    """Cancel an order nothing has been received against."""
    if not reason.strip():
        raise ProcurementError("Cancelling an order must record a reason.")
    if order.receipts.exclude(status=ReceiptStatus.DRAFT).exists():
        raise ProcurementError(
            "Goods have already been received against this order. Close it "
            "short instead.",
            detail={"reference": order.reference},
        )

    order.status = PurchaseOrderStatus.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancellation_reason = reason
    order.save(
        update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"]
    )
    record(
        AuditAction.CANCEL,
        entity_type="procurement.PurchaseOrder",
        entity_id=order.uuid,
        entity_label=order.reference,
        reason=reason,
    )
    return order


# ---------------------------------------------------------------------------
# Goods receipt
# ---------------------------------------------------------------------------


@tenant_atomic_method
def create_receipt(
    order: PurchaseOrder,
    location,
    lines: list,
    actor=None,
    delivery_note_number: str = "",
    supplier_invoice_number: str = "",
    supplier_invoice_amount=None,
    notes: str = "",
) -> GoodsReceipt:
    """Book a delivery in, pending quality check.

    Nothing reaches stock here. The receipt is recorded, quality is checked,
    and only then is it posted — because stock that failed inspection should
    never have been dispensable, and reversing it afterwards leaves a window
    in which it could have gone out.
    """
    if order.status not in OPEN_ORDER_STATUSES:
        raise ProcurementError(
            f"{order.reference} is {order.get_status_display().lower()} and "
            "cannot receive goods.",
            detail={"status": order.status},
        )
    if not lines:
        raise ProcurementError("A receipt must contain something.")

    receipt = GoodsReceipt.objects.create(
        reference=_next_reference(GoodsReceipt, "GRN"),
        order=order,
        supplier=order.supplier,
        facility=order.facility,
        location=location,
        status=ReceiptStatus.QUALITY_CHECK,
        received_by_id=getattr(actor, "uuid", None),
        received_by_name=getattr(actor, "full_name", ""),
        delivery_note_number=delivery_note_number,
        supplier_invoice_number=supplier_invoice_number,
        supplier_invoice_amount=(
            Decimal(str(supplier_invoice_amount))
            if supplier_invoice_amount is not None
            else MONEY_ZERO
        ),
        notes=notes,
        created_by_id=getattr(actor, "uuid", None),
    )

    total = MONEY_ZERO
    for index, entry in enumerate(lines):
        product = entry["product"]
        received = Decimal(str(entry["received_quantity"]))
        free = Decimal(str(entry.get("free_quantity") or 0))
        unit_cost = Decimal(str(entry["unit_cost"]))
        line_total = money(received * unit_cost)

        ReceiptLine.objects.create(
            receipt=receipt,
            order_line=entry.get("order_line"),
            product=product,
            product_name=product.display_name,
            batch_number=entry["batch_number"],
            manufactured_on=entry.get("manufactured_on"),
            expires_on=entry["expires_on"],
            received_quantity=received,
            free_quantity=free,
            # Assume everything is good until quality says otherwise; the
            # check records rejections, not acceptances.
            accepted_quantity=received + free,
            unit_cost=unit_cost,
            selling_price=Decimal(str(entry.get("selling_price") or 0)),
            mrp=Decimal(str(entry.get("mrp") or 0)),
            line_total=line_total,
            display_order=index,
            created_by_id=getattr(actor, "uuid", None),
        )
        total += line_total

    receipt.total_value = total
    receipt.save(update_fields=["total_value", "updated_at"])
    return receipt


@tenant_atomic_method
def quality_check(receipt: GoodsReceipt, rejections: list, actor=None,
                  notes: str = "") -> GoodsReceipt:
    """Record what failed inspection.

    `rejections` is a list of `{line_uuid, quantity, reason}`. Anything not
    listed is accepted — the check records exceptions, because in a normal
    delivery almost everything is fine and requiring a positive acceptance
    per line turns inspection into box-ticking.
    """
    if receipt.status != ReceiptStatus.QUALITY_CHECK:
        raise ProcurementError(
            f"{receipt.reference} is not awaiting a quality check.",
            detail={"status": receipt.status},
        )

    by_uuid = {str(line.uuid): line for line in receipt.lines.all()}
    rejected_any = False

    for rejection in rejections:
        line = by_uuid.get(str(rejection.get("line_uuid")))
        if line is None:
            continue
        quantity = Decimal(str(rejection["quantity"]))
        reason = (rejection.get("reason") or "").strip()
        if not reason:
            raise ProcurementError(
                f"{line.product_name}: a rejection must say why.",
                detail={"line": str(line.uuid)},
            )
        if quantity > line.total_units:
            raise ProcurementError(
                f"{line.product_name}: rejecting more than arrived.",
                detail={
                    "rejected": str(quantity),
                    "received": str(line.total_units),
                },
            )

        line.rejected_quantity = quantity
        line.accepted_quantity = line.total_units - quantity
        line.rejection_reason = reason
        line.save(
            update_fields=[
                "rejected_quantity", "accepted_quantity",
                "rejection_reason", "updated_at",
            ]
        )
        rejected_any = True

    all_rejected = all(
        line.accepted_quantity <= ZERO for line in receipt.lines.all()
    )
    receipt.status = (
        ReceiptStatus.REJECTED
        if all_rejected
        else ReceiptStatus.PARTIALLY_REJECTED if rejected_any
        else ReceiptStatus.ACCEPTED
    )
    receipt.quality_checked_by_id = getattr(actor, "uuid", None)
    receipt.quality_checked_at = timezone.now()
    receipt.quality_notes = notes
    receipt.save(
        update_fields=[
            "status", "quality_checked_by_id", "quality_checked_at",
            "quality_notes", "updated_at",
        ]
    )

    if rejected_any:
        logger.warning(
            "Quality rejection on %s from %s: %s",
            receipt.reference, receipt.supplier.name, notes or "see lines",
        )
    return receipt


@tenant_atomic_method
def post_receipt(receipt: GoodsReceipt, actor=None) -> dict:
    """Create the batches and post the stock movements.

    This is the single door through which purchased stock enters. Every batch
    it creates carries the receipt reference, so a batch on a shelf can be
    traced to the delivery, the order, the quotation and the requisition.

    Free units are folded into the batch quantity but not into its cost, and
    the unit cost is the *effective* one — free stock dilutes the cost of the
    delivery rather than arriving at zero.
    """
    if receipt.status not in {
        ReceiptStatus.ACCEPTED,
        ReceiptStatus.PARTIALLY_REJECTED,
    }:
        raise ProcurementError(
            f"{receipt.reference} is {receipt.get_status_display().lower()}; "
            "only a quality-checked receipt can be posted.",
            detail={"status": receipt.status},
        )

    posted = []
    for line in receipt.lines.all():
        if line.accepted_quantity <= ZERO:
            continue

        batch, _ = Batch.objects.get_or_create(
            product=line.product,
            batch_number=line.batch_number,
            expires_on=line.expires_on,
            defaults={
                "manufactured_on": line.manufactured_on,
                "purchase_price": line.effective_unit_cost,
                "selling_price": line.selling_price,
                "mrp": line.mrp,
                "supplier_name": receipt.supplier.name,
                "receipt_reference": receipt.reference,
                "created_by_id": getattr(actor, "uuid", None),
            },
        )

        post_movement(
            batch=batch,
            location=receipt.location,
            movement_type=MovementType.PURCHASE,
            quantity=line.accepted_quantity,
            actor=actor,
            unit_cost=line.effective_unit_cost,
            reason=f"Received on {receipt.reference} from {receipt.supplier.name}",
            reference_type="procurement.GoodsReceipt",
            reference_id=str(receipt.uuid),
        )

        line.batch = batch
        line.save(update_fields=["batch", "updated_at"])

        if line.order_line:
            line.order_line.received_quantity += line.accepted_quantity
            line.order_line.rejected_quantity += line.rejected_quantity
            line.order_line.save(
                update_fields=[
                    "received_quantity", "rejected_quantity", "updated_at"
                ]
            )

        posted.append(
            {
                "product": line.product_name,
                "batch": batch.batch_number,
                "quantity": str(line.accepted_quantity),
                "unit_cost": str(line.effective_unit_cost),
                "expires_on": line.expires_on.isoformat(),
            }
        )

    receipt.status = ReceiptStatus.POSTED
    receipt.posted_at = timezone.now()
    receipt.save(update_fields=["status", "posted_at", "updated_at"])

    _refresh_order_status(receipt.order)

    record(
        AuditAction.CREATE,
        entity_type="procurement.GoodsReceipt",
        entity_id=receipt.uuid,
        entity_label=f"{receipt.reference} posted to stock",
        metadata={
            "batches": len(posted),
            "value": str(receipt.total_value),
            "invoice_matches": receipt.invoice_matches,
        },
    )

    if receipt.invoice_matches is False:
        logger.warning(
            "Invoice mismatch on %s: supplier says %s, received %s",
            receipt.reference,
            receipt.supplier_invoice_amount,
            receipt.total_value,
        )

    return {"reference": receipt.reference, "batches": posted}


def _refresh_order_status(order: PurchaseOrder) -> None:
    lines = list(order.lines.all())
    if not lines:
        return
    if all(line.is_complete for line in lines):
        order.status = PurchaseOrderStatus.RECEIVED
    elif any(line.received_quantity > ZERO for line in lines):
        order.status = PurchaseOrderStatus.PARTIALLY_RECEIVED
    else:
        return
    order.save(update_fields=["status", "updated_at"])


# ---------------------------------------------------------------------------
# Supplier performance
# ---------------------------------------------------------------------------


def supplier_performance(supplier: Supplier, since=None) -> dict:
    """How a supplier has actually behaved.

    Every figure is computed from receipts rather than stored on the supplier,
    because a performance score somebody typed is a performance score somebody
    chose. The gap between the agreed lead time and the measured one is the
    number worth looking at.
    """
    since = since or (timezone.now() - timezone.timedelta(days=365))

    orders = PurchaseOrder.objects.filter(
        supplier=supplier, created_at__gte=since
    ).exclude(status=PurchaseOrderStatus.DRAFT)
    receipts = GoodsReceipt.objects.filter(
        supplier=supplier, status=ReceiptStatus.POSTED, posted_at__gte=since
    ).prefetch_related("lines")

    lead_times = []
    for receipt in receipts:
        if receipt.order.approved_at:
            lead_times.append(
                (receipt.received_on - receipt.order.approved_at.date()).days
            )

    # Expected includes free units: they are part of what the supplier
    # undertook to deliver, so counting them as delivery against a denominator
    # that excludes them produced fill rates above 100%.
    expected = ZERO
    received = ZERO
    rejected = ZERO
    for order in orders.prefetch_related("lines"):
        for line in order.lines.all():
            expected += line.quantity + line.free_quantity
            received += line.received_quantity
            rejected += line.rejected_quantity

    measured_lead_time = (
        int(sum(lead_times) / len(lead_times)) if lead_times else None
    )
    late_orders = [o for o in orders if o.is_overdue]

    return {
        "supplier": supplier.name,
        "code": supplier.code,
        "status": supplier.status,
        "can_order_from": supplier.can_order_from,
        "licence_expired": supplier.licence_expired,
        "since": since.isoformat(),
        "orders": orders.count(),
        "order_value": money(
            orders.aggregate(total=models.Sum("total"))["total"] or MONEY_ZERO
        ),
        "receipts": receipts.count(),
        "agreed_lead_time_days": supplier.agreed_lead_time_days,
        "measured_lead_time_days": measured_lead_time,
        #: Positive means slower than promised.
        "lead_time_variance": (
            measured_lead_time - supplier.agreed_lead_time_days
            if measured_lead_time is not None
            else None
        ),
        "expected_units": expected,
        "received_units": received,
        "fill_rate_percent": (
            round(float(received / expected) * 100, 1) if expected > ZERO else None
        ),
        "rejection_rate_percent": (
            round(float(rejected / received) * 100, 1) if received > ZERO else None
        ),
        "orders_late": len(late_orders),
        "currently_overdue": [
            {
                "reference": order.reference,
                "expected": order.expected_delivery,
                "days_late": order.days_late,
                "value": str(order.total),
            }
            for order in late_orders
        ],
    }


def procurement_dashboard(facility) -> dict:
    """What the buyer needs to see this morning."""
    requisitions = PurchaseRequisition.objects.filter(facility=facility)
    orders = PurchaseOrder.objects.filter(facility=facility)
    open_orders = orders.filter(status__in=list(OPEN_ORDER_STATUSES))
    overdue = [order for order in open_orders if order.is_overdue]

    return {
        "facility": facility.name,
        "requisitions_awaiting_approval": requisitions.filter(
            status=RequisitionStatus.SUBMITTED
        ).count(),
        "requisitions_approved_unordered": requisitions.filter(
            status=RequisitionStatus.APPROVED
        ).count(),
        "orders_awaiting_approval": orders.filter(
            status__in=[
                PurchaseOrderStatus.DRAFT,
                PurchaseOrderStatus.PENDING_APPROVAL,
            ]
        ).count(),
        "orders_open": open_orders.count(),
        "orders_overdue": len(overdue),
        "open_order_value": money(
            open_orders.aggregate(total=models.Sum("total"))["total"] or MONEY_ZERO
        ),
        "receipts_awaiting_check": GoodsReceipt.objects.filter(
            facility=facility, status=ReceiptStatus.QUALITY_CHECK
        ).count(),
        "receipts_awaiting_posting": GoodsReceipt.objects.filter(
            facility=facility,
            status__in=[ReceiptStatus.ACCEPTED, ReceiptStatus.PARTIALLY_REJECTED],
        ).count(),
        "suppliers_blocked": Supplier.objects.exclude(
            status=SupplierStatus.ACTIVE
        ).count(),
        "licences_expiring": Supplier.objects.filter(
            status=SupplierStatus.ACTIVE,
            drug_licence_expires_on__lte=timezone.localdate()
            + timezone.timedelta(days=60),
        ).count(),
        "overdue_orders": [
            {
                "reference": order.reference,
                "supplier": order.supplier.name,
                "expected": order.expected_delivery,
                "days_late": order.days_late,
                "value": str(order.total),
            }
            for order in sorted(overdue, key=lambda o: o.days_late, reverse=True)[:10]
        ],
    }
