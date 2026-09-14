"""The organization's day: figures for whoever runs the place.

What these hold is the rule that makes the figures trustworthy: a block the
viewer may not see, or the plan does not include, is **left out** rather than
reported as zero -- "no inpatients" and "you may not see inpatients" are
different claims -- and the whole answer is refused to somebody without
analytics access.
"""

import re

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


class _Everything:
    def has(self, code, scope=None):
        return True


class _Nothing:
    def has(self, code, scope=None):
        return False


class _Plan:
    def __init__(self, *missing):
        self.missing = set(missing)

    def has_module(self, code):
        return code not in self.missing


def _client(tenant, email):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.get(email=email)
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )


def test_the_owner_sees_the_organizations_day(tenant):
    response = _client(tenant, "owner@manakamana.test").get("/api/org/today/")
    assert response.status_code == 200, response.content
    body = response.json()

    for block in ("outpatients", "inpatients", "billing"):
        assert block in body, f"the owner was not shown {block}"
    assert body["facility"] is None
    assert re.fullmatch(r"\d+\.\d{2}", body["billing"]["collected"])
    assert body["inpatients"]["occupied"] <= body["inpatients"]["beds"]


def test_money_owed_is_never_negative(tenant):
    """Credit notes are issued invoices with negative totals. Counted as
    debts, they made the demo hospital owe itself money."""
    from decimal import Decimal

    body = _client(tenant, "owner@manakamana.test").get("/api/org/today/").json()
    assert Decimal(body["billing"]["outstanding"]) >= 0, body["billing"]


def test_a_facility_narrows_the_day(tenant):
    from apps.organization.models import Facility

    facility = Facility.objects.first()
    response = _client(tenant, "owner@manakamana.test").get(
        f"/api/org/today/?facility={facility.uuid}",
    )
    assert response.status_code == 200, response.content
    assert response.json()["facility"] == facility.name


def test_without_permission_a_block_is_absent_not_zero(tenant):
    from apps.organization.today import organization_today

    body = organization_today(_Nothing(), _Plan())
    assert set(body) == {"as_of", "facility"}, (
        "a block was reported to somebody who may not read what it counts"
    )


def test_a_module_outside_the_plan_is_absent(tenant):
    from apps.organization.today import organization_today

    body = organization_today(_Everything(), _Plan("hospital", "laboratory", "pharmacy"))
    for block in ("inpatients", "emergency", "laboratory", "pharmacy"):
        assert block not in body, f"{block} was shown without its module"
    assert "outpatients" in body and "billing" in body


def test_somebody_without_analytics_is_refused(tenant):
    response = _client(tenant, "doctor@manakamana.test").get("/api/org/today/")
    assert response.status_code == 403
