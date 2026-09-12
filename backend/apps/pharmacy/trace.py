"""Where a batch came from, where every unit went, and who has it now.

The recall question, answered from the ledger end to end. **The previous
answer missed every counter sale**: `recall_exposure` listed dispensing to
patients only, so a recalled batch sold over the counter — to a walk-in
customer, or to a patient buying without a prescription — did not appear in
the list of people to contact at all. On a pharmacy that does most of its
volume at the counter, that is most of the exposure.

A trace has four parts, each built from `StockEntry` rows and nothing else:

* **Origin** — the goods receipts that brought it in: supplier, receipt
  reference, date, quantity, cost.
* **Recipients** — everyone it reached: patients it was dispensed to, and
  counter sales **net of what came back** (returns and voids), with whatever
  identity the sale holds — a patient, a named customer and phone, or only a
  sale reference for an anonymous walk-in. A sale with nothing left after
  returns is not a recipient.
* **Where it is** — the balance at each location, including quarantine.
* **The ledger** — every movement in order, so any figure above can be
  checked line by line.

And a **reconciliation**: everything in minus everything out must equal what
the locations hold. A difference means stock moved without a ledger entry,
and a trace that silently absorbed it would be a trace nobody should rely on.
"""

from collections import OrderedDict
from decimal import Decimal

from django.db import models

from apps.pharmacy.models import (
    INBOUND_MOVEMENTS,
    Batch,
    BatchStock,
    MovementType,
    StockEntry,
)

ZERO = Decimal("0.000")

#: Movements that take stock out of the building to a person.
TO_PEOPLE = {MovementType.DISPENSE, MovementType.SALE}
#: Movements that remove stock without it reaching anybody.
WRITTEN_OFF = {
    MovementType.DAMAGE, MovementType.EXPIRY, MovementType.RECALL,
    MovementType.PURCHASE_RETURN, MovementType.ADJUSTMENT_DOWN,
    MovementType.CONSUMPTION,
}


def _sale_for_return(reference: str):
    from apps.pos.models import SaleReturn

    found = SaleReturn.objects.filter(reference=reference).select_related("sale").first()
    return found.sale.reference if found else None


