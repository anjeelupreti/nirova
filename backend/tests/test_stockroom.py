"""Receiving a delivery, counting the shelf, and the pair of people that takes.

Thirteen endpoints in `apps/pharmacy` had no screen: receiving, adjusting, the
ledger, valuation, reconciliation, batch quarantine and recall exposure, and
stock counts with their record-and-approve pair. **A pharmacy could dispense
from stock it had no way of putting there.** Found by `manage.py audit_reach`,
which asks the question `audit_screens` cannot: not "does what the screens call
answer", but "does anything call this at all".

The tests here are the flow end to end, and the refusals inside it. The refusals
are the point: a stock count that adjusts itself is a blank cheque, and the
control that stops it lives in the service rather than in the permission -- a
`pharmacy_manager` holds both `stock.count` and `stock.approve_adjustment`, so
nothing about the permissions alone prevents them signing off their own count.
"""

import json
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"
#: `store_keeper`: receives, adjusts and counts. The *maker* half of the pair.
#:
#: Added to the demo tenant for these tests, because there was no account that
#: could receive a delivery: `pharmacy_manager` holds `stock.count` and
#: `stock.approve_adjustment` and deliberately not `stock.adjust`, so the whole
#: stockroom was untestable from the outside. The same omission as the missing
#: receptionist, one module along.
KEEPER = f"store@{DEMO}.test"
#: `pharmacy_manager`: approves what the keeper counted. The *checker*.
APPROVER = f"pharmacy@{DEMO}.test"
OWNER = f"owner@{DEMO}.test"
#: The till. Holds neither `stock.count` nor `stock.adjust`, correctly.
TILL = f"counter@{DEMO}.test"


def _client(email, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        return None
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
        raise_request_exception=False,
    )


def _body(response):
    return json.loads(response.content.decode())


@pytest.fixture
def keeper(tenant):
    client = _client(KEEPER, tenant)
    if client is None:
        pytest.skip(f"no {KEEPER}; run manage.py seed_demo")
    return client


@pytest.fixture
def place(tenant):
    """A stock location and its facility."""
    from apps.pharmacy.models import StockLocation

    location = StockLocation.objects.select_related("facility").filter(
        is_active=True
    ).first()
    if location is None:
        pytest.skip("no stock location in the demo tenant")
    return location


@pytest.fixture
def product(tenant):
    from apps.pharmacy.models import Product

    row = Product.objects.filter(is_active=True).first()
    if row is None:
        pytest.skip("no products in the demo tenant")
    return row


@pytest.fixture
def cleanup(tenant):
    """Remove the batch and count each test created, and nothing else.

    These run against the shared development tenant. A batch left behind would
    sit in every later valuation and expiry report, and a count left open would
    be picked up by the next run as "the open count".
    """
    made = {"batches": [], "counts": []}
    yield made
    from apps.pharmacy.models import Batch, StockCount, StockEntry

    if made["counts"]:
        StockCount.objects.filter(uuid__in=made["counts"]).delete()
    if made["batches"]:
        StockEntry.objects.filter(batch__uuid__in=made["batches"]).delete()
        Batch.objects.filter(uuid__in=made["batches"]).delete()


def _receive(client, product, place, cleanup, *, quantity="40", number=None):
    number = number or f"TEST-{date.today():%y%m%d}-{id(cleanup) % 9973}"
    response = client.post(
        "/api/pharmacy/stock/receive/",
        data=json.dumps({
            "product_uuid": str(product.uuid),
            "location_uuid": str(place.uuid),
            "batch_number": number,
            "expires_on": (date.today() + timedelta(days=400)).isoformat(),
            "quantity": quantity,
            "purchase_price": "10.00",
            "selling_price": "14.00",
            "mrp": "15.00",
            "supplier_name": "Test Distributors",
            "receipt_reference": "TEST-CHALLAN-1",
        }),
        content_type="application/json",
    )
    if response.status_code == 201:
        cleanup["batches"].append(_body(response)["batch"]["uuid"])
    return response


# -- receiving --------------------------------------------------------------


def test_a_delivery_can_be_booked_in(keeper, product, place, cleanup):
    """The endpoint that creates a batch, and the only one that does.

    There is no "create batch" anywhere in this system, deliberately: a batch
    exists because something arrived, with an expiry and a price. This is the
    door.
    """
    response = _receive(keeper, product, place, cleanup)
    assert response.status_code == 201, response.content[:400]

    body = _body(response)
    assert body["batch"]["batch_number"].startswith("TEST-")
    assert body["entry"]["movement_type"] == "purchase"
    # The ledger records the *balance after*, not just the change. A ledger of
    # deltas cannot answer "what was on the shelf on the 14th" without replaying
    # itself from the beginning.
    assert body["entry"]["balance_after"]


