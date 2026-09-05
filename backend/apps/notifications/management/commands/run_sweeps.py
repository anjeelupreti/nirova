"""Run the notification sweeps for one tenant, or for every tenant.

Written as a management command so it can be a cron entry today and a task in
the automation engine (§98) later without the sweep itself changing.

Safe to run as often as you like: every sweep is keyed, so repeated runs
produce one notification per situation rather than one per run.
"""

from django.core.management.base import BaseCommand

from apps.notifications.sweeps import sweep_expiring_credentials
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization, OrganizationStatus


class Command(BaseCommand):
    help = "Raise and resolve notifications for dates that have moved."

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization",
            help="Slug of one organization. Omit to sweep every active tenant.",
        )
        parser.add_argument("--within-days", type=int, default=90)

    def handle(self, *args, **options):
        if options["organization"]:
            organizations = Organization.objects.filter(
                slug=options["organization"])
        else:
            organizations = Organization.objects.filter(
                status=OrganizationStatus.ACTIVE)

        for organization in organizations:
            with tenant_context(context_for_organization(organization)):
                report = sweep_expiring_credentials(options["within_days"])
            # Reported per tenant rather than summed. A total of zero across
            # forty tenants and a zero for one particular tenant are different
            # facts, and only the second one tells you where to look.
            self.stdout.write(
                f"  {organization.slug:20s} credentials: "
                f"checked {report['checked']}, raised {report['raised']}, "
                f"already standing {report['standing']}, "
                f"resolved {report['resolved']}"
            )
