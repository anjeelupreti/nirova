"""What the frontend asks the API for, read out of the frontend source.

Shared by `manage.py audit_screens`, which probes those paths as each demo
user and reports what refuses, and `manage.py audit_queries`, which probes
them once and counts the queries behind each one. Both audits need the same
answer to the same question -- "what does this screen actually call?" -- and a
second copy of this regex would drift from the first one silently, which is
the failure this function exists to avoid in the first place.

**Why a regex over the source and not a hand-kept list.** A list of
screen-to-endpoint mappings maintained by hand drifts from the code, and it
drifts without any symptom: the audit keeps passing while it checks fewer and
fewer things. `test_nav.py` learned that the hard way (log 236). The source is
the only description of what a screen calls that cannot be out of date.
"""

import re
from pathlib import Path

from django.conf import settings

#: Paths whose call would change data. Read-only verbs only: an audit that
#: posted would be an audit that has to be cleaned up after. Names rather than
#: methods, because the path is all either audit has to go on before it calls.
UNSAFE = re.compile(
    r"/(create|approve|reject|void|cancel|close|open|start|complete|"
    r"dispense|check-in|check-out|call-next|decide|submit|issue|post|pay)/?$"
)

#: `api.get<T>("/path")`, `api.post(\`/path/${id}/\`)`, and the rest. Captures
#: the whole quoted string including interpolations, so that a path built with
#: `${id}` can be told apart from one written out in full.
API_CALL = re.compile(r"""api\.(?:get|post|patch|del|put)[^(]*\(\s*[`"']([^`"']*)""")


def paths_by_page(only: str | None = None) -> dict[str, dict[str, bool]]:
    """Map each page to the API paths it calls.

    Returns `{page_name: {path: inferred_only}}`, where `inferred_only` is True
    when every sighting of that path on that page was a truncated detail route
    rather than a literal call.

    **The truncation matters and used to be silent.** An earlier regex stopped
    at `$`, so `/payroll/payslips/${reference}/document/` was recorded and
    probed as `/payroll/payslips/` -- a different endpoint with a different
    permission -- and its entirely correct 403 was then reported as a failure
    of the screen. Several of the first run's 117 failures were that, and each
    one cost a real triage read. Callers use the flag to show those rows
    without counting them.
    """
    root = Path(settings.BASE_DIR).parent / "frontend" / "src" / "pages"
    if not root.exists():
        return {}

    pages: dict[str, dict[str, bool]] = {}
    for file in sorted(root.rglob("*.tsx")):
        name = file.stem
        if only and only.lower() not in name.lower():
            continue

        paths: dict[str, bool] = {}
        for match in API_CALL.finditer(file.read_text(encoding="utf-8")):
            raw = match.group(1)
            if not raw.startswith("/"):
                continue

            # **An interpolation in the query string is not the same as one in
            # the path, and treating them alike hid a fifth of the console from
            # this audit.**
            #
            # `/hr/leave/${ref}/decide/` has a *route* that depends on a value:
            # there is nothing to probe without inventing a reference.
            # `/ed/board/?facility=${f}` has a fully determined route and a
            # dynamic *value* -- it is a real call the screen makes on every
            # load. The first version dropped the query string from both, so
            # `/ed/board/` was probed with no facility, the view's
            # `get_object_or_404(Facility, ...)` answered 404, and that 404 was
            # written off as an artifact. The ED board, the ICU board, the
            # outpatient queue and the laboratory worklist -- four of the
            # busiest screens in the product -- were being reported on without
            # ever being called.
            route, _, query = raw.partition("?")
            if "$" in route:
                # A detail route. Keep the collection prefix so a reader sees
                # the module was reached, but it is a different endpoint from
                # the one the screen calls and is not counted.
                prefix = route.split("$", 1)[0]
                if not prefix.endswith("/") or UNSAFE.search(prefix):
                    continue
                full = "/api" + prefix
                paths[full] = paths.get(full, True) and True
                continue

            if UNSAFE.search(route):
                continue

            # The query template is kept whole, `${...}` included. The command
            # fills the placeholders with real values at probe time; keeping the
            # template rather than the resolved path means the row prints as the
            # screen wrote it, which is what a reader is looking for.
            full = "/api" + route + (f"?{query}" if query else "")
            paths[full] = False

        if paths:
            pages[name] = paths
    return pages
