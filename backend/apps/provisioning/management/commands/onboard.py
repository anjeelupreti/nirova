"""Take on a customer from the command line.

The same service the platform API calls, so there is one definition of what
onboarding means and not two that drift. Useful in its own right: an operator
migrating a customer in, or scripting a batch of them, should not have to
drive HTTP to do it — and this is also the only way to exercise the real
provisioning path in a test-shaped way, because `CREATE DATABASE` cannot run
inside the transaction pytest wraps every test in.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.common.exceptions import DomainError
from apps.provisioning.onboarding import DEFAULT_TRIAL_DAYS, onboard_organization
from apps.tenancy.models import BusinessType


class Command(BaseCommand):
    help = "Create a customer: organization, subscription, database, owner."

    def add_arguments(self, parser):
        parser.add_argument("slug", help="URL-safe short name, e.g. sunrise.")
        parser.add_argument("--legal-name", required=True)
        parser.add_argument(
            "--display-name",
            help="What staff see. Defaults to the legal name.",
        )
        parser.add_argument("--email", required=True, help="Billing contact.")
        parser.add_argument("--plan", required=True)
        parser.add_argument("--owner-email", required=True)
        parser.add_argument("--owner-name", required=True)
        parser.add_argument(
            "--business-type",
            default=BusinessType.CLINIC,
            choices=[value for value, _ in BusinessType.choices],
        )
        parser.add_argument("--trial-days", type=int, default=DEFAULT_TRIAL_DAYS)
        parser.add_argument("--province", default="")
        parser.add_argument("--district", default="")
        parser.add_argument("--phone", default="")

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Onboarding {options['slug']} on the {options['plan']} plan"
            )
        )
        self.stdout.write(
            "  This creates a database and runs every migration against it. "
            "It takes a while."
        )

        try:
            result = onboard_organization(
                slug=options["slug"],
                legal_name=options["legal_name"],
                display_name=options["display_name"] or options["legal_name"],
                primary_email=options["email"],
                plan_code=options["plan"],
                owner_email=options["owner_email"],
                owner_name=options["owner_name"],
                business_type=options["business_type"],
                trial_days=options["trial_days"],
                province=options["province"],
                district=options["district"],
                phone=options["phone"],
            )
        except DomainError as exc:
            # Re-raised as a CommandError so the shell gets a non-zero exit and
            # a readable line, rather than a traceback ending in a domain
            # exception nobody outside the codebase recognises.
            detail = f" ({exc.detail})" if exc.detail else ""
            raise CommandError(f"{exc.message}{detail}") from exc

        organization = result["organization"]
        owner = result["owner"]

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"  {organization.display_name} ({organization.slug})"
        ))
        self.stdout.write(f"    status        {organization.status}")
        self.stdout.write(f"    database      {result['database_status']}")
        self.stdout.write(f"    plan          {result['plan']}")
        self.stdout.write(f"    administrator {owner.email}")

        if not owner.has_usable_password():
            # The question the operator will be asked next, answered before
            # they have to ask it.
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "    They have no password yet. Send them a reset link; nobody "
                "here should know their credential."
            ))
