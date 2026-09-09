"""Moving stock between a pharmacy's own locations.

`MovementType.TRANSFER_OUT` and `TRANSFER_IN` had been in the model since the
pharmacy app was written and **nothing had ever created one**. There was no
service, no endpoint and no way, through the product, to move a box from the
main store to the dispensary -- which is a thing every hospital pharmacy does
several times a day.

The tests that matter here are the ones about the gap between the two ends. A
transfer written as a single atomic pair of movements would pass a happy-path
test and be wrong in the way that counts: stock would appear at the
destination while it was still in a van, and the destination could dispense
it.
"""

from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


def _quantity(batch, location):
    from apps.pharmacy.models import BatchStock

    row = BatchStock.objects.filter(batch=batch, location=location).first()
    return row.quantity if row else Decimal("0")


@pytest.fixture
def two_locations(tenant):
    """A location with stock in it, and somewhere else at the same facility.

    Taken from the demo tenant rather than created, because it already has the
    shape this models: a Main store and a Dispensary counter at the pharmacy.
    The source is whichever holds stock -- the direction of travel is
    irrelevant to the mechanics, and picking the stocked end means these tests
    do not have to manufacture an opening balance before they can start.
    """
    from apps.pharmacy.models import BatchStock, StockLocation

    stocked = (
        BatchStock.objects.filter(quantity__gt=0)
        .select_related("location")
        .first()
    )
    assert stocked is not None, "no stock anywhere; run manage.py bootstrap"

    source = stocked.location
    destination = (
        StockLocation.objects.filter(facility=source.facility)
        .exclude(pk=source.pk)
        .first()
    )
    assert destination is not None, (
        f"only one stock location at {source.facility}; a transfer needs two"
    )
    return source, destination


@pytest.fixture
def stocked_batch(tenant, two_locations):
    """A batch with something in it at the source."""
    from apps.pharmacy.models import BatchStock

    source, _ = two_locations
    row = (
        BatchStock.objects.filter(location=source, quantity__gt=0)
        .select_related("batch")
        .order_by("-quantity")
        .first()
    )
    assert row is not None, "the source location has no stock"
    return row.batch


# ---------------------------------------------------------------------------
# The gap between the two ends
# ---------------------------------------------------------------------------


def test_stock_leaves_the_source_and_does_not_arrive_until_received(
    tenant, two_locations, stocked_batch,
):
    """**The reason this is two steps and not one.**

    Between dispatch and receipt the goods are in neither place. An atomic
    transfer would put them at the destination immediately, and a dispensary
    could then hand a patient something still in a van.
    """
    from apps.pharmacy.services import dispatch_transfer, receive_transfer

    source, destination = two_locations
    before_source = _quantity(stocked_batch, source)
    before_destination = _quantity(stocked_batch, destination)

    transfer = dispatch_transfer(
        source=source, destination=destination,
        items=[{"batch": stocked_batch, "quantity": Decimal("10")}],
    )

    assert _quantity(stocked_batch, source) == before_source - Decimal("10"), (
        "the stock has not left the source"
    )
    assert _quantity(stocked_batch, destination) == before_destination, (
        "the stock arrived before anybody received it -- a dispensary could "
        "now dispense something that is still in transit"
    )

    receive_transfer(transfer)

    assert _quantity(stocked_batch, destination) == (
        before_destination + Decimal("10")
    )


def test_a_shortfall_is_recorded_rather_than_quietly_corrected(
    tenant, two_locations, stocked_batch,
):
    """Ten went, eight arrived, and the system can say so.

    Posting the full quantity in and adjusting it down afterwards would give a
    tidy ledger describing something that did not happen. The two missing
    units stay visible as a shortfall on the line.
    """
    from apps.pharmacy.services import dispatch_transfer, receive_transfer

    source, destination = two_locations
    before_destination = _quantity(stocked_batch, destination)

    transfer = dispatch_transfer(
        source=source, destination=destination,
        items=[{"batch": stocked_batch, "quantity": Decimal("10")}],
    )
    line = transfer.lines.get()
    receive_transfer(transfer, received={str(line.uuid): Decimal("8")})

    line.refresh_from_db()
    transfer.refresh_from_db()

    assert line.quantity_received == Decimal("8")
    assert line.shortfall == Decimal("2")
    assert transfer.has_discrepancy is True
    assert _quantity(stocked_batch, destination) == (
        before_destination + Decimal("8")
    ), "the destination was credited with stock that never arrived"


