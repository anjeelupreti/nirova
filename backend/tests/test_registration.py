"""Signing up is the one write an anonymous caller can make. It must stay one row.

`POST /api/auth/register/` records a request and nothing else — no database,
no login, no organization — and it is guarded because anything anyone can
post to, somebody will post to ten thousand times.
"""

import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

URL = "/api/auth/register/"


def _form(**overrides):
    body = {
        "organization_name": "Himal Test Hospital",
        "business_type": "hospital",
        "province": "Bagmati",
        "district": "Lalitpur",
        "facility_count": 2,
        "bed_count": 60,
        "modules": ["hospital", "pharmacy", "laboratory"],
        "contact_name": "Test Person",
        "contact_email": "registration-test@example.test",
        "contact_phone": "+977-9800000000",
        "contact_role": "Medical director",
    }
    body.update(overrides)
    return body


def _post(client, body, ip="203.0.113.7"):
    return client.post(URL, data=json.dumps(body), content_type="application/json",
                       REMOTE_ADDR=ip)


@pytest.fixture
def clean(organization):
    from apps.provisioning.models import RegistrationRequest

    RegistrationRequest.objects.filter(contact_email__endswith="@example.test").delete()
    yield
    RegistrationRequest.objects.filter(contact_email__endswith="@example.test").delete()


def test_a_request_is_recorded_and_nothing_is_provisioned(client, clean):
    from apps.provisioning.models import RegistrationRequest
    from apps.tenancy.models import Organization

    organizations = Organization.objects.count()
    response = _post(client, _form())
    assert response.status_code == 201, response.content[:300]
    reference = json.loads(response.content)["reference"]
    stored = RegistrationRequest.objects.get(reference=reference)
    assert stored.status == "new"
    assert stored.modules == ["hospital", "laboratory", "pharmacy"]
    assert Organization.objects.count() == organizations, (
        "an anonymous form created an organization"
    )


def test_nonsense_is_refused_with_reasons(client, clean):
    response = _post(client, _form(business_type="casino", pan_number="12ab",
                                   modules=["hospital", "spaceflight"], province="Atlantis"))
    assert response.status_code == 400
    text = response.content.decode()
    for field in ("business_type", "pan_number", "modules", "province"):
        assert field in text, f"{field} was not refused"


def test_a_bot_that_fills_the_honeypot_is_told_yes_and_stores_nothing(client, clean):
    from apps.provisioning.models import RegistrationRequest

    before = RegistrationRequest.objects.count()
    response = _post(client, _form(website="http://spam.example"))
    assert response.status_code == 201, "a bot should not learn it was caught"
    assert RegistrationRequest.objects.count() == before


def test_one_address_cannot_flood_the_queue(client, clean):
    statuses = [
        _post(client, _form(contact_email=f"flood{n}@example.test"), ip="198.51.100.9").status_code
        for n in range(7)
    ]
    assert statuses[:5] == [201] * 5
    assert statuses[5] == 429 and statuses[6] == 429


def test_the_queue_is_for_platform_staff_only(client, clean, tenant):
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    owner = User.objects.filter(email=f"owner@{tenant.slug}.test").first()
    if owner is None:
        pytest.skip("no demo owner; run manage.py seed_demo")
    token = RefreshToken.for_user(owner).access_token
    response = client.get("/api/platform/registrations/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 403, (
        "a customer's owner could read other prospects' contact details"
    )
    assert client.get("/api/platform/registrations/").status_code in (401, 403)
