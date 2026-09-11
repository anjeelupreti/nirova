"""Taking back what the counter sold, and who decides the money goes out.

Four endpoints with no screen, found by `manage.py audit_reach`. A pharmacy
could sell and could not take anything back -- which in practice means it
happens in cash out of the drawer and the stock ledger never hears about it.

**The refusals are the substance.** A refund is the classic route for taking
money out of a till, so: raising and approving are different permissions, the
service refuses an approval by whoever raised it, a refusal must say why, and a
line already partly returned can only give back the remainder. Each of those is
a way the control could be got around, and each is tested by trying it.
"""

import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"
#: `pharmacy_counter`: holds `sale.return` and not `sale.return_approve`. The
#: person who takes the goods back over the counter.
TILL = f"counter@{DEMO}.test"
#: `pharmacy_manager`: holds `sale.return_approve` and **not** `sale.return`.
#: The separation here is cleaner than the stock one -- the manager cannot raise
#: a return at all.
MANAGER = f"pharmacy@{DEMO}.test"
#: The organization owner, who bypasses permission checks entirely and is
#: therefore the *only* actor who can both raise a return and approve one. That
#: makes them the only actor for whom `assert_different_actors` is the thing
#: standing in the way -- see `test_the_owner_cannot_approve_a_return_they_raised`.
OWNER = f"owner@{DEMO}.test"
#: Holds neither. The diary of refunds is not a doctor's business.
DOCTOR = f"doctor@{DEMO}.test"


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
def till(tenant):
    client = _client(TILL, tenant)
    if client is None:
        pytest.skip(f"no {TILL}; run manage.py seed_demo")
    return client


@pytest.fixture
def sale(tenant):
    """A completed sale with something still returnable on it."""
    from apps.pos.models import Sale

    for candidate in Sale.objects.prefetch_related("lines").order_by("-sold_at"):
        if not candidate.is_returnable:
            continue
        if any(line.returnable_quantity > 0 for line in candidate.lines.all()):
            return candidate
    pytest.skip("no returnable sale; run manage.py seed_pos_demo")


@pytest.fixture
def cleanup(tenant):
    """Undo the returns a test raised.

    Deleted rather than left, because a pending return sits in the counter's
    queue forever and an approved one has moved stock. The approved case is
    handled by only approving in the one test that needs it, and cleaning that
    return up puts the stock ledger back where it was.
    """
    made = []
    yield made
    from apps.pos.models import SaleReturn

    if made:
        SaleReturn.objects.filter(reference__in=made).delete()


def _raise(client, sale, cleanup, *, quantity=None, reason="Wrong strength dispensed"):
    line = next(
        row for row in sale.lines.all() if row.returnable_quantity > 0
    )
    response = client.post(
        f"/api/pos/sales/{sale.reference}/return/",
        data=json.dumps({
            "entries": [{
                "sale_line": str(line.uuid),
                "quantity": str(quantity or line.returnable_quantity),
                "condition_note": "Seal intact",
            }],
            "reason": reason,
            "restock": True,
        }),
        content_type="application/json",
    )
    if response.status_code == 201:
        cleanup.append(_body(response)["reference"])
    return response, line


# -- raising ----------------------------------------------------------------


def test_the_counter_can_take_something_back(till, sale, cleanup):
    """The person at the till raises it; nothing is refunded yet."""
    response, _ = _raise(till, sale, cleanup)
    assert response.status_code == 201, response.content[:400]

    raised = _body(response)
    assert raised["status"] == "pending", (
        "a return refunded itself on the way in"
    )
    assert raised["requested_by_name"]
    assert raised["lines"], "a return with no lines returns nothing"
    assert Decimalish(raised["refund_total"]) > 0


def Decimalish(value) -> float:
    return float(value or 0)


