"""Where a facility is, and what that means for its records.

Nirova was built for Nepal and three assumptions about Nepal are baked into
places that have nothing to do with geography:

* `settings.TIME_ZONE = "Asia/Kathmandu"`, a single constant, so **every
  timestamp in the system renders in Kathmandu time**. Django stores UTC, so
  the data is right and the display is wrong -- which is the more dangerous
  of the two, because nothing looks broken. A ward in Dubai administering a
  drug at 08:00 local sees it recorded as 09:45. Nobody checks a clock they
  have no reason to distrust.

* `fiscal_year_for()` returns a Bikram Sambat label and assumes the year
  begins on 16 July. Invoice numbering is gapless *per fiscal year*, so a
  facility in a country whose year begins in January would have its invoice
  sequence reset in the middle of July, which is a compliance problem rather
  than a cosmetic one.

* `STANDARD_VAT_RATE = 13.00`.

None of this is wrong for the practice this was written for, and a single
clinic in Kathmandu should not have to configure any of it. So the defaults
below **are** Nepal, and a group with a facility in another country states the
difference rather than the whole picture.

**Why configuration and not a model field.** `ConfigSetting` already resolves
narrowest-first -- facility, then department, then organization -- and already
supports locking a value at the organization level so a branch cannot quietly
opt out of a group policy. A `Facility.timezone` column would be a second,
weaker version of a mechanism that exists. It also means no migration, and no
schema change to a table every tenant database has a copy of.
"""

from contextvars import ContextVar
from datetime import date
from decimal import Decimal

from django.conf import settings

LOCALE_NAMESPACE = "locale"

TIMEZONE_KEY = "timezone"
FISCAL_CALENDAR_KEY = "fiscal_calendar"
CURRENCY_KEY = "currency"
TAX_RATE_KEY = "standard_tax_rate"

#: Locale values already resolved during this request, keyed by (key,
#: facility_id).
#:
#: `ServiceItem.effective_tax_rate` is a model *property* -- it has no request
#: to hang a memo on, and it is evaluated once per row when a service
#: catalogue is serialised. Without this, opening a 50-item price list would
#: run fifty configuration queries to answer the same question fifty times.
#:
#: A `ContextVar` rather than a module dict, matching how the tenant context
#: itself is carried: module state is shared across threads and would leak one
#: tenant's locale into another's request. Cleared by the tenant middleware
#: alongside the tenant token, so nothing survives the request that set it and
#: a configuration change is visible on the very next one.
_resolved: ContextVar[dict | None] = ContextVar("nirova_locale", default=None)


def clear_cache() -> None:
    """Forget everything resolved for this request. Called by the middleware."""
    _resolved.set(None)


class FiscalCalendar:
    """Which day a financial year begins on.

    Named by what they are rather than by country, because several countries
    share each one and a customer should not have to find their own flag in a
    list to discover that their year starts in April like everyone else's.
    """

    #: 16 July, labelled in Bikram Sambat: "2083/84". Nepal.
    NEPAL = "nepal"
    #: 1 January, labelled by the Gregorian year: "2026". Most of the world,
    #: including the UAE, Qatar, Germany and China.
    GREGORIAN = "gregorian"
    #: 1 April, labelled by the span: "2026/27". India, the United Kingdom,
    #: Japan, South Africa.
    APRIL = "april"
    #: 1 July, labelled by the span: "2026/27". Australia, Egypt, Pakistan,
    #: Bangladesh.
    JULY = "july"

    CHOICES = [
        (NEPAL, "Nepal (16 July, Bikram Sambat)"),
        (GREGORIAN, "Calendar year (1 January)"),
        (APRIL, "1 April"),
        (JULY, "1 July"),
    ]

    #: (month, day) each year starts on. Nepal is absent: its start moves
    #: against the Gregorian calendar and `apps.billing.fiscal` computes it.
    STARTS = {
        GREGORIAN: (1, 1),
        APRIL: (4, 1),
        JULY: (7, 1),
    }


