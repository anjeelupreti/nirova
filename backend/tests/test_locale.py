"""That a group operating in two countries keeps two sets of local facts.

Nirova was built for Nepal and three assumptions about Nepal reached places
that have nothing to do with geography: one global `TIME_ZONE`, a fiscal year
that begins on 16 July, and a VAT rate. None of that is wrong for the practice
it was written for. All of it is wrong for a group with a branch in Dubai.

These tests are written from the outside in -- a real request, with real
headers, reading a real timestamp back -- because the failure this guards
against is a *display* failure. The data was always stored in UTC and was
always right; what was wrong was the clock everybody read it on, and only an
end-to-end check can see that.
"""

import json
from datetime import date

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"


def _client(email, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        return None
    token = RefreshToken.for_user(user).access_token
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )


def _clear_locale():
    from apps.organization.locale import LOCALE_NAMESPACE
    from apps.organization.models import ConfigSetting

    ConfigSetting.all_objects.filter(namespace=LOCALE_NAMESPACE).delete()


@pytest.fixture
def locale_reset(tenant):
    """Leave the tenant exactly as it was found.

    These tests write organization-wide configuration, and the suite runs
    against a real demo tenant. One that left a Dubai timezone behind would
    silently change what every later test measures.
    """
    _clear_locale()
    yield
    _clear_locale()


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_a_tenant_that_has_said_nothing_is_nepal(tenant, locale_reset):
    """A single clinic in Kathmandu configures nothing and gets Nepal.

    The point of the defaults. If this test ever has to change, the change is
    a migration for every existing customer, not an edit.
    """
    from django.conf import settings

    from apps.organization.locale import (
        FiscalCalendar,
        currency,
        fiscal_calendar,
        timezone_name,
    )

    assert timezone_name() == settings.TIME_ZONE == "Asia/Kathmandu"
    assert fiscal_calendar() == FiscalCalendar.NEPAL
    assert currency() == "NPR"


def test_the_nepali_fiscal_year_is_unchanged_by_any_of_this(tenant, locale_reset):
    """The regression that would matter most.

    `fiscal_year_for` now asks which calendar applies before answering.
    Nepal's answer must be bit-for-bit what it was, because invoice numbering
    is gapless per fiscal year and a changed label renumbers documents that
    have already been issued.
    """
    from apps.billing.fiscal import fiscal_year_for

    assert fiscal_year_for(date(2026, 9, 8)) == "2083/84"
    assert fiscal_year_for(date(2026, 7, 15)) == "2082/83", (
        "the day before Shrawan 1 still belongs to the previous year"
    )
    assert fiscal_year_for(date(2026, 7, 16)) == "2083/84", (
        "Shrawan 1 opens the new year"
    )


# ---------------------------------------------------------------------------
# A second country
# ---------------------------------------------------------------------------


def test_a_gregorian_tenant_numbers_by_the_calendar_year(tenant, locale_reset):
    """A Dubai branch does not reset its invoice sequence in July."""
    from apps.billing.fiscal import fiscal_year_for
    from apps.organization.config import set_config_value
    from apps.organization.locale import (
        FISCAL_CALENDAR_KEY,
        LOCALE_NAMESPACE,
        FiscalCalendar,
    )

    set_config_value(
        LOCALE_NAMESPACE, FISCAL_CALENDAR_KEY, FiscalCalendar.GREGORIAN,
    )
    assert fiscal_year_for(date(2026, 9, 8)) == "2026"
    assert fiscal_year_for(date(2026, 7, 15)) == "2026", (
        "July is the middle of a calendar year, not the start of one -- this "
        "is the exact day Nepal's boundary would have moved it"
    )
    assert fiscal_year_for(date(2027, 1, 1)) == "2027"


def test_an_april_tenant_spans_two_years_in_its_label(tenant, locale_reset):
    """India and the UK. Written the way their finance teams write it."""
    from apps.billing.fiscal import fiscal_year_for
    from apps.organization.config import set_config_value
    from apps.organization.locale import (
        FISCAL_CALENDAR_KEY,
        LOCALE_NAMESPACE,
        FiscalCalendar,
    )

    set_config_value(LOCALE_NAMESPACE, FISCAL_CALENDAR_KEY, FiscalCalendar.APRIL)
    assert fiscal_year_for(date(2026, 9, 8)) == "2026/27"
    assert fiscal_year_for(date(2026, 3, 31)) == "2025/26"
    assert fiscal_year_for(date(2026, 4, 1)) == "2026/27"


