"""What the hospital owes, and the two people it takes to agree it owes it.

Six endpoints with no screen: claiming an expense, approving one, recording a
supplier invoice, approving that. Found by `manage.py audit_reach`.

**Building the screen found something worse than a missing screen.** Not one of
the sixteen seeded roles held `finance.post`, so the only account that could
post a journal entry or approve an expense was the organization owner. And
`ExpenseViewSet` asked for `finance.post` on *every* unsafe verb, so the owner
was also the only account that could raise a claim -- while `approve` refuses
the person who claimed it. **Nobody could complete the expense flow at all**,
and the feature had no screen, so nobody had ever tried.

The fix was two parts, and neither was widening an existing role. Claiming is
not posting, so `create` asks only for `report.read`. And a `financial_controller`
role now holds `finance.post`, deliberately without `invoice.create` --
`apps/finance/api.py` says the people who raise invoices and the people who keep
the ledger are not the same people, and widening `accountant` would have merged
exactly those two.
"""

import json
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"
#: `financial_controller`: posts to the ledger, approves expenses. The role that
#: did not exist.
CONTROLLER = f"controller@{DEMO}.test"
OWNER = f"owner@{DEMO}.test"
#: `store_keeper`: raises purchases. Holds `purchase.create` and not
#: `purchase.approve` -- the maker of the purchasing pair.
KEEPER = f"store@{DEMO}.test"
#: `pharmacy_manager`: holds `purchase.approve`. The checker.
APPROVER = f"pharmacy@{DEMO}.test"
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
def controller(tenant):
    client = _client(CONTROLLER, tenant)
    if client is None:
        pytest.skip(f"no {CONTROLLER}; run manage.py seed_demo")
    return client


@pytest.fixture
def facility(tenant):
    from apps.organization.models import Facility

    row = Facility.objects.filter(status="active").first()
    if row is None:
        pytest.skip("no active facility")
    return row


@pytest.fixture
def account(tenant):
    """A postable expense account to charge things to."""
    from apps.finance.models import Account

    row = (
        Account.objects.filter(is_postable=True, account_type="expense").first()
        or Account.objects.filter(is_postable=True).first()
    )
    if row is None:
        pytest.skip("no postable account; run manage.py seed_finance_demo")
    return row


@pytest.fixture
def cleanup(tenant):
    """Remove what each test created.

    Expenses and supplier invoices that were *approved* also wrote journal
    entries, and those are deliberately left: a posted entry is reversed, never
    deleted, and a test that deleted one would be teaching the suite a habit the
    application refuses to have. The tenant's trial balance still agrees --
    every posting here is balanced by construction.
    """
    made = {"expenses": [], "invoices": []}
    yield made
    from apps.finance.models import Expense, SupplierInvoice

    if made["expenses"]:
        Expense.objects.filter(reference__in=made["expenses"]).delete()
    if made["invoices"]:
        SupplierInvoice.objects.filter(reference__in=made["invoices"]).delete()


def _claim(client, facility, account, cleanup, *, amount="450.00"):
    response = client.post(
        "/api/finance/expenses/",
        data=json.dumps({
            "facility": str(facility.uuid),
            "account": str(account.uuid),
            "spent_on": date.today().isoformat(),
            "description": "Taxi to collect blood products",
            "amount": amount,
            "tax_amount": "0.00",
            "payment_method": "cash",
            "receipt_number": "TEST-1",
            "has_receipt": True,
        }),
        content_type="application/json",
    )
    if response.status_code == 201:
        cleanup["expenses"].append(_body(response)["reference"])
    return response


# -- expenses ---------------------------------------------------------------


