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

from django.core.management.base import BaseCommand
from django.test import Client

# The path extraction is shared with `audit_queries`, which needs the same
# answer to the same question. A second copy of that regex would drift from
# this one silently -- the exact failure it exists to prevent.
from apps.common.fixtures_for_audit import fill, resolve_values
from apps.common.screens import paths_by_page

#: Demo accounts, in the order a reviewer would think about them.
DEMO_USERS = ["owner", "doctor", "manager", "counter", "pharmacy"]


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
        pages = paths_by_page(options.get("screen"))
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

        # Real values for `?facility=${facility}` and the rest, resolved once
        # from the tenant. Without these the probe reaches the route with no
        # parameter, `get_object_or_404` answers 404, and a working endpoint is
        # reported as a missing one.
        #
        # Bound explicitly: the probes below get their tenant from the
        # `X-Organization` header through the middleware, but this runs in the
        # command's own process with no request behind it, so without a context
        # every one of these queries would go to the control plane and answer
        # nothing -- silently, which would put the audit right back where it
        # was.
        values = self._resolve_values(options["org"])

        broken = 0
        inferred = 0
        unprobeable = 0
        for page, paths in sorted(pages.items()):
            rows = []
            for path in sorted(paths):
                only_inferred = paths[path]
                target = fill(path, values) if "${" in path else path
                if target is None:
                    # A placeholder this tenant has no row for. Reported as
                    # unprobeable rather than guessed at: a made-up uuid would
                    # produce a 404 indistinguishable from a broken route.
                    unprobeable += 1
                    continue
                results = {}
                for name, client in clients.items():
                    results[name] = self._probe(client, target)
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
                    #
                    # 405 is the same kind of statement about the audit rather
                    # than the application: this command only ever sends GET,
                    # so "method not allowed" means the screen calls the path
                    # with a verb that is deliberately not probed -- `/quote/`,
                    # `/announce/`, `/read-all/`, `/invite/`. The `UNSAFE`
                    # pattern catches most of those by name, and a pattern
                    # listing verbs will always trail the routes somebody
                    # adds. The response code says it without a list.
                    if only_inferred or worst == 405:
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
                uncounted = only_inferred or max(results.values()) == 405
                label = f"~ {path}" if uncounted else path
                self.stdout.write(f"  {label[:46]:<46}    {cells}")

        self.stdout.write("")
        self.stdout.write(
            self.style.ERROR(f"{broken} endpoint(s) failed for at least one user.")
            if broken
            else self.style.SUCCESS("Every endpoint answered for every user.")
        )
        if unprobeable:
            self.stdout.write(
                f"({unprobeable} skipped: they need a value -- a facility, a "
                f"ward -- that this tenant has no row for.)"
            )
        if inferred:
            self.stdout.write(
                f"({inferred} marked ~ are not calls this command can make: "
                f"collection prefixes of interpolated detail routes, or paths "
                f"the screen reaches with a verb other than GET. Not counted.)"
            )

    # -- internals --------------------------------------------------------

    def _resolve_values(self, slug: str) -> dict:
        """Parameter values, read inside the tenant's own database."""
        from apps.tenancy.connections import context_for_organization
        from apps.tenancy.context import tenant_context
        from apps.tenancy.models import Organization

        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            return {}
        try:
            with tenant_context(context_for_organization(organization)):
                return resolve_values()
        except Exception as error:  # noqa: BLE001 - an unprovisioned tenant
            self.stdout.write(
                self.style.WARNING(f"  could not read parameter values: {error}")
            )
            return {}

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
