"""Count the queries behind every screen's endpoints, and name the N+1s.

`audit_screens` answers "does this answer at all". This answers "what does it
cost", which is the question that decides whether the product works for a
hospital rather than for a demo tenant.

**Why this is measured and not reviewed.** An N+1 is invisible in the code that
causes it. `row.employee.full_name` in a serializer is one attribute access;
whether it is free or a query per row depends on a `select_related` written in
a different file, and nothing in either file says which. It is also invisible
in use: on the demo tenant with 30 patients every screen is instant, and the
same endpoint on a tenant with 30,000 takes a minute. The only honest way to
know is to count.

**How an N+1 is identified here.** Queries per returned row. A fixed cost --
session, membership, permission resolution, the count query pagination needs --
does not scale with rows, so it washes out as the row count grows; a cost that
scales shows up as a ratio that stays put. A ratio at or above
`SUSPECT_PER_ROW` with more than `MIN_ROWS` rows is reported, because below
that the fixed cost dominates and the ratio means nothing.

This is a heuristic, deliberately, and it says so in its output. A single probe
cannot prove growth -- proving it needs the same endpoint at two row counts,
which is what `--compare` does by asking for two page sizes and reporting
whether the query count moved.

**Unbounded responses are reported too**, and they matter as much. An endpoint
serialising a whole table with `many=True` and no paginator is fine on the demo
tenant and a timeout on a real one; there are 116 such sites in the codebase.
A response with no `count`/`next` envelope is flagged with its row count so
the ones that can grow without limit can be found and capped.

    manage.py audit_queries                    # every screen
    manage.py audit_queries --screen Wards     # one screen
    manage.py audit_queries --slowest 20       # the worst, ranked
    manage.py audit_queries --compare          # probe twice, prove growth
"""

import json
import time

from django.core.management.base import BaseCommand
from django.db import connections
from django.test import Client
from django.test.utils import CaptureQueriesContext

from apps.common.screens import paths_by_page

#: Queries per returned row at or above which an endpoint is worth a look.
#: 0.5 rather than 1.0 because a serializer that fetches one related object per
#: row every *other* row -- a nullable foreign key, say -- is the same defect
#: at half the cost, and because the fixed overhead pushes a genuine 1.0 below
#: itself at small row counts.
SUSPECT_PER_ROW = 0.5

#: Below this many rows the fixed cost of a request dominates and the ratio
#: says nothing. Twelve fixed queries over three rows is four per row and
#: perfectly healthy.
MIN_ROWS = 8

#: Queries above which an endpoint is worth a look whatever its row count.
#: A request issuing this many has usually fanned out over something.
SUSPECT_TOTAL = 40


