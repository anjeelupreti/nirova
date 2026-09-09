"""Bring an empty database up to a working, populated system in one command.

This exists because "get Nirova running" was fifteen README lines that had to
be pasted in the right order, one of which silently depended on another. A
container cannot paste a README. `docker compose up` runs this.

Every step is idempotent -- `tests/test_seeds.py` proves it by running each
seed twice and asserting the second pass completes -- so this is safe to run
on every container start. It is not *fast* to run on every start, which is
what `--if-needed` is for.

**How "already done" is decided.** By asking the database, not by leaving a
file behind. A marker file has to live in a volume, and a volume can outlive
the database it describes: delete the Postgres volume and keep the state
volume, and the marker cheerfully reports that an empty database is fully
seeded. Reading the actual estate -- does the demo organization exist, and
does its tenant database contain patients -- cannot desync from the truth,
because it *is* the truth.
"""

import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, connections

from apps.tenancy.seeding import TENANT_SEEDS


class Command(BaseCommand):
    help = "Migrate, seed the catalogue, provision the demo tenant, and seed it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--if-needed",
            action="store_true",
            help="Skip the demo seeding if a populated demo tenant already exists.",
        )
        parser.add_argument(
            "--no-demo",
            action="store_true",
            help="Migrate and seed the catalogue only. No demo tenant, no data.",
        )
        parser.add_argument(
            "--wait-only",
            action="store_true",
            help="Wait for the database and then exit, migrating nothing.",
        )
        parser.add_argument(
            "--wait-for-db",
            type=int,
            default=0,
            metavar="SECONDS",
            help="Poll the control-plane database until it answers, then proceed.",
        )
        parser.add_argument(
            "--plan",
            default="enterprise",
            help=(
                "Plan to put the demo organization on. Defaults to enterprise "
                "so that every module can be demonstrated; see handle()."
            ),
        )
        parser.add_argument(
            "--slug",
            default="manakamana",
            help="Demo organization slug. Must match what seed_demo creates.",
        )

    def handle(self, *args, **options):
        # Checked first: `--wait-only` is a readiness probe and must behave
        # identically whether or not anything has been seeded.
        if options["wait_only"]:
            self._wait_for_db(options["wait_for_db"] or 60)
            return

        if options["wait_for_db"]:
            self._wait_for_db(options["wait_for_db"])

        started = time.monotonic()

        # The control plane first. Nothing else can be written until the
        # tables describing customers and plans exist. Both of these are fast
        # when there is nothing to do, so they run unconditionally -- skipping
        # them would mean a container that came up against a database one
        # migration behind and failed somewhere much less obvious.
        self._step("Migrating the control plane")
        call_command("migrate", verbosity=0, interactive=False)

        self._step("Seeding the plan catalogue")
        call_command("seed_catalog", verbosity=0)

        if options["no_demo"]:
            return self._done(started)

        if options["if_needed"] and self._demo_is_populated(options["slug"]):
            self.stdout.write(
                f"Demo tenant '{options['slug']}' already has data; "
                "skipping the seeds. Delete the postgres volume to rebuild it."
            )
            return self._done(started)

        # `seed_demo` is the only step that creates a database rather than
        # rows: it buys a plan and provisions the tenant. Everything after it
        # runs *inside* that tenant.
        # **Enterprise, not `seed_demo`'s own default of professional.**
        #
        # `seed_demo` picks professional deliberately: the Professional plan
        # excludes the hospital module, so its request to open a hospital
        # escalates to the platform instead of proceeding, and that escalation
        # is the thing that seed is demonstrating. Worth keeping -- run
        # `manage.py seed_demo --plan professional` to watch it.
        #
        # But a tenant with no hospital module cannot admit a patient, so
        # `seed_inpatient_demo` and everything downstream of it are refused by
        # the entitlement rule doing its job. A bootstrap whose purpose is a
        # system somebody can click through has to include the wards, the
        # theatre and the ICU, which means the demo tenant has to be entitled
        # to them.
        self._step(f"Provisioning the demo organization on '{options['plan']}'")
        call_command(
            "seed_demo", verbosity=0, slug=options["slug"], plan=options["plan"]
        )

        # Belt and braces. `seed_demo` migrates the tenant it provisions, but
        # a re-run against a tenant that predates newer migrations would
        # otherwise seed into an out-of-date schema and fail obscurely.
        self._step("Rolling migrations across every tenant")
        call_command("migrate_tenants", verbosity=0)

        for index, seed in enumerate(TENANT_SEEDS, start=1):
            self._step(f"[{index}/{len(TENANT_SEEDS)}] {seed}")
            call_command(seed, verbosity=0)

        self._done(started)

    # -- helpers ----------------------------------------------------------

    def _demo_is_populated(self, slug: str) -> bool:
        """Does a demo tenant exist *and* contain data?

        Two conditions, because they fail separately and mean different
        things. No organization means nothing has ever been provisioned. An
        organization whose tenant database has no patients means a previous
        bootstrap was interrupted between provisioning and seeding -- and that
        one must be finished, not skipped.

        Imports are local to the method: this command has to be importable and
        runnable before `migrate` has created any of these tables, and a
        module-level import of a model whose app is misconfigured turns a
        clear failure into an import error at startup.
        """
        from apps.patients.models import Patient
        from apps.tenancy.connections import context_for_organization
        from apps.tenancy.context import tenant_context
        from apps.tenancy.models import Organization

        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            return False

        from apps.tenancy.provisioning import database_exists

        # `exc` is bound outside the handler on purpose: Python deletes an
        # `except ... as exc` name when the block ends, and the message below
        # needs to say what actually went wrong.
        failure = ""
        try:
            with tenant_context(context_for_organization(organization)):
                return Patient.objects.exists()
        except Exception as exc:  # noqa: BLE001
            failure = str(exc)

        # **"I cannot reach it" is not "it is not there".**
        #
        # This used to report the failure and carry on into a full bootstrap,
        # which calls `provision_organization`, which cannot reach it either
        # -- and whose `except` writes `status=failed` and a last_error onto
        # the tenant. A *connectivity* problem was therefore escalated into a
        # tenant marked permanently broken, and it took a live incident to
        # notice: a backend container was reading a tenant row that named a
        # host only the host machine can resolve, and every restart re-broke a
        # database that was completely healthy.
        #
        # So the two are now told apart. If the database is on the server, the
        # problem is reaching it, and re-provisioning cannot help.
        record = getattr(organization, "database", None)
        if record is not None and database_exists(record.db_name):
            raise CommandError(
                f"Tenant database for '{slug}' exists but this process cannot "
                f"reach it ({failure}). Nothing has been changed. "
                "This is usually a host mismatch: the tenant row records a "
                f"hostname ({record.host}) that resolves somewhere else. "
                "Check with `manage.py recheck_tenants`, and repoint it with "
                "`manage.py retarget_tenants --host <name> --apply`."
            )

        self.stdout.write(
            self.style.WARNING(
                f"Demo tenant '{slug}' has no database ({failure}); "
                "running the full bootstrap."
            )
        )
        return False

    def _wait_for_db(self, seconds: int) -> None:
        """Block until the control plane answers, or give up loudly.

        Compose already gates startup on `pg_isready` via
        `depends_on: service_healthy`, so in the normal path this returns on
        the first attempt. It is here for `docker run` without compose, and
        for the window where Postgres accepts connections during its own
        first-boot initialisation and then restarts.
        """
        deadline = time.monotonic() + seconds
        attempt = 0
        while True:
            attempt += 1
            try:
                connections["default"].ensure_connection()
                self.stdout.write(f"Database answered on attempt {attempt}.")
                return
            except OperationalError as exc:
                if time.monotonic() >= deadline:
                    raise OperationalError(
                        f"Database did not answer within {seconds}s: {exc}"
                    ) from exc
                # `close()` matters: a failed connection is cached as failed,
                # and without it every later attempt re-reports the first error.
                connections["default"].close()
                time.sleep(1)

    def _step(self, message: str) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(f"==> {message}"))

    def _done(self, started: float) -> None:
        elapsed = time.monotonic() - started
        self.stdout.write(self.style.SUCCESS(f"Bootstrap complete in {elapsed:.0f}s."))