def batch_trace(batch: Batch) -> dict:
    entries = list(
        StockEntry.objects.filter(batch=batch)
        .select_related("location", "patient")
        .order_by("occurred_at", "id")
    )

    received = ZERO
    out_to_people = ZERO
    written_off = ZERO
    came_back = ZERO
    ledger = []
    origin = []

    # Recipients keyed by where the stock went: a dispensing record, or a sale.
    recipients: "OrderedDict[str, dict]" = OrderedDict()

    for entry in entries:
        inbound = entry.movement_type in INBOUND_MOVEMENTS
        quantity = entry.quantity
        ledger.append({
            "at": entry.occurred_at,
            "movement": entry.movement_type,
            "movement_label": entry.get_movement_type_display(),
            "direction": "in" if inbound else "out",
            "quantity": str(quantity),
            "balance_after": str(entry.balance_after),
            "location": entry.location.code,
            "reference": f"{entry.reference_type} {entry.reference_id}".strip(),
            "by": entry.performed_by_name,
            "patient": entry.patient.full_name if entry.patient_id else "",
        })

        if entry.movement_type in (MovementType.PURCHASE, MovementType.OPENING):
            received += quantity
            origin.append({
                "at": entry.occurred_at,
                "kind": entry.get_movement_type_display(),
                "quantity": str(quantity),
                "reference": entry.reference_id or batch.receipt_reference,
                "supplier": batch.supplier_name,
                "unit_cost": str(entry.unit_cost),
            })
        elif entry.movement_type == MovementType.DISPENSE:
            out_to_people += quantity
            key = f"dispense:{entry.reference_id or entry.id}"
            recipients[key] = {
                "kind": "dispensed",
                "at": entry.occurred_at,
                "reference": entry.reference_id,
                "patient_mrn": entry.patient.mrn if entry.patient_id else "",
                "name": entry.patient.full_name if entry.patient_id else "",
                "phone": entry.patient.phone if entry.patient_id else "",
                "quantity": quantity,
            }
        elif entry.movement_type == MovementType.SALE:
            out_to_people += quantity
            key = f"sale:{entry.reference_id}"
            row = recipients.setdefault(key, {
                "kind": "counter sale",
                "at": entry.occurred_at,
                "reference": entry.reference_id,
                "patient_mrn": entry.patient.mrn if entry.patient_id else "",
                "name": entry.patient.full_name if entry.patient_id else "",
                "phone": entry.patient.phone if entry.patient_id else "",
                "quantity": ZERO,
            })
            row["quantity"] += quantity
        elif entry.movement_type == MovementType.SALES_RETURN:
            came_back += quantity
            # A void references the sale itself; a return references the
            # return, which knows its sale.
            sale_reference = (
                entry.reference_id if entry.reference_type == "pos.Sale"
                else _sale_for_return(entry.reference_id)
            )
            if sale_reference and f"sale:{sale_reference}" in recipients:
                recipients[f"sale:{sale_reference}"]["quantity"] -= quantity
        elif entry.movement_type in WRITTEN_OFF:
            written_off += quantity

    # Counter sales carry the customer on the sale, not on the ledger line.
    sale_refs = [row["reference"] for row in recipients.values() if row["kind"] == "counter sale"]
    if sale_refs:
        from apps.pos.models import Sale

        for sale in Sale.objects.filter(reference__in=sale_refs).select_related("patient"):
            row = recipients.get(f"sale:{sale.reference}")
            if row is None or row["name"]:
                continue
            row["name"] = sale.customer_label or sale.customer_name or "Walk-in customer"
            row["phone"] = sale.customer_phone or (sale.patient.phone if sale.patient_id else "")
            row["patient_mrn"] = sale.patient.mrn if sale.patient_id else ""

    reached = [
        {**row, "quantity": str(row["quantity"])}
        for row in recipients.values()
        if row["quantity"] > ZERO
    ]

    holding = [
        {
            "location": stock.location.code,
            "location_name": stock.location.name,
            "quarantine": stock.location.is_quarantine,
            "quantity": str(stock.quantity),
        }
        for stock in BatchStock.objects.filter(batch=batch, quantity__gt=ZERO).select_related("location")
    ]
    held = sum((Decimal(row["quantity"]) for row in holding), ZERO)

    total_in = sum((entry.quantity for entry in entries if entry.movement_type in INBOUND_MOVEMENTS), ZERO)
    total_out = sum((entry.quantity for entry in entries if entry.movement_type not in INBOUND_MOVEMENTS), ZERO)
    expected = total_in - total_out

    return {
        "batch": {
            "uuid": str(batch.uuid),
            "batch_number": batch.batch_number,
            "product": batch.product.display_name,
            "product_code": batch.product.code,
            "expires_on": batch.expires_on,
            "status": batch.status,
            "supplier": batch.supplier_name,
            "received_on": batch.received_on,
        },
        "totals": {
            "received": str(received),
            "to_people": str(out_to_people),
            "returned": str(came_back),
            "written_off": str(written_off),
            "held": str(held),
            "recipients": len(reached),
            "identified_recipients": sum(1 for row in reached if row["name"] and row["name"] != "Walk-in customer"),
        },
        "reconciles": expected == held,
        "discrepancy": str(held - expected),
        "origin": origin,
        "recipients": reached,
        "holding": holding,
        "ledger": ledger,
    }


def find_batches(term: str, limit: int = 20):
    """Batches matching a batch number or a product name, newest first."""
    term = (term or "").strip()
    queryset = Batch.objects.select_related("product")
    if term:
        queryset = queryset.filter(
            models.Q(batch_number__icontains=term)
            | models.Q(product__generic_name__icontains=term)
            | models.Q(product__brand_name__icontains=term)
            | models.Q(product__code__iexact=term)
        )
    return list(queryset.order_by("-received_on", "batch_number")[:limit])