class Command(BaseCommand):
    help = "Count queries and rows for every endpoint each screen calls."

    def add_arguments(self, parser):
        parser.add_argument("--screen", help="Only this page, e.g. Wards.")
        parser.add_argument("--org", default="manakamana")
        parser.add_argument(
            "--user",
            default="owner",
            help="Probe as this demo account. Defaults to the owner, who sees "
                 "the most rows and therefore the most queries.",
        )
        parser.add_argument(
            "--slowest",
            type=int,
            default=0,
            help="Print only the N endpoints with the most queries.",
        )
        parser.add_argument(
            "--compare",
            action="store_true",
            help="Probe each endpoint at two page sizes and report whether the "
                 "query count grew -- the difference between a suspicion and a "
                 "measurement.",
        )

    def handle(self, *args, **options):
        pages = paths_by_page(options.get("screen"))
        if not pages:
            self.stdout.write(self.style.ERROR("No frontend pages found."))
            return

        client = self._client(
            f"{options['user']}@{options['org']}.test", options["org"]
        )
        if client is None:
            self.stdout.write(
                self.style.ERROR(f"No account {options['user']}@{options['org']}.test")
            )
            return

        # **One throwaway request before any measurement.** The tenant's
        # database alias is registered by the request that first needs it, so
        # `connections` does not contain it until something has been through
        # the middleware -- and `_measure` builds its capture list from
        # `connections`. The very first endpoint measured was therefore having
        # only its control-plane queries counted: `/api/ipd/admissions/`
        # measured 6 queries as the first row of a run and 50 as a later one.
        # A measurement that depends on its position in the run is not a
        # measurement.
        client.get("/api/auth/me/")

        measurements = []
        for page, paths in sorted(pages.items()):
            for path in sorted(paths):
                # An inferred prefix is a different endpoint from the one the
                # screen calls, so measuring it would attribute a cost to a
                # screen that does not pay it.
                if paths[path]:
                    continue
                result = self._measure(client, path)
                if result is None:
                    continue
                result["page"] = page
                if options["compare"]:
                    result["growth"] = self._growth(client, path)
                measurements.append(result)

        if not measurements:
            self.stdout.write("Nothing measurable.")
            return

        self._report(measurements, options)

    # -- measuring --------------------------------------------------------

    def _measure(self, client, path: str) -> dict | None:
        """One GET, with every database touched counted.

        **Both connections, not just the tenant's.** Authentication, the
        membership lookup and permission resolution run against the control
        plane, so counting only the tenant connection would hide a per-row
        control-plane query -- which is exactly the N+1 `test_staff_admin`
        already had to catch once. A query is a round trip whichever database
        it is aimed at.
        """
        aliases = [alias for alias in connections if connections[alias].settings_dict]
        started = time.perf_counter()
        try:
            # Nested contexts, one per alias: `CaptureQueriesContext` forces a
            # debug cursor on the connection it wraps, and each connection
            # needs its own.
            captures = [CaptureQueriesContext(connections[a]) for a in aliases]
            for capture in captures:
                capture.__enter__()
            try:
                response = client.get(path)
            finally:
                for capture in reversed(captures):
                    capture.__exit__(None, None, None)
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(f"  {path}: {error}"))
            return None
        elapsed = (time.perf_counter() - started) * 1000

        if response.status_code >= 400:
            # A refusal costs almost nothing and measuring it would put a
            # misleadingly healthy row in the table. `audit_screens` is where
            # refusals belong.
            return None

        queries = sum(len(capture.captured_queries) for capture in captures)
        rows, paginated = self._shape(response)
        return {
            "path": path,
            "queries": queries,
            "rows": rows,
            "paginated": paginated,
            "ms": elapsed,
            "bytes": len(response.content),
        }

    def _shape(self, response) -> tuple[int, bool]:
        """How many rows came back, and whether anything bounds that number."""
        try:
            body = json.loads(response.content.decode() or "null")
        except ValueError:
            return 0, True  # not JSON: a document or a file, nothing to bound
        if isinstance(body, dict):
            if "results" in body and isinstance(body["results"], list):
                return len(body["results"]), "count" in body or "next" in body
            # **An endpoint that declares its own bound counts as bounded.**
            # Not every list is DRF-paginated: the manager queue gathers four
            # different kinds of request, caps each, and reports `returned` and
            # `truncated` alongside the true totals. That is a bound, stated
            # more honestly than a `next` link would state it, and an audit
            # that kept flagging it would be training its reader to ignore the
            # one finding here that cannot be settled automatically.
            if "truncated" in body or "returned" in body:
                return self._longest(body), True
            # A dashboard payload: one object, often with several lists inside
            # it. The largest list is the one that can grow.
            return self._longest(body), False
        if isinstance(body, list):
            return len(body), False
        return 0, True

    def _longest(self, body: dict) -> int:
        """The longest list in a payload -- the one that can grow."""
        return max(
            (len(value) for value in body.values() if isinstance(value, list)),
            default=0,
        )

    def _growth(self, client, path: str) -> str:
        """Probe small and large, and say whether the query count moved.

        The difference between "this ratio looks like an N+1" and "this is an
        N+1". A fixed cost answers the same number twice; a per-row cost does
        not.
        """
        joiner = "&" if "?" in path else "?"
        small = self._measure(client, f"{path}{joiner}page_size=2")
        large = self._measure(client, f"{path}{joiner}page_size=100")
        if not small or not large:
            return "—"
        if large["rows"] <= small["rows"]:
            return "same rows"  # the endpoint ignores page_size
        moved = large["queries"] - small["queries"]
        if moved <= 0:
            return "flat"
        return f"+{moved} over +{large['rows'] - small['rows']} rows"

    # -- reporting --------------------------------------------------------

    def _report(self, measurements: list[dict], options: dict) -> None:
        suspects = [
            row for row in measurements
            # **A measurement outranks the heuristic.** `--compare` probes the
            # same endpoint at two page sizes; "flat" means the query count did
            # not move when the rows did, which is the definition of not being
            # an N+1. Keeping such a row on the suspect list after measuring it
            # would be reporting a ratio over a fact -- `/api/ipd/beds/` sits
            # at 0.8/row after its fix purely because the fixed cost of a
            # request is spread over 16 rows.
            if row.get("growth") != "flat"
            and (
                row["queries"] >= SUSPECT_TOTAL
                or (
                    row["rows"] >= MIN_ROWS
                    and row["queries"] / row["rows"] >= SUSPECT_PER_ROW
                )
            )
        ]
        unbounded = [
            row for row in measurements
            if not row["paginated"] and row["rows"] >= MIN_ROWS
        ]

        shown = measurements
        if options["slowest"]:
            shown = sorted(
                measurements, key=lambda row: row["queries"], reverse=True
            )[: options["slowest"]]
            self.stdout.write("")
            self.stdout.write(
                self.style.MIGRATE_HEADING(
                    f"{options['slowest']} endpoints by query count"
                )
            )
            self._table(shown, options)
        else:
            for page in sorted({row["page"] for row in measurements}):
                rows = [row for row in measurements if row["page"] == page]
                self.stdout.write("")
                self.stdout.write(self.style.MIGRATE_HEADING(page))
                self._table(rows, options)

        self.stdout.write("")
        self.stdout.write(
            f"{len(measurements)} endpoints measured, "
            f"{sum(row['queries'] for row in measurements)} queries total."
        )

        # **Three findings, not one.** A ratio and a measurement are different
        # claims and lumping them together makes the strong one look like the
        # weak one. `growing` has been proved by probing twice; `unsettled` is
        # a ratio that could not be tested, either because --compare was not
        # asked for or because the endpoint ignores `page_size` -- a report
        # over every account cannot be asked for fewer rows, so its ratio
        # stays a suspicion however many times it is measured.
        growing = [row for row in suspects if row.get("growth", "").startswith("+")]
        unsettled = [row for row in suspects if row not in growing]

        def _listing(rows):
            for row in sorted(
                rows,
                key=lambda row: row["queries"] / max(row["rows"], 1),
                reverse=True,
            ):
                per = row["queries"] / row["rows"] if row["rows"] else 0
                growth = row.get("growth")
                suffix = f"  {growth}" if growth and growth != "—" else ""
                self.stdout.write(
                    f"  {row['path'][:52]:<52} {row['queries']:>4}q "
                    f"{row['rows']:>4} rows  {per:>5.1f}/row{suffix}"
                )

        if growing:
            self.stdout.write("")
            self.stdout.write(
                self.style.ERROR(
                    f"{len(growing)} endpoint(s) issue more queries as rows "
                    "grow. Measured, not inferred -- these are N+1s:"
                )
            )
            _listing(growing)

        if unsettled:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(unsettled)} endpoint(s) have a high query-to-row "
                    "ratio that could not be settled by probing twice. Read "
                    "them; the ratio may be fixed cost spread over few rows:"
                )
            )
            _listing(unsettled)

        if unbounded:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(unbounded)} endpoint(s) answered an unbounded list "
                    "-- no count or next, so nothing caps the response:"
                )
            )
            for row in sorted(unbounded, key=lambda r: r["rows"], reverse=True):
                self.stdout.write(
                    f"  {row['path'][:52]:<52} {row['rows']:>4} rows "
                    f"{row['bytes'] / 1024:>7.0f} KB"
                )

    def _table(self, rows: list[dict], options: dict) -> None:
        header = f"  {'endpoint':<52} {'q':>4} {'rows':>5} {'ms':>6} {'KB':>6}"
        if options["compare"]:
            header += "  growth"
        self.stdout.write(header)
        for row in rows:
            per = row["queries"] / row["rows"] if row["rows"] else 0
            line = (
                f"  {row['path'][:52]:<52} {row['queries']:>4} "
                f"{row['rows']:>5} {row['ms']:>6.0f} {row['bytes'] / 1024:>6.1f}"
            )
            if options["compare"]:
                line += f"  {row.get('growth', '—')}"
            if row.get("growth") != "flat" and (
                row["queries"] >= SUSPECT_TOTAL
                or (row["rows"] >= MIN_ROWS and per >= SUSPECT_PER_ROW)
            ):
                self.stdout.write(self.style.ERROR(line))
            elif not row["paginated"] and row["rows"] >= MIN_ROWS:
                self.stdout.write(self.style.WARNING(line))
            else:
                self.stdout.write(line)

    # -- plumbing ---------------------------------------------------------

    def _client(self, email: str, org: str):
        from rest_framework_simplejwt.tokens import RefreshToken

        from apps.identity.models import User

        user = User.objects.filter(email=email).first()
        if user is None:
            return None
        return Client(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
            HTTP_X_ORGANIZATION=org,
            raise_request_exception=False,
        )
