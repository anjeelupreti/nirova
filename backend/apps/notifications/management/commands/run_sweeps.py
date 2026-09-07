"""Run the notification sweeps for one tenant, or for every tenant.

Written as a management command so it can be a cron entry today and a task in
the automation engine (§98) later without the sweep itself changing.

Safe to run as often as you like: every sweep is keyed, so repeated runs
produce one notification per situation rather than one per run.
"""

from django.core.management.base import BaseCommand

from apps.diagnostics.services import sweep_unacknowledged_criticals
from apps.notifications.reminders import run_all
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

            # Before the reminders, because this one is measured in minutes
            # while the rest are measured in days. A critical potassium nobody
            # has acknowledged is not a thing to look at tomorrow morning --
            # **this command needs a five-minute cron, not a nightly one**, and
            # the reminders are simply cheap enough to ride along with it.
            with tenant_context(context_for_organization(organization)):
                criticals = sweep_unacknowledged_criticals()
            if criticals["escalated"] or criticals["undeliverable"]:
                self.stdout.write(
                    f"  {organization.slug:20s} critical values: "
                    f"escalated {criticals['escalated']}"
                    + (f", UNDELIVERABLE {criticals['undeliverable']}"
                       if criticals["undeliverable"] else "")
                )
            if criticals["undeliverable"]:
                self.stderr.write(
                    f"  {organization.slug:20s} a critical result was "
                    f"escalated and there was nobody to tell."
                )

            with tenant_context(context_for_organization(organization)):
                reminders = run_all()
            for entry in reminders["reminders"]:
                self.stdout.write(
                    f"  {organization.slug:20s} {entry['reminder']:22s} "
                    f"considered {entry['considered']:4d}, "
                    f"raised {entry['raised']:3d}, "
                    f"standing {entry['standing']:3d}, "
                    f"resolved {entry['resolved']:3d}"
                    + (f"  UNDELIVERABLE {entry['undeliverable']}"
                       if entry["undeliverable"] else "")
                )
            # Said last and said loudly. A reminder running against forty
            # expiring batches and reaching nobody is a role assignment
            # somebody has to fix, and it looks exactly like success unless
            # this line exists.
            if reminders["undeliverable"]:
                self.stderr.write(
                    f"  {organization.slug:20s} "
                    f"{reminders['undeliverable']} reminder(s) had nobody to "
                    f"tell -- check who holds the permissions involved."
                )
            if reminders["broken"]:
                self.stderr.write(
                    f"  {organization.slug:20s} reminders that failed: "
                    + ", ".join(reminders["broken"])
                )