def test_receiving_the_same_batch_twice_adds_to_it(keeper, product, place, cleanup):
    """A batch is product, number and expiry together — a second delivery of the
    same batch is more of it, not a second batch.

    Getting this wrong splits one batch in two, and a recall then finds half of
    it.
    """
    from apps.pharmacy.models import Batch

    number = f"TEST-DUP-{id(cleanup) % 9973}"
    first = _receive(keeper, product, place, cleanup, quantity="10", number=number)
    assert first.status_code == 201
    second = _receive(keeper, product, place, cleanup, quantity="15", number=number)
    assert second.status_code == 201

    assert _body(first)["batch"]["uuid"] == _body(second)["batch"]["uuid"]
    assert Batch.objects.filter(
        product=product, batch_number=number
    ).count() == 1
    assert float(_body(second)["entry"]["balance_after"]) >= 25


def test_the_till_cannot_receive_stock(tenant, product, place, cleanup):
    """A counter assistant sells; a store keeper receives.

    Not pedantry: whoever books stock in decides what the system believes is on
    the shelf, and the person taking money at the till is the last one who
    should also be able to adjust that quietly.
    """
    till = _client(TILL, tenant)
    if till is None:
        pytest.skip(f"no {TILL}")
    assert _receive(till, product, place, cleanup).status_code == 403


# -- counting ---------------------------------------------------------------


def test_a_count_freezes_what_the_system_believes(keeper, product, place, cleanup):
    """Opening a count snapshots the expected quantities.

    That snapshot is what makes a variance meaningful: without it, a count
    compared against a number that moved while somebody was counting would
    report a variance for every dispense made that afternoon.
    """
    assert _receive(keeper, product, place, cleanup).status_code == 201

    response = keeper.post(
        "/api/pharmacy/counts/",
        data=json.dumps({
            "facility_uuid": str(place.facility.uuid),
            "location_uuid": str(place.uuid),
            "count_type": "cycle",
            "is_blind": True,
        }),
        content_type="application/json",
    )
    assert response.status_code in (200, 201), response.content[:400]
    count = _body(response)
    cleanup["counts"].append(count["uuid"])

    assert count["status"] == "counting", count["status"]
    assert count["is_blind"] is True
    assert count["lines"], "a count with no lines is counting nothing"

    # **A blind count must not tell the counter what to find.** The serializer
    # nulls `expected_quantity` while the count is open, which is stronger than
    # a screen choosing not to render it: the number never reaches the browser,
    # so it cannot be read out of the network tab or a cached response either.
    # Worth a test of its own, because the whole value of a blind count is this
    # one field being absent.
    assert all(line["expected_quantity"] is None for line in count["lines"]), (
        "a blind count is sending the expected quantity to whoever is counting"
    )