def test_one_facility_may_differ_from_the_group(tenant, locale_reset):
    """The reason this is configuration and not a setting.

    A group with a Kathmandu head office and a Dubai branch has one set of
    records and two financial years. `ConfigSetting` already resolves
    narrowest-first, so the facility-level row wins for that facility and the
    organization-level default stands everywhere else.
    """
    from apps.billing.fiscal import fiscal_year_for
    from apps.organization.config import set_config_value
    from apps.organization.locale import (
        FISCAL_CALENDAR_KEY,
        LOCALE_NAMESPACE,
        FiscalCalendar,
        fiscal_calendar,
    )
    from apps.organization.models import ConfigScope, Facility

    branch = Facility.objects.first()
    assert branch is not None, "no facility; run manage.py bootstrap"

    set_config_value(
        LOCALE_NAMESPACE, FISCAL_CALENDAR_KEY, FiscalCalendar.GREGORIAN,
        scope=ConfigScope.FACILITY, facility=branch,
    )

    assert fiscal_calendar(facility=branch) == FiscalCalendar.GREGORIAN
    assert fiscal_year_for(date(2026, 9, 8), facility=branch) == "2026"
    # And the group is untouched.
    assert fiscal_calendar() == FiscalCalendar.NEPAL
    assert fiscal_year_for(date(2026, 9, 8)) == "2083/84"


def test_the_group_can_lock_the_calendar_so_no_branch_may_differ(
    tenant, locale_reset,
):
    """The other half, and the one a consolidated filer needs.

    A group filing one return cannot have branches choosing their own year.
    `is_locked` at organization scope beats any facility row, which is a
    mechanism `ConfigSetting` already had and nothing was using for this.
    """
    from apps.organization.config import set_config_value
    from apps.organization.locale import (
        FISCAL_CALENDAR_KEY,
        LOCALE_NAMESPACE,
        FiscalCalendar,
        fiscal_calendar,
    )
    from apps.organization.models import ConfigScope, Facility

    branch = Facility.objects.first()
    set_config_value(
        LOCALE_NAMESPACE, FISCAL_CALENDAR_KEY, FiscalCalendar.GREGORIAN,
        scope=ConfigScope.FACILITY, facility=branch,
    )
    set_config_value(
        LOCALE_NAMESPACE, FISCAL_CALENDAR_KEY, FiscalCalendar.NEPAL,
        is_locked=True,
    )

    assert fiscal_calendar(facility=branch) == FiscalCalendar.NEPAL, (
        "a branch overrode a calendar the group had locked"
    )


# ---------------------------------------------------------------------------
# The clock everybody actually reads
# ---------------------------------------------------------------------------


def test_timestamps_render_in_the_configured_zone(tenant, locale_reset):
    """End to end, over HTTP, because this is a display failure.

    `/api/health/` returns `timezone.now().isoformat()`, so the offset in the
    response is exactly the offset the middleware activated. Kathmandu is
    +05:45 and Dubai is +04:00 -- an hour and three quarters apart, which is
    the gap a ward in the Gulf was reading its drug administration times
    across.
    """
    from apps.organization.config import set_config_value
    from apps.organization.locale import LOCALE_NAMESPACE, TIMEZONE_KEY

    client = _client(f"owner@{DEMO}.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    # Health is unauthenticated and tenant-free, so it is read through an
    # endpoint that goes through the tenant middleware instead.
    def offset_of(path="/api/auth/session/"):
        body = json.loads(client.get(path).content.decode())
        stamp = (body.get("user") or {}).get("last_active_at")
        assert stamp, f"no timestamp in the response to prove anything with: {body}"
        return stamp[-6:]

    assert offset_of() == "+05:45", "the default is not Kathmandu"

    set_config_value(LOCALE_NAMESPACE, TIMEZONE_KEY, "Asia/Dubai")
    assert offset_of() == "+04:00", (
        "the configured zone was not applied, so every timestamp this group "
        "reads is in somebody else's local time"
    )


def test_a_nonsense_timezone_does_not_take_the_tenant_down(tenant, locale_reset):
    """A typo in configuration is a wrong clock, not an outage.

    It was already a wrong clock before this feature existed, so falling back
    to the default is no worse than the status quo -- and refusing every
    request because somebody typed "Asia/Dubay" would be.
    """
    from apps.organization.config import set_config_value
    from apps.organization.locale import LOCALE_NAMESPACE, TIMEZONE_KEY

    client = _client(f"owner@{DEMO}.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    set_config_value(LOCALE_NAMESPACE, TIMEZONE_KEY, "Asia/Dubay")
    response = client.get("/api/auth/session/")
    assert response.status_code == 200, (
        "a misspelled timezone brought the whole tenant down"
    )
