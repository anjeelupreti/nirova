"""The sales report agrees with the till, and shows only what you may see.

Two defects it guards against. A period report computed by different rules
from the counter's own daily summary would give two numbers for one day, and
nobody would trust either — so a one-day report must equal the summary to the
paisa. And a report of costs and margins must not reach a doctor (who reads
reports for lab turnaround) or another branch's manager.

The trace endpoint is checked here too: the batch trace names people only for
somebody who may read patients.
"""

import json
from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


@pytest.fixture
def day(tenant):
    """A sale and a partial return at the pharmacy today. Rolled back."""
    from apps.identity.models import User
    from apps.organization.models import Facility
    from apps.pharmacy.models import Batch, MovementType, Product, StockLocation
    from apps.pharmacy.services import post_movement
    from apps.pos.services import approve_return, create_sale, open_session, request_return

    facility = Facility.objects.filter(facility_type="pharmacy").first()
    location = StockLocation.objects.filter(facility=facility, is_dispensable=True).first()
    if location is None:
        pytest.skip("no dispensary; run seed_pharmacy_demo")
    cashier = User.objects.get(email="counter@manakamana.test")
    manager = User.objects.get(email="owner@manakamana.test")

    product = Product.objects.create(
        code="SALES-T1", generic_name="Report test syrup", brand_name="Reposyr",
        strength="5 ml", dosage_form="syrup", base_unit="bottle", pack_size=1,
        requires_prescription=False,
    )
    batch = Batch.objects.create(
        product=product, batch_number="SRP-0001", expires_on=date(2030, 1, 1),
        purchase_price=Decimal("40.00"), selling_price=Decimal("75.00"), mrp=Decimal("80.00"),
        supplier_name="Nepal Pharma Distributors", receipt_reference="GRN-SRP-1",
    )
    post_movement(batch=batch, location=location, movement_type=MovementType.PURCHASE,
                  quantity=Decimal("50"), actor=manager, reason="Receipt",
                  reference_type="goods_receipt", reference_id="GRN-SRP-1")

    session = open_session(organization=tenant, facility=facility, location=location,
                           counter="REPORT-TEST", cashier=cashier)
    sale = create_sale(organization=tenant, session=session,
                       items=[{"product": product, "quantity": Decimal("4"), "batch": batch}],
                       actor=cashier, payments=[{"method": "cash"}])
    back = request_return(sale=sale, entries=[{"sale_line": sale.lines.first(), "quantity": Decimal("1")}],
                          reason="Wrong strength", actor=cashier, restock=True)
    approve_return(organization=tenant, sale_return=back, actor=manager, refund_method="cash")
    return {"facility": facility, "batch": batch, "tenant": tenant}


def _client(user, tenant):
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )


def test_one_day_agrees_with_the_tills_summary(day):
    from apps.pos.reports import sales_report
    from apps.pos.services import sales_summary

    today = timezone.localdate()
    report = sales_report(today, today, facility=day["facility"])["totals"]
    summary = sales_summary(day["facility"], on_date=today)

    assert report["sales"] == summary["sales_count"]
    assert report["gross_revenue"] == summary["gross_revenue"]
    assert report["refunds"] == summary["returns_total"]
    assert report["net_revenue"] == summary["net_revenue"]
    assert report["tax"] == summary["tax"]
    assert report["cost_of_goods"] == summary["net_cost_of_goods"]
    assert report["gross_margin"] == summary["gross_margin"]


def test_the_breakdowns_add_up_to_the_totals(day):
    from apps.pos.reports import sales_report

    today = timezone.localdate()
    report = sales_report(today, today, facility=day["facility"])
    totals = report["totals"]

    assert sum(row["sales"] for row in report["by_day"]) == totals["sales"]
    assert sum((row["net"] for row in report["by_day"]), Decimal("0")) == totals["net_revenue"]
    assert sum(row["sales"] for row in report["by_hour"]) == totals["sales"]
    assert sum(row["sales"] for row in report["by_cashier"]) == totals["sales"]
    syrup = next(row for row in report["by_product"] if row["product"].startswith("Reposyr")
                 or "Report test syrup" in row["product"])
    assert Decimal(syrup["quantity"]) == Decimal("4")


def test_a_period_longer_than_a_year_is_refused(tenant):
    from apps.pos.reports import sales_report

    with pytest.raises(ValueError):
        sales_report(date(2024, 1, 1), date(2025, 6, 1))


def test_a_doctor_is_not_shown_the_counters_margins(day):
    from apps.identity.models import User

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    if doctor is None:
        pytest.skip("no demo doctor; run seed_demo_population")
    response = _client(doctor, day["tenant"]).get("/api/pos/report/")
    assert response.status_code == 403


def test_a_branch_manager_sees_their_branch_and_not_another(day):
    from apps.identity.models import User
    from apps.organization.models import Facility

    manager = User.objects.get(email="pharmacy@manakamana.test")
    client = _client(manager, day["tenant"])

    own = client.get(f"/api/pos/report/?facility={day['facility'].uuid}")
    assert own.status_code == 200, own.content

    elsewhere = Facility.objects.exclude(id=day["facility"].id).first()
    if elsewhere is not None:
        refused = client.get(f"/api/pos/report/?facility={elsewhere.uuid}")
        assert refused.status_code == 403

    # "All facilities" is all of *theirs*: the same figures as their own.
    everything = json.loads(client.get("/api/pos/report/").content)
    assert everything["totals"] == json.loads(own.content)["totals"]


def test_the_trace_withholds_names_from_the_store(day):
    from apps.identity.models import User

    store = User.objects.get(email="store@manakamana.test")
    pharmacist = User.objects.get(email="pharmacy@manakamana.test")
    path = f"/api/pharmacy/batches/{day['batch'].uuid}/trace/"

    hidden = _client(store, day["tenant"]).get(path)
    assert hidden.status_code == 200, hidden.content
    body = json.loads(hidden.content)
    assert body["identities"] == "restricted"
    assert all(not row["name"] and not row["phone"] for row in body["recipients"])

    shown = json.loads(_client(pharmacist, day["tenant"]).get(path).content)
    assert shown["identities"] == "shown"
