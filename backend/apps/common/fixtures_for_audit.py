"""Real values for the query parameters the screens interpolate.

`audit_screens` and `audit_queries` probe the paths a screen calls. Many of
those carry a value the screen resolves at runtime -- `?facility=${facility}`,
`?ward=${ward}`, `?admission=${uuid}` -- and a probe without it is not a probe
of that endpoint: `get_object_or_404(Facility, uuid=None)` answers 404, which
reads as a broken route and is nothing of the kind.

So the audits resolve one real row per parameter from the tenant and fill the
placeholders in. **One row, not a search**: the point is to reach the endpoint's
real code path, not to exercise its data. A board that answers for the first
facility answers for all of them, and an audit that iterated every facility
would take minutes to tell you the same thing.

**A parameter with no value resolves to nothing, and the path is left alone.**
An empty tenant has no facility, and inventing a uuid would replace an honest
404 with a misleading one. The audits report those rows as unprobeable rather
than pretending.
"""

import logging
import re

logger = logging.getLogger(__name__)

#: `${...}` and `{...}` as the frontend writes them inside a template literal.
PLACEHOLDER = re.compile(r"\$\{([^}]*)\}")


def _first(model_path: str, **filters):
    """The uuid of one row, or None when the tenant has none.

    Imported lazily and per call: this module is loaded by a management command
    that must not import half the application at start-up, and a model that
    does not exist in some deployment should make one parameter unresolvable
    rather than break the whole audit.
    """
    module_name, _, class_name = model_path.rpartition(".")
    try:
        module = __import__(module_name, fromlist=[class_name])
        model = getattr(module, class_name)
        row = model.objects.filter(**filters).order_by("pk").first()
    except Exception as error:  # noqa: BLE001 - an audit must not fail on this
        logger.debug("audit fixture %s unavailable: %s", model_path, error)
        return None
    return str(row.uuid) if row is not None else None


def resolve_values() -> dict:
    """`{parameter name: value}` for the placeholders the screens use.

    Keyed by the *substring* the frontend puts in the placeholder rather than
    by an exact match, because the same parameter is written several ways --
    `${facility}`, `${facilityUuid}`, `${session.facility}` -- and a table
    keyed on exact names would need an entry per spelling and would silently
    miss the next one.
    """
    from datetime import date, timedelta

    today = date.today()
    return {
        "facility": _first("apps.organization.models.Facility"),
        "ward": _first("apps.inpatient.models.Ward"),
        "admission": _first("apps.inpatient.models.Admission"),
        "patient": _first("apps.patients.models.Patient"),
        "encounter": _first("apps.encounters.models.Encounter"),
        "department": _first("apps.organization.models.Department"),
        "employee": _first("apps.hr.models.Employee"),
        "product": _first("apps.pharmacy.models.Product"),
        # Dates and plain scalars, so `?from=${start}&to=${end}` and
        # `?days=${days}` reach the endpoint with something it can parse.
        "from": (today - timedelta(days=30)).isoformat(),
        "start": (today - timedelta(days=30)).isoformat(),
        "to": today.isoformat(),
        "end": today.isoformat(),
        "date": today.isoformat(),
        "days": "30",
        "page": "1",
        # Two characters, not one: `/clinical/patients/search/` refuses a
        # single character with "Enter at least two characters", which is a
        # correct refusal that a one-character fixture turned into a reported
        # failure. A search term short enough to match half the tenant is
        # exactly right here -- the probe is checking that the endpoint
        # answers, not what it finds.
        "query": "ra",
        "q": "ra",
        "search": "ra",
        "term": "ra",
    }


def fill(path: str, values: dict) -> str | None:
    """Substitute every `${...}` in `path`, or None if one cannot be resolved.

    **Keyed on the query parameter's name, not on the expression inside the
    braces.** The first version matched the expression by substring, which
    reads well and is wrong: `?from=${today()}` matched the `to` key, because
    "to" is inside "today()", and `?to=${inDays(14)}` matched `days` and became
    `to=30`. The roster endpoint then answered 400 for all five users and the
    audit reported a working screen as broken -- a false failure invented by
    the tool built to find real ones.

    The parameter name is the API's own contract and the frontend has to spell
    it the server's way, so it is the one part of the call that cannot drift.

    Returning None rather than a partially-filled path is deliberate. Half a
    substitution leaves `?facility=${facility}&ward=w-1`, which the server
    reads as a facility literally named `${facility}` -- a 404 that looks like
    a broken endpoint and is a broken probe.
    """
    route, separator, query = path.partition("?")
    if "${" in route:
        # Path interpolation: the route itself depends on a value, so there is
        # no parameter name to key on. Callers treat these as unprobeable.
        return None
    if not separator:
        return path

    unresolved = False
    rebuilt = []
    for pair in query.split("&"):
        name, has_value, value = pair.partition("=")
        if not has_value or "${" not in value:
            rebuilt.append(pair)
            continue
        key = name.strip().lower()
        # `facility_uuid` and `facilityId` both mean the facility. Trimming the
        # common suffixes is enough; anything further would be guessing.
        for suffix in ("_uuid", "_id", "uuid", "id"):
            if key.endswith(suffix) and len(key) > len(suffix):
                key = key[: -len(suffix)].rstrip("_")
                break
        resolved = values.get(key)
        if not resolved:
            unresolved = True
            break
        # The whole value, not just the placeholder: `?ref=REF-${n}` would
        # otherwise become `REF-<uuid>`, which is not a reference either.
        rebuilt.append(f"{name}={resolved}")

    if unresolved:
        return None
    return f"{route}?{'&'.join(rebuilt)}"
