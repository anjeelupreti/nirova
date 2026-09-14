"""A module nobody bought is refused at the API, not only hidden in the rail.

The console stopped showing screens outside the plan, and a hidden screen is
a courtesy: the endpoints behind it stayed open to a saved URL, an
integration, or anybody with a token. These check the gate that closes them —
and, just as importantly, that it does not close anything a customer bought
something to do.
"""

import json

import pytest
from django.test import Client
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


@pytest.fixture
def owner(tenant):
    from apps.identity.models import User

    user = User.objects.get(email="owner@manakamana.test")
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )


@pytest.fixture
def without_hospital(tenant):
    """Take the hospital module away from this organization for one test.

    An override rather than a plan edit: the override layer is what a support
    agent uses, it replaces whatever the plan said, and it is rolled back with
    the test like everything else.
    """
    from apps.catalog.keys import ModuleCode
    from apps.entitlements.models import EntitlementOverride, OverrideKind

    EntitlementOverride.objects.create(
        organization=tenant,
        kind=OverrideKind.MODULE,
        key=ModuleCode.HOSPITAL,
        is_enabled=False,
        reason="Test: the customer never bought inpatients",
    )
    return tenant


def test_the_wards_are_open_to_a_customer_who_bought_them(owner):
    assert owner.get("/api/ipd/wards/").status_code == 200


def test_the_wards_are_refused_to_one_who_did_not(owner, without_hospital):
    response = owner.get("/api/ipd/wards/")
    assert response.status_code == 402, response.content[:200]
    body = json.loads(response.content)["error"]
    assert body["code"] == "not_entitled"
    assert "hospital" in body["message"] or body["detail"].get("module") == "hospital"


def test_every_endpoint_of_the_module_is_gated_not_just_the_list(owner, without_hospital):
    """The whole prefix, because a gate on the list view and not on the detail
    view is a gate on the sidebar and not on the data."""
    for path in ("/api/ipd/wards/", "/api/ipd/admissions/", "/api/ed/arrivals/",
                 "/api/icu/stays/", "/api/ot/cases/"):
        assert owner.get(path).status_code == 402, f"{path} was not gated"


def test_what_every_customer_bought_is_never_gated(owner, without_hospital):
    """The refusal must not reach the things a clinic, a pharmacy and a
    hospital all do: patients, the diary, billing, notifications, settings."""
    for path in ("/api/clinical/patients/", "/api/clinical/appointments/",
                 "/api/billing/invoices/", "/api/notifications/",
                 "/api/org/facilities/", "/api/auth/me/"):
        assert owner.get(path).status_code != 402, f"{path} is gated and should not be"


def test_the_gate_is_silent_for_the_platform_console(db):
    """Platform staff have no organization bound; there is nothing to check
    and the console must not 402 on its own dashboard."""
    from apps.identity.models import User

    staff = User.objects.filter(is_platform_staff=True, is_active=True).first()
    if staff is None:
        pytest.skip("no platform staff account")
    client = Client(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(staff).access_token}")
    assert client.get("/api/platform/dashboard/").status_code == 200


def test_every_gated_prefix_names_a_module_the_catalogue_sells():
    from apps.catalog.keys import ModuleCode
    from apps.entitlements.gate import GATED_PREFIXES

    for prefix, module in GATED_PREFIXES:
        assert prefix.startswith("/api/"), f"{prefix} is not an API prefix"
        assert module in ModuleCode.ALL, f"{prefix} gates on an unknown module {module}"
