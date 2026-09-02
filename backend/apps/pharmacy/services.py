"""Stock movements, FEFO allocation, dispensing and expiry."""

import logging
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.entitlements.services import require_module
from apps.pharmacy.models import (
    DISPENSABLE_STATUSES,
    INBOUND_MOVEMENTS,
    ZERO,
    Batch,
    BatchStatus,
    BatchStock,
    Dispense,
    DispenseLine,
    DispenseStatus,
    MovementType,
    Product,
    StockCount,
    StockCountLine,
    StockCountStatus,
    StockEntry,
    StockLocation,
    expiry_bucket,
)
# assert_different_actors: a stock adjustment is the classic route for
# concealing theft, so the person who counted may not approve the variance.
from apps.rbac.services import assert_different_actors
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.pharmacy")

QUANTUM = Decimal("0.001")


class PharmacyError(DomainError):
    code = "pharmacy_operation_failed"


class InsufficientStock(PharmacyError):
    code = "insufficient_stock"
    status_code = 409


class FefoOverrideRequired(PharmacyError):
    """A later-expiring batch was chosen while an earlier one has stock.

    Not a refusal. There are real reasons to break FEFO — a damaged outer
    box, a patient who cannot swallow that presentation, a batch physically
    at another counter. What is not acceptable is doing it silently, so the
    override is captured with a reason and an approver.
    """

    code = "fefo_override_required"
    status_code = 409
    message = "An earlier-expiring batch is in stock. Give a reason to override."


def quantise(value) -> Decimal:
    return Decimal(str(value)).quantize(QUANTUM)


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


@tenant_atomic_method
def post_movement(
    batch: Batch,
    location: StockLocation,
    movement_type: str,
    quantity,
    actor=None,
    reason: str = "",
    reference_type: str = "",
    reference_id: str = "",
    patient=None,
    unit_cost=None,
    fefo_overridden: bool = False,
    fefo_override_reason: str = "",
    approved_by=None,
    allow_negative: bool = False,
) -> StockEntry:
    """Append one movement to the ledger and refresh the cached balance.

    The cache row is locked with `select_for_update` for the duration, so two
    counters dispensing the same batch at the same moment cannot both read the
    same balance and both succeed. The lock is on the cache rather than the
    ledger because the cache is the row being contended.

    `allow_negative` exists for opening balances and reconciliation, where the
    ledger is being made to match reality rather than the other way round. It
    defaults to False because a negative balance in normal operation means
    something was dispensed that was not there.
    """
    quantity = quantise(quantity)
    if quantity <= ZERO:
        raise PharmacyError("A stock movement must have a positive quantity.")

    stock, _ = BatchStock.objects.select_for_update().get_or_create(
        batch=batch,
        location=location,
        defaults={"product": batch.product, "quantity": ZERO},
    )

    is_inbound = movement_type in INBOUND_MOVEMENTS
    delta = quantity if is_inbound else -quantity
    new_balance = stock.quantity + delta

    if new_balance < ZERO and not allow_negative:
        raise InsufficientStock(
            f"{batch.product.display_name} batch {batch.batch_number} has "
            f"{stock.quantity} at {location.code}; {quantity} was requested.",
            detail={
                "product": batch.product.code,
                "batch": batch.batch_number,
                "available": str(stock.quantity),
                "requested": str(quantity),
                "location": location.code,
            },
        )

    cost = Decimal(str(unit_cost)) if unit_cost is not None else batch.purchase_price
    entry = StockEntry.objects.create(
        batch=batch,
        location=location,
        product=batch.product,
        movement_type=movement_type,
        quantity=quantity,
        balance_after=new_balance,
        unit_cost=cost,
        total_cost=(cost * quantity).quantize(Decimal("0.01")),
        performed_by_id=getattr(actor, "uuid", None),
        performed_by_name=getattr(actor, "full_name", ""),
        reference_type=reference_type,
        reference_id=str(reference_id) if reference_id else "",
        patient=patient,
        reason=reason,
        fefo_overridden=fefo_overridden,
        fefo_override_reason=fefo_override_reason,
        approved_by_id=getattr(approved_by, "uuid", None),
        created_by_id=getattr(actor, "uuid", None),
    )

    stock.quantity = new_balance
    stock.last_movement_at = entry.occurred_at
    stock.save(update_fields=["quantity", "last_movement_at", "updated_at"])

    # Stock adjustments are audited at NOTABLE severity by default; the ones
    # that move stock out for a reason other than a sale deserve attention.
    if movement_type in {
        MovementType.ADJUSTMENT_UP,
        MovementType.ADJUSTMENT_DOWN,
        MovementType.THEFT,
        MovementType.DAMAGE,
        MovementType.DISPOSAL,
    }:
        record(
            AuditAction.STOCK_ADJUST,
            entity_type="pharmacy.StockEntry",
            entity_id=entry.uuid,
            entity_label=f"{movement_type} {quantity} {batch.product.code}",
            reason=reason,
            metadata={
                "batch": batch.batch_number,
                "location": location.code,
                "balance_after": str(new_balance),
            },
        )
    return entry


