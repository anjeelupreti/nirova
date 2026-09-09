"""Re-examine tenant databases and clear a status that is no longer true.

**Found by an incident rather than by reading.** The Postgres container went
away for a few hours during development. Every request that touched the demo
tenant failed, `TenantDatabase.status` was set to `failed` with
`last_error="Cannot reach tenant database"` — and when Postgres came back,
**nothing set it right again**. The database was healthy, fully migrated and
full of data; the tenant stayed unreachable because a row said so, and
`context_for_organization` refuses a failed tenant before it tries to connect.

That is correct behaviour on the way in — a tenant whose database is broken
should fail fast rather than time out on every query — and it is a trap on the
way out. `failed` was a one-way door with no handle on the inside. A hosted
system where a transient outage permanently strands a customer, and the only
repair is an UPDATE on the control plane, is one where every blip becomes a
support escalation.

So this asks each tenant database the only question that matters — **does it
answer?** — and moves the status to match reality in either direction. Safe to
run on a schedule; safe to run while things are broken.
"""

from django.core.management.base import BaseCommand
from django.db import connections

from apps.tenancy.models import TenantDatabase, TenantDatabaseStatus
from apps.tenancy.provisioning import database_exists


class Command(BaseCommand):
    help = "Check each tenant database and correct a status that has gone stale."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only", help="Restrict to one organization slug.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the corrections. Without it, this only reports.",
        )

    def handle(self, *args, **options):
        rows = TenantDatabase.objects.select_related("organization")
        if options["only"]:
            rows = rows.filter(organization__slug=options["only"])

        recovered = broken = unchanged = 0
        for tenant_db in rows.order_by("alias"):
            reachable, detail = self._probe(tenant_db)
            slug = tenant_db.organization.slug

            if reachable and tenant_db.status != TenantDatabaseStatus.READY:
                self.stdout.write(self.style.SUCCESS(
                    f"  {slug}: {tenant_db.status} -> ready (it answers)"
                ))
                recovered += 1
                if options["apply"]:
                    tenant_db.status = TenantDatabaseStatus.READY
                    tenant_db.last_error = ""
                    tenant_db.save(
                        update_fields=["status", "last_error", "updated_at"]
                    )

            elif not reachable and tenant_db.status == TenantDatabaseStatus.READY:
                # The other direction, and the reason this is not simply a
                # "clear the failed flag" command: a tenant recorded as ready
                # that stopped answering is worth surfacing before a user
                # finds it.
                self.stdout.write(self.style.ERROR(
                    f"  {slug}: ready -> failed ({detail})"
                ))
                broken += 1
                if options["apply"]:
                    tenant_db.status = TenantDatabaseStatus.FAILED
                    tenant_db.last_error = detail[:2000]
                    tenant_db.save(
                        update_fields=["status", "last_error", "updated_at"]
                    )
            else:
                self.stdout.write(f"  {slug}: {tenant_db.status}, unchanged")
                unchanged += 1

        self.stdout.write("")
        summary = f"{recovered} recovered, {broken} newly failed, {unchanged} unchanged"
        if options["apply"]:
            self.stdout.write(self.style.SUCCESS(summary))
        else:
            self.stdout.write(self.style.WARNING(
                f"Dry run: {summary}. Add --apply to write it."
            ))

    def _probe(self, tenant_db) -> tuple[bool, str]:
        """Does this database exist and answer a query?

        Both, because they fail differently. A dropped database and a database
        that exists but refuses connections are different incidents, and a
        check that only did the second would report "unreachable" for one that
        is simply gone.
        """
        try:
            if not database_exists(tenant_db.db_name):
                return False, f"{tenant_db.db_name} does not exist"
        except Exception as exc:  # noqa: BLE001
            return False, f"could not ask the server: {exc}"

        # `register_tenant_connection` adds the alias to Django's connection
        # handler at runtime; `check_tenant_connection` is the existing probe,
        # reused rather than reimplemented so that this command and the health
        # endpoint cannot disagree about what "reachable" means.
        from apps.tenancy.connections import (
            check_tenant_connection,
            register_tenant_connection,
        )

        try:
            alias = register_tenant_connection(tenant_db)
            if not check_tenant_connection(alias):
                return False, "registered but did not answer SELECT 1"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
        return True, ""