def test_more_cannot_come_back_than_went_out(till, sale, cleanup):
    """A line already partly returned can only give back the remainder.

    Worth testing rather than assuming, because the screen shows
    `returnable_quantity` from the server precisely so it never has to work this
    out -- and if the server did not enforce it, the screen would be the only
    thing standing between a customer and a double refund.
    """
    line = next(row for row in sale.lines.all() if row.returnable_quantity > 0)
    too_many = str(line.returnable_quantity + 1)

    response = till.post(
        f"/api/pos/sales/{sale.reference}/return/",
        data=json.dumps({
            "entries": [{"sale_line": str(line.uuid), "quantity": too_many}],
            "reason": "Trying to return more than was sold",
            "restock": True,
        }),
        content_type="application/json",
    )
    assert response.status_code == 400, (
        f"returned {too_many} of a line with {line.returnable_quantity} "
        f"available: {response.status_code}"
    )


def test_a_doctor_cannot_raise_a_refund(tenant, sale, cleanup):
    """`sale.return` is a counter permission. A refund moves money."""
    doctor = _client(DOCTOR, tenant)
    if doctor is None:
        pytest.skip(f"no {DOCTOR}")
    response, _ = _raise(doctor, sale, cleanup)
    assert response.status_code == 403


# -- deciding ---------------------------------------------------------------


def test_the_till_cannot_approve_its_own_return(till, sale, cleanup):
    """Two permissions, and the counter holds only the first."""
    response, _ = _raise(till, sale, cleanup)
    assert response.status_code == 201
    reference = _body(response)["reference"]

    refused = till.post(
        f"/api/pos/returns/{reference}/decide/",
        data=json.dumps({"approve": True, "refund_method": "cash"}),
        content_type="application/json",
    )
    assert refused.status_code == 403, (
        f"the till approved its own refund: {refused.status_code}"
    )


def test_the_owner_cannot_approve_a_return_they_raised(tenant, sale, cleanup):
    """The guard that the permissions alone do not provide.

    **Run as the owner, and that is the whole design of this test.** No role
    holds both `sale.return` and `sale.return_approve` -- the manager who
    approves cannot raise one, which is a cleaner separation than the stock
    count has. So every role-based actor is stopped by the permission gate and
    never reaches `assert_different_actors`, and a test written as any of them
    would pass with that check deleted.

    The organization owner bypasses permission checks entirely, which makes
    them the one actor in the system for whom the same-actor guard is the only
    obstacle -- and, not incidentally, the one person who could otherwise
    refund themselves out of a till unobserved.

    I wrote this as the pharmacy manager first, on the strength of a `p in
    perms` check that matched `sale.return` inside `sale.return_approve`. The
    test failed at the raise step, which is how the substring bug surfaced.
    """
    owner = _client(OWNER, tenant)
    if owner is None:
        pytest.skip(f"no {OWNER}")

    response, _ = _raise(owner, sale, cleanup)
    assert response.status_code == 201, response.content[:400]
    reference = _body(response)["reference"]

    refused = owner.post(
        f"/api/pos/returns/{reference}/decide/",
        data=json.dumps({"approve": True, "refund_method": "cash"}),
        content_type="application/json",
    )
    assert refused.status_code in (400, 403), (
        "the owner approved a refund they raised themselves: "
        f"{refused.status_code} {refused.content[:300]}"
    )


def test_a_refusal_must_say_why(till, tenant, sale, cleanup):
    """The customer is standing there and will be told something.

    It may as well be the reason that was recorded.
    """
    manager = _client(MANAGER, tenant)
    if manager is None:
        pytest.skip(f"no {MANAGER}")

    response, _ = _raise(till, sale, cleanup)
    reference = _body(response)["reference"]

    silent = manager.post(
        f"/api/pos/returns/{reference}/decide/",
        data=json.dumps({"approve": False, "decision_notes": ""}),
        content_type="application/json",
    )
    assert silent.status_code == 400

    spoken = manager.post(
        f"/api/pos/returns/{reference}/decide/",
        data=json.dumps({
            "approve": False,
            "decision_notes": "Opened pack, cold chain broken",
        }),
        content_type="application/json",
    )
    assert spoken.status_code == 200, spoken.content[:400]
    assert _body(spoken)["status"] == "rejected"
    assert _body(spoken)["decision_notes"]


