"""Which endpoints no screen calls, and which screens call nothing that exists.

**Written after finding §20.** Provider schedules, slot generation, capacity,
overbooking, schedule exceptions, booking with double-book prevention,
cancellation, no-show — twelve ticked items of appointment management, and no
page in the console called any of it. A receptionist could not book an
appointment. The gap had been there for the whole life of the feature, and the
only symptom was that nobody ever used it.

`audit_screens` cannot find that, by construction: it starts from what the
screens call and asks whether it answers. An endpoint no screen calls is not in
its list at all. This command starts from the other end — the URL configuration
— and asks which parts of the API nothing reaches.

**A gap here is a question, not a fault.** Plenty of endpoints are legitimately
unreached: the patient portal has its own frontend, the platform console reads
the control plane, webhooks and health checks answer machines. So this reports
and groups, and the judgement stays with a person. What it removes is the
*noticing*, which took two years last time.

    manage.py audit_reach              # every unreached endpoint, by module
    manage.py audit_reach --module ot  # one module
    manage.py audit_reach --verbose    # list the reached ones too
"""

import re
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.urls import get_resolver

# Every file, not just the pages: `GlobalSearch` is a component and
# `useSession` is a hook, and neither would be seen by the per-page map.
from apps.common.screens import every_referenced_path

#: Prefixes whose consumer is deliberately not the staff console.
#:
#: Listed by name so that adding one is a decision somebody writes down -- the
#: same reason `test_invariants` keeps its unlinked-routes list. A silent
#: exclusion list is how a real gap gets filed as expected.
NOT_THE_CONSOLE = {
    "/api/portal/": "the patient portal has its own frontend",
    "/api/auth/": "authentication, called by the API client rather than a screen",
    "/api/platform/": "the SaaS console, read by platform staff",
    "/api/health": "health and readiness, answered to machines",
    "/api/ready": "health and readiness, answered to machines",
    "/api/schema": "the OpenAPI schema and its viewer",
    "/api/docs": "the OpenAPI schema and its viewer",
    "/api/redoc": "the OpenAPI schema and its viewer",
}

#: A named regex group as DRF's routers write them: `(?P<pk>[^/.]+)`.
#:
#: These are *raw regexes*, not path converters. The first version of this
#: command stripped only `<...>` and reported routes like
#: `/api/billing/^charges/(?P*[^/.]+)/` — not a path, matching nothing, so 784
#: endpoints looked unreached against a console that plainly works. A tool whose
#: output is obviously wrong is at least honest; one that is subtly wrong is the
#: danger, and this was one keystroke from being subtly wrong.
NAMED_GROUP = re.compile(r"\(\?P<[^>]+>[^)]*\)")

#: Path converters, as `path()` writes them.
CONVERTER = re.compile(r"<[^>]+>")


class Command(BaseCommand):
    help = "Report API endpoints that no screen calls."

    def add_arguments(self, parser):
        parser.add_argument("--module", help="Only paths containing this.")
        parser.add_argument(
            "--verbose", action="store_true", help="List reached endpoints too."
        )

    def handle(self, *args, **options):
        called = self._called_prefixes()
        registered = self._registered()

        unreached = defaultdict(list)
        reached = defaultdict(list)
        excused = defaultdict(list)

        for path in sorted(registered):
            if options.get("module") and options["module"] not in path:
                continue
            module = self._module_of(path)

            excuse = next(
                (why for prefix, why in NOT_THE_CONSOLE.items()
                 if path.startswith(prefix)),
                None,
            )
            if excuse:
                excused[excuse].append(path)
            elif self._is_called(path, called):
                reached[module].append(path)
            else:
                unreached[module].append(path)

        if options["verbose"]:
            for module in sorted(reached):
                self.stdout.write("")
                self.stdout.write(self.style.SUCCESS(f"{module} — reached"))
                for path in reached[module]:
                    self.stdout.write(f"    {path}")

        total_unreached = sum(len(paths) for paths in unreached.values())
        for module in sorted(unreached):
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(module))
            for path in unreached[module]:
                self.stdout.write(self.style.WARNING(f"    {path}"))

        self.stdout.write("")
        self.stdout.write(
            f"{sum(len(p) for p in reached.values())} endpoint(s) reached by a "
            f"screen, {total_unreached} not."
        )
        for why, paths in sorted(excused.items()):
            self.stdout.write(f"  {len(paths):>3} excused: {why}")
        if total_unreached:
            self.stdout.write("")
            self.stdout.write(
                "An unreached endpoint is a question, not a fault: it may be "
                "consumed by a job, a report or another service. What it must "
                "not be is a feature nobody can use."
            )

    # -- internals --------------------------------------------------------

    def _registered(self) -> set:
        """Every `/api/...` route the project serves, as a collection path.

        Detail routes are folded into their collection: `/patients/<uuid>/` is
        not a separate feature from `/patients/`, and listing both doubles the
        output without adding a finding.
        """
        paths = set()

        def walk(patterns, prefix=""):
            for entry in patterns:
                pattern = prefix + str(entry.pattern)
                if hasattr(entry, "url_patterns"):
                    walk(entry.url_patterns, pattern)
                    continue
                # DRF's format-suffix routes are the same endpoint with
                # `.json` on the end. Counting them doubles every router's
                # contribution to the output and adds no finding.
                if "format" in pattern:
                    continue

                cleaned = pattern.replace("\\.", ".").replace("^", "")
                cleaned = cleaned.replace("$", "")
                cleaned = NAMED_GROUP.sub("*", cleaned)
                cleaned = CONVERTER.sub("*", cleaned)
                cleaned = "/" + cleaned.lstrip("/")
                if not cleaned.startswith("/api/"):
                    continue
                paths.add(cleaned)

        walk(get_resolver().url_patterns)
        return paths

    def _called_prefixes(self) -> set:
        """Every distinct API path the console calls, normalised.

        Query strings and interpolated segments are dropped: what matters here
        is whether anything reaches the endpoint at all, not with which values.
        """
        called = set()
        for path in every_referenced_path():
            cleaned = path.split("?", 1)[0]
            cleaned = re.sub(r"\$\{[^}]*\}", "*", cleaned)
            called.add(cleaned.rstrip("/") + "/")
        return called

    def _is_called(self, registered: str, called: set) -> bool:
        """Whether any call the console makes reaches this route.

        Compared segment by segment with `*` matching anything, because a
        registered `/api/hr/leave/*/decide/` and a called `/api/hr/leave/*/decide/`
        agree while their raw strings need not.
        """
        target = registered.rstrip("/") + "/"
        for call in called:
            if self._same(target, call):
                return True
            # A call to a detail route implies the collection is reachable:
            # somebody got the identifier from somewhere.
            if call.startswith(target) or target.startswith(call):
                return True
        return False

    def _same(self, left: str, right: str) -> bool:
        first, second = left.strip("/").split("/"), right.strip("/").split("/")
        if len(first) != len(second):
            return False
        return all(
            a == b or a == "*" or b == "*" for a, b in zip(first, second)
        )

    def _module_of(self, path: str) -> str:
        parts = path.strip("/").split("/")
        return parts[1] if len(parts) > 1 else path
