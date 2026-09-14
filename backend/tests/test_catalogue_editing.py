"""Editing what is for sale, while customers are on it.

The catalogue was complete and unreachable: plans could be seeded and read,
never edited, so pricing a module needed a developer and a deployment. What
had to be true before opening it up is what these check — that a plan is not a
document but a promise to everyone on it, and that the promise cannot be
quietly reduced.
"""

import json

import pytest
from django.test import Client
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


def _client(user):
    return Client(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")


@pytest.fixture
def platform(db):
    from apps.identity.models import User

    staff = User.objects.filter(is_platform_staff=True, is_active=True).first()
    if staff is None:
        pytest.skip("no platform staff account; run manage.py seed_demo")
    return _client(staff)


@pytest.fixture
def plan_with_subscriber(db):
    """The plan the demo tenant is actually on, and its subscription."""
    from apps.subscriptions.models import Subscription

    subscription = (
        Subscription.objects.filter(organization__slug="manakamana")
        .select_related("plan", "organization")
        .exclude(status__in=["cancelled", "expired", "draft"])
        .first()
    )
    if subscription is None:
        pytest.skip("the demo tenant has no live subscription")
    return subscription


def test_the_whole_catalogue_arrives_in_one_payload(platform):
    body = json.loads(platform.get("/api/platform/catalogue/").content)
    assert body["plans"] and body["modules"], "nothing is for sale"
    plan = body["plans"][0]
    assert {"code", "base_price", "modules", "features", "limits"} <= set(plan)
    # Every module the editor offers is one the application enforces, or it is
    # flagged as unknown rather than shown as a normal product.
    assert all("known" in module for module in body["modules"])


def test_a_price_can_be_changed_without_a_deployment(platform, plan_with_subscriber):
    code = plan_with_subscriber.plan.code
    before = plan_with_subscriber.plan.base_price

    response = platform.patch(
        f"/api/platform/catalogue/plans/{code}/",
        data=json.dumps({"base_price": "4321.00", "tagline": "Now with a tagline"}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content[:300]
    assert json.loads(response.content)["base_price"] == "4321.00"

    plan_with_subscriber.plan.refresh_from_db()
    assert plan_with_subscriber.plan.base_price != before


def test_taking_a_module_away_from_a_live_plan_is_refused_until_confirmed(
    platform, plan_with_subscriber, tenant,
):
    from apps.entitlements.resolver import resolve_entitlements

    code = plan_with_subscriber.plan.code
    catalogue = json.loads(platform.get("/api/platform/catalogue/").content)
    plan = next(row for row in catalogue["plans"] if row["code"] == code)
    included = [key for key, row in plan["modules"].items() if row["is_included"]]
    if "laboratory" not in included:
        pytest.skip("the demo plan does not include laboratory")

    wanted = {key: dict(row) for key, row in plan["modules"].items()}
    wanted["laboratory"]["is_included"] = False

    refused = platform.put(
        f"/api/platform/catalogue/plans/{code}/modules/",
        data=json.dumps({"modules": wanted}),
        content_type="application/json",
    )
    assert refused.status_code == 400, refused.content[:300]
    body = json.loads(refused.content)["error"]
    assert body["code"] == "needs_confirmation"
    impact = body["detail"]["impact"]
    assert impact["organizations"] >= 1
    assert impact["names"], "the refusal does not say who is affected"
    assert "laboratory" in impact["removes_modules"]

    # Still entitled: a refused edit changed nothing.
    assert resolve_entitlements(plan_with_subscriber.organization).has_module("laboratory")

    applied = platform.put(
        f"/api/platform/catalogue/plans/{code}/modules/",
        data=json.dumps({"modules": wanted, "confirm": True}),
        content_type="application/json",
    )
    assert applied.status_code == 200, applied.content[:300]
    assert not resolve_entitlements(plan_with_subscriber.organization).has_module("laboratory"), (
        "the customer kept a module the plan no longer includes"
    )


def test_adding_a_module_needs_no_confirmation(platform, plan_with_subscriber):
    code = plan_with_subscriber.plan.code
    catalogue = json.loads(platform.get("/api/platform/catalogue/").content)
    plan = next(row for row in catalogue["plans"] if row["code"] == code)
    wanted = {key: dict(row) for key, row in plan["modules"].items()}
    for row in wanted.values():
        row["is_included"] = True

    response = platform.put(
        f"/api/platform/catalogue/plans/{code}/modules/",
        data=json.dumps({"modules": wanted}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content[:300]


def test_tightening_a_limit_is_treated_as_taking_something_away(platform, plan_with_subscriber):
    code = plan_with_subscriber.plan.code
    plan = json.loads(platform.get(f"/api/platform/catalogue/plans/{code}/").content)
    limits = {key: dict(row) for key, row in plan["limits"].items()}
    if not limits:
        pytest.skip("the demo plan sets no limits")

    key = next(iter(limits))
    limits[key]["value"] = 1  # unlimited or larger, either way: tighter

    refused = platform.put(
        f"/api/platform/catalogue/plans/{code}/limits/",
        data=json.dumps({"limits": limits}),
        content_type="application/json",
    )
    assert refused.status_code == 400
    assert json.loads(refused.content)["error"]["code"] == "needs_confirmation"


def test_a_plan_change_is_previewed_before_it_is_applied(platform, plan_with_subscriber):
    from apps.catalog.models import Plan

    other = Plan.objects.exclude(pk=plan_with_subscriber.plan_id).filter(is_active=True).first()
    if other is None:
        pytest.skip("only one plan in the catalogue")

    preview = json.loads(platform.get(
        f"/api/platform/subscriptions/{plan_with_subscriber.uuid}/plan/?plan={other.code}",
    ).content)
    assert preview["from_plan"] == plan_with_subscriber.plan.code
    assert preview["to_plan"] == other.code
    assert "loses_modules" in preview and "gains_modules" in preview

    # A reason is required, and a reduction needs confirming.
    unreasoned = platform.post(
        f"/api/platform/subscriptions/{plan_with_subscriber.uuid}/plan/",
        data=json.dumps({"plan": other.code}),
        content_type="application/json",
    )
    assert unreasoned.status_code == 400
    assert json.loads(unreasoned.content)["error"]["code"] == "reason_required"

    body = {"plan": other.code, "reason": "Customer downgraded for the quiet season"}
    if preview["loses_something"]:
        blocked = platform.post(
            f"/api/platform/subscriptions/{plan_with_subscriber.uuid}/plan/",
            data=json.dumps(body), content_type="application/json",
        )
        assert blocked.status_code == 400
        assert json.loads(blocked.content)["error"]["code"] == "needs_confirmation"
        body["confirm"] = True

    applied = platform.post(
        f"/api/platform/subscriptions/{plan_with_subscriber.uuid}/plan/",
        data=json.dumps(body), content_type="application/json",
    )
    assert applied.status_code == 200, applied.content[:300]
    plan_with_subscriber.refresh_from_db()
    assert plan_with_subscriber.plan_id == other.pk


def test_a_hospital_administrator_cannot_price_the_product(tenant):
    from apps.identity.models import User

    owner = User.objects.get(email="owner@manakamana.test")
    assert owner.is_platform_staff is False
    client = _client(owner)

    assert client.get("/api/platform/catalogue/").status_code == 403
    assert client.patch(
        "/api/platform/catalogue/plans/enterprise/",
        data=json.dumps({"base_price": "0.00"}),
        content_type="application/json",
    ).status_code == 403


def test_a_module_the_application_does_not_enforce_cannot_be_sold(platform):
    """The refusal that keeps the catalogue honest: a plan may only contain
    modules that exist, and a module's existence comes from the code."""
    catalogue = json.loads(platform.get("/api/platform/catalogue/").content)
    code = catalogue["plans"][0]["code"]
    response = platform.put(
        f"/api/platform/catalogue/plans/{code}/modules/",
        data=json.dumps({"modules": {"dialysis": {"is_included": True}}}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "dialysis" in json.loads(response.content)["error"]["message"]


def test_a_closed_subscription_cannot_be_moved_between_plans(platform):
    """Found by previewing a change against a cancelled subscription and being
    shown a confident, meaningless diff — the platform list is ordered newest
    first and a customer's history sits in it beside their live one."""
    from apps.catalog.models import Plan
    from apps.subscriptions.models import Subscription

    closed = Subscription.objects.filter(status__in=["cancelled", "expired"]).first()
    if closed is None:
        pytest.skip("no closed subscription in this database")
    other = Plan.objects.exclude(pk=closed.plan_id).filter(is_active=True).first()

    preview = platform.get(f"/api/platform/subscriptions/{closed.uuid}/plan/?plan={other.code}")
    assert preview.status_code == 400
    assert json.loads(preview.content)["error"]["code"] == "subscription_closed"
