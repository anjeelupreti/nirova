"""Paying a bill with eSewa or Khalti.

The provider's servers are replaced at the one seam every request passes
through (`gateways._call`), with answers shaped like their documented ones.
The eSewa form signature was separately checked against eSewa's own sandbox,
which accepts it and rejects a tampered copy (development log 280).

What is tested is what would cost a hospital money or a patient trust: that
nothing is recorded as paid until the provider says so server to server; that
confirming twice records one receipt; that a wrong amount is never applied;
that money taken for a bill already settled is flagged for refund, not lost;
and that a patient can pay only their own bills.
"""

import json
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

PORTAL_IDENTIFIER = "+977-9800000001"
PORTAL_PASSWORD = "correct horse battery"


class Provider:
    """Stands in for eSewa and Khalti. Records calls; answers from a script."""

    def __init__(self):
        self.calls = []
        self.esewa_status = "COMPLETE"
        self.khalti_status = "Completed"
        self.reported = None  # amount the provider reports; None = as asked

    def __call__(self, url, *, body=None, headers=None):
        self.calls.append((url, body, headers))
        if "epayment/initiate" in url:
            return {"pidx": "PIDX-TEST-1", "payment_url": "https://test-pay.khalti.com/?pidx=PIDX-TEST-1",
                    "expires_at": "2026-09-12T12:00:00+05:45", "expires_in": 1800}
        if "epayment/lookup" in url:
            asked = self.asked_paisa
            return {"pidx": body["pidx"], "total_amount": self.reported * 100 if self.reported else asked,
                    "status": self.khalti_status, "transaction_id": "KHT-TXN-9", "fee": 0, "refunded": False}
        if "transaction/status" in url:
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(url).query)
            return {"product_code": query["product_code"][0], "transaction_uuid": query["transaction_uuid"][0],
                    "total_amount": float(self.reported or query["total_amount"][0]),
                    "status": self.esewa_status, "ref_id": "ESW-REF-7"}
        raise AssertionError(f"unexpected call to {url}")

    @property
    def asked_paisa(self):
        for url, body, _ in self.calls:
            if "initiate" in url:
                return body["amount"]
        return 0


@pytest.fixture
def provider(monkeypatch):
    from apps.billing import gateways

    stub = Provider()
    monkeypatch.setattr(gateways, "_call", stub)
    return stub


@pytest.fixture
def invoice(tenant):
    """An issued invoice with money owing, for the portal's demo patient."""
    from apps.billing.models import ServiceItem
    from apps.billing.services import capture_charge, create_invoice
    from apps.organization.models import Facility
    from apps.patients.models import Patient

    patient = Patient.objects.filter(mrn="MRN-000001").first()
    service = ServiceItem.objects.filter(is_active=True, default_price__gte=20).first()
    facility = Facility.objects.filter(facility_type__in=["clinic", "hospital"]).first()
    if not (patient and service and facility):
        pytest.skip("demo patient, price list or facility missing")
    charge = capture_charge(tenant, patient, facility, service, quantity=Decimal("2"))
    made = create_invoice(tenant, patient, facility, charges=[charge], issue=True)
    assert made.balance_due > 0
    return made


@pytest.fixture
def khalti_key(tenant):
    from apps.common.sealing import seal
    from apps.organization.config import set_config_value

    set_config_value("payments", "khalti_secret_key", seal("test_secret_key_0123456789abcdef"))


def test_esewa_is_offered_in_test_mode_with_its_public_merchant(tenant):
    from apps.billing.online import available_providers

    offered = {row["provider"]: row for row in available_providers()}
    assert "esewa" in offered and offered["esewa"]["test_mode"] is True
    assert "khalti" not in offered, "Khalti offered with no merchant key"


def test_nothing_is_paid_until_the_provider_confirms(invoice, provider):
    from apps.billing.models import OnlinePayment
    from apps.billing.online import confirm, start

    before = invoice.balance_due
    started = start(invoice, "esewa", return_to="http://localhost:5174/")
    fields = started["form"]["fields"]
    assert fields["product_code"] == "EPAYTEST"
    assert fields["signed_field_names"] == "total_amount,transaction_uuid,product_code"
    assert "attempt=" in fields["success_url"]

    invoice.refresh_from_db()
    assert invoice.balance_due == before, "starting a payment changed the balance"

    provider.esewa_status = "PENDING"
    attempt = confirm(OnlinePayment.objects.get(uuid=started["uuid"]))
    assert attempt.status == "pending" and attempt.payment is None

    provider.esewa_status = "COMPLETE"
    attempt = confirm(attempt)
    assert attempt.status == "completed" and attempt.payment is not None
    assert attempt.payment.method == "esewa" and "ESW-REF-7" in attempt.payment.reference
    invoice.refresh_from_db()
    assert invoice.balance_due == before - attempt.amount


def test_confirming_twice_records_one_receipt(invoice, provider):
    from apps.billing.models import OnlinePayment, Payment
    from apps.billing.online import confirm, start

    started = start(invoice, "esewa", return_to="http://localhost:5174/")
    attempt = OnlinePayment.objects.get(uuid=started["uuid"])
    confirm(attempt)
    confirm(attempt)
    assert Payment.objects.filter(invoice=invoice, method="esewa").count() == 1


def test_a_different_amount_is_never_applied(invoice, provider):
    from apps.billing.models import OnlinePayment
    from apps.billing.online import confirm, start

    started = start(invoice, "esewa", return_to="http://localhost:5174/")
    provider.reported = Decimal(started["amount"]) - 1
    attempt = confirm(OnlinePayment.objects.get(uuid=started["uuid"]))
    assert attempt.payment is None
    assert "not the" in attempt.needs_attention