def test_a_variance_is_recorded_and_needs_approval_by_somebody_else(
    keeper, tenant, product, place, cleanup
):
    """The whole point of the pair.

    Counting sends the numbers for review; it adjusts nothing. Approving is a
    separate act, and the service refuses it to whoever did the counting -- a
    count that adjusts itself is a blank cheque.

    **The counting here is done by the `pharmacy_manager`, not the store
    keeper, and that is the whole design of this test.** The store keeper does
    not hold `stock.approve_adjustment`, so their approval is refused for want
    of the permission and never reaches the segregation check at all. Written
    that way first, this test passed with `assert_different_actors` deleted --
    it proved the permission gate and nothing else. The manager holds *both*
    `stock.count` and `stock.approve_adjustment`, so they are the only actor
    for whom the segregation guard is the thing standing in the way.
    """
    counter = _client(APPROVER, tenant)
    if counter is None:
        pytest.skip(f"no {APPROVER}")

    assert _receive(keeper, product, place, cleanup, quantity="40").status_code == 201

    started = _body(counter.post(
        "/api/pharmacy/counts/",
        data=json.dumps({
            "facility_uuid": str(place.facility.uuid),
            "location_uuid": str(place.uuid),
            "count_type": "cycle",
            "is_blind": True,
        }),
        content_type="application/json",
    ))
    cleanup["counts"].append(started["uuid"])

    # Count one line deliberately short. The expected quantity is withheld from
    # the API response during a blind count -- correctly -- so the test reads it
    # from the database, which is what the person counting cannot do.
    from apps.pharmacy.models import StockCountLine

    line = started["lines"][0]
    expected = StockCountLine.objects.get(uuid=line["uuid"]).expected_quantity
    short = str(max(float(expected) - 3, 0))
    recorded = counter.post(
        f"/api/pharmacy/counts/{started['uuid']}/record/",
        data=json.dumps({
            "lines": [{
                "line_uuid": line["uuid"],
                "counted_quantity": short,
                "variance_reason": "Three blister strips missing from the box",
            }],
        }),
        content_type="application/json",
    )
    assert recorded.status_code == 200, recorded.content[:400]

    body = _body(recorded)
    assert body["status"] == "review", "recording should not adjust anything yet"
    counted = next(l for l in body["lines"] if l["uuid"] == line["uuid"])
    assert counted["has_variance"] is True
    assert float(counted["variance"]) != 0

    # The person who counted may not approve it, *even holding the permission*.
    same_person = counter.post(
        f"/api/pharmacy/counts/{started['uuid']}/approve/",
        data=json.dumps({"notes": "Signing off my own count"}),
        content_type="application/json",
    )
    assert same_person.status_code in (400, 403), (
        "the counter approved their own count: "
        f"{same_person.status_code} {same_person.content[:300]}"
    )

    # Somebody else can. The owner here, because the manager is now the person
    # who counted -- which is the situation this whole test is about.
    other = _client(OWNER, tenant)
    if other is None:
        pytest.skip(f"no {OWNER}")
    approved = other.post(
        f"/api/pharmacy/counts/{started['uuid']}/approve/",
        data=json.dumps({"notes": "Checked against the delivery note"}),
        content_type="application/json",
    )
    assert approved.status_code == 200, approved.content[:400]


def test_the_till_cannot_open_a_count(tenant, place):
    till = _client(TILL, tenant)
    if till is None:
        pytest.skip(f"no {TILL}")
    assert till.get("/api/pharmacy/counts/").status_code == 403


# -- adjusting and the ledger ----------------------------------------------


def test_an_adjustment_needs_a_reason_worth_reading(
    keeper, product, place, cleanup
):
    """The API asks for at least five characters, and that is the right idea.

    An adjustment is stock appearing or disappearing with no transaction behind
    it. "adj" as the reason explains nothing to whoever reads the ledger next
    year, which is the only reason the field exists.
    """
    received = _receive(keeper, product, place, cleanup)
    assert received.status_code == 201
    batch_uuid = _body(received)["batch"]["uuid"]

    def adjust(reason):
        return keeper.post(
            "/api/pharmacy/stock/adjust/",
            data=json.dumps({
                "batch_uuid": batch_uuid,
                "location_uuid": str(place.uuid),
                "movement_type": "damage",
                "quantity": "2",
                "reason": reason,
            }),
            content_type="application/json",
        )

    assert adjust("adj").status_code == 400
    good = adjust("Two strips crushed in transit")
    assert good.status_code in (200, 201), good.content[:400]


def test_the_ledger_shows_what_happened_and_the_running_balance(
    keeper, product, place, cleanup
):
    """The question a ledger has to answer is "and then what was left".

    A ledger of movements without a running balance forces whoever is
    reconciling to add the column up by hand, which is how they stop
    reconciling.
    """
    assert _receive(keeper, product, place, cleanup).status_code == 201

    response = keeper.get(f"/api/pharmacy/stock/ledger/?location={place.uuid}")
    assert response.status_code == 200, response.content[:300]

    body = _body(response)
    entries = body.get("entries") or body.get("results") or body
    assert entries, "the ledger is empty immediately after a receipt"
    first = entries[0]
    assert "movement_type" in first
    assert "balance_after" in first


def test_valuation_answers_with_a_number(keeper, place):
    """What is on the shelf, valued. Reported to the accountant every month."""
    response = keeper.get(f"/api/pharmacy/stock/valuation/?location={place.uuid}")
    assert response.status_code == 200, response.content[:300]
    body = _body(response)
    # Four figures, and the fourth is the one worth acting on: stock that has
    # expired is still counted in the first two and is worth nothing.
    for field in (
        "value_at_cost", "value_at_retail", "potential_margin",
        "expired_value_at_cost",
    ):
        assert field in body, f"{field} missing from {sorted(body)}"
