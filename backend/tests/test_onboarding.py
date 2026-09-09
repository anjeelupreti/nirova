"""That the platform can take on a customer without a database shell.

Everything needed to provision a tenant had existed for a long time and none
of it was reachable over HTTP. `OrganizationViewSet` was
`ReadOnlyModelViewSet`; `provision_organization` was called only by
`manage.py provision_tenant` and `seed_demo`. Onboarding therefore required an
engineer with shell access on the production host, which puts a person with a
database prompt in the middle of every sale.

**What is tested here, and what deliberately is not.** These cover the API
contract: who may call it, what it refuses, and that a refusal leaves nothing
behind. They do **not** drive a real provisioning run, and that is a constraint
rather than a choice:

    django.db.transaction.TransactionManagementError:
    This is forbidden when an 'atomic' block is active.

`CREATE DATABASE` cannot run inside a transaction, and pytest-django wraps
every test in one. The obvious fix is `django_db(transaction=True)` — and it
is the wrong fix here, because `TransactionTestCase` **truncates every table
in `databases` afterwards**, and `databases="__all__"` includes the demo
tenant that the rest of this suite reads. A test that passes by destroying the
fixture every other test depends on is worse than no test.

So the provisioning half is verified where it can be: `manage.py bootstrap`
creates a tenant database from nothing on every container start, and
`manage.py onboard` runs this exact service from the command line. See log 245
for the live end-to-end check against the running stack.
"""

import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

#: Deliberately not "sunrise" or anything a person might name a real customer.
SLUG = "probeclinic"
OWNER = "owner@probeclinic.test"


def _platform_client():
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    staff = User.objects.filter(is_platform_staff=True).first()
    if staff is None:
        pytest.skip("no platform staff account; run manage.py bootstrap")
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(staff).access_token}"
    )


def _purge():
    """Remove every trace of the probe customer, database included."""
    from apps.identity.models import Membership, User
    from apps.subscriptions.models import Subscription, SubscriptionEvent
    from apps.provisioning.models import ChangeRequestPolicy
    from apps.tenancy.models import Organization, TenantDatabase
    from apps.tenancy.provisioning import drop_physical_database

    organization = Organization.all_objects.filter(slug=SLUG).first()
    if organization is None:
        User.objects.filter(email=OWNER).delete()
        return

    tenant_db = TenantDatabase.all_objects.filter(
        organization=organization,
    ).first()
    if tenant_db is not None:
        try:
            drop_physical_database(tenant_db)
        except Exception:  # noqa: BLE001 - best effort; the row goes either way
            pass
        TenantDatabase.all_objects.filter(pk=tenant_db.pk).delete()

    SubscriptionEvent.all_objects.filter(
        subscription__organization=organization,
    ).delete()
    Subscription.all_objects.filter(organization=organization).delete()
    ChangeRequestPolicy.all_objects.filter(organization=organization).delete()
    Membership.all_objects.filter(organization=organization).delete()
    Organization.all_objects.filter(pk=organization.pk).delete()
    User.objects.filter(email=OWNER).delete()


@pytest.fixture
def clean_slate():
    _purge()
    yield
    _purge()


def _onboard(client, **overrides):
    payload = {
        "slug": SLUG,
        "legal_name": "Probe Clinic Pvt Ltd",
        "display_name": "Probe Clinic",
        "primary_email": "admin@probeclinic.test",
        "business_type": "clinic",
        "plan_code": "starter",
        "owner_email": OWNER,
        "owner_name": "Rita Adhikari",
        "trial_days": 30,
        **overrides,
    }
    return client.post(
        "/api/platform/organizations/onboard/",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_an_unknown_plan_is_refused_and_names_the_real_ones(clean_slate):
    """A refusal that does not say what would have worked is a dead end."""
    from apps.tenancy.models import Organization

    response = _onboard(_platform_client(), plan_code="platinum-deluxe")
    assert response.status_code == 400, response.content

    error = json.loads(response.content.decode())["error"]
    assert error["detail"].get("available"), (
        "the operator is told the plan is wrong and not which plans exist"
    )
    assert not Organization.objects.filter(slug=SLUG).exists(), (
        "a customer was created for a plan that does not exist"
    )


def test_only_platform_staff_may_onboard(clean_slate, tenant):
    """A customer's own administrator is not the vendor.

    `organization_admin` is the most powerful role inside a tenant and holds
    every permission in the catalogue -- which is exactly why this endpoint is
    guarded by `IsPlatformStaff` and not by a permission code. No amount of
    authority inside one customer should create another.
    """
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User
    from apps.tenancy.models import Organization

    owner = User.objects.filter(email=f"owner@{tenant.slug}.test").first()
    if owner is None:
        pytest.skip("no tenant owner account")

    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(owner).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    assert _onboard(client).status_code == 403
    assert not Organization.objects.filter(slug=SLUG).exists()
