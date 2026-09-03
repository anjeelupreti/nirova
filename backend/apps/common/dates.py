"""Turning query-string dates into dates, at the edge.

A query parameter is always a string. Passing it straight into a service that
does arithmetic on it — `since - timedelta(days=1)`, `until - since` — raises a
TypeError, and passing it into an ORM filter *works*, which is worse: the same
value behaves differently depending on which line of the service touches it
first, so the bug appears only on the paths that compute rather than filter.

Parsing once at the API boundary means every service below it can assume it
has a real date. This module exists because that assumption was violated in
two modules on the same afternoon.
"""

from datetime import date, datetime

from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import serializers


def as_date(value, field: str = "date"):
    """A `date`, or None for an absent or empty parameter.

    Accepts an ISO date, an ISO datetime (taking its date), and anything that
    is already a date. Raises a DRF validation error rather than a TypeError,
    because a malformed `?since=lastweek` is a client mistake and deserves a
    400 with a sentence rather than a 500 with a traceback.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    parsed = parse_date(text)
    if parsed is None:
        moment = parse_datetime(text)
        parsed = moment.date() if moment else None
    if parsed is None:
        raise serializers.ValidationError(
            {field: f"'{text}' is not a date. Use YYYY-MM-DD."}
        )
    return parsed


def date_params(request, *names) -> dict:
    """Parse several date query parameters at once.

    Returns a dict keyed by name with `None` for anything absent, so a view
    can splat it into a service call without repeating the guard for each one.
    """
    return {name: as_date(request.query_params.get(name), name) for name in names}
