"""Point tenant databases at a different host or port.

`TenantDatabase` stores host and port per tenant rather than deriving them
from settings, deliberately: that is what lets one large customer be moved
onto its own database server without touching application code. This is the
command that performs that move -- and the everyday reason to reach for it is
smaller and more immediate.

**The everyday reason.** A tenant provisioned inside Docker records
`host="postgres"`, because that is the name the API container resolves. The
same Postgres is published on `localhost:5432`, so the *control plane* works
fine from the host -- but the moment a request touches a tenant, Django dials
`postgres` and the host cannot resolve it:

    psycopg.OperationalError: [Errno 11001] getaddrinfo failed

Nothing is broken. The row is describing a network the host is not on. Run
`manage.py retarget_tenants --host localhost` and the host can work against
the containers' database; `--host postgres` puts it back.

Dry by default. Moving where a tenant's data is read from is not something to
do because a command was typed slightly wrong, so it prints the plan and
changes nothing until `--apply`.
"""

from django.core.management.base import BaseCommand

from apps.tenancy.models import TenantDatabase


class Command(BaseCommand):
    help = "Repoint tenant database connections at a different host or port."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            help="New hostname, e.g. localhost or postgres.",
        )
        parser.add_argument("--port", help="New port.")
        parser.add_argument(
            "--only",
            help="Restrict to one organization slug. Default is every tenant.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write the change. Without it, this only reports.",
        )

    def handle(self, *args, **options):
        if not options["host"] and not options["port"]:
            self.stdout.write(
                self.style.ERROR("Give --host, --port, or both.")
            )
            return

        rows = TenantDatabase.objects.select_related("organization")
        if options["only"]:
            rows = rows.filter(organization__slug=options["only"])
        rows = list(rows.order_by("alias"))

        if not rows:
            self.stdout.write("No tenant databases match.")
            return

        changed = 0
        for row in rows:
            host = options["host"] or row.host
            port = options["port"] or row.port
            if (host, port) == (row.host, row.port):
                self.stdout.write(f"  {row.alias}: already {host}:{port}")
                continue

            self.stdout.write(
                f"  {row.alias}: {row.host}:{row.port} -> {host}:{port}"
            )
            changed += 1
            if options["apply"]:
                row.host = host
                row.port = port
                row.save(update_fields=["host", "port", "updated_at"])

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run: {changed} tenant(s) would move. "
                    "Add --apply to write it."
                )
            )
            return

        self.stdout.write(self.style.SUCCESS(f"\n{changed} tenant(s) moved."))
        if changed:
            # Aliases are registered into `connections` from these rows at
            # runtime, and a process that has already registered one keeps the
            # old settings for its lifetime.
            self.stdout.write(
                "Restart anything already running: a live process holds the "
                "connection settings it registered at startup."
            )