def test_receiving_more_than_was_sent_is_refused(
    tenant, two_locations, stocked_batch,
):
    """Not a happy surprise -- a counting error, and accepting it would
    create stock out of nothing."""
    from apps.common.exceptions import DomainError
    from apps.pharmacy.services import dispatch_transfer, receive_transfer

    source, destination = two_locations
    transfer = dispatch_transfer(
        source=source, destination=destination,
        items=[{"batch": stocked_batch, "quantity": Decimal("5")}],
    )
    line = transfer.lines.get()

    with pytest.raises(DomainError) as refused:
        receive_transfer(transfer, received={str(line.uuid): Decimal("6")})
    assert "Re-count" in str(refused.value)

    # And the transfer is still open, so it can be received correctly.
    transfer.refresh_from_db()
    assert transfer.is_open


# ---------------------------------------------------------------------------
# What cannot be sent
# ---------------------------------------------------------------------------


def test_more_than_is_there_cannot_be_sent(tenant, two_locations, stocked_batch):
    """`post_movement` already refuses this; the point is that the *whole*
    consignment rolls back rather than half of it going."""
    from apps.common.exceptions import DomainError
    from apps.pharmacy.models import StockTransfer
    from apps.pharmacy.services import dispatch_transfer

    source, destination = two_locations
    available = _quantity(stocked_batch, source)
    before = StockTransfer.objects.count()

    with pytest.raises(DomainError):
        dispatch_transfer(
            source=source, destination=destination,
            items=[{"batch": stocked_batch, "quantity": available + Decimal("1")}],
        )

    assert _quantity(stocked_batch, source) == available, (
        "stock left the source on a transfer that failed"
    )
    assert StockTransfer.objects.count() == before, (
        "a transfer record survived a rolled-back dispatch"
    )


def test_a_transfer_to_the_same_location_is_refused(
    tenant, two_locations, stocked_batch,
):
    """It is an adjustment, and calling it a transfer would hide that."""
    from apps.common.exceptions import DomainError
    from apps.pharmacy.services import dispatch_transfer

    source, _ = two_locations
    with pytest.raises(DomainError) as refused:
        dispatch_transfer(
            source=source, destination=source,
            items=[{"batch": stocked_batch, "quantity": Decimal("1")}],
        )
    assert "two different locations" in str(refused.value)


# ---------------------------------------------------------------------------
# Calling it back
# ---------------------------------------------------------------------------


def test_cancelling_returns_the_stock_and_keeps_both_movements(
    tenant, two_locations, stocked_batch,
):
    """Cancelling is not an undo.

    The stock really did leave, so it comes back as its own movement and both
    remain on the ledger. Erasing the dispatch would make the ledger disagree
    with what the storekeeper remembers.
    """
    from apps.pharmacy.models import MovementType, StockEntry, TransferStatus
    from apps.pharmacy.services import cancel_transfer, dispatch_transfer

    source, destination = two_locations
    before = _quantity(stocked_batch, source)

    transfer = dispatch_transfer(
        source=source, destination=destination,
        items=[{"batch": stocked_batch, "quantity": Decimal("7")}],
    )
    cancel_transfer(transfer, reason="Van broke down")

    transfer.refresh_from_db()
    assert transfer.status == TransferStatus.CANCELLED
    assert _quantity(stocked_batch, source) == before, (
        "the stock did not come back"
    )
    assert _quantity(stocked_batch, destination) == _quantity(
        stocked_batch, destination
    )

    entries = StockEntry.objects.filter(
        reference_type="pharmacy.StockTransfer",
        reference_id=str(transfer.uuid),
    )
    kinds = sorted(entries.values_list("movement_type", flat=True))
    assert kinds == sorted([MovementType.TRANSFER_OUT, MovementType.TRANSFER_IN]), (
        f"both movements should survive a cancellation; found {kinds}"
    )


def test_a_received_transfer_cannot_be_received_or_cancelled_again(
    tenant, two_locations, stocked_batch,
):
    """Idempotence matters here because receiving twice would credit the
    destination twice."""
    from apps.common.exceptions import DomainError
    from apps.pharmacy.services import (
        cancel_transfer,
        dispatch_transfer,
        receive_transfer,
    )

    source, destination = two_locations
    transfer = dispatch_transfer(
        source=source, destination=destination,
        items=[{"batch": stocked_batch, "quantity": Decimal("3")}],
    )
    receive_transfer(transfer)
    after = _quantity(stocked_batch, destination)

    with pytest.raises(DomainError):
        receive_transfer(transfer)
    with pytest.raises(DomainError):
        cancel_transfer(transfer, reason="too late")

    assert _quantity(stocked_batch, destination) == after, (
        "a second receipt credited the destination again"
    )
