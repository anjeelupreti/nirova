"""Nepali fiscal year handling.

Nepal's fiscal year runs from Shrawan 1 to Ashadh end in the Bikram Sambat
calendar — roughly 16 July to 15 July in the Gregorian one. Statutory invoice
numbering restarts each fiscal year, so getting this wrong misnumbers every
document a facility issues.

**A deliberate approximation, stated plainly.** Shrawan 1 does not fall on a
fixed Gregorian date: it drifts between 16 and 17 July depending on the year,
because BS is a lunisolar calendar whose month lengths vary and are published
annually rather than computed. This module pins the boundary at 16 July.

That is wrong for at most one day per year, and only for documents issued on
that day. It is accepted here because the alternative — bundling a BS
conversion table — is a real dependency with its own maintenance burden, and
because the boundary is configurable per organization (`fiscal_year_start_*`
on `Organization`) for customers who need it exact.

**If this system is used for statutory VAT filing, replace this with a proper
BS calendar before go-live.** The seam is `fiscal_year_for()`: swap its body,
and everything downstream follows.
"""

from datetime import date

#: Gregorian date on which the Nepali fiscal year begins, near enough.
#: See the module docstring for why this is a constant and not a calculation.
FISCAL_YEAR_START_MONTH = 7
FISCAL_YEAR_START_DAY = 16

#: Offset from a Gregorian year to the Bikram Sambat year, for dates falling
#: after the BS new year (Baisakh 1, around 14 April). Shrawan is always after
#: Baisakh, so the fiscal year's opening month always uses this offset.
BS_OFFSET_AFTER_NEW_YEAR = 57
BS_OFFSET_BEFORE_NEW_YEAR = 56


def fiscal_year_start(on_date: date) -> date:
    """The Gregorian date on which `on_date`'s fiscal year began."""
    boundary = date(on_date.year, FISCAL_YEAR_START_MONTH, FISCAL_YEAR_START_DAY)
    if on_date >= boundary:
        return boundary
    return date(on_date.year - 1, FISCAL_YEAR_START_MONTH, FISCAL_YEAR_START_DAY)


def fiscal_year_for(on_date: date | None = None) -> str:
    """The fiscal year label for a date, in the form Nepal writes it: 2082/83.

    Worked example. 2 September 2026 falls after 16 July 2026, so the fiscal
    year began on 16 July 2026. That date is in Shrawan, after Baisakh, so its
    BS year is 2026 + 57 = 2083, and the label is "2083/84".
    """
    on_date = on_date or date.today()
    start = fiscal_year_start(on_date)
    bs_year = start.year + BS_OFFSET_AFTER_NEW_YEAR
    return f"{bs_year}/{(bs_year + 1) % 100:02d}"


def fiscal_year_bounds(on_date: date | None = None) -> tuple[date, date]:
    """First and last Gregorian day of the fiscal year containing `on_date`.

    Used by period reporting, where "this year's revenue" has to mean the
    customer's year rather than the calendar's.
    """
    from datetime import timedelta

    start = fiscal_year_start(on_date or date.today())
    next_start = date(
        start.year + 1, FISCAL_YEAR_START_MONTH, FISCAL_YEAR_START_DAY
    )
    return start, next_start - timedelta(days=1)


def approximate_bs_year(on_date: date | None = None) -> int:
    """The Bikram Sambat year for a Gregorian date.

    Approximate for the same reason as the rest of this module, and off by at
    most a day either side of Baisakh 1. Adequate for display; not adequate
    for a statutory filing.
    """
    on_date = on_date or date.today()
    # Baisakh 1 lands around 14 April.
    if (on_date.month, on_date.day) >= (4, 14):
        return on_date.year + BS_OFFSET_AFTER_NEW_YEAR
    return on_date.year + BS_OFFSET_BEFORE_NEW_YEAR