def test_somebody_can_claim_an_expense_without_being_able_to_post_it(
    tenant, facility, account, cleanup
):
    """The deadlock, from the other side.

    The `pharmacy_manager` holds `report.read` and not `finance.post`. Before
    this, their claim was refused because the viewset asked for the posting
    permission on every write -- so the only person who could raise a claim was
    the one person forbidden from approving it.
    """
    claimant = _client(APPROVER, tenant)
    if claimant is None:
        pytest.skip(f"no {APPROVER}")

    response = _claim(claimant, facility, account, cleanup)
    assert response.status_code == 201, response.content[:400]
    assert _body(response)["status"] != "approved", (
        "a claim posted itself on creation"
    )


def test_an_expense_cannot_be_approved_by_whoever_claimed_it(
    controller, facility, account, cleanup
):
    """The control, exercised by somebody for whom it is the only obstacle.

    The controller holds `finance.post`, so their approval reaches the
    same-actor check rather than stopping at the permission gate. A test run as
    anybody else would pass with the check deleted -- which is how the stock
    count test managed to prove nothing.
    """
    claimed = _claim(controller, facility, account, cleanup)
    assert claimed.status_code == 201, claimed.content[:400]
    reference = _body(claimed)["reference"]

    refused = controller.post(f"/api/finance/expenses/{reference}/approve/")
    assert refused.status_code == 400, (
        f"the claimant approved their own expense: {refused.status_code} "
        f"{refused.content[:300]}"
    )
    assert "claimed it" in _body(refused)["detail"]


def test_somebody_else_can_approve_it_and_it_reaches_the_ledger(
    controller, tenant, facility, account, cleanup
):
    """Approval and posting are one step, deliberately.

    An approved expense that is not in the books is a liability nobody knows
    about, and the gap between two actions is where that lives.
    """
    from apps.finance.models import JournalEntry

    claimed = _claim(controller, facility, account, cleanup, amount="617.00")
    assert claimed.status_code == 201
    reference = _body(claimed)["reference"]

    other = _client(OWNER, tenant)
    approved = other.post(f"/api/finance/expenses/{reference}/approve/")
    assert approved.status_code == 200, approved.content[:400]
    assert _body(approved)["status"] == "approved"
    assert _body(approved)["approved_by_name"]

    # It is in the books, and the entry is balanced. An unbalanced posting is
    # the one thing a ledger must never contain.
    entry = JournalEntry.objects.filter(source_reference=reference).first()
    assert entry is not None, "an approved expense that is not in the ledger"
    assert entry.total_debit == entry.total_credit, (
        f"unbalanced posting: {entry.total_debit} vs {entry.total_credit}"
    )


def test_the_till_cannot_see_the_payables(tenant):
    till = _client(TILL, tenant)
    if till is None:
        pytest.skip(f"no {TILL}")
    assert till.get("/api/finance/expenses/").status_code == 403
    assert till.get("/api/finance/supplier-invoices/").status_code == 403


# -- supplier invoices ------------------------------------------------------


def _invoice(client, facility, cleanup, *, total="12500.00"):
    # A supplier is *chosen*, not typed: `supplier_uuid` is required and
    # unique-with the invoice number, which is what stops the same bill being
    # entered twice under two spellings of one supplier's name.
    from apps.procurement.models import Supplier

    supplier = Supplier.objects.first()
    if supplier is None:
        pytest.skip("no suppliers in the demo tenant")

    response = client.post(
        "/api/finance/supplier-invoices/",
        data=json.dumps({
            "facility": str(facility.uuid),
            "supplier_uuid": str(supplier.uuid),
            "supplier_name": supplier.name,
            "supplier_invoice_number": f"TD-{date.today():%y%m%d}-1",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "subtotal": total,
            "tax_amount": "0.00",
            "total": total,
        }),
        content_type="application/json",
    )
    if response.status_code == 201:
        cleanup["invoices"].append(_body(response)["reference"])
    return response