def stock_on_hand(product: Product, location: StockLocation = None) -> Decimal:
    """Total dispensable stock of a product, from the cache."""
    queryset = BatchStock.objects.filter(
        product=product, batch__status__in=list(DISPENSABLE_STATUSES)
    ).exclude(batch__expires_on__lt=timezone.localdate())
    if location:
        queryset = queryset.filter(location=location)
    total = queryset.aggregate(total=models.Sum("quantity"))["total"]
    return quantise(total or ZERO)


def rebuild_stock_cache(batch: Batch = None, location: StockLocation = None) -> dict:
    """Recompute cached balances from the ledger.

    The cache is derived, and this is what makes that claim true rather than
    aspirational. Run it after any incident, and on a schedule: a discrepancy
    that nobody looks for is a discrepancy nobody finds.
    """
    entries = StockEntry.objects.all()
    if batch:
        entries = entries.filter(batch=batch)
    if location:
        entries = entries.filter(location=location)

    totals: dict[tuple, Decimal] = {}
    for entry in entries.iterator():
        key = (entry.batch_id, entry.location_id)
        totals[key] = totals.get(key, ZERO) + entry.signed_quantity

    corrected = []
    for (batch_id, location_id), total in totals.items():
        stock = BatchStock.objects.filter(
            batch_id=batch_id, location_id=location_id
        ).first()
        if stock is None:
            continue
        if stock.quantity != total:
            corrected.append(
                {
                    "batch": batch_id,
                    "location": location_id,
                    "cached": str(stock.quantity),
                    "ledger": str(total),
                }
            )
            stock.quantity = total
            stock.save(update_fields=["quantity", "updated_at"])

    if corrected:
        logger.warning(
            "Stock cache disagreed with the ledger in %d place(s): %s",
            len(corrected), corrected,
        )
    return {"checked": len(totals), "corrected": corrected}


# ---------------------------------------------------------------------------
# FEFO
# ---------------------------------------------------------------------------


def fefo_batches(product: Product, location: StockLocation) -> list:
    """Dispensable stock of a product, earliest expiry first.

    First Expiry First Out, not First In First Out: what matters is which box
    goes out of date soonest, and that is not always the one that arrived
    first. Expired, quarantined and recalled batches are excluded outright —
    they are physically present but must not leave the shelf.
    """
    today = timezone.localdate()
    return list(
        BatchStock.objects.filter(
            product=product,
            location=location,
            batch__status__in=list(DISPENSABLE_STATUSES),
            batch__expires_on__gte=today,
            quantity__gt=ZERO,
        )
        .select_related("batch")
        .order_by("batch__expires_on", "batch__received_on", "id")
    )