def test_approving_puts_the_stock_back_and_records_the_refund(
    till, tenant, sale, cleanup
):
    """The whole point: the money and the shelf both move, together.

    A refund that does not restock leaves the ledger saying the stock was sold;
    a restock without a refund leaves the customer out of pocket. They are one
    decision and the service does both.
    """
    from apps.pharmacy.models import BatchStock

    manager = _client(MANAGER, tenant)
    if manager is None:
        pytest.skip(f"no {MANAGER}")

    response, line = _raise(till, sale, cleanup)
    assert response.status_code == 201
    reference = _body(response)["reference"]
    returning = float(_body(response)["lines"][0]["quantity"])

    before = None
    if line.batch_id and line.sale.location_id:
        stock = BatchStock.objects.filter(
            batch_id=line.batch_id, location_id=line.sale.location_id
        ).first()
        before = float(stock.quantity) if stock else None

    approved = manager.post(
        f"/api/pos/returns/{reference}/decide/",
        data=json.dumps({"approve": True, "refund_method": "cash"}),
        content_type="application/json",
    )
    assert approved.status_code == 200, approved.content[:400]

    decided = _body(approved)
    assert decided["status"] in {"approved", "completed"}
    assert decided["approved_by_name"]
    assert float(decided["refund_total"]) > 0

    if before is not None:
        stock = BatchStock.objects.filter(
            batch_id=line.batch_id, location_id=line.sale.location_id
        ).first()
        assert float(stock.quantity) == pytest.approx(before + returning), (
            "the refund was recorded and the stock never came back on the shelf"
        )


def test_a_doctor_cannot_read_the_refund_queue(tenant):
    doctor = _client(DOCTOR, tenant)
    if doctor is None:
        pytest.skip(f"no {DOCTOR}")
    assert doctor.get("/api/pos/returns/").status_code == 403


# -- the credit note reverses what was paid ---------------------------------


def _credit_arithmetic(line: dict):
    """What `_recalculate` will make of a credit line: qty x price - discount + tax."""
    return line["quantity"] * line["unit_price"] - line["discount_amount"] + line["tax_amount"]


def _returned(*, quantity, unit_price, discount_amount, tax_amount, total, back, vat="0"):
    from decimal import ROUND_HALF_UP, Decimal
    from types import SimpleNamespace

    line = SimpleNamespace(
        quantity=Decimal(quantity), unit_price=Decimal(unit_price),
        discount_amount=Decimal(discount_amount), tax_amount=Decimal(tax_amount),
        tax_percent=Decimal(vat), total=Decimal(total),
        product=SimpleNamespace(code="X"), product_name="X", batch_number="B",
    )
    back = Decimal(back)
    refund = (line.total * back / line.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return SimpleNamespace(sale_line=line, quantity=back, refund_amount=refund)


def test_a_credit_note_line_gives_back_the_vat_that_was_charged():
    """Three plasters back from a 13% VAT sale: credit 10.17, not the 9.00 shelf price.

    The line used to carry zero tax, so the note was credited without its VAT
    and the refund — correctly computed at 10.17 — was refused as more than
    the note owed. Found by the first VAT-rated product the demo ever sold.
    """
    from decimal import Decimal

    from apps.pos.services import _credit_line

    row = _returned(quantity="10", unit_price="3.00", discount_amount="0",
                    tax_amount="3.90", total="33.90", back="3", vat="13")
    line = _credit_line(row)
    assert _credit_arithmetic(line) == Decimal("-10.17"), line
    assert line["tax_amount"] == Decimal("-1.17")


def test_a_credit_note_line_keeps_the_discount_the_customer_had():
    """A discounted line is credited at the discounted price, not the list price."""
    from decimal import Decimal

    from apps.pos.services import _credit_line

    row = _returned(quantity="10", unit_price="12.00", discount_amount="12.00",
                    tax_amount="0", total="108.00", back="3")
    line = _credit_line(row)
    assert _credit_arithmetic(line) == Decimal("-32.40"), line
    assert line["discount_amount"] == Decimal("-3.60")


def test_awkward_shares_still_land_on_the_paisa():
    """A third of a line whose tax and discount do not divide evenly."""
    from decimal import Decimal

    from apps.pos.services import _credit_line

    row = _returned(quantity="3", unit_price="7.00", discount_amount="1.00",
                    tax_amount="2.60", total="22.60", back="1", vat="13")
    line = _credit_line(row)
    assert _credit_arithmetic(line) == -row.refund_amount, line