def test_recording_and_approving_an_invoice_are_different_people(
    tenant, facility, cleanup
):
    """`purchase.create` records it; `purchase.approve` agrees to pay it.

    The store keeper who ordered the goods is not the person who signs off the
    bill, and the split is the whole reason a goods receipt exists.
    """
    keeper = _client(KEEPER, tenant)
    approver = _client(APPROVER, tenant)
    if keeper is None or approver is None:
        pytest.skip("the purchasing pair has no demo users")

    recorded = _invoice(keeper, facility, cleanup)
    assert recorded.status_code == 201, recorded.content[:400]
    reference = _body(recorded)["reference"]
    assert _body(recorded)["status"] == "draft"

    # The maker cannot approve: they do not hold `purchase.approve`.
    assert keeper.post(
        f"/api/finance/supplier-invoices/{reference}/approve/"
    ).status_code == 403

    approved = approver.post(
        f"/api/finance/supplier-invoices/{reference}/approve/"
    )
    assert approved.status_code == 200, approved.content[:400]
    assert _body(approved)["status"] == "approved"


def test_an_invoice_cannot_be_approved_twice(tenant, facility, cleanup):
    """The second approval would post it to the ledger a second time.

    Which is how a supplier gets paid twice, and how the payables figure stops
    agreeing with what is actually owed.
    """
    keeper = _client(KEEPER, tenant)
    approver = _client(APPROVER, tenant)
    if keeper is None or approver is None:
        pytest.skip("the purchasing pair has no demo users")

    reference = _body(_invoice(keeper, facility, cleanup))["reference"]
    first = approver.post(f"/api/finance/supplier-invoices/{reference}/approve/")
    assert first.status_code == 200

    again = approver.post(f"/api/finance/supplier-invoices/{reference}/approve/")
    assert again.status_code == 400, (
        f"an invoice was approved twice: {again.status_code}"
    )
    assert "already" in _body(again)["detail"]


# -- the role that did not exist -------------------------------------------


def test_somebody_other_than_the_owner_can_keep_the_ledger(tenant):
    """Stated as a fact, because the absence of it was the bug.

    Not one of the sixteen seeded roles held `finance.post`, so posting a
    journal entry and approving an expense were the organization owner's
    personal responsibilities. A control that can only be exercised by the
    owner is a control that gets delegated by sharing the owner's password.
    """
    from apps.rbac.models import Role

    holders = [
        role.code
        for role in Role.objects.filter(is_active=True)
        if "finance.post" in role.permissions
        and not role.is_superuser_role
    ]
    assert holders, (
        "no role holds finance.post, so only the organization owner can post "
        "to the ledger. Run manage.py sync_roles."
    )

    controller = Role.objects.filter(code="financial_controller").first()
    assert controller is not None
    assert "invoice.create" not in controller.permissions, (
        "the ledger keeper can now raise invoices, which merges the two jobs "
        "apps/finance/api.py separates on purpose"
    )


# -- the reference allocator ------------------------------------------------


def test_a_reference_is_not_reissued_after_a_deletion(
    controller, facility, account, cleanup
):
    """The bug this file found, pinned so it cannot come back.

    References were allocated as `objects.count() + 1`. `BaseModel` soft-deletes
    -- `objects` hides the row and the `unique=True` on the column still sees it
    -- so deleting one expense dropped the count, the next claim was allocated a
    reference that already existed, and the insert died with a `UniqueViolation`
    behind a 500. **Any tenant that had ever deleted one of these could never
    create another.**

    Nothing about that is visible in `f"EX-{count:06d}"`, which is why it
    survived: it looks like a sequence and is a headcount.
    """
    from apps.finance.models import Expense

    first = _claim(controller, facility, account, cleanup)
    assert first.status_code == 201
    reference = _body(first)["reference"]

    # Soft-delete it, the way the application does.
    Expense.objects.get(reference=reference).delete()
    cleanup["expenses"].remove(reference)

    second = _claim(controller, facility, account, cleanup)
    assert second.status_code == 201, (
        "the reference was reissued after a deletion: "
        f"{second.status_code} {second.content[:300]}"
    )
    assert _body(second)["reference"] != reference, (
        "the deleted document's reference was handed out again -- it is quoted "
        "on paper and down a telephone, and two documents cannot share it"
    )
