"""Roll migrations across every tenant database. Run on deploy."""

from django.core.management.base import BaseCommand

from apps.tenancy.provisioning import migrate_all_tenants


class Command(BaseCommand):
    help = "Apply pending migrations to all tenant databases."

    def handle(self, *args, **options):
        results = migrate_all_tenants(verbosity=0)
        for alias in results["migrated"]:
            self.stdout.write(self.style.SUCCESS(f"  migrated  {alias}"))
        for failure in results["failed"]:
            self.stdout.write(
                self.style.ERROR(f"  FAILED    {failure['alias']}: {failure['error']}")
            )
        self.stdout.write(
            f"{len(results['migrated'])} migrated, {len(results['failed'])} failed."
        )
