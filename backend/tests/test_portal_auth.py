"""The patient portal's front door.

The portal's session lives in the tenant database, so the organization is
part of every request. Found while screenshotting the patient app: a request
carrying a portal token and no organization answered 500 — the authenticator
queried a tenant table with no tenant — where it should have sent the patient
back to sign in.
"""

import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

#: Seeded by `seed_portal_demo`.
IDENTIFIER = "+977-9800000001"
PASSWORD = "correct horse battery"


def _sign_in(client, tenant):
    response = client.post(
        "/api/me/auth/",
        data=json.dumps({"action": "login", "identifier": IDENTIFIER, "password": PASSWORD}),
        content_type="application/json",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    if response.status_code != 200:
        pytest.skip("no demo portal account; run manage.py seed_portal_demo")
    return json.loads(response.content)["token"]


def test_a_portal_token_without_a_hospital_is_asked_to_sign_in_again(tenant):
    from django.test import Client

    client = Client(raise_request_exception=False)
    token = _sign_in(client, tenant)
    response = client.get("/api/me/?section=home", HTTP_AUTHORIZATION=f"Portal {token}")
    # Against the old code this reads 200 here and 500 in the running stack:
    # the test's `tenant` fixture leaves a tenant bound to the thread, so the
    # session lookup that failed in production finds one. Both are wrong —
    # no hospital was named — and the assertion is on the right answer.
    assert response.status_code == 401, (response.status_code, response.content[:200])


def test_a_signed_in_patient_reaches_home(tenant):
    from django.test import Client

    client = Client(raise_request_exception=False)
    token = _sign_in(client, tenant)
    response = client.get(
        "/api/me/?section=home",
        HTTP_AUTHORIZATION=f"Portal {token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    assert response.status_code == 200, response.content[:300]


def test_a_released_result_reaches_the_patient_with_its_value(tenant):
    """Every released result the portal shows carries a value.

    The portal read `value` and `reference_range` from a model that stores
    `numeric_value`, `text_value` and `reference_text`, through `getattr` with
    a default — so nothing failed and every value arrived blank.
    """
    from django.test import Client

    client = Client(raise_request_exception=False)
    token = _sign_in(client, tenant)
    response = client.get(
        "/api/me/?section=results",
        HTTP_AUTHORIZATION=f"Portal {token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    assert response.status_code == 200, response.content[:300]
    shown = [row for order in json.loads(response.content) if order["visible"] for row in order["results"]]
    if not shown:
        pytest.skip("no released results for the demo patient")
    blank = [row["analyte"] for row in shown if not str(row["value"]).strip()]
    assert not blank, f"released results reached the patient with no value: {blank}"