def allocate_fefo(
    product: Product,
    location: StockLocation,
    quantity,
    preferred_batch: Batch = None,
) -> dict:
    """Choose which batches to take a quantity from.

    Returns the allocation and whether it broke FEFO. Deliberately does not
    raise on a short allocation — a pharmacist needs to know they can supply
    12 of 30 so they can dispense part and order the rest, and an exception
    would just hide that.
    """
    quantity = quantise(quantity)
    candidates = fefo_batches(product, location)

    if preferred_batch is not None:
        chosen = [row for row in candidates if row.batch_id == preferred_batch.pk]
        if not chosen:
            raise InsufficientStock(
                f"Batch {preferred_batch.batch_number} has no dispensable "
                f"stock at {location.code}.",
                detail={"batch": preferred_batch.batch_number},
            )
        # FEFO is broken only if something expiring *sooner* has stock.
        earliest = candidates[0]
        breaks_fefo = earliest.batch.expires_on < preferred_batch.expires_on
        allocation = [
            {
                "batch": chosen[0].batch,
                "quantity": min(quantity, chosen[0].available),
                "location": location,
            }
        ]
        return {
            "allocation": allocation,
            "allocated": sum(row["quantity"] for row in allocation),
            "shortfall": max(quantity - chosen[0].available, ZERO),
            "breaks_fefo": breaks_fefo,
            "earliest_batch": earliest.batch if breaks_fefo else None,
        }

    allocation = []
    remaining = quantity
    for row in candidates:
        if remaining <= ZERO:
            break
        take = min(remaining, row.available)
        if take <= ZERO:
            continue
        allocation.append(
            {"batch": row.batch, "quantity": take, "location": location}
        )
        remaining -= take

    return {
        "allocation": allocation,
        "allocated": quantity - remaining,
        "shortfall": remaining,
        "breaks_fefo": False,
        "earliest_batch": None,
    }


# ---------------------------------------------------------------------------
# Dispensing
# ---------------------------------------------------------------------------


