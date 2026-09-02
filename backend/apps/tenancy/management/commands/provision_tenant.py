"""Create and provision one organization's database."""

from django.core.management.base import BaseCommand, CommandError

from apps.tenancy.models import Organization
from apps.tenancy.provisioning import provision_organization


class Command(BaseCommand):
    help = "Provision the tenant database for an organization."

    def add_arguments(self, parser):
        parser.add_argument("slug", help="Organization slug.")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"No organization with slug '{slug}'.")

        tenant_db = provision_organization(
            organization, verbosity=options.get("verbosity", 1)
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Provisioned {slug}: {tenant_db.db_name} ({tenant_db.status})"
            )
        )
