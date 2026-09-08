"""That a customer can configure their own system.

`ConfigSetting` had existed since the organization app was written and had
**never had an endpoint**, so two features shipped that nobody could reach:
the privacy switch, and the whole locale layer added in logs 241 and 242.
`config.read` and `config.update` were in the catalogue, held by four roles,
and checked by nothing.

The tests that matter most here are the refusals. A settings endpoint is a
write path into a tenant's configuration table, and the two ways it goes wrong
are accepting a key nobody declared and accepting a value nobody validated.
"""

import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"
PATH = "/api/org/settings/"


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
    )


def _body(response):
    return json.loads(response.content.decode())


@pytest.fixture
def admin(tenant):
    client = _client(f"owner@{DEMO}.test", tenant)
    if client is None:
        pytest.skip("no owner account; run manage.py bootstrap")
    return client


@pytest.fixture(autouse=True)
def _leave_no_settings_behind(tenant):
    """The suite runs against a real tenant.

    A test that left the timezone on Dubai would change what every later test
    measures -- including the ones in `test_locale.py`, which assert the
    defaults.
    """
    from apps.organization.locale import clear_cache
    from apps.organization.models import ConfigSetting

    def purge():
        ConfigSetting.all_objects.filter(
            namespace__in=["locale", "privacy"],
        ).delete()
        clear_cache()

    purge()
    yield
    purge()


def _put(client, code, value, **extra):
    return client.put(
        PATH,
        data=json.dumps({"code": code, "value": value, **extra}),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_the_settings_list_says_what_is_chosen_and_what_is_merely_default(
    tenant, admin,
):
    """`is_set` is the field that makes the screen honest.

    "13.00" tells a reader nothing about whether somebody chose it or whether
    it is what everybody gets, and those are different facts when you are
    deciding whether to change it.
    """
    body = _body(admin.get(PATH))
    by_code = {s["code"]: s for s in body["settings"]}

    assert "locale.timezone" in by_code
    assert by_code["locale.timezone"]["value"] == "Asia/Kathmandu"
    assert by_code["locale.timezone"]["is_set"] is False
    assert by_code["locale.timezone"]["set_at"] == ""

    _put(admin, "locale.timezone", "Asia/Dubai")

    after = {s["code"]: s for s in _body(admin.get(PATH))["settings"]}
    assert after["locale.timezone"]["value"] == "Asia/Dubai"
    assert after["locale.timezone"]["is_set"] is True
    assert after["locale.timezone"]["set_at"] == "organization"


def test_a_choice_setting_publishes_its_choices(tenant, admin):
    """So the screen renders a select without a hard-coded list of its own.

    A second copy of the fiscal calendars in the frontend is a second thing to
    update, and the one that gets forgotten is always the copy.
    """
    body = _body(admin.get(PATH))
    calendar = next(
        s for s in body["settings"] if s["code"] == "locale.fiscal_calendar"
    )
    values = {c["value"] for c in calendar["choices"]}
    assert {"nepal", "gregorian", "april", "july"} <= values
    assert all(c["label"] for c in calendar["choices"]), (
        "a choice with no label is a value the reader has to decode"
    )


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------


def test_a_setting_nobody_declared_cannot_be_written(tenant, admin):
    """The reason this is a registry and not a key/value endpoint.

    Without it, `config.update` is permission to write arbitrary rows into a
    tenant's configuration table, and every consumer of `config_value` has to
    defend itself against keys it has never heard of.
    """
    from apps.organization.models import ConfigSetting

    response = _put(admin, "evil.backdoor", "x")
    assert response.status_code == 400, response.content
    assert not ConfigSetting.all_objects.filter(namespace="evil").exists(), (
        "the refusal did not prevent the write"
    )


@pytest.mark.parametrize(
    "code,value",
    [
        ("locale.timezone", "Asia/Dubay"),          # a plausible typo
        ("locale.fiscal_calendar", "narnia"),       # not one of the choices
        ("locale.standard_tax_rate", "not a number"),
        ("locale.standard_tax_rate", "300"),        # a percentage over 100
        ("locale.currency", "Rupees"),              # not a three-letter code
    ],
)
def test_a_value_that_would_break_something_is_refused(
    tenant, admin, code, value,
):
    """Each of these was reachable before validation existed.

    The timezone one is the pointed case: a misspelled zone does not throw
    anywhere, it silently leaves every timestamp in the default zone. Caught
    at the boundary, it is a message; caught nowhere, it is a wrong clock.
    """
    response = _put(admin, code, value)
    assert response.status_code == 400, (
        f"{code}={value!r} was accepted: {response.content}"
    )
    assert _body(response)["error"]["message"], "a refusal with nothing to act on"


def test_an_organization_wide_setting_is_refused_per_facility(tenant, admin):
    """A privacy policy one branch can switch off is not a policy."""
    from apps.organization.models import Facility

    facility = Facility.objects.first()
    response = _put(
        admin, "privacy.require_care_relationship", True,
        facility_uuid=str(facility.uuid),
    )
    assert response.status_code == 400, response.content
    assert "whole organization" in _body(response)["error"]["message"]


# ---------------------------------------------------------------------------
# Who may
# ---------------------------------------------------------------------------


def test_reading_and_changing_are_different_permissions(tenant, admin):
    """`config.read` and `config.update` are separate codes and it shows here.

    An operations manager may see how the system is configured and may not
    change it. Collapsing the two would have made that row impossible.
    """
    manager = _client(f"manager@{DEMO}.test", tenant)
    if manager is None:
        pytest.skip("no operations manager account")

    assert manager.get(PATH).status_code == 200
    assert _put(manager, "locale.currency", "AED").status_code == 403


def test_somebody_with_neither_permission_sees_nothing(tenant):
    doctor = _client(f"doctor@{DEMO}.test", tenant)
    if doctor is None:
        pytest.skip("no doctor account")
    assert doctor.get(PATH).status_code == 403


# ---------------------------------------------------------------------------
# Resetting
# ---------------------------------------------------------------------------


def test_resetting_returns_to_the_default_and_says_so(tenant, admin):
    """Deleting the row rather than writing the default value.

    So `is_set` becomes false again, and a tenant that later changes its mind
    about what the default should be follows it rather than being pinned to a
    value it once copied.
    """
    _put(admin, "locale.timezone", "Asia/Dubai")
    response = admin.delete(f"{PATH}?code=locale.timezone")
    assert response.status_code == 200, response.content

    body = _body(response)
    assert body["value"] == "Asia/Kathmandu"
    assert body["is_set"] is False


def test_the_change_is_written_to_the_audit_log_with_both_sides(tenant, admin):
    """"Somebody turned privacy on" is not enough a year later."""
    from apps.audit.models import AuditEvent

    _put(admin, "privacy.require_care_relationship", True)

    event = (
        AuditEvent.objects.filter(
            entity_type="organization.ConfigSetting",
            entity_id="privacy.require_care_relationship",
        )
        .order_by("-created_at")
        .first()
    )
    assert event is not None, "changing a security setting left no audit trail"
    change = (event.changes or {}).get("privacy.require_care_relationship", {})
    assert change.get("to") is True, change
    assert "from" in change, "the log records what it became and not what it was"
