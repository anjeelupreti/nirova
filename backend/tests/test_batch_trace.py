"""A batch traced from its supplier to every person it reached.

The defect this was written for: the recall list counted dispensing only, so
a recalled batch sold over the counter reached people the recall could not
see. These build a small, real history through the services — receive,
dispense to a patient, sell at the counter, take part of the sale back — and
check that the trace names every recipient, nets the return, and reconciles.
"""

from datetime import date
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


@pytest.fixture
def history(tenant):
    """One batch with a known life. Rolled back with the test."""
    from apps.identity.models import User
    from apps.organization.models import Facility
    from apps.patients.models import Patient
    from apps.pharmacy.models import Batch, MovementType, Product, StockLocation
    from apps.pharmacy.services import dispense, post_movement
    from apps.pos.services import approve_return, create_sale, open_session, request_return

    facility = Facility.objects.filter(facility_type="pharmacy").first()
    location = StockLocation.objects.filter(facility=facility, is_dispensable=True).first()
    if location is None:
        pytest.skip("no dispensary; run seed_pharmacy_demo")
    cashier = User.objects.get(email="counter@manakamana.test")
    manager = User.objects.get(email="owner@manakamana.test")
    patient = Patient.objects.filter(merged_into__isnull=True).exclude(phone="").first()

    product = Product.objects.create(
        code="TRACE-T1", generic_name="Trace test tablet", brand_name="Tracetab",
        strength="1 mg", dosage_form="tablet", base_unit="tablet", pack_size=10,
        requires_prescription=False,
    )
    batch = Batch.objects.create(
        product=product, batch_number="TRC-0001",
        expires_on=date(2030, 1, 1), purchase_price=Decimal("1.00"),
        selling_price=Decimal("2.00"), mrp=Decimal("2.50"),
        supplier_name="Nepal Pharma Distributors", receipt_reference="GRN-TRC-1",
    )
    post_movement(batch=batch, location=location, movement_type=MovementType.PURCHASE,
                  quantity=Decimal("100"), actor=manager, reason="Receipt",
                  reference_type="goods_receipt", reference_id="GRN-TRC-1")

    organization = tenant
    dispense(organization, patient, facility, location,
             items=[{"product": product, "quantity": Decimal("10"), "batch": batch}],
             actor=manager)

    session = open_session(organization=organization, facility=facility, location=location,
                           counter="TRACE-TEST", cashier=cashier)
    sale = create_sale(organization=organization, session=session,
                       items=[{"product": product, "quantity": Decimal("5"), "batch": batch}],
                       actor=cashier, customer_name="Ram Bahadur", customer_phone="+977-9841000001",
                       payments=[{"method": "cash"}])
    line = sale.lines.first()
    back = request_return(sale=sale, entries=[{"sale_line": line, "quantity": Decimal("2")}],
                          reason="Bought too many", actor=cashier, restock=True)
    approve_return(organization=organization, sale_return=back, actor=manager, refund_method="cash")
    return {"batch": batch, "patient": patient, "sale": sale}


def test_the_trace_names_the_counter_customer(history):
    from apps.pharmacy.trace import batch_trace

    trace = batch_trace(history["batch"])
    kinds = {row["kind"]: row for row in trace["recipients"]}
    assert "counter sale" in kinds, "a counter sale is missing from the recipients"
    sold = kinds["counter sale"]
    assert sold["name"] == "Ram Bahadur" and sold["phone"] == "+977-9841000001"
    assert Decimal(sold["quantity"]) == Decimal("3"), "the return was not netted off the sale"

    dispensed = kinds["dispensed"]
    assert dispensed["patient_mrn"] == history["patient"].mrn
    assert Decimal(dispensed["quantity"]) == Decimal("10")


def test_the_trace_reconciles(history):
    from apps.pharmacy.trace import batch_trace

    trace = batch_trace(history["batch"])
    totals = trace["totals"]
    assert Decimal(totals["received"]) == Decimal("100")
    assert Decimal(totals["to_people"]) == Decimal("15")
    assert Decimal(totals["returned"]) == Decimal("2")
    assert Decimal(totals["held"]) == Decimal("87")
    assert trace["reconciles"] is True, trace["discrepancy"]
    assert trace["origin"][0]["reference"] == "GRN-TRC-1"


def test_recall_exposure_now_includes_counter_sales(history):
    """The regression: exposure used to list the dispensed patient only."""
    from apps.pharmacy.services import recall_exposure

    exposure = recall_exposure(history["batch"])
    names = {row["name"] for row in exposure["patients"]}
    assert "Ram Bahadur" in names, "a counter customer is invisible to the recall"
