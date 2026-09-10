"""Open every screen's endpoints as every demo user, and report what breaks.

Written after a screenshot of the self-service screen showing "The submitted
data is not valid" over a half-rendered page. That turned out to be four
separate faults on one screen, none of which any test caught, because the
tests probe **one** endpoint per screen and the screens call eight.

**What this does that the test suite does not.** `test_nav.py` asks "does the
screen open for the role that can see it" and answers with a single probe.
This reads the *frontend source*, extracts every API path each page actually
calls, and hits all of them as each demo account. A screen is not working
because its first request succeeded.

**Read the output as a starting point, not a verdict.** A 403 here may be
correct -- a counter assistant should not read the employee directory -- so
the command reports rather than asserts, and the judgement about which
refusals are wrong stays with a person. What it removes is the *finding*.

    manage.py audit_screens                 # every screen, every demo user
    manage.py audit_screens --screen Queue  # one screen
    manage.py audit_screens --user doctor   # one account
    manage.py audit_screens --failures      # only what did not answer 2xx
"""

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client

#: Demo accounts, in the order a reviewer would think about them.
DEMO_USERS = ["owner", "doctor", "manager", "counter", "pharmacy"]

#: Paths whose call would change data. Read-only verbs only: an audit that
#: posted would be an audit that has to be cleaned up after.
UNSAFE = re.compile(
    r"/(create|approve|reject|void|cancel|close|open|start|complete|"
    r"dispense|check-in|check-out|call-next|decide|submit|issue|post|pay)/?$"
)


class Command(BaseCommand):
    help = "Call every endpoint each screen uses, as each demo user."

    def add_arguments(self, parser):
        parser.add_argument("--screen", help="Only this page, e.g. Queue.")
        parser.add_argument("--user", help="Only this demo account, e.g. doctor.")
        parser.add_argument("--org", default="manakamana")
        parser.add_argument(
            "--failures",
            action="store_true",
            help="Print only what did not answer 2xx.",
        )

    def handle(self, *args, **options):
        pages = self._paths_by_page(options.get("screen"))
        if not pages:
            self.stdout.write(self.style.ERROR("No frontend pages found."))
            return

        users = [options["user"]] if options.get("user") else DEMO_USERS
        clients = {}
        for name in users:
            client = self._client(f"{name}@{options['org']}.test", options["org"])
            if client is None:
                self.stdout.write(self.style.WARNING(f"  no account {name}@…"))
                continue
            clients[name] = client

        broken = 0
        inferred = 0
        for page, paths in sorted(pages.items()):
            rows = []
            for path in sorted(paths):
                only_inferred = paths[path]
                results = {}
                for name, client in clients.items():
                    results[name] = self._probe(client, path)
                worst = max(results.values())
                if options["failures"] and worst < 400:
                    continue
                rows.append((path, results, only_inferred))
                if worst >= 400:
                    # An inferred prefix is still probed and still shown -- a
                    # 500 there is worth seeing -- but it is not counted as a
                    # failure of the screen, because the screen never asks for
                    # it. Counting it made the headline number untrustworthy,
                    # and a number a reader discounts is worse than no number.
                    if only_inferred:
                        inferred += 1
                    else:
                        broken += 1

            if not rows:
                continue

            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(page))
            header = "    " + " ".join(f"{n[:6]:>6}" for n in clients)
            self.stdout.write(f"  {'endpoint':<46}{header}")
            for path, results, only_inferred in rows:
                cells = " ".join(self._cell(results[name]) for name in clients)
                label = f"~ {path}" if only_inferred else path
                self.stdout.write(f"  {label[:46]:<46}    {cells}")

        self.stdout.write("")
        self.stdout.write(
            self.style.ERROR(f"{broken} endpoint(s) failed for at least one user.")
            if broken
            else self.style.SUCCESS("Every endpoint answered for every user.")
        )
        if inferred:
            self.stdout.write(
                f"({inferred} marked ~ are collection prefixes of interpolated "
                f"detail routes, not calls the screen makes. Not counted.)"
            )

    # -- internals --------------------------------------------------------

    def _paths_by_page(self, only: str | None) -> dict:
        """Every `/api/...` path each page calls, read out of the source.

        Regex over the frontend rather than a hand-kept list, for the reason
        the nav probe map had to learn (log 236): a list maintained by hand
        drifts from the code, and it drifts silently.
        """
        root = Path(settings.BASE_DIR).parent / "frontend" / "src" / "pages"
        if not root.exists():
            return {}

        # The whole quoted path, interpolations included, so that a path built
        # with `${id}` can be told apart from one written out in full.
        call = re.compile(r"""api\.(?:get|post|patch|del|put)[^(]*\(\s*[`"']([^`"']*)""")

        pages = {}
        for file in sorted(root.rglob("*.tsx")):
            name = file.stem
            if only and only.lower() not in name.lower():
                continue

            #: path -> whether every sighting of it was a truncated detail
            #: route. Starts True and is cleared by the first literal sighting.
            paths: dict[str, bool] = {}
            for match in call.finditer(file.read_text(encoding="utf-8")):
                raw = match.group(1)
                if not raw.startswith("/"):
                    continue

                # **Truncation, made visible instead of silent.** The first
                # version of this regex stopped at `$`, so
                # `/payroll/payslips/${reference}/document/` was recorded and
                # probed as `/payroll/payslips/` -- a different endpoint with
                # a different permission. It then reported that endpoint's
                # entirely correct 403 as a failure of the screen. Several of
                # the 117 failures in the first full run were this, and each
                # one cost a real triage read.
                interpolated = "$" in raw
                path = raw.split("$", 1)[0] if interpolated else raw
                if interpolated:
                    # Keep only a clean collection prefix; a fragment like
                    # `/hr/leave/` from `/hr/leave/${ref}/decide/` is at least
                    # a real route, whereas `/hr/attendance/?from=` is not.
                    path = path.split("?", 1)[0]
                    if not path.endswith("/"):
                        continue

                if UNSAFE.search(path):
                    continue

                full = "/api" + path
                # A path seen literally anywhere on the page is a real call,
                # whatever else truncated to the same prefix.
                paths[full] = paths.get(full, True) and interpolated

            if paths:
                pages[name] = paths
        return pages

    def _client(self, email: str, org: str):
        from rest_framework_simplejwt.tokens import RefreshToken

        from apps.identity.models import User

        user = User.objects.filter(email=email).first()
        if user is None:
            return None
        return Client(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
            HTTP_X_ORGANIZATION=org,
            # A 500 should be reported as a 500, not raised out of the loop
            # and stop the audit at the first broken screen.
            raise_request_exception=False,
        )

    def _probe(self, client, path: str) -> int:
        try:
            return client.get(path).status_code
        except Exception:  # noqa: BLE001
            return 599

    def _cell(self, code: int) -> str:
        text = f"{code:>6}"
        if code < 300:
            return self.style.SUCCESS(text)
        if code < 400:
            return text
        if code in (401, 403):
            # Amber, not red: a refusal may be exactly right, and colouring it
            # as a fault trains the reader to ignore the column.
            return self.style.WARNING(text)
        return self.style.ERROR(text)