def generate_dispense_reference() -> str:
    year = timezone.now().year
    stem = f"DSP-{year}-"
    last = (
        Dispense.all_objects.filter(reference__startswith=stem)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{stem}{sequence:06d}"


@tenant_atomic_method
def dispense(
    organization,
    patient,
    facility,
    location: StockLocation,
    items: list,
    actor=None,
    prescription_uuid=None,
    prescription_reference: str = "",
    encounter_uuid=None,
    counselling_notes: str = "",
    approved_by=None,
) -> Dispense:
    """Hand medicines to a patient, taking stock FEFO.

    Each item is `{product, quantity, [batch], [override_reason],
    [prescription_line_uuid]}`. A single item can produce several lines when
    the quantity spans batches, which FEFO makes routine — the oldest batch is
    often not big enough on its own.

    The whole dispensing is one transaction: a partial hand-over that took
    stock from two batches and failed on the third would leave the shelf and
    the ledger disagreeing.
    """
    require_module(organization, ModuleCode.PHARMACY)

    if not items:
        raise PharmacyError("A dispensing must include at least one medicine.")
    if not location.is_dispensable:
        raise PharmacyError(
            f"{location.name} is not a dispensing location.",
            detail={"location": location.code},
        )

    record_ = Dispense.objects.create(
        reference=generate_dispense_reference(),
        patient=patient,
        facility=facility,
        location=location,
        prescription_uuid=prescription_uuid,
        prescription_reference=prescription_reference,
        encounter_uuid=encounter_uuid,
        status=DispenseStatus.DRAFT,
        dispensed_by_id=getattr(actor, "uuid", None),
        dispensed_by_name=getattr(actor, "full_name", ""),
        counselling_notes=counselling_notes,
        created_by_id=getattr(actor, "uuid", None),
    )

    total = Decimal("0.00")
    order = 0

    for item in items:
        product = item["product"]
        quantity = quantise(item["quantity"])
        preferred = item.get("batch")
        override_reason = (item.get("override_reason") or "").strip()

        result = allocate_fefo(product, location, quantity, preferred_batch=preferred)

        if result["shortfall"] > ZERO:
            raise InsufficientStock(
                f"{product.display_name}: {result['allocated']} available of "
                f"{quantity} requested at {location.code}.",
                detail={
                    "product": product.code,
                    "requested": str(quantity),
                    "available": str(result["allocated"]),
                },
            )

        if result["breaks_fefo"] and not override_reason:
            earliest = result["earliest_batch"]
            raise FefoOverrideRequired(
                f"{product.display_name}: batch {earliest.batch_number} expires "
                f"{earliest.expires_on} and is in stock. Give a reason to "
                f"dispense a later batch instead.",
                detail={
                    "product": product.code,
                    "earliest_batch": earliest.batch_number,
                    "earliest_expiry": earliest.expires_on.isoformat(),
                    "chosen_batch": preferred.batch_number if preferred else None,
                },
            )

        for part in result["allocation"]:
            batch = part["batch"]
            line_quantity = part["quantity"]

            post_movement(
                batch=batch,
                location=location,
                movement_type=MovementType.DISPENSE,
                quantity=line_quantity,
                actor=actor,
                reference_type="pharmacy.Dispense",
                reference_id=str(record_.uuid),
                patient=patient,
                reason=f"Dispensed on {record_.reference}",
                fefo_overridden=result["breaks_fefo"],
                fefo_override_reason=override_reason,
                approved_by=approved_by,
            )

            line_total = (batch.selling_price * line_quantity).quantize(
                Decimal("0.01")
            )
            DispenseLine.objects.create(
                dispense=record_,
                product=product,
                batch=batch,
                product_name=product.display_name,
                batch_number=batch.batch_number,
                expires_on=batch.expires_on,
                quantity=line_quantity,
                unit_price=batch.selling_price,
                total=line_total,
                prescription_line_uuid=item.get("prescription_line_uuid"),
                is_substitution=item.get("is_substitution", False),
                substitution_reason=item.get("substitution_reason", ""),
                fefo_overridden=result["breaks_fefo"],
                fefo_override_reason=override_reason,
                instructions=item.get("instructions", ""),
                display_order=order,
                created_by_id=getattr(actor, "uuid", None),
            )
            total += line_total
            order += 1

        if result["breaks_fefo"]:
            logger.warning(
                "FEFO OVERRIDDEN %s: chose %s over %s expiring %s — %s",
                record_.reference,
                preferred.batch_number if preferred else "?",
                result["earliest_batch"].batch_number,
                result["earliest_batch"].expires_on,
                override_reason,
            )

    record_.status = DispenseStatus.DISPENSED
    record_.dispensed_at = timezone.now()
    record_.total_value = total
    record_.save(
        update_fields=["status", "dispensed_at", "total_value", "updated_at"]
    )

    record(
        AuditAction.CREATE,
        entity_type="pharmacy.Dispense",
        entity_id=record_.uuid,
        entity_label=f"{record_.reference} — {patient.mrn}",
        metadata={
            "lines": record_.lines.count(),
            "value": str(total),
            "prescription": prescription_reference,
        },
    )
    return record_


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def expiring_stock(location: StockLocation = None, within_days: int = 180) -> list:
    """Batches with stock that expire within a window, most urgent first.

    Reported per bucket so a pharmacist can act at the right moment: a batch
    180 days out can be transferred to a busier branch, one at 30 days can be
    discounted, and one at 7 days is probably a write-off.
    """
    today = timezone.localdate()
    cutoff = today + timezone.timedelta(days=within_days)

    queryset = BatchStock.objects.filter(
        quantity__gt=ZERO,
        batch__expires_on__lte=cutoff,
        batch__status__in=[BatchStatus.ACTIVE, BatchStatus.QUARANTINE],
    ).select_related("batch", "product", "location")
    if location:
        queryset = queryset.filter(location=location)

    rows = []
    for stock in queryset.order_by("batch__expires_on"):
        days = stock.batch.days_to_expiry
        rows.append(
            {
                "product_code": stock.product.code,
                "product_name": stock.product.display_name,
                "batch_number": stock.batch.batch_number,
                "expires_on": stock.batch.expires_on,
                "days_to_expiry": days,
                "bucket": expiry_bucket(days),
                "quantity": stock.quantity,
                "location": stock.location.code,
                "value_at_cost": (
                    stock.batch.purchase_price * stock.quantity
                ).quantize(Decimal("0.01")),
            }
        )
    return rows


@tenant_atomic_method
def sweep_expired(location: StockLocation = None, actor=None) -> dict:
    """Write off stock that has passed its expiry date.

    Two steps, both necessary. Marking the batch expired stops it being
    dispensed; writing the stock out of the ledger stops it being counted as
    an asset. Doing only the first leaves expired stock inflating the
    valuation; doing only the second leaves a batch that looks dispensable.
    """
    today = timezone.localdate()
    expired_batches = Batch.objects.filter(
        expires_on__lt=today, status=BatchStatus.ACTIVE
    )

    written_off = []
    total_value = Decimal("0.00")

    for batch in expired_batches:
        batch.status = BatchStatus.EXPIRED
        batch.save(update_fields=["status", "updated_at"])

        levels = BatchStock.objects.filter(batch=batch, quantity__gt=ZERO)
        if location:
            levels = levels.filter(location=location)

        for stock in levels:
            value = (batch.purchase_price * stock.quantity).quantize(Decimal("0.01"))
            post_movement(
                batch=batch,
                location=stock.location,
                movement_type=MovementType.EXPIRY,
                quantity=stock.quantity,
                actor=actor,
                reason=f"Expired on {batch.expires_on}",
            )
            written_off.append(
                {
                    "product": batch.product.display_name,
                    "batch": batch.batch_number,
                    "quantity": str(stock.quantity),
                    "location": stock.location.code,
                    "value": str(value),
                }
            )
            total_value += value

    if written_off:
        logger.warning(
            "Expiry sweep wrote off %d batch-locations worth %s",
            len(written_off), total_value,
        )
    return {
        "batches_expired": expired_batches.count(),
        "written_off": written_off,
        "total_value": total_value,
    }


@tenant_atomic_method
def quarantine_batch(batch: Batch, reason: str, actor=None,
                     recall_reference: str = "") -> Batch:
    """Take a batch out of circulation without moving it.

    Used for recalls and quality holds. The stock stays where it is and stays
    on the books — it has not left the building — but `is_dispensable` turns
    false, so FEFO stops offering it.
    """
    if not reason.strip():
        raise PharmacyError("Quarantining a batch must record why.")

    batch.status = (
        BatchStatus.RECALLED if recall_reference else BatchStatus.QUARANTINE
    )
    batch.quarantine_reason = reason
    batch.recall_reference = recall_reference
    batch.save(
        update_fields=["status", "quarantine_reason", "recall_reference", "updated_at"]
    )

    record(
        AuditAction.UPDATE,
        entity_type="pharmacy.Batch",
        entity_id=batch.uuid,
        entity_label=f"{batch.product.display_name} batch {batch.batch_number}",
        reason=reason,
        metadata={"status": batch.status, "recall": recall_reference},
    )
    logger.warning(
        "BATCH %s %s: %s (recall %s)",
        batch.batch_number, batch.status, reason, recall_reference or "n/a",
    )
    return batch


def recall_exposure(batch: Batch) -> dict:
    """Who received stock from a batch, and what is left.

    The question a recall actually asks. It is answerable only because the
    ledger records the patient on every dispensing movement — a
    product-level stock system cannot answer it at all.
    """
    dispensed = StockEntry.objects.filter(
        batch=batch, movement_type=MovementType.DISPENSE
    ).select_related("patient")

    remaining = BatchStock.objects.filter(batch=batch, quantity__gt=ZERO)

    return {
        "batch_number": batch.batch_number,
        "product": batch.product.display_name,
        "expires_on": batch.expires_on,
        "status": batch.status,
        "dispensed_count": dispensed.count(),
        "dispensed_quantity": quantise(
            dispensed.aggregate(total=models.Sum("quantity"))["total"] or ZERO
        ),
        "patients": [
            {
                "mrn": entry.patient.mrn,
                "name": entry.patient.full_name,
                "phone": entry.patient.phone,
                "quantity": str(entry.quantity),
                "dispensed_at": entry.occurred_at,
            }
            for entry in dispensed
            if entry.patient_id
        ],
        "remaining": [
            {
                "location": stock.location.code,
                "quantity": str(stock.quantity),
            }
            for stock in remaining
        ],
    }


# ---------------------------------------------------------------------------
# Reorder and valuation
# ---------------------------------------------------------------------------


def reorder_suggestions(location: StockLocation = None) -> list:
    """Products at or below their reorder level.

    The reorder point accounts for lead time: ordering when stock hits the
    minimum guarantees a stock-out for however long delivery takes.
    """
    suggestions = []
    for product in Product.objects.filter(is_active=True, is_formulary=True):
        on_hand = stock_on_hand(product, location)
        if product.reorder_level <= ZERO or on_hand > product.reorder_level:
            continue

        # Consumption over the last 30 days, as a crude daily rate.
        since = timezone.now() - timezone.timedelta(days=30)
        used = StockEntry.objects.filter(
            product=product,
            movement_type__in=[MovementType.DISPENSE, MovementType.SALE,
                              MovementType.CONSUMPTION],
            occurred_at__gte=since,
        ).aggregate(total=models.Sum("quantity"))["total"] or ZERO
        daily = quantise(Decimal(used) / 30) if used else ZERO

        cover_days = int(on_hand / daily) if daily > ZERO else None
        suggested = max(
            (product.maximum_stock or product.reorder_level * 2) - on_hand, ZERO
        )

        suggestions.append(
            {
                "product_code": product.code,
                "product_name": product.display_name,
                "on_hand": on_hand,
                "reorder_level": product.reorder_level,
                "daily_consumption": daily,
                "lead_time_days": product.lead_time_days,
                "days_of_cover": cover_days,
                #: True when stock will run out before a delivery could
                #: arrive. That is the difference between "order soon" and
                #: "order today".
                "stockout_before_delivery": (
                    cover_days is not None and cover_days < product.lead_time_days
                ),
                "suggested_quantity": quantise(suggested),
            }
        )

    suggestions.sort(
        key=lambda row: (
            not row["stockout_before_delivery"],
            row["days_of_cover"] if row["days_of_cover"] is not None else 9999,
        )
    )
    return suggestions


def stock_valuation(location: StockLocation = None) -> dict:
    """What the stock on the shelves is worth.

    At cost, not at selling price: an unsold box is an asset at what it cost,
    and valuing it at retail books a profit that has not happened.
    """
    queryset = BatchStock.objects.filter(quantity__gt=ZERO).select_related(
        "batch", "product"
    )
    if location:
        queryset = queryset.filter(location=location)

    at_cost = Decimal("0.00")
    at_retail = Decimal("0.00")
    expired_value = Decimal("0.00")
    today = timezone.localdate()

    for stock in queryset:
        cost = (stock.batch.purchase_price * stock.quantity).quantize(Decimal("0.01"))
        at_cost += cost
        at_retail += (stock.batch.selling_price * stock.quantity).quantize(
            Decimal("0.01")
        )
        if stock.batch.expires_on < today:
            expired_value += cost

    return {
        "value_at_cost": at_cost,
        "value_at_retail": at_retail,
        "potential_margin": at_retail - at_cost,
        "expired_value_at_cost": expired_value,
        "batch_count": queryset.count(),
    }


# ---------------------------------------------------------------------------
# Stock counting
# ---------------------------------------------------------------------------


@tenant_atomic_method
def start_count(facility, location: StockLocation, actor=None,
                count_type: str = "cycle", is_blind: bool = True) -> StockCount:
    """Open a count, freezing the expected quantities.

    Freezing matters: a movement during counting would otherwise change the
    variance under the counter's feet and make the result unexplainable.
    """
    year = timezone.now().year
    stem = f"SC-{year}-"
    last = (
        StockCount.all_objects.filter(reference__startswith=stem)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1

    count = StockCount.objects.create(
        reference=f"{stem}{sequence:04d}",
        facility=facility,
        location=location,
        count_type=count_type,
        is_blind=is_blind,
        status=StockCountStatus.COUNTING,
        counted_by_id=getattr(actor, "uuid", None),
        created_by_id=getattr(actor, "uuid", None),
    )

    for stock in BatchStock.objects.filter(location=location).select_related(
        "batch", "product"
    ):
        StockCountLine.objects.create(
            count=count,
            batch=stock.batch,
            product=stock.product,
            expected_quantity=stock.quantity,
            created_by_id=getattr(actor, "uuid", None),
        )
    return count


@tenant_atomic_method
def approve_count(count: StockCount, actor=None, notes: str = "") -> dict:
    """Approve a count and post the adjustments.

    The approver may not be the counter. A stock adjustment is the classic
    route for concealing theft, and a count that adjusts itself is a blank
    cheque — which is why this is enforced rather than left to policy.
    """
    if count.status != StockCountStatus.REVIEW:
        raise PharmacyError(
            f"Count {count.reference} is {count.get_status_display().lower()}; "
            "only a count in review can be approved.",
            detail={"status": count.status},
        )

    assert_different_actors(
        count.counted_by_id, getattr(actor, "uuid", None), "stock count approval"
    )

    adjustments = []
    for line in count.lines.all():
        if not line.has_variance:
            continue
        if not line.variance_reason.strip():
            raise PharmacyError(
                f"{line.product.display_name}: a variance of {line.variance} "
                "needs an explanation before it can be approved.",
                detail={"product": line.product.code, "variance": str(line.variance)},
            )

        variance = line.variance
        post_movement(
            batch=line.batch,
            location=count.location,
            movement_type=(
                MovementType.ADJUSTMENT_UP if variance > ZERO
                else MovementType.ADJUSTMENT_DOWN
            ),
            quantity=abs(variance),
            actor=actor,
            reason=f"{count.reference}: {line.variance_reason}",
            reference_type="pharmacy.StockCount",
            reference_id=str(count.uuid),
            approved_by=actor,
        )
        line.is_approved = True
        line.save(update_fields=["is_approved", "updated_at"])
        adjustments.append(
            {
                "product": line.product.display_name,
                "batch": line.batch.batch_number,
                "expected": str(line.expected_quantity),
                "counted": str(line.final_quantity),
                "variance": str(variance),
                "reason": line.variance_reason,
            }
        )

    count.status = StockCountStatus.APPLIED
    count.approved_by_id = getattr(actor, "uuid", None)
    count.approved_at = timezone.now()
    count.approval_notes = notes
    count.completed_at = count.completed_at or timezone.now()
    count.save(
        update_fields=[
            "status", "approved_by_id", "approved_at", "approval_notes",
            "completed_at", "updated_at",
        ]
    )

    record(
        AuditAction.APPROVE,
        entity_type="pharmacy.StockCount",
        entity_id=count.uuid,
        entity_label=f"{count.reference} at {count.location.code}",
        reason=notes,
        metadata={"adjustments": len(adjustments)},
    )
    return {"reference": count.reference, "adjustments": adjustments}