#: What a tenant gets when it has said nothing. Nepal, because that is who
#: this was built for and a single clinic in Kathmandu should not have to
#: configure its own country to raise an invoice.
DEFAULTS = {
    TIMEZONE_KEY: settings.TIME_ZONE,
    FISCAL_CALENDAR_KEY: FiscalCalendar.NEPAL,
    CURRENCY_KEY: "NPR",
    # Nepal's standard VAT. The UAE charges 5, the UK 20, India varies by
    # GST slab -- so this is the *fallback* for a service that names no rate
    # of its own, not a claim about what healthcare is taxed at anywhere.
    TAX_RATE_KEY: "13.00",
}


def _value(key, facility=None, department=None):
    """One locale value, resolved for this facility, once per request.

    Swallows a missing configuration table on purpose. This is called from
    request middleware, which runs before anything has confirmed the tenant
    database is migrated -- and a group that has not yet configured a locale
    is the overwhelmingly common case, not an error worth a 500.
    """
    from apps.organization.config import config_value

    facility_id = getattr(facility, "id", facility)
    memo_key = (key, facility_id, getattr(department, "id", department))
    memo = _resolved.get()
    if memo is not None and memo_key in memo:
        return memo[memo_key]

    try:
        value = config_value(
            LOCALE_NAMESPACE, key, default=DEFAULTS[key],
            facility=facility, department=department,
        )
    except Exception:  # noqa: BLE001 - see the docstring
        # Not memoised. A failure here usually means the tenant database is
        # not ready, and caching that answer would keep serving the default
        # after it became ready.
        return DEFAULTS[key]

    if memo is None:
        memo = {}
        _resolved.set(memo)
    memo[memo_key] = value
    return value


def timezone_name(facility=None) -> str:
    """The IANA zone this facility's staff read their clocks in.

    A group's facilities may sit in different zones, which is the whole reason
    this resolves per facility rather than per organization: a chain running
    Kathmandu and Dubai has one set of records and two working days.
    """
    return _value(TIMEZONE_KEY, facility=facility)


def fiscal_calendar(facility=None) -> str:
    """Which financial year this facility keeps.

    Per facility rather than per organization, and that is deliberate but
    debatable: a group filing one consolidated return wants a single calendar,
    and a group whose branches are separately incorporated in different
    countries genuinely has several. The organization-level lock is how the
    first kind stops the second kind's behaviour -- set it locked at
    organization scope and no facility can differ.
    """
    return _value(FISCAL_CALENDAR_KEY, facility=facility)


def currency(facility=None) -> str:
    return _value(CURRENCY_KEY, facility=facility)


def standard_tax_rate(facility=None) -> Decimal:
    """The rate a standard-rated service is charged at, when it names none.

    A `Decimal`, never a float: this multiplies money. `Decimal(str(...))`
    rather than `Decimal(...)` because a value that arrived from JSON
    configuration may be a float, and `Decimal(0.05)` is not 0.05.
    """
    raw = _value(TAX_RATE_KEY, facility=facility)
    try:
        return Decimal(str(raw))
    except (ArithmeticError, TypeError, ValueError):
        return Decimal(DEFAULTS[TAX_RATE_KEY])


def fiscal_year_start_for(calendar: str, on_date: date) -> date:
    """First day of the financial year containing `on_date`, for a calendar.

    Nepal is not handled here -- its start moves against the Gregorian
    calendar and `apps.billing.fiscal.fiscal_year_start` already computes it
    from the Bikram Sambat new year. Raising rather than guessing, so a caller
    that forgets the special case fails loudly instead of silently filing
    Nepali invoices under a January year.
    """
    if calendar == FiscalCalendar.NEPAL:
        raise ValueError(
            "Nepal's fiscal year start is computed by apps.billing.fiscal, "
            "not from a fixed month and day."
        )
    month, day = FiscalCalendar.STARTS[calendar]
    start = date(on_date.year, month, day)
    if on_date < start:
        start = date(on_date.year - 1, month, day)
    return start


def fiscal_year_label_for(calendar: str, start: date) -> str:
    """How a year beginning on `start` is written down.

    A calendar year is one number, because "2026/27" for a year that ends in
    December would be a lie. Everything else spans two and is written that
    way, which is how the finance teams in those countries already write it.
    """
    if calendar == FiscalCalendar.GREGORIAN:
        return str(start.year)
    return f"{start.year}/{(start.year + 1) % 100:02d}"