def test_money_for_a_bill_settled_meanwhile_is_flagged_for_refund(invoice, provider):
    from apps.billing.models import OnlinePayment
    from apps.billing.online import confirm, start
    from apps.billing.services import record_payment

    started = start(invoice, "esewa", return_to="http://localhost:5174/")
    record_payment(invoice, invoice.balance_due, "cash")  # paid at the counter meanwhile
    attempt = confirm(OnlinePayment.objects.get(uuid=started["uuid"]))
    assert attempt.status == "completed" and attempt.payment is None
    assert "Refund" in attempt.needs_attention


def test_khalti_amounts_travel_in_paisa(invoice, provider, khalti_key):
    from apps.billing.models import OnlinePayment
    from apps.billing.online import confirm, start

    started = start(invoice, "khalti", return_to="http://localhost:5174/")
    assert started["redirect_url"].startswith("https://test-pay.khalti.com/")
    initiate = next(body for url, body, _ in provider.calls if "initiate" in url)
    assert initiate["amount"] == int(Decimal(started["amount"]) * 100)
    assert "customer_info" not in initiate, "patient details were sent to the wallet"
    headers = next(h for url, _, h in provider.calls if "initiate" in url)
    assert headers["Authorization"] == "Key test_secret_key_0123456789abcdef"

    attempt = confirm(OnlinePayment.objects.get(uuid=started["uuid"]))
    assert attempt.reference == "PIDX-TEST-1"
    assert attempt.payment is not None and attempt.payment.method == "khalti"


def test_a_cancelled_khalti_payment_records_nothing(invoice, provider, khalti_key):
    from apps.billing.models import OnlinePayment
    from apps.billing.online import confirm, start

    started = start(invoice, "khalti", return_to="http://localhost:5174/")
    provider.khalti_status = "User canceled"
    attempt = confirm(OnlinePayment.objects.get(uuid=started["uuid"]))
    assert attempt.status == "cancelled" and attempt.payment is None


def test_the_merchant_key_is_never_shown_back(tenant, khalti_key):
    from apps.identity.models import User
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    owner = User.objects.get(email="owner@manakamana.test")
    client = Client(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(owner).access_token}",
                    HTTP_X_ORGANIZATION=tenant.slug)
    body = json.loads(client.get("/api/org/settings/").content)
    row = next(s for s in body["settings"] if s["code"] == "payments.khalti_secret_key")
    assert "0123456789" not in json.dumps(row)
    assert row["value"].endswith("cdef") and row["value"].startswith("••••")


def test_a_patient_pays_only_their_own_bills(tenant, invoice, provider):
    from django.test import Client

    from apps.billing.models import Invoice, InvoiceStatus

    client = Client(raise_request_exception=False)
    login = client.post("/api/me/auth/", data=json.dumps(
        {"action": "login", "identifier": PORTAL_IDENTIFIER, "password": PORTAL_PASSWORD}),
        content_type="application/json", HTTP_X_ORGANIZATION=tenant.slug)
    if login.status_code != 200:
        pytest.skip("no demo portal account; run manage.py seed_portal_demo")
    headers = {"HTTP_AUTHORIZATION": f"Portal {json.loads(login.content)['token']}",
               "HTTP_X_ORGANIZATION": tenant.slug}

    def post(body):
        return client.post("/api/me/", data=json.dumps(body), content_type="application/json", **headers)

    bills = json.loads(client.get("/api/me/?section=invoices", **headers).content)
    assert any(row["provider"] == "esewa" for row in bills["pay_with"])

    mine = post({"action": "pay", "invoice": invoice.number, "provider": "esewa"})
    assert mine.status_code == 201, mine.content[:300]

    someone_else = (
        Invoice.objects.exclude(patient=invoice.patient).exclude(status=InvoiceStatus.DRAFT)
        .filter(is_credit_note=False).first()
    )
    if someone_else is not None:
        refused = post({"action": "pay", "invoice": someone_else.number, "provider": "esewa"})
        assert refused.status_code in (400, 403, 404)

    confirmed = post({"action": "confirm_payment", "attempt": json.loads(mine.content)["uuid"]})
    assert confirmed.status_code == 200, confirmed.content[:300]
    assert json.loads(confirmed.content)["status"] == "completed"


def test_an_unfinished_esewa_payment_stays_open(invoice, provider):
    """The regression: eSewa answers NOT_FOUND while the payer is still at the
    wallet, and reading that as "expired" settled the attempt seconds after it
    began — so a payer who then paid had their money stranded."""
    from apps.billing.models import OnlinePayment
    from apps.billing.online import confirm, start

    started = start(invoice, "esewa", return_to="http://localhost:5174/")
    provider.esewa_status = "NOT_FOUND"
    attempt = confirm(OnlinePayment.objects.get(uuid=started["uuid"]))
    assert attempt.status == "pending", "an unfinished payment was given up on"

    # And when they finish, it is still there to be applied.
    provider.esewa_status = "COMPLETE"
    attempt = confirm(attempt)
    assert attempt.status == "completed" and attempt.payment is not None


def test_an_attempt_nobody_finished_is_given_up(invoice, provider):
    from datetime import timedelta

    from django.utils import timezone

    from apps.billing.models import OnlinePayment
    from apps.billing.online import ABANDONED_AFTER, confirm, start

    started = start(invoice, "esewa", return_to="http://localhost:5174/")
    attempt = OnlinePayment.objects.get(uuid=started["uuid"])
    OnlinePayment.objects.filter(pk=attempt.pk).update(
        created_at=timezone.now() - ABANDONED_AFTER - timedelta(minutes=1),
    )
    provider.esewa_status = "NOT_FOUND"
    assert confirm(OnlinePayment.objects.get(pk=attempt.pk)).status == "expired"
